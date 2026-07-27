#!/usr/bin/env python3
"""
Phase 0 — live draught capture. START THIS NOW; the history compounds.

Every day this sweeps the grain ports for dry-bulk vessels and records each
one's crew-reported draught (plus ETA, origin and destination) into the
``draught_snapshots`` table. Draught is the one field ``inradius_history`` does
NOT carry, so it cannot be backfilled: the only way to know a ship's arrival and
departure draught is to capture them live while it is alongside. Every week this
does not run is a week of Delta-draught that will never exist, and Delta-draught is
what turns "arriving DWT capacity" (an upper bound) into an actual tonnage.

CREDIT BUDGET
-------------
* The sweep (``vessel_inradius``) costs 1 credit per vessel found.
* ``vessel_pro`` (draught/ETA/ports) costs 3 credits and is called at most once
  per hull per day, only for dry-bulk hulls. Use ``--max-pro`` to hard-cap it.
Roughly 50-100 credits/day across the six ports at ``--radius`` = port radius,
comfortably inside a 20,000/month allowance run daily.

RUNS IN A SANDBOX / CI
----------------------
Unlike the historical backfill, this uses only plain GET endpoints, so it works
anywhere the network can reach api.datalastic.com. Schedule it daily (cron, a
Routine, or scripts/capture_draughts.sh).

USAGE
-----
    export DATALASTIC_API_KEY="..."
    python -m marsa.draught_capture --plan            # show plan, spend nothing
    python -m marsa.draught_capture --ports mine      # daily capture
    python -m marsa.draught_capture --ports dammam --max-pro 20
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from . import config, storage
from .config import PORTS, MY_PORTS
from .datalastic_client import Datalastic, DatalasticError
from .tpc import laden_state


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _pick(d: dict, *names):
    """First non-empty value among candidate keys (case-insensitive)."""
    low = {k.lower(): v for k, v in d.items()}
    for n in names:
        v = low.get(n.lower())
        if v not in (None, "", []):
            return v
    return None


def _port_name(d: dict, *names):
    """A port field that may be a string or a {name, unlocode} object."""
    v = _pick(d, *names)
    if isinstance(v, dict):
        return v.get("name") or v.get("unlocode") or v.get("port")
    return v


def _snapshot_from_pro(uuid: str, port_key: str, pro: dict) -> dict:
    """Flatten a vessel_pro payload into a draught_snapshots row."""
    return {
        "uuid": uuid,
        "captured_at": _now_iso(),
        "port_key": port_key,
        "mmsi": _pick(pro, "mmsi"),
        "imo": _pick(pro, "imo"),
        "name": _pick(pro, "name", "name_ais"),
        "draught_m": _num(_pick(pro, "draught", "draft", "current_draught",
                                "draught_current")),
        "nav_status": _pick(pro, "navigation_status", "nav_status", "navstat"),
        "speed_kn": _num(_pick(pro, "speed")),
        "lat": _num(_pick(pro, "lat", "latitude")),
        "lon": _num(_pick(pro, "lon", "longitude")),
        "destination": _port_name(pro, "destination_port", "dest_port",
                                   "destination"),
        "origin_port": _port_name(pro, "departure_port", "origin_port",
                                   "last_port"),
        "eta": _pick(pro, "eta", "eta_utc"),
        "source": "vessel_pro",
    }


def _captured_today(conn) -> set:
    """UUIDs already vessel_pro'd today - so a re-run mid-day doesn't re-spend."""
    rows = conn.execute(
        "SELECT DISTINCT uuid FROM draught_snapshots "
        "WHERE substr(captured_at, 1, 10) = ?", (_today(),)).fetchall()
    return {r[0] for r in rows}


def capture(sel, *, max_pro=None, use_scan_radius=False,
            db_path=config.DB_PATH, verbose=True):
    conn = storage.connect(db_path)
    cli = Datalastic()
    st = cli.stat()
    if verbose:
        print(f"Key {st['key_status']} | credits remaining: "
              f"{st['requests_remaining']}")

    already = _captured_today(conn)
    pro_calls = 0
    recorded = 0

    for pk in sel:
        port = PORTS[pk]
        radius = port["scan_radius_nm"] if use_scan_radius else port["port_radius_nm"]
        try:
            vessels = cli.vessel_inradius_all(
                lat=port["lat"], lon=port["lon"], radius=radius,
                exclude=config.INRADIUS_EXCLUDE)
        except DatalasticError as e:
            print(f"  ! sweep failed at {port['label']}: {e}", file=sys.stderr)
            continue

        bulk = [v for v in vessels
                if config.is_dry_bulk(_pick(v, "type_specific"), _pick(v, "type"))]
        if verbose:
            print(f"\n=== {port['label']} - {len(vessels)} vessels in "
                  f"{radius} NM, {len(bulk)} dry-bulk ===")

        for v in bulk:
            uuid = _pick(v, "uuid")
            if not uuid or uuid in already:
                continue
            if max_pro is not None and pro_calls >= max_pro:
                if verbose:
                    print(f"  (reached --max-pro {max_pro}; stopping pro lookups)")
                break
            try:
                pro = cli.vessel_pro(uuid=uuid) or {}
            except DatalasticError as e:
                print(f"  ! vessel_pro failed for {uuid}: {e}", file=sys.stderr)
                continue
            pro_calls += 1
            snap = _snapshot_from_pro(uuid, pk, pro)
            storage.record_draught(conn, snap)
            already.add(uuid)
            recorded += 1
            if verbose:
                d = snap["draught_m"]
                print(f"  + {snap['name'] or uuid[:8]:24} "
                      f"draught={d if d is not None else '?':>5} m  "
                      f"nav={snap['nav_status'] or '?':16} "
                      f"from={snap['origin_port'] or '?'}")

    conn.commit()
    conn.close()
    if verbose:
        print(f"\nDone. {recorded} draught snapshots recorded "
              f"(~{pro_calls * 3} credits on vessel_pro). Run daily; Delta-draught "
              "accrues per hull over successive days at berth.")
    return recorded


def plan(sel):
    print("Draught-capture plan (no credits spent):")
    for pk in sel:
        p = PORTS[pk]
        print(f"  {p['label']:32} sweep {p['port_radius_nm']} NM "
              f"@ ({p['lat']}, {p['lon']})")
    print("\nPer run: 1 credit per vessel found + 3 credits per new dry-bulk "
          "hull (vessel_pro), capped by --max-pro. Schedule daily.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ports", default="mine",
                    help="comma list of keys, 'mine' (the six), or 'all'")
    ap.add_argument("--max-pro", type=int, default=None, dest="max_pro",
                    help="hard cap on vessel_pro lookups this run (credit guard)")
    ap.add_argument("--scan-radius", action="store_true", dest="scan_radius",
                    help="sweep the wider scan radius instead of the port radius")
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--plan", action="store_true",
                    help="print the plan and exit (no credits spent)")
    a = ap.parse_args(argv)

    ports_arg = MY_PORTS if a.ports == "mine" else a.ports
    sel = list(PORTS) if ports_arg == "all" else [p.strip() for p in ports_arg.split(",")]
    bad = [p for p in sel if p not in PORTS]
    if bad:
        sys.exit(f"unknown port key(s): {bad}. valid: {list(PORTS)}")

    if a.plan:
        plan(sel)
        return
    try:
        capture(sel, max_pro=a.max_pro, use_scan_radius=a.scan_radius, db_path=a.db)
    except DatalasticError as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(1)


def _num(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    main()
