# Handoff: 0008 — [quick] Make the meaning of auto output size clear (lead → codex)

- **Date:** 2026-11-14
- **Type:** quick
- **Ledger:** 0008 · **Spec:** docs/specs/0001-audio-reactive-visuals.md · **Plan:** — (quick item; follow-up from review r3 of PR #1: https://github.com/pepperhorn/visualz/pull/1#pullrequestreview-5903995535)
- **Branch:** orch/0008-auto-output-size · **Worktree:** created by T3
- **PR:** —
- **Base commit:** 108ff559be065b8e77b3da644569fd3465f44c17
- **Port (if running a server):** 5280
- **Status:** open

## Goal
Review finding F6. `visualz/__main__.py:60` calls `stage_size(settings)` with no display detection, so `auto` output always means 1280×720, but the high profile's `output` entry in `visualz/schema/profiles.py` (about line 61) says 1920×1080, which can never be reached through `auto`. Don't add display detection here (that belongs to T2, which owns the display). Fix the mismatch: make the published defaults table and its docstring say what actually happens (`auto` output = 1280×720 unless the user sets a size; the high profile renders internally at the output size, up to 1920×1080 when set).

## Scope
- **Files you own:** `visualz/schema/profiles.py`, `tests/media/test_profiles.py`, your two handoff files
- **Do not touch:** everything else. Other quick fixes are running in parallel on `visualz/state/__init__.py`, `visualz/state/runtime.py`, `visualz/state/json_safe.py`, `visualz/media/__init__.py` and `visualz/schema/profiles.py`; if you need a change in a file you don't own, stop and say so in your return handoff.

## Acceptance criteria
- [ ] The profile table no longer claims an output default that `auto` can't produce, and the docstring states the rule.
- [ ] A test pins: high profile + `auto` → 1280×720 output and internal; high profile + explicit 1920×1080 → internal 1920×1080; low profile unchanged.
- [ ] No behaviour change for explicit sizes or for the low profile.
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
Codex, 2026-11-14: I will align the profile table and module documentation so
`auto` output defaults to 1280×720 for either profile. The high profile will keep
following the selected output internally, capped at 1920×1080; explicit sizes and
low-profile defaults will remain unchanged. I will add regression coverage in
`tests/media/test_profiles.py`, verify with ruff/pytest (and xvfb if available),
and return a committed handoff plus a draft PR. I own only the two assigned
source/test files and these task handoffs. No open questions. GBrain: unavailable
(no GBrain tool exposed in this session).

---
## Return (implementer → lead; write a separate …--codex-to-lead.md)
