# Build one where you live

Monsoon Ears listens to Tucson, but nothing about the architecture is
Tucson-shaped. The SDR capture, the squelch/VAD gating, Whisper, and the
classify → extract → alert agent graph don't care what they're pointed at. The
national data sources it correlates against — USGS Water Services, NWS
`api.weather.gov`, APRS-IS — work anywhere in the United States and take a
latitude and longitude as their only location input.

What you have to supply is local knowledge: which frequencies your agencies use,
which gauges matter, and what the streets are called. That's the honest scope of
this guide. Budget an afternoon for a first working capture and a weekend to get
the extraction quality good.

## What it costs

| Item | Cost |
|---|---|
| Raspberry Pi 5 (8 GB) | ~$80 |
| RTL-SDR Blog V3 + dipole antenna kit | ~$40 |
| Active cooler, 27 W USB-C PSU, 64 GB A2 microSD | ~$35 |
| Printed case | filament |
| **Hardware total** | **~$155** |
| Anthropic API, running 24/7 | ~$10–15 / mo |
| Electricity (~5 W average) | ~$0.40 / mo |

The API line is the one to watch, and it scales with how much radio traffic you
capture. See [Controlling cost](#controlling-cost).

A case that fits the Pi 5 with the active cooler:
[Raspberry Pi 5 Case (Snap Fit)](https://www.printables.com/model/642650-raspberry-pi-5-case-snap-fit)
on Printables. Print settings we used are on the landing page.

## Step 1 — Find your frequencies

This is the step that decides whether the project works at all, and it's the one
nobody can do for you.

Start at [RadioReference](https://www.radioreference.com/) and open the database
for your county. You're looking for two things.

**Analog FM conventional channels.** Fire and EMS dispatch are the useful ones —
they carry structured, address-bearing traffic. Note the frequency in MHz and
whether the entry is marked encrypted.

**A trunked system, if your area has one.** Most metros have moved to P25. You
need the system's control channel frequencies, its System ID and WACN, and the
decimal talkgroup IDs you care about. Anything marked `TE` (Terminated
Encryption) or otherwise encrypted is unusable — leave it out.

Then edit `config/frequencies.py`. The existing entries are the format:

```python
ANALOG_FM: list[Frequency] = [
    Frequency("Rural Metro Fire Dispatch F1/F2", 154.370, "nfm", "Rural Metro Fire / AMR", "primary"),
    ...
]
```

Priority drives the scanner's dwell — `primary` channels get probed every cycle,
`low` only when `SCAN_MIN_PRIORITY` allows. Include your local NOAA Weather
Radio transmitter; the scanner visits it periodically for forecast context.

For the trunked side, `PCWIN_TALKGROUPS` in the same file feeds op25. See
[`deploy/op25_setup.md`](../deploy/op25_setup.md) — that's the fiddliest part of
the whole build, and it's optional. Analog-only is a complete system.

**Verify before you invest in the rest.** Point the dongle at one dispatch
frequency and confirm you hear traffic:

```bash
uv run python -m ingestion.runner_analog
```

If nothing comes through, the problem is antenna placement or the frequency
itself, and no amount of downstream configuration will help. Antenna height and
a clear line to the transmitter matter more than anything you'll do in software.

## Step 2 — Set your location

Edit `config/locale.py`. Six values, all in one file:

| Value | What it does |
|---|---|
| `PLACE_NAME` | Interpolated into agent prompts, so the model knows where it is |
| `REGION_NAME` | Longer form — city plus surrounding jurisdiction |
| `GEOCODE_QUERY_SUFFIX` | Appended to bare street names before geocoding |
| `UTC_OFFSET_HOURS` | Local-time rendering (see the note on DST in the file) |
| `REGION_CENTER` | Approximate center of your coverage area |
| `REGION_LAT` / `REGION_LON` | Bounding box that rejects implausible geocodes |
| `SEASON_START` / `SEASON_END` | Your hazard season as (month, day) |

The bounding box does real work. A bare street name like "Speedway and Kolb"
will happily geocode to another continent — we saw a −41° latitude in testing —
and the box is what throws those out. Make it generous enough to cover the
outlying communities your radio traffic mentions, tight enough that a global
mismatch fails.

Then set the two location values that live in `.env` because their clients read
env directly, and keep them consistent with `REGION_CENTER`:

```bash
NWS_POINT=32.2,-110.97          # lat,lon — your NWS forecast point
APRS_IS_FILTER=r/32.2/-110.9/50 # lat/lon/radius-km for the APRS-IS feed
```

`config/locale.py` ships with a test (`tests/test_locale.py`) that catches the
common inconsistency where the bounding box and center drift apart.

## Step 3 — Pick your gauges

`config/gauges.py` lists the stream and rain gauges the correlation digest reads.

Find yours through the [USGS Water Services](https://waterservices.usgs.gov/)
site inventory — query by county or bounding box for sites with an
instantaneous-values service. You want discharge (parameter `00060`) or gage
height (`00065`). The API is documented, free, and needs no key.

For each site, record its ID, name, coordinates, and which watercourse it sits
on. One field deserves attention:

```python
GaugeSite("09486500", "Santa Cruz River at Cortaro", "usgs", "Santa Cruz",
          32.351, -111.096, baseflow=True)
```

`baseflow=True` marks reaches that carry water year-round — below a wastewater
plant, or a genuinely perennial stream. Without the flag, steady normal flow
reads as a flood every single run and the digest cries wolf continuously. Check
each site's historical record before deciding.

Many counties also run their own ALERT flood-warning network with a public feed.
Tucson's is wired up in `ingestion/pima_alert_client.py` as a best-effort source
with no documented API — treat it as a model for adding yours, not as something
that will work unmodified.

## Step 4 — Write your gazetteer

`config/gazetteer.py` is the file that makes transcripts usable. It's a plain
list of local proper nouns — arterials, highways, neighborhoods, hospitals,
watercourses, agency names — injected into the extract prompt so the model can
repair what Whisper mangled.

This matters more than it sounds. Whisper does not know your streets, and radio
audio is bad. "Tanque Verde" comes back as "tank a verde"; "Speedway" as "speed
wait". With the gazetteer in the prompt, the model repairs those against a known
list instead of guessing. Without it, roughly half your locations fail to
geocode.

Aim for a hundred or so names across the categories, weighted toward what
dispatchers actually say. An hour with a local map gets you most of the value.
Add names as you notice them failing — this file is never finished.

The gazetteer rides in a cached system block, so its size costs almost nothing
per event during active traffic.

## Step 5 — Adapt the hazard

Everything above gets you captured, transcribed, classified, geocoded radio
traffic — which is most of the system and is hazard-agnostic. The flood-specific
part is the correlation digest in `agents/alert.py`: the prompt that weighs NWS
warnings against stream discharge against APRS rainfall.

If flooding is your hazard, you're done. If it isn't, that prompt and the gauge
sources are what you rewrite. Wildfire is the obvious neighbor and maps onto the
same shape:

| Flood | Wildfire |
|---|---|
| NWS Flash Flood Warning | NWS Red Flag Warning |
| USGS stream discharge | RAWS fuel moisture, wind, humidity |
| APRS station rainfall | APRS station wind and temperature |
| Named washes in the gazetteer | Named canyons, ridges, drainages |
| Fire/EMS/flood-control talkgroups | Fire and wildland talkgroups |

The structure carries over: a cheap official signal that anchors the verdict, a
physical sensor signal, a citizen-sensor signal, and voice traffic to correlate
against. Rewrite `_MONSOON_SYSTEM` with that rubric and repoint
`config/gauges.py` at your sensor network.

We haven't built the wildfire variant. If you do, open a PR with your config as
an example — that's the fastest way to find out which parts genuinely need
generalizing and which are fine as they are.

## Step 6 — Run it

Standard setup from the [README](../README.md#quick-start):

```bash
git clone https://github.com/keatonwilson/monsoon_ears.git
cd monsoon_ears
uv venv
uv pip install -e ".[pi,dev]"
cp .env.example .env     # then edit
```

Set `ANTHROPIC_API_KEY` and, if you want push alerts, `NTFY_TOPIC`. Run one
capture leg by hand first and watch rows land in the database before installing
services. Once it works:

```bash
sudo deploy/install_services.sh
```

Dashboard at `http://<pi-hostname>:8000`.

## Controlling cost

The API bill scales with captured traffic, and a busy metro captures a lot. Four
knobs, roughly in order of effect:

- `SCAN_MIN_PRIORITY` — stop scanning low-priority channels entirely.
- `DIGEST_INTERVAL_MIN` — the Sonnet digest is the expensive per-run call. Every 15 minutes is aggressive; 30 or 60 is fine outside your hazard season.
- `NOISE_FLOOR_RMS` — tune it up and fewer noise-only chunks reach Whisper. Costs nothing but a little tuning; this is the cheapest win.
- `CLASSIFY_MODEL` / `EXTRACT_MODEL` — already Haiku. Little left to save here.

Outside your hazard season, disabling the digest entirely is reasonable. It has
nothing to correlate.

## Legal and ethical notes

Receive-only monitoring of unencrypted public-safety frequencies does not
require a license in the US and is legal in most jurisdictions — but check
yours, since a few states restrict mobile scanner use, and rules elsewhere in
the world differ substantially. Never attempt to decode encrypted traffic.

Publishing is a separate question from listening. This pipeline captures real
emergencies involving real people, often with addresses attached. If you put any
of it on the public internet — a dashboard, a demo, a screenshot — mask house
numbers, drop names and any medical detail, and prefer flood, fire, or
road-closure traffic over medical calls. The dashboard as shipped binds to your
LAN, and that's a sensible default to keep.

Set a real `NOMINATIM_USER_AGENT` with working contact information. The public
geocoding services are free because people don't abuse them.
