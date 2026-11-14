"""Main thread owns SDL/GL; server, audio and camera own independent workers."""

import argparse
import signal
import sys
import time
from contextlib import ExitStack
from threading import Lock

from visualz.audio import Analyser
from visualz.camera import Worker
from visualz.gl import Context
from visualz.overlay import Overlay
from visualz.render import Engine
from visualz.server import Server
from visualz.state import Store


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
            audio, camera = Analyser(store), Worker(store)
            for worker in (audio, camera):
                cleanup.callback(worker.close)
                worker.start()
            stage = store.snapshot()["settings"]["stage"]
            context = Context(args.size or (stage["width"], stage["height"]), args.window)
            cleanup.callback(context.close)
            engine = Engine(context, store, audio, camera)
            cleanup.callback(engine.close)
            overlay = Overlay(context, args.data_dir)
            cleanup.callback(overlay.close)
            status_lock = Lock()
            status = {"fps": 0, "devices": []}

            def telemetry():
                with status_lock:
                    return {"audio": dict(audio.snapshot()), "stage": dict(status)}

            server = Server(store, args.port, telemetry)
            cleanup.callback(server.close)
            server.start()
            print(f"Control: http://0.0.0.0:{args.port}/control", flush=True)
            last, count = time.monotonic(), 0
            while not stopped and context.running():
                now = time.monotonic()
                snapshot = store.snapshot()
                engine.draw(snapshot, audio.snapshot(), now)
                overlay.draw(snapshot, now)
                context.swap()
                count += 1
                if now - last >= 1:
                    with status_lock:
                        status["fps"] = count / (now - last)
                    last, count = now, 0
    except Exception as exc:
        print(f"visualz: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
