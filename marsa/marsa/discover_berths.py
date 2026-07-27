#!/usr/bin/env python3
"""
Fill the grain-berth geofences — the change that turns ship movements into
grain flow. Nothing downstream (grain tonnage, the nowcast by commodity) works
until config.PORTS[...]['grain_berths'] is populated.

This queries each port's ``terminals[]`` from Datalastic so you can see the
candidate berth positions and copy the grain-silo quays into config.py as
{"name", "lat", "lon", "radius_nm"} entries. It only READS reference data
(1 credit per port), and it does NOT edit config.py for you — picking which
terminal is the grain quay is a judgement call that must be made deliberately,
not guessed by a script.

USAGE
-----
    export DATALASTIC_API_KEY="..."
    python -m marsa.discover_berths --ports mine
    python -m marsa.discover_berths --ports dammam
"""

from __future__ import annotations

import argparse
import sys

from .config import PORTS, MY_PORTS
from .datalastic_client import Datalastic, DatalasticError


def discover(sel):
    cli = Datalastic()
    for pk in sel:
        port = PORTS[pk]
        print(f"\n=== {port['label']} ({port['unlocode']}) ===")
        try:
            data = cli.port(unlocode=port["unlocode"]) or {}
        except DatalasticError as e:
            print(f"  ! lookup failed: {e}", file=sys.stderr)
            continue
        terminals = data.get("terminals") or []
        if not terminals:
            print("  no terminals returned. Fall back to a satellite berth plan "
                  "for the SAGO silo quay and enter it by hand.")
            continue
        print(f"  {len(terminals)} terminal(s). Grain quays are usually named "
              "'grain', 'silo', 'SAGO', or 'bulk':")
        found_candidate = False
        for t in terminals:
            name = t.get("name") or t.get("terminal_name") or "?"
            lat = t.get("lat") or t.get("latitude")
            lon = t.get("lon") or t.get("longitude")
            is_cand = _looks_grain(name)
            found_candidate = found_candidate or is_cand
            hint = "  <-- candidate" if is_cand else ""
            print(f"    - {name:38} lat={lat} lon={lon}{hint}")
        if not found_candidate:
            # Observed live (2026-07): Datalastic lists container terminals only
            # for the KSA ports, no grain quay. Don't pretend otherwise.
            print("  No grain-named terminal here (Datalastic tends to list "
                  "container terminals only). Get the SAGO silo berth from a "
                  "satellite/port-authority plan, OR derive it empirically once "
                  "draught_capture has logged where grain hulls actually berth.")
            continue
        print("  Copy the grain quay into config.PORTS['%s']['grain_berths'] as:"
              % pk)
        print('    {"name": "...", "lat": <lat>, "lon": <lon>, "radius_nm": 0.5}')


def _looks_grain(name: str) -> bool:
    n = (name or "").lower()
    return any(w in n for w in ("grain", "silo", "sago", "bulk", "cereal"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ports", default="mine",
                    help="comma list of keys, 'mine' (the six), or 'all'")
    a = ap.parse_args(argv)
    ports_arg = MY_PORTS if a.ports == "mine" else a.ports
    sel = list(PORTS) if ports_arg == "all" else [p.strip() for p in ports_arg.split(",")]
    bad = [p for p in sel if p not in PORTS]
    if bad:
        sys.exit(f"unknown port key(s): {bad}. valid: {list(PORTS)}")
    try:
        discover(sel)
    except DatalasticError as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
