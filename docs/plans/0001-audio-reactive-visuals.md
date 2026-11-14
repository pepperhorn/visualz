# Plan 0001 — Audio-reactive visuals for live shows (v1)

- **Spec:** ../specs/0001-audio-reactive-visuals.md
- **Base:** main @ initial scaffold commit
- **Verification (whole item):** `npm run lint && npm test && npm run build`

## Approach
See [ADR 0001](../decisions/0001-browser-stack.md). One npm package, three areas:

```
shared/      Zod schemas + types: Settings, Scene, OverlayTemplate, WS messages, defaults
server/      Node HTTP + WebSocket: state store, data/ persistence, uploads, import/export
src/stage/   projector page: audio/, visuals/ (engine + modes), overlay/
src/control/ control UI page
deploy/      Pi install script, systemd unit, kiosk autostart
```

State model: the server holds the single source of truth (settings, active scene, active overlay, now-playing). Clients send patches over WebSocket; the server validates, persists (debounced), and broadcasts. The stage additionally publishes audio levels and its device list at a low rate for the control UI meter.

T1 lands first and fixes the seams so the rest can run in parallel: it creates the shared schemas, and stub entry points `startVisuals()` and `mountOverlay()` that T2 and T3 fill in.

## Tasks

### T1 — Scaffold, shared schemas, server, state sync
- **Depends on:** —
- **Route:** implement (default)
- **Owns:** `package.json`, `package-lock.json`, `tsconfig*.json`, `vite.config.ts`, `eslint.config.js`, `vitest.config.ts`, `index.html`, `control.html`, `shared/**`, `server/**`, `src/lib/**` (WS client store used by both pages), `src/stage/main.ts`, `src/stage/visuals/index.ts` (stub), `src/stage/overlay/index.ts` (stub), `src/control/main.ts` (stub), `tests/shared/**`, `tests/server/**`
- **Acceptance:** AC9 (schema + validation), AC14, AC15, AC18; upload endpoints with type and size checks, and server-side downscaling of gallery pictures; template import/export endpoints (AC13 server side); `npm run dev` serves both pages with live reload on `--host 0.0.0.0`
- **Verify:** `npm run lint && npm test && npm run build`
- **Notes / gotchas:** the schemas are the contract for T2–T4, so cover every field the spec names (look controls incl. halftone, palettes, picture sets, scenes, overlay template incl. theme-colour references and variables, auto-cycle). Publish the overlay JSON Schema file from Zod. After T1 merges, T2–T4 may not edit `shared/**`: they request changes in their return handoff.

### T2 — Stage audio + visual engine + eight modes
- **Depends on:** T1
- **Route:** implement (default)
- **Owns:** `src/stage/audio/**`, `src/stage/visuals/**`, `tests/stage/audio/**`, `tests/stage/visuals/**`
- **Acceptance:** AC1–AC6 (stage side), AC19, AC20 (stage side), AC16 (design for it: low-res framebuffer, measured fps readout)
- **Verify:** `npm run lint && npm test && npm run build`
- **Notes / gotchas:** WebGL2 only. Render each mode to a low-res framebuffer, then a post pass does palette quantise + dither + nearest-neighbour upscale, or the halftone screen (run at output resolution so dots stay round). `chromascope` and `gallery` need a persistent feedback buffer (ping-pong framebuffers) and the raw waveform as a texture; `gallery` holds at most two picture textures at once and loads the next one ahead of the transition. Crossfade by rendering two modes during the fade only. Beat detection and auto-gain are pure functions with unit tests on synthetic buffers. Keep shaders cheap for the Pi's GPU: no loops over 32 iterations, no dependent texture reads in loops.

### T3 — Stage overlay renderer
- **Depends on:** T1
- **Route:** implement (alt)
- **Owns:** `src/stage/overlay/**`, `public/fonts/**`, `tests/stage/overlay/**`
- **Acceptance:** AC7, AC8, AC10 (stage side), AC11, AC12; three example templates as seed data files under `src/stage/overlay/examples/`
- **Verify:** `npm run lint && npm test && npm run build`
- **Notes / gotchas:** DOM/CSS over the canvas. Load uploaded fonts with the FontFace API. Bundled fonts must be OFL or similar: record each font's licence in `public/fonts/LICENSES.md`. Variable substitution must escape HTML.

### T4 — Control UI
- **Depends on:** T1
- **Route:** implement (alt)
- **Owns:** `src/control/**`, `tests/control/**`
- **Acceptance:** control-side of AC1, AC3–AC6, AC7–AC13, AC20 (picture-set upload, ordering, transition and amount controls); phone-portrait layout; blackout; level meter
- **Verify:** `npm run lint && npm test && npm run build`
- **Notes / gotchas:** no UI framework heavier than needed (Preact or vanilla). The overlay editor shows a scaled live preview by reusing `mountOverlay()` from T3 through its public interface only.

### T5 — Pi deployment
- **Depends on:** T1
- **Route:** implement (default)
- **Owns:** `deploy/**`, `docs/guides/pi-setup.md`
- **Acceptance:** AC17; hardware notes (USB audio options, HDMI settings)
- **Verify:** `shellcheck deploy/*.sh` plus the whole-item command
- **Notes / gotchas:** Bookworm uses Wayland (labwc): kiosk autostart differs from older X11 guides. Chromium flags: `--kiosk --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream`. Cannot be fully verified without hardware: the return handoff must say what was and wasn't tested.

## Merge order
T1 → (T2, T3, T4, T5 in parallel, any order) → lead runs the whole-item verification and an end-to-end check on main.

## Risks
- **Pi GPU performance** on the heavier modes (`liquid`, `kaleido`, `gallery`, and anything using feedback buffers). Mitigation: internal resolution scaling, per-mode quality setting; AC16 is checked on real hardware by the human.
- **Schema churn** after T1. Mitigation: T1 covers the full spec surface; later changes go through the lead as a quick item.
- **Kiosk audio permission and device naming** vary by OS release. Mitigation: T5 documents the tested OS version.
- **Hardware-only criteria** (AC16, AC17) cannot be verified by agents and need a run on the user's Pi.
