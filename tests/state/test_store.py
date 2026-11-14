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
    assert Store(tmp_path).get() == before
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
