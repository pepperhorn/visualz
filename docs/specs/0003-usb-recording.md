# 0003 — Stereo and multitrack recording to a USB drive

- **Status:** draft
- **Ledger:** 0003 · **Plan:** ../plans/0003-usb-recording.md
- **Author:** lead · **Date:** 2026-11-14

## Problem
The Pi is already connected to the XR18 by USB and receives all of the mixer's channels. The band wants to record gigs and rehearsals from it onto a USB drive, either as a simple stereo recording or as separate tracks for mixing later, started and stopped from the same web UI, with no laptop.

## Goals
- Record a stereo pair, or any set of the mixer's USB channels as separate tracks, to a USB drive plugged into the Pi.
- Start, stop, and monitor recording from the web UI.
- Recording never disturbs the visuals, and the visuals never disturb the recording.
- A power cut or crash loses at most the last few seconds, not the take.

## Non-goals
- No playback through the mixer, no virtual soundcheck, no overdubbing.
- No editing, mixing, bouncing, or MP3 export on the Pi.
- No recording to the SD card (too slow and wears it out), except a short emergency buffer.
- No upload to cloud storage in v1.
- No effect on the mixer's own routing: which signals appear on which USB channel is set on the mixer.

## User-visible behaviour

### Modes
- **Stereo**: two chosen USB channels (for example the main mix) into one stereo file. Format WAV 24-bit, or FLAC to save space.
- **Multitrack**: any chosen set of USB channels, each written as its own mono WAV file, 24-bit, at the mixer's sample rate (48 kHz, or 44.1 kHz if the mixer is set to it). Up to every channel the device offers: 18 on the XR18. The recorder takes the channel count from the device, so a larger interface (for example an X32's 32-channel USB card) needs no code change, only enough hardware: see Constraints.
- Both at once is allowed: a stereo file plus the separate tracks, in the same take folder.

### Tracks
- The record page lists the mixer's USB channels with a live meter each, an arm switch, and a name.
- When the mixer link from item 0002 is available, track names default to the channel names on the mixer; they can always be typed by hand.
- Arm-all, arm-none, and saved arm sets (for example "full band", "stereo only").

### Takes
- One big Record button, on the record page and on the Live page. Stop asks for confirmation.
- Each take is a folder on the drive named with date, time, and an optional take name, containing the audio files, a text file listing tracks, sample rate, and start time, and a markers file.
- **Markers**: a Mark button drops a named marker at the current time. If "now playing" changes in the visuals UI during a take, a marker with the song title is added automatically, so the take can be split by song later.
- While recording: elapsed time, size written, time remaining on the drive at the current track count, per-track meters with clip indicators, and a dropout counter.
- Recording can be set to start automatically when the service starts and a drive is present ("always record"), off by default.

### Drive
- The page shows drives plugged in, their free space, and their format. exFAT, ext4, and FAT32 are accepted; long multitrack files are split under the hood where a format limits file size, and the split is seamless (sample-accurate, documented in the take's text file).
- Recording refuses to start, with a clear reason, if no drive is present or the drive is too slow or too full for the armed track count (a short speed check runs when a drive is first selected).
- **Eject** button flushes and unmounts the drive so it can be pulled safely. Pulling the drive during a take stops the take cleanly at the last flushed point and shows an error.
- A low-space warning at 10 minutes remaining; recording stops cleanly before the drive is full.

### Reliability
- If a dropout (lost audio) happens, recording continues, the gap is filled with silence so tracks stay in sync, and the time is logged in the take's text file and counted on the page.
- File headers are kept valid during the take, so a power cut leaves files that open normally up to the last few seconds.
- The recorder runs as its own service and keeps recording if the visuals or mixer pages crash or restart.

## Constraints
- The XR18's USB capture is shared between the visuals and the recorder through ALSA's capture-sharing layer (`dsnoop`), configured by the install script, so both can read the device at once. The visuals read their two channels from the shared device, never the raw one.
- Recorder priority is above the visuals: under load, the visuals drop frames before the recorder drops audio.
- Pi 2/3 have a single USB 2.0 bus shared by the mixer, the drive, a webcam, and (Pi 2) a Wi-Fi adapter. Eighteen tracks at 24-bit is about 2.6 MB per second, roughly 9.3 GB per hour. This is within the bus's capacity but leaves less margin with a webcam attached; AC10 measures it.
- Thirty-two tracks (an X32) is about 4.6 MB per second, roughly 16.6 GB per hour, and close to the limit of a Pi 2/3's single USB 2.0 bus once the drive is on the same bus. It is expected to need the NUC-class machine; on a Pi 2/3 the page warns when the armed track count exceeds what the drive speed check supports.
- Disk writes go through a memory buffer of several seconds so a slow moment on the drive does not cause a dropout.
- Follows ADR 0002 conventions: Python, apt-installable dependencies, static web pages, the same UI shell as 0001.
- Trusted local network. Record and stop are available to anyone who can open the UI; eject and "always record" sit behind the engineer PIN from 0002 when that service is installed.

## Acceptance criteria
- [ ] AC1 — With a simulated 18-channel capture source, a multitrack take of chosen channels produces one mono 24-bit WAV per armed track, sample-aligned, with correct length and content (verified against the known test signal).
- [ ] AC2 — Stereo mode produces a valid stereo WAV and a valid FLAC from the chosen pair; stereo and multitrack can run in the same take.
- [ ] AC3 — The visuals' audio input and the recorder read the same capture device at the same time (test with the shared-capture configuration, or its simulated equivalent).
- [ ] AC4 — Killing the recorder process mid-take leaves files that open in a standard audio tool and contain everything up to the last few seconds.
- [ ] AC5 — Injected dropouts are filled with silence, logged with their times, and counted; tracks remain aligned afterwards.
- [ ] AC6 — Takes longer than a format's file-size limit are split and rejoin sample-accurately.
- [ ] AC7 — Markers: manual marks and automatic now-playing marks appear in the markers file with correct times.
- [ ] AC8 — Drive handling: listing, free space and time-remaining estimate, refusal with a reason when absent, too slow, or too full; clean stop on low space; eject unmounts; removing the drive mid-take stops cleanly.
- [ ] AC9 — Record, stop (with confirmation), arm sets, meters, elapsed time, and dropout count work from the record page; the Record button and status also show on the Live page; two clients stay in sync.
- [ ] AC10 — (Human, real hardware) On the Pi 2 or 3 with the XR18: a 60-minute, 18-track take to the band's USB drive with the visuals running completes with zero dropouts; repeated with the webcam attached. Results recorded in the ledger.
- [ ] AC11 — Stopping or crashing the visuals service does not interrupt a take.
- [ ] AC12 — The project verification command passes.

## Open questions
1. **File layout for multitrack**: I assumed one mono WAV per track, which every DAW imports directly. The alternative is a single multichannel file per take. Say if you prefer that.
2. **Which drive?** A USB SSD or a good USB stick is fine; a spinning hard disk powered from the Pi 2/3 may brown out the board and would need a powered hub. Confirm what you plan to use so the setup guide covers it.
