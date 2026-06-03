"""Last-hour tab — a wide-angle rollup of every source, built once an hour.

Complements the Threads tab (per-conversation) with a single digest of the
whole hour: counts by type, top incidents, gauge/weather posture, plus a
scrollable history of prior rollups.
"""

from __future__ import annotations

import streamlit as st

from dashboard.api_client import APIClient
from dashboard.style import fmt_az, fmt_az_full, severity_chip


def _render_summary(s: dict) -> None:
    start = fmt_az(s.get("window_start"))
    end = fmt_az(s.get("window_end"))
    sev = severity_chip(s.get("severity_max")) if s.get("severity_max") else ""
    st.markdown(
        f"{sev} <b>{start}–{end}</b> · {s.get('event_count', 0)} event(s)",
        unsafe_allow_html=True,
    )
    if s.get("summary"):
        st.markdown(f"💬 {s['summary']}")

    by_type = s.get("by_type") or {}
    if by_type:
        cols = st.columns(max(len(by_type), 1))
        for col, (t, n) in zip(cols, sorted(by_type.items(), key=lambda kv: -kv[1])):
            col.metric(t, n)

    if s.get("top_incidents"):
        st.markdown("**Top incidents**")
        for inc in s["top_incidents"]:
            st.markdown(f"- {inc}")

    notes = st.columns(2)
    if s.get("gauge_note"):
        notes[0].caption(f"🌊 {s['gauge_note']}")
    if s.get("weather_note"):
        notes[1].caption(f"⛈️ {s['weather_note']}")


def render(client: APIClient) -> None:
    st.subheader("Last hour at a glance")
    st.caption(
        "A wide-angle rollup of every source — voice by type, top incidents, "
        "gauge + weather posture — regenerated once an hour."
    )

    auto = st.toggle("Auto-refresh (60s)", value=True, key="hourly_auto")
    if auto:
        try:
            from streamlit_autorefresh import st_autorefresh  # type: ignore
            st_autorefresh(interval=60_000, key="hourly_refresh")
        except Exception:  # noqa: BLE001
            pass

    try:
        latest = client.hourly_summary().get("summary")
    except Exception as exc:  # noqa: BLE001
        st.error(f"API error: {exc}")
        return

    if not latest:
        st.info("No hourly summary yet — the worker generates one each hour.")
        return

    with st.container(border=True):
        st.caption(f"Generated {fmt_az_full(latest.get('generated_at'))}")
        _render_summary(latest)

    st.divider()
    st.markdown("#### Earlier hours")
    try:
        history = client.hourly_summaries(limit=24).get("results", [])
    except Exception as exc:  # noqa: BLE001
        st.error(f"API error: {exc}")
        return

    # Skip the first (already shown as "latest").
    for s in history[1:]:
        with st.expander(
            f"{fmt_az(s.get('window_start'))}–{fmt_az(s.get('window_end'))} · "
            f"{s.get('event_count', 0)} event(s)"
        ):
            _render_summary(s)
