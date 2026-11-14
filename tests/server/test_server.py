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
        id="test", name="Test", mode="kaleido", mode_params={}, look=store.get()["settings"]["look"]
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
