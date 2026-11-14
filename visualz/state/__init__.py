"""Single writer contract shared by API and workers; snapshots never retain locks."""

import json
import logging
import os
import time
from queue import Queue
from threading import Lock, Thread

from visualz.state.runtime import Runtime
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from threading import RLock, Timer
from types import MappingProxyType

from visualz.schema import defaults, validate

COLLECTIONS = {
    "scenes": "scene",
    "overlays": "overlay",
    "picture_sets": "picture_set",
    "assets": "asset",
}


def merge(target, patch):
    """Recursive object merge; arrays/scalars replace. Null is a stored value."""
    if not isinstance(patch, dict):
        raise ValueError("patch must be an object")
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = deepcopy(value)
    return target


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(map(freeze, value))
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return list(map(thaw, value))
    return value


def atomic_write(path, content):
    """Durable temp write and directory sync, then atomic replacement and sync."""
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("wb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
        temp.replace(path)
        os.fsync(directory)
    finally:
        os.close(directory)


class Store:
    """Immutable render snapshots, validated transactions and durable persistence.

    Call submit(patch) from the render thread: it never waits for validation/disk.
    transaction()/patch() are for server/worker threads only, never render handlers.
    flush serialises and writes outside the writer lock under a separate flush lock.
    Only changed projections are written. Corrupt startup state recovers from one
    durable rotating backup, then defaults, and is quarantined rather than fatal.
    """

    def __init__(self, data_dir="data", debounce=0.2):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock, self._flush_lock = RLock(), Lock()
        self._listeners, self._timer = [], None
        self._closed = False
        self._accepting = True
        self.debounce = debounce
        self.runtime = Runtime()
        self._last_good = None
        self._persisted = None
        self._data = defaults()
        recovered = False
        for name in ("state.json", "state.json.bak"):
            path = self.data_dir / name
            if not path.exists():
                if name == "state.json" and (self.data_dir / "state.json.bak").exists():
                    recovered = True
                continue
            try:
                raw = path.read_bytes()
                candidate = json.loads(raw)
                self._validate(candidate)
                self._data, self._last_good = candidate, raw
                break
            except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
                recovered = True
                logging.warning("Rejected %s; recovering state: %s", name, exc)
                try:
                    path.rename(path.with_name(f"{name}.corrupt-{time.time_ns()}"))
                except OSError:
                    logging.warning("Could not quarantine %s", path)
        self.runtime.publish_status("stage", {"state_recovered": recovered})
        if recovered:
            logging.warning("State recovered from backup or defaults")
        for file in (self.data_dir / "overlays").glob("*.json"):
            try:
                template = validate("overlay", json.loads(file.read_text()))
                if template["id"] != file.stem:
                    raise ValueError("template filename must match id")
                candidate = deepcopy(self._data)
                candidate["overlays"][template["id"]] = template
                self._validate(candidate)
                self._data = candidate
            except (ValueError, OSError, TypeError, KeyError) as exc:
                logging.warning("Rejected overlay %s: %s", file.name, exc)
        self._snapshot = freeze(self._data)
        self._pending = Queue()
        self._worker = Thread(target=self._apply_pending, daemon=True)
        self._worker.start()

    def _validate(self, state, previous=None):
        if not isinstance(state, dict) or set(state) != set(defaults()):
            raise ValueError("state: unknown or missing root fields")
        for key in ("settings", "now_playing"):
            if previous is None or state[key] != previous[key]:
                validate(key, state[key])
        for collection, schema in COLLECTIONS.items():
            if not isinstance(state[collection], dict):
                raise ValueError(f"{collection}: expected object")
            for key, value in state[collection].items():
                if previous is None or previous[collection].get(key) != value:
                    validate(schema, value)
                if value["id"] != key:
                    raise ValueError(f"{collection}: key must match id")
        for field, collection in [("active_scene", "scenes"), ("active_overlay", "overlays")]:
            if state[field] is not None and state[field] not in state[collection]:
                raise ValueError(f"{field}: missing reference")
        paths = {asset["path"] for asset in state["assets"].values()}
        for owner, settings in [
            ("settings", state["settings"]),
            *[(f"scene.{k}", v) for k, v in state["scenes"].items()],
        ]:
            if (
                settings.get("picture_set") is not None
                and settings["picture_set"] not in state["picture_sets"]
            ):
                raise ValueError(f"{owner}.picture_set: missing reference")
            if settings.get("source_asset") is not None and settings["source_asset"] not in paths:
                raise ValueError(f"{owner}.source_asset: missing reference")
            if settings["look"]["palette"] not in state["settings"]["palettes"]:
                raise ValueError(f"{owner}.look.palette: unknown palette")

    def snapshot(self):
        return self._snapshot

    def get(self):
        return thaw(self._snapshot)

    def subscribe(self, callback):
        with self._lock:
            self._listeners.append(callback)

        def unsubscribe():
            with self._lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)

        return unsubscribe

    def transaction(self, change):
        with self._lock:
            if self._closed:
                raise RuntimeError("store is closed")
            candidate = deepcopy(self._data)
            change(candidate)
            self._validate(candidate, self._data)
            self._data = candidate
            self._snapshot = freeze(candidate)
            if self._timer:
                self._timer.cancel()
            self._timer = Timer(self.debounce, self.flush)
            self._timer.daemon = True
            self._timer.start()
            for callback in tuple(self._listeners):
                try:
                    callback(deepcopy(candidate))
                except Exception:
                    logging.exception("State subscriber failed")
            return deepcopy(candidate)

    def patch(self, patch):
        return self.transaction(lambda state: merge(state, patch))

    def submit(self, patch):
        """Queue a JSON patch without taking the state/disk lock (render-safe)."""
        if not self._accepting:
            raise RuntimeError("store is closing")
        self._pending.put_nowait(deepcopy(patch))

    def _apply_pending(self):
        while True:
            patch = self._pending.get()
            try:
                if patch is None:
                    return
                self.patch(patch)
            except Exception as exc:
                self.runtime.publish_status("state", {"error": str(exc)})
            finally:
                self._pending.task_done()

    def flush(self):
        with self._flush_lock:
            with self._lock:
                current = self._data  # Published dictionaries are never mutated again.
            if current == self._persisted:
                return
            encoded = json.dumps(current, indent=2).encode()
            if self._last_good is not None:
                atomic_write(self.data_dir / "state.json.bak", self._last_good)
            atomic_write(self.data_dir / "state.json", encoded)
            self._last_good = encoded
            previous = self._persisted or {}
            for collection in COLLECTIONS:
                if current[collection] == previous.get(collection):
                    continue
                directory = self.data_dir / collection
                directory.mkdir(exist_ok=True)
                old_values = previous.get(collection, {})
                for old in directory.glob("*.json"):
                    if old.stem not in current[collection]:
                        old.unlink()
                for key, value in current[collection].items():
                    if old_values.get(key) != value:
                        atomic_write(
                            directory / f"{key}.json", json.dumps(value, indent=2).encode()
                        )
            if current["settings"] != previous.get("settings"):
                atomic_write(
                    self.data_dir / "settings.json", json.dumps(current["settings"]).encode()
                )
            self._persisted = current

    def close(self):
        self._accepting = False
        self._pending.put(None)
        self._worker.join()
        with self._lock:
            self._closed = True
            if self._timer:
                self._timer.cancel()
        self.flush()
