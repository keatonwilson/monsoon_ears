"""Thin requests-based client for the Monsoon Ears FastAPI app."""

from __future__ import annotations

import os
from typing import Any, Optional

import requests


class APIClient:
    def __init__(self, base_url: Optional[str] = None, timeout_sec: float = 10.0):
        self.base_url = (base_url or os.getenv("MONSOON_API_URL", "http://localhost:8000")).rstrip("/")
        self.timeout = timeout_sec

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        resp = requests.get(f"{self.base_url}{path}", params=params or {}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(f"{self.base_url}{path}", json=body, timeout=self.timeout)
        if resp.status_code >= 400:
            # Bubble up the API's reason verbatim for the dashboard to surface.
            try:
                detail = resp.json().get("detail")
            except Exception:  # noqa: BLE001
                detail = resp.text
            raise APIClientError(detail or f"HTTP {resp.status_code}")
        return resp.json()

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def events(self, **params) -> dict[str, Any]:
        return self._get("/events", params=params)

    def event(self, event_id: int) -> dict[str, Any]:
        return self._get(f"/events/{event_id}")

    def aprs(self, **params) -> dict[str, Any]:
        return self._get("/aprs", params=params)

    def gauges(self, **params) -> dict[str, Any]:
        return self._get("/gauges", params=params)

    def summary(self) -> dict[str, Any]:
        return self._get("/summary")

    def alerts(self, **params) -> dict[str, Any]:
        return self._get("/alerts", params=params)

    def nl_query(self, question: str) -> dict[str, Any]:
        return self._post("/query", body={"question": question})

    def threads(self, **params) -> dict[str, Any]:
        return self._get("/threads", params=params)

    def thread(self, thread_id: int) -> dict[str, Any]:
        return self._get(f"/threads/{thread_id}")

    def resummarize_thread(self, thread_id: int) -> dict[str, Any]:
        return self._post(f"/threads/{thread_id}/summarize", body={})


class APIClientError(Exception):
    pass
