# Landing page demo — script and asset list

Working reference for the hero video and the inline loops on the landing page
(`docs/index.html`).

**The page no longer carries placeholder boxes.** As of 2026-09-30 it ships with
what actually exists — two screen recordings and four photographs — and the
sections that had nothing were rewritten to stand on their own text rather than
advertise a gap. Adding a remaining asset means writing its slot back in, not
filling an empty one.

## The scheduling constraint

The showcase capability is the flood-correlation digest, and off-season it
correctly returns "no active situation" — the system working perfectly and a
completely dead demo. **Segment 5 has to be filmed during monsoon season
(Jun 15 – Sep 30), ideally on a forecast storm day.** Everything else can be
shot any time.

Capture in one or two batched sessions rather than leaving the pipeline
soaking — the worker plus the Sonnet digest are the cost drivers.

If this slips past September: replay archived DB rows into a scratch database
and film against that, and say so on the page. A replayed demo that's honest
beats a live demo that shows nothing.

## Anonymization rule

Use **flood, road-closure, or water-rescue** traffic. Not medical.

Receiving unencrypted public-safety radio is legal, and the transcripts are
already in the repo's own database, but republishing a specific medical
incident tied to a specific street address on a public web page is a different
question from monitoring it. The rule for anything that ships publicly:

- Prefer flood-control, road-closure, wash-related, or traffic traffic.
- Mask house numbers — "the 200 block of W Irvington" rather than "205 W Irvington".
- Bleep or drop any name, DOB, or patient detail.
- No medical nature-of-call in the audio, the transcript, or a screenshot.

This applies to the screen recordings too. The Feed and Threads pages show
whatever was captured, so either film during a flood-traffic window or scrub the
scratch DB before recording.

## Hero video — ~100 seconds, narrated

### 1. Cold open (0:00–0:10)

Real captured radio over black. Staticky, hard to parse. No narration. The
transcript then types itself onto screen beneath a waveform.

The whole project in one beat: noise becomes text. Resist the urge to explain
anything here.

> Assets: `audio-dispatch`, `gfx-waveform`

### 2. The hardware (0:10–0:20)

Slow pan or turntable on the Pi 5 in the printed case, antenna and dongle
visible. Caption over: *"A Raspberry Pi 5, a $40 SDR, an antenna. About $130."*

> Assets: `video-case-turntable`, `photo-case-hero`

### 3. The problem (0:20–0:35)

A wash dry, then the same wash running. Narration: how fast the washes come up,
how little warning there is, why this is the hazard that matters here.

> Assets: `video-wash-dry`, `video-wash-running` (fallback: `screen-map-washes`)

### 4. The pipeline (0:35–0:55)

The architecture diagram, animated so each stage highlights as it's named —
capture, squelch, VAD, Whisper, classify, extract. Cut to the real Feed page
filling with rows in real time.

> Assets: `gfx-architecture-animated`, `screen-feed-filling`

### 5. The money shot (0:55–1:15)

MonsoonPage during genuine correlated activity: radio traffic, gauge discharge
climbing, an active NWS warning, and the digest verdict with its citations. Cut
to the phone as the Ntfy push lands.

This is the segment worth waiting for a storm to film. It is the only one that
can't be faked or reshot later.

> Assets: `screen-monsoon-digest`, `screen-phone-ntfy`

### 6. Ask (1:15–1:30)

Type a plain-English question into the Ask page, watch it become SQL and return
rows. Lands hardest with non-technical viewers and it's the cheapest thing on
the list to shoot.

Plan the query in advance — something that returns an interesting, non-empty,
non-medical result. Candidates: *"which washes came up most this week?"*,
*"how many road closures in the last month?"*

> Assets: `screen-ask-nl-sql`

### 7. Close (1:30–1:40)

"Build one where you live." Repo link, build-your-own docs link, case link.

> Assets: `gfx-endcard`

## Inline loops

Three short silent loops embedded further down the page, so it stays alive for
people who don't press play. Cut these from hero footage rather than shooting
separately.

| ID | Source | Section it sits in |
|---|---|---|
| `loop-feed` | segment 4 | How it works |
| `loop-digest` | segment 5 | The monsoon feature |
| `loop-ask` | segment 6 | Ask your data |

## Asset checklist

### Shot on location

- [x] `photo-case-hero` — shot 2026-09-30. Published as `docs/assets/case-hero.jpg`.
- [x] `photo-setup-hero` — the whole rig on the windowsill with the antenna and monsoon sky. Not in the original list; it became the hero image (`docs/assets/hero-setup.jpg`) and the source for `assets/og-card.jpg`.
- [x] `photo-case-ports` — `docs/assets/case-ports.jpg`, on the build-your-own page.
- [x] `photo-case-internals` — lid off, cooler visible. `docs/assets/case-internals.jpg`, on the build-your-own page.
- [ ] `video-case-turntable` — slow rotation, 8–10 s, loopable. **Superseded for now:** the hero is a still photograph, which suits a portrait composition better than a 21:9 video band. Only worth shooting if the hero changes shape.
- [ ] `video-wash-dry` / `video-wash-running` — same wash, same framing, two conditions. **Out of season as of 2026-09-30** — the running plate needs next year's monsoon (Jun 15 – Sep 30).

### Screen recordings (pipeline live)

- [x] `screen-monsoon-digest` — shot 2026-09-29 11:23 MST during a Flash Flood Warning. Published as `docs/assets/digest.mp4` (12.5 s, silent loop).
- [ ] `screen-phone-ntfy` — phone screen recording, push arriving.
- [x] `screen-feed-filling` / `screen-map-washes` — both covered by the single dashboard tour shot 2026-09-29 10:08 MST. Published as `docs/assets/tour.mp4` (52.5 s, silent, three regions blurred).
- [ ] `screen-ask-nl-sql` — AskPage, pre-planned query. **Not shot:** the take errored out (API credit balance), and the error text exposed billing state. Reshoot against a scrubbed DB.

### Blurs applied to `tour.mp4`

Masking these was cheaper than reshooting, but they are the reason the raw
`.mov` files stay out of git (`_footage/` is ignored):

| Time | What | Why |
|---|---|---|
| 4–13.5 s | Three bullets in the hourly rollup | Overdose, unconscious-person and medical-alarm calls, each with a full street address |
| 20.3–26.2 s | One raw-feed card band | A transmission naming a fall (injury detail); band is oversized to survive scroll drift |
| 29.8–34 s | Map popup | EMS transport with destination hospital |

The recording was also cut at 52.5 s, which drops both the Ask error and a
Monsoon-tab scroll where an EMS event with two house numbers comes into view.

Record at 2x the final display size; the dashboard is dense and re-encoding is
unforgiving.

### Audio

- [ ] `audio-dispatch` — one clean flood/road-closure capture pulled from the DB, house number masked.

### Graphics

- [ ] `gfx-waveform` — waveform animation for the cold open.
- [ ] `gfx-architecture-animated` — animated version of the README mermaid diagram.
- [ ] `gfx-endcard` — links card.
- [ ] `gfx-bom-card` — the $130 bill of materials, also used on the build-your-own page.

### Written

- [x] `docs/build-your-own.md` — hardware BOM, frequency research, gauges, gazetteer.
- [ ] Wildfire example config, once someone actually wants one.
