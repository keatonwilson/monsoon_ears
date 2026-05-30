"""Folium map: incident pins, APRS station markers, Pima wash overlay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import folium
import streamlit as st
from streamlit_folium import st_folium

from dashboard.api_client import APIClient
from dashboard.style import folium_color_for_type

TUCSON_CENTER = (32.22, -110.97)
WASH_GEOJSON_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "washes.geojson"


@st.cache_data(ttl=24 * 3600)
def _load_washes() -> Optional[dict]:
    if not WASH_GEOJSON_PATH.exists():
        return None
    return json.loads(WASH_GEOJSON_PATH.read_text())


def render(client: APIClient) -> None:
    st.subheader("Map view")
    col1, col2, col3 = st.columns([1, 1, 2])
    minutes = col1.slider("Events from last (min)", 15, 24 * 60, 60 * 6, step=15, key="map_minutes")
    aprs_minutes = col2.slider("APRS from last (min)", 5, 6 * 60, 30, step=5, key="map_aprs_minutes")
    show_aprs = col3.toggle("APRS station markers", value=True, key="map_show_aprs")
    show_washes = col3.toggle("Pima County wash overlay", value=True, key="map_show_washes")

    try:
        events = client.events(since_minutes=minutes, limit=500)["results"]
        aprs = client.aprs(minutes=aprs_minutes, limit=300)["results"] if show_aprs else []
    except Exception as exc:  # noqa: BLE001
        st.error(f"API error: {exc}")
        return

    fmap = folium.Map(location=TUCSON_CENTER, zoom_start=11, tiles="cartodbpositron")

    # Wash GeoJSON overlay.
    if show_washes:
        washes = _load_washes()
        if washes:
            folium.GeoJson(
                washes,
                name="Pima County washes",
                style_function=lambda _f: {
                    "color": "#1e6091", "weight": 2, "opacity": 0.6,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=[k for k in (washes["features"][0]["properties"].keys()) if "NAME" in k.upper()][:1] or [],
                ),
            ).add_to(fmap)
        else:
            st.caption("Wash GeoJSON not found at data/washes.geojson — run scripts/fetch_washes.py.")

    # Voice events with lat/lon.
    incident_layer = folium.FeatureGroup(name="Voice incidents").add_to(fmap)
    plotted_incidents = 0
    for row in events:
        if row.get("lat") is None or row.get("lon") is None:
            continue
        color = folium_color_for_type(row.get("transmission_type"))
        popup_lines = [
            f"<b>#{row['id']}</b> · {row['transmission_type'] or 'unknown'}",
            f"<i>{row['frequency_mhz']:.4f} MHz</i>",
            row.get("raw_text", "")[:200],
        ]
        if row.get("units"):
            popup_lines.append(f"units: {', '.join(row['units'])}")
        if row.get("severity") and row["severity"] != "unknown":
            popup_lines.append(f"severity: <b>{row['severity']}</b>")
        folium.Marker(
            location=(row["lat"], row["lon"]),
            popup=folium.Popup("<br>".join(popup_lines), max_width=320),
            icon=folium.Icon(color=color, icon="info-sign"),
        ).add_to(incident_layer)
        plotted_incidents += 1

    # APRS stations with lat/lon.
    aprs_layer = folium.FeatureGroup(name="APRS stations").add_to(fmap) if show_aprs else None
    plotted_aprs = 0
    if aprs_layer is not None:
        for row in aprs:
            if row.get("lat") is None or row.get("lon") is None:
                continue
            tooltip_bits = [row["callsign"]]
            if row.get("temp_f") is not None:
                tooltip_bits.append(f"{row['temp_f']:.0f}°F")
            if row.get("rainfall_in") is not None:
                tooltip_bits.append(f"rain {row['rainfall_in']:.2f}in")
            if row.get("wind_mph") is not None:
                tooltip_bits.append(f"wind {row['wind_mph']:.0f}mph")
            folium.CircleMarker(
                location=(row["lat"], row["lon"]),
                radius=5, color="#5cb85c", fill=True, fill_opacity=0.7,
                tooltip=" · ".join(tooltip_bits),
            ).add_to(aprs_layer)
            plotted_aprs += 1

    folium.LayerControl(collapsed=False).add_to(fmap)

    st.caption(
        f"{plotted_incidents} voice incident(s) + "
        f"{plotted_aprs} APRS station(s) on map · "
        f"{len(events) - plotted_incidents} event(s) skipped (no geolocation yet)"
    )
    st_folium(fmap, height=650, use_container_width=True, returned_objects=[])
