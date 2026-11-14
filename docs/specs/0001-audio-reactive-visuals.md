# 0001 — Audio-reactive visuals for live shows (v1)

- **Status:** draft
- **Ledger:** 0001 · **Plan:** ../plans/0001-audio-reactive-visuals.md
- **Author:** lead · **Date:** 2026-11-14

## Problem
The band wants projected visuals at gigs that react to the music and keep evolving, without anyone operating a VJ rig. It should be a box (a Raspberry Pi) that plugs into a projector and an audio feed, shows the band's branding like a music-TV channel, and can be steered from a phone.

## Goals
- Generative visuals driven by live audio from a USB mic or USB line-in.
- Several distinct visual modes, switchable live and able to auto-cycle.
- An 8-bit / pixel-art look available on every mode.
- Overlay: a logo bug (image or looping video) in a corner, and titles (band name, song, extra lines).
- All overlay fonts and colours configurable.
- Overlays saved as JSON templates that work like slides: build a set in advance, then switch between them live.
- A web UI to control everything from another device on the network.
- Boots straight into the show on the Pi with no keyboard.
- Runs on a Raspberry Pi 2 or 3.
- Can use a USB webcam to take photos of the room at intervals and make visuals from them.

## Non-goals
- No built-in audio input: the Pi has no onboard mic or line-in, so a USB audio device is required hardware.
- No MIDI, DMX, OSC, or Ableton Link sync.
- No user accounts or auth on the control UI (trusted local network only).
- No multi-projector mapping, edge blending, or keystone correction.
- No in-browser shader editor. New modes are added in code.
- Pi Zero and Pi 1 are not supported.
- No live webcam video on screen in v1: the camera supplies still photos only.
- No full-resolution or long-form video playback: clips are short, low-resolution source material for the visuals, not a media player.

## User-visible behaviour

### Stage (projector output)
- Fullscreen on HDMI, no cursor, no desktop. Shows the active visual mode with the active overlay on top.
- If audio is missing or silent, visuals keep moving on their own (idle animation), never a black or frozen screen.
- The stage never depends on a control device being connected.

### Audio
- Input device is chosen in the control UI from the capture devices the Pi reports. The choice persists across restarts.
- Analysis produces: overall level, bass / mid / treble energy, a spectrum, and beat onsets. All are smoothed and auto-gained so a quiet room and a loud stage both give a usable range.
- The expected source is the band's Behringer XR18 mixer connected to the Pi by USB (it is a class-compliant multichannel interface), using two of its USB send channels as left and right. Any other class-compliant USB interface with a stereo line feed works the same way. Left and right are analysed together for levels and beats, and are also available separately so modes can use the stereo image. Mono sources work too.
- On a multichannel device (for example a mixer that is itself a USB interface), the control UI picks which two input channels are left and right.
- Controls: input gain, sensitivity, smoothing. A live level meter in the control UI shows the signal is arriving.

### Visual modes
Each mode is a shader with the shared audio inputs, a slow "evolution" clock so it never loops visibly, and a small set of its own parameters. v1 ships these eight:

| Mode | Look |
|---|---|
| `pixel-eye` | 8-bit landscape with a central eye, blocky clouds, pulsing on the beat |
| `kaleido` | Mirrored, dense psychedelic pattern with flowing bands of saturated colour |
| `prism` | Triangle lattice with rainbow light rays on a dark background |
| `liquid` | Oil-and-water liquid light show: drifting blobs and bubbles, lens-like colour |
| `opart` | High-contrast warped moiré / illusion pattern |
| `plasma` | Classic demoscene plasma and tunnel, the simplest all-purpose mode |
| `chromascope` | Analogue video-synth look: glowing, feedback-trailed ribbons and Lissajous-style figures drawn directly from the audio waveform (left channel against right when the source is stereo), with drifting colour |
| `gallery` | Morphs generatively through a set of uploaded pictures (see below) |

**Gallery mode.** The user uploads a set of pictures (JPEG/PNG/WebP) into one or more named picture sets. The mode shows them as living images rather than a slideshow:
- Moves from one picture to the next with a generative transition, chosen per set or at random: flow-warp melt, pixel-sort smear, kaleidoscope fold, luminance dissolve, or feedback bloom. Transitions are triggered by time, by beats, or manually.
- While a picture is held, it is never static: audio drives slow warping, zoom-breathing, colour shifting, and feedback trails. An amount control goes from "nearly a clean photo" to "barely recognisable".
- Order is sequential or shuffled; pictures are cropped to fill or fitted with a blurred fill behind.
- This is shader-based morphing of the supplied pictures. It does not generate new imagery with an AI model (not feasible live on a Pi).
- Pictures are downscaled on upload to a size the Pi's GPU can hold.

**Video clips as source material.** A picture set can also contain video clips (WebM, MP4, or GIF), freely mixed with pictures and camera photos:
- A clip plays on a loop while it is held, and gets exactly the same treatment as a picture: generative transitions in and out, audio-reactive warping, feedback trails, the amount control, and the pixel and halftone looks.
- Playback options per clip: loop, ping-pong (forwards then backwards), or beat-jump (cuts to a random point in the clip on each beat). Playback speed can follow the audio level.
- Clips are converted on upload to a small, low-frame-rate version (about the internal render resolution, 12 to 15 fps, silent) so the Pi can play them. The original file is kept so it can be re-converted. Clips longer than 60 seconds are trimmed, with a warning.
- A clip can also be used as the source texture for `kaleido` (the kaleidoscope folds the moving image instead of a generated pattern). The same applies to any picture.
- During a transition between two clips, the outgoing clip may freeze on its last frame on a Pi 2.

**Camera as a picture source.** With a USB webcam attached, a picture set can be fed by the camera instead of uploads:
- The camera takes a still photo every N seconds (default 30, minimum 5), or on demand from a "snap now" button.
- The set keeps the most recent M photos (default 12) and drops the oldest, so the gallery is always morphing through the last few minutes of the room.
- A camera set can be mixed with uploaded pictures (e.g. band photos interleaved with crowd shots).
- Camera photos get the same treatment as any picture: transitions, audio-reactive warping, the amount control, and the pixel and halftone looks.
- Photos are kept in memory only by default and are gone at power-off. A setting saves them to `data/` instead; a button deletes all camera photos.
- The control UI shows the latest photo so the camera can be aimed, with controls for mirror, rotation, and brightness.
- If no camera is attached, the camera options are hidden and nothing else changes.

Global look controls, applied to every mode:
- **Pixel size** (1 = off, up to chunky blocks), **colour depth** (full, or quantised to a palette of 4 to 256 colours), **dither** on/off.
- **Halftone**: renders the image as a print-style dot screen. Controls: dot size, screen angle, shape (dot, line, diamond), and style (mono ink on paper colour, duotone from the palette, or CMYK with offset screen angles). Dot size can pulse with the audio. Halftone and pixel are alternatives: one is active at a time.
- **Palette**: a set of built-in palettes plus custom palettes (a list of hex colours) editable in the UI.
- Brightness, contrast, saturation, speed, audio-reactivity amount.

Mode switching:
- Pick a mode in the UI: the stage crossfades to it (fade time configurable, 0 = cut).
- **Auto-cycle**: rotate through a chosen subset of modes every N seconds or every N beats, in order or shuffled.
- **Scenes**: a saved bundle of mode + mode parameters + look controls, stored as JSON and recallable with one tap.

### Overlay
The overlay is described by a JSON **overlay template**. A template contains:
- **Logo bug**: asset (uploaded image — PNG/SVG/GIF/WebP — or video — MP4/WebM/GIF, converted on upload to a short silent loop of at most 10 seconds), corner (default bottom-right), size, margin, opacity. Optional.
- **Text blocks** (zero or more), each with: text, position (corner / lower-third / centre, plus offsets), font family, size, weight, letter-spacing, upper-case toggle, text colour, optional background box colour and padding, optional outline or shadow colour, alignment.
- **Animation**: how the overlay enters and leaves (cut, fade, slide, or MTV-style: show for N seconds at the start, then hide; optionally reappear every M minutes).
- A name and an order index.

Behaviour:
- Templates are files (`data/overlays/<id>.json`), validated against a published schema. They can be edited in the UI or by hand, exported, and imported.
- The control UI shows templates as an ordered list of slides with a preview. Tap one to take it live. Next / previous buttons and a "clear overlay" button are always visible.
- Text can use `{{variables}}` (e.g. `{{band}}`, `{{song}}`) filled from a small live "now playing" form, so one lower-third template serves every song.
- **Fonts**: a bundled set of open-licence fonts (including at least two pixel fonts and two bold display fonts) plus uploaded font files (TTF/OTF). Any font is selectable per text block.
- **Colours**: every colour in a template is a free hex/alpha value, picked with a colour picker. A template may also reference named theme colours (`primary`, `accent`, `text`, `background`) defined once in settings, so a whole set can be re-coloured in one place.
- The first run ships three example templates: logo bug only, lower-third (band + song), and full title card.

### Control UI (`/control`)
Works on a phone in portrait. Sections: Live (mode, auto-cycle, overlay slides, now-playing, blackout), Look, Audio, Overlays (template editor), Scenes, Assets (logo, video, font, and picture-set uploads), System (stage resolution, restart stage, show the Pi's address).
- Changes apply to the stage within 100 ms and are saved automatically.
- **Blackout** button: fades the stage to black (overlay optional) and back.
- Two control devices open at once stay in sync.

### On the Pi
- One install script sets up the app as a service that starts on boot and draws straight to HDMI. No desktop is needed.
- After power-on, the show is on the projector within about a minute with the last-used settings.
- The control UI is reachable at `http://<hostname>.local:<port>/control`; the address is shown on the stage for the first 20 seconds after boot.

## Constraints
- Hardware target: Raspberry Pi 2 (v1.1 or v1.2) and Pi 3 (B, B+), 1 GB RAM, Raspberry Pi OS Lite (Bookworm, 32-bit so one image serves both), HDMI out. USB audio class interface with stereo line input. Optional USB (UVC) webcam.
- GPU limits: OpenGL ES 2.0 only (GLSL ES 1.00). No WebGL2/ES3 features, short shaders, small textures (2048 px maximum, and few of them).
- Performance: output is 1280×720. Modes render at a low internal resolution and are upscaled (default 480×270 on a Pi 3, 320×180 on a Pi 2). At those defaults every mode holds at least 30 fps on a Pi 3 and at least 24 fps on a Pi 2. A per-mode quality setting may simplify the heavy modes on a Pi 2.
- Stack per ADR 0002: one Python 3 program (SDL2 on KMS/DRM, OpenGL ES 2.0, ALSA capture, Pillow for text) with an embedded web server; control UI is static HTML/JS with no build step. Python dependencies must be installable from Raspberry Pi OS apt packages.
- No network needed at the venue beyond the control device reaching the Pi. No CDN assets: fonts and libraries are bundled.
- Network: the Pi joins an existing Wi-Fi network as a client, configured at install time. A Pi 2 needs a USB Wi-Fi adapter or Ethernet.
- All persistent state lives in one `data/` directory (settings, scenes, overlays, uploaded assets) so it can be backed up or copied between Pis.
- Uploads are size-limited and type-checked; file names are sanitised.

## Acceptance criteria
- [ ] AC1 — With a USB audio input selected, the control UI level meter moves with sound, and every mode visibly responds to bass, treble, and beats.
- [ ] AC2 — With no audio device or silence, every mode keeps animating.
- [ ] AC3 — All eight modes render, can be selected from the UI, and crossfade on switch.
- [ ] AC4 — Pixel size, colour depth, dither, halftone (all three styles), and palette apply to every mode; a custom palette can be created and used.
- [ ] AC5 — Auto-cycle rotates through the selected modes by time and by beats.
- [ ] AC6 — A scene can be saved, survives a restart, and recalls mode, parameters, and look.
- [ ] AC7 — An image logo and a looping video logo each display in the chosen corner at the chosen size and opacity.
- [ ] AC8 — Text blocks render with the chosen font, size, colours, background, and position; an uploaded font can be selected and renders on the stage.
- [ ] AC9 — Overlay templates are stored as JSON files that pass schema validation; an invalid file is rejected with a readable error and never crashes the stage.
- [ ] AC10 — Templates appear as an ordered slide list; tapping one, or next/previous, changes the stage overlay with the template's animation; clear removes it.
- [ ] AC11 — `{{band}}` / `{{song}}` variables update on the stage when the now-playing form changes.
- [ ] AC12 — Changing a theme colour re-colours every template that references it.
- [ ] AC13 — Templates can be exported and re-imported (including on another install) with their assets.
- [ ] AC14 — Two control clients stay in sync; control clients reconnect by themselves after the app restarts.
- [ ] AC15 — Settings persist across a restart.
- [ ] AC16 — At default settings each mode holds at least 30 fps on a Pi 3 and at least 24 fps on a Pi 2 (measured with the built-in fps readout).
- [ ] AC17 — The install script on a fresh Raspberry Pi OS Lite image results in the stage on HDMI after reboot, with audio capture working.
- [ ] AC18 — `.venv/bin/ruff check . && .venv/bin/pytest` passes.
- [ ] AC19 — `chromascope` draws figures that follow the live waveform and leave fading trails; with a stereo source the figure changes when left and right differ.
- [ ] AC20 — With a picture set of at least three uploaded images, `gallery` moves through them with generative transitions (by time, by beats, and manually), each held picture reacts to audio, and the amount control visibly ranges from near-clean to heavily abstracted.
- [ ] AC21 — With a USB webcam attached, a camera picture set fills with photos at the set interval and on "snap now", keeps only the most recent M, and `gallery` morphs through them; the latest photo shows in the control UI; with no webcam the app runs normally.
- [ ] AC22 — Camera photos are not written to disk unless the save setting is on, and "delete all camera photos" removes them.

- [ ] AC23 — An uploaded WebM, MP4, and GIF each convert and play as a looping clip inside `gallery` with transitions, audio reaction, and looks applied; loop, ping-pong, and beat-jump all work; a clip or picture can be chosen as the source for `kaleido`.
- [ ] AC24 — On a multichannel audio device, the chosen two channels drive the visuals.

## Open questions
Answered 2026-11-14: hardware is a Pi 2 or 3; audio is two line inputs through a class-compliant USB interface; the renderer is native (ADR 0002); the Pi joins the venue Wi-Fi router already used for the audio desk, so no hotspot is needed.

None. Licence is MIT (human, 2026-11-14).
