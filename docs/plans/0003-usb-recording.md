# Plan 0003 — Stereo and multitrack recording to a USB drive

- **Spec:** ../specs/0003-usb-recording.md
- **Base:** main, after 0001 T1, T2, T4, and T5 are merged
- **Verification (whole item):** `.venv/bin/ruff check . && .venv/bin/pytest`

## Approach
A third small service in the same repo, `python -m visualz.recorder`, separate from the visuals and the mixer.

```
visualz/recorder/
  __main__.py   entry point, aiohttp app on its own port
  capture.py    ALSA capture thread reading all channels from the shared device into a ring buffer; dropout detection
  writer.py     writer thread: per-track WAV writers with periodic header refresh, FLAC for stereo, file splitting, silence fill
  takes.py      take folders, track list file, markers
  drives.py     drive discovery, mount, free space, speed check, eject
  api.py        REST + WebSocket: arm, record, stop, mark, meters, status
  sim.py        simulated multichannel source with known test signals
web/recorder/   record page (static, no build)
deploy/         ALSA shared-capture config, service unit, mount rules
```

Capture and disk writing are on separate threads joined by a ring buffer of several seconds, so the capture thread never waits on the drive. Meters are computed on the capture thread and sent to browsers at about 10 Hz.

## Tasks

### T1 — Recorder service
- **Depends on:** 0001 T1 and T2 merged (T2 fixes how the visuals open the audio device)
- **Route:** implement (default)
- **Owns:** `visualz/recorder/**`, `tests/recorder/**`
- **Acceptance:** AC1, AC2, AC4 to AC8, AC11, AC12, and the API side of AC9
- **Verify:** `.venv/bin/ruff check . && .venv/bin/pytest`
- **Notes / gotchas:** read the device at its native format and channel count; do not resample. Write WAV with the standard library or a small pure-Python writer so headers can be refreshed in place; verify 24-bit packing against a reference tool in tests. Drive operations need privileges: use the system's removable-media service rather than running the recorder as root, and keep every such call in `drives.py`. Real-time priority for the capture thread is set by the service unit, not by the code.

### T2 — Shared capture and deployment
- **Depends on:** 0001 T5 merged
- **Route:** implement (default)
- **Owns:** `deploy/alsa/**`, `deploy/visualz-recorder.service`, `deploy/recorder-install.sh`, `docs/guides/recording.md`
- **Acceptance:** AC3 (configuration and a documented manual test), hardware notes for AC10
- **Verify:** `shellcheck deploy/*.sh` plus the whole-item command
- **Notes / gotchas:** the shared-capture layer must be defined for the mixer's full channel count and its actual sample rate, and both the visuals and the recorder must open it by the same name. Changing the main install script from 0001 T5 goes through the lead.

### T3 — Record page and Live-page control
- **Depends on:** T1; 0001 T4 merged
- **Route:** implement (alt)
- **Owns:** `web/recorder/**`, `tests/web/recorder/**`, and the Record widget on the Live page (exact file named in the handoff once 0001 T4 has merged)
- **Acceptance:** page side of AC7 to AC9
- **Verify:** `.venv/bin/ruff check . && .venv/bin/pytest`

## Merge order
T1 and T2 in parallel → T3 → human runs AC10.

## Risks
- **USB bus contention** on a Pi 2/3 (mixer, drive, webcam, Wi-Fi adapter on one USB 2.0 bus) causing dropouts at 18 tracks. Mitigation: buffer, priority, AC10 measured with and without the webcam; fallback is fewer tracks or 16-bit.
- **Shared capture** adds a layer between the device and both programs; a wrong configuration shows up as no audio in the visuals. Mitigation: T2's manual test and a check in the smoke script.
- **Filesystem speed**: an existing Pi recorder project reports overruns at 32 tracks on anything but XFS. Mitigation: the speed check on drive selection, the ext4/XFS recommendation, and AC10 run on the band's actual drive.
- **Drive power**: bus-powered hard disks can brown out a Pi 2/3. Mitigation: setup guide recommends an SSD or stick, or a powered hub.
- **No real hardware in development**: everything is verified against a simulated source. AC10 is the real test and should be done at a rehearsal before any gig is relied on.
