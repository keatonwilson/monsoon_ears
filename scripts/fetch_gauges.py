"""One-shot snapshot of the configured stream/rain gauges.

A quick way to confirm the USGS client + parser work against the live API (and,
with --pima, the best-effort Pima ALERT scraper) without running the polling
service. Prints a table; does not write to the DB.

    uv run python scripts/fetch_gauges.py
    uv run python scripts/fetch_gauges.py --pima
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from ingestion.pima_alert_client import fetch_pima_alert  # noqa: E402
from ingestion.usgs_client import fetch_usgs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pima", action="store_true", help="also hit the best-effort Pima ALERT feed")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    readings = list(fetch_usgs())
    if args.pima:
        readings += [r for r in fetch_pima_alert() if (r.precip_in or 0) > 0]

    if not readings:
        print("No gauge readings returned.")
        return 1

    print(f"{'source':10} {'site':10} {'name':34} {'Q(cfs)':>8} {'stage(ft)':>9} {'precip(in)':>10}")
    for r in sorted(readings, key=lambda r: (r.source, -(r.discharge_cfs or 0))):
        q = f"{r.discharge_cfs:.1f}" if r.discharge_cfs is not None else "-"
        s = f"{r.gage_height_ft:.2f}" if r.gage_height_ft is not None else "-"
        p = f"{r.precip_in:.2f}" if r.precip_in is not None else "-"
        print(f"{r.source:10} {r.site_id:10} {(r.site_name or '')[:34]:34} {q:>8} {s:>9} {p:>10}")
    print(f"\n{len(readings)} readings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
