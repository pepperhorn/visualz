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


@pytest.mark.parametrize("collection", ["overlays", "scenes", "picture_sets"])
@pytest.mark.parametrize("earlier_save", [False, True], ids=["first-save", "after-save"])
@pytest.mark.parametrize("invalid_edit", [False, True], ids=["valid-file", "invalid-edit"])
def test_deleted_document_stays_deleted_after_restart(
    tmp_path, collection, earlier_save, invalid_edit
):
    seed = Store(tmp_path, debounce=100)
    state = seed.get()
    documents = {
        "overlays": dict(state["overlays"]["lower-third"], id="delete-me"),
        "scenes": dict(
            id="delete-me", name="Scene", mode="plasma", modes={}, look=state["settings"]["look"]
        ),
        "picture_sets": dict(
            id="delete-me", name="Pictures", items=[], order="sequential", fit="fill",
            transition="random", trigger="seconds", interval=30, amount=0.5,
            camera=dict(
                enabled=False, device=None, interval=30, keep_count=12, save=False,
                mirror=False, rotation=0, brightness=0,
            ),
        ),
    }
    seed.patch({collection: {"delete-me": documents[collection]}})
    seed.close()
    path = tmp_path / collection / "delete-me.json"
    assert path.exists()

    store = Store(tmp_path, debounce=100)
    try:
        assert "delete-me" in store.get()[collection]
        if earlier_save:
            store.patch({"now_playing": {"song": "Earlier save"}})
            store.flush()
        if invalid_edit:
            path.write_bytes(b"{unfinished hand edit")
        store.transaction(lambda state: state[collection].pop("delete-me"))
        store.flush()
        assert "delete-me" not in store.get()[collection]
        assert not path.exists()
        if invalid_edit:
            assert path.with_name("delete-me.invalid.json").read_bytes() == b"{unfinished hand edit"
            assert path.with_name("delete-me.invalid.txt").read_text()
    finally:
        store.close()

    restarted = Store(tmp_path)
    try:
        assert "delete-me" not in restarted.get()[collection]
        assert not path.exists()
        if invalid_edit:
            assert restarted.runtime.status()["stage"]["rejected_" + collection]
            assert path.with_name("delete-me.invalid.json").read_bytes() == b"{unfinished hand edit"
    finally:
        restarted.close()


@pytest.mark.parametrize("rename", [False, True], ids=["same-content", "corrected-content"])
def test_quarantined_overlay_replacement_survives_later_save(tmp_path, rename):
    import json

    store = Store(tmp_path, debounce=100)
    path = tmp_path / "overlays/lower-third.json"
    try:
        store.flush()
        original = path.read_bytes()
        path.write_bytes(b"{unfinished hand edit")
        store.patch({"overlays": {"title-card": {"name": "Trigger quarantine"}}})
        store.flush()
        assert not path.exists()
        rejected = path.with_name("lower-third.invalid.json")
        assert rejected.read_bytes() == b"{unfinished hand edit"

        store.transaction(lambda state: state["overlays"].pop("lower-third"))
        store.flush()
        corrected = json.loads(original)
        if rename:
            corrected["name"] = "Corrected hand edit"
        content = json.dumps(corrected).encode()
        path.write_bytes(content)
        store.patch({"overlays": {"title-card": {"name": "Next save"}}})
        store.flush()
        assert path.read_bytes() == content
        assert rejected.read_bytes() == b"{unfinished hand edit"
        store.reload_documents()
        store._pending.join()
        assert store.get()["overlays"]["lower-third"] == corrected
    finally:
        store.close()


@pytest.mark.parametrize("earlier_save", [False, True], ids=["first-save", "after-save"])
def test_changed_overlay_ui_delete_wins_and_preserves_conflict(tmp_path, earlier_save):
    import json

    seed = Store(tmp_path)
    seed.close()
    path = tmp_path / "overlays/lower-third.json"
    store = Store(tmp_path, debounce=100)
    try:
        if earlier_save:
            store.flush()
        edited = dict(store.get()["overlays"]["lower-third"], name="External replacement")
        content = json.dumps(edited).encode()
        path.unlink()
        path.write_bytes(content)
        store.transaction(lambda state: state["overlays"].pop("lower-third"))
        store.flush()
        assert not path.exists()
        conflict = path.with_name("lower-third.invalid.json")
        assert conflict.read_bytes() == content
        assert "conflicted" in conflict.with_suffix(".txt").read_text()
        store.reload_documents()
        store._pending.join()
        assert "lower-third" not in store.get()["overlays"]
    finally:
        store.close()
    restarted = Store(tmp_path)
    try:
        assert "lower-third" not in restarted.get()["overlays"]
        assert not path.exists()
        entry = restarted.runtime.status()["stage"]["rejected_overlays"][0]
        assert entry["kind"] == "conflict" and entry["resolved"] is False
    finally:
        restarted.close()


def test_rejections_capped_newest_and_publication_cannot_break_startup(tmp_path, monkeypatch):
    import os
    from visualz.state.runtime import Runtime

    directory = tmp_path / "overlays"
    directory.mkdir()
    for index in range(1000):
        path = directory / f"edit.invalid-{index}.json"
        path.write_text("{}")
        os.utime(path, ns=(index + 1, index + 1))
    store = Store(tmp_path, debounce=100)
    try:
        status = store.runtime.status()["stage"]
        assert status["rejected_overlays_total"] == 1000
        files = status["rejected_overlays"]
        assert len(files) == 50
        assert files[0]["file"] == "edit.invalid-999.json"
        assert files[-1]["file"] == "edit.invalid-950.json"
        assert all(entry["resolved"] is False for entry in files)
    finally:
        store.close()

    publish = Runtime.publish_status

    def fail_rejections(self, target, values):
        if any(key.startswith("rejected_") for key in values):
            raise ValueError("status unavailable")
        return publish(self, target, values)

    monkeypatch.setattr(Runtime, "publish_status", fail_rejections)
    store = Store(tmp_path)
    store.close()


def test_dismiss_rejected_pair_and_resolved_status(tmp_path, monkeypatch):
    from threading import current_thread
    from pathlib import Path

    store = Store(tmp_path, debounce=100)
    try:
        store.flush()
        directory = tmp_path / "overlays"
        rejected = directory / "lower-third.invalid.json"
        rejected.write_text("bad")
        rejected.with_suffix(".txt").write_text("bad JSON")
        other = directory / "title-card.invalid.json"
        other.write_text("other")
        other.with_suffix(".txt").write_text("keep")
        store._refresh_rejections("overlays")
        store._publish_rejections("overlays")
        entries = store.runtime.status()["stage"]["rejected_overlays"]
        assert all(entry["resolved"] for entry in entries)
        unlink = Path.unlink

        def worker_unlink(path, *args, **kwargs):
            assert current_thread() is store._worker
            return unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", worker_unlink)
        store.runtime.enqueue_command(dict(
            target="overlays", name="dismiss_rejected", id="dismiss",
            args=dict(collection="overlays", file=rejected.name),
        ))
        store.runtime.drain_commands()
        assert store.runtime.command_result("dismiss")["value"] == {"queued": True}
        store._pending.join()
        assert not rejected.exists() and not rejected.with_suffix(".txt").exists()
        assert other.read_text() == "other" and other.with_suffix(".txt").read_text() == "keep"
        assert (directory / "lower-third.json").exists()
        assert store.runtime.status()["stage"]["rejected_overlays_total"] == 1
    finally:
        store.close()


@pytest.mark.parametrize("collection,file", [
    ("overlays", "../x"), ("overlays", "/tmp/x.invalid.json"),
    ("overlays", "lower-third.json"), ("overlays", "../scenes/x.invalid.json"),
    ("overlays", "x\\invalid.json"), ("overlays", "x..invalid.json"),
    ("assets", "x.invalid.json"), ("../scenes", "x.invalid.json"),
])
def test_dismiss_rejected_refuses_unsafe_names(tmp_path, collection, file):
    store = Store(tmp_path, debounce=100)
    try:
        store.flush()
        before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        store.runtime.enqueue_command(dict(
            target="overlays", name="dismiss_rejected", id="bad",
            args=dict(collection=collection, file=file),
        ))
        store.runtime.drain_commands()
        store._pending.join()
        assert store.runtime.command_result("bad")["error"]
        assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    finally:
        store.close()


@pytest.mark.parametrize("first_save", [True, False])
def test_valid_hand_edit_survives_different_overlay_save(tmp_path, first_save):
    import json

    seed = Store(tmp_path)
    seed.close()
    store = Store(tmp_path, debounce=100)
    path = tmp_path / "overlays/lower-third.json"
    try:
        if not first_save:
            store.flush()
        edited = dict(store.get()["overlays"]["lower-third"], name="Hand edited")
        content = json.dumps(edited).encode()
        path.write_bytes(content)
        store.patch({"overlays": {"title-card": {"name": "UI edit"}}})
        store.flush()
        assert path.read_bytes() == content
        assert store.get()["overlays"]["lower-third"] == edited
        store.reload_documents()
        store._pending.join()
        assert store.get()["overlays"]["lower-third"] == edited
    finally:
        store.close()
    restarted = Store(tmp_path)
    try:
        assert restarted.get()["overlays"]["lower-third"] == edited
    finally:
        restarted.close()


@pytest.mark.parametrize("first_save", [True, False])
def test_same_overlay_conflict_keeps_ui_and_quarantines_hand_edit(tmp_path, first_save):
    import json

    seed = Store(tmp_path)
    seed.close()
    store = Store(tmp_path, debounce=100)
    path = tmp_path / "overlays/lower-third.json"
    try:
        if not first_save:
            store.flush()
        edited = dict(store.get()["overlays"]["lower-third"], name="Hand edited")
        content = json.dumps(edited).encode()
        path.write_bytes(content)
        store.patch({"overlays": {"lower-third": {"name": "UI edit"}}})
        store.flush()
        assert json.loads(path.read_bytes())["name"] == "UI edit"
        rejected = path.with_name("lower-third.invalid.json")
        assert rejected.read_bytes() == content
        assert "conflicted" in rejected.with_suffix(".txt").read_text()
        entry = store.runtime.status()["stage"]["rejected_overlays"][0]
        assert entry["kind"] == "conflict" and entry["resolved"] is False
        assert store.get()["overlays"]["lower-third"]["name"] == "UI edit"
    finally:
        store.close()


def test_failed_reload_does_not_claim_hand_dropped_file(tmp_path, monkeypatch):
    import json

    store = Store(tmp_path, debounce=100)
    try:
        store.flush()
        path = tmp_path / "overlays/lower-third.json"
        edited = dict(store.get()["overlays"]["lower-third"], name="Failed reload edit")
        content = json.dumps(edited).encode()
        path.write_bytes(content)
        validate = store._validate

        def fail_transaction(state, previous=None):
            if previous is store._data:
                raise ValueError("Reload race: reference changed")
            return validate(state, previous)

        monkeypatch.setattr(store, "_validate", fail_transaction)
        store.reload_documents()
        store._pending.join()
        assert "Reload race" in store.runtime.status()["state"]["error"]
        monkeypatch.setattr(store, "_validate", validate)
        # Drop the same bytes seen during the failed reload, then delete via UI.
        path.unlink()
        path.write_bytes(content)
        store.transaction(lambda state: state["overlays"].pop("lower-third"))
        store.flush()
        assert not path.exists()
        assert path.with_name("lower-third.invalid.json").read_bytes() == content
    finally:
        store.close()


def test_reload_does_not_mark_unwritten_ui_document_as_saved(tmp_path):
    import json

    store = Store(tmp_path, debounce=100)
    try:
        store.flush()
        added = dict(store.get()["overlays"]["lower-third"], id="new", name="New")
        store.patch({"overlays": {"new": added}})
        store.reload_documents()
        store._pending.join()
        store.flush()
        assert json.loads((tmp_path / "overlays/new.json").read_text()) == added
    finally:
        store.close()


def test_dismiss_does_not_delete_file_from_another_collection(tmp_path):
    store = Store(tmp_path, debounce=100)
    try:
        directory = tmp_path / "scenes"
        directory.mkdir()
        rejected = directory / "only-here.invalid.json"
        rejected.write_text("keep")
        rejected.with_suffix(".txt").write_text("keep note")
        store.dismiss_rejected("overlays", rejected.name)
        store._pending.join()
        assert store.runtime.status()["state"]["error"]
        assert rejected.read_text() == "keep"
        assert rejected.with_suffix(".txt").read_text() == "keep note"
    finally:
        store.close()


def test_close_preserves_and_loads_valid_external_edit(tmp_path):
    import json

    seed = Store(tmp_path)
    seed.close()
    store = Store(tmp_path, debounce=100)
    edited = dict(store.get()["overlays"]["lower-third"], name="Edited before close")
    path = tmp_path / "overlays/lower-third.json"
    content = json.dumps(edited).encode()
    path.write_bytes(content)
    store.close()
    assert path.read_bytes() == content
    assert store.get()["overlays"]["lower-third"] == edited


def test_identical_ui_and_external_edit_has_no_conflict(tmp_path):
    import json

    store = Store(tmp_path, debounce=100)
    try:
        store.flush()
        path = tmp_path / "overlays/lower-third.json"
        edited = dict(store.get()["overlays"]["lower-third"], name="Same")
        content = json.dumps(edited).encode()
        path.write_bytes(content)
        store.patch({"overlays": {"lower-third": {"name": "Same"}}})
        store.flush()
        assert path.read_bytes() == content
        assert not list(path.parent.glob("*.invalid*.json"))
        assert store._disk_documents[path] == edited
    finally:
        store.close()


@pytest.mark.parametrize("content", [b"null", b"[]", b"42", b'"text"', b"true"])
def test_non_object_hand_drop_is_quarantined_never_deleted(tmp_path, content):
    store = Store(tmp_path, debounce=100)
    try:
        store.flush()
        path = tmp_path / "overlays/hand-drop.json"
        path.write_bytes(content)
        store.patch({"overlays": {"title-card": {"name": "Trigger save"}}})
        store.flush()
        assert not path.exists()
        rejected = path.with_name("hand-drop.invalid.json")
        assert rejected.read_bytes() == content
        assert rejected.with_suffix(".txt").read_text()
        entry = store.runtime.status()["stage"]["rejected_overlays"][0]
        assert entry["kind"] == "invalid" and entry["resolved"] is False
    finally:
        store.close()


def test_rejections_add_no_save_reads_or_validations(tmp_path, monkeypatch):
    from pathlib import Path
    import visualz.state as state_module

    counts = []
    for rejected_count in (0, 50):
        directory = tmp_path / str(rejected_count)
        seed = Store(directory, debounce=100)
        overlay = seed.get()["overlays"]["lower-third"]
        seed.patch({"overlays": {
            f"extra-{index}": dict(overlay, id=f"extra-{index}") for index in range(27)
        }})
        seed.close()
        for index in range(rejected_count):
            path = directory / "overlays" / f"lower-third.invalid-{index}.json"
            path.write_text("{}")
            path.with_suffix(".txt").write_text("bad edit")
        store = Store(directory, debounce=100)
        try:
            store.flush()
            calls = dict(reads=0, state_validations=0, schema_validations=0, publications=0)
            original_open = Path.open
            original_validate = store._validate
            original_schema = state_module.validate
            original_publish = store.runtime.publish_status

            def open_counted(path, mode="r", *args, **kwargs):
                if "r" in mode:
                    calls["reads"] += 1
                return original_open(path, mode, *args, **kwargs)

            def validate_counted(*args, **kwargs):
                calls["state_validations"] += 1
                return original_validate(*args, **kwargs)

            def schema_counted(*args, **kwargs):
                calls["schema_validations"] += 1
                return original_schema(*args, **kwargs)

            def publish_counted(target, values):
                if any(key.startswith("rejected_") for key in values):
                    calls["publications"] += 1
                return original_publish(target, values)

            with monkeypatch.context() as patch:
                patch.setattr(Path, "open", open_counted)
                patch.setattr(store, "_validate", validate_counted)
                patch.setattr(state_module, "validate", schema_counted)
                patch.setattr(store.runtime, "publish_status", publish_counted)
                store.patch({"overlays": {"title-card": {"name": "Changed"}}})
                store.flush()
                counts.append(calls.copy())
                assert calls["publications"] == 0  # rejection/resolution data is unchanged
                store.patch({"now_playing": {"song": "Unrelated save"}})
                store.flush()
                assert calls["publications"] == 0
            # Publication itself may use only cached facts, including resolved.
            def forbidden(*args, **kwargs):
                raise AssertionError("publication performed I/O or validation")

            with monkeypatch.context() as patch:
                patch.setattr(Path, "open", forbidden)
                patch.setattr(store, "_validate", forbidden)
                patch.setattr(state_module, "validate", forbidden)
                store._published_rejections.pop("overlays")
                store._publish_rejections("overlays")
                assert "overlays" in store._published_rejections
        finally:
            store.close()
    assert counts[0] == counts[1]
    assert counts[1]["state_validations"] == 1
    assert counts[1]["schema_validations"] == 1
