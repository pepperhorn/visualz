# Handoff: 0010 — Reject oversized commands at the server; bound image metadata (lead → codex)

- **Date:** 2026-11-14
- **Type:** quick
- **Ledger:** 0010 · **Spec:** docs/specs/0001-audio-reactive-visuals.md · **Plan:** — (follow-ups from the reviews of PR #5: https://github.com/pepperhorn/visualz/pull/5#pullrequestreview-5907713192 and https://github.com/pepperhorn/visualz/pull/5#pullrequestreview-5907765644)
- **Branch:** orch/0010-bound-command-args · **Worktree:** created by T3
- **PR:** —
- **Base commit:** e98f86845036cf453750b67324216337dac8c57b
- **Port (if running a server):** 5300
- **Status:** open

## Goal
Defence in depth for the command path, which any phone on the venue Wi-Fi can reach:

1. **Bound command arguments on arrival.** `POST /api/stage/command` and the WebSocket command message accept arbitrary JSON args; a 4097-element `asset_id` list reached `drain_commands` on the render thread. Reject a command whose args exceed the same element limit used for status (reuse the constant and the counting function from `visualz/state/json_safe.py` / `runtime.py`; do not define a second limit), and cap the request body size for this endpoint, with HTTP 413 (or 400) and a WS error reply carrying the client's id. Rejected commands are never queued.
2. **`publish_image` metadata** is still coerced inside the runtime lock with no size limit: coerce outside the lock and apply the same limit.
3. **The size check calls `len()` on arbitrary objects**, so a misbehaving object can raise something other than `ValueError`: make the check raise only `ValueError` (wrap or avoid the call).

## Scope
- **Files you own:** `visualz/server/__init__.py`, `visualz/state/runtime.py`, `visualz/state/json_safe.py`, `tests/server/test_server.py`, `tests/state/test_runtime.py`, your two handoff files.
- **Do not touch:** everything else. Item 0009 is editing `visualz/state/__init__.py` and `tests/state/test_store.py` in parallel.

## Acceptance criteria
- [ ] Test: an HTTP command with a 5000-element arg is rejected with a 4xx and a clear message, and nothing is queued; same over WebSocket, with the id echoed.
- [ ] Test: an over-size request body is rejected without being parsed into memory in full (use aiohttp's limits).
- [ ] Test: normal commands, including one with a few hundred elements of args, still work.
- [ ] Test: `publish_image` with oversized metadata raises `ValueError` quickly and leaves the previous image in place; coercion is not under the lock.
- [ ] Test: an object whose `__len__` raises produces `ValueError` (publisher side) and never breaks telemetry.
- [ ] Media upload endpoints keep their own, larger limits unchanged.
- [ ] Verify passes.

## Verify with
```bash
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q   # if xvfb is available
```

## Known gotchas / decisions already made
- Use `python3.11` for the venv (system `python3` is 3.14; pygame has no wheel for it). `uv` is not on PATH.
- Since PR #5, command status published by `drain_commands` is a bounded summary that cannot raise; keep that.
- No schema or dependency changes.
- GBrain: unavailable.

## Open questions
None.

---
## Receiver ack

I will reject oversized command arguments before enqueueing through HTTP or WebSocket, add an endpoint-specific body limit without changing upload limits, bound and coerce image metadata outside the runtime lock, and normalize size-check failures to ValueError. I will change only the six assigned code/test files and task handoffs, run the required verification, and open a draft PR on orch/0010-bound-command-args. No open questions. GBrain: unavailable.

---
## Return (implementer → lead; write a separate …--codex-to-lead.md)
