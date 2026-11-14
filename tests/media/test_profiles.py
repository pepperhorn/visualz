import json
import shutil
import subprocess
from io import BytesIO

import pytest
from PIL import Image

from visualz.media import ingest, reconvert, register_commands
from visualz.schema.profiles import media_options
from visualz.state import Store


@pytest.mark.parametrize("profile,expected", [("low", 2048), ("high", 4096)])
def test_r2_2_picture_profile_and_reconversion(tmp_path, profile, expected):
    data = BytesIO()
    Image.new("RGB", (4500, 1000), "red").save(data, "PNG")
    asset = ingest(tmp_path, "picture.png", data.getvalue(), profile=profile)
    assert Image.open(tmp_path / asset["path"]).width == expected
    regenerated = reconvert(tmp_path, asset, profile="high")
    assert Image.open(tmp_path / regenerated["path"]).width == 4096
    assert (tmp_path / asset["path"]).exists()  # live references are never broken


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable"
)
@pytest.mark.parametrize(
    "profile,size,fps,logo_size,logo_fps",
    [("low", (480, 270), 15, 192, 10), ("high", (1280, 720), 30, 512, 30)],
)
def test_r2_2_video_profile_parameters(tmp_path, profile, size, fps, logo_size, logo_fps):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=512x512:r=30",
            "-t",
            "0.2",
            "-c:v",
            "mpeg4",
            str(source),
        ],
        check=True,
    )
    data = source.read_bytes()
    clip = ingest(tmp_path, "clip.mp4", data, "clip", profile=profile)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(tmp_path / clip["path"])],
        capture_output=True,
        check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert (stream["width"], stream["height"]) == size
    assert stream["r_frame_rate"] == f"{fps}/1"
    logo = ingest(tmp_path, "logo.mp4", data, "logo", profile=profile)
    manifest = json.loads((tmp_path / logo["path"]).read_text())
    assert manifest["fps"] == logo_fps
    assert (
        max(Image.open((tmp_path / logo["path"]).parent / manifest["frames"][0]).size) == logo_size
    )


def test_r2_2_auto_resolution_and_registered_reconvert(tmp_path):
    store = Store(tmp_path)
    data = BytesIO()
    Image.new("RGB", (4500, 1000), "blue").save(data, "PNG")
    original = ingest(tmp_path, "original.png", data.getvalue())
    store.patch({"assets": {original["id"]: original}})
    assert media_options(store.snapshot()["settings"], store.runtime)["picture_size"] == 2048
    store.runtime.publish_status("stage", {"hardware_profile": "high"})
    assert media_options(store.snapshot()["settings"], store.runtime)["picture_size"] == 4096
    media = register_commands(store)
    store.runtime.enqueue_command(
        {"target": "media", "name": "reconvert", "args": {"asset_id": original["id"]}}
    )
    store.runtime.drain_commands()
    assert media.wait_idle(timeout=5)
    media.close()
    regenerated = store.runtime.status()["media"]["regenerated_asset"]
    assert Image.open(tmp_path / regenerated["path"]).width == 4096
    assert regenerated["id"] in store.get()["assets"]
    store.close()
