"""
Geospatial helpers — great-circle distance and grain-berth inference.

Kept dependency-free (pure math) so it can be unit-tested without a network or
any AIS data, and reused by both the historical pipeline and the live capture.
"""

from __future__ import annotations

import math

EARTH_RADIUS_NM = 3440.065


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles between two lat/lon points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(a))


def nearest_berth(lat: float, lon: float, berths: list[dict]):
    """(distance_nm, berth) for the closest configured berth, or (None, None)."""
    best = None
    for b in berths:
        d = haversine_nm(lat, lon, b["lat"], b["lon"])
        if best is None or d < best[0]:
            best = (d, b)
    return best if best else (None, None)


def infer_grain(port: dict, points) -> tuple[str, str]:
    """
    Classify a call as grain / non-grain from how close the vessel came to a
    configured grain berth. ``points`` is an iterable of (lat, lon) pairs
    sampled over the call.

    Returns (flag, confidence). With no geofences configured the honest answer
    is "Unknown" at Low confidence — never a silent Non-grain.
    """
    berths = port.get("grain_berths") or []
    if not berths:
        return ("Unknown (no grain-berth configured)", "Low")

    best_dist = None
    best_berth = None
    for lat, lon in points:
        d, b = nearest_berth(lat, lon, berths)
        if d is not None and (best_dist is None or d < best_dist):
            best_dist, best_berth = d, b
    if best_dist is None:
        return ("Unknown (no positions)", "Low")

    radius = best_berth.get("radius_nm", 0.8)
    if best_dist <= radius:
        conf = "High" if best_dist <= radius / 2 else "Med"
        return ("Grain (est.)", conf)
    return ("Non-grain (est.)", "Med")
