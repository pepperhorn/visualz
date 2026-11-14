# Handoff: 0005 — [quick] Deleted overlay, scene or picture set must stay deleted after a restart (lead → codex)

- **Date:** 2026-11-14
- **Type:** quick
- **Ledger:** 0005 · **Spec:** docs/specs/0001-audio-reactive-visuals.md · **Plan:** — (quick item; follow-up from review r3 of PR #1: https://github.com/pepperhorn/visualz/pull/1#pullrequestreview-5903995535)
- **Branch:** orch/0005-deleted-docs-restart · **Worktree:** created by T3
- **PR:** —
- **Base commit:** 108ff559be065b8e77b3da644569fd3465f44c17
- **Port (if running a server):** 5250
- **Status:** open

## Goal
Review finding F1. `visualz/state/__init__.py` (about line 340) unlinks a per-document file only when `old.stem in old_values`, and `old_values` comes from `self._persisted`, which is `None` until the first flush. So if a deletion is the first save since boot, the file stays on disk and `_read_documents` reloads it at the next start. Fix: also unlink a document file that was loaded at start-up (track the set of files read from disk, e.g. `self._disk_documents`). Invalid hand-edited files must still be quarantined, never deleted: that behaviour must not change.

## Scope
- **Files you own:** `visualz/state/__init__.py`, `tests/state/test_store.py`, your two handoff files
- **Do not touch:** everything else. Other quick fixes are running in parallel on `visualz/state/__init__.py`, `visualz/state/runtime.py`, `visualz/state/json_safe.py`, `visualz/media/__init__.py` and `visualz/schema/profiles.py`; if you need a change in a file you don't own, stop and say so in your return handoff.

## Acceptance criteria
- [ ] Test: start a store, delete an overlay as the very first change, flush and close, start again: the overlay is gone from state and its file is gone from disk. Same for a scene and a picture set.
- [ ] Test: a deletion after earlier saves still removes the file (no regression).
- [ ] The existing quarantine tests still pass unchanged.
- [ ] No change to JSON schemas, dependencies, or the documented contracts in `docs/handoffs/2026-11-14-0001-t1-scaffold--codex-to-lead.md` beyond what this handoff states.
- [ ] Verify passes.

## Verify with
```bash
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q   # if xvfb is available
```

## Known gotchas / decisions already made
- The system `python3` on the build box is 3.14, and pygame has no wheel for it (the source build fails without SDL headers). Build the venv with Python 3.11: `uv venv --python 3.11 --seed .venv && .venv/bin/pip install -e '.[dev]'`.
- The target is Raspberry Pi OS Bookworm (Python 3.11). Keep to the standard library and the dependencies already in `pyproject.toml`.
- GBrain: unavailable.

## Open questions
None.

---
## Receiver ack
Codex acknowledges: track valid documents read from disk so deleting an overlay, scene or picture set before the first save removes its file and survives restart. Preserve invalid-edit quarantine and existing persistence contracts. Changes are limited to the two assigned Python files and this task’s handoffs. Add restart and prior-save regression coverage, run the required checks, then push the branch and open a draft PR. No open questions. GBrain: unavailable.

---
## Return (implementer → lead; write a separate …--codex-to-lead.md)
