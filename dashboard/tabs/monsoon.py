"""Monsoon correlation tab — APRS rainfall, flood-control voice, latest digest."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.api_client import APIClient
from dashboard.style import fmt_az_full


def _format_timestamp(iso: str | None) -> str:
    return fmt_az_full(iso)


def render(client: APIClient) -> None:
    st.subheader("Monsoon correlation")

    # --- Latest Sonnet digest -----------------------------------------------
    try:
        summary = client.summary()
    except Exception as exc:  # noqa: BLE001
        st.error(f"API error: {exc}")
        return

    if summary["available"]:
        cols = st.columns([1, 4])
        if summary["should_alert"]:
            cols[0].error("Alert active")
        else:
            cols[0].success("No alert")
        cols[1].caption(f"Last digest: {_format_timestamp(summary['timestamp'])}")
        if summary.get("summary"):
            st.markdown(f"**Summary** — {summary['summary']}")
        if summary.get("correlation_note"):
            st.markdown(f"**Correlation note** — {summary['correlation_note']}")
        if summary.get("correlated_event_ids"):
            st.caption(f"Correlated event ids: {summary['correlated_event_ids']}")
    else:
        st.info("No monsoon digest has run yet. The agent worker runs one every 15 minutes by default.")

    st.divider()

    # --- APRS weather rollup -------------------------------------------------
    st.markdown("### APRS weather stations (last 30 min)")
    try:
        aprs = client.aprs(minutes=30, limit=200)["results"]
    except Exception as exc:  # noqa: BLE001
        st.error(f"API error: {exc}")
        return

    if not aprs:
        st.caption("No APRS packets in the last 30 minutes. Start the APRS-IS client on the Pi.")
    else:
        df = pd.DataFrame(aprs)
        weather = df[df[["temp_f", "rainfall_in", "wind_mph"]].notna().any(axis=1)]
        if weather.empty:
            st.caption("APRS traffic is present but no weather-field reports in window.")
        else:
            agg = (
                weather.groupby("callsign")
                .agg(
                    temp_f=("temp_f", "max"),
                    rainfall_in=("rainfall_in", "max"),
                    wind_mph=("wind_mph", "max"),
                    last_seen=("timestamp", "max"),
                )
                .sort_values("rainfall_in", ascending=False, na_position="last")
                .reset_index()
            )
            st.dataframe(agg, use_container_width=True, hide_index=True)

    st.divider()

    # --- Recent fire / EMS / flood-control voice -----------------------------
    st.markdown("### Fire / EMS / flood-control radio (last 60 min)")
    try:
        events = client.events(since_minutes=60, limit=200)["results"]
    except Exception as exc:  # noqa: BLE001
        st.error(f"API error: {exc}")
        return
    relevant = [r for r in events if r.get("transmission_type") in ("fire", "ems", "flood_control")]
    if not relevant:
        st.caption("No fire / EMS / flood-control transmissions in the last hour.")
        return
    table = pd.DataFrame([
        {
            "id": r["id"],
            "time": _format_timestamp(r["timestamp"]),
            "type": r.get("transmission_type"),
            "severity": r.get("severity"),
            "freq_mhz": r["frequency_mhz"],
            "locations": ", ".join(r.get("locations") or []),
            "wash_name": r.get("wash_name"),
            "raw_text": (r.get("raw_text") or "")[:140],
        }
        for r in relevant
    ])
    st.dataframe(table, use_container_width=True, hide_index=True)
