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
- Not a replacement for X AIR Edit: no EQ, gate, compressor, FX editing, routing, or preamp settings in v1.
- No preamp gain or phantom power control (too easy to cause damage or feedback from a phone).
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
- Optional PIN: when set, the engineer page asks for it once per device. Musician pages never need it.

### Musician page (`/mixer/me/<bus>`)
- Shows only the sends into that musician's bus, plus the bus master level. Nothing on this page can change the main mix or another bus.
- Each bus can be given a musician name and a maximum master level (a cap) from the engineer page.
- "More me" shortcut: the musician marks which channels are theirs, and one big control raises those against everything else.
- The engineer page shows a QR code and link for each bus so a musician can open their page by scanning.
- A musician can save their mix as a named profile and reload it at the next gig.

### Safety
- Fader moves sent from a page are rate-limited, and a single gesture cannot raise a level by more than a set step at once, so a slip of a thumb does not produce a jump to full.
- Mutes on the engineer page for main LR ask for confirmation when un-muting.
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
- [ ] AC5 — A musician page can only change its own bus's sends and master: requests for anything else are rejected by the server, not just hidden in the page.
- [ ] AC6 — The bus cap is enforced by the server.
- [ ] AC7 — "More me" raises the marked channels against the rest within the bus and stays within the cap.
- [ ] AC8 — QR codes on the engineer page open the right musician page.
- [ ] AC9 — Musician profiles save, survive a restart, and reload.
- [ ] AC10 — With a PIN set, the engineer page is refused without it and musician pages still work.
- [ ] AC11 — Rate limit and step limit are enforced by the server.
- [ ] AC12 — Losing the mixer disables controls and shows the state; it reconnects by itself when the mixer returns.
- [ ] AC13 — Stopping the visuals service leaves the mixer pages working.
- [ ] AC14 — The project verification command passes.
- [ ] AC15 — (Human, real hardware) With the real XR18 on the venue router: discovery, faders, mutes, meters, and a musician page all work, and stay in sync with X AIR Edit on another device.

## Open questions
1. **How do you run monitors?** I assumed each musician has one of the six buses (mono). If you use stereo-linked buses for in-ears, say so and the musician page will treat a linked pair as one mix.
2. **Is an engineer PIN wanted by default**, or off unless you turn it on? Assumed off.
