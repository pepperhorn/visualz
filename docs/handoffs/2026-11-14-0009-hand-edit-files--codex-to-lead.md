# Handoff: 0009 — Hand-edited document files (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0009 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) (AC6, AC15 and invalid hand-edit preservation) · **Plan:** quick task, none
- **Branch:** orch/0009-hand-edit-files
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-eaeb49dd-35f767300013de77
- **PR:** pending creation after this committed return
- **Base commit:** e98f86845036cf453750b67324216337dac8c57b (dispatch reference; branch includes subsequent main docs/status fixes)
- **Port:** 5290 (no server started)
- **Status:** closed

## Goal
Keep the stage starting with large rejection collections, allow safe dismissal, preserve valid external document edits, and avoid claiming disk files when reload validation fails.

## Context you need
Read [dispatch and receiver acknowledgement](2026-11-14-0009-hand-edit-files--lead-to-codex.md). All four requested fixes are implemented; no scope expansion or dependencies were needed.

## Scope
- **In:** rejection reporting/dismissal, per-document save baselines, conflict preservation, transactional reload ownership, regression tests.
- **Out:** server/runtime/json coercion changes (0010), UI confirmation, schema/dependency changes, merges.
- **Files owned/changed:** `visualz/state/__init__.py`, `tests/state/test_store.py`, the dispatch acknowledgement and this return handoff. No other repository files changed.

## Acceptance criteria
- [x] 1,000 rejected files allow startup; newest 50 listed with total 1,000.
- [x] Worker dismissal removes exactly the named quarantine JSON/note pair; unsafe paths and live names fail; a file in another collection survives.
- [x] A valid hand edit survives saving another overlay on the first/subsequent save, becomes live, reloads and survives restart.
- [x] Same-document UI/external conflict keeps UI data and quarantines external bytes with a conflict note.
- [x] Failed reload validation does not claim the observed file; a subsequent hand drop survives UI deletion.
- [x] Existing deletion/restart, invalid quarantine and atomic backup tests pass.
- [x] Ruff, full pytest, and xvfb pytest pass.

## Verify with
```bash
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q
```

## Known gotchas / decisions made
- GBrain: unavailable (no GBrain tools exposed; no pages used).
- **API for the control UI:** `overlays.dismiss_rejected` accepts keyword args `collection` (`overlays`, `scenes`, or `picture_sets`) and `file` (basename matching `<id>.invalid.json` or `<id>.invalid-<digits>.json`, where id uses the existing document-id alphabet/limit). Path separators, dots in ids, traversal and live filenames fail immediately as command errors. No confirmation inside this handler; the UI provides it.
- Like reload, valid dismiss requests immediately return `{"queued": true}`; disk work runs on Store's worker. Disk failures (including a name absent from the requested collection) appear in `status.state.error`; a queued command result does not confirm disk completion. A symlinked collection directory is refused; unlinking a symlink file removes only the link.
- **Status API:** retain `status.stage.rejected_<collection>` as an array, newest first by modification time with filename as a deterministic tie-break, capped at 50. Each entry is `{file, error, resolved}`. `resolved` means the corresponding live `<id>.json` currently validates against the state. New sibling field `status.stage.rejected_<collection>_total` counts all rejected/protected files, including entries outside the cap. This preserves the existing list contract; the numeric sibling supplies the requested total. Notes are read at most 1,024 characters; publication errors are logged and cannot abort startup.
- Separate document baselines track values last loaded/written rather than the last full-state save. On a changed collection, valid disk edits win over unchanged memory; concurrent UI edits are not overwritten by adoption. External files for ids deleted in memory remain on disk for explicit reload, preserving 0005 behavior. Conflicting changed memory wins and the external file is quarantined with a conflict note.
- Reload stages disk ownership and commits it only after its state transaction succeeds. Only files actually loaded are used as disk baselines, so new unsaved UI documents still get written.
- Final close-time flush can apply an internal validated adoption after public writes are closed, without scheduling another timer.

## Open questions
None.

---
## Receiver ack
Lead acknowledges through the ledger; no implementer ledger changes made.

---
## Return
- **Outcome:** done
- **Verification output:**
  ```text
  All checks passed!
  125 passed, 3 skipped in 11.53s
  128 passed, 1 warning (xvfb; pygame/pkg_resources deprecation)
  ```
- **Out-of-scope issues found:** none requiring changes to another task's files.
- **Follow-ups:** control UI can use the command/status contract above; review and merge remain with the lead.
- **For GBrain (lead to promote):** distinguish per-document loaded/written baselines from full-state persistence snapshots; publish disk ownership only after state validation commits.
