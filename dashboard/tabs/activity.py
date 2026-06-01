"""24-hour activity chart — stacked bar by transmission_type + counts by frequency."""

from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.api_client import APIClient
from dashboard.style import SOURCE_LABELS, channel_label


def _render_sdr_banner(client: APIClient) -> None:
    """Compact 'what's the dongle doing right now' line, if the supervisor is up."""
    try:
        status = client.sdr_status()
    except Exception:  # noqa: BLE001 — never let the banner break the tab
        return
    if not status.get("available"):
        return
    leg = status.get("current_leg")
    label = {"p25": "P25 / PCWIN", "analog": "Analog scan"}.get(leg, leg or "idle")
    src = status.get("plan_source", "")
    badge = "🤖 agent" if src == "agent" else "📻 rules"
    line = f"**Current band:** {label}  ·  {badge}"
    rationale = status.get("rationale")
    if rationale:
        line += f"  ·  _{rationale}_"
    st.caption(line)


def render(client: APIClient) -> None:
    st.subheader("Activity in the last 24 hours")
    _render_sdr_banner(client)
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
    df["source"] = df["source"].fillna("analog") if "source" in df else "analog"
    # Human channel per row: talkgroup name for P25, frequency for analog.
    df["channel"] = df.apply(lambda r: channel_label(r.to_dict()), axis=1)

    m1, m2, m3 = st.columns(3)
    m1.metric("Events captured", len(df))
    m2.metric("Distinct channels", df["channel"].nunique())
    by_source = df["source"].value_counts().to_dict()
    m3.metric(
        "By source",
        " · ".join(f"{SOURCE_LABELS.get(s, s)} {n}" for s, n in by_source.items()) or "—",
    )

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

    # By channel: a simple table for quick visual. Uses the talkgroup name for
    # P25 rows instead of the 0.0 MHz placeholder, and carries the source.
    chan_counts = (
        df.groupby(["source", "channel"]).size().reset_index(name="events")
        .sort_values("events", ascending=False)
    )
    st.dataframe(chan_counts, use_container_width=True, hide_index=True)
