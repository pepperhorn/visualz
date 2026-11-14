# Plan 0001 — Audio-reactive visuals for live shows (v1)

- **Spec:** ../specs/0001-audio-reactive-visuals.md
- **Base:** main @ the commit that adds this plan
- **Verification (whole item):** `.venv/bin/ruff check . && .venv/bin/pytest`

## Approach
See [ADR 0002](../decisions/0002-native-renderer.md). One Python package, one process:

```
visualz/
  __main__.py     entry point and main loop wiring                      T1
  state/          state store, patch/validate/persist, change events   T1
  schema/         JSON Schema files, defaults, validation helpers      T1
  server/         aiohttp REST + WebSocket, uploads, import/export     T1
  media/          upload ingest: image downscale, video -> frame loop  T1
  gl/             ES 2.0 helpers: context, shader, quad, texture, FBO  T1
  audio/          ALSA capture thread, analysis                        T2
  render/         engine, post pass (pixel/halftone), modes/*.frag     T2
  camera/         webcam still capture worker                          T2
  overlay/        layout, Pillow rasteriser, GL drawing, animations    T3
  fonts/          bundled fonts + licences                             T3
web/              static control UI (HTML/JS/CSS, no build)            T4
deploy/           install script, systemd unit, boot config            T5
tests/            mirrors the package layout
```

State model: the store is the single source of truth (settings, active scene, active overlay, now-playing, picture sets). The control UI sends patches over WebSocket; the server thread validates against the schema, applies, persists (debounced) to `data/`, and broadcasts. The render loop reads an immutable snapshot each frame, so no locks are held while drawing. The audio thread publishes levels the same way; the server relays them to control clients at about 10 Hz for the meter.

T1 lands first and fixes the seams: schemas, the GL helpers, and stub modules with the function signatures T2 and T3 fill in (`render.Engine`, `overlay.Overlay`, `overlay.render_preview`, `audio.Analyser`, `camera.Worker`). After T1, the human runs the hardware smoke test on the real Pi before T2 to T5 are dispatched.

## Tasks

### T1 — Scaffold, schemas, state, server, media ingest, GL helpers, smoke test
- **Depends on:** —
- **Route:** implement (default)
- **Owns:** `pyproject.toml`, `ruff.toml`, `visualz/__init__.py`, `visualz/__main__.py`, `visualz/state/**`, `visualz/schema/**`, `visualz/server/**`, `visualz/media/**`, `visualz/gl/**`, stub `__init__.py` in `visualz/{audio,render,camera,overlay}/`, `web/index.html` (placeholder), `tools/smoke.py`, `tests/state/**`, `tests/schema/**`, `tests/server/**`, `tests/media/**`, `tests/conftest.py`
- **Acceptance:** AC9, AC13 (server side), AC14, AC15, AC18; upload endpoints with type and size checks, sanitised names, image downscale, logo video to frame loop and gallery clip to low-res low-fps file via ffmpeg (original kept); `python -m visualz --window` opens a window on a laptop showing a test pattern and serves the placeholder UI on `0.0.0.0`
- **Verify:** `.venv/bin/ruff check . && .venv/bin/pytest`
- **Notes / gotchas:** the schemas are the contract for T2 to T4, so cover every field the spec names: look controls incl. halftone, palettes, theme colours, scenes, auto-cycle, picture sets incl. camera sets, overlay templates with variables. After T1 merges, other tasks may not edit `visualz/schema/**`: they request changes in their return handoff. `tools/smoke.py` is a standalone script for the real Pi: opens KMS/DRM with ES 2.0, draws an animated shader, prints fps, GL renderer string, ALSA capture devices, and video devices. Tests that need a GL context must skip cleanly when none is available. Runtime dependencies must exist as Raspberry Pi OS Bookworm apt packages: list the apt names in `pyproject.toml` comments for T5.

### T2 — Audio, render engine, eight modes, camera worker
- **Depends on:** T1 (and a passing smoke test on the Pi)
- **Route:** implement (default)
- **Owns:** `visualz/audio/**`, `visualz/render/**`, `visualz/camera/**`, `tests/audio/**`, `tests/render/**`, `tests/camera/**`
- **Acceptance:** AC1 to AC6 (stage side), AC16 (design for it; fps readout), AC19, AC20, AC21 and AC22 (stage side), AC23 (stage side), AC24
- **Verify:** `.venv/bin/ruff check . && .venv/bin/pytest`
- **Notes / gotchas:** GLSL ES 1.00 only, `precision mediump float` unless a mode proves it needs more; constant loop bounds of 16 or fewer; at most 2 texture reads per pixel in a mode. Render the mode to a low-res framebuffer; the post pass does palette quantise + dither + nearest upscale, or the halftone screen at output resolution. Crossfade renders two modes only during the fade. `chromascope` and `gallery` use ping-pong feedback framebuffers; the waveform goes in as a small texture (L and R rows). `gallery` holds at most two picture textures and uploads the next one ahead of the transition, off the frame it is needed. Beat detection and auto-gain are pure NumPy functions tested on synthetic buffers. Open the capture device by a configurable ALSA name taken from settings, never a hard-coded hardware device: item 0003 will point it at a shared-capture device so a recorder can read the mixer at the same time. Read only the two chosen channels out of however many the device delivers. Audio capture and camera capture run on threads and must never block the render loop; a missing or unplugged device degrades to idle animation, not an exception. Clips play through a decoder thread (for example an ffmpeg subprocess piping raw frames of the pre-converted file) into a small frame queue; the render loop only uploads the newest ready frame and never waits. Only one clip decodes at a time on a Pi 2. Camera stills via a subprocess grab (ffmpeg or v4l2) so no heavy vision library is needed.

### T3 — Overlay
- **Depends on:** T1
- **Route:** implement (alt)
- **Owns:** `visualz/overlay/**`, `visualz/fonts/**`, `tests/overlay/**`
- **Acceptance:** AC7, AC8, AC10 (stage side), AC11, AC12; three example templates as seed files in `visualz/overlay/examples/`; `render_preview(template, variables, size)` returns a Pillow image using the same layout code as the stage
- **Verify:** `.venv/bin/ruff check . && .venv/bin/pytest`
- **Notes / gotchas:** rasterise each element with Pillow only when its inputs change, cache the texture, and animate with quad position and alpha. Text features: font, size, weight (via font file), letter-spacing, upper-case, colour with alpha, background box, outline, shadow, alignment. Frame-loop logos play from a texture atlas produced by T1's media ingest. Bundled fonts must be OFL or similar, with each licence recorded in `visualz/fonts/LICENSES.md`. Layout is tested without GL by comparing `render_preview` output properties (bounds, colours at sample points).

### T4 — Control UI
- **Depends on:** T1
- **Route:** implement (alt)
- **Owns:** `web/**`, `tests/web/**`
- **Acceptance:** control side of AC1, AC3 to AC13, AC20 to AC24; phone-portrait layout; blackout; level meter; reconnects by itself
- **Verify:** `.venv/bin/ruff check . && .venv/bin/pytest`
- **Notes / gotchas:** static files, no build step, no CDN: vanilla JS modules (a small vendored library is acceptable if its licence is recorded). Overlay previews come from the server preview endpoint, not from re-implementing layout in the browser. Forms are generated from the JSON Schemas where practical so new fields appear without UI work.

### T5 — Pi deployment
- **Depends on:** T1
- **Route:** implement (default)
- **Owns:** `deploy/**`, `docs/guides/pi-setup.md`
- **Acceptance:** AC17; Wi-Fi client setup for a named network at install time; hardware notes (USB audio interfaces, multichannel mixers over USB, webcams, HDMI mode, Pi 2 Wi-Fi adapter)
- **Verify:** `shellcheck deploy/*.sh` plus the whole-item command
- **Notes / gotchas:** Raspberry Pi OS Lite Bookworm 32-bit. Install runtime dependencies with apt, not pip. systemd unit with `Restart=always`, running as a non-root user in the `video`, `render`, `audio`, and `input` groups. Set the HDMI mode to 720p and enough GPU memory. Keep Raspberry-Pi-specific steps (boot config, GPU memory) in clearly separated functions so a second board (Orange Pi Zero 2W on Armbian) can be added later without rewriting the script. Cannot be fully verified without hardware: the return handoff must say what was and wasn't tested.

## Merge order
T1 → human runs `tools/smoke.py` on the Pi → (T2, T3, T4, T5 in parallel, any order) → lead runs the whole-item verification on main → human runs the hardware criteria.

## Risks
- **pygame + KMS/DRM + ES 2.0 on the Pi 2/3** is unproven here. Mitigation: the smoke test gate after T1. Fallback if it fails: create the context with raw EGL/GBM bindings, contained in `visualz/gl/`.
- **GPU performance**, especially `liquid`, `kaleido`, `gallery`, the feedback buffers, and halftone at output resolution on a Pi 2. Mitigation: internal resolution and per-mode quality settings; the halftone pass may drop to half output resolution.
- **Shader compiler limits** on VideoCore IV differ from desktop drivers, so a shader that works on a laptop may fail on the Pi. Mitigation: strict GLSL rules in T2, and the human's hardware pass.
- **Clip playback cost** on a Pi 2: decoding plus a texture upload every frame. Mitigation: clips are pre-converted to the internal resolution at 12 to 15 fps; the frame rate may drop further on a Pi 2.
- **Memory**: 1 GB shared with the GPU. Mitigation: caps on picture size, picture count, and logo loop length.
- **Hardware-only criteria** (AC16, AC17, AC21 with a real webcam) cannot be verified by agents and need a run on the user's Pi.
- **Schema churn** after T1. Mitigation: T1 covers the full spec surface; later changes go through the lead as a quick item.
