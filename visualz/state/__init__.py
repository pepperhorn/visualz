"""Single writer contract shared by API and workers; snapshots never retain locks."""

import json
import logging
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


class Store:
    """Thread-safe patch/replace/delete, immutable snapshot, debounced atomic save.

    subscribe(callback) returns unsubscribe; callbacks receive a full mutable copy.
    Renderers call snapshot() (constant-time reference read), never disk operations.
    close() flushes; a corrupt persisted state raises instead of silently overwriting.
    """

    def __init__(self, data_dir="data", debounce=0.2):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._listeners = []
        self._timer = None
        self._closed = False
        self.debounce = debounce
        path = self.data_dir / "state.json"
        self._data = json.loads(path.read_text()) if path.exists() else defaults()
        # Hand-edited templates are supported; reject malformed files without
        # replacing the last known valid template or stopping the stage.
        for file in (self.data_dir / "overlays").glob("*.json"):
            try:
                template = validate("overlay", json.loads(file.read_text()))
                if template["id"] != file.stem:
                    raise ValueError("template filename must match id")
                self._data["overlays"][template["id"]] = template
            except (ValueError, OSError) as exc:
                logging.warning("Rejected overlay %s: %s", file.name, exc)
        self._validate(self._data)
        self._snapshot = freeze(self._data)

    def _validate(self, state):
        if set(state) != set(defaults()):
            raise ValueError("state: unknown or missing root fields")
        for key in ("settings", "now_playing"):
            validate(key, state[key])
        for collection, schema in COLLECTIONS.items():
            if not isinstance(state[collection], dict):
                raise ValueError(f"{collection}: expected object")
            for key, value in state[collection].items():
                validate(schema, value)
                if value["id"] != key:
                    raise ValueError(f"{collection}: key must match id")
        for field, collection in [("active_scene", "scenes"), ("active_overlay", "overlays")]:
            if state[field] is not None and state[field] not in state[collection]:
                raise ValueError(f"{field}: missing reference")
        picture_set = state["settings"]["picture_set"]
        if picture_set is not None and picture_set not in state["picture_sets"]:
            raise ValueError("settings.picture_set: missing reference")

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
        """Apply change(dict) atomically after full validation; return committed state."""
        with self._lock:
            if self._closed:
                raise RuntimeError("store is closed")
            candidate = deepcopy(self._data)
            change(candidate)
            self._validate(candidate)
            self._data = candidate
            self._snapshot = freeze(candidate)
            if self._timer:
                self._timer.cancel()
            self._timer = Timer(self.debounce, self.flush)
            self._timer.daemon = True
            self._timer.start()
            # Notify under the writer lock so clients observe commit order.
            for callback in tuple(self._listeners):
                try:
                    callback(deepcopy(candidate))
                except Exception:
                    logging.exception("State subscriber failed")
            return deepcopy(candidate)

    def patch(self, patch):
        if not isinstance(patch, dict):
            raise ValueError("patch must be an object")
        return self.transaction(lambda state: merge(state, patch))

    def flush(self):
        with self._lock:
            path = self.data_dir / "state.json"
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(self._data, indent=2))
            temp.replace(path)
            for collection in COLLECTIONS:
                directory = self.data_dir / collection
                directory.mkdir(exist_ok=True)
                for old in directory.glob("*.json"):
                    if old.stem not in self._data[collection]:
                        old.unlink()
                for key, value in self._data[collection].items():
                    temp = directory / f"{key}.tmp"
                    temp.write_text(json.dumps(value, indent=2))
                    temp.replace(directory / f"{key}.json")
            (self.data_dir / "settings.json").write_text(json.dumps(self._data["settings"]))

    def close(self):
        with self._lock:
            self._closed = True
            if self._timer:
                self._timer.cancel()
            self.flush()
