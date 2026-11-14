"""Bounded, content-checked upload ingest. All outputs are beneath data/assets.

Logo loops use numbered RGBA PNG frames plus manifest.json; stream current/next
textures. Conversion defaults and caps come from schema.profiles.
Clips use silent MPEG4 MP4; originals are retained for profile reconversion.
"""

import json
from visualz.schema.profiles import profile_defaults
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


def ingest(
    data_dir,
    filename,
    content,
    kind="image",
    *,
    profile="low",
    clip_size=None,
    clip_fps=None,
    logo_size=None,
    logo_fps=None,
    logo_frames=None,
    picture_size=None,
):
    """Validate bytes and return asset metadata; failures remove partial outputs."""
    options = profile_defaults(profile)
    clip_size = tuple(clip_size or options["clip_size"])
    clip_fps = options["clip_fps"] if clip_fps is None else clip_fps
    logo_size = options["logo_size"] if logo_size is None else logo_size
    logo_fps = options["logo_fps"] if logo_fps is None else logo_fps
    logo_frames = options["logo_frames"] if logo_frames is None else logo_frames
    picture_size = options["picture_size"] if picture_size is None else picture_size
    if (
        len(clip_size) != 2
        or not all(isinstance(v, int) and 1 <= v <= cap for v, cap in zip(clip_size, (1920, 1080)))
        or not 1 <= clip_fps <= 60
        or not 1 <= logo_size <= 512
        or not 1 <= logo_fps <= 30
        or not isinstance(logo_frames, int)
        or not 1 <= logo_frames <= 300
        or not 1 <= picture_size <= 4096
    ):
        raise ValueError("Invalid media conversion limits")
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
                        f"scale={picture_size}:{picture_size}:force_original_aspect_ratio=decrease",
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
                    image.thumbnail((picture_size, picture_size))
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
                        f"scale={clip_size[0]}:{clip_size[1]}:force_original_aspect_ratio=decrease,"
                        f"pad={clip_size[0]}:{clip_size[1]}:(ow-iw)/2:(oh-ih)/2,fps={clip_fps}",
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
                        f"scale={logo_size}:{logo_size}:force_original_aspect_ratio=decrease,fps={logo_fps}",
                        "-frames:v",
                        str(min(logo_frames, int(10 * logo_fps))),
                        str(directory / "frame-%04d.png"),
                    ]
                )
                frames = sorted(p.name for p in directory.glob("frame-*.png"))
                if not frames:
                    raise ValueError("Logo contains no frames")
                output = directory / "manifest.json"
                output.write_text(
                    json.dumps(dict(fps=logo_fps, duration=len(frames) / logo_fps, frames=frames))
                )
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


def reconvert(data_dir, asset, **limits):
    """Regenerate an asset from retained original bytes; old paths remain valid.

    Background-worker API: returns new asset metadata. Caller atomically remaps
    references/metadata if taking it live, then can delete the obsolete asset.
    Imported manifest-only loops have no source video and cannot be reconverted.
    """
    from visualz.media.archive import checked_path

    if not asset.get("original"):
        raise ValueError("Asset has no retained original for reconversion")
    original = checked_path(Path(data_dir), asset["original"])
    return ingest(data_dir, asset["name"], original.read_bytes(), asset["kind"], **limits)


def register_commands(store):
    """Register a short media.reconvert(asset_id) handler that queues background work.

    Result acknowledgement says queued; final metadata/error is status.media.
    No references are switched automatically: T4 may apply regenerated_asset.
    """
    from visualz.schema.profiles import media_options

    def reconvert_command(asset_id):
        def work():
            try:
                asset = store.get()["assets"][asset_id]
                result = reconvert(
                    store.data_dir,
                    asset,
                    **media_options(store.snapshot()["settings"], store.runtime),
                )
                store.patch({"assets": {result["id"]: result}})
                store.runtime.publish_status("media", {"regenerated_asset": result, "error": None})
            except Exception as exc:
                store.runtime.publish_status("media", {"error": str(exc)})

        store.submit_task(work)
        return {"queued": True, "asset_id": asset_id}

    store.runtime.register_command("media", "reconvert", reconvert_command)
