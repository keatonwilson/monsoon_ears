"""Guards on the location scalars a fork has to edit — the two helpers here are
the ones whose failure is silent (bad geocodes accepted, season always off)."""

from config.locale import (
    REGION_CENTER,
    REGION_LAT,
    REGION_LON,
    SEASON_END,
    SEASON_START,
    in_region,
    in_season,
)


def test_region_center_inside_its_own_bbox():
    # A fork that edits the bbox but forgets REGION_CENTER (or vice versa) has
    # an inconsistent locale — NWS_POINT / APRS_IS_FILTER would point elsewhere.
    assert in_region(*REGION_CENTER)


def test_bbox_bounds_are_ordered():
    assert REGION_LAT[0] < REGION_LAT[1]
    assert REGION_LON[0] < REGION_LON[1]


def test_in_region_rejects_out_of_area():
    # The real failure this catches: a bare street name geocoding to another
    # continent (we saw a -41 latitude in the wild).
    assert not in_region(-41.0, 174.0)
    assert not in_region(REGION_LAT[1] + 1.0, REGION_CENTER[1])


def test_in_season_covers_window_edges():
    assert in_season(*SEASON_START)
    assert in_season(*SEASON_END)
    assert not in_season(SEASON_START[0], SEASON_START[1] - 1)
    assert not in_season(SEASON_END[0], SEASON_END[1] + 1)


def test_in_season_excludes_off_season():
    assert not in_season(1, 15)
