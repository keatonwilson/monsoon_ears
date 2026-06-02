# Monsoon Ears — Handoff Checklist (2026-06-01)

Status: Phases 07–09 merged to `main`. The full pipeline is **production-stable** and
soaking on the Pi: single-dongle SDR supervisor time-sharing analog↔P25 (P25-primary),
APRS-IS, USGS gauges, the LangGraph worker, monsoon digest, FastAPI + Streamlit dashboard.
~11.5h soak: **0 service restarts, 62/62 op25 PCWIN locks, clean leg switches both directions.**

This is a prioritized list of known issues/fixes for the next session. Items are roughly
ordered by leverage. Each notes the relevant file(s).

---

## Environment / access (read first)
- **Pi:** `keaton@192.168.0.105` (`monsoon-ears.local`). **Always SSH with `-o IPQoS=none`**
  or the connection hangs (DSCP packet marking, not "flaky wifi" — see memory `pi-ssh-ipqos`).
- **sudo is password-gated** — ask the user for it; don't expect unattended `systemctl`.
- Repo on Pi: `~/Documents/projects/monsoon_ears` (lowercase `projects`), now on `main`.
- Services (systemd, `Restart=on-failure`): `monsoon-sdr`, `monsoon-worker`, `monsoon-aprs`,
  `monsoon-gauges`. Dashboard + API are **NOT** services (see B1).
- Dashboard: http://192.168.0.105:8501 · API: http://192.168.0.105:8000

---

## A. Quality / accuracy — highest leverage

- [ ] **A1. Transcription quality is the #1 limiter.** Most P25/analog transcripts are
  Whisper garble ("northwest Maine", "4th half location", "This was coffee depraved").
  Only **~25% of location-tagged events geocode** because the extracted "location" text is
  nonsense — *not* a geocoder problem. Options, cheapest first:
  - Whisper `initial_prompt` seeded with Tucson street/agency/scanner vocabulary
    (units, "code 2", wash names, common streets) to bias decoding.
  - Bump model `small`→`medium` (CPU cost on the Pi — benchmark first).
  - Tighten the no_speech/logprob hallucination gates (`ingestion/transcribe.py`,
    `agents/hallucination.py`) — some garble is low-confidence and should be dropped.
  - Files: `ingestion/transcribe.py`, `ingestion/preprocess.py`, `agents/hallucination.py`.

- [ ] **A2. Extraction emits low-quality locations from garbled text.** The extractor will
  happily return "northwest Maine" as a location. Consider: only geocode when classifier
  confidence is high, and/or validate the extracted string looks address-like before geocoding.
  File: `agents/extract.py`.

---

## B. Operational / deployment hardening

- [ ] **B1. Dashboard + API run in a tmux session (`monsoon-ui`), not systemd.** They will
  **not survive a Pi reboot.** Add `monsoon-api.service` + `monsoon-dashboard.service`
  (model on the existing units in `deploy/systemd/`, wrap `scripts/run_api.sh` /
  `scripts/run_dashboard.sh`) and add them to `deploy/install_services.sh`.

- [ ] **B2. Geocode cache permanently caches negative results — design bug that bit us.**
  `geocode()` writes `cache[key] = [lat, lon]` even when both are `None`, and cache-first
  returns that forever. A transient provider outage (or the original 403 bug) **poisons the
  cache permanently** — that's why the first backfill filled 0/202 and I had to manually purge
  184 null entries. Fix: don't cache misses, OR cache them with a short TTL, OR distinguish
  "clean no-match" (cacheable) from "error/timeout" (never cache). File: `agents/extract.py`
  (`geocode`, `_load_cache`/`_save_cache`). The `scripts/backfill_geocode.py` helper exists for re-runs.

- [ ] **B3. Clean up soak scaffolding on the Pi.** A `soakmon` tmux session (5-min metrics
  logger → `data/soak_metrics.log`) is still running. Decide: formalize it as a tiny health
  endpoint/service, or kill it. Also a stray `~/Documents/projects/monsoon_ears/.claude/.claude/`
  dir + untracked `.claude/settings.local.json` on the Pi — tidy up.

- [ ] **B4. APRS uses `N0CALL` (receive-only).** Fine for read-only, but if you want to be a
  good APRS-IS citizen / avoid future filtering, register a real callsign. `.env` `APRS_IS_CALLSIGN`.

---

## E. Dashboard UX

- [ ] **E1. Distinguish P25 vs. analog vs. APRS signals more clearly (esp. threads).**
  (User request.) The dashboard doesn't make the source obvious — threads in particular
  should visually call out whether a cluster is P25 (with talkgroup label), analog FM (with
  frequency), or APRS. Ideas: a per-source badge/color/icon on thread + event rows, source
  filters, and showing the P25 talkgroup name (via `config/frequencies.talkgroup_label`) instead
  of the `frequency_mhz=0.0` placeholder P25 rows carry. Files: `dashboard/tabs/threads.py` (and
  the other tabs), `dashboard/tabs/activity.py`; data already has `source` + `talkgroup_id`.

## C. P25 / op25

- [ ] **C1. op25 re-locks PCWIN (~25s) every time the P25 leg starts.** Inherent to
  time-sharing one dongle P25-primary (62 re-locks over the soak). During those ~25s, calls
  are missed. Options: longer `SDR_CYCLE_MIN` / P25 dwell to amortize; a P25-only posture
  (`SDR_ENABLE_ANALOG=false`) when analog isn't needed; or investigate whether op25 can be
  suspended/resumed instead of killed. Files: `ingestion/sdr_supervisor.py`,
  `agents/band_manager.py`, `deploy/op25_setup.md` §5.

- [ ] **C2. The Band Manager agent layer (`BAND_MANAGER_AGENT`) has never run live.** It's off
  by default and only unit-tested. If desired, enable it during a monsoon event and validate it
  actually shifts dwell toward P25 on rising gauges/flood traffic. File: `agents/band_manager.py`.

- [ ] **C3. Harmless noise:** op25 logs `failed to open audio device: default` on the headless
  Pi (expected — we use `-U` UDP audio). Could suppress to keep journals clean.

---

## D. Nice-to-have / future

- [ ] **D1. New data sources (deferred from Phase 07).** The `/source-scout` skill proposes
  candidates (review-only). NWS api.weather.gov watches/warnings is the keystone next add — it
  feeds the digest AND becomes a stronger Band Manager signal. Also: Pima DOT road closures.
- [ ] **D2. Run `/source-scout`** to get a reviewable proposal of untracked USGS gauges /
  PCWIN talkgroups (e.g. `scripts/scout_sources.py` already finds untracked Tucson gauges).
- [ ] **D3. Real soak metrics summary.** `data/soak_metrics.log` on the Pi has the full
  11.5h time series if you want a proper writeup / chart.

---

## Process notes
- **Per-workstream branches + PRs off `main`** is the established workflow; the user merges.
- **Avoid stacked PRs.** PR #10 was based on PR #9's branch; `gh pr edit --base main` to
  retarget is **blocked by a GitHub projects-classic GraphQL error**, so #10 merged into its
  stacked base and a follow-up PR (#11) was needed to carry the diff into `main`. Branch
  directly off `main` next time.
- Tests: `uv run --no-sync pytest -q` (180 passing). Run on dev machine; op25/SDR can't run there.
