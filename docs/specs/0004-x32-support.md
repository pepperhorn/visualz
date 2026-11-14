# 0004 — X32 Rack support (mixer control and 32-track recording)

- **Status:** draft
- **Ledger:** 0004 · **Plan:** to be written after 0002 is built
- **Author:** lead · **Date:** 2026-11-14

## Problem
Besides the XR18, the band uses a Behringer X32 Rack with an X-USB card and an S16 stage box. The web mixer (0002) and the recorder (0003) are built around the XR18. The same box should work when it is plugged into the X32 instead, without a different setup or a different UI to learn.

## Goals
- The mixer pages from 0002 work with the X32 Rack, with the same features: strips, sends on faders, channel detail (preamp gain, phantom power, sends, EQ, gate, compressor), and musician monitor pages for wedges and in-ears.
- Preamps on the S16 are controlled from the same channel detail view as the local ones.
- The box recognises which mixer it is connected to and switches by itself.
- The recorder from 0003 records up to all 32 channels of the X-USB card.
- The visuals take their stereo feed from two chosen X-USB channels, as with the XR18.

## Non-goals
- Everything that is a non-goal in 0002 and 0003 stays one here (FX rack editing, routing, snapshots and scenes, automix, DCA and mute-group setup, playback).
- No matrix mixes, no mono/centre bus, no P16 personal monitoring setup, no user-assignable controls.
- No setup of the AES50 link or of which S16 inputs feed which channels: that is done on the mixer. The pages show the result.
- Other X32 family models and the M32 are not tested. They may work through the same profile.

## User-visible behaviour

### What changes on the pages
- 32 input channels, 8 aux inputs, 8 FX returns, 16 mix buses, and main LR. Strip banks are 8 wide on a phone, with a bank selector.
- Up to 16 monitor mixes. Buses can be linked in odd-even pairs for in-ears, as on the XR18.
- Channel detail matches the X32: 4-band EQ on inputs and 6-band on buses, gate, compressor, and sends to all 16 buses.
- The status badge names the mixer model, so it is always clear which desk is being controlled.

### Preamps and the S16
- Each channel's preamp section controls whichever physical preamp is routed to that channel: a local input on the rack or an S16 input over AES50. The section says which one ("Local 3", "S16 input 5").
- If two channels share one physical preamp, the page says so, because a gain change affects both.
- A channel fed from a source with no preamp (USB return, aux) shows trim only, with no gain or phantom power.
- Phantom power keeps its confirmation, and it names the physical input as well as the channel.

### Switching mixers
- Discovery finds either mixer. The service loads the matching profile and the pages rebuild for it.
- Musician names, mix types, caps, and saved profiles are kept separately per mixer, so XR18 gig settings and X32 gig settings do not overwrite each other.
- If both mixers are on the network at once, the engineer picks one. The choice is remembered.

### Recording
- The record page lists 32 USB channels. Track names default to what is routed to each USB send where the mixer reports it; otherwise they are typed by hand.
- Thirty-two tracks at 24-bit is about 16.6 GB per hour.

## Constraints
- Implemented as a second mixer profile for the 0002 service, not a fork. If the XR18-only assumption has leaked anywhere outside the profile, fixing that is part of this item.
- X32 control is OSC over UDP on port 10023. The `xair-api` library supports the X32 only partly, so most addresses are implemented directly.
- Reference for the protocol: the unofficial X32 OSC protocol document by Patrick-Gilles Maillot. His repository `pmaillot/X32-Behringer` is GPL-3: it may be read and its emulator may be run as an external tool for testing, but no code from it may be copied into this MIT repository. `wisq/x32_remote` (MIT) is a readable command reference. Neither is a dependency.
- The test suite uses our own simulated X32 (an extension of the 0002 simulator). Running against Maillot's emulator is an optional extra check, documented but not required to pass.
- **Hardware for 32 tracks**: a Raspberry Pi 2 or 3 has one USB 2.0 bus shared by the X-USB card and the drive, and is not expected to record 32 tracks reliably. The supported machine for 32-track recording is the Intel NUC (or another machine with USB 3). On a Pi 2/3 the recorder limits the armed track count to what the drive speed check supports and says why.
- Mixer control and the visuals have no such limit and run on a Pi 2/3 with the X32.

## Acceptance criteria
- [ ] AC1 — Against a simulated X32, every 0002 acceptance criterion that applies passes with the X32 profile (strips, sync, sends on faders, meters, musician page limits, caps, profiles, PIN, limits, reconnect, channel detail read/write with correct units, EQ curve, copy/paste, gain-reduction meters, linked mixes).
- [ ] AC2 — The XR18 profile still passes all of 0002's criteria unchanged.
- [ ] AC3 — Preamp control follows routing: for a channel fed from a local input and one fed from an AES50 (S16) input, gain and phantom power go to the right physical preamp and the page names it; a shared preamp is flagged; a source with no preamp shows trim only.
- [ ] AC4 — With the simulated XR18 swapped for the simulated X32 on the network, the service switches profile and the pages rebuild without a restart; per-mixer settings are kept apart.
- [ ] AC5 — The recorder records 32 simulated channels to 32 aligned mono files (0003 AC1 at 32 channels).
- [ ] AC6 — On the low hardware profile, arming more tracks than the drive check supports is refused with a clear reason.
- [ ] AC7 — The project verification command passes.
- [ ] AC8 — (Human, real hardware) With the real X32 Rack and S16: discovery, faders, mutes, meters, a wedge mix and an in-ear mix, and channel detail on one local and one S16 channel all work and agree with X32 Edit. Phantom power and gain are checked on both a local and an S16 input with speakers turned down.
- [ ] AC9 — (Human, real hardware) A 60-minute, 32-track take on the NUC completes with zero dropouts.

## Open questions
1. **Which machine goes with the X32?** If you want 32-track recording at X32 gigs, that needs the NUC. If stereo or a reduced track count is enough there, the Pi can do it. Mixer control works on either.
2. **How many monitor mixes do you run on the X32**, and are the in-ears on linked bus pairs as on the XR18? Assumed yes.
3. **Do you use the S16's outputs for monitors** (wedges fed from the stage box)? It does not change the pages, only the setup guide.
