"""Conversions must not delay live controls or prevent process shutdown."""

import os
from pathlib import Path
import subprocess
import sys
from threading import Event
import time

import pytest
from PIL import Image

import visualz.media as media
from visualz.state import Store


def command(store, asset_id):
    accepted = store.runtime.enqueue_command(
        {"target": "media", "name": "reconvert", "args": {"asset_id": asset_id}}
    )
    store.runtime.drain_commands()
    result = store.runtime.command_result(accepted["id"])
    assert result["value"] == {"queued": True, "asset_id": asset_id}
    assert result["error"] is None


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def convert(args):
        Image.new("RGBA", (16, 16), "red").save(args[-1])

    monkeypatch.setattr(media, "run_ffmpeg", convert)
    store = Store(tmp_path)
    original = media.ingest(tmp_path, "logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>', "logo")
    store.patch({"assets": {original["id"]: original}})
    worker = media.register_commands(store)
    try:
        yield store, worker, original
    finally:
        worker.close()
        store.close()


def old_files(store, original):
    directory = store.data_dir / "assets" / original["id"]
    return {p.name: p.read_bytes() for p in directory.iterdir()}


def test_controls_apply_within_100ms_and_conversions_are_serial(setup, monkeypatch):
    store, worker, original = setup
    before = old_files(store, original)
    entered, release, landed = Event(), Event(), Event()
    outputs = []

    def slow_converter(args):
        outputs.append(Path(args[-1]))
        entered.set()
        assert release.wait(5)
        Image.new("RGBA", (16, 16), "blue").save(args[-1])

    monkeypatch.setattr(media, "run_ffmpeg", slow_converter)
    command(store, original["id"])
    try:
        assert entered.wait(2)
        command(store, original["id"])
        store.subscribe(lambda state: landed.set() if state["settings"]["blackout"]["enabled"] else None)
        started = time.monotonic()
        store.submit({"settings": {"blackout": {"enabled": True}}})
        assert landed.wait(0.1), "live control blocked behind media conversion"
        assert time.monotonic() - started < 0.1
        assert len(outputs) == 1
        assert not worker.wait_idle(timeout=0.01)
    finally:
        release.set()
    assert worker.wait_idle(timeout=3)
    assert len(outputs) == 2
    assert len({p.parent for p in outputs}) == 2
    assert all(p.parent.name != original["id"] for p in outputs)
    assert len(store.get()["assets"]) == 3
    assert old_files(store, original) == before
    assert store.runtime.status()["media"]["error"] is None


def test_failure_cleans_new_directory_and_worker_recovers(setup, monkeypatch):
    store, worker, original = setup
    before = old_files(store, original)
    partials = []

    def fail(args):
        path = Path(args[-1])
        path.write_bytes(b"partial")
        partials.append(path.parent)
        raise ValueError("fake conversion failure")

    monkeypatch.setattr(media, "run_ffmpeg", fail)
    command(store, original["id"])
    assert worker.wait_idle(timeout=3)
    assert "fake conversion failure" in store.runtime.status()["media"]["error"]
    assert not partials[0].exists()
    assert set(store.get()["assets"]) == {original["id"]}
    assert old_files(store, original) == before
    monkeypatch.setattr(media, "run_ffmpeg", lambda args: Path(args[-1]).write_bytes(b"new"))
    command(store, original["id"])
    assert worker.wait_idle(timeout=3)
    assert store.runtime.status()["media"]["error"] is None
    assert len(store.get()["assets"]) == 2


def test_close_kills_converter_discards_queue_and_cleans_partial(setup, monkeypatch):
    store, worker, original = setup
    before = old_files(store, original)
    ready = store.data_dir / "ready"
    entered = Event()
    partials = []

    def subprocess_converter(args):
        partials.append(Path(args[-1]).parent)
        entered.set()
        media._run_process(
            [sys.executable, "-c", """
import os, pathlib, sys, time
pathlib.Path(sys.argv[1]).write_bytes(b'partial')
pathlib.Path(sys.argv[2]).write_text(str(os.getpid()))
time.sleep(60)
""", args[-1], str(ready)],
            timeout=120,
        )

    monkeypatch.setattr(media, "run_ffmpeg", subprocess_converter)
    command(store, original["id"])
    assert entered.wait(2)
    deadline = time.monotonic() + 3
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()
    pid = int(ready.read_text())
    command(store, original["id"])
    started = time.monotonic()
    worker.close()
    assert time.monotonic() - started < 3
    assert worker.wait_idle(timeout=0.5)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert len(partials) == 1
    assert not partials[0].exists()
    assert old_files(store, original) == before
    assert set(store.get()["assets"]) == {original["id"]}
    assert "cancelled" in store.runtime.status()["media"]["error"]
    with pytest.raises(RuntimeError, match="closed"):
        worker.submit(original["id"])


def test_process_exits_with_uninterruptible_converter(tmp_path):
    # An uncooperative/native converter must not acquire the executor's implicit
    # interpreter-exit join. Its half-made directory stays unregistered on exit.
    script = """
import sys
from pathlib import Path
from threading import Event
import visualz.media as media
from visualz.state import Store
root = Path(sys.argv[1])
media.run_ffmpeg = lambda args: Path(args[-1]).write_bytes(b'old')
store = Store(root)
asset = media.ingest(root, 'logo.svg', b'<svg/>', 'logo')
store.patch({'assets': {asset['id']: asset}})
worker = media.register_commands(store)
entered = Event()
def hang(args):
    Path(args[-1]).write_bytes(b'partial')
    entered.set()
    Event().wait(60)
media.run_ffmpeg = hang
worker.submit(asset['id'])
assert entered.wait(2)
worker.close()
store.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, timeout=6
    )
    assert result.returncode == 0, result.stderr.decode()
    reopened = Store(tmp_path)
    try:
        assert len(reopened.get()["assets"]) == 1
        directories = [p for p in (tmp_path / "assets").iterdir() if p.is_dir()]
        assert len(directories) == 2
        assert any((p / "image.png").read_bytes() == b"partial" for p in directories)
    finally:
        reopened.close()


def test_bad_asset_does_not_stop_worker(setup):
    store, worker, original = setup
    for missing in (None, "missing"):
        worker.submit(missing)
        assert worker.wait_idle(timeout=2)
        assert store.runtime.status()["media"]["error"]
    command(store, original["id"])
    assert worker.wait_idle(timeout=2)
    assert store.runtime.status()["media"]["error"] is None
