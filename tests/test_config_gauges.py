"""Catalog sanity for config/gauges.py — the 2026-06-03 source-scout additions."""

from config.gauges import (
    USGS_SITES,
    site_is_baseflow,
    site_wash,
    usgs_site_ids,
)

# The four ground-truth gauges scout_sources.py surfaced (active IV sites).
_NEW_SITES = {
    "09482440": "Santa Cruz",
    "09485450": "Pantano",
    "09486055": "Rillito",
    "09486350": "Cañada del Oro",
}


def test_new_gauges_present_with_expected_washes():
    for site_id, wash in _NEW_SITES.items():
        assert site_id in usgs_site_ids(), f"{site_id} missing from catalog"
        assert site_wash(site_id) == wash


def test_canada_del_oro_now_gauged():
    """CDO was a tracked wash with no gauge before this PR — now it has one."""
    cdo_sites = [s for s in USGS_SITES if s.wash == "Cañada del Oro"]
    assert cdo_sites, "Cañada del Oro should now have at least one USGS gauge"


def test_no_duplicate_site_ids():
    ids = usgs_site_ids()
    assert len(ids) == len(set(ids)), "duplicate USGS site ids in the catalog"


def test_new_reaches_are_not_baseflow():
    # All four are ephemeral (Silverlake is upstream of the effluent reaches).
    for site_id in _NEW_SITES:
        assert site_is_baseflow(site_id) is False
