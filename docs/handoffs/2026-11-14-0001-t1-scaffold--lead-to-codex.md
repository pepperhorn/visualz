# Handoff: 0001-t1 — Scaffold, schemas, state, server, media ingest, GL helpers, smoke test (lead → codex)

- **Date:** 2026-11-14
- **Type:** dispatch
- **Ledger:** 0001 · **Spec:** docs/specs/0001-audio-reactive-visuals.md · **Plan:** docs/plans/0001-audio-reactive-visuals.md (task T1)
- **Branch:** orch/0001-t1-scaffold · **Worktree:** created by T3
- **PR:** —
- **Base commit:** 5f0c2fae8ce4327878357d2721d38a97a34f83bd
- **Port (if running a server):** 5211
- **Status:** open

## Goal
Create the Python project for visualz and everything the four later tasks build on: packaging and tooling, the JSON Schemas and defaults for all persistent data, the state store, the embedded web server (REST + WebSocket, uploads, import/export), media ingest, the OpenGL ES 2.0 helper layer, a main loop that shows a test pattern, stub modules with agreed signatures for audio, render, camera, and overlay, and a standalone hardware smoke test script for a Raspberry Pi 2/3. Done means `python -m visualz --window` runs on a Linux desktop, the API works end to end under test, and the verify command passes.

## Context you need
Read in this order:
1. `AGENTS.md`
2. `docs/decisions/0002-native-renderer.md` — the stack. ADR 0001 is superseded: ignore it.
3. `docs/specs/0001-audio-reactive-visuals.md` — the whole spec. You implement only part of it, but your schemas must cover all of it.
4. `docs/plans/0001-audio-reactive-visuals.md` — the layout, the state model, and task T1. Read T2 to T5 as well so your seams fit them.
5. `docs/mockups/index.html` — visual reference for what the data has to describe (overlay templates, look controls, picture sets).

Nothing exists in the repo yet except docs. You are creating the first code.

## Scope
- **In:**
  - `pyproject.toml` with runtime deps and a `dev` extra (ruff, pytest, pytest-asyncio or equivalent), an entry point, and comments listing the Raspberry Pi OS Bookworm apt package name for each runtime dependency.
  - `visualz/schema/`: JSON Schema files and defaults for Settings (audio incl. device and L/R channel choice, look controls incl. pixel and halftone, palettes, theme colours, auto-cycle, stage resolution), Scene, OverlayTemplate (logo bug, text blocks, animation, variables, theme-colour references), PictureSet (pictures, clips with playback options, camera sets with interval and keep-count), NowPlaying. A validation helper returning readable errors.
  - `visualz/state/`: the store. Patch, validate, apply, debounced persist to `data/`, change subscription, immutable snapshot for the render loop. Thread-safe.
  - `visualz/server/`: aiohttp app running on its own thread. REST for settings, scenes, overlays (CRUD, ordering, take-live, next/prev/clear), picture sets, assets, now-playing, blackout; WebSocket for patches and broadcasts, plus a low-rate channel for audio levels and stage status (fps, devices); uploads; overlay template export/import as a zip including referenced assets; an overlay preview endpoint that calls `overlay.render_preview`.
  - `visualz/media/`: ingest. Images: type-check, downscale to a GPU-safe size. Logo video and GIF: convert with ffmpeg to a frame loop of at most 10 seconds (atlas or frame files plus a small manifest). Gallery clips: convert with ffmpeg to a low-resolution, 12 to 15 fps, silent file, trim to 60 seconds with a warning, keep the original. Fonts: accept TTF/OTF only.
  - `visualz/gl/`: context creation through pygame/SDL2 with an OpenGL ES 2.0 profile (windowed on desktop, KMS/DRM fullscreen on the Pi), shader compile and link with readable errors, fullscreen quad, textured quad with alpha, texture upload and update from bytes or a Pillow image, framebuffer objects.
  - `visualz/__main__.py`: argument parsing (`--window`, `--port`, `--data-dir`, `--size`), starts the server thread, runs the main loop calling the engine and overlay stubs, shuts down cleanly.
  - Stubs in `visualz/audio/__init__.py`, `visualz/render/__init__.py`, `visualz/camera/__init__.py`, `visualz/overlay/__init__.py`: classes and functions with final signatures and docstrings (`audio.Analyser`, `render.Engine`, `camera.Worker`, `overlay.Overlay`, `overlay.render_preview(template, variables, size)`), doing the minimum (the render stub draws a test pattern; the others return neutral values). Document each signature: later tasks replace the bodies, not the interfaces.
  - `web/index.html`: a placeholder page that connects to the WebSocket and prints the state, so the server can be tried by hand.
  - `tools/smoke.py`: standalone script for a real Pi 2/3. Opens KMS/DRM with ES 2.0, draws an animated shader for 15 seconds, prints fps, the GL vendor/renderer/version strings, maximum texture size, ALSA capture devices with channel counts, and video capture devices. Must depend only on the apt packages and give a clear message for each thing that fails rather than a stack trace.
  - Tests for schema, state, server, and media.
- **Out:** real audio capture and analysis, visual modes, the post pass, camera capture, overlay layout and drawing, the control UI, deployment scripts. Those are T2 to T5.
- **Files you own:** `pyproject.toml`, `ruff.toml`, `visualz/__init__.py`, `visualz/__main__.py`, `visualz/state/**`, `visualz/schema/**`, `visualz/server/**`, `visualz/media/**`, `visualz/gl/**`, the stub `__init__.py` in `visualz/audio/`, `visualz/render/`, `visualz/camera/`, `visualz/overlay/`, `web/index.html`, `tools/smoke.py`, `tests/state/**`, `tests/schema/**`, `tests/server/**`, `tests/media/**`, `tests/conftest.py`, and your own handoff files (the ack section below, and `docs/handoffs/2026-11-14-0001-t1-scaffold--codex-to-lead.md`).
- **Do not touch:** any other file under `docs/`, `AGENTS.md`, `CLAUDE.md`, `.ph-orch.json`, `README.md`, `LICENSE`, `.claude/`. If `.gitignore` needs a line, say so in the return handoff.

## Acceptance criteria
- [ ] Spec AC9: overlay templates are JSON files validated against the schema; an invalid file is rejected with a readable error and is never loaded into state.
- [ ] Spec AC13 (server side): overlay templates export and re-import with their assets, into a fresh data directory.
- [ ] Spec AC14: two WebSocket clients stay in sync; a client that reconnects receives the full current state.
- [ ] Spec AC15: all state persists across a restart of the program.
- [ ] Spec AC18: the verify command passes.
- [ ] The schemas cover every field the spec names for settings, look, palettes, theme colours, scenes, auto-cycle, overlay templates, picture sets (pictures, clips, camera), and now-playing. List in the return handoff any spec item you could not express.
- [ ] Uploads reject wrong types and oversized files, and sanitise file names (no path escapes).
- [ ] Media ingest produces: a downscaled image; a logo frame loop of at most 10 seconds; a converted gallery clip with the original kept. Tests that need ffmpeg skip cleanly when it is not installed.
- [ ] `python -m visualz --window` opens a window with an animated test pattern and serves the placeholder page on `0.0.0.0:<port>`; changing state through the API is visible in the placeholder page.
- [ ] Tests that need a GL context or a display skip cleanly when none is available; the suite passes headless.
- [ ] The render loop never blocks on the server thread or on disk.
- [ ] `tools/smoke.py --help` works on a desktop, and the script's failure paths print plain messages.
- [ ] Stub signatures are documented and match the plan's names.

## Verify with
```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
```

## Known gotchas / decisions already made
- GBrain: unavailable.
- Target is a Raspberry Pi 2/3: Python 3.11 (Raspberry Pi OS Bookworm), 32-bit ARM, 1 GB RAM, OpenGL ES 2.0 only. Do not use any language or library feature that needs Python newer than 3.11.
- Runtime dependencies must be available as Bookworm apt packages (pygame, PyOpenGL, numpy, Pillow, aiohttp, jsonschema are expected to be). If something you want is pip-only, do not add it: note it in the return handoff as a question.
- No Node, no build step, no CDN.
- Validation is JSON Schema (`jsonschema`), not pydantic, so the schema files themselves are the published contract.
- After this merges, other tasks may not edit `visualz/schema/**`, so err on the side of completeness and include sensible defaults.
- Colours in templates are either a hex value with optional alpha or a reference to a named theme colour.
- Text in overlay templates may contain `{{band}}`-style variables. In this handoff that is literal template syntax in the product, not a placeholder for you to fill.
- The server and the renderer share one process. The server runs on its own thread with its own event loop; the main thread owns GL.
- You cannot test on a Pi. Say clearly in the return handoff what was verified only on a desktop.
- The dev server must bind `0.0.0.0` and use port 5211 in this worktree.

## Open questions
None.

---
## Receiver ack
Acknowledged: I will build the Python 3.11 foundation, complete persistent JSON contracts, thread-safe store, aiohttp API and WebSocket synchronisation, bounded media ingest, ES 2 helpers, documented neutral worker interfaces and animated test pattern, plus the standalone Pi smoke test. I will change only the listed owned files and my task handoffs, verify headlessly, and return a draft PR. Hardware verification remains with the human. GBrain: unavailable. Open questions: none.

---
## Return (implementer → lead; fill in when done, or in a separate …-to-lead.md)
