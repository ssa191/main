"""
MARSA configuration — ports, geofences, classification thresholds, constants.

Single source of truth for everything the two divergent copies of
``arrivals_pipeline.py`` used to define inline. Import from here; do not
re-declare ports or thresholds anywhere else.

GRAIN BERTHS (read this before trusting the grain flag)
-------------------------------------------------------
AIS carries no cargo field. A call is inferred "grain" only when the vessel
passed within a configured grain-berth geofence. Those geofences START EMPTY:
until you fill ``grain_berths`` per port, every call reads
"Unknown (no grain-berth configured)" — which is exactly the state the current
``ksa_arrivals.csv`` is in.

Filling them is Phase 0 work and nothing downstream (tonnage by commodity,
the nowcast) works without it. Two ways to fill them, in order of preference:

  1. ``python -m marsa.discover_berths --ports mine`` — pulls each port's
     ``terminals[]`` from Datalastic so you can see candidate berth positions.
  2. Satellite / port-authority berth plans for the SAGO silo quays, entered
     as {name, lat, lon, radius_nm} dicts below.

Do NOT guess coordinates. A wrong geofence produces confident-but-false grain
flags, which is worse than an honest "Unknown".
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Ports — the major KSA cargo ports. Coordinates verified live via Datalastic.
#   scan_radius_nm : area pulled by the history report (<= 50). Keep tight
#                    where ports are close together (the Yanbu pair are ~13 NM
#                    apart) to avoid one port's scan swallowing the other's.
#   port_radius_nm : how close a ship must come to count this as a real call.
#   grain_berths   : geofences for grain-silo quays. EMPTY until you fill them
#                    (see module docstring). Each entry:
#                    {"name": str, "lat": float, "lon": float, "radius_nm": float}
# ---------------------------------------------------------------------------

PORTS: dict[str, dict] = {
    "jeddah": {
        "label": "Jeddah Islamic Port", "unlocode": "SAJED",
        "uuid": "b347dce9-5318-a3c9-7580-a867630778b0",
        "lat": 21.48182, "lon": 39.14713,
        "scan_radius_nm": 15, "port_radius_nm": 7, "grain_berths": [],
    },
    "kap": {
        "label": "King Abdullah Port", "unlocode": "SAKAC",
        "uuid": "42e916b2-366d-a531-370c-72e163ad2ee1",
        "lat": 22.52477, "lon": 39.09416,
        "scan_radius_nm": 12, "port_radius_nm": 6, "grain_berths": [],
    },
    "yanbu_cml": {
        "label": "Yanbu Commercial Port", "unlocode": "SAYNB",
        "uuid": "8f5f5fb1-7562-e5b2-b7dd-ce582e339181",
        "lat": 24.0665, "lon": 38.0675,
        "scan_radius_nm": 8, "port_radius_nm": 5, "grain_berths": [],
    },
    "yanbu_ind": {
        "label": "Yanbu Industrial Port", "unlocode": "SAYBI",
        "uuid": "589e0476-f3dc-4698-0d07-9efe70d66184",
        "lat": 23.949, "lon": 38.2375,
        "scan_radius_nm": 8, "port_radius_nm": 5, "grain_berths": [],
    },
    "jubail": {
        "label": "Jubail Port", "unlocode": "SAJUB",
        "lat": 27.035, "lon": 49.6795,
        "scan_radius_nm": 15, "port_radius_nm": 7, "grain_berths": [],
    },
    "dammam": {
        "label": "Dammam (King Abdulaziz Port)", "unlocode": "SADMM",
        "uuid": "7f78df2b-a529-641f-7f57-77e90d261181",
        "lat": 26.441, "lon": 50.1485,
        "scan_radius_nm": 15, "port_radius_nm": 7, "grain_berths": [],
    },
    "ras_al_khair": {
        "label": "Ras Al Khair", "unlocode": "SARAZ",
        "lat": 27.55828, "lon": 49.18322,
        "scan_radius_nm": 12, "port_radius_nm": 6, "grain_berths": [],
    },
    "jazan": {
        "label": "Jazan Port", "unlocode": "SAGIZ",
        "uuid": "d587e71d-0d52-a1ae-fc97-bf9fa1d36e0a",
        "lat": 16.91887, "lon": 42.55726,
        "scan_radius_nm": 12, "port_radius_nm": 6, "grain_berths": [],
    },
}

# The six grain-relevant ports (pass to --ports, or --ports mine).
MY_PORTS = "kap,jeddah,dammam,yanbu_cml,yanbu_ind,jazan"

# ---------------------------------------------------------------------------
# Vessel classification
# ---------------------------------------------------------------------------

DRY_BULK_SUBTYPES = ["bulk carrier", "bulker", "cement", "aggregates", "ore",
                     "obo", "cabu", "general cargo"]
EXCLUDE_SUBTYPES = ["container", "tanker", "reefer", "vehicle", "ro-ro",
                    "lng", "lpg"]

# For the live sweep: Datalastic vessel_inradius `type` filter values that keep
# the credit spend down by excluding obviously-irrelevant classes at the API.
INRADIUS_EXCLUDE = "Tanker,Passenger,Tug,Fishing,Pleasure Craft"


def size_class(dwt) -> str:
    """Bulk-carrier size band from deadweight tonnes."""
    try:
        d = float(dwt)
    except (ValueError, TypeError):
        return ""
    if d < 10000:
        return "Mini-bulk"
    if d < 40000:
        return "Handysize"
    if d < 65000:
        return "Handymax/Supramax/Ultramax"
    if d < 100000:
        return "Panamax/Kamsarmax"
    if d < 200000:
        return "Capesize"
    return "VLOC"


def is_dry_bulk(subtype, vtype) -> bool:
    s = f"{subtype or ''} {vtype or ''}".lower()
    if any(x in s for x in EXCLUDE_SUBTYPES):
        return False
    return any(x in s for x in DRY_BULK_SUBTYPES)


# ---------------------------------------------------------------------------
# History-backfill constants (async inradius_history report lifecycle)
# ---------------------------------------------------------------------------

DATA_START = "2021-08-10"   # earliest Datalastic history
WINDOW_DAYS = 7             # inradius_history hard cap per report
VISIT_GAP_HRS = 72          # absence that ends a port call (AIS pings sparsely)
ANCHOR_SPEED_KN = 1.0
POLL_SECONDS = 15
BATCH_SIZE = 10             # reports submitted before we start polling
REPORT_TIMEOUT = 3600
REPORT_CREDITS = 100        # measured: balance drops ~1,000 per 10-report batch

# ---------------------------------------------------------------------------
# Output locations
# ---------------------------------------------------------------------------

DB_PATH = "out/marsa.db"          # SQLite store, keyed (uuid, arrival_date)
CSV_PATH = "out/ksa_arrivals.csv"
RAW_DIR = "out/raw"               # cached report ZIPs (re-runs skip them)

# Columns for the flat CSV/XLSX export (order matters for humans reading it).
FIELDS = ["port", "vessel_name", "mmsi", "imo", "type_specific", "size_class",
          "dwt", "gross_tonnage", "length_m", "breadth_m", "year_built",
          "arrival_utc", "departure_utc", "days_in_port", "arrived_anchored",
          "grain_flag", "grain_confidence", "_min_dist_nm", "uuid"]
