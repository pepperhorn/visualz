from concurrent.futures import ThreadPoolExecutor

import pytest

from visualz.state import Store


def test_atomic_immutable_restart(tmp_path):
    store = Store(tmp_path)
    snapshot = store.snapshot()
    events = []
    unsubscribe = store.subscribe(events.append)
    store.patch({"now_playing": {"song": "Song"}})
    with pytest.raises(TypeError):
        snapshot["now_playing"]["song"] = "bad"
    assert snapshot["now_playing"]["song"] == ""
    before = store.get()
    with pytest.raises(ValueError):
        store.patch({"settings": {"audio": {"left_channel": -1}}})
    assert store.get() == before
    assert len(events) == 1
    unsubscribe()
    store.close()
    restarted = Store(tmp_path)
    assert restarted.get() == before
    restarted.close()
    assert (tmp_path / "overlays/lower-third.json").exists()


def test_concurrent_writers(tmp_path):
    store = Store(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: store.patch({"now_playing": {f"v{n}": str(n)}}), range(40)))
    assert all(store.get()["now_playing"][f"v{n}"] == str(n) for n in range(40))
    store.close()


def test_hand_edited_overlay_is_validated(tmp_path, caplog):
    import json

    store = Store(tmp_path)
    store.close()
    path = tmp_path / "overlays/lower-third.json"
    template = json.loads(path.read_text())
    template["name"] = "Edited by hand"
    path.write_text(json.dumps(template))
    reloaded = Store(tmp_path)
    assert reloaded.get()["overlays"]["lower-third"]["name"] == "Edited by hand"
    reloaded.close()
    path.write_text("{invalid json")
    reloaded = Store(tmp_path)
    assert "Rejected overlay" in caplog.text
    assert reloaded.get()["overlays"]["lower-third"]["name"] == "Edited by hand"
    reloaded.close()


def test_b3_recovery_backup_defaults_and_status(tmp_path, caplog):
    store = Store(tmp_path, debounce=100)
    store.patch({"now_playing": {"song": "last good"}})
    store.flush()
    store.patch({"now_playing": {"song": "newer"}})
    store.close()
    (tmp_path / "state.json").write_text("{truncated")
    recovered = Store(tmp_path)
    assert recovered.get()["now_playing"]["song"] == "last good"
    assert recovered.runtime.status()["stage"]["state_recovered"] is True
    assert list(tmp_path.glob("state.json.corrupt-*"))
    assert "recover" in caplog.text
    recovered.close()
    (tmp_path / "state.json").write_text("[]")
    (tmp_path / "state.json.bak").write_text("{}")
    fallback = Store(tmp_path)
    assert fallback.get()["now_playing"]["song"] == ""
    assert fallback.runtime.status()["stage"]["state_recovered"] is True
    fallback.close()


def test_s3_slow_disk_never_holds_writer_lock(tmp_path, monkeypatch):
    from threading import Event, Thread
    import visualz.state

    store = Store(tmp_path, debounce=100)
    store.flush()
    entered, release, changed = Event(), Event(), Event()
    original = visualz.state.atomic_write
    written = []

    def slow(path, content):
        written.append(path)
        if path.name == "state.json":
            entered.set()
            assert release.wait(3)
        original(path, content)

    monkeypatch.setattr(visualz.state, "atomic_write", slow)
    store.patch({"now_playing": {"song": "first"}})
    flush = Thread(target=store.flush)
    flush.start()
    assert entered.wait(3)

    def update():
        store.patch({"now_playing": {"band": "second"}})
        changed.set()

    writer = Thread(target=update)
    writer.start()
    try:
        assert changed.wait(1), "transaction waited for disk IO"
        store.submit({"now_playing": {"extra": "queued without disk lock"}})
    finally:
        release.set()
        flush.join(3)
        writer.join(3)
        store.close()
    assert not any(
        path.parent.name in ("overlays", "scenes", "assets", "picture_sets") for path in written
    )
    restarted = Store(tmp_path)
    assert restarted.get()["now_playing"]["extra"] == "queued without disk lock"
    restarted.close()


def test_atomic_write_syncs_before_replace(tmp_path, monkeypatch):
    import os
    from visualz.state import atomic_write

    seen = []
    real_sync, real_replace = os.fsync, type(tmp_path).replace

    def sync(fd):
        seen.append("sync")
        return real_sync(fd)

    def replace(path, target):
        assert seen == ["sync", "sync"]
        seen.append("replace")
        return real_replace(path, target)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(type(tmp_path), "replace", replace)
    atomic_write(tmp_path / "settings.json", b"{}")
    assert seen == ["sync", "sync", "replace", "sync"]


def test_schema_invalid_hand_edit_keeps_last_good(tmp_path, caplog):
    import json

    store = Store(tmp_path)
    store.close()
    path = tmp_path / "overlays/lower-third.json"
    template = json.loads(path.read_text())
    template["texts"][0]["size"] = -100
    path.write_text(json.dumps(template))
    recovered = Store(tmp_path)
    assert recovered.get()["overlays"]["lower-third"]["texts"][0]["size"] == 48
    assert "Rejected overlay" in caplog.text
    recovered.close()
