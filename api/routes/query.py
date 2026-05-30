"""POST /query — natural language → SQL → results."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_readonly_engine
from api.nl_sql import NLSQLError, run

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


@router.post("")
def nl_query(req: QueryRequest) -> dict[str, Any]:
    try:
        result = run(req.question, engine=get_readonly_engine())
    except NLSQLError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "sql": result.sql,
        "row_count": result.row_count,
        "rows": result.rows,
    }
