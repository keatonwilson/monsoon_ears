"""GET /sdr/status — what the dongle is doing right now.

The SDR supervisor (ingestion/sdr_supervisor.py) owns the single dongle and
time-shares the RF legs; it writes its current state to SDR_STATUS_FILE each time
it switches legs. This route just surfaces that file so the dashboard can show
which band is live and why. Read-only and best-effort: if the file is missing
(supervisor not running, or status file not configured) we report unavailable
rather than erroring.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/sdr", tags=["sdr"])


@router.get("/status")
def sdr_status() -> dict[str, Any]:
    path = os.getenv("SDR_STATUS_FILE", "").strip() or "./data/sdr_status.json"
    try:
        with open(path) as fh:
            status = json.load(fh)
    except (OSError, ValueError):
        return {"available": False}
    status["available"] = True
    return status
