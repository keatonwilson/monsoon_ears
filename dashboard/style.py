"""Color palette + display helpers shared across dashboard tabs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# Arizona doesn't observe DST, so this is a fixed UTC-7 mapping.
AZ_TZ = ZoneInfo("America/Phoenix")


def to_az(iso: str | None) -> Optional[datetime]:
    """Parse an ISO timestamp (assumed UTC if no tz) and convert to AZ time."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(AZ_TZ)


def fmt_az(iso: str | None, format: str = "%H:%M:%S MST") -> str:
    dt = to_az(iso)
    return dt.strftime(format) if dt else "—"


def fmt_az_full(iso: str | None) -> str:
    return fmt_az(iso, format="%Y-%m-%d %H:%M MST")


def az_date_label(iso: str | None) -> str:
    """Group-by-date label in AZ time: 'Today', 'Yesterday', or 'Mon, May 28'."""
    dt = to_az(iso)
    if not dt:
        return "Unknown date"
    today = datetime.now(AZ_TZ).date()
    delta = (today - dt.date()).days
    if delta == 0:
        return f"Today — {dt.strftime('%a, %b %d')}"
    if delta == 1:
        return f"Yesterday — {dt.strftime('%a, %b %d')}"
    return dt.strftime("%a, %b %d, %Y")

TYPE_COLORS = {
    "fire": "#d9534f",          # red
    "ems": "#0275d8",           # blue
    "police": "#5bc0de",        # cyan
    "ham": "#777777",           # gray
    "weather": "#5cb85c",       # green
    "aprs": "#9b59b6",          # purple
    "flood_control": "#f0ad4e", # orange
    "unknown": "#999999",
}

SEVERITY_COLORS = {
    "high": "#d9534f",
    "medium": "#f0ad4e",
    "low": "#5cb85c",
    "unknown": "#999999",
}


def chip(text: str, color: str) -> str:
    """Inline-styled HTML chip — Streamlit renders it via st.markdown(unsafe_allow_html=True)."""
    return (
        f'<span style="background:{color};color:white;padding:2px 8px;'
        f'border-radius:10px;font-size:0.85em;font-weight:500;'
        f'margin-right:4px;">{text}</span>'
    )


def type_chip(t: Optional[str]) -> str:
    if not t:
        return ""
    return chip(t.upper(), TYPE_COLORS.get(t, TYPE_COLORS["unknown"]))


def severity_chip(s: Optional[str]) -> str:
    if not s or s == "unknown":
        return ""
    return chip(s.upper(), SEVERITY_COLORS.get(s, SEVERITY_COLORS["unknown"]))


def folium_color_for_type(t: Optional[str]) -> str:
    """Folium's marker color requires a name, not a hex. Map our palette."""
    mapping = {
        "fire": "red",
        "ems": "blue",
        "police": "lightblue",
        "ham": "gray",
        "weather": "green",
        "aprs": "purple",
        "flood_control": "orange",
        "unknown": "gray",
    }
    return mapping.get(t or "unknown", "gray")
