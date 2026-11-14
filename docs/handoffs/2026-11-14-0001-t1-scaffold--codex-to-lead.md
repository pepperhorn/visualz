# Handoff: 0001-t1 — Scaffold foundation (codex → lead)

- **Date:** 2026-11-14
- **Type:** return
- **Ledger:** 0001 · **Spec:** [0001](../specs/0001-audio-reactive-visuals.md) · **Plan:** [0001, T1](../plans/0001-audio-reactive-visuals.md)
- **Branch:** orch/0001-t1-scaffold
- **Worktree:** /home/t3box/.t3/worktrees/visualz/t3-973ffe37-9ffd194d47c599aa
- **PR:** draft opened after this handoff commit; see branch PR and final task response.
- **Base commit:** 5f0c2fae8ce4327878357d2721d38a97a34f83bd
- **Implementation commit:** 6e075f3beb8ab0827f70098fef30a9f5e0dc5343
- **Port:** 5211
- **Status:** closed (implementation complete; awaiting review and hardware gate)

## Goal
Deliver the T1 Python foundation on which T2–T5 can build: persistent contracts, state, control server, media ingest, ES 2 helpers, documented worker interfaces, animated test pattern and a standalone hardware smoke test.

## Context you need
Read [dispatch and acknowledgement](2026-11-14-0001-t1-scaffold--lead-to-codex.md), [native renderer ADR](../decisions/0002-native-renderer.md), [spec](../specs/0001-audio-reactive-visuals.md), and [plan](../plans/0001-audio-reactive-visuals.md). No conversation history is required.

## Scope
- **In:** all T1 scope: Python packaging, schema/defaults, store, REST/WebSocket server, bounded uploads/conversion and template archives, GL helpers, main loop, neutral stubs, placeholder control page, hardware smoke script and tests.
- **Out:** real capture/analysis, visual modes, overlay composition, full UI, fonts and deployment (T2–T5).
- **Files owned/changed:** `pyproject.toml`, `ruff.toml`, `visualz/{__init__,__main__}.py`, `visualz/{state,schema,server,media,gl}/**`, stub `visualz/{audio,render,camera,overlay}/__init__.py`, `web/index.html`, `tools/smoke.py`, `tests/{state,schema,server,media}/**`, `tests/conftest.py`, and the two task handoffs.
- **Do not touch:** ledger and all other lead docs; no unowned files were changed.

## Acceptance criteria
- [x] AC9: published JSON Schema contracts, readable validation errors, atomic rejection; malformed hand-edited overlay files log a warning and retain the last valid template.
- [x] AC13 server: image logo template exports/imports into a fresh data directory with remapped, collision-safe asset paths. Manifest loops export their companion frame files; referenced fonts use the same asset mechanism.
- [x] AC14: two WebSocket clients receive identical committed state; reconnect receives current full state; telemetry is separate at 10 Hz.
- [x] AC15: canonical state persists across restart, with per-collection JSON and settings projections; snapshots are recursively immutable.
- [x] AC18: required verification passes (output below).
- [x] Persistent schema fields cover settings, pixel/halftone alternatives, full/quantised colour depth, palettes/theme, scenes, auto-cycle, overlay typography/animation/variables, gallery transitions and playback, camera settings, and now-playing. No named persistent spec field was left unexpressed. Mode-specific parameters remain an extensible scalar map for T2.
- [x] Uploads are bounded to 64 MiB, filenames decoded/sanitised, content checked; ZIP paths, expanded size, entry count, missing references and symlinks are checked.
- [x] Image downscale, MP4/WebM/GIF clip conversion, original retention, 60-second trim warning, and 10-second/150-frame logo cap tested with real ffmpeg.
- [x] Real application window starts on a virtual desktop, serves `/control` through the server thread, accepts an HTTP state change, exits cleanly on SIGTERM.
- [x] Headless GL test skips cleanly; explicit virtual-desktop ES test passes, including texture upload/update, framebuffer, and sub-quad UV sampling.
- [x] Render loop reads snapshots without holding locks or waiting on disk/server; worker stubs are neutral and their final signatures are documented.
- [x] `tools/smoke.py --help` works without runtime imports; desktop smoke works and device failures print plain messages.
- [ ] Human hardware gate: run `python3 tools/smoke.py` on the actual Pi 2/3 before dispatching T2–T5. KMS/DRM, VideoCore shader compatibility, USB device capabilities and target frame rates remain unverified.

## Verify with
```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
# Optional Linux desktop verification:
xvfb-run -a .venv/bin/pytest tests/media/test_ingest.py::test_gl_lifecycle_when_display_available -q
python3 tools/smoke.py --help
# Human Pi gate, apt packages only; no package installation required:
python3 tools/smoke.py
```

## Known gotchas / decisions already made
- GBrain: unavailable. No GBrain pages were consulted or written.
- Contracts are documented in module docstrings in `schema`, `server`, `state`, and worker stubs. Audio channels are zero-based; colours are `#RRGGBB[AA]` or `@primary`/`@accent`/`@text`/`@background`.
- REST uses `/api/settings`, `/api/now_playing`, `/api/{scenes,overlays,picture_sets,assets}` and `/api/state`. WebSocket `/ws` accepts `{type:"patch",patch:{...}}`; broadcasts are full `{type:"state",state:{...}}` snapshots. No revision/optimistic-lock protocol: serialized changes use last writer wins, while disjoint nested patches merge.
- `Store.transaction(change)` is the atomic mutation hook; `patch()` recursively merges objects and replaces arrays/scalars. Null is a stored value, not deletion. CRUD DELETE removes items explicitly. `snapshot()` is for renderers, `get()` for mutable JSON copies.
- Canonical `data/state.json` is atomically replaced after a 200 ms debounce and flushed at shutdown; per-collection JSON files are projections. Valid hand-edited overlay JSON is loaded at startup; invalid edits retain canonical values and log the rejection.
- Logo loops use a frame-file manifest (`fps`, `duration`, relative `frames`) at 256 px, 15 fps, <=150 frames; this is the allowed frame-file alternative to an atlas. Gallery clips are 480×270, 15 fps, silent MPEG4 MP4; original bytes stay under the asset directory. Images have a 32-megapixel decode guard and are downscaled to <=2048 px. SVG logo rasterisation uses ffmpeg's librsvg decoder when available.
- Archive imports preserve companion file layout, remap paths and register referenced assets. ZIP expansion is limited to 64 MiB/300 entries. Preview calls the exact T3 `render_preview(template, variables, size)` seam; it is transparent until T3 implements it.
- Example defaults contain the three required template structures; final example styling/font bundling remains T3 work. Audio/camera capture and overlay drawing intentionally remain stubs.
- Python 3.14 was this host's default; pygame lacked a wheel. Verification used an installed Python 3.11.18 interpreter. Pip-based ALSA builds also needed `gcc` and `libasound2-dev`, now noted in packaging comments. Pi deployment should use apt dependencies as planned.
- Desktop GL was Mesa llvmpipe, reporting OpenGL ES 3.2 after a minimum ES 2 request. Only ES 2 APIs/GLSL ES 1.00 are used, but this does not establish VideoCore IV compatibility.
- Smoke ALSA counts are the opened PCM's configured channel count, not a proof of maximum XR18 hardware channels. Real USB capture/channel enumeration is T2 and hardware verification.

## Open questions
None blocking T1. No `.gitignore` changes are needed; existing ignores cover venv, bytecode, egg-info and data. No dependency, architecture or scope decision outside ADR 0002 was introduced.

---
## Receiver ack
Lead acknowledges this return through the ledger; implementer did not edit it.

---
## Return (implementer → lead)
- **Outcome:** done; hardware gate pending with human.
- **What changed:** complete T1 foundation in the owned files, with documented seams for T2–T5.
- **Verification output:**
```text
$ .venv/bin/ruff check . && .venv/bin/pytest
All checks passed!
collected 25 items
24 passed, 1 skipped in 2.40s

$ xvfb-run -a .venv/bin/pytest tests/media/test_ingest.py::test_gl_lifecycle_when_display_available -q
1 passed, 1 warning in 0.44s
# Warning is pygame's upstream pkg_resources deprecation.

$ xvfb-run -a .venv/bin/python /tmp/visualz-launch-check.py
Control: http://0.0.0.0:5211/control
Window startup + real threaded HTTP API: PASS
Clean shutdown exit: 0
# Temporary integration driver launched python -m visualz --window --port 5211
# --size 320x180, checked HTTP GET/PATCH and terminated with SIGTERM.

$ xvfb-run -a .venv/bin/python tools/smoke.py --window --seconds 1
GL VENDOR: Mesa
GL RENDERER: llvmpipe (LLVM 21.1.8, 256 bits)
GL VERSION: OpenGL ES 3.2 Mesa 26.0.8-1ubuntu0.3
GL maximum texture size: 16384
Display: 82.6 fps (83 frames)
# ALSA devices were listed; v4l2-ctl was absent, reported without a traceback.

$ python3 tools/smoke.py --help
usage: smoke.py [-h] [--window] [--seconds SECONDS]
```
- **Decisions made:** full-state WebSocket messages, canonical state plus JSON projections, frame files for logos, explicit bounded ingest defaults, and colour-reference spelling are recorded above; no new ADR requested.
- **Out-of-scope issues found:** Pi hardware remains unavailable. Upstream pygame deprecation does not affect execution.
- **Follow-ups:** lead arranges cross-family review, then human Pi smoke gate before later tasks; carry API/stub contracts into subsequent dispatches.
- **For GBrain (lead to promote):** request ES 2 explicitly but verify on real VideoCore IV; a desktop driver may return newer ES. Python 3.14 development currently requires pygame build dependencies or a Python 3.11 development environment.
