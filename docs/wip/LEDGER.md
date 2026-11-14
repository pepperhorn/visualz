# WIP Ledger

> Single writer: the **lead**, on the main branch only. Implementers report status through their return handoff.
> Status: proposed · specced · planned · dispatched · in-review · changes-requested · ready · merged · closed · blocked · parked
> Waiting on: `child <taskId>` · `review <taskId>` · `ci` · `human: <why>` · `lead: <next action>`. Set it on every status change. A row needs the lead when it starts with `lead`, or when it's empty and Status is dispatched, in-review, changes-requested, ready, or merged. The lead's Stop hook won't let the lead end its turn while any row needs it.
> Type: normal items have a spec and plan. Quick items have the title prefix `[quick]` (no spec or plan, a short handoff). PRs adopted by `orch-sweep` have the prefix `[pr]`.

Next ID: 0004

## Active

| K | Title | Status | Waiting on | Owner (provider/model) | Branch | PR | Worktree | T3 task/thread | Spec | Plan | Latest handoff | Updated |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0001 | Audio-reactive visuals for live shows (v1) | in-review | review node:delegated-task:command%3Amcp%3A25bc09b8-d5f3-4e82-b258-7f74ee95d4b5%3Adelegate-task%3A0001-t1-review-r1 | T1: codex/gpt-6.1-sol | T1: orch/0001-t1-scaffold | T1: https://github.com/pepperhorn/visualz/pull/1 (head 4587a47) | T1: /home/t3box/.t3/worktrees/visualz/t3-973ffe37-9ffd194d47c599aa | T1 task `node:delegated-task:command%3Amcp%3A25bc09b8-d5f3-4e82-b258-7f74ee95d4b5%3Adelegate-task%3A0001-t1-impl-r1` · thread `thread:delegated-task:command%3Amcp%3A25bc09b8-d5f3-4e82-b258-7f74ee95d4b5%3Adelegate-task%3A0001-t1-impl-r1` · review r1 `node:delegated-task:command%3Amcp%3A25bc09b8-d5f3-4e82-b258-7f74ee95d4b5%3Adelegate-task%3A0001-t1-review-r1` | [spec](../specs/0001-audio-reactive-visuals.md) | [plan](../plans/0001-audio-reactive-visuals.md) | [T1 return](../handoffs/2026-11-14-0001-t1-scaffold--codex-to-lead.md) (on branch, at 4587a47) | 2026-11-14 |
| 0002 | XR18 web mixer and personal monitor mixes | planned | human: approve spec 0002 (no open questions left); build starts after 0001 T1 and T4 | — | — | — | — | — | [spec](../specs/0002-xr18-web-mixer.md) | [plan](../plans/0002-xr18-web-mixer.md) | — | 2026-11-14 |
| 0003 | Stereo and multitrack recording to a USB drive | planned | human: approve spec 0003 and answer its 2 open questions; build starts after 0001 T1, T2, T4, T5 | — | — | — | — | — | [spec](../specs/0003-usb-recording.md) | [plan](../plans/0003-usb-recording.md) | — | 2026-11-14 |

## Done / closed

| K | Title | PR | Merged | Notes |
|---|---|---|---|---|

## Suggestions

> Lead-curated ideas: next steps, improvements, code efficiencies, stack changes, risks. Each needs evidence (file:line, a measurement, or a link). Status: `new` · `accepted → NNNN` · `declined: <why>` · `done`. Keep declined rows so they aren't suggested again. A PR mentioned here isn't tracked: only the PR column of Active or Done rows counts.

| S | Kind | Suggestion | Evidence | Effort (S/M/L) | Value | Source | Status |
|---|---|---|---|---|---|---|---|
| S1 | next step | Drive visuals from individual XR18 channels (e.g. kick channel meter as the beat trigger, vocal level for the overlay) using the mixer link from 0002, instead of detecting beats from the stereo mix | Spec 0002 already subscribes to per-channel meters; spec 0001 beat detection works on a full mix, which is less reliable than a kick channel | M | high: tighter sync with the music | lead, 2026-11-14 | new |
| S2 | stack | Try the Orange Pi Zero 2W as a second board: run `tools/smoke.py` on it once 0001 T1 merges; if GPU acceleration and HDMI work, add it to the install script and raise the default internal resolution for it | Spec 0001 Constraints (secondary, unverified target); H618 + Mali-G31 is faster than the Pi 2/3 GPU, but HDMI on current images is unconfirmed (Armbian forum threads 32944, 36896) | S to test, M to support | medium: more headroom and built-in Wi-Fi | human, 2026-11-14 | new: waiting on smoke test by the human |
| S3 | stack | Use the Intel NUC7i5BNH on Ubuntu Server as the show machine, keeping Pi 2/3 as the low-end baseline: run `tools/smoke.py` on it once 0001 T1 merges | Spec 0001 Constraints (candidate target); Iris Plus 640 with Mesa is a mature KMS/DRM + GLES stack, 8 GB RAM, USB 3 on its own controller removes the single-USB-2-bus recording risk in spec 0003, internal SSD for takes | S to test | high: full-resolution visuals, safe 18-track recording | human, 2026-11-14 | new: human chose the Pi as primary on 2026-11-14; NUC stays a candidate |
| S4 | next step | X32 support: add an X32 mixer profile to 0002 (32 channels, 16 buses, OSC port 10023, different headamp and meter layout) and verify 32-track recording in 0003 | Spec 0002 Constraints (mixer profile) and spec 0003 Constraints (32-track load); `xair-api` README states X32 is only partially supported, so most of the profile would use `python-osc` directly | L | depends on whether the band uses an X32 | human question, 2026-11-14 | new: waiting on the human (do they have an X32?) |

Last health scan: never

## Log
<!-- One line per status change, newest first: YYYY-MM-DD NNNN old→new — note -->
2026-11-14 0001 — human: start on the Pi (primary target); NUC and Orange Pi remain candidates. 0002 and 0003 made model-agnostic (mixer profile, device channel count) so X32 can follow
2026-11-14 0001 dispatched→in-review — T1 done by codex, PR #1 (head 4587a47, +3221 lines, 24 passed 1 skipped); review r1 delegated to claude-opus-5-5
2026-11-14 0003 —→planned — spec and plan drafted at the human's request; 0001 plan T2 now opens audio by configurable ALSA name for shared capture
2026-11-14 0001 dispatched — T1 delegated to codex/gpt-6.1-sol (0001-t1-impl-r1)
2026-11-14 0001 planned→dispatched — spec approved by the human; T1 handoff written; T2–T5 wait on T1 merge and the Pi smoke test. GBrain: pending write-back (unavailable)
2026-11-14 0002 planned→planned — all open questions answered: wedges and in-ears, engineer PIN on by default (0000)
2026-11-14 0002 planned→planned — scope grown at the human's request: per-channel sends, preamp gain, phantom power, EQ, gate, compressor (new task T3)
2026-11-14 0002 —→planned — spec and plan drafted (built-in web mixer chosen over BandPilot and X AIR Edit remote desktop)
2026-11-14 0001 planned→planned — MIT licence added; XR18 over USB is the audio source; all open questions answered
2026-11-14 0001 planned→planned — retargeted to Pi 2/3: ADR 0002 (native renderer) accepted, ADR 0001 superseded; added halftone, chromascope, gallery, webcam source
2026-11-14 0001 —→planned — spec, plan, and ADR 0001 drafted; waiting on human approval
