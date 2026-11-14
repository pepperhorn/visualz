"""Exercise the real worker bridge and restart path through the threaded server."""

import json
import os
import selectors
import subprocess
import sys
import time
from urllib.request import Request, urlopen

import pytest


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="No desktop display",
)
def test_main_loop_commands_status_and_restart(tmp_path):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "visualz",
            "--window",
            "--port",
            "5211",
            "--size",
            "320x180",
            "--data-dir",
            str(tmp_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        # Only main writes readiness after workers, GL and server have started.
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 15
        output = []
        while time.monotonic() < deadline:
            if selector.select(0.1):
                line = os.read(process.stdout.fileno(), 65536).decode(errors="replace")
                output.append(line)
                if "Control:" in "".join(output):
                    break
                if not line:
                    break
        selector.close()
        assert "Control:" in "".join(output), "".join(output)

        def get(path):
            return json.load(urlopen("http://127.0.0.1:5211" + path, timeout=3))

        def command(target, name, args):
            request = Request(
                "http://127.0.0.1:5211/api/stage/command",
                data=json.dumps(dict(target=target, name=name, args=args)).encode(),
                headers={"Content-Type": "application/json"},
            )
            assert urlopen(request, timeout=3).status == 202

        status = get("/api/stage/status")
        assert status["stage"]["gl_renderer"]
        assert status["stage"]["resolution"] == [320, 180]
        assert status["stage"]["hostname"]
        assert status["stage"]["control_port"] == 5211
        assert status["stage"]["control_urls"][0].endswith(".local:5211/control")
        assert len(status["stage"]["control_urls"]) == len(status["stage"]["ip_addresses"]) + 1
        assert isinstance(status["stage"]["ip_addresses"], list)
        assert status["camera"]["present"] is False
        command("stage", "blackout", {"enabled": True})
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if get("/api/state")["settings"]["blackout"]["enabled"]:
                break
            time.sleep(0.01)
        else:
            pytest.fail("Main loop failed to dispatch blackout")
        command("audio", "refresh_devices", {})
        command("camera", "snap", {"set_id": "crowd"})
        command("camera", "delete_all", {"set_id": "crowd"})
        command("gallery", "next", {})
        command("gallery", "prev", {})
        command("stage", "restart", {})
        rest = process.communicate(timeout=10)[0]
        assert process.returncode == 1, rest
        assert json.loads((tmp_path / "state.json").read_text())["settings"]["blackout"]["enabled"]
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)
