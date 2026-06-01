"""Backfill lat/lon for transcription events that have locations but no coords.

The first soak ran with a placeholder Nominatim user-agent, so every geocode got
a 403 and ~10h of events have `locations` text but null `lat`/`lon` (→ no map
pins). This re-runs the (now fixed, fallback-chain) geocoder over those rows and
fills them in. Idempotent: rows that already have coordinates are skipped, and
the geocode cache means re-runs are cheap.

    uv run python scripts/backfill_geocode.py            # do it
    uv run python scripts/backfill_geocode.py --dry-run  # just report how many
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.extract import geocode  # noqa: E402
from db.database import TranscriptionEventRow, get_session  # noqa: E402
from sqlmodel import select  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only, don't write")
    ap.add_argument("--limit", type=int, default=0, help="cap rows processed (0 = all)")
    args = ap.parse_args()

    with get_session() as session:
        stmt = select(TranscriptionEventRow).where(
            TranscriptionEventRow.lat.is_(None),
            TranscriptionEventRow.locations.is_not(None),
        )
        rows = list(session.exec(stmt))

    # Only rows whose locations list is non-empty.
    candidates = [r for r in rows if r.locations]
    print(f"{len(candidates)} event(s) have locations but no coordinates.")
    if args.dry_run or not candidates:
        return 0
    if args.limit:
        candidates = candidates[: args.limit]

    filled = misses = 0
    for r in candidates:
        loc = r.locations[0]
        lat, lon = geocode(loc)
        if lat is None:
            misses += 1
            continue
        with get_session() as session:
            row = session.get(TranscriptionEventRow, r.id)
            row.lat, row.lon = lat, lon
            session.add(row)
            session.commit()
        filled += 1
        print(f"  id={r.id} {loc!r} -> ({lat:.5f}, {lon:.5f})")

    print(f"\nDone: filled {filled}, no-match {misses}, of {len(candidates)} processed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
