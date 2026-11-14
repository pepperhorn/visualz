"""Standalone smoke test contracts; hardware run remains a human gate."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


def load_smoke():
    path = Path(__file__).resolve().parents[2] / "tools/smoke.py"
    spec = importlib.util.spec_from_file_location("visualz_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def test_s5_usb_capture_channel_counts(tmp_path):
    smoke, _ = load_smoke()
    card = tmp_path / "card2"
    card.mkdir()
    (card / "stream0").write_text(
        "USB XR18\nPlayback:\n  Channels: 18\nCapture:\n  Channels: 64\n  Channels: 2\nPlayback:\n  Channels: 128\n"
    )
    assert smoke.capture_channels(tmp_path) == {str(card / "stream0"): [2, 64]}


def test_s5_smoke_help_without_optional_imports():
    _, path = load_smoke()
    result = subprocess.run(
        [sys.executable, "-S", str(path), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0 and "--window" in result.stdout


def test_s5_npot_upload_precision_and_upscale():
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("No desktop display for smoke exercise")
    _, path = load_smoke()
    result = subprocess.run(
        [sys.executable, str(path), "--window", "--seconds", "0.1"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NPOT 480x270 FBO: ready; sampling at 1280x720" in result.stdout
    assert "Fragment HIGH_FLOAT:" in result.stdout
    assert "Fragment MEDIUM_FLOAT:" in result.stdout
    assert "Display:" in result.stdout


def test_s5_kms_selects_egl_before_opening_display():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
from visualz.gl import Context
try:
    context = Context((128,128),window=False)
    context.close()
except Exception:
    pass
assert os.environ['PYOPENGL_PLATFORM'] == 'egl'
print('EGL selected')
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env={k: v for k, v in os.environ.items() if k != "PYOPENGL_PLATFORM"},
    )
    assert result.returncode == 0 and "EGL selected" in result.stdout
