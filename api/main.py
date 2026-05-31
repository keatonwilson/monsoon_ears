"""FastAPI app — read-only JSON over the events store, plus NL→SQL."""

from __future__ import annotations

import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from api.deps import get_settings  # noqa: E402
from api.routes import alerts, aprs, events, gauges, query, summary, threads  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="Monsoon Ears API",
    version="0.4.0",
    description="Read-only access to Tucson public-safety radio events, "
                "APRS weather packets, and the monsoon-correlation digest.",
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(aprs.router)
app.include_router(gauges.router)
app.include_router(summary.router)
app.include_router(alerts.router)
app.include_router(threads.router)
app.include_router(query.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}
