# Source Scout proposal — 2026-06-03

Scope: monsoon-relevant Tucson / Pima County sources not yet aggregated. Run as
the research step for the "richer sources" workstream.

## USGS stream gauges (VERIFIED — implemented in this PR)

`scripts/scout_sources.py --json` listed these as **active** real-time IV
stream gauges inside the Tucson bbox that are **not** in `USGS_SITES`. Treated as
ground truth (live `waterservices.usgs.gov`). All four sit on washes the pipeline
already cares about, and one (Cañada del Oro) is a **new wash** with no prior
gauge — a direct gap in flash-flood coverage.

| Site # | Name / wash | Lat,Lon | Why it matters | Source |
|---|---|---|---|---|
| 09482440 | Santa Cruz River at Silverlake Rd | 32.2001, -110.9878 | central-Tucson Santa Cruz reach (ephemeral; upstream of the effluent reaches) | scout_sources.py / USGS |
| 09485450 | Pantano Wash at Broadway Blvd | 32.2208, -110.8289 | denser Pantano coverage at a major mid-city crossing | scout_sources.py / USGS |
| 09486055 | Rillito Creek at La Cholla Blvd | 32.3028, -111.0114 | lower-Rillito reach near the CDO confluence | scout_sources.py / USGS |
| 09486350 | Cañada del Oro below Ina Road | 32.3362, -111.0421 | **new wash** — NW-side flash-flood signal not previously gauged | scout_sources.py / USGS |

Suggested edit — append to `USGS_SITES` in `config/gauges.py` (all non-baseflow;
Silverlake is upstream of the treated-effluent reaches so it runs dry between
storms):
```python
GaugeSite("09482440", "Santa Cruz River at Silverlake Rd", "usgs", "Santa Cruz", 32.2001, -110.9878),
GaugeSite("09485450", "Pantano Wash at Broadway Blvd", "usgs", "Pantano", 32.2208, -110.8289),
GaugeSite("09486055", "Rillito Creek at La Cholla Blvd", "usgs", "Rillito", 32.3028, -111.0114),
GaugeSite("09486350", "Cañada del Oro below Ina Road", "usgs", "Cañada del Oro", 32.3362, -111.0421),
```

## Web / API feeds (VERIFIED endpoint — proposed as a follow-up)

| Feed | Endpoint | Returns | Integration sketch | Source |
|---|---|---|---|---|
| NWS Area Forecast Discussion (Tucson WFO) | `api.weather.gov/products/types/AFD/locations/TWC` → newest `@graph[0].id` → `api.weather.gov/products/{uuid}` (`.productText`) | Forecaster prose: monsoon setup, moisture/PWAT, flash-flood potential | new `ingestion/nws_afd_client.py` (mirrors `nws_client.py`), store latest `productText`, fold a trimmed excerpt into the monsoon-digest prompt + a dashboard caption | weather.gov (KTWC, confirmed 2026-06-03) |

Why it's a strong monsoon signal: the AFD is where forecasters explicitly call
the day's flash-flood threat and monsoon moisture — high-signal context the
digest currently lacks. Endpoint confirmed live (office `KTWC`, productCode
`AFD`, JSON-LD with per-issuance UUIDs). Deferred from this PR only because a
poller + persistence + digest wiring can't be smoke-tested live in this session;
it is ready to implement as the next increment.

## PCWIN talkgroups (proposed as a follow-up — needs DB confirmation)

RadioReference's PCWIN page enumerates more candidate talkgroups (Tucson
Regional Fire Dispatch category, Valley Emergency Communications Center, Pima
County Sheriff). Adding any requires the **decimal ID + agency + encryption
status** per talkgroup, which is behind RadioReference's DB views and not
citable from open search alone. **Not proposed with specific IDs** to honor the
"cite or don't propose" rule. Recommended next step: pull the PCWIN talkgroup
list from a RadioReference account and append unencrypted fire/EMS/EOC/flood IDs
to `PCWIN_TALKGROUPS`, then re-run `scripts/gen_op25_config.py`.

Sources: <https://wiki.radioreference.com/index.php/Pima_County_Wireless_Integrated_Network_(PCWIN)>,
<https://www.radioreference.com/db/tgCat/20153> (Tucson Regional Fire Dispatch),
<https://www.radioreference.com/db/tgCat/20205> (VECC).

## Analog FM channels (no confident new candidates)

No new, citable, monsoon-relevant analog FM channel surfaced beyond what
`ANALOG_FM` already covers (Rural Metro fire/EMS, Northwest Fire, NOAA, a ham
repeater). Additional fire-district fireground channels exist but vary by
incident and are low-signal for flood correlation. Deferred.

## Notes / rejected
- TPD / Marana PD talkgroups — rejected (AES-encrypted, never decode).
- Far-south / Sonoita-basin USGS sites — rejected (out of the Tucson metro bbox).
- Lightning / MesoWest-RAWS / ADOT closures — viable but lower-priority than the
  AFD; left as future scouting once the AFD feed lands.
