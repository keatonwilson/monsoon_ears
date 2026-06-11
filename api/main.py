"""FastAPI app — read-only JSON over the events store, plus NL→SQL.

Also serves the React dashboard: web/dist (built on the dev Mac, rsynced to
the Pi) is mounted as static files with an SPA fallback, so the UI and API
share :8000 and the same origin.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from api.routes import (  # noqa: E402
    alerts,
    aprs,
    events,
    gauges,
    hourly,
    query,
    sdr,
    summary,
    threads,
    washes,
    weather,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="Monsoon Ears API",
    version="0.4.0",
    description="Read-only access to Tucson public-safety radio events, "
                "APRS weather packets, and the monsoon-correlation digest.",
)

# No CORS middleware: the React dashboard is served same-origin from this app,
# and the Vite dev server proxies API paths so dev is same-origin too.
# Gzip is mainly for /washes (3 MB of GeoJSON) but list endpoints benefit too.
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(events.router)
app.include_router(aprs.router)
app.include_router(gauges.router)
app.include_router(summary.router)
app.include_router(alerts.router)
app.include_router(threads.router)
app.include_router(hourly.router)
app.include_router(sdr.router)
app.include_router(query.router)
app.include_router(weather.router)
app.include_router(washes.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


# --- SPA serving -------------------------------------------------------------
# Registered after every API route so those always win. Guarded so the API
# runs fine on a machine without a frontend build (e.g. CI, fresh checkout).

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        # index.html itself is uncached; the hashed files under /assets carry
        # the long-term caching.
        return FileResponse(WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"})
