#!/usr/bin/env bash
# Launch op25 (boatbod fork) locked onto PCWIN, streaming decoded voice as PCM
# over UDP :23456 with the HTTP console on :8080. This is the exact validated
# command from deploy/op25_setup.md §3, wrapped so it can be used as OP25_CMD
# (the SDR supervisor's P25 leg launches `ingestion.runner_p25`, which spawns
# this and consumes the UDP audio via UdpP25Backend).
#
# Runs ONLY on the Pi (needs the built op25 + the SDR). rx.py must run from the
# apps/ dir with apps + apps/tdma on PYTHONPATH (else ModuleNotFoundError: lfsr),
# and the trunk/tg_tags/whitelist files must resolve from CWD — so we copy the
# generated configs in first.
set -euo pipefail

OP25_APPS="${OP25_APPS:-$HOME/op25/op25/gr-op25_repeater/apps}"
REPO="${REPO:-$HOME/Documents/projects/monsoon_ears}"
GAINS="${OP25_GAINS:-lna:40}"

cd "$OP25_APPS"
cp "$REPO"/config/op25/{trunk.tsv,tg_tags.tsv,whitelist.tsv} .

exec env PYTHONPATH="$PWD:$PWD/tdma" ./rx.py \
    --nocrypt --args 'rtl' --gains "$GAINS" \
    -S 960000 -q 0 -T trunk.tsv -2 -V -U \
    -l http:0.0.0.0:8080
