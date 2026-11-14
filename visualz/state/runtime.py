"""GL-free worker bridge, available as store.runtime on every thread.

Workers register_command(target, name, handler); handlers run on the main thread
when drain_commands() is called each frame. Handlers must only enqueue worker
work or Store.submit(), never wait for capture, conversion, network or disk.
Handlers MUST return within 2 ms. drain_commands(budget_ms=2) stops starting new
handlers when its frame budget expires; a running handler cannot be preempted.
POST /api/stage/command and WS {type:command,target,name,args} share this queue.
Accepted means queued, not completed. Optional unique client id (string/integer,
<=128 chars) is echoed in acknowledgements and command_result messages. HTTP
clients read GET /api/stage/result/<id>; WS results return to the originating
connection. The last 128 results are retained; do not reuse a cached id.
Handler failures appear in caller results and status.commands, never escape.
Full queues return HTTP 503 / Retry-After: 1 (WS error status/retry_after).

Initial commands (args are keyword arguments): audio.refresh_devices();
camera.snap(set_id), camera.delete_all(set_id); gallery.next(), gallery.prev();
stage.restart(), stage.blackout(enabled, overlay=False, fade_seconds=.5);
media.reconvert(asset_id), overlays.reload().
T2 replaces neutral audio/camera/gallery handlers by registering the same names.

publish_status(target, dict) merges volatile fields; status() returns a copy.
Coercion runs before taking the runtime lock. MAX_STATUS_ELEMENTS (4096) bounds the
total array elements and sequence slots in each update (including nested
containers); oversized updates raise ValueError naming the key and limit,
without changing prior status. NumPy sizes are checked before tolist().
Audio: devices [{id,name,channels}] (actual capture channels, not configured stereo),
levels {level,left,right,bass,mid,treble,beat}. Camera: present, devices, latest
(image endpoint name or null). Stage: fps, gl_renderer, hardware_profile (detected
low/high; null until T2 detects), requested_profile, resolution, hostname,
ip_addresses, state_recovered. publish_image(name, bytes, content_type) publishes
bounded in-memory snapshots exposed at /api/stage/image/<name>; None removes one.
"""

from copy import deepcopy
from collections import OrderedDict
import logging
import time
from uuid import uuid4
from visualz.state.json_safe import JsonCoercer
from inspect import signature
from queue import Empty, Full, Queue
from threading import RLock
import re


MAX_STATUS_ELEMENTS = 4096


class CommandQueueFull(ValueError):
    """Transient overload; HTTP maps this to 503 with Retry-After."""


class Runtime:
    def __init__(self):
        self._lock = RLock()
        self._handlers = {}
        self._commands = Queue(maxsize=128)
        self._status = {}
        self._images = {}
        self._results = OrderedDict()
        self.coerce = JsonCoercer()

    def register_command(self, target, name, handler):
        with self._lock:
            self._handlers[target, name] = handler

    def enqueue_command(self, envelope, on_result=None):
        if (
            not isinstance(envelope, dict)
            or not {"target", "name", "args"} <= set(envelope)
            or set(envelope) - {"target", "name", "args", "id"}
        ):
            raise ValueError("Command requires target, name, args and optional id")
        envelope = deepcopy(envelope)
        envelope.setdefault("id", uuid4().hex)
        if (
            isinstance(envelope["id"], bool)
            or not isinstance(envelope["id"], (str, int))
            or not 1 <= len(str(envelope["id"])) <= 128
        ):
            raise ValueError("Command id must be a string or integer of at most 128 characters")
        if not all(
            isinstance(envelope[k], str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", envelope[k])
            for k in ("target", "name")
        ) or not isinstance(envelope["args"], dict):
            raise ValueError("Command target/name must be identifiers and args an object")
        with self._lock:
            if str(envelope["id"]) in self._results:
                raise ValueError("Command id is already in use; choose a unique id")
            handler = self._handlers.get((envelope["target"], envelope["name"]))
            if handler is None:
                raise ValueError(f"Unknown command: {envelope['target']}.{envelope['name']}")
            try:
                signature(handler).bind(**envelope["args"])
            except TypeError as exc:
                raise ValueError(f"Invalid command arguments: {exc}") from exc
            try:
                self._commands.put_nowait((handler, envelope, on_result))
            except Full as exc:
                raise CommandQueueFull("Command queue is full; retry later") from exc

            self._results[str(envelope["id"])] = {"id": envelope["id"], "pending": True}
            while len(self._results) > 128:
                self._results.popitem(last=False)
        return {"accepted": True, "id": envelope["id"]}

    def command_result(self, command_id):
        with self._lock:
            return deepcopy(self._results.get(str(command_id)))

    def drain_commands(self, limit=32, budget_ms=2):
        """Handlers MUST return within 2 ms and offload long work to a worker.

        A handler cannot be preempted; the budget stops starting more handlers.
        Above 5 ms we log and publish slow_handler. Failures become caller results.
        """
        deadline = time.perf_counter() + budget_ms / 1000
        for _ in range(limit):
            if time.perf_counter() >= deadline:
                break
            try:
                handler, command, callback = self._commands.get_nowait()
            except Empty:
                break
            started = time.perf_counter()
            result = {
                "id": command["id"],
                "target": command["target"],
                "name": command["name"],
                "pending": False,
            }
            try:
                result.update(value=handler(**command["args"]), error=None)
            except Exception as exc:
                logging.exception("Command %s.%s failed", command["target"], command["name"])
                result.update(value=None, error=self.coerce(exc, "command_error"))
            elapsed = (time.perf_counter() - started) * 1000
            result = self.coerce(result, "command_result")
            with self._lock:
                self._results[str(command["id"])] = result
                self._results.move_to_end(str(command["id"]))
                while len(self._results) > 128:
                    self._results.popitem(last=False)
            self.publish_status(
                "commands",
                {"last": command, "error": result["error"], "last_ms": elapsed, "result": result},
            )
            if elapsed > 5:
                slow = dict(target=command["target"], name=command["name"], milliseconds=elapsed)
                logging.warning("Slow command handler: %s", slow)
                self.publish_status("commands", {"slow_handler": slow})
            if callback is not None:
                try:
                    callback(deepcopy(result))
                except Exception:
                    logging.exception("Command result callback failed")

    def publish_status(self, target, values):
        if not isinstance(values, dict):
            raise ValueError("Status must be an object")
        values = self.coerce(values, str(target), max_elements=MAX_STATUS_ELEMENTS)
        with self._lock:
            self._status.setdefault(target, {}).update(values)

    def status(self):
        with self._lock:
            return deepcopy(self._status)

    def publish_image(self, name, content, content_type="image/jpeg", metadata=None):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", name):
            raise ValueError("Invalid image name")
        if content is not None and (
            len(content) > 2 * 1024 * 1024
            or content_type not in ("image/jpeg", "image/png", "image/webp")
        ):
            raise ValueError("Image must be JPEG/PNG/WebP and at most 2 MiB")
        with self._lock:
            if content is None:
                self._images.pop(name, None)
                self._status.setdefault("images", {}).pop(name, None)
            else:
                self._images[name] = (bytes(content), content_type)
                self._status.setdefault("images", {})[name] = self.coerce(
                    {**(metadata or {}), "content_type": content_type, "bytes": len(content)},
                    f"images.{name}",
                )

    def image(self, name):
        with self._lock:
            return self._images.get(name)
