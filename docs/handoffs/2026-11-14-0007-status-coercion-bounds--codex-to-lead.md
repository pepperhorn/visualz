# Handoff: 0007 — Bounded status coercion outside the runtime lock (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0007 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) · **Plan:** — (quick item)
- **Branch:** orch/0007-status-coercion-bounds
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-41a2c306-ab370d26783ea5dc
- **PR:** https://github.com/pepperhorn/visualz/pull/5 (draft)
- **Base commit:** 108ff559be065b8e77b3da644569fd3465f44c17
- **Implementation commit:** eb65a1aa25e5c470b92f370dcc62b31eaa2b12f6
- **Port:** 5270 (no server started)
- **Status:** closed

## Goal
Address F4 from PR #1: prevent worker status conversion from holding the runtime lock or converting an oversized camera frame. See the [dispatch and receiver acknowledgement](2026-11-14-0007-status-coercion-bounds--lead-to-codex.md) and [existing runtime contracts](2026-11-14-0001-t1-scaffold--codex-to-lead.md).

## Scope
- **In:** size preflight before JSON coercion, coercion before lock acquisition, atomic rejection, and regression tests.
- **Out:** schemas, dependencies, server telemetry/supervision, image publication, other quick items, and hardware verification.
- **Files owned/changed:** `visualz/state/runtime.py`, `visualz/state/json_safe.py`, new `tests/state/test_runtime.py`, and the two 0007 handoffs. No other files changed; ledger untouched.

## Acceptance criteria
- [x] A 480×270×3 NumPy frame raises a key-specific ValueError naming the 4096 limit in under 5 ms; earlier status remains intact, including other fields in the rejected update.
- [x] A 2048-float spectrum is accepted and detached from its source array.
- [x] While an object's string conversion blocks, another thread can read status and drain/complete a queued command.
- [x] `MAX_STATUS_ELEMENTS` is the single limit constant, documented alongside the runtime handler/publication contract.
- [x] Defensive send-time coercion remains tolerant; existing telemetry failure/restart coverage passes.
- [x] Required lint and tests pass, including all display tests under Xvfb.

## Verify with
```bash
# Lead's corrected setup command (Python 3.11):
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q
```

## Known gotchas / decisions already made
- GBrain: unavailable; no pages consulted or written.
- Initial setup found no `uv` on PATH; installed it into an isolated `/tmp/visualz-0007-tools` environment, then used it to create the Python 3.11.18 project venv. The project installed successfully. The lead subsequently supplied the simpler setup command above. No repository dependency/setup changes.
- The optional `max_elements` coercer argument is used only by `publish_status`. NumPy `.size` is checked before `.tolist()`; the bound is never swallowed by NumPy conversion's fallback exception handler.
- The aggregate budget counts sequence slots and array elements across the complete update, including nested sequence containers. Mappings route traversal without consuming sequence slots. Arrays are counted from metadata rather than again from their converted lists. Object arrays are traversed to prevent hiding a large nested sequence; cycles use the existing ancestry convention. Exact-bound flat lists and 64×64 arrays are accepted.
- Oversized updates fail before any runtime status mutation. The bounded traversal and coercion both run outside the runtime lock; the lock only protects the final merge. Existing string/NaN/NumPy conversion and warning behavior is retained.

## Open questions
None.

---
## Receiver ack
Lead acknowledges through the ledger; implementer leaves the ledger unchanged.

---
## Return (implementer → lead)
- **Outcome:** done; ready for cross-family review.
- **Commits:** acknowledgement 703d8b7; implementation eb65a1a; return handoff follows.
- **What changed:** publication-only aggregate size validation, lock-free conversion before atomic status merge, and 12 regression cases for limits, concurrency, source isolation and tolerant defensive coercion.
- **Verification output:**
```text
$ .venv/bin/ruff check . && .venv/bin/pytest
All checks passed!
collected 78 items
75 passed, 3 skipped in 7.39s

$ xvfb-run -a .venv/bin/pytest -q
78 passed in 9.06s
```
- **Decisions made:** aggregate slot accounting and publication-only opt-in as described above; no ADR requested.
- **Out-of-scope issues found:** none.
- **Follow-ups:** review this PR; no PR watching or polling performed.
- **For GBrain (lead to promote):** guard NumPy sizes before `.tolist()` and perform worker conversion before acquiring shared render/runtime locks; send-time defensive conversion remains independently tolerant.
