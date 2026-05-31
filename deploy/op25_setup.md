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

Use the **boatbod** fork — it's the actively-maintained P25-Phase-II fork and its
`install.sh` handles the GNURadio deps + build + install in one shot (verified on
a Pi 5 / Debian 13 "trixie" with GNURadio 3.10). Run it in `tmux` so a dropped
SSH doesn't kill the compile.

```bash
sudo apt install -y tmux git
tmux new -s op25
cd ~
git clone https://github.com/boatbod/op25.git
cd op25
./install.sh 2>&1 | tee ~/op25_build.log     # ~20–30 min; prompts for sudo
```

> The apps land in `~/op25/op25/gr-op25_repeater/apps/` — note the **underscore**
> (`gr-op25_repeater`), not the hyphen some older docs show.

## 2. PCWIN system facts (verified live on the Pi, May 2026)

- **System:** Pima County Wireless Integrated Network (PCWIN), P25 Phase II
- **WACN:** `0xBEE00` · **SYSID:** `0x3BB` · **RFSS/Site:** 1/1
- **Control-channel NAC:** `0x3B1` — **not** the SYSID. NAC is per-channel and
  independent of SYSID, so `trunk.tsv` sets the NAC column to **`0` (auto-detect)**;
  op25 then reports `Reconfiguring NAC from 0x000 to 0x3b1` and locks.
- **Control channels (Simulcast A):** `853.375 / 853.625 / 853.7125 / 853.900` —
  op25 roams across them automatically.
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

`rx.py` does `sys.path.append('tdma')` **relative to the current directory**, so
it must run **from the `apps/` dir** with `apps` + `apps/tdma` on `PYTHONPATH`
(otherwise: `ModuleNotFoundError: No module named 'lfsr'`). The relative
`tg_tags.tsv` / `whitelist.tsv` paths inside `trunk.tsv` also resolve against the
CWD, so copy the three config files into `apps/` (or use absolute paths):

```bash
cd ~/op25/op25/gr-op25_repeater/apps
cp ~/Documents/projects/monsoon_ears/config/op25/{trunk.tsv,tg_tags.tsv,whitelist.tsv} .
PYTHONPATH="$PWD:$PWD/tdma" ./rx.py --nocrypt --args 'rtl' --gains 'lna:40' \
  -S 960000 -q 0 -T trunk.tsv -2 -V -U -l http:0.0.0.0:8080 2>&1 | tee ~/op25_rx.log
```

Open `http://monsoon-ears.local:8080`. A healthy lock shows
`PCWIN Simulcast A (Metro Tucson)`, a header line like
`NAC 0x3b1 WACN 0xbee00 SYSID 0x3bb ... tsbks <rising>`, and the System
Frequencies table with **Active Talkgroup IDs** + Voice Counts as calls happen.
(`failed to open audio device: default` is harmless on a headless Pi — we use
`-U` for UDP audio, see §4.) If it doesn't lock, bump gain (`lna:40`→`49`) or
check the antenna.

## 4. Bridge op25 audio into the pipeline  ⏳ *remaining work*

**Live finding:** with `-U`, op25 does **not** write per-call WAV files — it
streams decoded voice as **raw PCM over UDP to `127.0.0.1:23456`** (`Listening on
127.0.0.1:23456` in the log), and exposes the *current* call's talkgroup/frequency
via the `:8080` HTTP console (the same JSON the web UI polls). So the Phase 5
`WavDirBackend` (which watched for `<tgid>-<epoch>.wav` files) does **not** match
this op25 build as-is. Two ways to close the gap:

1. **UDP backend (recommended).** Add a `P25Backend` that reads PCM frames from
   UDP `:23456` and pairs them with the active talkgroup polled from the
   `:8080` console, segmenting per call → `P25Call`. Replaces `WavDirBackend`
   for this op25 setup; the `run_p25_ingestion` loop and everything downstream
   stay the same.
2. **WAV-recorder shim.** Run op25's `audio.py`/recorder (or `multi_rx.py` with a
   file sink) to write per-call WAVs named `<tgid>-<epoch_ms>.wav` into
   `P25_WAV_DIR`, and keep the existing `WavDirBackend`.

Option 1 is the cleaner fit and is the next task. Until it lands, `runner_p25`
won't produce rows even though op25 is decoding.

```bash
# .env (already present)
P25_WAV_DIR=/home/keaton/Documents/projects/monsoon_ears/data/op25_calls
# OP25_CMD=  # leave empty; run rx.py from apps/ per §3 (PYTHONPATH + config copy)
```

The end-state goal is unchanged: `source="p25"` rows with real talkgroup IDs
appear (e.g. via `GET /events?source=p25`) and flow through classify → extract →
alert to the dashboard (`P25 · <talkgroup label>`).

## 5. Run it as a service

A unit ships at [`deploy/systemd/monsoon-p25.service`](./systemd/monsoon-p25.service)
but is **not** enabled by `install_services.sh` — turn it on only after the
manual run above works:

```bash
sudo systemctl enable --now monsoon-p25
journalctl -u monsoon-p25 -f
```
