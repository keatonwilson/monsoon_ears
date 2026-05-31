"""Discover candidate USGS stream gauges near Tucson that aren't in our catalog.

A deterministic helper for the `source-scout` skill: it queries the USGS site
service for active stream sites with instantaneous-values (IV) data inside a
Tucson bounding box, then diffs them against config/gauges.py so the scout can
cite hard data ("USGS 09xxxxxx, Cañada del Oro, has IV data and isn't in
USGS_SITES") rather than guessing.

This only *reports* candidates — it never edits config/gauges.py. The scout (or
you) decides what's actually worth adding.

    uv run python scripts/scout_sources.py            # human-readable table
    uv run python scripts/scout_sources.py --json      # machine-readable

The pure parse/diff functions take no network and are unit-tested in
tests/test_scout_sources.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Allow running as a bare script (python scripts/scout_sources.py) as well as a
# module — mirror scripts/fetch_gauges.py's bootstrap.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.gauges import USGS_SITES  # noqa: E402

SITE_URL = "https://waterservices.usgs.gov/nwis/site/"

# Tucson metro bounding box (west, south, east, north). Generous enough to catch
# Cañada del Oro and the east-side washes; tight enough to exclude Phoenix/Nogales.
TUCSON_BBOX = (-111.20, 31.90, -110.60, 32.55)


@dataclass(frozen=True)
class SiteCandidate:
    site_id: str
    name: str
    lat: float | None
    lon: float | None


def parse_site_rdb(text: str) -> list[SiteCandidate]:
    """Parse the USGS site service RDB (tab-separated) into candidates. Pure.

    RDB format: comment lines start with '#', then a header row of column names,
    then a 'format' row (e.g. '5s\\t15s\\t...'), then data rows. We key off the
    `site_no`, `station_nm`, `dec_lat_va`, `dec_long_va` columns by name so we're
    resilient to column reordering.
    """
    # RDB "format" row cells look like 5s / 15s / 16n / 11d.
    _fmt_cell = re.compile(r"^\d+[snd]$")

    header: list[str] | None = None
    out: list[SiteCandidate] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if header is None:
            header = cols
            continue
        # Skip the type/format row that follows the header.
        if all(_fmt_cell.match(c) for c in cols if c):
            continue
        row = dict(zip(header, cols))
        site_id = (row.get("site_no") or "").strip()
        if not site_id:
            continue

        def _f(key: str) -> float | None:
            v = (row.get(key) or "").strip()
            try:
                return float(v)
            except ValueError:
                return None

        out.append(SiteCandidate(
            site_id=site_id,
            name=(row.get("station_nm") or "").strip(),
            lat=_f("dec_lat_va"),
            lon=_f("dec_long_va"),
        ))
    return out


def new_candidates(discovered: list[SiteCandidate], known_ids: set[str]) -> list[SiteCandidate]:
    """Discovered sites not already in the catalog, de-duplicated. Pure."""
    seen: set[str] = set()
    out: list[SiteCandidate] = []
    for c in discovered:
        if c.site_id in known_ids or c.site_id in seen:
            continue
        seen.add(c.site_id)
        out.append(c)
    return out


def fetch_site_rdb(bbox: tuple[float, float, float, float] = TUCSON_BBOX, timeout: int = 30) -> str:
    """Fetch active IV stream sites in the bbox as RDB text."""
    import requests

    params = {
        "format": "rdb",
        "bBox": ",".join(f"{v:.4f}" for v in bbox),
        "siteType": "ST",          # stream
        "siteStatus": "active",
        "hasDataTypeCd": "iv",     # has instantaneous-values data
    }
    resp = requests.get(SITE_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def discover(bbox: tuple[float, float, float, float] = TUCSON_BBOX) -> list[SiteCandidate]:
    known = {s.site_id for s in USGS_SITES}
    return new_candidates(parse_site_rdb(fetch_site_rdb(bbox)), known)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args()

    try:
        candidates = discover()
    except Exception as exc:  # noqa: BLE001 — a discovery tool should fail loud but clean
        print(f"discovery failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([asdict(c) for c in candidates], indent=2))
        return 0

    known = {s.site_id for s in USGS_SITES}
    print(f"USGS sites already in config/gauges.py: {len(known)}")
    if not candidates:
        print("No new active IV stream gauges found in the Tucson bbox. Catalog looks complete.")
        return 0
    print(f"\n{len(candidates)} candidate gauge(s) NOT in the catalog:\n")
    for c in candidates:
        loc = f"({c.lat:.3f},{c.lon:.3f})" if c.lat and c.lon else "(no coords)"
        print(f"  {c.site_id}  {c.name}  {loc}")
    print("\nReview these and, if useful, add GaugeSite rows to config/gauges.py USGS_SITES.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
