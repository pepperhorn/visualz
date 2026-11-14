import asyncio
import json
from io import BytesIO
from zipfile import ZipFile

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from visualz.server import create_app
from visualz.state import Store


async def next_state(ws):
    while True:
        message = await asyncio.wait_for(ws.receive_json(), 3)
        if message["type"] == "state":
            return message["state"]


async def test_sync_reconnect_and_rejection(api):
    client, store = api
    first, second = await client.ws_connect("/ws"), await client.ws_connect("/ws")
    assert await next_state(first) == await next_state(second)
    await first.send_json({"type": "patch", "patch": {"now_playing": {"song": "Live"}}})
    assert (await next_state(first))["now_playing"]["song"] == "Live"
    assert (await next_state(second))["now_playing"]["song"] == "Live"
    await second.close()
    second = await client.ws_connect("/ws")
    assert (await next_state(second))["now_playing"]["song"] == "Live"
    before = store.get()
    response = await client.patch("/api/state", json={"overlays": {"bad": {"id": "bad"}}})
    assert response.status == 400
    assert store.get() == before
    await first.close()
    await second.close()


async def test_crud_slides_scene_preview(api):
    client, store = api
    assert (await client.get("/control")).status == 200
    assert (await client.get("/api/schemas")).status == 200
    assert (await client.post("/api/overlays/next")).status == 200
    assert store.get()["active_overlay"] == "logo-bug"
    await client.post("/api/overlays/prev")
    assert store.get()["active_overlay"] == "title-card"
    await client.post("/api/overlays/order", json=["title-card", "logo-bug", "lower-third"])
    await client.post("/api/overlays/lower-third/live")
    assert store.get()["active_overlay"] == "lower-third"
    response = await client.get("/api/overlays/lower-third/preview")
    assert Image.open(BytesIO(await response.read())).size == (640, 360)
    scene = dict(
        id="test",
        name="Test",
        mode="kaleido",
        modes={"kaleido": {"params": {}, "quality": "medium"}},
        look=store.get()["settings"]["look"],
    )
    assert (await client.post("/api/scenes", json=scene)).status == 201
    assert (await client.post("/api/scenes/test/live")).status == 200
    assert store.get()["settings"]["mode"] == "kaleido"
    await client.delete("/api/scenes/test")
    assert store.get()["active_scene"] is None
    await client.post("/api/overlays/clear")
    assert store.get()["active_overlay"] is None


async def test_upload_export_import_fresh(api, tmp_path):
    client, store = api
    image = BytesIO()
    Image.new("RGB", (32, 32), "red").save(image, "PNG")
    form = FormData()
    form.add_field("file", image.getvalue(), filename="../../logo.png", content_type="image/png")
    response = await client.post("/api/assets?kind=image", data=form)
    assert response.status == 201
    asset = await response.json()
    assert asset["name"] == "logo.png"
    template = store.get()["overlays"]["logo-bug"]
    template["logo"] = dict(
        asset=asset["path"], corner="bottom-right", size=128, margin=20, opacity=1
    )
    await client.put("/api/overlays/logo-bug", json=template)
    exported = await (await client.get("/api/overlays/logo-bug/export")).read()
    fresh = Store(tmp_path / "fresh")
    async with TestClient(TestServer(create_app(fresh))) as other:
        response = await other.post("/api/overlays/import", data=exported)
        assert response.status == 201
        imported = await response.json()
        path = fresh.data_dir / imported["logo"]["asset"]
        assert path.read_bytes() == (store.data_dir / asset["path"]).read_bytes()
    fresh.close()


async def test_upload_bad_and_zip_escape(api):
    client, store = api
    form = FormData()
    form.add_field("file", b"not an image", filename="x.png")
    assert (await client.post("/api/assets", data=form)).status == 400
    archive = BytesIO()
    with ZipFile(archive, "w") as z:
        z.writestr("template.json", json.dumps(store.get()["overlays"]["logo-bug"]))
        z.writestr("assets/../../escaped", b"bad")
    assert (await client.post("/api/overlays/import", data=archive.getvalue())).status == 400
    assert not (store.data_dir.parent / "escaped").exists()


async def test_asset_escape(api):
    client, _ = api
    assert (await client.get("/assets/%2e%2e%2fsettings.json")).status in (400, 404)


@pytest.mark.parametrize(
    "path", ["/api/settings", "/api/now_playing", "/api/overlays", "/api/picture_sets"]
)
async def test_routes(api, path):
    client, _ = api
    assert (await client.get(path)).status == 200


async def test_upload_limit(api, monkeypatch):
    import visualz.server

    client, store = api
    monkeypatch.setattr(visualz.server, "MAX_UPLOAD", 10)
    form = FormData()
    form.add_field("file", b"x" * 11, filename="big.png")
    assert (await client.post("/api/assets", data=form)).status == 413
    assert store.get()["assets"] == {}


async def test_import_missing_asset_is_atomic(api):
    client, store = api
    before = store.get()
    template = before["overlays"]["logo-bug"].copy()
    template["logo"] = dict(
        asset="assets/missing.png", corner="bottom-right", size=128, margin=20, opacity=1
    )
    archive = BytesIO()
    with ZipFile(archive, "w") as z:
        z.writestr("template.json", json.dumps(template))
    assert (await client.post("/api/overlays/import", data=archive.getvalue())).status == 400
    assert store.get() == before


async def test_b1_worker_command_status_and_image_bridge(api):
    from threading import Thread, get_ident

    client, store = api
    calls = []
    store.runtime.register_command(
        "camera", "snap", lambda set_id: calls.append((set_id, get_ident()))
    )
    store.runtime.publish_status(
        "audio",
        {"devices": [{"id": "shared", "name": "XR18", "channels": 64}], "levels": {"level": 0.7}},
    )
    store.runtime.publish_status("camera", {"present": True, "latest": "camera-main"})
    store.runtime.publish_status(
        "stage",
        {
            "fps": 30,
            "gl_renderer": "VideoCore IV",
            "hardware_profile": "low",
            "resolution": [1280, 720],
            "hostname": "stage",
            "ip_addresses": ["192.0.2.1"],
        },
    )
    store.runtime.publish_image("camera-main", b"image-bytes", "image/jpeg")
    assert (
        await client.post(
            "/api/stage/command",
            json={"target": "camera", "name": "snap", "args": {"set_id": "crowd"}},
        )
    ).status == 202
    assert not calls
    thread = Thread(target=store.runtime.drain_commands)
    thread.start()
    thread.join()
    assert calls[0][0] == "crowd" and calls[0][1] != get_ident()
    status = await (await client.get("/api/stage/status")).json()
    assert status["audio"]["devices"][0]["channels"] == 64
    assert status["camera"]["latest"] == "camera-main"
    assert status["stage"]["state_recovered"] is False
    assert (await client.get("/api/stage/image/absent")).status == 404
    assert await (await client.get("/api/stage/image/camera-main")).read() == b"image-bytes"
    ws = await client.ws_connect("/ws")
    await next_state(ws)
    await ws.send_json(
        {"type": "command", "target": "camera", "name": "snap", "args": {"set_id": "ws"}}
    )
    while True:
        message = await asyncio.wait_for(ws.receive_json(), 3)
        if message["type"] == "command":
            assert message["accepted"]
            break
    store.runtime.drain_commands()
    assert calls[-1][0] == "ws"
    while True:
        message = await asyncio.wait_for(ws.receive_json(), 3)
        if message["type"] == "telemetry":
            assert message["stage"]["hardware_profile"] == "low"
            break
    await ws.close()
    for payload in (
        {"target": "missing", "name": "x", "args": {}},
        {"target": "camera", "name": "snap", "args": {}},
        {"target": 2, "name": "snap", "args": {}},
    ):
        response = await client.post("/api/stage/command", json=payload)
        assert response.status == 400 and (await response.json())["error"]


def template_archive(template, files):
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("template.json", json.dumps(template))
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


@pytest.mark.parametrize(
    "name,content",
    [
        ("logo.png", b"#!/bin/sh\n"),
        ("font.ttf", b"garbage"),
        ("manifest.json", b'{"fps":8,"duration":1,"frames":["../../etc/passwd"]}'),
    ],
)
async def test_b2_invalid_archive_is_atomic_including_unreferenced_files(api, name, content):
    client, store = api
    before = store.get()
    disk_before = {p for p in store.data_dir.rglob("*") if p.is_file()}
    payload = template_archive(before["overlays"]["logo-bug"], {f"assets/x/{name}": content})
    assert (await client.post("/api/overlays/import", data=payload)).status == 400
    assert store.get() == before
    assert {p for p in store.data_dir.rglob("*") if p.is_file()} == disk_before


async def test_frame_and_font_round_trip_and_no_original_export(api, tmp_path):
    from pathlib import Path

    fonts = list(Path("/usr/share/fonts").rglob("*.ttf"))
    if not fonts:
        pytest.skip("No test TTF installed")
    client, store = api
    template = store.get()["overlays"]["lower-third"]
    template["logo"] = dict(
        asset="assets/loop/manifest.json", corner="bottom-right", size=128, margin=20, opacity=1
    )
    template["texts"][0]["font_asset"] = "assets/font.ttf"
    frame = BytesIO()
    Image.new("RGBA", (256, 256), "red").save(frame, "PNG")
    files = {
        "assets/loop/manifest.json": json.dumps(
            {"fps": 8, "duration": 0.125, "frames": ["frame-0001.png"]}
        ),
        "assets/loop/frame-0001.png": frame.getvalue(),
        "assets/font.ttf": fonts[0].read_bytes(),
    }
    response = await client.post("/api/overlays/import", data=template_archive(template, files))
    assert response.status == 201
    imported = await response.json()
    assert len(store.get()["assets"]) == 2
    loop_path = store.data_dir / imported["logo"]["asset"]
    assert Image.open(loop_path.parent / "frame-0001.png").size == (192, 192)
    (loop_path.parent / "original-large.mp4").write_bytes(b"unreferenced original")
    exported = await (await client.get(f"/api/overlays/{imported['id']}/export")).read()
    with ZipFile(BytesIO(exported)) as archive:
        assert not any("original-large.mp4" in name for name in archive.namelist())
    fresh = Store(tmp_path / "fresh-loop")
    try:
        async with TestClient(TestServer(create_app(fresh))) as other:
            response = await other.post("/api/overlays/import", data=exported)
            assert response.status == 201
            again = await response.json()
            assert len(fresh.get()["assets"]) == 2
            assert (fresh.data_dir / again["texts"][0]["font_asset"]).exists()
            assert (fresh.data_dir / again["logo"]["asset"]).exists()
    finally:
        fresh.close()


async def test_import_downscales_and_drops_valid_unreferenced_files(api):
    client, store = api
    image = BytesIO()
    Image.new("RGB", (3000, 1000), "blue").save(image, "PNG")
    template = store.get()["overlays"]["logo-bug"]
    template["logo"] = dict(
        asset="assets/large.png", corner="bottom-right", size=128, margin=20, opacity=1
    )
    response = await client.post(
        "/api/overlays/import",
        data=template_archive(
            template, {"assets/large.png": image.getvalue(), "assets/unused.png": image.getvalue()}
        ),
    )
    assert response.status == 201
    imported = await response.json()
    assert Image.open(store.data_dir / imported["logo"]["asset"]).width == 2048
    assert len(store.get()["assets"]) == 1
    assert len(list((store.data_dir / "assets").iterdir())) == 1


async def test_missing_export_preview_assets_are_404(api):
    client, store = api
    for url in ("/api/overlays/absent/preview", "/api/overlays/absent/export"):
        assert (await client.get(url)).status == 404
    store.patch(
        {
            "overlays": {
                "logo-bug": {
                    "logo": dict(
                        asset="assets/missing.png",
                        corner="bottom-right",
                        size=128,
                        margin=20,
                        opacity=1,
                    )
                }
            }
        }
    )
    assert (await client.get("/api/overlays/logo-bug/export")).status == 404


async def test_references_palette_and_asset_deletion(api):
    from visualz.media import ingest

    client, store = api
    image = BytesIO()
    Image.new("RGB", (16, 16)).save(image, "PNG")
    asset = ingest(store.data_dir, "test.png", image.getvalue())
    store.patch({"assets": {asset["id"]: asset}, "settings": {"source_asset": asset["path"]}})
    response = await client.delete("/api/assets/" + asset["id"])
    assert response.status == 400 and "in use" in (await response.json())["error"]
    store.patch({"settings": {"source_asset": None}})
    assert (await client.delete("/api/assets/" + asset["id"])).status == 200
    assert not (store.data_dir / "assets" / asset["id"]).exists()
    assert (
        await client.patch("/api/settings", json={"look": {"palette": "missing"}})
    ).status == 400
    scene = dict(
        id="test",
        name="Test",
        mode="plasma",
        modes={},
        look=store.get()["settings"]["look"],
        picture_set="missing",
    )
    assert (await client.post("/api/scenes", json=scene)).status == 400
    scene.pop("picture_set")
    scene["source_asset"] = "assets/absent.png"
    assert (await client.post("/api/scenes", json=scene)).status == 400


async def test_picture_set_delete_clears_scene_and_active_references(api):
    client, store = api
    picture_set = dict(
        id="crowd",
        name="Crowd",
        items=[],
        order="sequential",
        fit="fill",
        transition="random",
        trigger="manual",
        interval=30,
        amount=0.5,
        camera=dict(
            enabled=True,
            device=None,
            interval=30,
            keep_count=12,
            save=False,
            mirror=False,
            rotation=0,
            brightness=0,
        ),
    )
    assert (await client.post("/api/picture_sets", json=picture_set)).status == 201
    scene = dict(
        id="crowd",
        name="Crowd",
        mode="gallery",
        modes={"gallery": {"params": {"amount": 0.8}, "quality": "low"}},
        look=store.get()["settings"]["look"],
        picture_set="crowd",
    )
    assert (await client.post("/api/scenes", json=scene)).status == 201
    await client.post("/api/scenes/crowd/live")
    assert "plasma" in store.get()["settings"]["modes"]
    assert store.get()["settings"]["modes"]["gallery"]["quality"] == "low"
    assert (await client.delete("/api/picture_sets/crowd")).status == 200
    assert store.get()["settings"]["picture_set"] is None
    assert store.get()["scenes"]["crowd"]["picture_set"] is None


async def test_b2_rollback_on_publish_failure(api, monkeypatch):
    client, store = api
    image = BytesIO()
    Image.new("RGB", (16, 16), "red").save(image, "PNG")
    template = store.get()["overlays"]["logo-bug"]
    template["logo"] = dict(
        asset="assets/a.png", corner="bottom-right", size=128, margin=20, opacity=1
    )

    def fail(change):
        raise ValueError("Publish rejected")

    monkeypatch.setattr(store, "transaction", fail)
    response = await client.post(
        "/api/overlays/import", data=template_archive(template, {"assets/a.png": image.getvalue()})
    )
    assert response.status == 400
    assert not [p for p in store.data_dir.rglob("*") if p.is_file()]
    assert not (store.data_dir / "assets").exists()


async def receive_type(ws, kind):
    while True:
        message = await asyncio.wait_for(ws.receive_json(), 3)
        if message["type"] == kind:
            return message


async def test_r2_1_telemetry_coercion_survives_tick_failure_and_restart(tmp_path, caplog):
    import numpy as np

    store = Store(tmp_path)

    class Custom:
        def __str__(self):
            return "custom-value"

    values = dict(
        beat=np.bool_(True),
        level=np.float32(0.5),
        spectrum=np.array([1, np.nan, np.inf]),
        extra=Custom(),
        pair=(1, 2),
        tags={3, 4},
    )
    store.runtime.publish_status("audio", values)
    store.runtime.publish_status("audio", values)
    store.runtime.publish_image(
        "latest", b"png", "image/png", metadata={"exposure": np.float32(0.25), "object": Custom()}
    )
    assert sum("audio.extra" in record.message for record in caplog.records) == 1
    calls = 0

    def telemetry():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("tick failure")
        if calls == 3:
            raise asyncio.CancelledError("unexpected child exit")
        # Defensive send-time path also sees fresh, unnormalised worker data.
        return {"audio": values, "images": store.runtime.status()["images"]}

    try:
        async with TestClient(TestServer(create_app(store, telemetry))) as client:
            ws = await client.ws_connect("/ws")
            first = await receive_type(ws, "telemetry")
            assert first["audio"]["beat"] is True
            assert first["audio"]["level"] == 0.5
            assert first["audio"]["spectrum"] == [1, None, None]
            assert first["audio"]["extra"] == "custom-value"
            assert first["images"]["latest"]["exposure"] == 0.25
            for _ in range(3):
                assert (await receive_type(ws, "telemetry"))["audio"]["pair"] == [1, 2]
            assert calls >= 6
            assert "Telemetry tick failed" in caplog.text
            assert "restarting" in caplog.text
            await ws.close()
    finally:
        store.close()


async def test_r2_3_5_command_ids_results_errors_and_overload(api):
    import numpy as np

    client, store = api
    store.runtime.register_command(
        "test", "value", lambda: {"beat": np.bool_(True), "array": np.array([np.nan, 2])}
    )

    def fail():
        raise ValueError("handler failed")

    store.runtime.register_command("test", "fail", fail)
    response = await client.post(
        "/api/stage/command",
        json={"target": "test", "name": "value", "args": {}, "id": "http-command"},
    )
    assert await response.json() == {"accepted": True, "id": "http-command"}
    store.runtime.drain_commands()
    result = await (await client.get("/api/stage/result/http-command")).json()
    assert result["id"] == "http-command" and result["value"] == {"beat": True, "array": [None, 2]}
    await client.post(
        "/api/stage/command",
        json={"target": "test", "name": "fail", "args": {}, "id": "http-failure"},
    )
    store.runtime.drain_commands()
    failed = await (await client.get("/api/stage/result/http-failure")).json()
    assert failed["id"] == "http-failure" and failed["error"] == "handler failed"
    ws = await client.ws_connect("/ws")
    await next_state(ws)
    await ws.send_json(
        {"type": "command", "target": "test", "name": "fail", "args": {}, "id": "ws-command"}
    )
    ack = await receive_type(ws, "command")
    assert ack["id"] == "ws-command"
    store.runtime.drain_commands()
    result = await receive_type(ws, "command_result")
    assert result["id"] == "ws-command" and result["error"] == "handler failed"
    for _ in range(128):
        store.runtime.enqueue_command({"target": "test", "name": "value", "args": {}})
    overloaded = await client.post(
        "/api/stage/command", json={"target": "test", "name": "value", "args": {}}
    )
    assert overloaded.status == 503 and overloaded.headers["Retry-After"] == "1"
    assert (
        await client.post(
            "/api/stage/command", json={"target": "unknown", "name": "value", "args": {}}
        )
    ).status == 400
    await ws.send_json(
        {"type": "command", "target": "test", "name": "value", "args": {}, "id": "retry"}
    )
    error = await receive_type(ws, "error")
    assert error["id"] == "retry" and error["status"] == 503
    await ws.close()


async def test_r2_2_high_frame_count_archive_import_and_export(api):
    client, store = api
    store.runtime.publish_status("stage", {"hardware_profile": "high"})
    template = store.get()["overlays"]["logo-bug"]
    template["logo"] = dict(
        asset="assets/loop/manifest.json", corner="bottom-right", size=512, margin=20, opacity=1
    )
    image = BytesIO()
    Image.new("RGBA", (1, 1), "red").save(image, "PNG")
    frames = [f"frame-{n:04d}.png" for n in range(300)]
    files = {f"assets/loop/{name}": image.getvalue() for name in frames}
    files["assets/loop/manifest.json"] = json.dumps(dict(fps=30, duration=10, frames=frames))
    response = await client.post("/api/overlays/import", data=template_archive(template, files))
    assert response.status == 201
    imported = await response.json()
    manifest = json.loads((store.data_dir / imported["logo"]["asset"]).read_text())
    assert len(manifest["frames"]) == 300 and manifest["fps"] == 30
    response = await client.get("/api/overlays/" + imported["id"] + "/export")
    assert response.status == 200
    with ZipFile(BytesIO(await response.read())) as archive:
        assert len(archive.namelist()) == 302
