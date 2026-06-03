"""Stream/rain gauge catalog feeding the monsoon correlation digest.

USGS Water Services (instantaneous values) is the stable backbone — documented
JSON, no auth. The Pima County RFCD ALERT network is an optional best-effort
source (no documented API). Sites are tied to the named Tucson washes the
pipeline already tracks (see TUCSON_WASHES in agents/extract.py).

USGS site IDs verified live against waterservices.usgs.gov (May 2026).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GaugeSite:
    site_id: str
    name: str
    source: str   # "usgs" | "pima_alert"
    wash: str     # the named wash/watercourse this gauge sits on
    lat: float
    lon: float
    # Some reaches carry perennial flow (e.g. treated-effluent discharge), so a
    # nonzero discharge there is NORMAL, not a flood. For these, only a clearly
    # rising stage/discharge trend is a flood signal — see agents/alert.py.
    baseflow: bool = False


# Tucson-metro USGS streamgages on the washes the project tracks. (Barrel
# Canyon / Sonoita and other far-south sites are intentionally excluded.)
USGS_SITES: list[GaugeSite] = [
    GaugeSite("09482500", "Santa Cruz River at Tucson", "usgs", "Santa Cruz", 32.221, -110.982),
    # Cortaro sits below the metro wastewater plants and runs ~tens of cfs of
    # treated effluent year-round, so steady nonzero flow here is not a flood.
    GaugeSite("09486500", "Santa Cruz River at Cortaro", "usgs", "Santa Cruz", 32.351, -111.096, baseflow=True),
    GaugeSite("09482000", "Santa Cruz River at Continental", "usgs", "Santa Cruz", 31.872, -110.980),
    GaugeSite("09484000", "Sabino Creek near Tucson", "usgs", "Sabino", 32.315, -110.811),
    GaugeSite("09484500", "Tanque Verde Creek at Tucson", "usgs", "Tanque Verde", 32.264, -110.841),
    GaugeSite("09485700", "Rillito Creek at Dodge Blvd", "usgs", "Rillito", 32.271, -110.915),
    GaugeSite("09484600", "Pantano Wash near Vail", "usgs", "Pantano", 32.036, -110.678),
    GaugeSite("09485000", "Rincon Creek near Tucson", "usgs", "Rincon", 32.130, -110.626),
    # Added 2026-06-03 (scout_sources.py): four active IV gauges that densify
    # coverage on tracked washes and add Cañada del Oro (NW-side, previously
    # ungauged). All ephemeral — Silverlake is upstream of the effluent reaches.
    GaugeSite("09482440", "Santa Cruz River at Silverlake Rd", "usgs", "Santa Cruz", 32.2001, -110.9878),
    GaugeSite("09485450", "Pantano Wash at Broadway Blvd", "usgs", "Pantano", 32.2208, -110.8289),
    GaugeSite("09486055", "Rillito Creek at La Cholla Blvd", "usgs", "Rillito", 32.3028, -111.0114),
    GaugeSite("09486350", "Cañada del Oro below Ina Road", "usgs", "Cañada del Oro", 32.3362, -111.0421),
]

# Best-effort; populated only if a usable ALERT endpoint is found (see
# ingestion/pima_alert_client.py). Cañada del Oro has no USGS gauge and would
# live here.
PIMA_ALERT_SITES: list[GaugeSite] = []


def usgs_site_ids() -> list[str]:
    return [s.site_id for s in USGS_SITES]


_SITE_BY_ID: dict[str, GaugeSite] = {s.site_id: s for s in USGS_SITES + PIMA_ALERT_SITES}


def site_wash(site_id: str) -> str | None:
    """The named wash a gauge sits on, for the digest prompt / dashboard."""
    site = _SITE_BY_ID.get(site_id)
    return site.wash if site else None


def site_is_baseflow(site_id: str) -> bool:
    """True if this gauge carries perennial baseflow (nonzero flow is normal)."""
    site = _SITE_BY_ID.get(site_id)
    return bool(site and site.baseflow)
