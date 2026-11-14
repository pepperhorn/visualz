# Handoff: 0005 — Deleted documents stay deleted after restart (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0005 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) · **Plan:** — (quick item)
- **Branch:** orch/0005-deleted-docs-restart
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-b5185c97-1c685ad08d65842e
- **PR:** https://github.com/pepperhorn/visualz/pull/4 (draft)
- **Base commit:** 5a1b569 (main with dispatch docs; code base 108ff559be065b8e77b3da644569fd3465f44c17)
- **Implementation commit:** ca57d57a1346ec4f7fd607805f5eee06593e566a
- **Port:** 5250 (unused)
- **Status:** closed (implementation complete; awaiting lead review)

## Goal
Ensure that deleting an overlay, scene or picture set as the first save since startup removes its file and survives restart, preserving invalid hand edits through quarantine.

## Context you need
[Dispatch and receiver acknowledgement](2026-11-14-0005-deleted-docs-restart--lead-to-codex.md) describes F1 from PR #1 review r3. [Foundation contracts](2026-11-14-0001-t1-scaffold--codex-to-lead.md) remain unchanged beyond the assigned deletion fix.

## Scope
- **In:** deletion eligibility for documents loaded from disk; restart, prior-save and invalid-edit regression coverage.
- **Out:** schemas, dependencies, APIs, other quick items, ledger and other docs.
- **Files owned/changed:** `visualz/state/__init__.py`, `tests/state/test_store.py`, this return handoff and the dispatch handoff's receiver acknowledgement only.

## Acceptance criteria
- [x] First-save deletion removes overlay, scene and picture-set files and survives reopening the store.
- [x] Deletion after an earlier save still works for all three collections.
- [x] Existing quarantine tests pass unchanged. New tests also confirm invalid edits encountered during deletion retain exact rejected bytes and readable errors across restart.
- [x] No schema, dependency or unrelated contract changes; only owned files changed.
- [x] Required verification passes.

## Verify with
```bash
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q
```

## Known gotchas / decisions already made
- GBrain: unavailable; no pages consulted or written.
- `uv` was missing from PATH. Installed it into `/tmp/visualz-0005-uv` using a temporary Python 3.11 venv, prepended that environment's bin directory to PATH, then ran the prescribed setup successfully. No project dependency files changed.
- Reused the existing `_disk_documents` map rather than introducing duplicate tracking. A document absent from current state can be unlinked only if its parsed disk contents still match the tracked value last loaded/written. Previous snapshot membership alone cannot authorise document deletion. Remove the map entry after unlink or quarantine. Asset deletion retains the existing previous-snapshot rule.
- Validation/quarantine still runs before deletion. Rejected paths and `.invalid` files retain their existing protection.

## Open questions
None.

---
## Receiver ack
Lead acknowledges the return through the ledger; implementer did not edit the ledger.

---
## Return (implementer → lead)
- **Outcome:** done; ready for cross-family review.
- **Commits:** 18c038d (acknowledgement), ca57d57 (implementation), followed by this return document commit.
- **What changed:** first-flush deletion now recognises startup-loaded documents. Twelve parametrised cases cover three collections × first/prior save × valid/invalid disk file.
- **Verification output:**
```text
Before fix: pytest tests/state/test_store.py -q -k deleted_document
3 failed, 9 passed, 17 deselected in 0.71s
(The three failures were valid files deleted on the first save, one per collection.)

$ .venv/bin/ruff check . && .venv/bin/pytest
All checks passed!
collected 78 items
75 passed, 3 skipped in 8.31s

$ xvfb-run -a .venv/bin/pytest -q
78 passed in 9.74s

$ git diff --check
(no output; passed)
```
- **Decisions made:** reuse disk tracking; clear entries on successful deletion and when rejecting a document; keep all validation/quarantine gates intact. No ADR needed.
- **Out-of-scope issues found:** none.
- **Follow-ups:** lead to arrange cross-family review; merge only through normal orchestration policy. PR is draft and is not being watched or polled.
- **For GBrain (lead to promote):** startup-loaded per-document files must count as deletion candidates even before a first persisted snapshot exists.

## Review revision — 2026-11-14
- **Review:** https://github.com/pepperhorn/visualz/pull/4#pullrequestreview-5907756067; lead directed taking the reviewer’s fix, with document unlinking allowed only for matching tracked contents.
- **Outcome:** addressed; F1 remains fixed. Only the assigned state module, tests and this return handoff changed.
- **What changed:** `_reject_document` forgets the original path, including on quarantine failure (existing rejected-path protection remains). Flush compares parsed document contents with `_disk_documents` before permitting unlink. Changed valid files remain available for normal explicit reload; invalid files follow existing quarantine. The previous snapshot cannot bypass this content check. Asset handling is unchanged.
- **Regression coverage:** invalid hand edit → quarantine → UI deletion → valid file hand-dropped at the same path → another overlay save preserves the exact bytes. Covers both identical-to-original and corrected content, and verifies explicit reload accepts the file. Additional tests cover external replacement immediately before UI deletion, both before and after an earlier save. All four cases failed before the revision. The original twelve deletion/restart cases and existing quarantine tests pass unchanged.
- **Decisions made:** use the content check for all three document collections even when the id is in the previous persisted snapshot, to satisfy the lead’s “only unlink” rule; a prior snapshot does not establish ownership of newly hand-edited bytes. No schema, dependency or API change.
- **Non-blocking suggestion:** reviewer suggests caching `(mtime_ns, size)` to avoid parsing unchanged disk documents. Deferred outside this fix; lead may record it in the Suggestions table.
- **Open questions:** none. GBrain: unavailable.
- **Verification output:**
```text
$ .venv/bin/ruff check . && .venv/bin/pytest
All checks passed!
collected 82 items
79 passed, 3 skipped in 8.27s

$ xvfb-run -a .venv/bin/pytest -q
82 passed in 9.85s

$ git diff --check
(no output; passed)
```
