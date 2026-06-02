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

## 4. Bridge op25 audio into the pipeline  ✅ *built + verified live*

**Live finding:** with `-U`, op25 does **not** write per-call WAV files — it
streams decoded voice as **raw PCM over UDP to `127.0.0.1:23456`** (`Listening on
127.0.0.1:23456` in the log), and exposes the *current* call's talkgroup via the
`:8080` HTTP console. The Phase 5 `WavDirBackend` never matched this, so the
**`UdpP25Backend`** (`ingestion/capture_p25.py`) is the real bridge and is now the
default (`P25_BACKEND=udp` in `runner_p25`).

**Verified on the Pi (May 2026)** with `scripts/p25_preflight.py`:
- **UDP audio** = 320-byte datagrams → 160 × `int16` LE mono @ **8 kHz** (20 ms
  frames), plus occasional 2-byte keepalives (tolerated). Resampled 8k→16k.
- **Console:** `change_freq.tgid` is `null` when idle and carries the active
  talkgroup during a whitelisted voice call — `parse_active_tgid` reads it; a
  background `Op25ConsolePoller` keeps the latest tgid for pairing.
- **End-to-end:** a live PCSO East-1 (tg 18009) call produced a
  `source="p25", talkgroup_id=18009` row through Whisper → SQLite.

Call boundaries come from the inter-packet gap (`CallAccumulator`, `P25_GAP_SEC`,
default 0.8s). Run it manually to validate before enabling the leg:

```bash
# Terminal 1: op25 (uses the §3 command)
scripts/run_op25.sh
# Terminal 2: observe what op25 emits
uv run python scripts/p25_preflight.py --seconds 25
# Terminal 3: actually ingest (UDP backend; op25 already running)
P25_BACKEND=udp uv run python -m ingestion.runner_p25
```

## 5. Run it under the SDR supervisor

The single dongle is owned by **`monsoon-sdr`** (the supervisor), which time-shares
the analog and P25 legs — do **not** run `monsoon-p25` alongside it. The P25 leg
launches op25 itself via `OP25_CMD`, so set in `.env`:

```bash
SDR_ENABLE_P25=true
OP25_CMD=/home/keaton/Documents/projects/monsoon_ears/scripts/run_op25.sh
P25_BACKEND=udp
SDR_DEFAULT_POSTURE=p25          # P25-primary: op25 holds the dongle most of the cycle
SDR_LEG_COOLDOWN_SEC=8           # give op25/gnuradio time to release the SDR on a switch
```

then restart the supervisor:

```bash
sudo systemctl restart monsoon-sdr
journalctl -u monsoon-sdr -f
```

## 6. The control-channel re-lock cost (and how to minimize it)

Every time the P25 leg *starts*, op25 has to re-acquire the PCWIN control channel
before it can follow calls — measured at **~20–22s** on the Pi (leg start → the
`Reconfiguring NAC from 0x000 to 0x3b1` lock line). Calls in that window are
missed. In a time-shared P25-primary rota that's one re-lock per cycle (≈6/hour at
`SDR_CYCLE_MIN=10`). This is inherent to giving up the dongle for the analog leg —
there's no warm hand-off, op25 must cold-start.

Levers, cheapest first:

1. **Hold the leg.** The supervisor now *keeps op25 alive across cycle boundaries*
   when the next segment is the same leg (see `_run_segment` keep-alive). So a
   **P25-only posture** pays the re-lock exactly **once, at startup**, then never
   again:
   ```bash
   SDR_ENABLE_ANALOG=false     # op25 holds the dongle continuously — zero re-locks
   ```
   Use this during an active monsoon event when analog (NW Fire / NOAA / ham)
   isn't needed.
2. **Amortize.** Keep both legs but lengthen the cycle so the fixed re-lock cost is
   a smaller fraction of each P25 dwell and happens less often:
   ```bash
   SDR_CYCLE_MIN=20            # ~3 re-locks/hour instead of ~6, longer P25 dwell
   ```
3. **Let the Band Manager decide** (`BAND_MANAGER_AGENT=true`): on rising gauges /
   flood traffic it shifts weight toward P25, lengthening the P25 dwell and so
   amortizing the re-lock when it matters most.

> Note: in the default **P25-primary-with-analog** rota the legs alternate every
> cycle, so the keep-alive never triggers and the per-cycle re-lock is unavoidable
> — switch to a P25-only posture (lever 1) to eliminate it.
