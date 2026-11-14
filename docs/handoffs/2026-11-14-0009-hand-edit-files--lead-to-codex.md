# Handoff: 0009 — Hand-edited document files: dismiss, cap, and never silently revert (lead → codex)

- **Date:** 2026-11-14
- **Type:** quick
- **Ledger:** 0009 · **Spec:** docs/specs/0001-audio-reactive-visuals.md (AC6, AC15; "invalid hand-edited files are kept and listed so they can be fixed") · **Plan:** — (follow-ups from reviews of PRs #1, #4, #5)
- **Branch:** orch/0009-hand-edit-files · **Worktree:** created by T3
- **PR:** —
- **Base commit:** e98f86845036cf453750b67324216337dac8c57b
- **Port (if running a server):** 5290
- **Status:** open

## Goal
Four related fixes in the Store's handling of per-document files (overlays, scenes, picture sets), all in `visualz/state/__init__.py`:

1. **Cap the rejected-files status (start-up failure).** Since PR #5, status values are limited to 4096 elements. `_publish_rejections` (about line 169) publishes every `*.invalid*.json` on disk, so 819 or more quarantined files in one collection make `Store()` raise `ValueError` at start-up and the stage never starts (review https://github.com/pepperhorn/visualz/pull/5#pullrequestreview-5907765644, N1, reproduced with 830 files). Publish at most the newest 50 per collection plus a total count, and make sure this publication can never stop the Store from starting.
2. **Dismiss a rejected file.** Add a command `overlays.dismiss_rejected` with args `{"collection": ..., "file": ...}` that deletes one quarantined `.invalid*.json` and its `.invalid*.txt` note, then republishes the list (review https://github.com/pepperhorn/visualz/pull/1#pullrequestreview-5903995535, F3). It must only ever delete files that match the quarantine naming inside that collection's directory: reject path separators, `..`, and any name that isn't a quarantine file. The control UI asks for confirmation; the command itself just does it. Also add to each listed entry whether its id now loads cleanly (e.g. `"resolved": true`).
3. **Never silently revert a valid hand edit.** The first save that touches a collection rewrites every document in it from memory (about line 349), so a valid hand edit made since start-up is silently reverted (review https://github.com/pepperhorn/visualz/pull/4#pullrequestreview-5907793514, suggestion 1). Rewrite a document file only when the in-memory value differs from what the store last loaded or wrote for it; if the file on disk has changed since then, treat it as a hand edit: load it if valid (it wins over an unchanged in-memory value), and if the same document was also changed in memory in that save, keep the in-memory value, and preserve the hand edit beside it using the existing quarantine naming with a note saying it conflicted.
4. **Reload race.** If a reload's state change fails validation, the store must not remember that file's content as its own (same review, suggestion 2), so a later UI delete can't remove a hand-dropped file.

## Scope
- **Files you own:** `visualz/state/__init__.py`, `tests/state/test_store.py`, your two handoff files.
- **Do not touch:** everything else. Item 0010 is editing `visualz/server/__init__.py`, `visualz/state/runtime.py`, `visualz/state/json_safe.py` and their tests in parallel.

## Acceptance criteria
- [ ] Test: 1000 quarantined files in one collection: `Store()` starts, status lists 50 newest and `total: 1000`.
- [ ] Test: `overlays.dismiss_rejected` removes exactly the named pair, republishes, and refuses `../x`, absolute paths, a live document file name, and a file from another collection (error result, nothing deleted).
- [ ] Test: start, hand-edit a valid overlay file, save a change to a *different* overlay: the hand edit is still on disk and is live after `overlays.reload` and after a restart.
- [ ] Test: hand edit and UI change to the *same* overlay in one save: UI value wins, hand edit preserved as a quarantine-named copy with a note.
- [ ] Test: reload whose state change fails validation, then a hand-dropped file, then a UI delete: the hand-dropped file survives.
- [ ] The existing behaviours stay: deletions persist across restarts (0005), invalid hand edits are quarantined never deleted, atomic writes with backup.
- [ ] Verify passes.

## Verify with
```bash
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q   # if xvfb is available
```

## Known gotchas / decisions already made
- Use `python3.11` for the venv (system `python3` is 3.14; pygame has no wheel for it). `uv` is not on PATH.
- Command handlers must return within 2 ms on the main thread; hand file work to the Store worker (`Store.submit`) as `overlays.reload` does.
- Status values are limited to 4096 elements in total per publish (`visualz/state/runtime.py`).
- No schema, dependency or other contract changes. The new command and the new status fields (`total`, `resolved`) are the only API additions; describe them precisely in your return handoff so the control UI task can use them.
- GBrain: unavailable.

## Open questions
None.

---
## Receiver ack

I will cap rejection publication at the newest 50 with a total, add a worker-backed safe dismissal command and resolved flags, preserve valid external edits and quarantine conflicts, and commit disk ownership only after a successful reload transaction. I will change only the two assigned source/test files and my handoffs, run the required checks, then push a draft PR. No open questions. GBrain: unavailable.

---
## Return (implementer → lead; write a separate …--codex-to-lead.md)
