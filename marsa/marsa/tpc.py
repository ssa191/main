"""
Displacement physics — tonnes-per-centimetre and a draught->tonnage estimate.

This is the seed of the Phase 2 tonnage engine, exposed early because it makes
the Phase 0 draught captures immediately interpretable: given a stored hull's
dimensions and a Delta-draught, you get an *indicative* discharged tonnage the
moment the ship leaves the berth.

IMPORTANT — indicative, not calibrated.
    tonnes ~= Delta_draught_cm * TPC
This ignores the two systematic biases the brief calls out: Red Sea / Gulf
water is denser than the 1.025 standard, and ships change trim during
discharge. Both are calibratable against GASTAT customs data once published;
until that calibration exists, treat every number here as an UPPER-BOUND-ish
estimate with wide error bars, never a published figure.
"""

from __future__ import annotations

from typing import Optional

# Standard seawater density (t/m^3). The Red Sea and Arabian Gulf run denser
# (~1.027-1.029); that correction is deferred to the calibration loop.
SEAWATER_DENSITY = 1.025

# Waterplane-area coefficient for modern bulk carriers. Sits ~0.80-0.88; 0.84
# is a reasonable default until per-class values are fitted.
DEFAULT_CWP = 0.84


def tpc(length_m: float, breadth_m: float,
        c_wp: float = DEFAULT_CWP,
        density: float = SEAWATER_DENSITY) -> Optional[float]:
    """
    Tonnes per centimetre of immersion.

        TPC = density * C_wp * L * B / 100

    Returns None if dimensions are missing/unusable rather than raising, so a
    partially-enriched hull doesn't crash a batch.
    """
    try:
        L = float(length_m)
        B = float(breadth_m)
    except (ValueError, TypeError):
        return None
    if L <= 0 or B <= 0:
        return None
    return density * c_wp * L * B / 100.0


def tonnage_from_draught(delta_draught_m: float,
                         length_m: float, breadth_m: float,
                         c_wp: float = DEFAULT_CWP,
                         density: float = SEAWATER_DENSITY) -> Optional[float]:
    """
    Indicative cargo tonnage from a change in draught.

        tonnes ~= (Delta_draught in cm) * TPC

    A positive ``delta_draught_m`` (arrival deeper than departure) is a
    discharge; a negative value is a loading. Returns None if inputs are
    unusable. See module docstring for why this is indicative only.
    """
    t = tpc(length_m, breadth_m, c_wp=c_wp, density=density)
    if t is None:
        return None
    try:
        dd_cm = float(delta_draught_m) * 100.0
    except (ValueError, TypeError):
        return None
    return dd_cm * t


def laden_state(arrival_draught_m: Optional[float],
                departure_draught_m: Optional[float],
                design_draught_m: Optional[float] = None,
                min_delta_m: float = 1.0) -> str:
    """
    Coarse laden/ballast/loading label from a pair of draughts.

    Deliberately conservative: without a credible draught pair it returns
    "unknown" rather than inventing a state. ``min_delta_m`` is the smallest
    draught change treated as a real cargo operation (below it, noise).
    """
    a = _f(arrival_draught_m)
    d = _f(departure_draught_m)
    if a is None or d is None:
        return "unknown"
    delta = a - d
    if delta >= min_delta_m:
        return "discharge (laden arrival)"
    if delta <= -min_delta_m:
        return "loading (ballast arrival)"
    return "no significant cargo change"


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (ValueError, TypeError):
        return None
    return f if f > 0 else None
