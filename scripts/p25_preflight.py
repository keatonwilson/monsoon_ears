"""Diagnose what a running op25 is actually emitting — UDP audio + console JSON.

Run this on the Pi while op25 (scripts/run_op25.sh or rx.py -U -l http:...:8080) is
locked onto PCWIN. It does NOT touch the SDR; it just observes op25's outputs so
we can confirm the UdpP25Backend's assumptions (PCM rate/format, console shape,
talkgroup field) against reality before enabling the P25 leg.

    uv run python scripts/p25_preflight.py --seconds 20

Reports: UDP bytes/sec on :23456 (→ implied sample rate at S16LE mono), and the
raw console response on :8080 with the talkgroup parse_active_tgid extracts.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingestion.capture_p25 import parse_active_tgid  # noqa: E402


def probe_udp(host: str, port: int, seconds: float) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.settimeout(1.0)
    print(f"[udp] listening {host}:{port} for {seconds:.0f}s — key up a monitored talkgroup…")
    total = pkts = 0
    sizes = set()
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        try:
            data, _ = sock.recvfrom(65535)
        except socket.timeout:
            continue
        total += len(data)
        pkts += 1
        sizes.add(len(data))
    sock.close()
    dur = max(time.monotonic() - t0, 1e-9)
    bps = total / dur
    print(f"[udp] {pkts} pkts, {total} bytes in {dur:.1f}s = {bps:.0f} B/s")
    if total:
        print(f"[udp] packet sizes seen: {sorted(sizes)[:10]}")
        print(f"[udp] implied rate @ S16LE mono ≈ {bps/2:.0f} samples/s "
              f"(expect ~8000; 0 means no voice during the window)")
    else:
        print("[udp] NO audio — no voice call happened, op25 not running with -U, "
              "or wrong port.")


def probe_console(base_url: str) -> None:
    import requests

    url = base_url.rstrip("/") + "/"
    print(f"[console] POST {url} command=update")
    try:
        resp = requests.post(url, json=[{"command": "update", "arg1": 0, "arg2": 0}], timeout=4)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[console] FAILED: {exc}")
        return
    types = [m.get("json_type") for m in payload if isinstance(m, dict)]
    print(f"[console] {len(payload)} messages, types={types}")
    print(f"[console] parse_active_tgid -> {parse_active_tgid(payload)}")
    # Dump a trimmed view of any message carrying a tgid for eyeballing.
    for m in payload:
        if isinstance(m, dict) and m.get("tgid"):
            print("[console] tgid-bearing msg:", json.dumps(m)[:300])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--udp-host", default="127.0.0.1")
    ap.add_argument("--udp-port", type=int, default=23456)
    ap.add_argument("--console", default="http://127.0.0.1:8080")
    ap.add_argument("--seconds", type=float, default=20.0)
    args = ap.parse_args()

    probe_console(args.console)
    print()
    probe_udp(args.udp_host, args.udp_port, args.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
