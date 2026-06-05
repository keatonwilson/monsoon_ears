"""Streamlit entrypoint for Monsoon Ears.

Run with:
    uv run streamlit run dashboard/app.py
"""

from __future__ import annotations

import os

import streamlit as st

from dashboard.api_client import APIClient, APIClientError
from dashboard.tabs import activity, hourly, live_feed, map_view, monsoon, query, threads

st.set_page_config(
    page_title="Monsoon Ears",
    page_icon="🌧️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _sidebar() -> APIClient:
    st.sidebar.title("🌧️ Monsoon Ears")
    st.sidebar.caption("Listening to Tucson — one transmission at a time.")
    default_url = os.getenv("MONSOON_API_URL", "http://localhost:8000")
    base_url = st.sidebar.text_input("API base URL", value=default_url)
    client = APIClient(base_url=base_url)
    try:
        health = client.health()
        st.sidebar.success(f"API ok — v{health.get('version', '?')}")
    except Exception as exc:  # noqa: BLE001
        st.sidebar.error(f"API unreachable: {exc}")
    st.sidebar.divider()
    st.sidebar.caption(
        "Read-only over the LAN. The events table is mutated only by the "
        "scanner + agent worker on the Pi."
    )
    return client


def main() -> None:
    client = _sidebar()
    tab_objs = st.tabs([
        "🧵 Threads",
        "🕐 Last hour",
        "📡 Raw feed",
        "🗺️ Map",
        "📊 24h activity",
        "🌧️ Monsoon",
        "🔎 Ask",
    ])
    with tab_objs[0]:
        threads.render(client)
    with tab_objs[1]:
        hourly.render(client)
    with tab_objs[2]:
        live_feed.render(client)
    with tab_objs[3]:
        map_view.render(client)
    with tab_objs[4]:
        activity.render(client)
    with tab_objs[5]:
        monsoon.render(client)
    with tab_objs[6]:
        query.render(client)


if __name__ == "__main__":
    main()
