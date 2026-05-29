"""Target frequencies for Monsoon Ears. Source: .claude/plan.md §Target Frequencies."""

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

# PCWIN Simulcast A control channels (Phase 01.5 / op25).
PCWIN_CONTROL_CHANNELS_MHZ = [853.375, 853.625, 853.7125, 853.900]
