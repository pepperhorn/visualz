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


def test_r2_3_command_budget_slow_handlers_and_failure(caplog):
    from visualz.state.runtime import Runtime
    import time

    runtime = Runtime()
    calls = []

    def slow():
        calls.append("slow")
        time.sleep(0.008)

    runtime.register_command("test", "slow", slow)
    runtime.register_command("test", "fast", lambda: calls.append("fast"))
    runtime.enqueue_command({"target": "test", "name": "slow", "args": {}, "id": "slow"})
    runtime.enqueue_command({"target": "test", "name": "fast", "args": {}})
    runtime.drain_commands(budget_ms=2)
    assert calls == ["slow"]
    status = runtime.status()["commands"]
    assert status["slow_handler"]["target"] == "test" and status["slow_handler"]["milliseconds"] > 5
    assert "Slow command handler" in caplog.text
    runtime.drain_commands()
    assert calls == ["slow", "fast"]


def test_r2_4_rejected_edits_preserved_and_reload(tmp_path):
    import json

    store = Store(tmp_path, debounce=100)
    store.flush()
    path = tmp_path / "overlays/lower-third.json"
    invalid = b'{"broken":true}'
    path.write_bytes(invalid)
    store.runtime.enqueue_command({"target": "overlays", "name": "reload", "args": {}})
    store.runtime.drain_commands()
    store._pending.join()
    store.patch({"overlays": {"title-card": {"name": "Changed"}}})
    store.flush()
    assert (tmp_path / "overlays/lower-third.invalid.json").read_bytes() == invalid
    assert (tmp_path / "overlays/lower-third.invalid.txt").read_text()
    assert (
        store.runtime.status()["stage"]["rejected_overlays"][0]["file"]
        == "lower-third.invalid.json"
    )
    valid = store.get()["overlays"]["lower-third"]
    valid["name"] = "Live hand edit"
    path.write_text(json.dumps(valid))
    store.reload_documents()
    store._pending.join()
    assert store.get()["overlays"]["lower-third"]["name"] == "Live hand edit"
    path.write_bytes(b"{second bad edit")
    store.reload_documents()
    store._pending.join()
    store.close()
    assert len(list((tmp_path / "overlays").glob("lower-third.invalid*.json"))) == 2
    restarted = Store(tmp_path)
    assert len(restarted.runtime.status()["stage"]["rejected_overlays"]) == 2
    assert restarted.get()["overlays"]["lower-third"]["name"] == "Live hand edit"
    restarted.close()


def test_r2_6_ordered_migration_and_future_version_recovery(tmp_path):
    import json
    from visualz.schema import defaults

    old = defaults()
    old.pop("schema_version")
    old["now_playing"]["song"] = "keep this"
    (tmp_path / "state.json").write_text(json.dumps(old))
    store = Store(tmp_path)
    assert store.get()["schema_version"] == 1
    assert store.get()["now_playing"]["song"] == "keep this"
    assert store.runtime.status()["stage"]["state_recovered"] is False
    store.close()
    newer = store.get()
    newer["schema_version"] = 999
    (tmp_path / "state.json").write_text(json.dumps(newer))
    recovered = Store(tmp_path)
    assert recovered.get()["schema_version"] == 1
    assert recovered.runtime.status()["stage"]["state_recovered"] is True
    quarantined = list(tmp_path.glob("state.json.corrupt-*"))
    assert json.loads(quarantined[0].read_text())["schema_version"] == 999
    recovered.close()


@pytest.mark.parametrize("collection", ["overlays", "scenes", "picture_sets"])
def test_r2_4_invalid_documents_survive_startup_and_flush(tmp_path, collection):
    directory = tmp_path / collection
    directory.mkdir()
    content = b'{"id":"mine","name":"unfinished"}'
    (directory / "mine.json").write_bytes(content)
    store = Store(tmp_path, debounce=100)
    store.patch({"now_playing": {"song": "changed"}})
    store.flush()
    assert (directory / "mine.invalid.json").read_bytes() == content
    assert (directory / "mine.invalid.txt").read_text()
    assert store.runtime.status()["stage"]["rejected_" + collection]
    store.close()


def test_r2_4_invalid_edit_between_reload_and_flush_is_preserved(tmp_path):
    store = Store(tmp_path, debounce=100)
    store.flush()
    path = tmp_path / "overlays/lower-third.json"
    content = b"not even JSON"
    path.write_bytes(content)
    store.patch({"overlays": {"lower-third": {"name": "API change"}}})
    store.flush()
    assert (path.parent / "lower-third.invalid.json").read_bytes() == content
    assert store.get()["overlays"]["lower-third"]["name"] == "API change"
    store.close()


def test_non_json_persistent_worker_values_are_rejected(tmp_path):
    import numpy as np

    store = Store(tmp_path)
    before = store.get()
    for value in (np.float32(0.5), float("nan"), object()):
        with pytest.raises(ValueError, match="finite JSON"):
            store.patch({"settings": {"modes": {"plasma": {"params": {"amount": value}}}}})
    assert store.get() == before
    store.close()


def test_semantic_hand_edit_is_preserved_before_flush(tmp_path):
    import json

    store = Store(tmp_path, debounce=100)
    scene = dict(
        id="test", name="Scene", mode="plasma", modes={}, look=store.get()["settings"]["look"]
    )
    store.patch({"scenes": {"test": scene}})
    store.flush()
    file = tmp_path / "scenes/test.json"
    edited = json.loads(file.read_text())
    edited["source_asset"] = "assets/missing.png"
    file.write_text(json.dumps(edited))
    store.patch({"scenes": {"test": {"name": "API rename"}}})
    store.flush()
    assert (
        json.loads((file.parent / "test.invalid.json").read_text())["source_asset"]
        == "assets/missing.png"
    )
    assert "source_asset" not in store.get()["scenes"]["test"]
    store.close()


def test_status_cycles_extended_numpy_and_bad_string_are_safe():
    import json
    import numpy as np
    from visualz.state.runtime import Runtime

    class BrokenString:
        def __str__(self):
            raise ValueError("broken string conversion")

    cyclic = []
    cyclic.append(cyclic)
    runtime = Runtime()
    runtime.publish_status(
        "test", {"extended": np.longdouble(0.5), "cycle": cyclic, "broken": BrokenString()}
    )
    snapshot = runtime.status()
    assert snapshot["test"]["extended"] == 0.5
    assert "BrokenString" in snapshot["test"]["broken"]
    json.dumps(snapshot, allow_nan=False)
