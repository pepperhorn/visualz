"""GL-free worker bridge, available as store.runtime on every thread.

Workers register_command(target, name, handler); handlers run on the main thread
when drain_commands() is called each frame. Handlers must only enqueue worker
work or Store.submit(), never wait for capture, conversion, network or disk.
POST /api/stage/command and WS {type:command,target,name,args} share this queue.
Accepted means queued, not completed; handler failures appear in status.commands.

Initial commands (args are keyword arguments): audio.refresh_devices();
camera.snap(set_id), camera.delete_all(set_id); gallery.next(), gallery.prev();
stage.restart(), stage.blackout(enabled, overlay=False, fade_seconds=.5).
T2 replaces neutral audio/camera/gallery handlers by registering the same names.

publish_status(target, dict) merges volatile fields; status() returns a copy.
Audio: devices [{id,name,channels}] (actual capture channels, not configured stereo),
levels {level,left,right,bass,mid,treble,beat}. Camera: present, devices, latest
(image endpoint name or null). Stage: fps, gl_renderer, hardware_profile (detected
low/high; null until T2 detects), requested_profile, resolution, hostname,
ip_addresses, state_recovered. publish_image(name, bytes, content_type) publishes
bounded in-memory snapshots exposed at /api/stage/image/<name>; None removes one.
"""

from copy import deepcopy
from inspect import signature
from queue import Empty, Full, Queue
from threading import RLock
import re


class Runtime:
    def __init__(self):
        self._lock = RLock()
        self._handlers = {}
        self._commands = Queue(maxsize=128)
        self._status = {}
        self._images = {}

    def register_command(self, target, name, handler):
        with self._lock:
            self._handlers[target, name] = handler

    def enqueue_command(self, envelope):
        if not isinstance(envelope, dict) or set(envelope) != {"target", "name", "args"}:
            raise ValueError("Command requires exactly target, name, args")
        if not all(
            isinstance(envelope[k], str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", envelope[k])
            for k in ("target", "name")
        ) or not isinstance(envelope["args"], dict):
            raise ValueError("Command target/name must be identifiers and args an object")
        with self._lock:
            handler = self._handlers.get((envelope["target"], envelope["name"]))
            if handler is None:
                raise ValueError(f"Unknown command: {envelope['target']}.{envelope['name']}")
            try:
                signature(handler).bind(**envelope["args"])
            except TypeError as exc:
                raise ValueError(f"Invalid command arguments: {exc}") from exc
            try:
                self._commands.put_nowait((handler, deepcopy(envelope)))
            except Full as exc:
                raise ValueError("Command queue is full; retry later") from exc

    def drain_commands(self, limit=32):
        for _ in range(limit):
            try:
                handler, command = self._commands.get_nowait()
            except Empty:
                break
            try:
                handler(**command["args"])
                self.publish_status("commands", {"last": command, "error": None})
            except Exception as exc:
                self.publish_status("commands", {"last": command, "error": str(exc)})

    def publish_status(self, target, values):
        if not isinstance(values, dict):
            raise ValueError("Status must be an object")
        with self._lock:
            self._status.setdefault(target, {}).update(deepcopy(values))

    def status(self):
        with self._lock:
            return deepcopy(self._status)

    def publish_image(self, name, content, content_type="image/jpeg"):
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
            else:
                self._images[name] = (bytes(content), content_type)

    def image(self, name):
        with self._lock:
            return self._images.get(name)
