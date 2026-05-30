# op25 / PCWIN P25 setup (on the Pi)

This brings the deferred **P25 Phase II** path online so Monsoon Ears ingests
Tucson Fire, Rural Metro, AMR, VECC, and the Pima County EOC from the **PCWIN**
trunked system — the same agent graph, a different physical-layer decoder.

> ⚠️ **All of this runs on the Pi against the SDR.** op25 is not pip-installable
> and cannot be validated off-device. The Python side
> (`ingestion/capture_p25.py`, `ingestion/runner_p25.py`, the talkgroup catalog,
> the generated `config/op25/` files) is unit-tested with a fake op25 backend,
> but live decode must be confirmed here.

## 1. Build op25 (one time, ~20–30 min)

op25 requires GNURadio and must be built from source.

```bash
sudo apt install -y gnuradio gr-osmosdr cmake git
cd ~
git clone https://github.com/osmocom/op25.git
cd op25
mkdir build && cd build
cmake ..
make -j4            # all 4 Pi 5 cores
sudo make install
sudo ldconfig
```

## 2. PCWIN system facts (verified via radioreference.com, May 2026)

- **System:** Pima County Wireless Integrated Network (PCWIN), P25 Phase II
- **System ID:** `3BB` · **WACN:** `BEE00`
- **Primary control channel:** `853.625 MHz` (Simulcast A; alternates
  `853.375 / 853.7125 / 853.900`)
- **Talkgroups:** the unencrypted priority set (TFD 15000–15009, Rural Metro
  13003, AMR 13007, VECC 11012, Pima EOC 21500/21501, PCSO 18009/18024, 12001).
  TPD and Marana PD are AES-encrypted (`TE`) and excluded.

The single source of truth is [`config/frequencies.py`](../config/frequencies.py)
(`PCWIN`, `PCWIN_TALKGROUPS`). The op25 config files are **generated** from it:

```bash
# from the repo root, after any edit to PCWIN_TALKGROUPS
uv run python scripts/gen_op25_config.py
```

This writes `config/op25/{trunk.tsv, tg_tags.tsv, whitelist.tsv}` (committed).
The whitelist contains only unencrypted talkgroups, so op25 never follows the
encrypted ones.

## 3. Validate the lock

```bash
cd ~/op25/op25/gr-op25-repeater/apps
python3 rx.py --args 'rtl' -S 2000000 -o 60 \
  -T /home/keaton/Documents/projects/monsoon_ears/config/op25/trunk.tsv \
  -l http:0.0.0.0:8080 2> stderr.2
```

Open `http://monsoon-ears.local:8080`. Within a few minutes (daytime) you should
see system lock and **TG 15001 (TFD A2 Dispatch)** light up with activity. If you
don't get a lock, try another Simulcast A control channel from the list above.

## 4. Bridge op25 audio into the pipeline

`ingestion/runner_p25.py` consumes **per-call WAV files** named
`<talkgroup_dec>-<epoch_millis>.wav` from `P25_WAV_DIR`, transcribes each, and
stores it as a `source="p25"` row with the real `talkgroup_id`.

Configure op25's call recorder to write WAVs into that directory using the above
naming, then point the runner at it. In `.env`:

```bash
P25_WAV_DIR=/home/keaton/Documents/projects/monsoon_ears/data/op25_calls
# Optional: let the runner launch op25 itself instead of running it separately.
# OP25_CMD=python3 /home/keaton/op25/op25/gr-op25-repeater/apps/rx.py --args 'rtl' ...
```

> The exact op25 recorder flags / filename shaping are the one piece that must
> be confirmed on the Pi against your op25 build. If op25's native recorder
> can't produce this naming directly, add a thin wrapper that renames its output
> into `<tgid>-<epoch_ms>.wav`. The `WavDirBackend` contract is intentionally
> simple so any shim satisfies it.

Run it manually first:

```bash
P25_WAV_DIR=.../data/op25_calls uv run python -m ingestion.runner_p25
```

Confirm `source="p25"` rows with real talkgroup IDs appear (e.g. via
`GET /events?source=p25`) and flow through classify → extract → alert to the
dashboard (the live feed shows `P25 · <talkgroup label>`).

## 5. Run it as a service

A unit ships at [`deploy/systemd/monsoon-p25.service`](./systemd/monsoon-p25.service)
but is **not** enabled by `install_services.sh` — turn it on only after the
manual run above works:

```bash
sudo systemctl enable --now monsoon-p25
journalctl -u monsoon-p25 -f
```
