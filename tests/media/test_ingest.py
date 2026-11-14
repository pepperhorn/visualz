import json
import shutil
import subprocess
from io import BytesIO

import pytest
from PIL import Image

from visualz.media import MAX_UPLOAD, ingest


def image_bytes(size=(3000, 1000)):
    output = BytesIO()
    Image.new("RGB", size, "red").save(output, "PNG")
    return output.getvalue()


def test_image_downscale_and_bad_types(tmp_path):
    asset = ingest(tmp_path, "../../photo.png", image_bytes())
    assert asset["name"] == "photo.png"
    assert Image.open(tmp_path / asset["path"]).size == (2048, 683)
    with pytest.raises(ValueError):
        ingest(tmp_path, "font.ttf", b"not a font", "font")
    with pytest.raises(ValueError):
        ingest(tmp_path, "fake.png", b"not an image")
    with pytest.raises(ValueError, match="64 MiB"):
        ingest(tmp_path, "huge.png", b"x" * (MAX_UPLOAD + 1))


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable"
)
def test_video_and_logo(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=64x64:r=15",
            "-t",
            "1",
            "-c:v",
            "mpeg4",
            str(source),
        ],
        check=True,
    )
    content = source.read_bytes()
    clip = ingest(tmp_path, "source.mp4", content, "clip")
    assert (tmp_path / clip["original"]).read_bytes() == content
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(tmp_path / clip["path"])],
        capture_output=True,
        check=True,
    )
    video = json.loads(result.stdout)["streams"][0]
    assert (video["width"], video["height"]) == (480, 270)
    assert video["r_frame_rate"] == "15/1"
    logo = ingest(tmp_path, "logo.mp4", content, "logo")
    manifest = json.loads((tmp_path / logo["path"]).read_text())
    assert 0 < manifest["duration"] <= 10
    assert len(manifest["frames"]) <= 80


def test_gl_lifecycle_when_display_available():
    import os

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("No desktop display")
    from visualz.gl import Context, Framebuffer, Program, Quad, Texture, TEXTURED, api
    from visualz.render import PATTERN

    try:
        context = Context((128, 128), window=True)
    except RuntimeError as exc:
        pytest.skip(str(exc))
    try:
        program, quad = Program(PATTERN), Quad()
        texture = Texture((16, 16), Image.new("RGBA", (16, 16)))
        texture.update(bytes(16 * 16 * 4))
        fbo = Framebuffer((16, 16))
        program.use(time=1.0)
        quad.draw(program)
        import numpy as np

        gl = api()
        image = Image.new("RGBA", (4, 1))
        image.putdata([(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 255, 255)])
        strip = Texture((4, 1), image)
        strip.bind()
        for parameter in (gl.GL_TEXTURE_MIN_FILTER, gl.GL_TEXTURE_MAG_FILTER):
            gl.glTexParameteri(gl.GL_TEXTURE_2D, parameter, gl.GL_NEAREST)
        small, textured = Quad((-0.5, -0.5, 0.5, 0.5)), Program(TEXTURED)
        fbo.bind()
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        small.draw(textured, strip)
        pixels = np.zeros((16, 16, 4), dtype=np.uint8)
        gl.glReadPixels(0, 0, 16, 16, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixels)
        assert tuple(pixels[8, 4]) == (255, 0, 0, 255)
        assert tuple(pixels[8, 11]) == (255, 255, 255, 255)
        # An uploaded image is top-down; rendering its FBO texture onward must
        # preserve orientation rather than flipping on every feedback pass.
        vertical = Image.new("RGBA", (1, 2))
        vertical.putdata([(255, 0, 0, 255), (0, 0, 255, 255)])
        upload = Texture((1, 2), vertical)
        first, second = Framebuffer((16, 16)), Framebuffer((16, 16))
        normal, flipped = Quad(), Quad(flip_v=True)
        first.bind()
        normal.draw(textured, upload)
        second.bind()
        flipped.draw(textured, first.texture)
        pixels = np.zeros((16, 16, 4), dtype=np.uint8)
        gl.glReadPixels(0, 0, 16, 16, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixels)
        assert pixels[15, 8, 0] > 240 and pixels[15, 8, 2] < 15
        assert pixels[0, 8, 2] > 240 and pixels[0, 8, 0] < 15
        for resource in (
            normal,
            flipped,
            upload,
            first,
            second,
            small,
            textured,
            strip,
            fbo,
            texture,
            quad,
            program,
        ):
            resource.close()
    finally:
        context.close()


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable"
)
@pytest.mark.parametrize("extension", ["webm", "gif"])
def test_gallery_other_containers(tmp_path, extension):
    source = tmp_path / f"source.{extension}"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=64x64:r=15",
            "-t",
            "0.4",
            str(source),
        ],
        check=True,
    )
    asset = ingest(tmp_path, source.name, source.read_bytes(), "clip")
    assert (tmp_path / asset["path"]).stat().st_size > 0
    assert (tmp_path / asset["original"]).exists()


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable"
)
def test_duration_caps(tmp_path):
    source = tmp_path / "long.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=32x32:r=1",
            "-t",
            "61",
            "-c:v",
            "mpeg4",
            str(source),
        ],
        check=True,
    )
    content = source.read_bytes()
    clip = ingest(tmp_path, source.name, content, "clip")
    assert clip["warnings"] == ["Clip trimmed to 60 seconds"]
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(tmp_path / clip["path"])],
        capture_output=True,
        check=True,
    )
    assert float(json.loads(result.stdout)["format"]["duration"]) <= 60
    logo = ingest(tmp_path, source.name, content, "logo")
    manifest = json.loads((tmp_path / logo["path"]).read_text())
    assert len(manifest["frames"]) == 80
    assert manifest["duration"] == 10
    assert manifest["fps"] == 8
    frame = tmp_path / logo["path"]
    assert all(max(Image.open(frame.parent / name).size) <= 128 for name in manifest["frames"])


def test_conversion_uses_low_priority_and_one_thread(monkeypatch):
    import visualz.media

    seen = []

    def run(args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(visualz.media.subprocess, "run", run)
    monkeypatch.setattr(visualz.media.shutil, "which", lambda name: "/usr/bin/" + name)
    visualz.media.run_ffmpeg(["-i", "input.mp4", "output.mp4"])
    assert seen[0][:4] == ["nice", "-n", "19", "ffmpeg"]
    assert seen[0].count("-threads") == 2
    assert all(seen[0][n + 1] == "1" for n, arg in enumerate(seen[0]) if arg == "-threads")
