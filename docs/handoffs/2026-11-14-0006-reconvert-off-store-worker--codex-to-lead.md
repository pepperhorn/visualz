# Handoff: 0006 — Reconversion worker scope blocker (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0006 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) · **Plan:** — (quick)
- **Branch:** orch/0006-reconvert-off-store-worker
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-b6da7119-c467d96c754936c5
- **PR:** draft PR on the branch above; URL supplied in the final response and PR body
- **Base commit:** 108ff559be065b8e77b3da644569fd3465f44c17 (implementation base from dispatch)
- **Port:** 5260
- **Status:** blocked

## Goal
Move reconversion to a serial media-owned worker, keep Store.submit responsive within 100 ms, preserve existing assets and failure status, and bound shutdown.

## Context you need
Read the [dispatch and receiver acknowledgement](2026-11-14-0006-reconvert-off-store-worker--lead-to-codex.md) and [foundation contracts](2026-11-14-0001-t1-scaffold--codex-to-lead.md). No implementation changes have been made. Receiver acknowledgement is committed as a895684d26c778b056caced9e72d1da9e02b260a.

## Scope
- **In / files owned:** `visualz/media/__init__.py`, `visualz/media/archive.py`, new `tests/media/test_reconvert.py`, and both 0006 handoffs.
- **Out:** all other files, including the ledger; no schemas, dependencies or unrelated contracts may change.
- **Scope needed:** `visualz/__main__.py` for worker shutdown wiring, and `tests/media/test_profiles.py` for the existing reconversion test's completion wait.

## Acceptance criteria
- [ ] Store.submit applies within 100 ms during a slow fake conversion.
- [ ] Fresh outputs; failure removes new directory, preserves old asset, publishes status.media.error.
- [ ] Reconversions run serially.
- [ ] Shutdown completes within a few seconds; partial-directory behavior documented.
- [ ] Schemas/dependencies/contracts unchanged except authorized reconversion behavior.
- [ ] Required verification passes.

## Verify with
```bash
uv venv --python 3.11 --seed .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q
```

## Known gotchas / decisions already made
GBrain: unavailable. Python 3.11 is installed at `/home/t3box/.local/bin/python3.11`, but `uv` is absent from PATH. The specified setup command was attempted and exited 127: `/bin/bash: line 7: uv: command not found`. No environment was created and no tests were run.

## Open questions
1. Expand file ownership to `visualz/__main__.py` so `register_commands(store)` can return the media worker and the existing ExitStack can register its close callback before closing Store? Presently the return is ignored (`visualz/__main__.py:61`); Store has no worker shutdown registration API (`visualz/state/__init__.py:357`). This avoids monkeypatching Store.close or depending on private store internals.
2. Expand ownership to `tests/media/test_profiles.py` so `test_r2_2_auto_resolution_and_registered_reconvert` waits for media completion? At lines 83–84 it currently calls `store._pending.join()` then immediately reads `status.media.regenerated_asset`. Once conversion leaves that queue, join no longer waits for it and the existing test becomes racy/fails.

## Receiver ack
Lead acknowledges through the ledger; implementer does not edit it.

## Return (implementer → lead)
- **Outcome:** blocked, per the dispatch scope rule and AGENTS.md §7. No code changed.
- **What changed:** committed receiver acknowledgement and this self-contained blocked return.
- **Verification output:** setup failed with `uv: command not found`; lint/tests not run. Read-only inspection confirmed both scope blockers above.
- **Decisions made:** no Store.close monkeypatch, private-state shutdown polling, test monkeypatch or global interpreter-exit-only lifecycle workaround. Request explicit ownership of the real lifecycle wiring and existing test instead.
- **Out-of-scope issues found:** existing reconversion test couples completion to the store queue; lifecycle wiring is outside assigned files.
- **Follow-ups:** lead to expand scope/re-dispatch; use Python 3.11 venv directly or make uv available. Then implement a single serial conversion worker, cancellable/bounded shutdown, and regression tests.
- **For GBrain (lead to promote):** worker extraction tasks should own application cleanup wiring and tests that assume the previous queue provides completion.
