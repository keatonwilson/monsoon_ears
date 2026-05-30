"""24-hour activity chart — stacked bar by transmission_type + counts by frequency."""

from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.api_client import APIClient


def render(client: APIClient) -> None:
    st.subheader("Activity in the last 24 hours")
    try:
        data = client.events(since_minutes=24 * 60, limit=500)
    except Exception as exc:  # noqa: BLE001
        st.error(f"API error: {exc}")
        return

    rows = data["results"]
    if not rows:
        st.info("No events in the last 24 hours yet.")
        return

    df = pd.DataFrame(rows)
    # API stores UTC-naive ISO; treat as UTC then convert to AZ for display.
    df["timestamp"] = (
        pd.to_datetime(df["timestamp"], utc=True)
        .dt.tz_convert("America/Phoenix")
    )
    df["hour"] = df["timestamp"].dt.floor("h")
    df["transmission_type"] = df["transmission_type"].fillna("unknown")
    df["frequency_mhz"] = df["frequency_mhz"].astype(float).round(4)

    st.metric("Events captured", len(df))
    st.metric("Distinct frequencies", df["frequency_mhz"].nunique())

    # Stacked bar: count per hour by type.
    counts = df.groupby(["hour", "transmission_type"]).size().reset_index(name="count")
    bar = (
        alt.Chart(counts)
        .mark_bar()
        .encode(
            x=alt.X("hour:T", title="Hour (Arizona)"),
            y=alt.Y("count:Q", title="Events"),
            color=alt.Color("transmission_type:N", legend=alt.Legend(title="Type")),
            tooltip=["hour:T", "transmission_type:N", "count:Q"],
        )
        .properties(height=320)
    )
    st.altair_chart(bar, use_container_width=True)

    # By frequency: a simple table for quick visual.
    freq_counts = (
        df.groupby("frequency_mhz").size().reset_index(name="events")
        .sort_values("events", ascending=False)
    )
    st.dataframe(freq_counts, use_container_width=True, hide_index=True)
