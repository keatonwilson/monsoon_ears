"""PCWIN talkgroup catalog + generated op25 config stay well-formed and in sync."""

import importlib.util
from pathlib import Path

from config.frequencies import (
    PCWIN,
    PCWIN_TALKGROUPS,
    TALKGROUP_HINTS,
    active_talkgroups,
    talkgroup_label,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OP25_DIR = _REPO_ROOT / "config" / "op25"


def _load_generator():
    """Load scripts/gen_op25_config.py by path (scripts/ isn't a package)."""
    path = _REPO_ROOT / "scripts" / "gen_op25_config.py"
    spec = importlib.util.spec_from_file_location("gen_op25_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- catalog ----------------------------------------------------------------


def test_talkgroup_ids_are_unique():
    decs = [tg.dec for tg in PCWIN_TALKGROUPS]
    assert len(decs) == len(set(decs))


def test_encrypted_talkgroups_excluded_from_active_set():
    assert any(tg.encrypted for tg in PCWIN_TALKGROUPS), "expected some encrypted TGs in the catalog"
    assert all(not tg.encrypted for tg in active_talkgroups())
    # Encrypted TGs must not leak into the classifier hints either.
    encrypted_decs = {tg.dec for tg in PCWIN_TALKGROUPS if tg.encrypted}
    assert encrypted_decs.isdisjoint(TALKGROUP_HINTS)


def test_tfd_dispatch_is_primary_and_labeled():
    assert talkgroup_label(15001) == "TFD A2 — All Dispatches"
    tfd = next(tg for tg in PCWIN_TALKGROUPS if tg.dec == 15001)
    assert tfd.priority == "primary"
    assert tfd.hex == "3a99"  # matches the radioreference HEX


def test_unknown_talkgroup_label_is_none():
    assert talkgroup_label(99999) is None
    assert talkgroup_label(None) is None


# --- generated op25 config sync ---------------------------------------------


def test_committed_op25_files_match_generator():
    """The committed config/op25/* must equal a fresh generation — i.e. nobody
    hand-edited them or forgot to re-run gen_op25_config.py."""
    gen = _load_generator()
    for name, expected in gen.generate().items():
        committed = (_OP25_DIR / name).read_text()
        assert committed == expected, f"{name} is stale — run scripts/gen_op25_config.py"


def test_whitelist_contains_only_active_talkgroups():
    whitelist = (_OP25_DIR / "whitelist.tsv").read_text()
    listed = {int(line) for line in whitelist.splitlines() if line and not line.startswith("#")}
    assert listed == {tg.dec for tg in active_talkgroups()}


def test_trunk_tsv_control_channels_and_auto_nac():
    trunk = (_OP25_DIR / "trunk.tsv").read_text()
    assert "853.7125" in trunk  # full-precision control channel, not truncated
    # NAC column must be 0 (auto-detect). NAC is per-channel and independent of
    # the SYSID — op25 learns SYSID/WACN from the control channel, so the SYSID
    # must NOT be hardcoded into the NAC slot (that bug rejected every frame).
    data_row = [ln for ln in trunk.splitlines() if ln.startswith(PCWIN.name)][0]
    nac_col = data_row.split("\t")[3]
    assert nac_col == "0", f"NAC column should be auto (0), got {nac_col!r}"
    assert PCWIN.sysid not in trunk
