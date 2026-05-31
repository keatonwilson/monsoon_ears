"""agents/band_manager.py — deterministic baseline + clamped, fail-safe agent."""

import pytest

from agents.band_manager import (
    LEG_ANALOG,
    LEG_P25,
    _allocate,
    _BandPlanResponse,
    _normalise_clamped,
    plan_dwell,
)
from agents.context import Situation


def _situation(**kw) -> Situation:
    base = dict(
        flood_event_count=0, gauge_reading_count=0, max_discharge_cfs=None,
        max_gage_height_ft=None, aprs_packet_count=0, aprs_rain_max_in=None,
        hour_local=14, monsoon_season=True,
    )
    base.update(kw)
    return Situation(**base)


# --- fake LLM client (instructor-style: returns the response_model) ----------


class _FakeMessages:
    def __init__(self, response, raises=False):
        self.response = response
        self.raises = raises
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("boom")
        return self.response


class _FakeClient:
    def __init__(self, response=None, raises=False):
        self.messages = _FakeMessages(response, raises=raises)


# --- pure allocation ---------------------------------------------------------


def test_allocate_splits_by_weight_and_sums_to_cycle():
    alloc = _allocate({LEG_P25: 0.7, LEG_ANALOG: 0.3}, cycle_sec=600, floor_sec=60)
    assert alloc[LEG_P25] > alloc[LEG_ANALOG]
    assert pytest.approx(sum(alloc.values())) == 600


def test_allocate_enforces_floor_for_extreme_weights():
    alloc = _allocate({LEG_P25: 0.98, LEG_ANALOG: 0.02}, cycle_sec=600, floor_sec=60)
    assert alloc[LEG_ANALOG] >= 60
    assert pytest.approx(sum(alloc.values())) == 600


def test_allocate_single_leg_gets_whole_cycle():
    assert _allocate({LEG_ANALOG: 1.0}, cycle_sec=600, floor_sec=60) == {LEG_ANALOG: 600}


def test_normalise_clamped_no_zero_weight():
    # A zero from the agent must not produce a zero-weight leg; the hard
    # per-leg floor itself is enforced later in _allocate (seconds).
    w = _normalise_clamped({LEG_P25: 1.0, LEG_ANALOG: 0.0})
    assert w[LEG_ANALOG] > 0.0
    assert pytest.approx(sum(w.values())) == 1.0


# --- baseline plan -----------------------------------------------------------


def test_baseline_is_p25_primary_and_ordered(monkeypatch):
    monkeypatch.setenv("BAND_MANAGER_AGENT", "false")
    plan = plan_dwell(cycle_sec=600, legs=[LEG_P25, LEG_ANALOG], floor_sec=60)
    assert plan.source == "baseline"
    # P25 leads the cycle and gets the larger share.
    assert plan.segments[0].leg == LEG_P25
    assert plan.segments[0].seconds > plan.segments[1].seconds
    assert pytest.approx(plan.total_seconds) == 600


def test_single_enabled_leg_skips_agent(monkeypatch):
    monkeypatch.setenv("BAND_MANAGER_AGENT", "true")  # would call LLM if consulted
    plan = plan_dwell(cycle_sec=600, legs=[LEG_ANALOG])
    assert plan.source == "single-leg"
    assert len(plan.segments) == 1
    assert plan.segments[0].leg == LEG_ANALOG
    assert plan.segments[0].seconds == 600


def test_no_legs_returns_empty_plan():
    plan = plan_dwell(cycle_sec=600, legs=[])
    assert plan.segments == []


# --- agentic layer -----------------------------------------------------------


def test_agent_shifts_toward_p25_under_flood_conditions(monkeypatch):
    monkeypatch.setenv("BAND_MANAGER_AGENT", "true")
    client = _FakeClient(_BandPlanResponse(
        p25_weight=0.95, analog_weight=0.05,
        rationale="Rillito discharge spiking — camp on PCWIN fire/EMS.",
    ))
    snap = _situation(flood_event_count=6, max_discharge_cfs=900.0, aprs_rain_max_in=1.3)
    plan = plan_dwell(
        cycle_sec=600, legs=[LEG_P25, LEG_ANALOG], floor_sec=60,
        snapshot=snap, client=client,
    )
    assert plan.source == "agent"
    assert "Rillito" in plan.rationale
    assert plan.segments[0].leg == LEG_P25
    # Agent pushed harder toward P25 than the 0.7 baseline would.
    assert plan.weights[LEG_P25] > 0.7
    assert plan.segments[1].seconds >= 60  # floor still honoured
    assert client.messages.calls, "agent should have been consulted"


def test_agent_failure_falls_back_to_baseline(monkeypatch):
    monkeypatch.setenv("BAND_MANAGER_AGENT", "true")
    client = _FakeClient(raises=True)
    plan = plan_dwell(
        cycle_sec=600, legs=[LEG_P25, LEG_ANALOG], floor_sec=60,
        snapshot=_situation(), client=client,
    )
    assert plan.source == "baseline"
    assert plan.segments[0].leg == LEG_P25  # still a valid P25-primary plan
    assert pytest.approx(plan.total_seconds) == 600
