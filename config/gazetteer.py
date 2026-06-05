"""Curated Tucson / Pima County gazetteer for LLM transcript correction.

Whisper garbles proper nouns it has never heard on noisy FM: "Speedway" comes
out "speed way" or "speedwait", "Tanque Verde" as "tank a verde", "Ina" as
"eena". We cannot fix this at the Whisper decode layer — seeding an
``initial_prompt`` with this vocabulary leaks it back as fake transmissions
(see ``ingestion/transcribe.py`` and memory ``whisper-initial-prompt-leak``).

Instead we hand the known local vocabulary to the *extraction* LLM, which
already runs once per event, and ask it to repair garbled proper nouns against
this list (``corrected_text``). No new API call.

The block is also deliberately large (well past Haiku's ~2048-token cacheable
prefix floor) so it can ride in a ``cache_control``'d system block that is
byte-identical across every extract call — see ``agents/extract.py``. That keeps
the per-call cost of carrying all this context near zero during active traffic.
"""

from __future__ import annotations

# Named washes that carry flood flow — the monsoon signal. Canonical home for
# the list; ``agents/extract.py`` re-exports it for its geocoding regex.
TUCSON_WASHES = (
    "Rillito", "Pantano", "Santa Cruz", "Tanque Verde", "Sabino",
    "Cañada del Oro", "Brawley", "Julian", "Agua Caliente", "Ventana",
    "Arroyo Chico", "Alamo", "Big Wash", "Rodeo", "Airport",
)

# Major arterials and well-known roads. Whisper mangles these constantly, so a
# rich list gives the corrector strong anchors. Grouped loosely E-W / N-S.
TUCSON_ARTERIALS = (
    # East-west
    "Speedway", "Broadway", "Grant", "22nd Street", "Ina", "Orange Grove",
    "River", "Sunrise", "Skyline", "Golf Links", "Irvington", "Valencia",
    "Ajo Way", "Drexel", "Los Reales", "Fort Lowell", "Prince", "Roger",
    "Magee", "Tangerine", "Lambert", "Pima Street", "Glenn",
    # North-south
    "Oracle", "Campbell", "Country Club", "Alvernon", "Swan", "Craycroft",
    "Wilmot", "Kolb", "Pantano", "Houghton", "Harrison", "Sabino Canyon",
    "Tanque Verde", "Stone", "First Avenue", "La Cholla", "La Canada",
    "Thornydale", "Shannon", "Silverbell", "Mission", "Park Avenue",
    "Euclid", "Palo Verde", "Old Spanish Trail", "Cortaro Farms",
)

# Highways and interstates common in traffic/closure traffic.
TUCSON_HIGHWAYS = (
    "I-10", "I-19", "Aviation Parkway", "Barraza-Aviation", "SR-77",
    "Oracle Road", "Houghton Road", "SR-86", "Ajo Highway", "Gates Pass",
    "Catalina Highway", "Mount Lemmon Highway",
)

# Neighborhoods, districts, and landmarks that show up as locations.
TUCSON_PLACES = (
    "Downtown", "University of Arizona", "Sam Hughes", "Armory Park",
    "Barrio Viejo", "Menlo Park", "Catalina Foothills", "Foothills",
    "Oro Valley", "Marana", "Vail", "Sahuarita", "Green Valley", "Tucson Estates",
    "Flowing Wells", "Casas Adobes", "Tanque Verde Valley", "Rita Ranch",
    "Civano", "Midvale Park", "Drexel Heights", "Littletown", "Tucson Mall",
    "El Con", "Park Place", "Reid Park", "Saguaro National Park",
    "Tucson International Airport", "Davis-Monthan", "Pima Community College",
    "Banner UMC", "Tucson Medical Center", "St. Joseph's", "Northwest Medical",
)

# Public-safety agencies and dispatch entities heard on the air.
TUCSON_AGENCIES = (
    "Tucson Fire", "TFD", "Tucson Police", "TPD", "Rural Metro",
    "Northwest Fire", "Golder Ranch Fire", "Drexel Heights Fire",
    "Three Points Fire", "Avra Valley Fire", "Mount Lemmon Fire",
    "Pima County Sheriff", "PCSD", "Oro Valley Police", "Marana Police",
    "Sahuarita Police", "University of Arizona Police", "AMR", "Southwest Ambulance",
    "Pima County DOT", "Pima Flood Control", "Regional Flood Control District",
    "Department of Public Safety", "DPS", "Border Patrol", "Air Methods",
    "VECC", "Pima County Emergency Operations Center",
)

# Common dispatch shorthand the model should recognize as codes, not words.
DISPATCH_CODES_HINT = (
    "code 2 (no lights/sirens), code 3 (lights/sirens), TC (traffic collision), "
    "MVA (motor vehicle accident), MVC (motor vehicle crash), 10-50 (accident), "
    "10-52 (ambulance needed), MCI (mass casualty incident), signal 4 (collision), "
    "PD (police), FD (fire), full arrest (cardiac arrest), structure (structure fire), "
    "still alarm, working fire, water rescue, swift water"
)


def _bullet_list(label: str, items: tuple[str, ...]) -> str:
    return f"{label}: " + ", ".join(items)


def gazetteer_reference() -> str:
    """The Tucson reference block injected into the extract system prompt.

    Kept stable (no per-call data) so the whole system block caches.
    """
    return "\n".join(
        [
            "Tucson / Pima County local reference — use it to repair garbled "
            "proper nouns in transcripts (Whisper mangles unfamiliar local "
            "names from noisy FM):",
            _bullet_list("Major streets/arterials", TUCSON_ARTERIALS),
            _bullet_list("Highways", TUCSON_HIGHWAYS),
            _bullet_list("Named flood washes", TUCSON_WASHES),
            _bullet_list("Neighborhoods / landmarks", TUCSON_PLACES),
            _bullet_list("Agencies", TUCSON_AGENCIES),
            f"Dispatch shorthand: {DISPATCH_CODES_HINT}",
        ]
    )
