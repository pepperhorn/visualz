"""Validated overlay archives. Staging is private; failure publishes no files/state."""

import json
import math
import shutil
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZipFile
from io import BytesIO

from PIL import Image

from visualz.media import MAX_UPLOAD, ingest
from visualz.schema import validate


def references(value):
    if isinstance(value, str) and value.startswith("assets/"):
        return {value}
    if isinstance(value, dict):
        return set().union(set(), *(references(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(set(), *(references(v) for v in value))
    return set()


def checked_path(root, name):
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or not path.parts
        or path.parts[0] != "assets"
    ):
        raise ValueError("Invalid asset path")
    result = (root / name).resolve()
    if not result.is_relative_to((root / "assets").resolve()):
        raise ValueError("Asset path escapes data directory")
    return result


def loop_manifest(content):
    value = validate("logo_loop", json.loads(content))
    if not math.isclose(value["duration"], len(value["frames"]) / value["fps"], abs_tol=0.001):
        raise ValueError("Logo duration must match frame count / fps")
    return value


def import_archive(store, payload):
    root = store.data_dir
    with TemporaryDirectory(prefix="visualz-import-") as temporary:
        staging = Path(temporary)
        with ZipFile(BytesIO(payload)) as archive:
            members = archive.infolist()
            if len(members) > 300 or sum(m.file_size for m in members) > MAX_UPLOAD:
                raise ValueError("Archive exceeds expanded size or file count limit")
            if len({m.filename for m in members}) != len(members):
                raise ValueError("Duplicate archive entries")
            template = validate("overlay", json.loads(archive.read("template.json")))
            assets, manifests = {}, {}
            # Validate EVERY supplied file, including unreferenced ones, but retain
            # only referenced assets and the PNG frames a manifest actually lists.
            for member in members:
                if member.filename == "template.json":
                    continue
                checked_path(root, member.filename)
                if member.is_dir() or (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Only regular asset files are accepted")
                content = archive.read(member)
                suffix = PurePosixPath(member.filename).suffix.lower()
                if suffix == ".json":
                    manifests[member.filename] = loop_manifest(content)
                    continue
                if suffix in (".ttf", ".otf"):
                    kind = "font"
                elif suffix in (".mp4", ".webm", ".gif"):
                    kind = "logo"
                elif suffix in (".png", ".jpg", ".jpeg", ".webp"):
                    kind = "image"
                else:
                    raise ValueError("Unsupported archive asset type")
                assets[member.filename] = ingest(
                    staging, PurePosixPath(member.filename).name, content, kind
                )
            for name, manifest in manifests.items():
                directory = staging / "assets" / uuid4().hex
                directory.mkdir(parents=True)
                for frame in manifest["frames"]:
                    source_name = (PurePosixPath(name).parent / frame).as_posix()
                    if source_name not in assets:
                        raise ValueError("Manifest is missing a valid PNG frame")
                    source = staging / assets[source_name]["original"]
                    with Image.open(source) as image:
                        if image.format != "PNG":
                            raise ValueError("Logo frames must be PNG")
                        image.thumbnail((128, 128))
                        image.convert("RGBA").save(directory / frame)
                path = directory / "manifest.json"
                path.write_text(json.dumps(manifest))
                assets[name] = dict(
                    id=directory.name,
                    path=path.relative_to(staging).as_posix(),
                    original=None,
                    kind="logo",
                    name="manifest.json",
                    warnings=[],
                )
            refs = references(template)
            if not refs <= set(assets):
                raise ValueError("Archive is missing referenced assets")
            selected = {ref: assets[ref] for ref in refs}
            mapping = {ref: asset["path"] for ref, asset in selected.items()}

            def remap(value):
                if isinstance(value, str):
                    return mapping.get(value, value)
                if isinstance(value, dict):
                    return {k: remap(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [remap(v) for v in value]
                return value

            template = remap(template)
            validate("overlay", template)
            moved = []
            had_assets = (root / "assets").exists()
            try:
                (root / "assets").mkdir(exist_ok=True)
                for asset in selected.values():
                    source = staging / "assets" / asset["id"]
                    destination = root / "assets" / asset["id"]
                    # Publish fresh UUID directories only after all files pass checks.
                    if destination.exists():
                        raise ValueError("Asset destination already exists")
                    moved.append(destination)
                    shutil.copytree(source, destination)

                def commit(state):
                    if template["id"] in state["overlays"]:
                        template["id"] = uuid4().hex
                    state["overlays"][template["id"]] = template
                    state["assets"].update({a["id"]: a for a in selected.values()})

                store.transaction(commit)
            except Exception:
                for directory in moved:
                    shutil.rmtree(directory, ignore_errors=True)
                if not had_assets:
                    try:
                        (root / "assets").rmdir()
                    except OSError:
                        pass
                raise
            return template
