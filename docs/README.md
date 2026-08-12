# Documentation map

Where everything lives, what state the project is actually in, and what's next.
Start here when you've been away from the repo for a while.

## Where everything sits

| Document | What it's for |
|---|---|
| [`README.md`](../README.md) | The front door — architecture, quick start, configuration reference, engineering notes. What a visitor reads. |
| [`docs/index.html`](./index.html) | Public landing page, served by GitHub Pages from this folder. Static, no build step. |
| [`docs/build-your-own.md`](./build-your-own.md) | How to stand this up somewhere other than Tucson: frequencies, locale, gauges, gazetteer, adapting the hazard. |
| [`docs/demo-script.md`](./demo-script.md) | Hero-video script, shot list, and the asset checklist. Also carries the anonymization rule for anything published. |
| [`deploy/op25_setup.md`](../deploy/op25_setup.md) | Building and configuring op25 for P25 trunked decode. The fiddliest part of the build. |
| [`web/README.md`](../web/README.md) | React dashboard development — dev server, proxy, build, rsync to the Pi. |
| [`proposals/README.md`](../proposals/README.md) | How `source-scout` proposals work. Nothing in there is auto-applied. |
| [`.claude/plan.md`](../.claude/plan.md) | The original long-form spec (636 lines). Historical — it describes the plan, not the current system. Where the two disagree, the code wins. |
| [`.env.example`](../.env.example) | Every runtime knob, with defaults and comments. |

### Configuration, by what you're changing

| To change… | Edit |
|---|---|
| Anything about where this runs | `config/locale.py` — plus `NWS_POINT` / `APRS_IS_FILTER` in `.env` |
| Which channels get scanned | `config/frequencies.py` |
| Which gauges feed the digest | `config/gauges.py` |
| Transcript repair quality | `config/gazetteer.py` |
| Tuning, models, intervals, cost | `.env` |

## Where the project actually is

All six phases are done. The pipeline captures analog FM and P25 trunked voice,
transcribes locally, classifies and extracts through the agent graph, correlates
against APRS, USGS gauges, and NWS alerts, and serves a React dashboard from
FastAPI on `:8000`. 242 tests pass.

Two things are true that the code won't tell you:

- **The Pi services are stopped and disabled** (since 2026-06-02) to control API spend. Nothing is running until you re-enable it.
- **Tailscale on the Pi is still pending**, so remote access is LAN-only.

## Next steps

### Now — landing page

The page and both guides are written and committed on
`docs/landing-page-and-portability`. What remains is not writing, it's capture
and configuration:

1. Push the branch and open the PR.
2. Enable Pages: Settings → Pages → deploy from `main`, folder `/docs`. Then set the repo's `homepageUrl`, currently empty.
3. Shoot the assets in [`demo-script.md`](./demo-script.md). Every slot on the page is a labelled placeholder box keyed to that checklist.

**This is time-boxed.** The showcase asset — MonsoonPage during real correlated
flood activity — can only be filmed during monsoon season, which ends September
30. Everything else can be shot any time. If it slips, the fallback is replaying
archived rows into a scratch database and saying so on the page.

Do the capture in one or two batched sessions on a forecast storm day rather
than leaving the pipeline soaking; the worker and the Sonnet digest are the cost
drivers.

### Next — a fun weekend

**Meshtastic alert egress.** One ~$30 Heltec node on the Pi's USB plus the
`meshtastic` Python library, broadcasting high-severity alerts onto the local
mesh. Flash floods are exactly when cell service is least reliable and Ntfy only
reaches connected phones, so this closes a real gap rather than adding a feature.
Small module, good landing-page bullet.

### When someone asks

**A wildfire example config.** The portability pass is done and the mapping is
sketched in [`build-your-own.md`](./build-your-own.md#step-5--adapt-the-hazard),
but nothing is built. Worth doing when a real fork wants it — their friction
tells you what genuinely needs generalizing, which is information you can't get
by guessing.

### Deliberately not doing

- **Platform-ification** — multi-tenant infrastructure, a plugin system, a hazard registry. Generalize by documentation until a real fork proves otherwise.
- **LoRa sensor ingestion** — building and fielding your own rain-gauge mesh duplicates data APRS-IS, USGS, and ALERT already provide for free. (Alert *egress* over Meshtastic is a different thing, and is on the list above.)
- **An APRS callsign** — the feed is receive-only by design; `N0CALL` with passcode `-1` is intentional.

## Operational reminders

The ones that have cost time before:

- `ssh` to the Pi hangs unless you pass `-o IPQoS=none`.
- `uv` isn't on the Pi's non-login SSH `PATH` — use `/home/keaton/.local/bin/uv` for ad-hoc commands.
- One dongle, so analog and P25 can't run at once. The SDR supervisor time-shares them; don't start `monsoon-runner` or `monsoon-p25` directly.
- Build the dashboard on the Mac (`cd web && npm run build`) and rsync — the Pi doesn't build it.
- Never give Whisper an `initial_prompt`; it leaks back as fake high-confidence transcripts.
