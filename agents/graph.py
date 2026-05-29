"""LangGraph DAG that runs classify → extract → alert for a single row.

The graph is intentionally linear — each node has a single responsibility and
its own failure mode. Nodes update typed state in place; the final node
persists results to SQLite and (conditionally) pushes a Ntfy alert.
"""

from __future__ import annotations

import logging
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph

from agents.alert import evaluate_alert, push_ntfy
from agents.classify import classify_event
from agents.extract import extract_event
from db.database import TranscriptionEventRow, get_session
from db.queries import update_classification, update_extraction
from models.schemas import (
    AlertDecision,
    ClassifiedEvent,
    ExtractedEvent,
    TranscriptionEvent,
)

logger = logging.getLogger(__name__)


class GraphState(TypedDict, total=False):
    row_id: int
    transcription: TranscriptionEvent
    classified: Optional[ClassifiedEvent]
    extracted: Optional[ExtractedEvent]
    alert: Optional[AlertDecision]


def classify_node(state: GraphState) -> dict:
    classified = classify_event(state["transcription"])
    return {"classified": classified}


def extract_node(state: GraphState) -> dict:
    extracted = extract_event(state["classified"])
    return {"extracted": extracted}


def alert_node(state: GraphState) -> dict:
    extracted = state["extracted"]
    classified = state["classified"]
    row_id = state["row_id"]
    # Persist agent outputs.
    update_classification(row_id, classified)
    update_extraction(row_id, extracted)
    decision = evaluate_alert(extracted)
    if decision.should_alert:
        push_ntfy(
            title=f"[Monsoon Ears] {decision.reason or 'alert'}",
            body=decision.summary or extracted.raw_text[:200],
        )
    return {"alert": decision}


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("classify", classify_node)
    g.add_node("extract", extract_node)
    g.add_node("alert", alert_node)
    g.set_entry_point("classify")
    g.add_edge("classify", "extract")
    g.add_edge("extract", "alert")
    g.add_edge("alert", END)
    return g.compile()


_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def _row_to_event(row: TranscriptionEventRow) -> TranscriptionEvent:
    return TranscriptionEvent(
        id=row.id,
        timestamp=row.timestamp,
        frequency_mhz=row.frequency_mhz,
        raw_text=row.raw_text,
        duration_sec=row.duration_sec,
        source=row.source,
        talkgroup_id=row.talkgroup_id,
    )


def run_for_row(row_id: int) -> GraphState:
    """Hydrate state from a TranscriptionEventRow and run the graph."""
    with get_session() as session:
        row = session.get(TranscriptionEventRow, row_id)
        if row is None:
            raise ValueError(f"row {row_id} not found")
        transcription = _row_to_event(row)
    initial: GraphState = {
        "row_id": row_id,
        "transcription": transcription,
        "classified": None,
        "extracted": None,
        "alert": None,
    }
    logger.debug("running graph for row %d", row_id)
    final = get_graph().invoke(initial)
    return final
