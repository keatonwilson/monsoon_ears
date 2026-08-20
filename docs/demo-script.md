# Landing page demo — script and asset list

Working reference for the hero video and the inline loops on the landing page
(`docs/index.html`). Nothing here is built yet; the page ships with placeholders
that match the asset IDs below.

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

- [ ] `photo-case-hero` — Pi in the printed case, good light, plain background. This is the image people remember; it's worth doing properly. Also crop this to 1200×630 for `assets/og-card.jpg` (the social-share card).
- [ ] `video-case-turntable` — slow rotation, 8–10 s, loopable.
- [ ] `photo-case-ports` — port and antenna access, for the build-your-own page.
- [ ] `video-wash-dry` / `video-wash-running` — same wash, same framing, two conditions.

### Screen recordings (pipeline live)

- [ ] `screen-monsoon-digest` — **storm day only.** MonsoonPage during real correlated activity.
- [ ] `screen-phone-ntfy` — phone screen recording, push arriving.
- [ ] `screen-feed-filling` — Feed page taking rows in real time.
- [ ] `screen-ask-nl-sql` — AskPage, pre-planned query.
- [ ] `screen-map-washes` — MapPage with the wash overlay (fallback for segment 3).

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
