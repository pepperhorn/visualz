"""Bounded, content-checked upload ingest. All outputs are beneath data/assets.

Logo loops use numbered RGBA PNG frames plus manifest.json (8 fps, <=80 frames, <=128 px each; stream individual textures).
Clips use silent MPEG4 MP4 at 480x270/15 fps; originals are retained for conversion.
"""

import json
import re
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from urllib.parse import unquote

from PIL import Image, ImageFont, UnidentifiedImageError

MAX_UPLOAD = 64 * 1024 * 1024
MAX_TEXTURE = 2048


def safe_name(name):
    return (
        re.sub(r"[^a-zA-Z0-9_.-]", "_", Path(unquote(name).replace("\\", "/")).name)[:100]
        or "upload"
    )


def run_ffmpeg(args):
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg is required for video conversion")
    try:
        result = subprocess.run(
            [
                "nice",
                "-n",
                "19",
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-threads",
                "1",
                *args[:-1],
                "-threads",
                "1",
                args[-1],
            ],
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Media conversion exceeded 120 seconds") from exc
    if result.returncode:
        raise ValueError(
            "Unsupported or invalid media: " + result.stderr.decode(errors="replace")[-500:]
        )


def ingest(data_dir, filename, content, kind="image"):
    """Validate bytes and return asset metadata; failures remove partial outputs."""
    if kind not in ("image", "logo", "clip", "font"):
        raise ValueError("Unknown asset kind")
    if not content or len(content) > MAX_UPLOAD:
        raise ValueError("Upload must contain 1 byte to 64 MiB")
    root = Path(data_dir)
    asset_id = uuid4().hex
    directory = root / "assets" / asset_id
    directory.mkdir(parents=True)
    name = safe_name(filename)
    original = directory / ("original-" + name)
    original.write_bytes(content)
    warnings = []
    try:
        suffix = Path(name).suffix.lower()
        if kind == "font":
            if suffix not in (".ttf", ".otf") or content[:4] not in (
                b"\x00\x01\x00\x00",
                b"OTTO",
                b"true",
            ):
                raise ValueError("Only valid TTF/OTF fonts are accepted")
            ImageFont.truetype(BytesIO(content), size=16)
            output = original
        elif kind == "image" or (kind == "logo" and suffix not in (".gif", ".mp4", ".webm")):
            if suffix == ".svg" and kind == "logo":
                # ffmpeg's librsvg decoder rasterises SVG without a web renderer.
                if (
                    b"<svg" not in content[:4096]
                    or b"<!ENTITY" in content
                    or b"<!DOCTYPE" in content
                ):
                    raise ValueError("Invalid SVG logo")
                output = directory / "image.png"
                run_ffmpeg(
                    [
                        "-i",
                        str(original),
                        "-vf",
                        "scale=1024:1024:force_original_aspect_ratio=decrease",
                        "-frames:v",
                        "1",
                        str(output),
                    ]
                )
            else:
                with Image.open(BytesIO(content)) as image:
                    if image.format not in ("JPEG", "PNG", "WEBP", "GIF"):
                        raise ValueError("Expected JPEG, PNG, WebP or GIF image")
                    if image.width * image.height > 32_000_000:
                        raise ValueError("Image exceeds 32 megapixel decode limit")
                    image.load()
                    image.thumbnail((MAX_TEXTURE, MAX_TEXTURE))
                    output = directory / "image.png"
                    image.convert("RGBA").save(output)
        else:
            if suffix not in (".mp4", ".webm", ".gif"):
                raise ValueError("Clips and logo loops must be MP4, WebM or GIF")
            # Probe content before conversion; a suffix alone never establishes type.
            if not shutil.which("ffprobe"):
                raise ValueError("ffprobe is required for video conversion")
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(original),
                ],
                capture_output=True,
                timeout=20,
            )
            if probe.returncode:
                raise ValueError("Invalid video or GIF")
            info = json.loads(probe.stdout)
            if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
                raise ValueError("Upload has no video stream")
            formats = set(info.get("format", {}).get("format_name", "").split(","))
            if not formats.intersection({"mov", "mp4", "matroska", "webm", "gif"}):
                raise ValueError("Expected MP4, WebM or GIF container")
            duration = float(info.get("format", {}).get("duration", 0))
            if kind == "clip":
                if duration > 60:
                    warnings.append("Clip trimmed to 60 seconds")
                output = directory / "clip.mp4"
                run_ffmpeg(
                    [
                        "-i",
                        str(original),
                        "-t",
                        "60",
                        "-an",
                        "-vf",
                        "scale=480:270:force_original_aspect_ratio=decrease,"
                        "pad=480:270:(ow-iw)/2:(oh-ih)/2,fps=15",
                        "-c:v",
                        "mpeg4",
                        "-q:v",
                        "5",
                        str(output),
                    ]
                )
            else:
                run_ffmpeg(
                    [
                        "-i",
                        str(original),
                        "-t",
                        "10",
                        "-an",
                        "-vf",
                        "scale=128:128:force_original_aspect_ratio=decrease,fps=8",
                        "-frames:v",
                        "80",
                        str(directory / "frame-%04d.png"),
                    ]
                )
                frames = sorted(p.name for p in directory.glob("frame-*.png"))
                if not frames:
                    raise ValueError("Logo contains no frames")
                output = directory / "manifest.json"
                output.write_text(json.dumps(dict(fps=8, duration=len(frames) / 8, frames=frames)))
        return dict(
            id=asset_id,
            path=output.relative_to(root).as_posix(),
            original=original.relative_to(root).as_posix(),
            kind=kind,
            name=name,
            warnings=warnings,
        )
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        subprocess.TimeoutExpired,
        ValueError,
    ) as exc:
        shutil.rmtree(directory)
        raise ValueError(f"Upload rejected: {exc}") from exc
