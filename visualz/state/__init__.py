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
from visualz.schema.migrations import migrate, SCHEMA_VERSION

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
        self._document_lock = Lock()
        self._rejected_paths = set()
        self._disk_documents = {}
        recovered = False
        for name in ("state.json", "state.json.bak"):
            path = self.data_dir / name
            if not path.exists():
                if name == "state.json" and (self.data_dir / "state.json.bak").exists():
                    recovered = True
                continue
            try:
                raw = path.read_bytes()
                candidate = migrate(json.loads(raw))
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
        self._data = self._read_documents(self._data)
        self._snapshot = freeze(self._data)
        self._pending = Queue()
        self._worker = Thread(target=self._apply_pending, daemon=True)
        self._worker.start()
        self.runtime.register_command("overlays", "reload", self.reload_documents)

    @staticmethod
    def _is_rejected(path):
        return ".invalid" in path.stem

    def _read_documents(self, state):
        """Preserve all rejected edits, including earlier ones, and expose errors."""
        state = deepcopy(state)
        for collection in ("picture_sets", "scenes", "overlays"):
            directory = self.data_dir / collection
            for file in sorted(directory.glob("*.json")):
                if self._is_rejected(file):
                    continue
                try:
                    state = self._document_candidate(file, state, collection)
                    self._disk_documents[file] = state[collection][file.stem]
                except (ValueError, OSError, TypeError, KeyError) as exc:
                    self._reject_document(file, exc)
            self._publish_rejections(collection)
        return state

    def _document_candidate(self, file, state, collection):
        value = validate(COLLECTIONS[collection], json.loads(file.read_text()))
        if value["id"] != file.stem:
            raise ValueError("Document filename must match id")
        candidate = deepcopy(state)
        candidate[collection][value["id"]] = value
        self._validate(candidate)
        return candidate

    def _reject_document(self, file, error):
        logging.warning("Rejected %s %s: %s", file.parent.name, file.name, error)
        invalid = file.with_name(file.stem + ".invalid.json")
        if invalid.exists():
            invalid = file.with_name(f"{file.stem}.invalid-{time.time_ns()}.json")
        try:
            file.rename(invalid)
            invalid.with_suffix(".txt").write_text(str(error))
        except OSError:
            self._rejected_paths.add(file)
            logging.exception("Could not quarantine rejected hand edit; protecting original")

    def _publish_rejections(self, collection):
        directory = self.data_dir / collection
        problems = []
        for invalid in sorted(directory.glob("*.invalid*.json")):
            error = invalid.with_suffix(".txt")
            try:
                message = error.read_text() if error.exists() else "Rejected hand edit; see log"
            except OSError:
                message = "Cannot read rejection details; see log"
            problems.append(dict(file=invalid.name, error=message))
        problems.extend(
            dict(file=p.name, error="Could not quarantine rejected hand edit; see log")
            for p in self._rejected_paths
            if p.parent == directory
        )
        self.runtime.publish_status("stage", {"rejected_" + collection: problems})

    def reload_documents(self):
        """Command handler: hand disk work to Store's existing background worker."""
        self._pending.put_nowait("reload_documents")
        return {"queued": True}

    def _validate(self, state, previous=None):
        if not isinstance(state, dict) or set(state) != set(defaults()):
            raise ValueError("state: unknown or missing root fields")
        if state["schema_version"] != SCHEMA_VERSION or type(state["schema_version"]) is not int:
            raise ValueError("Unsupported schema_version")
        try:
            json.dumps(state, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"State must contain finite JSON values: {exc}") from exc
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

    def submit_task(self, work):
        """Queue a short-lived background job; close drains jobs before flushing."""
        if not self._accepting:
            raise RuntimeError("store is closing")
        self._pending.put_nowait(work)

    def _apply_pending(self):
        while True:
            patch = self._pending.get()
            try:
                if patch is None:
                    return
                if callable(patch):
                    patch()
                elif patch == "reload_documents":
                    with self._document_lock:
                        # Serialize reload/flush disk access, but only load touched
                        # document values into a fresh transaction at commit time.
                        with self._flush_lock:
                            before = self.get()
                            loaded = self._read_documents(before)

                            def apply(state):
                                for collection in ("picture_sets", "scenes", "overlays"):
                                    for key, value in loaded[collection].items():
                                        if before[collection].get(key) != value:
                                            state[collection][key] = value

                            self.transaction(apply)
                else:
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
                    if self._is_rejected(old) or old in self._rejected_paths:
                        continue
                    if collection in ("overlays", "scenes", "picture_sets"):
                        try:
                            value = json.loads(old.read_text())
                            if value != self._disk_documents.get(old):
                                self._document_candidate(old, current, collection)
                        except (ValueError, OSError, TypeError, KeyError) as exc:
                            self._reject_document(old, exc)
                            continue
                    if old.stem not in current[collection] and (
                        old.stem in old_values or old in self._disk_documents
                    ):
                        old.unlink()
                        self._disk_documents.pop(old, None)
                for key, value in current[collection].items():
                    if directory / f"{key}.json" in self._rejected_paths:
                        continue
                    if old_values.get(key) != value:
                        path = directory / f"{key}.json"
                        atomic_write(path, json.dumps(value, indent=2).encode())
                        self._disk_documents[path] = value
                if collection in ("overlays", "scenes", "picture_sets"):
                    self._publish_rejections(collection)
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
