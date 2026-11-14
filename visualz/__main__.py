"""Main thread owns SDL/GL; server, audio and camera own independent workers."""

import argparse
import signal
import sys
import time
from contextlib import ExitStack
import socket
import subprocess
import ctypes

from visualz.audio import Analyser
from visualz.camera import Worker
from visualz.gl import Context
from visualz.overlay import Overlay
from visualz.render import Engine
from visualz.server import Server
from visualz.state import Store
from visualz.schema.profiles import stage_size
from visualz.media import register_commands


def size_arg(value):
    try:
        width, height = map(int, value.lower().split("x"))
        if not (64 <= width <= 1920 and 64 <= height <= 1080):
            raise ValueError()
        return width, height
    except ValueError:
        raise argparse.ArgumentTypeError("Expected WIDTHxHEIGHT within 64x64..1920x1080") from None


def main():
    parser = argparse.ArgumentParser(description="visualz native ES 2 stage")
    parser.add_argument(
        "--window", action="store_true", help="Use a desktop window instead of KMS/DRM"
    )
    parser.add_argument("--port", type=int, default=5211)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--size", type=size_arg, default=None)
    args = parser.parse_args()
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)
    try:
        with ExitStack() as cleanup:
            store = Store(args.data_dir)
            cleanup.callback(store.close)
            runtime = store.runtime
            runtime.publish_status("stage", {"hardware_profile": None})
            audio, camera = Analyser(store), Worker(store)
            for worker in (audio, camera):
                cleanup.callback(worker.close)
                worker.start()
            context = Context(args.size or stage_size(store.snapshot()["settings"]), args.window)
            register_commands(store)
            cleanup.callback(context.close)
            engine = Engine(context, store, audio, camera)
            cleanup.callback(engine.close)
            overlay = Overlay(context, args.data_dir)
            cleanup.callback(overlay.close)
            restart_requested = False

            def restart():
                nonlocal stopped, restart_requested
                stopped, restart_requested = True, True

            def blackout(enabled, overlay=False, fade_seconds=0.5):
                if (
                    not isinstance(enabled, bool)
                    or not isinstance(overlay, bool)
                    or not isinstance(fade_seconds, (float, int))
                    or not 0 <= fade_seconds <= 10
                ):
                    raise ValueError("Invalid blackout arguments")
                store.submit(
                    {
                        "settings": {
                            "blackout": dict(
                                enabled=enabled, overlay=overlay, fade_seconds=fade_seconds
                            )
                        }
                    }
                )

            runtime.register_command("stage", "restart", restart)
            runtime.register_command("stage", "blackout", blackout)
            hostname = socket.gethostname()
            try:
                result = subprocess.run(
                    ["hostname", "-I"], capture_output=True, text=True, timeout=2
                )
                addresses = sorted(set(result.stdout.split())) if result.returncode == 0 else []
                if not addresses:
                    addresses = sorted(
                        {entry[4][0] for entry in socket.getaddrinfo(hostname, None)}
                    )
            except (OSError, subprocess.TimeoutExpired):
                addresses = []
            from visualz.gl import api

            renderer = ctypes.cast(api().glGetString(api().GL_RENDERER), ctypes.c_char_p).value
            runtime.publish_status(
                "stage",
                dict(
                    fps=0,
                    gl_renderer=renderer.decode() if renderer else "unknown",
                    requested_profile=store.snapshot()["settings"]["hardware_profile"],
                    resolution=list(context.size),
                    hostname=hostname,
                    ip_addresses=addresses,
                    control_port=args.port,
                    control_urls=[
                        f"http://{hostname.removesuffix('.local')}.local:{args.port}/control"
                    ]
                    + [
                        f"http://{'[' + address + ']' if ':' in address else address}:{args.port}/control"
                        for address in addresses
                    ],
                ),
            )
            server = Server(store, args.port)
            cleanup.callback(server.close)
            server.start()
            print(f"Control: http://0.0.0.0:{args.port}/control", flush=True)
            last, count = time.monotonic(), 0
            while not stopped and context.running():
                now = time.monotonic()
                runtime.drain_commands()
                snapshot = store.snapshot()
                engine.draw(snapshot, audio.snapshot(), now)
                overlay.draw(snapshot, now)
                context.swap()
                count += 1
                if now - last >= 1:
                    runtime.publish_status(
                        "stage",
                        {
                            "fps": count / (now - last),
                            "requested_profile": snapshot["settings"]["hardware_profile"],
                        },
                    )
                    last, count = now, 0
    except Exception as exc:
        print(f"visualz: {exc}", file=sys.stderr)
        return 1
    return 1 if restart_requested else 0


if __name__ == "__main__":
    raise SystemExit(main())
