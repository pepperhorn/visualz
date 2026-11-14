# Handoff: 0010 — Bound command arguments and image metadata (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0010 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) · **Plan:** — (quick)
- **Dispatch:** [lead → codex](2026-11-14-0010-bound-command-args--lead-to-codex.md)
- **Branch:** orch/0010-bound-command-args
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-a3b90767-d9bddebb355b5d35
- **PR:** https://github.com/pepperhorn/visualz/pull/6 (draft)
- **Base commit:** 7e90fe1 (starting checkout; includes the dispatch)
- **Implementation commits:** b47470e74990f80e1c08713676bb099ba5891ee5; review fixes bc0da597d6dca8d0c7bf804f25f874daf2ee7be4
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
  ======================= 131 passed, 3 skipped in 11.29s ========================
  134 passed, 1 warning in 12.76s
  git diff --check: clean
  ```
  The xvfb warning is pygame's existing pkg_resources deprecation. Without xvfb, three display-dependent tests skip.
- **Decisions made:** the command endpoint alone gets a 64 KiB body cap, separate from the shared 4096-element aggregate budget. The limited request is cloned at the start of the error middleware so the handler and queue-full error reply share its cached JSON and preserve the client id. WS command frames now share the HTTP 64 KiB cap (measured in UTF-8 bytes); other message types retain the existing 1 MiB cap. Oversized args are also rejected through the shared enqueue path. Image metadata includes the generated content_type/bytes fields in its final aggregate budget; the merged metadata mapping is checked once before conversion, with no duplicate size traversal. Custom sizing failures are normalized to ValueError without weakening tolerant send-time coercion. The prior oversized-args/result drain regression now uses small args that produce an oversized result, preserving coverage of bounded command status and subsequent callbacks under the new argument contract.
- **Out-of-scope issues found:** none.
- **Follow-ups:** lead to arrange cross-family review and decide merge; no further implementation work outstanding.
- **For GBrain (lead to promote):** aiohttp cloned requests share the stream but have separate JSON/body caches; apply an endpoint-specific clone before middleware that rereads a body for an error response.


## Review fixes (2026-11-14)
Addressed [review 5907857475](https://github.com/pepperhorn/visualz/pull/6#pullrequestreview-5907857475) under the lead's explicit decisions:

- Shared `MAX_JSON_DEPTH = 32` in `json_safe.py`, enforced by an iterative (non-recursive) aggregate size/depth walk before command deepcopy or publisher conversion. NumPy dimensionality counts toward depth. Ancestor tracking still handles cycles and counts repeated references in separate branches.
- HTTP JSON parser RecursionError becomes a readable 400; WS catches it and returns an error while preserving the connection. The id is echoed after successful parsing (500-level test); it is null when the decoder cannot produce an envelope (2000-level test).
- Command-only WS cap measures encoded UTF-8 bytes against `MAX_COMMAND_BODY`. Tests reject both 900 KB ASCII and 40,000 non-ASCII characters, echo the id, prove nothing queued, and successfully apply a similarly large patch on the same socket.
- Deep command tests construct raw JSON to avoid the client's encoder limits. Both 500- and 2000-deep payloads are rejected over HTTP and WS, then a following WS command succeeds. 500-deep status/image tests verify ValueError and unchanged prior publications. A boundary test covers exactly the allowed depth and cycles.
- Replaced the new image metadata test's 5 ms wall-clock assertion with a NumPy-like conversion sentinel whose `tolist()` fails if called. Removed the redundant raw-metadata size walk; the merged mapping is checked/coerced once outside the lock, including generated content_type/bytes fields.
- Only the originally owned files and this return handoff changed. Full verification above rerun on the review fix. No open questions or outstanding implementation fixes; ready for cross-family re-review.
