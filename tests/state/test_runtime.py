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
    with pytest.raises(ValueError, match=rf"camera: total size exceeds.*{MAX_STATUS_ELEMENTS}"):
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
    [list(range(MAX_STATUS_ELEMENTS - 2)), np.zeros(MAX_STATUS_ELEMENTS - 2)],
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
    with pytest.raises(ValueError, match=rf"test: total size exceeds.*{MAX_STATUS_ELEMENTS}"):
        runtime.publish_status("test", {"value": value})
    assert runtime.status() == {}


def test_object_array_cannot_hide_oversized_sequence():
    values = np.empty(1, dtype=object)
    values[0] = [0] * (MAX_STATUS_ELEMENTS + 1)
    with pytest.raises(ValueError, match=rf"test: total size exceeds.*{MAX_STATUS_ELEMENTS}"):
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


@pytest.mark.parametrize("kind", ["bytes", "bytearray", "memoryview", "dict"])
def test_binary_frames_and_large_mappings_rejected_quickly(kind):
    runtime = Runtime()
    if kind == "dict":
        value = dict.fromkeys(range(200_000), 0)
    else:
        frame = np.zeros((480, 270, 3), dtype=np.uint8)
        value = {"bytes": bytes, "bytearray": bytearray, "memoryview": memoryview}[kind](
            frame.tobytes()
        )
    started = perf_counter()
    with pytest.raises(ValueError, match=rf"^camera: total size exceeds.*{MAX_STATUS_ELEMENTS}"):
        runtime.publish_status("camera", {"frame": value})
    assert perf_counter() - started < 0.005
    assert runtime.status() == {}


def test_mapping_keys_and_values_share_aggregate_budget():
    runtime = Runtime()
    # Outer key/value pair plus 2047 inner key/value pairs exhaust the budget.
    runtime.publish_status("test", {"value": dict.fromkeys(range(2047), 0)})
    previous = runtime.status()
    with pytest.raises(ValueError, match=r"^test: total size exceeds"):
        runtime.publish_status("test", {"value": dict.fromkeys(range(2048), 0)})
    with pytest.raises(ValueError, match=r"^test: total size exceeds"):
        runtime.publish_status("test", {"value": {tuple(range(4096)): 0}})
    assert runtime.status() == previous


def test_aggregate_error_names_target_instead_of_last_nested_field():
    with pytest.raises(ValueError) as raised:
        Runtime().publish_status("audio", {"spectrum": [0] * 4000, "x": [0] * 100})
    assert str(raised.value) == f"audio: total size exceeds the {MAX_STATUS_ELEMENTS} element status limit"


def test_oversized_command_result_does_not_interrupt_drain():
    runtime = Runtime()
    values = list(range(MAX_STATUS_ELEMENTS + 1))
    callbacks = []
    runtime.register_command("test", "echo", lambda value: values if value == "large" else value)
    runtime.enqueue_command(
        {"id": "large", "target": "test", "name": "echo", "args": {"value": "large"}},
        callbacks.append,
    )
    # Drain one first so its bounded summary can be inspected.
    runtime.drain_commands()
    summary = runtime.status()["commands"]
    assert summary["last"] == {"id": "large", "target": "test", "name": "echo"}
    assert summary["result"]["ok"] is True
    assert "value" not in summary["result"] and "args" not in summary["last"]
    assert callbacks[0]["value"] == values
    assert runtime.command_result("large")["value"] == values
    callbacks.clear()
    for command_id, value in (("large-again", "large"), ("next", "ok")):
        runtime.enqueue_command(
            {"id": command_id, "target": "test", "name": "echo", "args": {"value": value}},
            callbacks.append,
        )
    runtime.drain_commands(budget_ms=1000)
    assert [result["id"] for result in callbacks] == ["large-again", "next"]
    assert callbacks[0]["value"] == values and callbacks[1]["value"] == "ok"


@pytest.mark.parametrize("fail_slow_publication", [False, True])
def test_publication_exceptions_never_prevent_callbacks_or_next_command(
    monkeypatch, caplog, fail_slow_publication
):
    from itertools import count
    import visualz.state.runtime as runtime_module

    runtime = Runtime()
    callbacks = []
    publish = runtime.publish_status

    def broken_publication(target, values):
        if not fail_slow_publication or "slow_handler" in values:
            raise RuntimeError("injected publication failure")
        publish(target, values)

    # Deterministically exercise the slow-handler publication without sleeping.
    monkeypatch.setattr(runtime_module.time, "perf_counter", lambda ticks=count(step=0.006): next(ticks))
    monkeypatch.setattr(runtime, "publish_status", broken_publication)
    runtime.register_command("test", "ping", lambda: "pong")
    for command_id in ("first", "next"):
        runtime.enqueue_command(
            {"id": command_id, "target": "test", "name": "ping", "args": {}}, callbacks.append
        )
    runtime.drain_commands(budget_ms=1000)
    assert [result["id"] for result in callbacks] == ["first", "next"]
    assert all(result["value"] == "pong" for result in callbacks)
    assert "Command status publication failed" in caplog.text


def test_command_error_status_truncated_but_client_result_kept():
    runtime = Runtime()
    message = "x" * 10_000
    callbacks = []

    def fail():
        raise ValueError(message)

    runtime.register_command("test", "fail", fail)
    runtime.enqueue_command({"target": "test", "name": "fail", "args": {}}, callbacks.append)
    runtime.drain_commands()
    assert callbacks[0]["error"] == message
    assert runtime.command_result(callbacks[0]["id"])["error"] == message
    summary = runtime.status()["commands"]
    assert summary["result"]["ok"] is False
    assert summary["error"] == summary["result"]["error"] == message[:256]


def test_status_deepcopy_outside_lock_preserves_snapshot_during_updates(monkeypatch):
    import visualz.state.runtime as runtime_module

    runtime = Runtime()
    runtime.publish_status("audio", {"levels": [1, 2]})
    runtime.publish_image("latest", b"old", metadata={"sequence": 1})
    copying = Event()
    release = Event()
    deepcopy = runtime_module.deepcopy

    def blocked_copy(value):
        copying.set()
        assert release.wait(3)
        return deepcopy(value)

    monkeypatch.setattr(runtime_module, "deepcopy", blocked_copy)
    with ThreadPoolExecutor(max_workers=2) as pool:
        snapshot = pool.submit(runtime.status)
        try:
            assert copying.wait(1)
            pool.submit(runtime.publish_status, "audio", {"levels": [3]}).result(timeout=1)
            pool.submit(runtime.publish_image, "latest", b"new", "image/png").result(timeout=1)
            pool.submit(runtime.publish_image, "latest", None).result(timeout=1)
        finally:
            release.set()
        before = snapshot.result(timeout=1)
    assert before["audio"]["levels"] == [1, 2]
    assert before["images"]["latest"]["sequence"] == 1
    assert runtime.status() == {"audio": {"levels": [3]}, "images": {}}
    before["audio"]["levels"].append(99)
    assert runtime.status()["audio"]["levels"] == [3]


@pytest.mark.parametrize("publisher", ["status", "image"])
@pytest.mark.parametrize("error", [RuntimeError, TypeError, OverflowError, ValueError])
def test_broken_size_accessor_is_value_error_and_preserves_publication(publisher, error):
    runtime = Runtime()

    class BrokenSize:
        def __len__(self):
            raise error("broken size")

    runtime.publish_image("latest", b"previous", metadata={"sequence": 1})
    before = runtime.status()
    with pytest.raises(ValueError):
        if publisher == "status":
            runtime.publish_status("camera", {"bad": BrokenSize()})
        else:
            runtime.publish_image("latest", b"new", metadata={"bad": BrokenSize()})
    assert runtime.status() == before
    assert runtime.image("latest")[0] == b"previous"
    assert JsonCoercer()(BrokenSize())  # Defensive telemetry coercion remains tolerant.


def test_oversized_command_rejected_before_copy_or_queue():
    runtime = Runtime()

    class NoCopy(list):
        def __deepcopy__(self, memo):
            pytest.fail("Oversized args must not be copied")

    runtime.register_command("test", "echo", lambda value: value)
    with pytest.raises(ValueError, match=r"command.args: total size exceeds"):
        runtime.enqueue_command({
            "id": "oversized", "target": "test", "name": "echo",
            "args": {"value": NoCopy(range(5000))},
        })
    assert runtime._commands.empty()
    assert runtime.command_result("oversized") is None


def test_oversized_image_metadata_rejected_before_conversion_and_atomically():
    runtime = Runtime()
    runtime.publish_image("latest", b"previous", metadata={"sequence": 1})
    before = runtime.status()

    class NoConversion:
        __module__ = "numpy"
        size = 480 * 270 * 3

        def tolist(self):
            pytest.fail("Oversized metadata must not be converted")

    with pytest.raises(ValueError, match=r"images.latest: total size exceeds"):
        runtime.publish_image("latest", b"new", metadata={"frame": NoConversion()})
    assert runtime.image("latest")[0] == b"previous"
    assert runtime.status() == before


def test_image_metadata_coercion_outside_lock_and_detached():
    runtime = Runtime()
    converting, release = Event(), Event()

    class BlockingString:
        def __str__(self):
            converting.set()
            assert release.wait(3)
            return "converted"

    runtime.publish_image("latest", b"previous")
    metadata = {"extra": BlockingString(), "spectrum": np.array([1, 2])}
    with ThreadPoolExecutor(max_workers=2) as pool:
        publish = pool.submit(runtime.publish_image, "latest", b"new", "image/png", metadata)
        try:
            assert converting.wait(1)
            assert pool.submit(runtime.image, "latest").result(timeout=1)[0] == b"previous"
            pool.submit(runtime.publish_status, "stage", {"fps": 30}).result(timeout=1)
            assert pool.submit(runtime.status).result(timeout=1)["stage"]["fps"] == 30
        finally:
            release.set()
        publish.result(timeout=1)
    metadata["spectrum"][:] = 0
    assert runtime.status()["images"]["latest"]["spectrum"] == [1, 2]
    assert runtime.status()["images"]["latest"]["extra"] == "converted"


@pytest.mark.parametrize("publisher", ["status", "image", "command"])
def test_deep_publications_rejected_before_copy_or_conversion(publisher):
    runtime = Runtime()
    runtime.publish_status("camera", {"present": True})
    runtime.publish_image("latest", b"previous")
    previous = runtime.status()
    nested = 0
    for _ in range(500):
        nested = [nested]
    with pytest.raises(ValueError, match=r"nesting exceeds 32 levels"):
        if publisher == "status":
            runtime.publish_status("camera", {"deep": nested})
        elif publisher == "image":
            runtime.publish_image("latest", b"new", metadata={"deep": nested})
        else:
            runtime.register_command("test", "echo", lambda value: value)
            runtime.enqueue_command({
                "id": "deep", "target": "test", "name": "echo", "args": {"value": nested},
            })
    assert runtime.status() == previous
    assert runtime.image("latest")[0] == b"previous"
    assert runtime._commands.empty()
    assert runtime.command_result("deep") is None


def test_shared_depth_limit_boundary_and_cycles():
    from visualz.state.json_safe import MAX_JSON_DEPTH

    nested = 0
    for _ in range(MAX_JSON_DEPTH):
        nested = [nested]
    coerce = JsonCoercer()
    assert coerce(nested, max_elements=MAX_STATUS_ELEMENTS) == nested
    with pytest.raises(ValueError, match="nesting exceeds"):
        coerce([nested], max_elements=MAX_STATUS_ELEMENTS)
    cycle = []
    cycle.append(cycle)
    coerce.check_size(cycle, "cycle", MAX_STATUS_ELEMENTS)
