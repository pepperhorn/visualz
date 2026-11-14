# 0002 — XR18 web mixer and personal monitor mixes

- **Status:** draft
- **Ledger:** 0002 · **Plan:** ../plans/0002-xr18-web-mixer.md
- **Author:** lead · **Date:** 2026-11-14

## Problem
The Pi already sits next to the band's Behringer XR18 (it takes its audio from the mixer over USB) and is on the same Wi-Fi router. The band wants to control the mixer from a browser through that same headless Pi, instead of running a separate desktop app, and to let each musician adjust their own monitor mix from their phone.

Options considered and declined by the human on 2026-11-14: streaming Behringer's X AIR Edit desktop app to the browser (too heavy and awkward on a Pi 2/3 and a phone), and running BandPilot on the Pi (untested on this hardware).

## Goals
- A mixer page in the Pi's web UI that controls the XR18 over the network.
- A personal monitor page per musician that can only touch that musician's own bus.
- Stays in sync with any other controller in use (X AIR Edit on a tablet, the mixer's own state).
- Light enough to run beside the visuals on a Pi 2 or 3.
- Mixer control keeps working if the visuals crash or restart.

## Non-goals
- Not a full replacement for X AIR Edit: no FX rack editing (choosing and tweaking effect types), no input/output routing, no USB routing, no automix, no DCA or mute-group setup in v1.
- No snapshot recall or save in v1.
- No recording, no audio streaming to phones.
- Other mixer families (X32 and similar) are not targeted. XR12, XR16, and MR18 may work but are not tested.

## User-visible behaviour

### Connection
- The Pi finds the mixer on the network by itself; a manual IP address field is the fallback. The choice persists.
- A status badge shows connected / searching / lost, with the mixer's name and firmware. On a lost connection, controls are disabled, the last known values stay visible, and it reconnects by itself.
- The mixer is always the source of truth: the page shows what the mixer reports, and a change made on any other controller shows up within half a second.

### Engineer page (`/mixer`)
- Strips for the 16 input channels, the aux input, the 4 FX returns, the 6 buses, and main LR. Each strip shows the name and colour set on the mixer, a fader, a mute button, and a level meter.
- A mix selector switches what the faders control: the main LR mix, or the sends to any one bus ("sends on faders").
- Phone portrait shows a scrollable row of strips with large touch targets; faders need a deliberate drag (a tap on the track does not jump the level).
- Engineer PIN: on by default, set to `0000` on a fresh install. The engineer page asks for it once per device and remembers it. It can be changed or turned off in the mixer settings. While it is still `0000`, the engineer page shows a reminder to change it. Musician pages never need it.

### Channel detail (engineer only)
Tapping a strip's name opens that channel. Required by the human on 2026-11-14: sends, preamp gain, phantom power, EQ, and dynamics.

- **Preamp**: gain, phantom power (48 V), polarity invert, low-cut on/off and frequency. Shown for the 16 mic/line inputs only.
- **Sends**: this channel's level into each of the 6 buses and the 4 FX sends, each with its own fader and mute, and the pre/post tap point. This is the per-channel view of the same sends that "sends on faders" shows per bus.
- **EQ**: on/off, and for each band its type, frequency, gain, and width, with a drawn curve that can be dragged on a touch screen and number fields for exact values. 4 bands on input channels, 6 on buses and main LR.
- **Gate**: on/off, mode, threshold, range, attack, hold, release, with a gain-reduction meter.
- **Compressor**: on/off, threshold, ratio, knee, attack, hold, release, make-up gain, mix, with a gain-reduction meter.
- Pan, and the channel's name and colour, can be edited here too.
- Buses and main LR open the same view with the sections that apply to them (EQ, compressor, no preamp or gate).
- Copy and paste of a channel's EQ or dynamics settings to another channel.
- A "reset section" button on EQ, gate, and compressor, with confirmation.

### Musician page (`/mixer/me/<bus>`)
- A **monitor mix** is either one bus (mono, typically a wedge) or a stereo-linked pair of buses (typically in-ears). Linking is read from the mixer: a linked pair appears as one mix everywhere, with one page, one QR code, and one master.
- The engineer sets each mix up once: the musician's name, the type (**wedge** or **in-ear**), and a maximum master level (a cap). Mixes can be any combination, for example two in-ear pairs and two wedges across the six buses.
- The page shows only the sends into that mix, plus its master level. Nothing on this page can change the main mix or another musician's mix.
- **In-ear mixes** also show a pan control per channel, so the musician can place instruments left and right. Wedge mixes have no pan.
- **In-ear safety**: level rises are ramped rather than instant, the cap applies, and the page shows the mix's output meter so the musician can see how hot it is.
- **Wedge mixes** show a note on the engineer side only: the bus EQ (in channel detail) is where feedback is notched, and musicians cannot reach it.
- A shared wedge can be opened by more than one musician at once; they see each other's changes.
- "More me" shortcut: the musician marks which channels are theirs, and one big control raises those against everything else.
- The engineer page shows a QR code and link for each bus so a musician can open their page by scanning.
- A musician can save their mix as a named profile and reload it at the next gig.

### Safety
- Fader moves sent from a page are rate-limited, and a single gesture cannot raise a level by more than a set step at once, so a slip of a thumb does not produce a jump to full.
- Mutes on the engineer page for main LR ask for confirmation when un-muting.
- **Phantom power** asks for confirmation on every switch, on or off, and names the channel in the question.
- **Preamp gain** moves in small steps per gesture (no jump from a stray tap) and shows the input meter beside it while adjusting.
- Preamp, EQ, and dynamics are engineer-only and sit behind the engineer PIN; musician pages can never reach them.
- If two people move the same control, the last move wins and both pages show the result.

## Constraints
- Runs as its own service on the Pi, separate from the visuals program, on its own port. The visuals control UI links to it and it links back.
- Talks to the mixer with OSC over UDP on the local network, using the MIT-licensed `xair-api` Python library where it fits, and `python-osc` directly where it does not (for example meters or change subscriptions).
- Pure-Python dependencies only; no build step for the web pages; no CDN.
- CPU budget on a Pi 2: under 10% of one core with one engineer page and four musician pages open with meters running.
- Meters update in the browser at about 10 times a second.
- Follows the stack and conventions of ADR 0002 and reuses the 0001 web UI shell and styling.
- Trusted local network; the PIN is a guard against accidents, not security.

## Acceptance criteria
- [ ] AC1 — Against a simulated XR18 (a test OSC server in the repo), the service discovers it, connects, and shows names, colours, fader positions, and mutes for all strips.
- [ ] AC2 — Moving a fader or mute on the page changes the simulated mixer; changing the simulated mixer from elsewhere updates open pages within 0.5 s.
- [ ] AC3 — Sends on faders: selecting a bus makes the faders control that bus's sends.
- [ ] AC4 — Meters animate from simulated meter data at about 10 Hz.
- [ ] AC5 — A musician page can only change its own mix's sends (and pan, for in-ears) and master: requests for anything else are rejected by the server, not just hidden in the page.
- [ ] AC6 — The bus cap is enforced by the server.
- [ ] AC7 — "More me" raises the marked channels against the rest within the bus and stays within the cap.
- [ ] AC8 — QR codes on the engineer page open the right musician page.
- [ ] AC21 — A stereo-linked bus pair on the (simulated) mixer appears as one in-ear mix with per-channel pan; unlinking it on the mixer turns it back into two mono mixes. Level rises on an in-ear mix are ramped. A wedge mix has no pan control.
- [ ] AC9 — Musician profiles save, survive a restart, and reload.
- [ ] AC10 — A fresh install requires PIN `0000` for the engineer page and shows the change-it reminder; the PIN can be changed and turned off; the engineer page and its API are refused without the PIN while musician pages still work; repeated wrong PINs are slowed down.
- [ ] AC11 — Rate limit and step limit are enforced by the server.
- [ ] AC12 — Losing the mixer disables controls and shows the state; it reconnects by itself when the mixer returns.
- [ ] AC13 — Stopping the visuals service leaves the mixer pages working.
- [ ] AC14 — The project verification command passes.
- [ ] AC16 — Channel detail reads and writes, against the simulated mixer: preamp gain, phantom power, polarity, low-cut; every bus and FX send level, mute, and tap point; every EQ band parameter; every gate and compressor parameter listed in the spec. Values shown match the mixer's units (dB, Hz, ms, ratio).
- [ ] AC17 — Phantom power cannot be switched without the confirmation, and a musician-page client is refused preamp, EQ, and dynamics changes by the server.
- [ ] AC18 — The EQ curve drawn on the page matches the band settings and updates when the mixer is changed from elsewhere.
- [ ] AC19 — Copy and paste of EQ and dynamics between channels works; reset restores the mixer's defaults for that section.
- [ ] AC20 — Gate and compressor gain-reduction meters animate from simulated meter data.
- [ ] AC15 — (Human, real hardware) With the real XR18 on the venue router: discovery, faders, mutes, meters, a musician page, and channel detail (gain, phantom, sends, EQ, gate, compressor) all work, and stay in sync with X AIR Edit on another device.

## Open questions
Answered 2026-11-14: monitors are a combination of wedges and in-ear feeds, so both mono and stereo-linked mixes are supported. The engineer PIN is on by default, initially `0000`.

None.
