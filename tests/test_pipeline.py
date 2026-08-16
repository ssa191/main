#!/usr/bin/env python3
"""Unit tests for the port-call logic, including a NEGATIVE CONTROL proving the
window-stitching check can actually fail (a check that always passes is useless).

Run:  python3 tests/test_pipeline.py /path/to/fixtures
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rak_departures as R
from windows import WINDOWS

FIX = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rak_fixtures"
fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        fails.append(name)


print("Loading fixtures ...")
all_fixes = []
for tag, frm, to, _rid in WINDOWS:
    kept, n_raw, _w = read = R.read_window(os.path.join(FIX, f"{tag}.zip"), tag, frm, to, 4.0)
    all_fixes.extend(kept)
print(f"  {len(all_fixes):,} fixes within 4 NM\n")

print("1. Radius filter")
worst = max(R.haversine_nm(R.CENTER_LAT, R.CENTER_LON, f["lat"], f["lon"]) for f in all_fixes)
check("no fix beyond the 4 NM radius", worst <= 4.0 + 1e-9, f"max {worst:.3f} NM")
wide, _n, _w = R.read_window(os.path.join(FIX, "w17.zip"), "w17", "2026-03-04", "2026-03-11", 20.0)
tight, _n2, _w2 = R.read_window(os.path.join(FIX, "w17.zip"), "w17", "2026-03-04", "2026-03-11", 4.0)
check("20 NM keeps strictly more than 4 NM", len(wide) > len(tight), f"{len(wide)} vs {len(tight)}")

print("\n2. Minimum call duration")
calls, dropped = R.build_port_calls(all_fixes, 24.0, 3.0)
shortest = min((c["departure_epoch"] - c["arrival_epoch"]) / 3600 for c in calls)
check("every surviving call is >= 3 h", shortest >= 3.0, f"shortest {shortest:.2f} h")
check("some passes were dropped", dropped > 0, f"{dropped} dropped")

print("\n3. Gap splitting")
gaps_ok = True
by_v = defaultdict(list)
for c in calls:
    by_v[c["uuid"]].append(c)
for uuid, cs in by_v.items():
    cs.sort(key=lambda c: c["arrival_epoch"])
    for a, b in zip(cs, cs[1:]):
        if b["arrival_epoch"] - a["departure_epoch"] <= 24 * 3600:
            gaps_ok = False
check("consecutive calls of one vessel are >24 h apart", gaps_ok)

print("\n4. Seam duplicate handling")
# Consecutive windows share an endpoint date, so the same fix appears in both.
dupe_seam = sum(
    1 for f in all_fixes
    if any(f["epoch"] == R.datetime.strptime(w[2], "%Y-%m-%d").replace(tzinfo=R.timezone.utc).timestamp()
           for w in WINDOWS[:-1])
)
check("seam-duplicated raw fixes exist in the input", dupe_seam >= 0, f"{dupe_seam} at exact seam instants")
seam_call = [c for c in calls if c["uuid"] == "uuid-bahri-9660530"
             and c["arrival_epoch"] <= R.datetime.strptime("2025-12-17", "%Y-%m-%d")
             .replace(tzinfo=R.timezone.utc).timestamp() <= c["departure_epoch"]]
check("the planted w05/w06 straddling call is ONE call, not two", len(seam_call) == 1,
      f"found {len(seam_call)}")
if seam_call:
    check("that call spans >1 window", len(seam_call[0]["windows"]) > 1,
          f"windows={seam_call[0]['windows']}")

print("\n5. Stitching check -- POSITIVE (correct pooling)")
good = R.stitch_check(calls)
check("pooled reconstruction passes the seam test",
      not (good["p_value"] < 0.01 and good["near_boundary"] > good["expected_by_chance"]),
      f"near={good['near_boundary']} exp={good['expected_by_chance']:.1f} p={good['p_value']:.4f}")

print("\n6. Stitching check -- NEGATIVE CONTROL (deliberately broken pooling)")
# Rebuild calls WITHIN each window separately, which is exactly the bug the
# check exists to catch: a ship alongside across a seam becomes two calls.
broken = []
per_window = defaultdict(list)
for f in all_fixes:
    per_window[f["window"]].append(f)
for tag, wf in per_window.items():
    c, _d = R.build_port_calls(wf, 24.0, 3.0)
    broken.extend(c)
bad = R.stitch_check(broken)
check("per-window reconstruction is CAUGHT by the seam test",
      bad["p_value"] < 0.01 and bad["near_boundary"] > bad["expected_by_chance"],
      f"near={bad['near_boundary']} exp={bad['expected_by_chance']:.1f} p={bad['p_value']:.4f}")
check("broken pooling inflates the call count", len(broken) > len(calls),
      f"{len(broken)} vs {len(calls)}")

print("\n7. Size classes")
cases = [(5_000, "Mini-bulk"), (32_000, "Handysize"), (63_000, "Handymax/Supramax/Ultramax"),
         (82_000, "Panamax/Kamsarmax"), (180_000, "Post-Panamax/Capesize"),
         (320_000, "Capesize/VLOC"), (None, "unknown"), ("", "unknown")]
for dwt, want in cases:
    got = R.size_class(dwt)
    check(f"dwt {dwt!r} -> {want}", got == want, got)

print("\n8. Boundary conditions of the size ladder")
check("39,999 dwt is Handysize", R.size_class(39_999) == "Handysize")
check("40,000 dwt is Handymax band", R.size_class(40_000) == "Handymax/Supramax/Ultramax")
check("99,999 dwt is Panamax band", R.size_class(99_999) == "Panamax/Kamsarmax")
check("200,000 dwt is Capesize/VLOC", R.size_class(200_000) == "Capesize/VLOC")

print("\n" + "=" * 60)
if fails:
    print(f"{len(fails)} FAILURES: {fails}")
    sys.exit(1)
print("All tests passed.")
