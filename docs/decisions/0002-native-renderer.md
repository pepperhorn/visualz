# ADR 0002 — Native Python renderer on OpenGL ES 2.0, no browser on the Pi

- **Status:** accepted (human, 2026-11-14)
- **Date:** 2026-11-14 · **Work item:** 0001 · **Supersedes:** 0001

## Context
The show must run on a Raspberry Pi 2 or 3: 1 GB RAM, a VideoCore IV GPU that supports OpenGL ES 2.0 only, and (Pi 2) a 32-bit ARMv7 CPU. Chromium with fullscreen WebGL plus a DOM overlay is too slow on a Pi 3 and unusable on a Pi 2, and WebGL2 is not available on this GPU at all.

## Decision
One Python 3 program runs on Raspberry Pi OS Lite with no desktop:
- **Display**: SDL2 (through pygame) on the KMS/DRM driver, with an OpenGL ES 2.0 context (PyOpenGL). All visuals are GLSL ES 1.00 fragment shaders rendered to a low-resolution framebuffer and upscaled.
- **Audio**: ALSA capture of the USB interface on a background thread; analysis with NumPy.
- **Overlay**: text and images are laid out and rasterised with Pillow into RGBA textures (any TTF/OTF font, any colour), then drawn as quads with animated position and opacity. Logo videos are converted on upload with ffmpeg into a short frame loop.
- **Camera**: stills grabbed from the UVC webcam at intervals by a background worker.
- **Control**: an aiohttp server inside the same process (its own thread) serves a static HTML/JS control UI and a REST + WebSocket API. No Node, no build step.
- **Schemas**: settings, scenes, and overlay templates are JSON validated against JSON Schema files in the repo.
- Tooling: ruff and pytest. Dependencies come from Raspberry Pi OS apt packages on the Pi, and from pip in a venv for development.

## Alternatives considered
- **Chromium kiosk (ADR 0001)**: best overlay ergonomics, but does not perform on the target hardware.
- **C++ or Rust with SDL2**: fastest and lightest, but slower to build and harder for others to add modes. Python's per-frame cost is small here because the GPU does the drawing and the CPU only sets a few uniforms.
- **Use a Pi 4/5**: declined by the human; the existing hardware is a Pi 2 or 3.

## Consequences
- Shaders are restricted to GLSL ES 1.00 and must be short: constant loop bounds, few texture reads, no derivatives extension assumed.
- The overlay is not HTML: layout features are what we build (text blocks, boxes, outline/shadow, images, frame loops). Rich text and CSS effects are out.
- Logo videos become frame loops with a length and size cap, stored as separate frame files with a manifest and loaded as individual textures. Frame size and rate depend on the hardware profile.
- The same program runs on a Linux laptop in a window for development, using the same ES 2.0 context.
- pygame on KMS/DRM with ES 2.0 is the main unproven piece on this hardware. T1 ships a hardware smoke test the human runs on the real Pi before the parallel tasks are dispatched.
- Stage and control server share one process: a crash takes both down, so the service restarts automatically.
