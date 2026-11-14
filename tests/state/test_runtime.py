"""Status publication stays bounded and does not stall the render bridge."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import perf_counter

import numpy as np
import pytest

from visualz.state.json_safe import JsonCoercer
from visualz.state.runtime import MAX_STATUS_ELEMENTS, Runtime


def test_frame_rejected_quickly_without_changing_status():
    runtime = Runtime()
    runtime.publish_status("camera", {"present": True, "latest": "previous"})
    previous = runtime.status()
    frame = np.zeros((480, 270, 3), dtype=np.uint8)
    started = perf_counter()
    with pytest.raises(ValueError, match=rf"camera\.frame.*{MAX_STATUS_ELEMENTS}"):
        runtime.publish_status("camera", {"latest": "new", "frame": frame})
    elapsed = perf_counter() - started
    assert elapsed < 0.005
    assert runtime.status() == previous


def test_spectrum_accepted_and_detached_from_publisher():
    runtime = Runtime()
    spectrum = np.linspace(0, 1, 2048, dtype=np.float32)
    expected = spectrum.tolist()
    runtime.publish_status("audio", {"spectrum": spectrum})
    spectrum[:] = 0
    assert runtime.status()["audio"]["spectrum"] == expected


@pytest.mark.parametrize(
    "value",
    [list(range(MAX_STATUS_ELEMENTS)), np.zeros((64, 64))],
)
def test_exact_limit_accepted(value):
    runtime = Runtime()
    runtime.publish_status("test", {"value": value})
    assert "value" in runtime.status()["test"]


@pytest.mark.parametrize(
    "value",
    [
        list(range(MAX_STATUS_ELEMENTS + 1)),
        tuple(range(MAX_STATUS_ELEMENTS + 1)),
        set(range(MAX_STATUS_ELEMENTS + 1)),
        {"a": [0] * 2048, "b": np.zeros(2049)},
        [[0] * 2048, [0] * 2048],
    ],
)
def test_sequence_and_nested_aggregate_limit(value):
    runtime = Runtime()
    with pytest.raises(ValueError, match=rf"test\.value.*{MAX_STATUS_ELEMENTS}"):
        runtime.publish_status("test", {"value": value})
    assert runtime.status() == {}


def test_object_array_cannot_hide_oversized_sequence():
    values = np.empty(1, dtype=object)
    values[0] = [0] * (MAX_STATUS_ELEMENTS + 1)
    with pytest.raises(ValueError, match=rf"test\.value.*{MAX_STATUS_ELEMENTS}"):
        Runtime().publish_status("test", {"value": values})


def test_blocked_coercion_allows_status_and_command_drain():
    runtime = Runtime()
    converting = Event()
    release = Event()

    class BlockingString:
        def __str__(self):
            converting.set()
            if not release.wait(3):
                raise RuntimeError("test did not release conversion")
            return "converted"

    runtime.publish_status("camera", {"present": True})
    runtime.register_command("test", "ping", lambda: "pong")
    accepted = runtime.enqueue_command({"target": "test", "name": "ping", "args": {}})
    with ThreadPoolExecutor(max_workers=2) as pool:
        publish = pool.submit(runtime.publish_status, "camera", {"extra": BlockingString()})
        try:
            assert converting.wait(1)
            snapshot = pool.submit(runtime.status).result(timeout=1)
            assert snapshot == {"camera": {"present": True}}
            pool.submit(runtime.drain_commands).result(timeout=1)
            result = pool.submit(runtime.command_result, accepted["id"]).result(timeout=1)
            assert result["value"] == "pong"
            assert not publish.done()
        finally:
            release.set()
        publish.result(timeout=1)
    assert runtime.status()["camera"] == {"present": True, "extra": "converted"}


def test_defensive_coercion_remains_unbounded_by_default():
    values = np.zeros(MAX_STATUS_ELEMENTS + 1)
    assert len(JsonCoercer()(values)) == values.size
