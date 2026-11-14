# Handoff: 0008 — Auto output size scope blocker (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0008 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) · **Plan:** — (quick item)
- **Branch:** orch/0008-auto-output-size
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-e5621b38-a4e821de1f08067f
- **PR:** Draft PR for this branch; linked from the implementation report and PR body.
- **Base commit:** 108ff559be065b8e77b3da644569fd3465f44c17 (dispatch base)
- **Last implementation commit:** none; receiver acknowledgement committed as 4e4170e32f4f2f8ad185260449576475ef4f1832.
- **Port:** 5280 (unused)
- **Status:** open — blocked

## Goal
Align the published output defaults and documentation with `auto` = 1280×720,
while keeping high internal resolution tied to output up to 1920×1080, explicit
sizes unchanged, and low-profile behaviour unchanged. See the
[dispatch](2026-11-14-0008-auto-output-size--lead-to-codex.md).

## Context you need
The [T1 return](2026-11-14-0001-t1-scaffold--codex-to-lead.md) documents the previous
low/high output defaults. This task intentionally supersedes that part only.
Inspection found an existing regression test outside this task's ownership that
pins the previous high-profile auto output, making the required verification
incompatible with the assigned scope.

## Scope
- **In:** `visualz/schema/profiles.py`, `tests/media/test_profiles.py`, and this task's two handoffs.
- **Out:** display detection, JSON schemas, dependencies, all other source/tests/docs.
- **Files owned:** the four paths above; only handoffs changed.
- **Do not touch:** notably `tests/schema/test_schema.py`, which is not assigned.

## Acceptance criteria
- [ ] Profile table and docstring state the requested auto rule.
- [ ] Regression tests pin high auto at 1280×720 output/internal, explicit high at 1920×1080 internal, and unchanged low defaults.
- [ ] Explicit sizes, low profile, JSON schemas and unrelated contracts remain unchanged.
- [ ] Verification passes.

## Verify with
```bash
uv venv --python 3.11 --seed .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest -q
```

## Known gotchas / decisions already made
- GBrain: unavailable (no GBrain tool exposed); no pages consulted or written.
- The requested setup command failed with `/bin/bash: line 1: uv: command not found`.
- `xvfb-run` is available at `/usr/bin/xvfb-run`.
- No production code or tests were edited. Stopped under the dispatch's ownership rule and AGENTS.md §7.

## Open questions
Lead: please extend ownership to `tests/schema/test_schema.py` (or arrange a
coordinated change to its existing expectation). At line 88,
`test_r2_2_profile_auto_and_full_hd_contract` requires
`stage_size(settings, "high") == (1920, 1080)` while stage width/height remain
`auto`. Changing high's table output to 1280×720 necessarily invalidates it.
The requested new regression must expect 1280×720 for that same output rule.
Recommend authorizing the existing test's expectation update to 1280×720.

The dispatch's premise also needs this nuance: main falls back to low when
`hardware_profile` is `auto` without detection, but explicitly selecting the high
hardware profile currently resolves auto output to 1920×1080. The requested
new high auto default would deliberately change that case too.

---
## Receiver ack
Lead acknowledges through the ledger; implementer does not edit it.

---
## Return (implementer → lead)
- **Outcome:** blocked; receiver acknowledgement and blocker report only.
- **What changed:** filled and committed dispatch receiver acknowledgement; wrote this return. No implementation attempted outside ownership.
- **Verification output:**
```text
$ uv venv --python 3.11 --seed .venv && .venv/bin/pip install -e '.[dev]'
/bin/bash: line 1: uv: command not found
```
Ruff/pytest not run: environment setup failed and implementation stopped at the scope blocker.
- **Decisions made:** no architectural decisions; no workarounds to preserve a contradictory test expectation.
- **Out-of-scope issues found:** conflicting existing test outside owned files; missing uv executable.
- **Follow-ups:** lead resolves test ownership; next implementer makes the table/docstring change and updates both existing and new regression tests, provisions Python 3.11 tooling, then runs verification.
- **For GBrain (lead to promote):** none until the output default is implemented and reviewed.
