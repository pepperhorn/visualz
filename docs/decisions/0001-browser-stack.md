# ADR 0001 — Render in a kiosk browser (WebGL + Web Audio), served by a small Node server

- **Status:** superseded by 0002 (never built: the target hardware changed to Pi 2/3)
- **Date:** 2026-11-14 · **Work item:** 0001

## Context
We need GPU-accelerated generative visuals on a Raspberry Pi, audio capture from USB devices, text and video overlays with arbitrary fonts and colours, and a web UI to control it all from a phone.

## Decision
One TypeScript codebase. A Node server on the Pi serves two pages and relays state over WebSocket:
- **Stage** (`/`): fullscreen Chromium in kiosk mode on the projector output. Visuals are WebGL2 fragment shaders; audio comes from `getUserMedia` + Web Audio `AnalyserNode`; the overlay is plain DOM/CSS above the canvas (text, `<img>`, looping `<video>`).
- **Control** (`/control`): the web UI, opened from any device on the same network.

Build with Vite; tests with Vitest; state and overlay templates validated with Zod schemas shared by server and both pages.

## Alternatives considered
- **Python + pygame/moderngl**: simple audio capture, but fonts, video loops, and layout for the overlay all have to be hand-built, and the control UI is a second stack.
- **openFrameworks / C++**: fastest, slowest to iterate on, hardest for others to add modes.
- **Processing / Hydra / projectM**: good visuals, but no overlay templating or control UI that fits; we'd be wrapping them anyway.

## Consequences
- Overlay fonts, colours, and video are free (CSS and `<video>`).
- Needs Raspberry Pi OS with desktop (Chromium) and a Pi 4 or 5; Pi 3 and Zero are not targeted.
- Shader cost is controlled by rendering to a low-resolution buffer and upscaling, which also gives the pixel look.
- Mic permission in kiosk mode needs the `--use-fake-ui-for-media-stream` Chromium flag.
- Development and most testing work on any laptop browser, no Pi required.
