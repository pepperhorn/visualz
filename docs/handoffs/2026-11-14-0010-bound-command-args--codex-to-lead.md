# Handoff: 0010 — Bound command arguments and image metadata (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0010 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) · **Plan:** — (quick)
- **Dispatch:** [lead → codex](2026-11-14-0010-bound-command-args--lead-to-codex.md)
- **Branch:** orch/0010-bound-command-args
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-a3b90767-d9bddebb355b5d35
- **PR:** pending creation after this handoff commit
- **Base commit:** 7e90fe1 (starting checkout; includes the dispatch)
- **Implementation commit:** b47470e74990f80e1c08713676bb099ba5891ee5
- **Port:** 5300 (no server left running)
- **Status:** closed

## Goal
Reject oversized commands before queueing, bound image metadata outside the runtime lock, and make size-check failures consistently raise ValueError.

## Scope
- **In / files owned:** `visualz/server/__init__.py`, `visualz/state/runtime.py`, `visualz/state/json_safe.py`, `tests/server/test_server.py`, `tests/state/test_runtime.py`, and the two 0010 handoff files.
- **Out / do not touch:** all other files, especially item 0009's store implementation/tests and the lead-owned ledger. No schema or dependency changes.

## Acceptance criteria
- [x] HTTP rejects 5000-element args with 400 and a clear message; WS returns an error with the client id. Neither queues or caches a pending result.
- [x] HTTP body limit uses aiohttp's request limit, returning 413 before JSON parsing. A chunked test withholds most of the body until rejection arrives, demonstrating early rejection.
- [x] Commands with 300-element args work over HTTP and WS; normal command/result and overload behavior remain covered.
- [x] Oversized image metadata raises ValueError quickly without replacing the prior image or status.
- [x] Blocking image metadata conversion leaves the runtime lock free for image reads and status reads/writes; NumPy metadata is detached from publishers.
- [x] Raising __len__ methods yield ValueError for status/image publishers; prior publications and subsequent telemetry remain healthy.
- [x] Upload/import limits are unchanged; verification passes.

## Verify with
```bash
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q
git diff --check
git diff --stat main...HEAD
```

## Known gotchas / decisions already made
GBrain: unavailable. No GBrain pages used.

## Open questions
None.

## Return
- **Outcome:** done; ready for lead review dispatch. No merge or PR watching performed.
- **What changed:** exposed the existing aggregate counter through `JsonCoercer.check_size`, reused `MAX_STATUS_ELEMENTS` for command args and image metadata, checked args before deepcopy/queueing, and prepared image metadata/content before locking and publishing atomically.
- **Verification output:**
  ```text
  All checks passed!
  ======================= 123 passed, 3 skipped in 11.27s ========================
  126 passed, 1 warning in 12.72s
  git diff --check: clean
  ```
  The xvfb warning is pygame's existing pkg_resources deprecation. Without xvfb, three display-dependent tests skip.
- **Decisions made:** the command endpoint alone gets a 64 KiB body cap, separate from the shared 4096-element aggregate budget. The limited request is cloned at the start of the error middleware so the handler and queue-full error reply share its cached JSON and preserve the client id. WS retains its existing 1 MiB message cap and rejects oversized args through the shared enqueue path. Image metadata includes the generated content_type/bytes fields in its final aggregate budget; the raw metadata is checked before constructing the merged mapping. Custom sizing failures are normalized to ValueError without weakening tolerant send-time coercion. The prior oversized-args/result drain regression now uses small args that produce an oversized result, preserving coverage of bounded command status and subsequent callbacks under the new argument contract.
- **Out-of-scope issues found:** none.
- **Follow-ups:** lead to arrange cross-family review and decide merge; no further implementation work outstanding.
- **For GBrain (lead to promote):** aiohttp cloned requests share the stream but have separate JSON/body caches; apply an endpoint-specific clone before middleware that rereads a body for an error response.
