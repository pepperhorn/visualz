# Handoff: 0001-t1 — Scaffold foundation, review round 2 (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0001 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) · **Plan:** [0001, T1](../plans/0001-audio-reactive-visuals.md)
- **Branch:** orch/0001-t1-scaffold
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-973ffe37-9ffd194d47c599aa
- **PR:** https://github.com/pepperhorn/visualz/pull/1 (draft)
- **Base commit:** 5f0c2fae8ce4327878357d2721d38a97a34f83bd
- **Initial implementation:** 6e075f3beb8ab0827f70098fef30a9f5e0dc5343
- **Review round 1 base:** 4587a47f33e23e40d5d5c1aad94baf536102b647; round 1 fixes: 9c2ba57a2b74e885a07a150cf6e3a0452b504d92.
- **Review round 2 base:** 9c2ba57a2b74e885a07a150cf6e3a0452b504d92; revisions are this branch's following commit.
- **Port:** 5211
- **Status:** closed

## Goal
Deliver T1's Python foundation. Round 1 findings are confirmed fixed by the round 2 reviewer; this revision addresses all six round 2 lead decisions (B1, S1–S3, M1–M2 and the migration suggestion). The updated spec and plan on `origin/main` were fetched and read without merging main, as directed. This document describes the resulting contracts; it supersedes the earlier return description.

## Context you need
Read [dispatch and acknowledgement](2026-11-14-0001-t1-scaffold--lead-to-codex.md), [native renderer ADR](../decisions/0002-native-renderer.md), the spec and plan above, and the round 1 review and implementation reply on the PR. GBrain: unavailable; no GBrain pages consulted or written.

## Scope
- **In:** T1 packaging, schema/defaults, store, REST/WebSocket server, uploads/archives/media conversion, ES 2 helpers, main loop, documented neutral worker stubs, placeholder control page, standalone smoke script and tests.
- **Out:** real audio/camera capture, real visual modes and gallery playback, overlay composition, full UI, bundled fonts and deployment (T2–T5).
- **Files owned:** `pyproject.toml`, `ruff.toml`, `visualz/{__init__,__main__}.py`, `visualz/{state,schema,server,media,gl}/**`, stub `visualz/{audio,render,camera,overlay}/__init__.py`, `web/index.html`, `tools/smoke.py`, `tests/{state,schema,server,media}/**`, `tests/conftest.py`, and the two task handoffs.
- **Do not touch:** ledger and all other lead docs. Only owned files changed; main was not merged. No `.gitignore` changes needed.

## Acceptance criteria
- [x] AC9: published schemas, readable atomic rejection, invalid JSON and schema-invalid hand-edited templates rejected without stopping the stage.
- [x] AC13: templates with image logos, frame loops and uploaded fonts round-trip into fresh data directories; imported referenced assets are registered. Imports validate every supplied file privately before publishing; any failure rolls back files and state. Valid unreferenced files are discarded.
- [x] AC14: synchronised clients and full state on reconnect; separate 10 Hz status telemetry.
- [x] AC15: atomic, fsynced state, one durable rotating backup, corrupt-file quarantine, backup/default recovery and `stage.state_recovered` status.
- [x] AC18 and upload/ingest bounds: required verification passes; real ffmpeg MP4/WebM/GIF conversion, clip original retention/trim warning, logo duration/size caps and file/ZIP rejection tested.
- [x] Schema covers named persistent fields; mode identifiers are open, per-mode maps preserve parameters/quality, and hardware profile defaults to `auto`. No named persistent spec field omitted.
- [x] GL helpers, immutable snapshots, background state submission, real threaded control server startup, command dispatch, blackout, clean shutdown and restart tested on a virtual desktop. Display-dependent tests skip headlessly.
- [x] Standalone smoke help works without optional imports; tests exercise NPOT rendering, texture upload/upscale, shader precision queries, USB capture descriptor parsing and EGL selection.
- [ ] Human gate: run `python3 tools/smoke.py` on the Pi before dispatching T2–T5. Actual KMS/DRM, VideoCore IV compatibility, XR18/webcam operation and target fps remain unverified.

## Verify with
```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
xvfb-run -a .venv/bin/pytest tests/media tests/server/test_process.py -q
python3 tools/smoke.py --help
# Human Pi hardware gate (standalone, apt dependencies only):
python3 tools/smoke.py
```

## Known gotchas / decisions already made
- **Worker bridge (B1):** `visualz.state.runtime.Runtime`, available as `store.runtime`, imports no GL. Workers call `register_command(target,name,handler)`, `publish_status(target,dict)` and `publish_image(name,bytes,content_type)`; no later task needs to edit the server. Main drains at most 32 commands per frame from a bounded 128-command queue, with a default 2 ms elapsed-time budget. Handlers MUST return within 2 ms and hand long work to their own worker; Python cannot preempt an in-progress handler. Above 5 ms the bridge logs a warning and publishes `commands.slow_handler` with target/name/milliseconds. Handler exceptions are logged and become error results, never render-loop exceptions.
- HTTP: `POST /api/stage/command {target,name,args,id?}` returns 202 with the correlation id when queued; `GET /api/stage/result/<id>` returns the pending/result record; `GET /api/stage/status`; `GET /api/stage/image/<name>`. WS uses `{type:"command",target,name,args,id?}` and returns an acceptance message and then a `command_result` message to the originating connection, both echoing id. Optional ids are unique strings or integers (<=128 characters); absent ids are generated. Results are cached for the last 128 commands; reusing a cached id is rejected. Invalid commands return 400; queue overload is 503 / Retry-After: 1 (WS status/retry_after). Execution failures also appear in `status.commands.error`.
- Initial registered command signatures: `audio.refresh_devices()`, `camera.snap(set_id)`, `camera.delete_all(set_id)`, `gallery.next()`, `gallery.prev()`, `stage.restart()`, `stage.blackout(enabled,overlay=False,fade_seconds=.5)`, `media.reconvert(asset_id)`, `overlays.reload()`. Audio/camera/gallery handlers are T1 stubs for T2 to replace. Restart exits non-zero after orderly cleanup; blackout submits a persistent patch.
- Status contract is documented in `state/runtime.py`: audio devices `{id,name,channels}` with actual capture channel counts and current `levels`; camera `present`, `devices`, `latest` image name/null; stage `fps`, `gl_renderer`, `hardware_profile`, `requested_profile`, `resolution`, `hostname`, `ip_addresses`, `control_port`, `control_urls` (hostname.local and each address, with IPv6 brackets), `state_recovered`, and rejected document lists. The T1 stubs publish empty device lists/neutral levels. Detected hardware profile is null until T2 publishes low/high; main does not overwrite a profile detected by Engine. Network addresses are read locally via `hostname -I`, with a hostname-resolution fallback.
- **Schema (S2/M5/M7):** settings and scenes use `modes: {"mode-id": {params:{...},quality:"low|medium|high"}}`. Parameter objects are free-form. `mode` and auto-cycle mode ids are nonempty strings. Scene recall merges mode entries, preserving other modes' settings. `hardware_profile` is auto/low/high (auto default); T2 owns detection. Audio device remains an arbitrary ALSA name and indices allow 0–255. Camera photos come through the set-level camera configuration and runtime image registry, not persistent picture items with fake asset paths. Theme colours/palette entries must be hex; template colours may reference `@primary` etc. Palette names and scene source references are checked.
- **Persistence (B3/S3):** canonical `data/state.json` and all projections use temp-file flush/fsync, directory fsync and atomic replace. The previous good canonical contents are written durably to `state.json.bak` before replacing the current state. Invalid canonical/backup files are quarantined as `.corrupt-<timestamp>`; startup tries current, backup, defaults, logs recovery and publishes its flag. Load runs the ordered migration registry before validation: missing/version 0 is stamped 1; future versions are quarantined and backup/default recovery is used. No other migrations are currently registered. Persistent non-JSON or non-finite worker values are rejected before commit. Valid hand-edited documents are then loaded independently.
- Disk serialization/writes run under a separate flush lock, outside the state writer lock. Unchanged projections/collections are skipped. Render-thread changes must use `Store.submit(patch)` (nonblocking queue); its worker validates/applies and persistence stays debounced. Synchronous `patch`/`transaction` are server/background-worker APIs. Snapshots are recursively immutable; null is a stored value, not deletion. Graceful close drains pending submissions and flushes.
- **Archive validation (B2/M1/M6):** staged images/fonts/videos use normal ingest; JSON loop manifests have a published schema and consistency checks, plain PNG frame names and required valid PNGs. All supplied files are checked, including unreferenced ones; only referenced assets/frames are published. Fresh UUID paths and asset metadata are committed with the template. Failures remove all newly copied files/directories. Export includes manifest plus listed frames and fonts, never an unreferenced original video. ZIP has a 512-entry cap (a 300-frame loop needs 302 entries), with compressed/expanded bounds of 64 MiB low / 384 MiB high from the profile table. Individual upload/source files retain the 64 MiB cap. The import endpoint streams to its explicit profile bound instead of the generic request-read limit. Imported high-rate loops are resized/resampled to the selected profile; all supplied frames are still validated before retaining only the selected frames.
- **Profile source of truth (round 2 S1):** `visualz/schema/profiles.py` supplies low: 480×270 internal (320×180 with `pi_model='pi2'`), target 30 fps, quality low; high: internal equals output up to 1920×1080, target 60 fps, quality high. Output defaults are 1280×720 low / 1920×1080 high. T2 owns hardware detection and consumes this table rather than duplicating constants. Explicit dimension/quality choices override auto.
- **Media profile parameters:** ingest accepts `profile` and explicit `clip_size`, `clip_fps`, `logo_size`, `logo_fps`, `logo_frames`, `picture_size`; server uploads/imports resolve auto from status (fallback low). Low: clips 480×270/15 fps, logos <=192 px/10 fps/100 frames, pictures <=2048 px. High: clips 1280×720/30 fps, logos <=512 px/30 fps/300 frames, pictures <=4096 px. Both keep ten-second logo and sixty-second silent clip limits. Originals remain available. ffmpeg stays nice 19 / single decoder and encoder thread; images retain the 32-megapixel decode guard. SVG rasterisation uses ffmpeg/librsvg when available.
- **Reconversion:** `media.reconvert(asset_id)` queues work on the Store background worker (drained at shutdown). Implemented/tested `reconvert(data_dir,asset,**limits)` reruns ingest from original bytes, returning a new registered asset while keeping live old paths intact. Status `media.regenerated_asset` exposes the result; the UI may switch references explicitly. Manifest-only imported loops lack source video and return a readable error if asked to reconvert.
- **Logo GPU memory cost:** frame files, not an atlas. Low: 100×192×192×4 = **14,745,600 bytes (14.0625 MiB)** if all frames were resident; current/next textures only = **294,912 bytes (288 KiB)**. High: 300×512×512×4 = **314,572,800 bytes (300 MiB)** if all resident; current/next only = **2,097,152 bytes (2 MiB)**. T3 should stream/cache compressed files and retain only current/next GPU textures, not eagerly allocate every texture. Imports use the same profile size/rate/count caps.
- **Telemetry safety (round 2 B1):** publication and defensive send-time coercion convert NumPy scalars/arrays to Python values, tuples/sets to lists, NaN/infinities to null, and unknown objects to safe strings with one logged warning per key. The same coercer handles command results and image metadata. Tick exceptions are logged and do not stop the loop; supervisors restart state/telemetry tasks if they exit unexpectedly. Tests inject both ordinary tick errors and a child cancellation and then require subsequent messages.
- **Hand edits (round 2 S3):** overlays, scenes and picture sets share validation/quarantine. Rejected bytes move to `<id>.invalid.json` and readable errors to `<id>.invalid.txt`; further failures use timestamped sibling names without overwriting prior rejected edits. Last valid versions remain live. Startup and flush protect rejected files; externally changed files are also validated before any overwrite/delete, using the same document validator. Quarantine failures protect the original in place. `stage.rejected_overlays`, `rejected_scenes`, `rejected_picture_sets` list errors across restarts. `overlays.reload()` queues a folder reread so valid edits take effect without restarting. It reloads all three shared collections.
- **GL (S1/S5):** default Quad UVs suit top-down uploads; use `Quad(flip_v=True)` when sampling FBO textures to preserve vertical orientation through upscales/feedback. KMS paths set `PYOPENGL_PLATFORM=egl` before importing OpenGL. Smoke now uploads a texture, renders to a 480×270 NPOT FBO, samples it at 1280×720 and reports fragment highp/mediump precision and selected platform. USB capture counts are read from `/proc/asound/card*/stream*` Capture sections, not configured stereo PCM widths. Non-USB/plugin channel limits are explicitly unknown.
- Unknown template IDs and missing export assets return readable 404s (M2). Picture-set deletion clears active and saved-scene references; referenced asset deletion rejects with a clear message, unreferenced asset deletion removes its files (M3).
- Suggestions 1/2 also implemented: cached validators, validation of changed documents, coalesced full-state broadcasts and concurrent sends with a timeout. Neutral meter status excludes waveform/spectrum arrays. Suggestion 3 (disable PyOpenGL error checking) is deferred: preserve diagnostics through the still-unverified hardware gate, then measure/profile before disabling globally.
- Python 3.11.18 used for verification. Pip ALSA builds need gcc/libasound2-dev; Bookworm deployment uses apt. Desktop software Mesa advertises newer ES despite requesting ES 2; only ES 2 APIs/GLSL ES 1.00 are used, but this is not proof of VideoCore IV support.

## Open questions
None blocking T1. No round 2 finding or requested lead decision was declined. Real worker behaviour, profile detection and hardware testing remain the planned T2/human work.

---
## Receiver ack
Lead acknowledges the return through the ledger; implementer did not edit the ledger.

---
## Return (implementer → lead)
- **Outcome:** round 1 confirmed fixed; all round 2 findings and six lead decisions addressed; ready for re-review. The complete diff was re-read for JSON boundary failures, command error propagation, profile/ZIP cap consistency and hand-edit data loss.
- **Verification output:**
```text
$ .venv/bin/ruff check . && .venv/bin/pytest
All checks passed!
collected 66 items
63 passed, 3 skipped in 7.76s

$ xvfb-run -a .venv/bin/pytest tests/media tests/server/test_process.py -q
17 passed, 1 warning in 6.66s
```
Three headless skips require a display: GL lifecycle/orientation, smoke rendering and real application integration. All three pass under Xvfb. The warning is pygame's upstream pkg_resources deprecation. The integration test covers the original stage/worker commands, status fields/control URLs, queued blackout and restart exit 1 with flushed state; dedicated tests cover media reconversion and document reload. New tests cover decisions 1–6, including NumPy/NaN/object coercion, supervision, profile conversion, frame budgets/slow-handler diagnostics, lossless rejection/reload, correlation/503 handling, and version migration/future-version recovery.
- **Decisions made:** the lead's round 1 and round 2 review decisions are implemented as described above; no further ADR requested.
- **Out-of-scope issues:** hardware unavailable; optional global error-check disabling deferred with rationale above.
- **Follow-ups:** cross-family re-review, then human hardware smoke gate; carry these revised schemas and runtime contracts into T2–T5 dispatches.
- **For GBrain (lead to promote):** USB channel counts must come from hardware descriptors, not an opened PCM's configured stereo width; FBO and Pillow texture origins differ; durable recovery and render-safe queued state mutation are essential for a power-cut-operated stage box.
