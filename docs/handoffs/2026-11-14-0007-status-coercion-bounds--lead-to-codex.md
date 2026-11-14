# Handoff: 0007 — [quick] Status coercion: run outside the runtime lock and bound its cost (lead → codex)

- **Date:** 2026-11-14
- **Type:** quick
- **Ledger:** 0007 · **Spec:** docs/specs/0001-audio-reactive-visuals.md · **Plan:** — (quick item; follow-up from review r3 of PR #1: https://github.com/pepperhorn/visualz/pull/1#pullrequestreview-5903995535)
- **Branch:** orch/0007-status-coercion-bounds · **Worktree:** created by T3
- **PR:** —
- **Base commit:** 108ff559be065b8e77b3da644569fd3465f44c17
- **Port (if running a server):** 5270
- **Status:** open

## Goal
Review finding F4. `publish_status` coerces values to JSON-safe form while holding the runtime lock (`visualz/state/runtime.py` about line 220). A mistaken `publish_status('camera', {'frame': ndarray(480,270,3)})` held the lock for 492 ms, which stalls the main thread's `drain_commands` and `status()`. Fix: coerce before taking the lock, and reject oversized values with a clear `ValueError` raised to the publisher: any array or sequence over 4096 elements in total. A 2048-bin spectrum must still be accepted. The defensive send-time coercion and the telemetry supervisor must keep working as they do now.

## Scope
- **Files you own:** `visualz/state/runtime.py`, `visualz/state/json_safe.py`, new test file `tests/state/test_runtime.py`, your two handoff files
- **Do not touch:** everything else. Other quick fixes are running in parallel on `visualz/state/__init__.py`, `visualz/state/runtime.py`, `visualz/state/json_safe.py`, `visualz/media/__init__.py` and `visualz/schema/profiles.py`; if you need a change in a file you don't own, stop and say so in your return handoff.

## Acceptance criteria
- [ ] Test: publishing a 480×270×3 array raises `ValueError` naming the key and the limit, quickly (under 5 ms), and leaves earlier status values in place.
- [ ] Test: a 2048-float array is accepted.
- [ ] Test: coercion does not run under the lock (e.g. a value whose conversion blocks does not stop another thread calling `status()` or `drain_commands()`).
- [ ] The limit is one named constant, documented in the module docstring next to the handler contract.
- [ ] No change to JSON schemas, dependencies, or the documented contracts in `docs/handoffs/2026-11-14-0001-t1-scaffold--codex-to-lead.md` beyond what this handoff states.
- [ ] Verify passes.

## Verify with
```bash
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q   # if xvfb is available
```

## Known gotchas / decisions already made
- The system `python3` on the build box is 3.14, and pygame has no wheel for it (the source build fails without SDL headers). Build the venv with Python 3.11: `uv venv --python 3.11 --seed .venv && .venv/bin/pip install -e '.[dev]'`.
- The target is Raspberry Pi OS Bookworm (Python 3.11). Keep to the standard library and the dependencies already in `pyproject.toml`.
- GBrain: unavailable.

## Open questions
None.

---
## Receiver ack

---
## Return (implementer → lead; write a separate …--codex-to-lead.md)
