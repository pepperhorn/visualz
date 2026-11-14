# Handoff: 0006 — Reconversion runs off the store worker (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0006 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) · **Plan:** — (quick)
- **Branch:** orch/0006-reconvert-off-store-worker
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-b6da7119-c467d96c754936c5
- **PR:** https://github.com/pepperhorn/visualz/pull/3 (draft)
- **Base commit:** 5a1b569d62f48d70397c7e8627e490c079e2a88c (worktree base; implementation foundation 108ff559be065b8e77b3da644569fd3465f44c17)
- **Port:** 5260 (no dev server started)
- **Status:** closed

## Goal
Move reconversion to a serial media-owned worker, keep Store.submit responsive within 100 ms, preserve existing assets and failure status, and bound shutdown.

## Context you need
Read the [dispatch and receiver acknowledgement](2026-11-14-0006-reconvert-off-store-worker--lead-to-codex.md), [scope answers](https://github.com/pepperhorn/visualz/blob/e93f769372c11927b29f4f3be2c2142b58081564/docs/handoffs/2026-11-14-0006-reconvert-off-store-worker--lead-to-codex-answers.md), and [foundation contracts](2026-11-14-0001-t1-scaffold--codex-to-lead.md). This return supersedes the blocked return at 4b0b513; the lead authorized both additional files. No main merge or rebase was needed.

## Scope
- **In / files owned:** `visualz/media/__init__.py`, `visualz/media/archive.py`, new `tests/media/test_reconvert.py`, and both 0006 handoffs; scope answers add `visualz/__main__.py` for shutdown wiring only and the completion wait in `tests/media/test_profiles.py::test_r2_2_auto_resolution_and_registered_reconvert`.
- **Changed:** media module, new reconversion tests, main shutdown wiring, only the authorized existing test function, and both handoffs. Archive module needed no changes.
- **Out:** all other files and ledger; schemas/dependencies/unrelated contracts unchanged.

## Acceptance criteria
- [x] Store.submit applies within 100 ms during a slow fake conversion (test waits for the actual blackout state notification).
- [x] Fresh outputs; failure removes the new directory, preserves the old asset byte-for-byte, and publishes status.media.error. Subsequent conversion succeeds and clears the error.
- [x] Two reconversions stay serial; second converter cannot start until the first is released. Both fresh assets are registered.
- [x] Shutdown kills/reaps an active converter subprocess, skips queued conversions and removes its partial directory. An isolated process test verifies exit even with a converter that cannot cooperate.
- [x] Schemas/dependencies/contracts unchanged except authorized reconversion worker behavior.
- [x] Required verification passes, including the complete suite under Xvfb.

## Verify with
```bash
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q
git diff --check
```

## Known gotchas / decisions already made
GBrain: unavailable; no pages consulted or written. Python 3.11.18 environment setup succeeded using the lead's corrected command. The initial uv attempt failed before the scope answers; it is no longer a blocker.

## Open questions
None.

## Receiver ack
Lead acknowledges through the ledger; implementer does not edit it.

## Return (implementer → lead)
- **Outcome:** done; draft PR updated for cross-family review. No PR watch or polling performed.
- **Commits:** a895684 acknowledges the initial dispatch, 4b0b513 records the original scope blocker; the following implementation commit updates both handoffs and contains the fix. Reviewed head is supplied in the final response.
- **What changed:** `register_commands(store)` now returns `ReconvertWorker`, a single media-owned daemon thread with `submit`, public `wait_idle(timeout=None)` and `close`. Conversion reads/copies original media and performs decoding entirely off the store queue; only the final short metadata patch uses Store.patch, followed by status publication. Main registers close on ExitStack before Store closes. Existing command acknowledgement and regenerated_asset/error fields are preserved. The old queue-based test wait now uses the public idle API and closes the worker.
- **Verification output:**
```text
$ .venv/bin/ruff check . && .venv/bin/pytest
All checks passed!
collected 71 items
68 passed, 3 skipped in 10.28s

$ xvfb-run -a .venv/bin/pytest -q
71 passed, 1 warning in 11.99s

$ git diff --check
(no output; exit 0)
```
  Headless skips are the existing display-dependent checks; they all pass under Xvfb. The warning is pygame's upstream pkg_resources deprecation. Five new tests cover control latency/serialization, failure cleanup/recovery, cancellation/queue discard, actual process exit with an uncooperative converter, and invalid asset requests without worker death.
- **Decisions made:** use a dedicated daemon thread instead of ThreadPoolExecutor, whose interpreter-exit join can wait for an uninterruptible task even after shutdown(wait=False). Close cancels pending work and signals conversion cancellation, joining for at most two seconds. A thread-local cancellation event lets existing ingest/reconvert signatures stay unchanged; ffmpeg and ffprobe both use a Popen communication loop with 100 ms cancellation checks on this worker. Ordinary synchronous ingest retains subprocess.run and the previous timeouts/priority/thread limits. Cancelling or timing out a child kills and reaps it before ingest removes the fresh directory. Final registration failure also removes the fresh output. Retained original writes now occur inside ingest's cleanup guard.
- **Partial-directory behavior:** normal subprocess cancellation removes the new UUID directory. Python/native image operations cannot be forcibly interrupted; after the two-second join cap, the daemon may finish later and will discard its output on the cancellation check. If the process exits first, an unregistered partial UUID directory can remain on disk; it is never registered or selected, and the old asset stays intact. The isolated process test verifies this fallback. No automatic orphan cleanup added.
- **Out-of-scope issues found:** none newly blocking; hardware behavior on the Pi was not tested.
- **Follow-ups:** lead to arrange cross-family review. If item 0008 merges first, reconcile its independent changes in tests/media/test_profiles.py when updating this branch, as the scope answers specify.
- **For GBrain (lead to promote):** worker extraction must include cleanup wiring and tests that used the original queue as a completion barrier. A daemon fallback and cooperative subprocess cancellation avoid executor shutdown hanging process exit.
