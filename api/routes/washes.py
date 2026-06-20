"""GET /washes — Pima County wash centerlines for the map overlay.

The GeoJSON is fetched per-machine by scripts/fetch_washes.py (data/ is
gitignored), so the SPA can't bundle it at build time — it comes from here.
Best-effort like /sdr/status: an empty FeatureCollection if the file is absent.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/washes", tags=["washes"])

_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}


def _washes_path() -> Path:
    configured = os.getenv("WASHES_GEOJSON", "").strip() or "./data/washes.geojson"
    return Path(configured).expanduser()


@router.get("")
def get_washes():
    path = _washes_path()
    if not path.is_file():
        return JSONResponse(
            {"type": "FeatureCollection", "features": []}, headers=_CACHE_HEADERS
        )
    return FileResponse(path, media_type="application/geo+json", headers=_CACHE_HEADERS)
