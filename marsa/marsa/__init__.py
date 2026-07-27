"""
MARSA — Maritime Arrivals & Regional Supply Analytics.

A Gulf grain-flow intelligence engine: reconstruct KSA dry-bulk port calls from
AIS, capture berth draughts live, and convert Delta-draught into cargo tonnage.

Package layout:
    config             ports, geofences, classification, constants
    datalastic_client  thin Datalastic API wrapper (async reports + live GETs)
    geofence           great-circle distance + grain-berth inference
    storage            SQLite store, idempotent on (uuid, arrival_date)
    tpc                displacement physics (TPC + indicative tonnage)
    arrivals_pipeline  Phase 1 historical backfill (converged)
    draught_capture    Phase 0 live draught capture (forward-only, start now)
    discover_berths    helper to fill the grain-berth geofences
"""

__version__ = "0.1.0"
