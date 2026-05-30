"""Shared FastAPI dependencies: settings, read-only DB engine."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


class Settings(BaseModel):
    db_path: str
    cors_origins: list[str]


@lru_cache
def get_settings() -> Settings:
    return Settings(
        db_path=os.getenv("DB_PATH", "./data/events.db"),
        cors_origins=[
            "http://localhost:8501",
            "http://monsoon-ears.local:8501",
            "http://127.0.0.1:8501",
        ],
    )


@lru_cache
def get_readonly_engine() -> Engine:
    """SQLite engine opened in read-only mode. The runner/worker keep their
    own writable engines via db.database.get_engine() — this never overlaps."""
    path = Path(get_settings().db_path).expanduser().resolve()
    # `?mode=ro&uri=true` makes SQLite reject any write attempts at the driver
    # level. We still set `check_same_thread=False` so FastAPI workers can
    # share the engine.
    url = f"sqlite:///file:{path}?mode=ro&uri=true"
    return create_engine(url, connect_args={"check_same_thread": False, "uri": True})
