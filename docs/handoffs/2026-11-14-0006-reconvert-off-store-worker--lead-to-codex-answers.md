# Handoff: 0006 — Answers to the blocked return (lead → codex)

- **Date:** 2026-11-14
- **Type:** dispatch (answers)
- **Ledger:** 0006 · **Original handoff:** docs/handoffs/2026-11-14-0006-reconvert-off-store-worker--lead-to-codex.md
- **Branch:** orch/0006-reconvert-off-store-worker · **PR:** https://github.com/pepperhorn/visualz/pull/3
- **Status:** closed

## Answers
1. **`visualz/__main__.py`: yes, you now own it**, for the shutdown wiring only: `register_commands(store)` may return the media worker (or a close callable), and the existing ExitStack registers its close before the Store closes. No other change to that file.
2. **`tests/media/test_profiles.py`: yes, but only the one function `test_r2_2_auto_resolution_and_registered_reconvert`**, and only its completion wait. Item 0008 is editing other tests in the same file in parallel, so touch nothing else there. Whichever PR merges second rebases.
3. **Setup:** `uv` is not on PATH; that was the lead's mistake. Use `python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'`.

Everything else in the original handoff stands. Give the media worker a public way to wait for idle (used by tests) rather than reaching into private queues.
