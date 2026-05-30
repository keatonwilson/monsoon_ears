"""Target frequencies for Monsoon Ears. Source: .claude/plan.md §Target Frequencies.

Analog FM channels are tuned directly by the scanner. The PCWIN P25 system is
decoded by op25 (see deploy/op25_setup.md); op25 locks a control channel and
follows voice grants on the priority talkgroups defined here.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Frequency:
    name: str
    mhz: float
    mode: str  # "nfm" | "p25" | "aprs"
    agency: str
    priority: str  # "primary" | "high" | "medium" | "low"


ANALOG_FM: list[Frequency] = [
    Frequency("Rural Metro Fire Dispatch F1/F2", 154.370, "nfm", "Rural Metro Fire / AMR", "primary"),
    Frequency("Rural Metro EMS Dispatch F3", 153.815, "nfm", "Rural Metro Fire / AMR", "primary"),
    Frequency("NOAA Weather Radio Tucson", 162.3975, "nfm", "NOAA", "primary"),
    Frequency("Rural Metro Fireground F4/F5", 154.400, "nfm", "Rural Metro Fire / AMR", "high"),
    Frequency("Northwest Fire Fireground backup", 154.250, "nfm", "Northwest Fire District", "medium"),
    Frequency("Northwest Fire Backup dispatch", 151.2425, "nfm", "Northwest Fire District", "medium"),
    Frequency("W7MST Tucson Ham Repeater", 146.820, "nfm", "Amateur", "low"),
]

APRS_2M = Frequency("APRS 2m national", 144.390, "aprs", "APRS", "primary")


# --- PCWIN P25 Phase II trunked system (op25) -------------------------------

# Pima County Wireless Integrated Network. Verified via radioreference.com
# (May 2026): System ID 3BB, WACN BEE00. op25 locks one control channel and
# follows voice grants for the talkgroups in PCWIN_TALKGROUPS.


@dataclass(frozen=True)
class Talkgroup:
    dec: int          # decimal talkgroup ID (what op25 reports / trunk.tsv uses)
    name: str
    agency: str
    kind: str         # "fire" | "ems" | "police" | "eoc"
    priority: str     # "primary" | "high" | "medium" | "low"
    encrypted: bool = False  # encrypted talkgroups are excluded from capture

    @property
    def hex(self) -> str:
        return format(self.dec, "x")


@dataclass(frozen=True)
class P25System:
    name: str
    sysid: str
    wacn: str
    control_channels_mhz: list[float]


# Simulcast A (Metro Tucson). 853.625 is the primary control channel.
PCWIN = P25System(
    name="PCWIN Simulcast A (Metro Tucson)",
    sysid="3BB",
    wacn="BEE00",
    control_channels_mhz=[853.625, 853.375, 853.7125, 853.900],
)

# Backwards-compatible alias for code/tests that referenced the bare list.
PCWIN_CONTROL_CHANNELS_MHZ = PCWIN.control_channels_mhz

# Priority talkgroups (.claude/plan.md §Priority Talkgroups). TFD/Rural Metro/
# AMR/VECC run unencrypted (`T`); TPD and Marana PD are AES-encrypted (`TE`) and
# excluded — listed here only so the exclusion is explicit and testable.
PCWIN_TALKGROUPS: list[Talkgroup] = [
    Talkgroup(15001, "TFD A2 — All Dispatches", "Tucson Fire", "fire", "primary"),
    Talkgroup(15000, "TFD A1 — Emergency", "Tucson Fire", "fire", "high"),
    Talkgroup(15002, "TFD A7 — Major Incidents", "Tucson Fire", "fire", "high"),
    Talkgroup(15006, "TFD A3 — North Responses", "Tucson Fire", "fire", "high"),
    Talkgroup(15007, "TFD A4 — South Responses", "Tucson Fire", "fire", "high"),
    Talkgroup(15008, "TFD A5 — East Responses", "Tucson Fire", "fire", "high"),
    Talkgroup(15009, "TFD A6 — West Responses", "Tucson Fire", "fire", "high"),
    Talkgroup(13003, "Rural Metro Fire Dispatch", "Rural Metro Fire", "fire", "high"),
    Talkgroup(13007, "AMR EMS-1 Tucson", "AMR", "ems", "high"),
    Talkgroup(11012, "VECC Valley Fire Dispatch", "VECC", "fire", "medium"),
    Talkgroup(21500, "Pima County EOC 1", "Pima County EOC", "eoc", "high"),
    Talkgroup(21501, "Pima County EOC 2", "Pima County EOC", "eoc", "high"),
    Talkgroup(18009, "PCSO East-1 Dispatch", "Pima County Sheriff", "police", "medium"),
    Talkgroup(18024, "PCSO North-1 Dispatch", "Pima County Sheriff", "police", "medium"),
    Talkgroup(12001, "Fire Back-up Station Alerting", "PCWIN", "fire", "medium"),
    # Encrypted — never decodes; kept for documentation + the exclusion test.
    Talkgroup(1, "TPD (encrypted)", "Tucson Police", "police", "low", encrypted=True),
    Talkgroup(2, "Marana PD (encrypted)", "Marana Police", "police", "low", encrypted=True),
]


def active_talkgroups() -> list[Talkgroup]:
    """Talkgroups we actually capture — unencrypted only."""
    return [tg for tg in PCWIN_TALKGROUPS if not tg.encrypted]


# dec -> "Name (Agency)" hint, used by the classifier as a per-talkgroup prior
# (the P25 analogue of the analog frequency hint).
TALKGROUP_HINTS: dict[int, str] = {
    tg.dec: f"{tg.name} ({tg.agency})" for tg in active_talkgroups()
}

_TALKGROUP_BY_DEC: dict[int, Talkgroup] = {tg.dec: tg for tg in PCWIN_TALKGROUPS}


def talkgroup_label(dec: int | None) -> str | None:
    """Human label for a talkgroup ID, e.g. 'TFD A2 — All Dispatches'. None if
    unknown or not a P25 event."""
    if dec is None:
        return None
    tg = _TALKGROUP_BY_DEC.get(dec)
    return tg.name if tg else None
