"""Threads tab — clustered conversations with auto-generated summaries."""

from __future__ import annotations

import streamlit as st

from dashboard.api_client import APIClient, APIClientError
from dashboard.style import (
    az_date_label,
    channel_label,
    fmt_az,
    fmt_az_full,
    severity_chip,
    source_chip,
    type_chip,
)


def _thread_header(t: dict) -> str:
    src_part = source_chip(t.get("source"))
    type_part = type_chip(t.get("transmission_type"))
    sev_part = severity_chip(t.get("severity"))
    incident = t.get("incident_type") or "—"
    start = fmt_az(t.get("start_timestamp"))
    end = fmt_az(t.get("end_timestamp"))
    date_part = fmt_az_full(t.get("start_timestamp"))
    return (
        f"{src_part}{type_part}{sev_part} "
        f"<b>{incident}</b> · {channel_label(t)} · "
        f"{t['event_count']} event(s) · {start}–{end}"
        f"<br><span style='color:#888;font-size:0.85em;'>{date_part}</span>"
    )


def _render_thread(client: APIClient, t: dict) -> None:
    with st.container(border=True):
        st.markdown(_thread_header(t), unsafe_allow_html=True)

        if t.get("summary"):
            st.markdown(f"💬 {t['summary']}")
        elif t.get("closed"):
            st.caption("Closed thread — summary pending on next worker cycle.")
        else:
            st.caption("Live thread — summary will be generated once it goes idle.")

        meta_cols = st.columns(3)
        if t.get("locations"):
            meta_cols[0].caption(f"📍 {', '.join(t['locations'])}")
        if t.get("units"):
            meta_cols[1].caption(f"🚒 {', '.join(t['units'])}")
        if t.get("summarized_at"):
            meta_cols[2].caption(f"Summarized {fmt_az_full(t['summarized_at'])}")

        btn_col, _ = st.columns([1, 5])
        if btn_col.button(
            "🔁 Re-summarize",
            key=f"resum-{t['id']}",
            help="Force the summary agent to re-read this thread now.",
        ):
            try:
                with st.spinner("Asking Haiku…"):
                    client.resummarize_thread(t["id"])
            except APIClientError as exc:
                st.error(f"Summarize failed: {exc}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"API error: {exc}")
            st.rerun()

        with st.expander(f"Raw fragments ({t['event_count']})"):
            try:
                detail = client.thread(t["id"])
            except Exception as exc:  # noqa: BLE001
                st.error(f"API error: {exc}")
                return
            for ev in detail.get("events", []):
                text = ev.get("corrected_text") or ev["raw_text"]
                st.write(
                    f"`{fmt_az(ev['timestamp'])}` "
                    f"[{channel_label(ev)}] "
                    f"({ev['duration_sec']:.1f}s) — {text}"
                )


def render(client: APIClient) -> None:
    st.subheader("Recent conversations")
    st.caption(
        "Same-frequency transmissions within 90s of each other are stitched "
        "into a thread and summarized by Haiku 4.5 once the channel goes idle."
    )

    col1, col2, col3 = st.columns([1, 1, 1])
    minutes = col1.slider("Window (min)", 30, 24 * 60, 60 * 24, step=30, key="threads_window")
    show_noise = col2.toggle("Show noise", value=False, key="threads_show_noise",
                             help="Include threads the summarizer judged unintelligible.")
    auto = col3.toggle("Auto-refresh (30s)", value=True, key="threads_auto")

    if auto:
        try:
            from streamlit_autorefresh import st_autorefresh  # type: ignore
            st_autorefresh(interval=30_000, key="threads_refresh")
        except Exception:  # noqa: BLE001
            pass

    try:
        data = client.threads(since_minutes=minutes, limit=100)
    except Exception as exc:  # noqa: BLE001
        st.error(f"API error: {exc}")
        return

    if data["count"] == 0:
        st.info("No threads yet. The scanner + worker need to run for a bit.")
        return

    results = data["results"]
    if not show_noise:
        results = [t for t in results if not t.get("is_noise")]
    hidden = data["count"] - len(results)

    caption = f"{len(results)} thread(s)"
    if hidden:
        caption += f" · {hidden} noise hidden"
    st.caption(caption)
    if not results:
        st.info("All recent threads were noise. Toggle “Show noise” to see them.")
        return

    current_date: str | None = None
    for t in results:
        label = az_date_label(t.get("start_timestamp"))
        if label != current_date:
            st.markdown(f"### {label}")
            current_date = label
        _render_thread(client, t)
