# 🌧️ Monsoon Ears

### Multi-Agent SDR Radio Intelligence Pipeline

#### Project Spec v2.2 — Claude Code Handoff

-----

## Project Identity

**Name:** Monsoon Ears
**Tagline:** *Listening to Tucson — one transmission at a time.*
**Repo name:** `monsoon-ears`
**Stack:** Python · LangGraph · Whisper · RTL-SDR · op25 · aprs3 · Anthropic API · Streamlit
**Hardware:** Raspberry Pi 5 (8GB) + RTL-SDR Blog V3 dongle

-----

## What It Does

Monsoon Ears is a Python-based multi-agent pipeline running on a Raspberry Pi 5. It:

1. Captures live radio traffic from Tucson-area frequencies via RTL-SDR dongle
1. Decodes analog FM voice (Rural Metro Fire/AMR, NOAA) and P25 digital trunked traffic (Tucson Fire / PCWIN) via op25
1. Transcribes voice audio locally using OpenAI Whisper
1. Decodes APRS packet data directly (no transcription needed)
1. Routes all events through a LangGraph agent graph: classify → extract → alert
1. Persists everything to SQLite
1. Surfaces a live Streamlit dashboard accessible over local network

The showcase feature: during monsoon season, the alert agent correlates Pima County flood control radio dispatches with APRS weather station rainfall data near the same washes — multi-modal sensor fusion in real time.

-----

## Hardware (Already Purchased ✅)

|Component                           |Notes                            |
|------------------------------------|---------------------------------|
|Raspberry Pi 5 (8GB RAM)            |All services run here            |
|RTL-SDR Blog V3 + dipole antenna kit|V4 is EOL — V3 is correct choice |
|27W USB-C power supply              |Official spec, non-negotiable    |
|microSD card (64GB, A2 rated)       |Flash Raspberry Pi OS Lite 64-bit|
|Active cooler                       |Required for 24/7 sustained load |

**Pi setup:** Headless, SSH only. No monitor/keyboard needed after initial flash.
**Static IP:** Assign via router DHCP reservation on first boot for stable dashboard URL.

-----

## Architecture

### Three Parallel Pipelines → Shared Store → Dashboard

```
ANALOG VOICE PIPELINE
[RTL-SDR Dongle]
      ↓
[Capture]         pyrtlsdr → WAV chunks, silence-filtered (Pi, local)
      ↓
[Preprocess]      Bandpass filter 300–3400Hz, normalize (Pi, local)
      ↓
[Whisper]         openai-whisper small model → raw text (Pi, local)
      ↓
[TranscriptionEvent]  {timestamp, frequency_mhz, raw_text, duration_sec}
      ↓
[Classify Agent]  TransmissionType + confidence (Anthropic Haiku)
      ↓
[Extract Agent]   Entities, location, severity, geocode (Anthropic Haiku)
      ↓
[Alert Agent] ←──────────────────────────────────────────┐
      ↓                                                   │
[SQLite DB]       voice_events table                      │
      ↓                                                   │
[Streamlit]       Live feed, map, charts ← local network  │
                                                          │
P25 DIGITAL PIPELINE (PCWIN trunked)                      │
[RTL-SDR Dongle]                                          │
      ↓                                                   │
[op25]            P25 Phase II decoder → WAV (Pi, local)  │
      ↓                                                   │
[Whisper]         Same transcription pipeline as analog   │
      ↓                                                   │
[TranscriptionEvent + source="p25"]                       │
      ↓                                                   │
[Classify / Extract / Alert] ────────────────────────────→│
                                                          │
APRS PIPELINE                                             │
[RTL-SDR @ 144.390 MHz]                                  │
      ↓                                                   │
[aprs3 decoder]   Structured packet → APRSEvent (Pi, local)
      ↓                                                   │
[Enrich]          Weather fields, spatial index (Pi, local)
      ↓                                                   │
[SQLite DB]       aprs_events table                       │
      ↓                                                   │
[Alert Agent] ───────────────────────────────────────────→┘
                  Cross-source monsoon correlation
```

**Key decisions:**
- Analog FM and P25 both feed Whisper → same agent graph downstream. Only the capture/decode layer differs.
- op25 runs as a separate subprocess tuned to PCWIN control channel; outputs decoded audio.
- APRS skips Whisper and classification — packet format already encodes type.
- The alert agent is the only node that sees all three pipelines and reasons across them.
- **Single RTL-SDR limitation:** can only tune to one frequency at a time. Frequency scanning or a second dongle required for simultaneous multi-channel monitoring. Start with one priority channel, expand later.

**All compute on Pi.** Only outbound traffic: Anthropic API calls for Haiku (classify/extract) and Sonnet (rolling summaries). No GPU needed.

-----

## Target Frequencies

> ⚠️ **Critical finding from hardware validation (May 2026):** Tucson Fire Department and virtually all major Pima County fire/EMS agencies operate on **PCWIN (Pima County Wireless Integrated Network) — Project 25 Phase II trunked digital**. Simple analog FM capture will not work for TFD. op25 is required to decode PCWIN traffic. Verified via radioreference.com May 2026.

### Analog FM — Receivable with rtl_fm (confirmed working)

|Frequency    |Agency                        |Description         |Pipeline|Priority        |
|-------------|------------------------------|--------------------|--------|----------------|
|154.370 MHz  |Rural Metro Fire / AMR        |Dispatch (F1/2)     |Voice   |⭐ Start here   |
|153.815 MHz  |Rural Metro Fire / AMR        |EMS Dispatch (F3)   |Voice   |⭐ Start here   |
|162.3975 MHz |NOAA Weather Radio Tucson     |Continuous broadcast|Voice   |⭐ Confirmed ✅  |
|144.390 MHz  |APRS 2m national              |Packet data         |Packet  |⭐ Start here   |
|154.400 MHz  |Rural Metro Fire / AMR        |Fireground (F4/F5)  |Voice   |High            |
|154.250 MHz  |Northwest Fire District       |Fireground backup   |Voice   |Medium          |
|151.2425 MHz |Northwest Fire District       |Backup dispatch     |Voice   |Medium          |
|146.820 MHz  |W7MST Tucson ham repeater     |Ham voice           |Voice   |Low             |

### P25 Digital Trunked — Requires op25 decoder

**System:** Pima County Wireless Integrated Network (PCWIN)
**Type:** Project 25 Phase II
**System ID:** `3BB` — **WACN:** `BEE00`

#### Control Channel Frequencies

op25 needs a control channel to lock onto the system. Use any of these for Metro Tucson:

| Site | Control Channels (MHz) |
|------|------------------------|
| Simulcast A (Metro Tucson) | 853.375, 853.625, 853.7125, 853.900 |
| Simulcast B (Metro Tucson) | 853.5375, 853.650, 853.850, 853.925 |
| North Simulcast (NW Tucson) | 851.3625, 851.6375, 851.7875, 852.725 |

Start with `853.625` (Simulcast A) as primary control channel.

#### Priority Talkgroups

| TG # (DEC) | TG # (HEX) | Description | Mode | Priority |
|------------|------------|-------------|------|----------|
| 15001 | 3a99 | TFD A2 — All Dispatches | T | ⭐ Primary |
| 15006 | 3a9e | TFD A3 — North Responses | T | High |
| 15007 | 3a9f | TFD A4 — South Responses | T | High |
| 15008 | 3aa0 | TFD A5 — East Responses | T | High |
| 15009 | 3aa1 | TFD A6 — West Responses | T | High |
| 15002 | 3a9a | TFD A7 — Major Incidents | T | High |
| 15000 | 3a98 | TFD A1 — Emergency | T | High |
| 13003 | 32cb | Rural Metro Fire Dispatch | T | High |
| 13007 | 32cf | AMR EMS-1 Tucson | T | High |
| 11012 | 2b04 | VECC Valley Fire Dispatch | T | Medium |
| 21500 | 53fc | Pima County EOC 1 | T | High (monsoon) |
| 21501 | 53fd | Pima County EOC 2 | T | High (monsoon) |
| 18009 | 4659 | PCSO East-1 Dispatch | T | Medium |
| 18024 | 4668 | PCSO North-1 Dispatch | T | Medium |
| 12001 | 2ee1 | Fire Back-up Station Alerting | T | Medium |

> ⚠️ Tucson Police (TPD) talkgroups are **encrypted** (`TE` mode) — skip entirely.
> ⚠️ Marana PD talkgroups are **encrypted** (`TE`) — skip.
> ✅ All TFD, Rural Metro, AMR, and VECC talkgroups are **unencrypted** (`T` mode).

#### op25 Config Snippet (for Phase 01.5)

```
# op25 trunk.tsv entry for PCWIN
# sysid  wacn   sysman  sites
3BB      BEE00  0       853.625
```

> 🔍 **Frequency scan findings (GQRX, May 2026):** 153.605 MHz (digital paging/POCSAG), 154.230 MHz (continuous, unidentified), 154.368 MHz (Rural Metro — matches 154.370 dispatch).

> ⚖️ Receive-only monitoring requires no ham license. All target TFD/Rural Metro/AMR talkgroups run unencrypted.
-----

## Pydantic Schemas

```python
# models/schemas.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from enum import Enum

class TransmissionType(str, Enum):
    FIRE = "fire"
    EMS = "ems"
    POLICE = "police"
    HAM = "ham"
    WEATHER = "weather"
    APRS = "aprs"
    FLOOD_CONTROL = "flood_control"
    UNKNOWN = "unknown"

class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"

class TranscriptionEvent(BaseModel):
    id: Optional[int] = None
    timestamp: datetime
    frequency_mhz: float
    raw_text: str
    duration_sec: float
    source: str = "analog"          # "analog" | "p25"
    talkgroup_id: Optional[int] = None  # P25 talkgroup DEC, e.g. 15001 for TFD Dispatch

class ClassifiedEvent(TranscriptionEvent):
    transmission_type: TransmissionType
    confidence: float  # 0.0–1.0
    language: str = "en"

class ExtractedEvent(ClassifiedEvent):
    locations: list[str] = []
    incident_type: Optional[str] = None
    callsigns: list[str] = []
    units: list[str] = []
    status_codes: list[str] = []
    severity: Severity = Severity.UNKNOWN
    lat: Optional[float] = None
    lon: Optional[float] = None
    wash_name: Optional[str] = None      # flood control
    road_closure: Optional[bool] = None  # flood control

class APRSEvent(BaseModel):
    """Bypasses Whisper and classification — packet type is already known."""
    id: Optional[int] = None
    timestamp: datetime
    callsign: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    symbol: Optional[str] = None
    comment: Optional[str] = None
    temp_f: Optional[float] = None
    rainfall_in: Optional[float] = None
    wind_mph: Optional[float] = None
    source: str = "aprs"

class AlertDecision(BaseModel):
    should_alert: bool
    reason: Optional[str] = None
    summary: Optional[str] = None
    correlated_event_ids: list[int] = []
    correlation_note: Optional[str] = None
```

-----

## Repository Structure

```
monsoon-ears/
├── ingestion/
│   ├── capture_analog.py   # rtl_fm → WAV chunks, silence filter
│   ├── capture_p25.py      # op25 subprocess → WAV chunks
│   ├── transcribe.py       # Whisper pipeline (shared by analog + P25)
│   ├── preprocess.py       # Bandpass filter + normalize
│   └── aprs_decode.py      # aprs3 decoder (runs as parallel process)
├── agents/
│   ├── graph.py            # LangGraph graph (all pipelines)
│   ├── classify.py         # Classification node — voice only
│   ├── extract.py          # Extraction node — voice + APRS enrichment
│   └── alert.py            # Alert + summary + monsoon correlation
├── models/
│   └── schemas.py          # All Pydantic models above
├── db/
│   ├── database.py         # SQLite via SQLModel
│   └── queries.py          # Common reads + spatial helpers
├── api/
│   └── main.py             # FastAPI: GET /summary, /events, /alerts
├── dashboard/
│   ├── app.py              # Streamlit main
│   └── monsoon.py          # Monsoon correlation tab
├── config/
│   └── trunk.tsv           # op25 PCWIN talkgroup config
├── tests/
│   ├── fixtures/           # Frozen transcripts + APRS packets (.json)
│   └── test_agents.py      # Pytest unit tests
├── docs/
│   └── architecture.md     # Mermaid diagram
├── .env.example
├── requirements.txt
└── README.md
```

-----

## Build Phases

### Phase 01 — Pi Setup & Hardware Validation (Week 1)

**Goal:** Confirmed working Pi + dongle before writing any pipeline code.

- [x] Flash Raspberry Pi OS Lite (64-bit) to microSD using Raspberry Pi Imager
- [x] Enable SSH in Imager advanced settings (set hostname `monsoon-ears`, username `keaton`, password, WiFi)
- [x] Install active cooler — third-party Vemico unit (3 separate thermal pads, not pre-applied; two mounting pins; 4-pin fan header near GPIO)
- [x] Boot Pi, SSH in: `ssh keaton@monsoon-ears.local`
- [ ] Assign static IP via router DHCP reservation ⚠️ *not yet done — Quantum Fiber router password unknown; Pi currently at 192.168.0.105 via DHCP*
- [x] `sudo apt update && sudo apt upgrade -y && sudo apt install rtl-sdr sox python3-pip git -y`
- [x] Plug in RTL-SDR dongle, run `rtl_test` — confirmed detected (R820T tuner, 1 device)
- [x] `python3 -m pip install pyrtlsdr --break-system-packages` — confirmed working (Raspberry Pi OS Lite uses externally-managed Python; always use `--break-system-packages` flag)
- [x] Confirmed hardware working via FM radio capture: `rtl_fm -f 91.3M -M fm -s 200k -r 16k -g 40 - | sox -t raw -r 16k -e signed -b 16 -c 1 - /tmp/fm.wav trim 0 10` → clear KUAT audio ✅
- [x] Confirmed NOAA Weather Radio reception: `162.3975 MHz` (not 162.550 — actual Tucson transmitter offset), NFM mode, Normal filter width ✅
- [x] Confirmed Rural Metro dispatch visible in GQRX at `154.368 MHz` (~154.370) ✅
- [x] Verified PCWIN system ID (`3BB`), WACN (`BEE00`), and control channel frequencies via radioreference.com ✅
- [x] Identified all priority TFD/Rural Metro/AMR talkgroup IDs ✅
- [ ] Assign static IP via router DHCP reservation ⚠️ *not yet done — Quantum Fiber router password unknown; Pi currently at `192.168.0.105` via DHCP*

**Deliverable:** Pi on network, dongle confirmed working, all target frequencies verified, PCWIN fully documented. ✅

**Field notes from Phase 01:**
- Active cooler CPU temp at idle: **45.5°C**, fan state: **0** (off) — healthy
- SSH reliability: use `ssh -v` flag if connection hangs after password; also add to `~/.ssh/config`:
  ```
  Host monsoon-ears.local
      ServerAliveInterval 10
      ServerAliveCountMax 3
  ```
- SSH key auth installed: `ssh-copy-id keaton@192.168.0.105` — passwordless SSH working ✅
- Moving the Pi degrades WiFi enough to break SSH — keep Pi stationary near router; run antenna coax to window separately
- `pip install` without `--break-system-packages` will fail on Raspberry Pi OS Lite 64-bit (PEP 668)
- NOAA actual Tucson frequency is **162.3975 MHz**, not 162.550 — and requires **NFM mode + Normal filter width** in GQRX / rtl_fm
- Use `ping monsoon-ears.local` to get current IP if DHCP lease changes
- GQRX on Mac useful for visual spectrum diagnosis — `brew install --cask gqrx`

-----

### Phase 01.5 — op25 Installation & PCWIN Validation (Week 1, before Phase 02)

**Goal:** op25 installed on Pi and successfully decoding PCWIN P25 traffic before building the ingestion pipeline around it.

> ⚠️ op25 is **not pip-installable**. It requires GNURadio and must be built from source. Budget 1–2 hours. Do this before Phase 02 — the ingestion pipeline depends on it working.

**Steps:**

```bash
# 1. Install GNURadio and dependencies
sudo apt install -y gnuradio gr-osmosdr cmake git

# 2. Clone op25
cd ~
git clone https://github.com/osmocom/op25.git
cd op25

# 3. Build
mkdir build && cd build
cmake ..
make -j4        # -j4 uses all 4 Pi 5 cores; takes ~20-30 min
sudo make install
sudo ldconfig

# 4. Test — lock onto PCWIN Simulcast A control channel
cd ~/op25/op25/gr-op25-repeater/apps
python3 rx.py --args 'rtl' -S 2000000 -o 60 -T trunk.tsv -l http:0.0.0.0:8080 2> stderr.2
```

**trunk.tsv for PCWIN:**
```
# Sysid  Nac    COSid  Wacn   Sysman  Sites                       TGs
3BB      0x3BB  0      BEE00  0       853.625:0:1:1               15001,15006,15007,15008,15009,13003,13007
```

**Validation:** op25 web UI at `http://192.168.0.105:8080` should show system lock and talkgroup activity. You should see TG 15001 (TFD A2 Dispatch) light up within a few minutes during daytime.

**Deliverable:** op25 running, PCWIN locked, TFD dispatch audio decoding to WAV.

-----

### Phase 02 — Ingestion Pipeline (Week 2–3)

**Goal:** Continuous audio capture from analog FM + P25 → Whisper transcription → SQLite, plus APRS decoding.

**Start frequency for analog voice:** `154.370 MHz` (Rural Metro Fire Dispatch) — confirmed active, analog FM, unencrypted. Use this to validate the full capture→Whisper→SQLite pipeline before adding P25 complexity.

**Voice ingestion (analog FM):**

```python
# ingestion/preprocess.py
import numpy as np
from scipy.signal import butter, filtfilt

def preprocess_radio_audio(audio_array, sr=16000):
    low, high = 300 / (sr/2), 3400 / (sr/2)
    b, a = butter(4, [low, high], btype='band')
    filtered = filtfilt(b, a, audio_array)
    return filtered / np.max(np.abs(filtered))
```

- Capture loop: tune to frequency, buffer IQ samples, convert to WAV chunks (5–10s)
- **Silence filter:** skip chunks < 1.5 seconds or below RMS amplitude threshold
- Load `whisper.load_model("small")` once at startup, reuse for all chunks
- Wrap output in `TranscriptionEvent`, persist to SQLite via SQLModel
- `source` field: `"analog"` for rtl_fm captures, `"p25"` for op25 decoded audio

**P25 ingestion (op25 subprocess):**

- op25 runs as a subprocess outputting decoded audio chunks
- Same Whisper pipeline as analog — only the capture layer differs
- Tag events with `source="p25"`, `talkgroup_id` field populated from op25 metadata
- Priority talkgroups to monitor: `15001` (TFD Dispatch), `13003` (Rural Metro), `13007` (AMR EMS-1)

**APRS ingestion (parallel process):**

- `pip install aprs3 --break-system-packages`
- Separate process tuned to 144.390 MHz
- Parse packets → `APRSEvent` schema
- Weather station packets (symbol `_`) → populate temp/rainfall/wind fields
- Store to `aprs_events` table in same SQLite DB

**Deliverable:** SQLite accumulating analog voice, P25 voice, and APRS packet events.

-----

### Phase 03 — LangGraph Agent Pipeline (Week 3–4)

**Goal:** Voice events flow through classify → extract → alert. APRS events skip to extract → alert.

**Classification node (voice only):**

```python
# agents/classify.py
import instructor
from anthropic import Anthropic
from models.schemas import ClassifiedEvent

client = instructor.from_anthropic(Anthropic())

def classify_node(event: TranscriptionEvent) -> ClassifiedEvent:
    return client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": f"Classify this radio transmission.\n"
                       f"Frequency: {event.frequency_mhz} MHz\n"
                       f"Text: {event.raw_text}\n\n"
                       f"Return transmission_type, confidence (0-1), language."
        }],
        response_model=ClassifiedEvent
    )
```

**Extraction node:**

- Voice: extract locations, incident_type, callsigns, units, severity, wash_name, road_closure
- APRS: enrich weather fields, geocode if needed
- Geocode location strings via `geopy` + Nominatim (free)
- Tucson washes as geocoding hints: Rillito, Pantano, Santa Cruz, Tanque Verde, Sabino, Canada del Oro

**Alert node (two-layer):**

1. Rule-based (free): `severity == HIGH` or `road_closure == True` → immediate Ntfy.sh push
1. LLM-based (Sonnet, every 15 min via APScheduler): rolling digest of recent activity

**Monsoon correlation prompt:**

```python
MONSOON_PROMPT = """
You are monitoring Tucson emergency radio and APRS weather stations.

Recent flood control radio activity:
{flood_events}

APRS weather station readings near mentioned locations (last 30 min):
{aprs_weather}

Are these consistent with an active flash flood situation?
Identify washes mentioned, correlate with nearby rainfall data,
assess severity, and flag if road closures appear imminent.
"""
```

**Deliverable:** Full agent pipeline running end-to-end on live data.

-----

### Phase 04 — FastAPI + Streamlit Dashboard (Week 5–6)

**Goal:** Observable, demoable system accessible from Mac browser.

**FastAPI endpoints:**

- `GET /events?limit=50&type=fire` — recent events, filterable by type
- `GET /summary` — latest 15-minute rolling digest
- `GET /alerts` — high-severity alert history
- `GET /aprs?limit=100` — recent APRS events

**Streamlit dashboard:**

- Live event feed (auto-refresh 30s) — voice + APRS unified view
- Folium map: incident pins (voice, color-coded by type) + APRS station markers (toggle)
- 24h activity bar chart by transmission type (altair)
- **Monsoon tab:** APRS rainfall readings by station, active flood control calls, affected washes, wash GeoJSON overlay
- NL query box → text-to-SQL → results table

Access via: `http://<pi-static-ip>:8501`

**Deliverable:** Live dashboard visible from Mac on same WiFi network.

-----

### Phase 05 — Polish & Portfolio (Week 7)

**Goal:** Repo is clean, demoable, and interview-ready.

- [ ] README with Mermaid architecture diagram, setup instructions, demo GIF
- [ ] `.env.example` with all keys documented
- [ ] `requirements.txt` with pinned versions
- [ ] Pytest fixtures: 20 sample transcripts + 10 APRS packets
- [ ] Record 2–3 min demo video — ideally during a monsoon storm
- [ ] LinkedIn/blog post: what you built, what surprised you, one thing you’d do differently

-----

## Key Dependencies

```txt
# SDR & Audio
pyrtlsdr
openai-whisper
sounddevice
scipy
aprs3

# P25 Digital Decoding
# op25 is NOT pip-installable — must be built from source on the Pi
# See: https://github.com/osmocom/op25
# Install via: sudo apt install gnuradio gr-osmosdr
# op25 runs as a subprocess, outputs decoded audio to stdout or UDP

# Agents & LLM
langgraph
anthropic
instructor
langchain          # text-to-SQL only

# Data & Storage
sqlmodel
pydantic
geopy

# API & Scheduling
fastapi
uvicorn
apscheduler

# Dashboard
streamlit
folium
streamlit-folium
altair

# Dev
pytest
python-dotenv
```

-----

## Environment Variables

```bash
# .env.example
ANTHROPIC_API_KEY=sk-ant-...
SDR_SAMPLE_RATE=2048000
SDR_GAIN=40
WHISPER_MODEL=small         # base | small | medium
SILENCE_THRESHOLD=0.01      # RMS amplitude floor
SILENCE_MIN_DURATION=1.5    # seconds
ALERT_NTFY_TOPIC=monsoon-ears-alerts
SUMMARY_INTERVAL_MIN=15
DB_PATH=/home/pi/monsoon-ears/data/events.db
API_PORT=8000
DASHBOARD_PORT=8501
```

-----

## Cost Summary

|Item                                     |Monthly       |
|-----------------------------------------|--------------|
|Pi 5 8GB (amortized 24mo)                |~$9           |
|RTL-SDR V3 (amortized 24mo)              |~$2           |
|Electricity (~5W avg)                    |~$0.40        |
|Anthropic API — Haiku classify/extract   |~$8–12        |
|Anthropic API — Sonnet summaries (96/day)|~$2–3         |
|**Total ongoing**                        |**~$22–27/mo**|

-----

## Interview Talking Points

**The hook:** "I built a multi-agent pipeline that listens to live Tucson emergency radio — both analog FM and P25 digital trunked — on a $40 dongle plugged into a Raspberry Pi, transcribes it with Whisper, routes it through a LangGraph graph, and during monsoon season correlates flood control dispatches with distributed APRS weather sensor data to synthesize flash flood alerts."

**Why multi-agent?** Each node has a single responsibility and independent failure mode. Classification failing doesn't break extraction. The graph makes data flow explicit and testable.

**Why three pipelines?** Voice (analog), P25 (digital trunked), and APRS are fundamentally different data formats requiring different decode layers, but they all converge at the same agent graph. APRS is already structured — it skips Whisper entirely. The interesting reasoning happens in the alert agent, which sees all three.

**Why op25?** Discovered during hardware validation that Tucson Fire Department runs P25 Phase II trunked digital, not analog FM. Added op25 as a decode layer that feeds the same Whisper → agent pipeline, so the downstream intelligence works identically regardless of source modality. This is a good example of the project evolving through real-world constraints.

**Why Pi + API vs fully local?** Deliberate architectural choice: edge ingestion (free, low latency) + cloud inference (quality without GPU). This is how production IoT/AI systems are actually built.

**The hard part:** Whisper on radio audio. Squelch noise, P25 digital artifacts, clipped speech. Silence filtering and bandpass preprocessing were essential — the pipeline produced garbage without them.

**What's next:** Swap API calls for a local 7B model on a Mac mini or NUC to eliminate ongoing costs. Add Pima County flood gauge sensor API as a third data source for the monsoon correlation.
-----

## Claude Code Handoff Notes

- Start with **Phase 01** entirely before touching Python. Hardware validation first.
- Build and test each phase fully before moving to the next. Don't scaffold the whole repo at once.
- The APRS pipeline is independent — build it in parallel with the voice pipeline from Phase 02 onward.
- Use `python-dotenv` from day one. No hardcoded paths or keys anywhere.
- The Pi runs Raspberry Pi OS Lite (no desktop). All Python deps install via `pip3 --break-system-packages`, system deps via `apt`.
- SQLite file lives at path set in `.env` — default `/home/keaton/monsoon-ears/data/events.db`
- Run Streamlit and FastAPI as `systemd` services so they survive reboots.
- `whisper.load_model()` is slow — load once at startup, keep in memory.
- **op25 is not pip-installable.** Must be built from source. Install GNURadio first: `sudo apt install gnuradio gr-osmosdr`. Then clone and build op25 from https://github.com/osmocom/op25. Plan a Phase 01.5 for this before P25 capture begins.
- **Single RTL-SDR = one frequency at a time.** Start with Rural Metro analog (154.370) for Phase 02. Add P25/PCWIN once op25 is working. A second RTL-SDR dongle (~$35) enables simultaneous channels.
- **Frequency scanning before Phase 02:** Spend time in GQRX confirming Rural Metro 154.370 and 153.815 are active before building the capture loop around them.
- **PCWIN talkgroup IDs:** Need to be identified from radioreference.com PCWIN system page before op25 can filter to TFD-specific traffic.
-----

*Monsoon Ears v2.3 — May 2026*
*Python · LangGraph · Whisper · RTL-SDR · op25 · aprs3 · Anthropic API · Streamlit*
*Phase 01 + frequency research complete. Phase 01.5 (op25) → Phase 02 next.*
