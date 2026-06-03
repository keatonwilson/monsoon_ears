"""Live event feed — auto-refreshing list of recent transmissions."""

from __future__ import annotations

import streamlit as st

from dashboard.api_client import APIClient
from dashboard.style import channel_label, fmt_az, severity_chip, type_chip


def _format_timestamp(iso: str | None) -> str:
    return fmt_az(iso)


# An event with no type / UNKNOWN type and a confidence at or below this is
# treated as noise and hidden unless "Show noise" is on. A real dispatch on a
# known channel scores well above this.
_NOISE_CONFIDENCE = 0.35


def _is_noise_event(row: dict) -> bool:
    ttype = (row.get("transmission_type") or "unknown").lower()
    conf = row.get("confidence")
    return ttype in ("", "unknown") and (conf is None or conf <= _NOISE_CONFIDENCE)


def render(client: APIClient) -> None:
    st.subheader("Recent transmissions")
    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
    limit = col1.slider("Show", min_value=10, max_value=200, value=50, step=10, key="live_feed_limit")
    type_filter = col2.selectbox(
        "Type",
        options=["all", "fire", "ems", "police", "weather", "ham", "flood_control"],
        key="live_feed_type",
    )
    show_noise = col3.toggle("Show noise", value=False, key="live_feed_show_noise",
                             help="Include UNKNOWN, low-confidence transmissions.")
    auto = col4.toggle("Auto-refresh (30s)", value=True, key="live_feed_auto")
    if auto:
        try:
            st.autorefresh = getattr(st, "autorefresh", None) or (lambda *a, **k: None)
            # Streamlit 1.38+ exposes `st.experimental_rerun` via timer plugins.
            # The portable shim: use st_autorefresh from streamlit-extras if present,
            # else fall back to a manual hint.
            from streamlit_autorefresh import st_autorefresh  # type: ignore
            st_autorefresh(interval=30_000, key="live_feed_refresh")
        except Exception:  # noqa: BLE001
            st.caption("Install `streamlit-autorefresh` for hands-free 30 s refresh; use the rerun button meanwhile.")

    params = {"limit": limit}
    if type_filter != "all":
        params["type"] = type_filter
    try:
        data = client.events(**params)
    except Exception as exc:  # noqa: BLE001
        st.error(f"API error: {exc}")
        return

    if data["count"] == 0:
        st.info("No events yet. The scanner + agent worker need to run for a bit.")
        return

    rows = data["results"]
    if not show_noise:
        rows = [r for r in rows if not _is_noise_event(r)]
    hidden = data["count"] - len(rows)
    if hidden:
        st.caption(f"{hidden} low-confidence/unknown event(s) hidden — toggle “Show noise” to see them.")

    for row in rows:
        cols = st.columns([1, 1, 6, 2])
        cols[0].markdown(f"**#{row['id']}**")
        cols[1].caption(_format_timestamp(row["timestamp"]))
        chips = type_chip(row.get("transmission_type")) + severity_chip(row.get("severity"))
        text = row.get("corrected_text") or row["raw_text"]
        cols[2].markdown(f"{chips} {text}", unsafe_allow_html=True)
        cols[3].caption(f"{channel_label(row)} · {row['duration_sec']:.1f}s")
        with st.expander("Details"):
            d = {
                "raw_text": row.get("raw_text") if row.get("corrected_text") else None,
                "locations": row.get("locations"),
                "units": row.get("units"),
                "callsigns": row.get("callsigns"),
                "status_codes": row.get("status_codes"),
                "incident_type": row.get("incident_type"),
                "wash_name": row.get("wash_name"),
                "road_closure": row.get("road_closure"),
                "lat / lon": (row.get("lat"), row.get("lon")),
            }
            st.json({k: v for k, v in d.items() if v})
