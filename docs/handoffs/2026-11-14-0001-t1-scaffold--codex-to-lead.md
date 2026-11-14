# Handoff: 0001-t1 — Scaffold foundation, review round 1 (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0001 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) · **Plan:** [0001, T1](../plans/0001-audio-reactive-visuals.md)
- **Branch:** orch/0001-t1-scaffold
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-973ffe37-9ffd194d47c599aa
- **PR:** https://github.com/pepperhorn/visualz/pull/1 (draft)
- **Base commit:** 5f0c2fae8ce4327878357d2721d38a97a34f83bd
- **Initial implementation:** 6e075f3beb8ab0827f70098fef30a9f5e0dc5343
- **Review round 1 base:** 4587a47f33e23e40d5d5c1aad94baf536102b647; revisions are this branch's following commit.
- **Port:** 5211
- **Status:** implementation complete; awaiting cross-family re-review and human hardware gate.

## Goal
Deliver T1's Python foundation and address every B1–B3, S1–S5 and M1–M7 finding from review round 1. The updated spec and plan on `origin/main` were fetched and read without merging main, as directed. This document describes the resulting contracts; it supersedes the earlier return description.

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
- **Worker bridge (B1):** `visualz.state.runtime.Runtime`, available as `store.runtime`, imports no GL. Workers call `register_command(target,name,handler)`, `publish_status(target,dict)` and `publish_image(name,bytes,content_type)`; no later task needs to edit the server. Main drains at most 32 commands per frame from a bounded 128-command queue. Handlers must enqueue work or use `Store.submit`, never perform blocking operations.
- HTTP: `POST /api/stage/command {target,name,args}` returns 202 when queued; `GET /api/stage/status`; `GET /api/stage/image/<name>`. WS uses `{type:"command",target,name,args}` and returns an acceptance message. Invalid envelopes, unknown commands, bad argument names and full queues give readable errors. Execution failures appear in `status.commands.error`.
- Initial registered command signatures: `audio.refresh_devices()`, `camera.snap(set_id)`, `camera.delete_all(set_id)`, `gallery.next()`, `gallery.prev()`, `stage.restart()`, `stage.blackout(enabled,overlay=False,fade_seconds=.5)`. Audio/camera/gallery handlers are T1 stubs for T2 to replace. Restart exits non-zero after orderly cleanup; blackout submits a persistent patch.
- Status contract is documented in `state/runtime.py`: audio devices `{id,name,channels}` with actual capture channel counts and current `levels`; camera `present`, `devices`, `latest` image name/null; stage `fps`, `gl_renderer`, `hardware_profile`, `requested_profile`, `resolution`, `hostname`, `ip_addresses`, `state_recovered`. The T1 stubs publish empty device lists/neutral levels. Detected hardware profile is null until T2 publishes low/high; main does not overwrite a profile detected by Engine. Network addresses are read locally via `hostname -I`, with a hostname-resolution fallback.
- **Schema (S2/M5/M7):** settings and scenes use `modes: {"mode-id": {params:{...},quality:"low|medium|high"}}`. Parameter objects are free-form. `mode` and auto-cycle mode ids are nonempty strings. Scene recall merges mode entries, preserving other modes' settings. `hardware_profile` is auto/low/high (auto default); T2 owns detection. Audio device remains an arbitrary ALSA name and indices allow 0–255. Camera photos come through the set-level camera configuration and runtime image registry, not persistent picture items with fake asset paths. Theme colours/palette entries must be hex; template colours may reference `@primary` etc. Palette names and scene source references are checked.
- **Persistence (B3/S3):** canonical `data/state.json` and all projections use temp-file flush/fsync, directory fsync and atomic replace. The previous good canonical contents are written durably to `state.json.bak` before replacing the current state. Invalid canonical/backup files are quarantined as `.corrupt-<timestamp>`; startup tries current, backup, defaults, logs recovery and publishes its flag. Valid hand-edited overlays are then loaded independently.
- Disk serialization/writes run under a separate flush lock, outside the state writer lock. Unchanged projections/collections are skipped. Render-thread changes must use `Store.submit(patch)` (nonblocking queue); its worker validates/applies and persistence stays debounced. Synchronous `patch`/`transaction` are server/background-worker APIs. Snapshots are recursively immutable; null is a stored value, not deletion. Graceful close drains pending submissions and flushes.
- **Archive validation (B2/M1/M6):** staged images/fonts/videos use normal ingest; JSON loop manifests have a published schema and consistency checks, plain PNG frame names and required valid PNGs. All supplied files are checked, including unreferenced ones; only referenced assets/frames are published. Fresh UUID paths and asset metadata are committed with the template. Failures remove all newly copied files/directories. Export includes manifest plus listed frames and fonts, never an unreferenced original video. ZIP remains capped at 64 MiB expanded / 300 entries.
- **Logo memory (S4):** frame files, not an atlas: <=128×128, 8 fps, <=80 frames / ten seconds. Full decoded CPU cache worst case is 80×128×128×4 = 5,242,880 bytes (5 MiB). T3 should retain at most current/next GPU textures: 131,072 bytes (128 KiB), rather than create 80 GL textures; no 2048 px atlas assumption remains. Imported PNG frames are also downscaled to 128 px. This preserves the ten-second limit by reducing fps and size.
- Gallery conversion stays 480×270/15 fps/silent/<=60 seconds, retaining original bytes. ffmpeg runs at nice 19 with one decoder and one encoder thread (M4). Image uploads retain a 32-megapixel decode guard and <=2048 px GPU size. SVG rasterisation uses ffmpeg/librsvg when available.
- **GL (S1/S5):** default Quad UVs suit top-down uploads; use `Quad(flip_v=True)` when sampling FBO textures to preserve vertical orientation through upscales/feedback. KMS paths set `PYOPENGL_PLATFORM=egl` before importing OpenGL. Smoke now uploads a texture, renders to a 480×270 NPOT FBO, samples it at 1280×720 and reports fragment highp/mediump precision and selected platform. USB capture counts are read from `/proc/asound/card*/stream*` Capture sections, not configured stereo PCM widths. Non-USB/plugin channel limits are explicitly unknown.
- Unknown template IDs and missing export assets return readable 404s (M2). Picture-set deletion clears active and saved-scene references; referenced asset deletion rejects with a clear message, unreferenced asset deletion removes its files (M3).
- Suggestions 1/2 also implemented: cached validators, validation of changed documents, coalesced full-state broadcasts and concurrent sends with a timeout. Neutral meter status excludes waveform/spectrum arrays. Suggestion 3 (disable PyOpenGL error checking) is deferred: preserve diagnostics through the still-unverified hardware gate, then measure/profile before disabling globally.
- Python 3.11.18 used for verification. Pip ALSA builds need gcc/libasound2-dev; Bookworm deployment uses apt. Desktop software Mesa advertises newer ES despite requesting ES 2; only ES 2 APIs/GLSL ES 1.00 are used, but this is not proof of VideoCore IV support.

## Open questions
None blocking T1. No blocking, should-fix or minor review item was declined. Real worker behaviour, profile detection and hardware testing remain the planned T2/human work.

---
## Receiver ack
Lead acknowledges the return through the ledger; implementer did not edit the ledger.

---
## Return (implementer → lead)
- **Outcome:** all B1–B3, S1–S5 and M1–M7 addressed; ready for re-review.
- **Verification output:**
```text
$ .venv/bin/ruff check . && .venv/bin/pytest
All checks passed!
collected 47 items
44 passed, 3 skipped in 3.35s

$ xvfb-run -a .venv/bin/pytest tests/media tests/server/test_process.py -q
12 passed, 1 warning in 3.86s
```
Three headless skips require a display: GL lifecycle/orientation, smoke rendering and real application integration. All three pass under Xvfb. The warning is pygame's upstream pkg_resources deprecation. The integration test covers all registered commands, status fields, queued blackout, and restart exit 1 with flushed state.
- **Decisions made:** the lead's seven review decisions are implemented as described above; no further ADR requested.
- **Out-of-scope issues:** hardware unavailable; optional global error-check disabling deferred with rationale above.
- **Follow-ups:** cross-family re-review, then human hardware smoke gate; carry these revised schemas and runtime contracts into T2–T5 dispatches.
- **For GBrain (lead to promote):** USB channel counts must come from hardware descriptors, not an opened PCM's configured stereo width; FBO and Pillow texture origins differ; durable recovery and render-safe queued state mutation are essential for a power-cut-operated stage box.
