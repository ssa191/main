#!/usr/bin/env python3
"""Build synthetic report ZIPs + a vessel_info cache so the pipeline can be
exercised end-to-end without touching the Datalastic API.

Deliberately includes the cases that break naive implementations:
  * a vessel alongside ACROSS a window seam (must come out as ONE call)
  * duplicate rows at the seam (consecutive windows share an endpoint date)
  * sub-3h passes (must be dropped)
  * vessels out at 8-18 NM (anchorage; must be filtered out by the 4 NM rule)
"""
import csv
import io
import json
import math
import os
import random
import sys
import zipfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from windows import WINDOWS

CENTER_LAT, CENTER_LON = 27.55828, 49.18322
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rak_fixtures"
random.seed(7)


def offset(lat, lon, nm, bearing_deg):
    r = 3440.065
    b = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    d = nm / r
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def ep(datestr):
    return int(datetime.strptime(datestr, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


# --- synthetic fleet --------------------------------------------------------
FLEET = []
# Bahri hulls (real IMOs so the Bahri matcher is genuinely exercised)
for imo, name, dwt in [
    ("9660516", "BAHRI ARASCO", 81855), ("9660528", "BAHRI GRAIN", 81855),
    ("9660530", "BAHRI BULK", 81864), ("9660542", "BAHRI WAFI", 81855),
    ("9660554", "BAHRI TRADER", 81855), ("9768045", "BAHRI SETA", 62601),
    ("9790842", "BAHRI HAYA", 63452), ("9826469", "BAHRI MUNIRA", 64499),
]:
    FLEET.append({"uuid": f"uuid-bahri-{imo}", "imo": imo, "name": name, "dwt": dwt,
                  "type_specific": "Bulk Carrier", "flag": "SA"})
# Other dry bulk
for i in range(40):
    FLEET.append({"uuid": f"uuid-bulk-{i:03d}", "imo": f"95{i:05d}", "name": f"TEST BULKER {i:03d}",
                  "dwt": random.choice([8_000, 32_000, 56_000, 63_000, 82_000, 180_000]),
                  "type_specific": random.choice(["Bulk Carrier", "Bulk Carrier", "Ore Carrier",
                                                  "Self Discharging Bulk Carrier"]), "flag": "PA"})
# Non dry-bulk (tankers etc) -- must be excluded from the dry-bulk subset
for i in range(15):
    FLEET.append({"uuid": f"uuid-tank-{i:03d}", "imo": f"94{i:05d}", "name": f"TEST TANKER {i:03d}",
                  "dwt": 50_000, "type_specific": "Crude Oil Tanker", "flag": "LR"})

fixes_by_window = {tag: [] for tag, _f, _t, _r in WINDOWS}
W = {tag: (ep(f), ep(t)) for tag, f, t, _r in WINDOWS}


def emit(uuid, start_epoch, dur_h, dist_nm, dest="RAS AL KHAIR", step_min=20):
    """Lay down fixes every step_min for dur_h, into whichever windows they fall in."""
    n = max(int(dur_h * 60 / step_min), 1)
    for k in range(n + 1):
        t = start_epoch + k * step_min * 60
        lat, lon = offset(CENTER_LAT, CENTER_LON, dist_nm, random.uniform(0, 360))
        for tag, (ws, we) in W.items():
            if ws <= t <= we:
                fixes_by_window[tag].append(
                    {"uuid": uuid, "lat": round(lat, 6), "lon": round(lon, 6),
                     "speed": 0.1, "course": 0, "heading": 0, "navstat": "Moored",
                     "destination": dest, "last_pos_epoch": t,
                     "last_pos_utc": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                     "distance_nm": round(dist_nm, 3)})


expected = {"calls": 0, "bahri_calls": 0, "seam_spanning": 0}

# 1. Normal calls: each vessel gets a handful of 1-4 day calls at 0.5-3 NM.
cursor = {}
for v in FLEET:
    t = ep(WINDOWS[0][1]) + random.randint(0, 5) * 86400
    while t < ep(WINDOWS[-1][2]) - 6 * 86400:
        dur = random.uniform(18, 90)          # hours alongside
        emit(v["uuid"], t, dur, random.uniform(0.5, 3.2))
        expected["calls"] += 1
        if v["imo"] in {f["imo"] for f in FLEET[:8]}:
            expected["bahri_calls"] += 1
        t += int(dur * 3600) + random.randint(4, 20) * 86400   # gap >> 24h

# 2. A call deliberately straddling the w05/w06 seam (2025-12-17).
emit("uuid-bahri-9660530", ep("2025-12-16") + 6 * 3600, 60, 1.1)
expected["seam_spanning"] += 1

# 3. Sub-3h passes -- must be dropped.
for i in range(12):
    emit(f"uuid-bulk-{i:03d}", ep("2026-02-02") + i * 86400, 1.5, 2.0, dest="TRANSIT", step_min=15)

# 4. Anchorage traffic at 8-18 NM -- must be filtered out by the 4 NM rule.
for i in range(20):
    emit(f"uuid-bulk-{i:03d}", ep("2026-03-05") + i * 3600 * 7, 40, random.uniform(8, 18), dest="ANCHOR")

# --- write ZIPs -------------------------------------------------------------
os.makedirs(OUT, exist_ok=True)
COLS = ["uuid", "lat", "lon", "speed", "course", "heading", "navstat", "destination",
        "last_pos_epoch", "last_pos_utc", "distance_nm"]
for tag, frm, to, rid in WINDOWS:
    rows = sorted(fixes_by_window[tag], key=lambda r: (r["uuid"], r["last_pos_epoch"]))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS)
    w.writeheader()
    w.writerows(rows)
    meta = {"report_type": "inradius_history", "report_id": rid, "from": frm, "to": to,
            "lat": CENTER_LAT, "lon": CENTER_LON, "radius": 20}
    with zipfile.ZipFile(os.path.join(OUT, f"{tag}.zip"), "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("meta.json", json.dumps(meta, indent=1))
        zf.writestr(f"inradius_{tag}.csv", buf.getvalue())

# --- vessel_info cache ------------------------------------------------------
os.makedirs("cache", exist_ok=True)
cache = {v["uuid"]: {"uuid": v["uuid"], "name": v["name"], "imo": v["imo"],
                     "mmsi": "40" + v["imo"], "country_iso": v["flag"],
                     "type": "Cargo", "type_specific": v["type_specific"],
                     "deadweight": v["dwt"]} for v in FLEET}
with open("cache/vessel_info.json", "w") as fh:
    json.dump(cache, fh, indent=1)

print(f"wrote {len(WINDOWS)} ZIPs to {OUT}")
print(f"fleet={len(FLEET)}  synthetic calls planted={expected['calls']} "
      f"(bahri={expected['bahri_calls']}, seam-straddling={expected['seam_spanning']})")
print(f"total fixes={sum(len(v) for v in fixes_by_window.values()):,}")
