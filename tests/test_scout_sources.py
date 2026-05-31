"""scripts/scout_sources.py — pure RDB parsing + catalog diff (no network)."""

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    """Load scripts/scout_sources.py by path (scripts/ isn't a package)."""
    path = _REPO_ROOT / "scripts" / "scout_sources.py"
    spec = importlib.util.spec_from_file_location("scout_sources", path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the module's frozen dataclasses can resolve their
    # __module__ in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# A realistic USGS site-service RDB response: comment block, header, format row,
# then two data rows. One site (09485700) is already in config/gauges.py; the
# other (09484550) is new.
_RDB = """\
# US Geological Survey
# retrieved: 2026-05-31
#
agency_cd\tsite_no\tstation_nm\tdec_lat_va\tdec_long_va\tsite_tp_cd
5s\t15s\t50s\t16n\t16n\t7s
USGS\t09485700\tRILLITO CREEK AT DODGE BLVD\t32.2710\t-110.9150\tST
USGS\t09484550\tCANADA DEL ORO NEAR TUCSON\t32.4180\t-110.9900\tST
"""


def test_parse_site_rdb_skips_comments_and_format_row():
    scout = _load()
    sites = scout.parse_site_rdb(_RDB)
    ids = [s.site_id for s in sites]
    assert ids == ["09485700", "09484550"]
    cdo = sites[1]
    assert "CANADA DEL ORO" in cdo.name
    assert cdo.lat == 32.418
    assert cdo.lon == -110.99


def test_new_candidates_excludes_known_and_dedupes():
    scout = _load()
    sites = scout.parse_site_rdb(_RDB)
    # Pretend Rillito is already catalogued.
    new = scout.new_candidates(sites + sites, known_ids={"09485700"})
    assert [s.site_id for s in new] == ["09484550"]  # known dropped, dup dropped


def test_parse_handles_missing_coords():
    scout = _load()
    rdb = (
        "agency_cd\tsite_no\tstation_nm\tdec_lat_va\tdec_long_va\n"
        "5s\t15s\t50s\t16n\t16n\n"
        "USGS\t09999999\tSOME WASH\t\t\n"
    )
    sites = scout.parse_site_rdb(rdb)
    assert sites[0].site_id == "09999999"
    assert sites[0].lat is None and sites[0].lon is None
