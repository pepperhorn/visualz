"""Single writer contract shared by API and workers; snapshots never retain locks."""

import json
import logging
import os
import re
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
        self._data = self._read_documents(self._data, self._disk_documents)
        self._document_values = {
            (collection, key): value
            for collection in ("overlays", "scenes", "picture_sets")
            for key, value in self._data[collection].items()
        }
        self._snapshot = freeze(self._data)
        self._pending = Queue()
        self._worker = Thread(target=self._apply_pending, daemon=True)
        self._worker.start()
        self.runtime.register_command("overlays", "reload", self.reload_documents)
        self.runtime.register_command("overlays", "dismiss_rejected", self.dismiss_rejected)

    @staticmethod
    def _is_rejected(path):
        return ".invalid" in path.stem

    def _read_documents(self, state, documents):
        """Preserve all rejected edits, including earlier ones, and expose errors."""
        state = deepcopy(state)
        for collection in ("picture_sets", "scenes", "overlays"):
            directory = self.data_dir / collection
            for file in sorted(directory.glob("*.json")):
                if self._is_rejected(file):
                    continue
                try:
                    state = self._document_candidate(file, state, collection)
                    documents[file] = state[collection][file.stem]
                except (ValueError, OSError, TypeError, KeyError) as exc:
                    documents.pop(file, None)
                    self._reject_document(file, exc)
            self._publish_rejections(collection, state)
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
        self._disk_documents.pop(file, None)
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

    def _publish_rejections(self, collection, state=None):
        # Rejection reporting is best effort: it must never prevent startup.
        try:
            directory = self.data_dir / collection
            files = set(directory.glob("*.invalid*.json"))
            files.update(p for p in self._rejected_paths if p.parent == directory)
            newest = sorted(files, key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
            problems = []
            if state is None:
                state = self.get() if hasattr(self, "_snapshot") else self._data
            for invalid in newest[:50]:
                try:
                    with invalid.with_suffix(".txt").open() as note:
                        message = note.read(1024)
                except (OSError, UnicodeError):
                    message = "Rejected hand edit; see log"
                resolved = False
                live = directory / (invalid.name.split(".invalid", 1)[0] + ".json")
                try:
                    self._document_candidate(live, state, collection)
                    resolved = True
                except (ValueError, OSError, TypeError, KeyError):
                    pass
                problems.append(dict(file=invalid.name, error=message, resolved=resolved))
            self.runtime.publish_status("stage", {
                "rejected_" + collection: problems,
                "rejected_" + collection + "_total": len(files),
            })
        except Exception:
            logging.exception("Could not publish rejected %s files", collection)

    def dismiss_rejected(self, collection, file):
        """Validate the name on the render thread; do all disk work on the worker."""
        if collection not in ("overlays", "scenes", "picture_sets"):
            raise ValueError("Unknown document collection")
        if not isinstance(file, str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,100}\.invalid(?:-[0-9]+)?\.json", file
        ):
            raise ValueError("Expected a quarantine filename without a path")

        def dismiss():
            with self._flush_lock:
                directory = self.data_dir / collection
                if directory.resolve() != self.data_dir.resolve() / collection:
                    raise ValueError("Collection directory must not be a symlink")
                path = directory / file
                # unlink removes a symlink itself, never its target.
                path.unlink()
                path.with_suffix(".txt").unlink(missing_ok=True)
                self._publish_rejections(collection)

        self.submit_task(dismiss)
        return {"queued": True}

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
        return self._transaction(change)

    def _transaction(self, change, closing=False):
        with self._lock:
            if self._closed and not closing:
                raise RuntimeError("store is closed")
            candidate = deepcopy(self._data)
            change(candidate)
            self._validate(candidate, self._data)
            self._data = candidate
            self._snapshot = freeze(candidate)
            if self._timer:
                self._timer.cancel()
            if not self._closed:
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
                            documents = dict(self._disk_documents)
                            loaded = self._read_documents(before, documents)

                            def apply(state):
                                for collection in ("picture_sets", "scenes", "overlays"):
                                    for key, value in loaded[collection].items():
                                        if before[collection].get(key) != value:
                                            state[collection][key] = value

                            self.transaction(apply)
                            self._disk_documents = documents
                            for file, value in documents.items():
                                self._document_values[file.parent.name, file.stem] = value
                            for collection in ("picture_sets", "scenes", "overlays"):
                                self._publish_rejections(collection)
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
            previous = self._persisted or {}
            for collection in COLLECTIONS:
                if current[collection] == previous.get(collection):
                    continue
                directory = self.data_dir / collection
                directory.mkdir(exist_ok=True)
                old_values = previous.get(collection, {})
                documents = collection in ("overlays", "scenes", "picture_sets")
                skip = set()
                for old in directory.glob("*.json"):
                    if self._is_rejected(old) or old in self._rejected_paths:
                        continue
                    unchanged = old.stem in old_values
                    if documents:
                        try:
                            value = json.loads(old.read_text())
                            unchanged = self._disk_documents.get(old) == value
                            if not unchanged:
                                candidate = self._document_candidate(old, current, collection)
                                memory = current[collection].get(old.stem)
                                baseline = self._document_values.get((collection, old.stem))
                                if memory is not None and memory != baseline:
                                    self._reject_document(old, ValueError(
                                        "Hand edit conflicted with an in-memory change; "
                                        "the in-memory value was kept"
                                    ))
                                elif memory is not None:
                                    # Apply only if a concurrent writer has not changed this id.
                                    def adopt(state):
                                        if state[collection].get(old.stem) == memory:
                                            state[collection][old.stem] = candidate[collection][old.stem]

                                    committed = self._transaction(adopt, closing=True)
                                    if committed[collection].get(old.stem) == value:
                                        current = deepcopy(current)
                                        current[collection][old.stem] = value
                                        self._disk_documents[old] = value
                                        self._document_values[collection, old.stem] = value
                        except (ValueError, OSError, TypeError, KeyError) as exc:
                            self._reject_document(old, exc)
                            skip.add(old.stem)
                            continue
                    if old.stem not in current[collection] and unchanged:
                        old.unlink()
                        self._disk_documents.pop(old, None)
                        self._document_values.pop((collection, old.stem), None)
                for key, value in current[collection].items():
                    path = directory / f"{key}.json"
                    if path in self._rejected_paths or key in skip:
                        continue
                    baseline = (self._document_values.get((collection, key)) if documents
                                else old_values.get(key))
                    if baseline != value or (documents and not path.exists()
                                             and path not in self._disk_documents
                                             and key not in old_values
                                             and self._persisted is None):
                        atomic_write(path, json.dumps(value, indent=2).encode())
                        self._disk_documents[path] = value
                        if documents:
                            self._document_values[collection, key] = value
                if documents:
                    self._publish_rejections(collection)
            encoded = json.dumps(current, indent=2).encode()
            if self._last_good is not None:
                atomic_write(self.data_dir / "state.json.bak", self._last_good)
            atomic_write(self.data_dir / "state.json", encoded)
            self._last_good = encoded
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
