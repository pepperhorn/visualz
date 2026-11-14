# Plan 0002 — XR18 web mixer and personal monitor mixes

- **Spec:** ../specs/0002-xr18-web-mixer.md
- **Base:** main, after 0001 T1 and T4 are merged
- **Verification (whole item):** `.venv/bin/ruff check . && .venv/bin/pytest`

## Approach
A second small Python program in the same repo, `python -m visualz.mixer`, run as its own systemd service. It reuses nothing from the render path, only shared helpers.

```
visualz/mixer/
  __main__.py   entry point, aiohttp app on its own port
  xr18.py       mixer link: discovery, connect, keep-alive, get/set, change subscription, meters
  model.py      in-memory mirror of the mixer state; permissions (engineer vs bus), caps, rate and step limits
  api.py        REST + WebSocket for the pages; PIN; profiles persisted in data/mixer/
  sim.py        simulated XR18 OSC server for tests and for trying the UI with no mixer
web/mixer/      engineer page and musician page (static, no build)
```

The mixer link keeps the connection alive with the mixer's periodic "remote" subscription so changes made elsewhere are pushed to us, and renews the meter subscription. All writes go through `model.py`, which is where permissions and limits are enforced, so the pages cannot bypass them.

## Tasks

### T1 — Mixer service: link, model, API, simulator
- **Depends on:** 0001 T1 merged
- **Route:** implement (default)
- **Owns:** `visualz/mixer/**`, `tests/mixer/**`, `deploy/visualz-mixer.service`
- **Acceptance:** AC1, AC2, AC4 to AC7, AC9 to AC14, AC16, AC17, AC19, AC20 at the API level, all against `sim.py`
- **Verify:** `.venv/bin/ruff check . && .venv/bin/pytest`
- **Notes / gotchas:** read the `xair-api` source before relying on it: confirm whether it exposes change subscription and meters, and whether its blocking getters (20 ms delay each) are acceptable for the initial state load, or whether a bulk read with `python-osc` is needed. X-Air OSC is on UDP port 10024; the remote subscription expires after about 10 seconds and must be renewed. Fader values on the wire are 0.0 to 1.0, not dB, and most EQ and dynamics parameters are likewise normalised with their own scaling curves (linear, log, or stepped): put every conversion in one tested module (`units.py`) so pages always show real units. Phantom power and gain live under the headamp addresses, not the channel addresses. The simulator must hold the full parameter set for a channel so round-trips can be tested. Record in the return handoff exactly which OSC addresses were used and which were verified only against the simulator. Adding the dependency to `pyproject.toml` needs the lead's OK in the handoff, since T1 does not own that file.

### T3 — Channel detail pages
- **Depends on:** T1, T2
- **Route:** implement (alt)
- **Owns:** `web/mixer/channel/**`, `tests/web/mixer/channel/**`
- **Acceptance:** AC18, and the page side of AC16, AC17, AC19, AC20
- **Verify:** `.venv/bin/ruff check . && .venv/bin/pytest`
- **Notes / gotchas:** the EQ curve is computed in the browser from the band settings (standard biquad responses) and drawn on a canvas; dragging a band handle sets frequency and gain, pinch or a slider sets width. Every control also has a number field. Phantom confirmation is enforced by the server with a two-step request, not only by a dialog. T2 leaves a link from each strip name to `channel/`; anything else T3 needs in T2's files goes through the lead.

### T2 — Mixer pages
- **Depends on:** T1; 0001 T4 merged (UI shell and styles)
- **Route:** implement (alt)
- **Owns:** `web/mixer/**`, `tests/web/mixer/**`
- **Acceptance:** AC3, AC8, and the page side of AC1, AC2, AC4, AC5, AC7, AC9, AC10, AC12
- **Verify:** `.venv/bin/ruff check . && .venv/bin/pytest`
- **Notes / gotchas:** faders must be usable with a thumb on a phone and must not jump on tap. QR codes are generated locally (vendored small library, licence recorded), not from a web service. Develop against `python -m visualz.mixer --sim`.

## Merge order
T1 → T2 → T3 → human runs AC15 on the real mixer.

## Risks
- **Parameter scaling**: wrong conversion between the mixer's normalised values and real units would show or set wrong EQ, dynamics, or gain values. Mitigation: one conversion module with tests, and a human spot-check against X AIR Edit as part of AC15.
- **No real mixer in development**: everything is verified against a simulator written from documentation, so real-hardware differences are likely. Mitigation: AC15 is a human check, and T1 lists every unverified OSC address.
- **Live-sound risk**: a bug here can change levels on stage. Mitigation: server-side caps, rate and step limits, confirmation on phantom power, small steps on gain, engineer-only access to preamp, EQ and dynamics, and the first real-hardware test should be done away from a gig with speakers turned down.
- **Wi-Fi reliability** at venues affects UDP control. Mitigation: visible connection state and automatic reconnect; the mixer keeps its own state if the Pi drops out.
