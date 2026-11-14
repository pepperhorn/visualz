# Handoff: 0006 — [quick] media.reconvert must not block the store worker (lead → codex)

- **Date:** 2026-11-14
- **Type:** quick
- **Ledger:** 0006 · **Spec:** docs/specs/0001-audio-reactive-visuals.md · **Plan:** — (quick item; follow-up from review r3 of PR #1: https://github.com/pepperhorn/visualz/pull/1#pullrequestreview-5903995535)
- **Branch:** orch/0006-reconvert-off-store-worker · **Worktree:** created by T3
- **PR:** —
- **Base commit:** 108ff559be065b8e77b3da644569fd3465f44c17
- **Port (if running a server):** 5260
- **Status:** closed

## Goal
Review finding F2. `media.reconvert` (`visualz/media/__init__.py:264-278`) runs ffmpeg (up to 120 s per asset) through `store.submit_task`, which is the store's single short-lived worker. Every `Store.submit()` queued behind it waits, including `stage.blackout` (`visualz/__main__.py:81`). Measured: a 2.24 s blackout delay on a desktop. Fix: run conversions on a thread (or single-thread executor) owned by the media module, and hand only the final `store.patch` and status update to the store. Conversions stay serial (one ffmpeg at a time: the Pi 2 can't afford more). Shut the executor down cleanly on close.

## Scope
- **Files you own:** `visualz/media/__init__.py`, `visualz/media/archive.py`, new test file `tests/media/test_reconvert.py`, your two handoff files
- **Do not touch:** everything else. Other quick fixes are running in parallel on `visualz/state/__init__.py`, `visualz/state/runtime.py`, `visualz/state/json_safe.py`, `visualz/media/__init__.py` and `visualz/schema/profiles.py`; if you need a change in a file you don't own, stop and say so in your return handoff.

## Acceptance criteria
- [ ] Test: while a reconvert is running (use a slow fake converter, not real ffmpeg), a `Store.submit()` lands within 100 ms.
- [ ] Reconvert still writes to a fresh asset directory, removes it on failure, never touches the old asset, and reports failure through `status.media.error`.
- [ ] Two reconvert requests in a row run one after the other, not at once.
- [ ] Process shutdown doesn't hang on a running conversion for more than a few seconds (document what happens to a half-made asset directory).
- [ ] No change to JSON schemas, dependencies, or the documented contracts in `docs/handoffs/2026-11-14-0001-t1-scaffold--codex-to-lead.md` beyond what this handoff states.
- [ ] Verify passes.

## Verify with
```bash
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q   # if xvfb is available
```

## Known gotchas / decisions already made
- The system `python3` on the build box is 3.14, and pygame has no wheel for it (the source build fails without SDL headers). Build the venv with Python 3.11: `python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'`.
- The target is Raspberry Pi OS Bookworm (Python 3.11). Keep to the standard library and the dependencies already in `pyproject.toml`.
- GBrain: unavailable.

## Open questions
None.

---
## Receiver ack

Acknowledged: move reconversion to a serial media-owned worker so Store.submit remains responsive; preserve fresh-directory conversion and failure reporting, and bound shutdown. I will change only the listed media files, new reconversion tests, and my handoffs. No open questions. GBrain: unavailable.

Continuation acknowledged: read the scope answers at commit e93f769372c11927b29f4f3be2c2142b58081564 (`docs/handoffs/2026-11-14-0006-reconvert-off-store-worker--lead-to-codex-answers.md`). Ownership now includes shutdown wiring only in `visualz/__main__.py` and completion-wait changes only in `test_r2_2_auto_resolution_and_registered_reconvert`. Use Python 3.11 venv directly and expose public media-worker wait-for-idle. Both scope blockers are resolved.

---
## Return (implementer → lead; write a separate …--codex-to-lead.md)
