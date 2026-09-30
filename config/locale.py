"""Everything that ties this deployment to one place on the map.

If you are standing up Monsoon Ears somewhere other than Tucson, this file is
the first thing to edit — it holds the location scalars that were previously
scattered across agents/context.py, agents/extract.py and several prompts.

The other three files carrying local knowledge are inherently your own data and
can't be reduced to constants:

  config/frequencies.py  analog FM channels + trunked talkgroups (radioreference.com)
  config/gauges.py       USGS / local stream+rain gauge sites (waterservices.usgs.gov)
  config/gazetteer.py    street, wash, place and agency names for transcript repair

Two more location values live in .env because they are consumed by clients that
already read env: NWS_POINT and APRS_IS_FILTER. Keep them in sync with
REGION_CENTER below.

See docs/build-your-own.md for the full walkthrough.
"""

from __future__ import annotations

# Short name of the area, interpolated into agent prompts ("... radio traffic
# in {PLACE_NAME}"). Keep it to something a model will recognise geographically.
PLACE_NAME = "Tucson"

# Longer form used where the prompt wants city + surrounding jurisdiction.
REGION_NAME = "Tucson / Pima County"

# Appended to a bare location string before geocoding, so "Speedway and Kolb"
# resolves locally rather than to a same-named street on another continent.
GEOCODE_QUERY_SUFFIX = "Tucson, AZ"

# Fixed UTC offset for local-time rendering.
# ponytail: a fixed offset, not a tz database lookup — Arizona has no DST, so
# there is nothing to get wrong. If your area observes DST, swap this for
# zoneinfo.ZoneInfo("America/Denver") and adjust local_now() below.
UTC_OFFSET_HOURS = -7

# Approximate center of the coverage area, for reference and for keeping
# NWS_POINT / APRS_IS_FILTER in .env honest.
REGION_CENTER = (32.2, -110.97)

# Bounding box (lat S/N, lon W/E) used to reject implausible geocodes. Generous
# enough to cover the outlying communities the radio traffic mentions, tight
# enough that a globally-ambiguous street name gets thrown out.
REGION_LAT = (31.2, 32.85)
REGION_LON = (-111.65, -110.4)

# The hazard season this deployment cares about, as (month, day) inclusive.
# Here: the NWS North American Monsoon window for southern Arizona. For a
# wildfire deployment this would be your local fire season.
SEASON_START = (6, 15)
SEASON_END = (9, 30)


def in_region(lat: float, lon: float) -> bool:
    """True if a coordinate falls inside the configured bounding box."""
    return REGION_LAT[0] <= lat <= REGION_LAT[1] and REGION_LON[0] <= lon <= REGION_LON[1]


def in_season(month: int, day: int) -> bool:
    """True if a local (month, day) falls inside the hazard season window."""
    return SEASON_START <= (month, day) <= SEASON_END
