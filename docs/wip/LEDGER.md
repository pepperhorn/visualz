# WIP Ledger

> Single writer: the **lead**, on the main branch only. Implementers report status through their return handoff.
> Status: proposed · specced · planned · dispatched · in-review · changes-requested · ready · merged · closed · blocked · parked
> Waiting on: `child <taskId>` · `review <taskId>` · `ci` · `human: <why>` · `lead: <next action>`. Set it on every status change. A row needs the lead when it starts with `lead`, or when it's empty and Status is dispatched, in-review, changes-requested, ready, or merged. The lead's Stop hook won't let the lead end its turn while any row needs it.
> Type: normal items have a spec and plan. Quick items have the title prefix `[quick]` (no spec or plan, a short handoff). PRs adopted by `orch-sweep` have the prefix `[pr]`.

Next ID: 0003

## Active

| K | Title | Status | Waiting on | Owner (provider/model) | Branch | PR | Worktree | T3 task/thread | Spec | Plan | Latest handoff | Updated |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0001 | Audio-reactive visuals for live shows (v1) | planned | human: approve spec 0001 (no open questions left) | — | — | — | — | — | [spec](../specs/0001-audio-reactive-visuals.md) | [plan](../plans/0001-audio-reactive-visuals.md) | — | 2026-11-14 |
| 0002 | XR18 web mixer and personal monitor mixes | planned | human: approve spec 0002 and answer its 2 open questions; build starts after 0001 T1 and T4 | — | — | — | — | — | [spec](../specs/0002-xr18-web-mixer.md) | [plan](../plans/0002-xr18-web-mixer.md) | — | 2026-11-14 |

## Done / closed

| K | Title | PR | Merged | Notes |
|---|---|---|---|---|

## Suggestions

> Lead-curated ideas: next steps, improvements, code efficiencies, stack changes, risks. Each needs evidence (file:line, a measurement, or a link). Status: `new` · `accepted → NNNN` · `declined: <why>` · `done`. Keep declined rows so they aren't suggested again. A PR mentioned here isn't tracked: only the PR column of Active or Done rows counts.

| S | Kind | Suggestion | Evidence | Effort (S/M/L) | Value | Source | Status |
|---|---|---|---|---|---|---|---|
| S1 | next step | Drive visuals from individual XR18 channels (e.g. kick channel meter as the beat trigger, vocal level for the overlay) using the mixer link from 0002, instead of detecting beats from the stereo mix | Spec 0002 already subscribes to per-channel meters; spec 0001 beat detection works on a full mix, which is less reliable than a kick channel | M | high: tighter sync with the music | lead, 2026-11-14 | new |

Last health scan: never

## Log
<!-- One line per status change, newest first: YYYY-MM-DD NNNN old→new — note -->
2026-11-14 0002 —→planned — spec and plan drafted (built-in web mixer chosen over BandPilot and X AIR Edit remote desktop)
2026-11-14 0001 planned→planned — MIT licence added; XR18 over USB is the audio source; all open questions answered
2026-11-14 0001 planned→planned — retargeted to Pi 2/3: ADR 0002 (native renderer) accepted, ADR 0001 superseded; added halftone, chromascope, gallery, webcam source
2026-11-14 0001 —→planned — spec, plan, and ADR 0001 drafted; waiting on human approval
