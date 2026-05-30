"""Fetch the Pima County Regional Flood Control wash network as GeoJSON.

Layer 6 ("Major Washes in Eastern Pima County") is the right size for our
overlay — covers Tucson and the named washes the project tracks (Rillito,
Pantano, Santa Cruz, Tanque Verde, Sabino, Cañada del Oro) without the
full 30 MB of every minor side channel.

The Pima County GIS portal serves this via a self-hosted ArcGIS MapServer
that supports `f=geojson` directly:

    https://gisdata.pima.gov/arcgis1/rest/services/GISOpenData/FloodControl/MapServer/6/query?where=1%3D1&outFields=*&f=geojson&outSR=4326

Run once:
    uv run python scripts/fetch_washes.py

Commit the resulting `data/washes.geojson` so the dashboard works on
fresh clones without re-hitting the GIS endpoint.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DEFAULT_LAYER = 6
URL_TEMPLATE = (
    "https://gisdata.pima.gov/arcgis1/rest/services/GISOpenData/FloodControl"
    "/MapServer/{layer}/query"
)
PARAMS = {
    "where": "1=1",
    "outFields": "*",
    "f": "geojson",
    "outSR": "4326",
}

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "washes.geojson"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", type=int, default=DEFAULT_LAYER,
                        help=f"MapServer layer id (default {DEFAULT_LAYER})")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    url = URL_TEMPLATE.format(layer=args.layer)
    logger.info("fetching %s", url)

    resp = requests.get(url, params=PARAMS, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features") or []
    if not features:
        logger.error("response had no features: %s", str(data)[:200])
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data))
    logger.info(
        "wrote %d features (%.1f KB) -> %s",
        len(features), args.output.stat().st_size / 1024, args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
