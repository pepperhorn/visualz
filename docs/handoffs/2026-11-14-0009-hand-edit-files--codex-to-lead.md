# Handoff: 0009 — Hand-edited document files (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0009 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) (AC6, AC15 and invalid hand-edit preservation) · **Plan:** quick task, none
- **Branch:** orch/0009-hand-edit-files
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-eaeb49dd-35f767300013de77
- **PR:** https://github.com/pepperhorn/visualz/pull/7
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
- **Status API:** retain `status.stage.rejected_<collection>` as an array, newest first by modification time with filename as a deterministic tie-break, capped at 50. Each entry is `{file, error, kind, resolved}`. `kind` is `"invalid"` for invalid edits and `"conflict"` for preserved hand edits that conflicted with a UI change or deletion. Conflict entries always have `resolved: false`, including after restart: the UI must not offer to casually dismiss the only copy of the hand edit. For other entries, `resolved` means that id is currently loaded and matches a valid document the Store loaded or wrote; it is derived from cached Store values, never a fresh disk read or validation. New sibling field `status.stage.rejected_<collection>_total` counts all rejected/protected files, including entries outside the cap. This preserves the existing list contract; the numeric sibling supplies the requested total. Notes are read at most 1,024 characters and cached when quarantine filenames are discovered. The newest 50 metadata records are cached too; normal saves reuse the existing directory scan and read no notes. Publication does no I/O or validation, deduplicates resolution checks by id and only publishes when the resulting collection status differs. Publication/discovery errors are logged and cannot abort startup.
- Separate document baselines track values last loaded/written rather than the last full-state save. On a changed collection, valid disk edits win over unchanged memory; concurrent UI edits are not overwritten by adoption. When a UI deletion and a hand edit target the same previously loaded id, the deletion wins: the hand edit is quarantined with a conflict note and the live filename is removed, preventing resurrection at restart. Newly dropped files for ids absent before that save remain available for explicit reload. Conflicting changed memory wins; identical hand/UI values are adopted without creating a conflict copy.
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
- **Implementation commits:** db4a877 (receiver acknowledgement), 5ec3af0 (implementation, regressions and return); final docs commit records the PR URL.
- **Verification output:**
  ```text
  All checks passed!
  132 passed, 3 skipped
  135 passed, 1 warning (xvfb; pygame/pkg_resources deprecation)
  ```
- **Out-of-scope issues found:** none requiring changes to another task's files.
- **Follow-ups:** control UI can use the command/status contract above; review and merge remain with the lead.
- **For GBrain (lead to promote):** distinguish per-document loaded/written baselines from full-state persistence snapshots; publish disk ownership only after state validation commits.

## PR review follow-up (2026-11-14)
Addressed [review 5907884293](https://github.com/pepperhorn/visualz/pull/7#pullrequestreview-5907884293) and all five lead decisions:

- Removed all document reads and validation from rejection publication. Separate discovery caches notes and sorted metadata; flush reuses its directory listing unless it created new quarantines. Reload publishes once after its transaction attempt, rather than inside loading and again after commit. Unchanged rejection/resolution data is not republished.
- Added a deterministic regression with 30 overlays and 0 versus 50 rejected files. A patch plus save has exactly the same read, state-validation and schema-validation counts in both cases (one state validation and one schema validation); neither save republishes unchanged rejection data. The test also forbids reads and validation during explicit publication.
- Local benchmark, 60 alternating patch/flush samples with 30 overlays: medians 7.914 ms (zero rejected files) and 8.364 ms (50). This is desktop evidence, not a Pi measurement; there is no timing threshold in tests. An initial measurement showed residual metadata-scan overhead, so the final implementation also caches newest-entry ordering and reuses the flush scan.
- Identical external/UI edits do not create conflicts. Conflict copies are distinctly marked and always unresolved. UI deletion wins over a simultaneous external edit, with preserved bytes and restart coverage; old tests expecting resurrection were updated to the lead's new decision. Clearing deleted ids from memory baselines keeps subsequent unrelated hand drops intact.
- Ownership checks require actual membership in the disk map: `null`, arrays, numbers, strings and booleans cannot compare equal to a missing owner and get deleted. All are covered by quarantine-preservation tests.
- The failed-reload race regression still proves that an uncommitted load cannot claim a file: a subsequent UI deletion preserves that file as a conflict copy rather than unlinking it as Store-owned content.

No open questions; the accepted asynchronous missing-file dismissal deviation is unchanged. Only the assigned Store source/tests and this return handoff changed in this follow-up.
