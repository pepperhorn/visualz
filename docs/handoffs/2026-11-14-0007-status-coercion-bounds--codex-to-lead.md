# Handoff: 0007 — Bounded status coercion outside the runtime lock (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0007 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) · **Plan:** — (quick item)
- **Branch:** orch/0007-status-coercion-bounds
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-41a2c306-ab370d26783ea5dc
- **PR:** https://github.com/pepperhorn/visualz/pull/5 (draft)
- **Base commit:** 108ff559be065b8e77b3da644569fd3465f44c17
- **Initial implementation commit:** eb65a1aa25e5c470b92f370dcc62b31eaa2b12f6
- **Review revision base:** 1b586731055e96e084a482c98d3b1c0cdb2ff92b; this handoff and the following branch commit address [review 5907713192](https://github.com/pepperhorn/visualz/pull/5#pullrequestreview-5907713192).
- **Port:** 5270 (no server started)
- **Status:** closed

## Goal
Address F4 from PR #1: prevent worker status conversion from holding the runtime lock or converting an oversized camera frame. See the [dispatch and receiver acknowledgement](2026-11-14-0007-status-coercion-bounds--lead-to-codex.md) and [existing runtime contracts](2026-11-14-0001-t1-scaffold--codex-to-lead.md).

## Scope
- **In:** size preflight before JSON coercion, coercion before lock acquisition, atomic rejection, safe command-status summaries, copy-on-write status snapshots, and regression tests.
- **Out:** schemas, dependencies, server telemetry/supervision, command argument boundary validation, image API changes, other quick items, and hardware verification.
- **Files owned/changed:** `visualz/state/runtime.py`, `visualz/state/json_safe.py`, new `tests/state/test_runtime.py`, and the two 0007 handoffs. No other files changed; ledger untouched.

## Acceptance criteria
- [x] A 480×270×3 NumPy frame raises a top-level-target-specific ValueError naming the 4096 limit in under 5 ms; earlier status remains intact, including other fields in the rejected update.
- [x] A 2048-float spectrum is accepted and detached from its source array.
- [x] While an object's string conversion blocks, another thread can read status and drain/complete a queued command.
- [x] `MAX_STATUS_ELEMENTS` is the single limit constant, documented alongside the runtime handler/publication contract.
- [x] Defensive send-time coercion remains tolerant; existing telemetry failure/restart coverage passes.
- [x] Oversized command arguments and results never escape through command status; callbacks receive complete results and the next queued command runs. Injected exceptions from both ordinary and slow-handler status publication are isolated.
- [x] Binary frame buffers and 200k-entry dictionaries reject in under 5 ms; mappings count keys and values recursively, and aggregate failures identify the target instead of blaming a nested field.
- [x] Status deep copying runs outside the lock and retains an isolated snapshot across status and image updates/removals.
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
- The aggregate budget counts sequence slots, array elements, and two slots per dict entry (one key and one value) across the complete update. Keys and values are recursively checked; bytes/bytearray count their length, memoryview counts nbytes, and other non-string Sized objects count len before stringification. Arrays use metadata rather than counting their converted lists again. Object arrays are traversed; cycles use the existing ancestry convention. A one-field update leaves 4094 slots for its array/list after counting its mapping pair. A 2048-bin spectrum still fits. Errors identify the top-level publication target and say its total size exceeds 4096.
- Oversized updates fail before any runtime status mutation. The bounded traversal and coercion both run outside the runtime lock; the lock protects a copy-on-write target replacement. status() shallow-copies target references under the lock and deep-copies them after releasing it. Image updates/removals also replace the images target dictionary so concurrent snapshots remain stable. Existing string/NaN/NumPy conversion and warning behavior is retained.

## Open questions
None.

---
## Receiver ack
Lead acknowledges through the ledger; implementer leaves the ledger unchanged.

---
## Return (implementer → lead)
- **Outcome:** done; ready for cross-family review.
- **Commits:** initial acknowledgement 703d8b7; implementation eb65a1a; original handoffs 8df0422 and 1b58673; review corrections are committed together with this updated handoff.
- **What changed:** publication-only aggregate size validation, conversion before atomic status replacement, copy-outside-lock snapshots, and 23 regression cases. Review F1: commands publish only target/name/id, ok, error text (at most 256 characters), and duration; the full result remains in the result cache/client callback unchanged. Both command-status publications share an exception guard, independent of result delivery. F2/F3: mappings and buffers share the budget, with a top-level aggregate error.
- **Verification output:**
```text
$ .venv/bin/ruff check . && .venv/bin/pytest
All checks passed!
collected 89 items
86 passed, 3 skipped in 7.63s

$ xvfb-run -a .venv/bin/pytest -q
89 passed in 9.16s
```
- **Decisions made:** lead decisions F1–F3 and optional copy-on-write snapshot suggestion implemented within owned files. Strings retain existing coercion semantics; command error summaries explicitly truncate text. Command result content and server argument validation remain unchanged. No ADR requested.
- **Out-of-scope issues found:** none.
- **Follow-ups:** cross-family re-review. Separately consider bounding command arguments at the HTTP/WS boundary (review suggestion 2); enqueue_command currently deep-copies unbounded args. This needs a later scoped task; no server changes here. No PR watching or polling performed.
- **For GBrain (lead to promote):** guard NumPy sizes before `.tolist()` and perform worker conversion before acquiring shared render/runtime locks; send-time defensive conversion remains independently tolerant.
