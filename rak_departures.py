#!/usr/bin/env python3
"""
Dry-bulk departure count for the Ma'aden terminal at Ras Al Khair (SARAZ),
split into Bahri-owned hulls vs everyone else, from Datalastic AIS data.

Input  : 37 pre-paid `inradius_history` reports (see windows.py), 12 Nov 2025 -> 29 Jul 2026,
         consecutive 7-day windows, 20 NM around 27.55828 / 49.18322.
Output : out/rak_portcalls.csv, out/rak_drybulk.csv, out/rak_summary.csv + console table.

This script NEVER submits a new report. It only retrieves finished ones (free)
and calls /vessel_info (1 credit/vessel, cached to disk so re-runs are free).

The API key is read from $DATALASTIC_API_KEY and is never written to disk.

Usage:
    export DATALASTIC_API_KEY=...
    python3 rak_departures.py                     # full run
    python3 rak_departures.py --radius 3          # sensitivity test
    python3 rak_departures.py --zip-dir ./zips    # use pre-downloaded ZIPs, no report API calls
    python3 rak_departures.py --skip-spot-check   # skip the vessel_history spot check
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from windows import WINDOWS

# ---------------------------------------------------------------------------
# PARAMETERS -- every assumption that moves the answer lives here.
# ---------------------------------------------------------------------------

# Terminal centre: Ras Al Khair, Saudi Arabia (UN/LOCODE SARAZ).
CENTER_LAT = 27.55828
CENTER_LON = 49.18322

# The scans were pulled at 20 NM to catch the approach and anchorage.
# 4 NM is what isolates ships actually alongside. CLI: --radius
BERTH_RADIUS_NM = 4.0

# A gap longer than this between consecutive fixes starts a new port call. CLI: --gap-hours
CALL_GAP_HOURS = 24.0

# Calls shorter than this are passes, not calls. CLI: --min-call-hours
MIN_CALL_HOURS = 3.0

# Dry bulk is defined on vessel_info.type_specific.
DRY_BULK_TYPES = {"Bulk Carrier", "Ore Carrier", "Self Discharging Bulk Carrier"}

# Bahri Dry Bulk owned fleet as of Aug 2026. Matched on IMO, never on name.
# Re-verified live against /vessel_find at the end of every run.
BAHRI_IMOS = {
    "9660516": "BAHRI ARASCO",
    "9660528": "BAHRI GRAIN",
    "9660530": "BAHRI BULK",
    "9660542": "BAHRI WAFI",
    "9660554": "BAHRI TRADER",
    "9768045": "BAHRI SETA",
    "9790842": "BAHRI HAYA",
    "9826469": "BAHRI MUNIRA",
}

# (upper_bound_dwt_exclusive, label). Last entry catches everything above.
SIZE_CLASSES = [
    (10_000, "Mini-bulk"),
    (40_000, "Handysize"),
    (65_000, "Handymax/Supramax/Ultramax"),
    (100_000, "Panamax/Kamsarmax"),
    (200_000, "Post-Panamax/Capesize"),
    (math.inf, "Capesize/VLOC"),
]

# Ma'aden's published throughput at Ras Al Khair, for the parcel-size sanity check.
MAADEN_THROUGHPUT_MT_LOW = 15_000_000
MAADEN_THROUGHPUT_MT_HIGH = 20_000_000

# Two fixes of the same vessel within this many seconds are the same fix.
# Consecutive report windows share an endpoint date, so the seams duplicate rows.
DEDUPE_SECONDS = 1

# How close a call boundary has to sit to a window boundary to count as
# "suspicious" in the stitching check.
STITCH_TOLERANCE_MIN = 30

API_BASE = "https://api.datalastic.com/api/v0"
CACHE_DIR = "cache"
ZIP_DIR = os.path.join(CACHE_DIR, "zips")
VESSEL_CACHE = os.path.join(CACHE_DIR, "vessel_info.json")
OUT_DIR = "out"

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def api_key() -> str:
    key = os.environ.get("DATALASTIC_API_KEY", "").strip()
    if not key:
        sys.exit(
            "DATALASTIC_API_KEY is not set in the environment.\n"
            "  export DATALASTIC_API_KEY=...   (the key is never written to disk by this script)"
        )
    return key


def api_get(path: str, params: dict, retries: int = 6) -> dict:
    """GET an api.datalastic.com endpoint with 429/5xx backoff. Returns parsed JSON.

    The limit is 600 req/min; on 429 we back off exponentially rather than hammer.
    404 is 'not found', not a failure, and is returned as {} so callers can skip.
    """
    q = dict(params)
    q["api-key"] = api_key()
    url = f"{API_BASE}/{path}?{urllib.parse.urlencode(q)}"
    delay = 2.0
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError(f"giving up on {path}")


def download_report_zip(report_id: str, dest: str) -> None:
    """Fetch a finished report's ZIP. Retrieval is free; presigned URLs last ~6h,
    so we always ask for a fresh one rather than caching links."""
    meta = api_get("report", {"report_id": report_id})
    data = meta.get("data", meta)
    status = data.get("status")
    if status != "_DONE_":
        raise RuntimeError(f"report {report_id} is {status}, not _DONE_ -- refusing to submit a new one")
    url = data.get("result_url")
    if not url:
        raise RuntimeError(f"report {report_id} is _DONE_ but has no result_url")
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=300) as resp, open(tmp, "wb") as fh:
        fh.write(resp.read())
    os.replace(tmp, dest)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    r_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_nm * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Stage 1 -- retrieve and parse the 37 windows
# ---------------------------------------------------------------------------


def ensure_zips(zip_dir: str, use_api: bool) -> None:
    os.makedirs(zip_dir, exist_ok=True)
    for tag, _f, _t, rid in WINDOWS:
        dest = os.path.join(zip_dir, f"{tag}.zip")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            continue
        if not use_api:
            sys.exit(f"missing {dest} and --zip-dir was given, so no report API call was attempted")
        print(f"  retrieving {tag} ({rid}) ...", flush=True)
        download_report_zip(rid, dest)


def read_window(zip_path: str, tag: str, expect_from: str, expect_to: str, radius_nm: float):
    """Return (kept_fixes, n_raw, meta_warnings) for one window's ZIP."""
    warnings = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        meta_name = next((n for n in names if n.endswith("meta.json")), None)
        csv_name = next((n for n in names if n.endswith(".csv")), None)
        if not csv_name:
            raise RuntimeError(f"{tag}: no CSV inside {zip_path}")

        # meta.json echoes the request -- verify the report really is the window we think.
        if meta_name:
            try:
                meta = json.loads(zf.read(meta_name).decode())
                flat = json.dumps(meta)
                for expect, label in ((expect_from, "from"), (expect_to, "to")):
                    if expect not in flat:
                        warnings.append(f"{tag}: meta.json does not mention {label}={expect}")
                for coord in ("27.55828", "49.18322"):
                    if coord not in flat:
                        warnings.append(f"{tag}: meta.json does not mention centre {coord}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                warnings.append(f"{tag}: meta.json unreadable")
        else:
            warnings.append(f"{tag}: no meta.json in ZIP")

        raw = zf.read(csv_name).decode("utf-8-sig", errors="replace")

    kept, n_raw, bad_rows = [], 0, 0
    for row in csv.DictReader(io.StringIO(raw)):
        n_raw += 1
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
            epoch = int(float(row["last_pos_epoch"]))
        except (TypeError, ValueError, KeyError):
            bad_rows += 1
            continue
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            bad_rows += 1
            continue
        d = haversine_nm(CENTER_LAT, CENTER_LON, lat, lon)
        if d <= radius_nm:
            kept.append(
                {
                    "uuid": row["uuid"],
                    "epoch": epoch,
                    "lat": lat,
                    "lon": lon,
                    "destination": (row.get("destination") or "").strip(),
                    "navstat": (row.get("navstat") or "").strip(),
                    "speed": row.get("speed"),
                    "window": tag,
                    "dist_nm": d,
                }
            )
    if bad_rows:
        warnings.append(f"{tag}: {bad_rows} unparseable/out-of-range rows skipped")
    return kept, n_raw, warnings


# ---------------------------------------------------------------------------
# Stage 2 -- port call reconstruction
# ---------------------------------------------------------------------------


def build_port_calls(fixes: list, gap_hours: float, min_call_hours: float) -> list:
    """Pool ALL windows first, then split -- that is what makes a ship alongside
    across a window boundary come out as one call instead of two."""
    by_vessel = defaultdict(list)
    for f in fixes:
        by_vessel[f["uuid"]].append(f)

    gap_s = gap_hours * 3600
    min_s = min_call_hours * 3600
    calls, dropped_short = [], 0

    for uuid, vf in by_vessel.items():
        vf.sort(key=lambda x: x["epoch"])

        # Consecutive windows share an endpoint date, so seams duplicate rows.
        deduped = [vf[0]]
        for f in vf[1:]:
            if f["epoch"] - deduped[-1]["epoch"] > DEDUPE_SECONDS:
                deduped.append(f)

        group = [deduped[0]]
        for f in deduped[1:]:
            if f["epoch"] - group[-1]["epoch"] > gap_s:
                calls.append((uuid, group))
                group = [f]
            else:
                group.append(f)
        calls.append((uuid, group))

    out = []
    for uuid, group in calls:
        dur = group[-1]["epoch"] - group[0]["epoch"]
        if dur < min_s:
            dropped_short += 1
            continue
        dest = ""
        for f in reversed(group):  # last non-empty destination in the call
            if f["destination"]:
                dest = f["destination"]
                break
        out.append(
            {
                "uuid": uuid,
                "arrival_epoch": group[0]["epoch"],
                "departure_epoch": group[-1]["epoch"],
                "n_fixes": len(group),
                "windows": sorted({f["window"] for f in group}),
                "min_dist_nm": round(min(f["dist_nm"] for f in group), 3),
                "last_destination": dest,
            }
        )
    out.sort(key=lambda c: c["departure_epoch"])
    return out, dropped_short


# ---------------------------------------------------------------------------
# Stage 3 -- vessel identity (cached; 1 credit per new vessel)
# ---------------------------------------------------------------------------


def load_vessel_cache() -> dict:
    if os.path.exists(VESSEL_CACHE):
        with open(VESSEL_CACHE) as fh:
            return json.load(fh)
    return {}


def resolve_vessels(uuids: list, use_api: bool) -> dict:
    cache = load_vessel_cache()
    todo = [u for u in uuids if u not in cache]
    if todo and not use_api:
        print(f"  WARNING: {len(todo)} vessels are not in the cache and the API is unavailable")
        return cache
    if todo:
        print(f"  resolving {len(todo)} new vessels via /vessel_info (1 credit each) ...", flush=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        for i, u in enumerate(todo, 1):
            try:
                resp = api_get("vessel_info", {"uuid": u})
            except urllib.error.HTTPError as e:
                print(f"    {u}: HTTP {e.code}, skipped")
                cache[u] = {}
                continue
            cache[u] = resp.get("data", {}) or {}
            if i % 25 == 0 or i == len(todo):
                with open(VESSEL_CACHE, "w") as fh:
                    json.dump(cache, fh, indent=1)
                print(f"    {i}/{len(todo)}", flush=True)
        with open(VESSEL_CACHE, "w") as fh:
            json.dump(cache, fh, indent=1)
    return cache


def size_class(dwt) -> str:
    try:
        d = float(dwt)
    except (TypeError, ValueError):
        return "unknown"
    if d <= 0:
        return "unknown"
    for bound, label in SIZE_CLASSES:
        if d < bound:
            return label
    return SIZE_CLASSES[-1][1]


def iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def stitch_check(calls: list, tolerance_min: int = STITCH_TOLERANCE_MIN) -> dict:
    """A ship alongside across a window boundary must come out as ONE call.

    If pooling failed, calls would be chopped at window seams and call endpoints
    would pile up on those 36 interior boundaries. We compare the observed pile-up
    against what random timing would produce.
    """
    bounds = []
    for _tag, _f, to, _rid in WINDOWS[:-1]:
        dt = datetime.strptime(to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        bounds.append(dt.timestamp())

    tol_s = tolerance_min * 60
    endpoints = [c["arrival_epoch"] for c in calls] + [c["departure_epoch"] for c in calls]
    if not endpoints:
        return {}

    near = sum(1 for e in endpoints if any(abs(e - b) <= tol_s for b in bounds))

    span_start = datetime.strptime(WINDOWS[0][1], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    span_end = datetime.strptime(WINDOWS[-1][2], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    span_s = span_end - span_start
    # Fraction of the timeline that sits within +/-tol of an interior boundary.
    p_chance = (len(bounds) * 2 * tol_s) / span_s
    expected = p_chance * len(endpoints)

    # Poisson tail: how surprising is `near` if boundaries were irrelevant?
    # P(X >= near). Computed with a running term -- expected**k / k! overflows
    # outright once `near` gets into the hundreds, which is exactly the regime
    # a broken reconstruction lands in.
    if expected > 0 and near > 0:
        term = math.exp(-expected)   # k = 0
        cdf = term                   # P(X <= 0)
        for k in range(1, near):
            term *= expected / k
            cdf += term
            if cdf >= 1.0:
                break
        p_val = min(max(1.0 - cdf, 0.0), 1.0)
    else:
        p_val = 1.0

    return {
        "endpoints": len(endpoints),
        "near_boundary": near,
        "expected_by_chance": expected,
        "p_chance_pct": p_chance * 100,
        "observed_pct": 100 * near / len(endpoints),
        "p_value": p_val,
        "tolerance_min": tolerance_min,
        "n_boundaries": len(bounds),
        "spanning_calls": sum(1 for c in calls if len(c["windows"]) > 1),
    }


def spot_check_bahri(rows: list, n: int = 3) -> list:
    """Pull vessel_history for a few Bahri calls and confirm the ship really was
    at Ras Al Khair on those dates. 2 credits per day queried."""
    bahri = [r for r in rows if r["bahri_flag"] == "Y"]
    if not bahri:
        return [{"note": "no Bahri calls found to spot-check"}]

    # Spread the picks across the period rather than taking three neighbours.
    picks = [bahri[i * (len(bahri) - 1) // max(n - 1, 1)] for i in range(min(n, len(bahri)))]
    results = []
    for r in picks:
        arr = datetime.strptime(r["arrival_utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        dep = datetime.strptime(r["departure_utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        frm = (arr - timedelta(days=1)).strftime("%Y-%m-%d")
        to = (dep + timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            resp = api_get("vessel_history", {"imo": r["imo"], "from": frm, "to": to})
        except urllib.error.HTTPError as e:
            results.append({"vessel": r["vessel_name"], "imo": r["imo"], "error": f"HTTP {e.code}"})
            continue
        pts = (resp.get("data") or {}).get("positions") or []
        inside = 0
        closest = None
        for p in pts:
            try:
                d = haversine_nm(CENTER_LAT, CENTER_LON, float(p["lat"]), float(p["lon"]))
            except (TypeError, ValueError, KeyError):
                continue
            closest = d if closest is None else min(closest, d)
            if d <= BERTH_RADIUS_NM:
                inside += 1
        results.append(
            {
                "vessel": r["vessel_name"],
                "imo": r["imo"],
                "call": f"{r['arrival_utc']} -> {r['departure_utc']}",
                "history_points": len(pts),
                "points_within_radius": inside,
                "closest_nm": None if closest is None else round(closest, 2),
                "verdict": "CONFIRMED at Ras Al Khair" if inside > 0 else "NOT CONFIRMED",
            }
        )
    return results


def verify_bahri_fleet() -> dict:
    """Re-verify the hardcoded fleet against the live vessel registry."""
    found = {}
    for subtype in sorted(DRY_BULK_TYPES):
        resp = api_get("vessel_find", {"name": "BAHRI", "fuzzy": "1", "type_specific": subtype})
        for v in (resp.get("data") or {}).get("vessels") or []:
            name = (v.get("name") or "").upper()
            if name.startswith("BAHRI "):  # drop fuzzy noise like BAHR / BAHJAT
                found[str(v.get("imo"))] = v.get("name")
    return {
        "live": found,
        "missing_from_live": {k: v for k, v in BAHRI_IMOS.items() if k not in found},
        "new_since_hardcoded": {k: v for k, v in found.items() if k not in BAHRI_IMOS},
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--radius", type=float, default=BERTH_RADIUS_NM, help="alongside radius in NM")
    ap.add_argument("--gap-hours", type=float, default=CALL_GAP_HOURS, help="gap that splits port calls")
    ap.add_argument("--min-call-hours", type=float, default=MIN_CALL_HOURS, help="minimum call duration")
    ap.add_argument("--zip-dir", default=None, help="use pre-downloaded ZIPs and make no report API calls")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--skip-spot-check", action="store_true")
    ap.add_argument("--skip-fleet-check", action="store_true")
    args = ap.parse_args()

    offline = args.zip_dir is not None
    zip_dir = args.zip_dir or ZIP_DIR
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    print("=" * 78)
    print("Ras Al Khair (SARAZ) dry-bulk departures -- Ma'aden terminal")
    print(f"centre {CENTER_LAT}/{CENTER_LON} | radius {args.radius} NM | "
          f"gap {args.gap_hours} h | min call {args.min_call_hours} h")
    print("=" * 78)

    # --- Stage 1: retrieve + parse -----------------------------------------
    print("\n[1/5] Retrieving and parsing 37 windows")
    ensure_zips(zip_dir, use_api=not offline)

    all_fixes, all_warnings = [], []
    print(f"\n  {'window':6} {'from':11} {'to':11} {'raw fixes':>10} {'<=radius':>9} {'vessels':>8}")
    for tag, frm, to, _rid in WINDOWS:
        path = os.path.join(zip_dir, f"{tag}.zip")
        if not os.path.exists(path):
            sys.exit(f"FAIL: {tag} ZIP missing at {path}")
        kept, n_raw, warns = read_window(path, tag, frm, to, args.radius)
        all_warnings.extend(warns)
        if n_raw == 0:
            sys.exit(f"FAIL: {tag} parsed to zero rows -- window is empty, refusing to continue")
        all_fixes.extend(kept)
        print(f"  {tag:6} {frm:11} {to:11} {n_raw:10,} {len(kept):9,} {len({k['uuid'] for k in kept}):8,}")

    if len(all_fixes) == 0:
        sys.exit("FAIL: no fixes survived the radius filter")
    print(f"\n  total fixes within {args.radius} NM: {len(all_fixes):,}")
    print(f"  unique vessels                : {len({f['uuid'] for f in all_fixes}):,}")

    if all_warnings:
        print("\n  DATA QUALITY WARNINGS:")
        for w in all_warnings:
            print(f"    ! {w}")

    # --- Stage 2: port calls ------------------------------------------------
    print("\n[2/5] Reconstructing port calls (all windows pooled before splitting)")
    calls, dropped_short = build_port_calls(all_fixes, args.gap_hours, args.min_call_hours)
    print(f"  calls reconstructed : {len(calls):,}")
    print(f"  dropped as < {args.min_call_hours} h : {dropped_short:,} (passes, not calls)")

    # --- Stage 3: vessel identity ------------------------------------------
    print("\n[3/5] Resolving vessel identity")
    uuids = sorted({c["uuid"] for c in calls})
    vessels = resolve_vessels(uuids, use_api=not offline)

    rows = []
    unresolved = 0
    for c in calls:
        v = vessels.get(c["uuid"]) or {}
        if not v:
            unresolved += 1
        imo = str(v.get("imo") or "")
        dwt = v.get("deadweight")
        dur_h = (c["departure_epoch"] - c["arrival_epoch"]) / 3600
        rows.append(
            {
                "vessel_name": v.get("name") or "UNKNOWN",
                "imo": imo,
                "mmsi": str(v.get("mmsi") or ""),
                "flag": v.get("country_iso") or "",
                "type_specific": v.get("type_specific") or "",
                "dwt": dwt if dwt is not None else "",
                "size_class": size_class(dwt),
                "arrival_utc": iso(c["arrival_epoch"]),
                "departure_utc": iso(c["departure_epoch"]),
                "days_alongside": round(dur_h / 24, 2),
                "last_destination": c["last_destination"],
                "bahri_flag": "Y" if imo in BAHRI_IMOS else "N",
                "uuid": c["uuid"],
                "n_fixes": c["n_fixes"],
                "min_dist_nm": c["min_dist_nm"],
                "windows_spanned": len(c["windows"]),
            }
        )
    if unresolved:
        print(f"  ! {unresolved} calls have no vessel_info (counted, but type unknown)")

    drybulk = [r for r in rows if r["type_specific"] in DRY_BULK_TYPES]
    print(f"  dry-bulk calls: {len(drybulk):,} of {len(rows):,}")

    # --- Stage 4: outputs ---------------------------------------------------
    print("\n[4/5] Writing outputs")
    cols = ["vessel_name", "imo", "mmsi", "flag", "type_specific", "dwt", "size_class",
            "arrival_utc", "departure_utc", "days_alongside", "last_destination", "bahri_flag",
            "uuid", "n_fixes", "min_dist_nm", "windows_spanned"]

    for fname, data in (("rak_portcalls.csv", rows), ("rak_drybulk.csv", drybulk)):
        p = os.path.join(args.out_dir, fname)
        with open(p, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(data)
        print(f"  {p} ({len(data):,} rows)")

    # Monthly summary, bucketed on DEPARTURE date.
    monthly = defaultdict(lambda: {"total": 0, "bahri": 0, "other": 0})
    for r in drybulk:
        m = r["departure_utc"][:7]
        monthly[m]["total"] += 1
        monthly[m]["bahri" if r["bahri_flag"] == "Y" else "other"] += 1

    summary_path = os.path.join(args.out_dir, "rak_summary.csv")
    with open(summary_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["month", "drybulk_departures", "bahri", "other", "bahri_pct"])
        for m in sorted(monthly):
            d = monthly[m]
            pct = 100 * d["bahri"] / d["total"] if d["total"] else 0
            w.writerow([m, d["total"], d["bahri"], d["other"], f"{pct:.1f}"])
    print(f"  {summary_path} ({len(monthly)} months)")

    print("\n  Dry-bulk departures from Ras Al Khair, by month of departure")
    print(f"  {'month':9} {'total':>7} {'Bahri':>7} {'other':>7} {'Bahri %':>9}")
    print("  " + "-" * 43)
    tot = bah = 0
    for m in sorted(monthly):
        d = monthly[m]
        pct = 100 * d["bahri"] / d["total"] if d["total"] else 0
        tot += d["total"]
        bah += d["bahri"]
        print(f"  {m:9} {d['total']:7,} {d['bahri']:7,} {d['other']:7,} {pct:8.1f}%")
    print("  " + "-" * 43)
    print(f"  {'TOTAL':9} {tot:7,} {bah:7,} {tot - bah:7,} "
          f"{(100 * bah / tot if tot else 0):8.1f}%")
    print("\n  NOTE: this counts Bahri-OWNED hulls only. Cargo Bahri fixes on")
    print("  chartered-in tonnage reads as 'Other', so the Bahri share is a FLOOR")
    print("  on their commercial role, not a ceiling.")

    # --- Stage 5: verification ---------------------------------------------
    print("\n[5/5] Verification")

    print("\n  (a) Window stitching -- do calls get chopped at window seams?")
    st = stitch_check(calls)
    if st:
        print(f"      call endpoints                      : {st['endpoints']:,}")
        print(f"      calls spanning >1 window            : {st['spanning_calls']:,}")
        print(f"      endpoints within +/-{st['tolerance_min']}min of a seam: {st['near_boundary']:,} "
              f"({st['observed_pct']:.2f}%)")
        print(f"      expected by chance                  : {st['expected_by_chance']:.1f} "
              f"({st['p_chance_pct']:.2f}%)")
        print(f"      Poisson p-value                     : {st['p_value']:.4f}")
        if st["p_value"] < 0.01 and st["near_boundary"] > st["expected_by_chance"]:
            print("      RESULT: FAIL -- endpoints cluster on window seams; windows are NOT stitching.")
        else:
            print("      RESULT: PASS -- no excess clustering on seams; windows stitch correctly.")

    print("\n  (b) Parcel-size sanity vs Ma'aden throughput (15-20 Mt/yr)")
    span_days = (datetime.strptime(WINDOWS[-1][2], "%Y-%m-%d")
                 - datetime.strptime(WINDOWS[0][1], "%Y-%m-%d")).days
    annualised = tot * 365 / span_days if span_days else 0
    laden_dwt = [float(r["dwt"]) for r in drybulk if str(r["dwt"]).replace(".", "").isdigit()]
    avg_dwt = sum(laden_dwt) / len(laden_dwt) if laden_dwt else 0
    print(f"      period                     : {span_days} days")
    print(f"      dry-bulk departures        : {tot:,}  -> {annualised:,.0f}/yr annualised")
    if annualised:
        lo = MAADEN_THROUGHPUT_MT_LOW / annualised
        hi = MAADEN_THROUGHPUT_MT_HIGH / annualised
        print(f"      implied avg parcel         : {lo:,.0f} - {hi:,.0f} t")
        print(f"      observed avg vessel dwt    : {avg_dwt:,.0f} t")
        if avg_dwt:
            ratio = ((lo + hi) / 2) / avg_dwt
            if ratio > 1.15:
                print(f"      FLAG: implied parcel is {ratio:.2f}x average dwt -- more cargo than the")
                print("            counted ships can carry. Departures are likely UNDER-counted.")
            elif ratio < 0.5:
                print(f"      FLAG: implied parcel is only {ratio:.2f}x average dwt -- ships would be")
                print("            half empty. Likely OVER-counting (non-Ma'aden traffic in radius).")
            else:
                print(f"      OK: implied parcel is {ratio:.2f}x average dwt -- consistent with")
                print("          part-laden bulkers on a phosphate/mineral trade.")

    if not args.skip_spot_check and not offline:
        print("\n  (c) Spot-check 3 Bahri calls against /vessel_history")
        for res in spot_check_bahri(rows):
            print(f"      {res}")
    else:
        print("\n  (c) Spot-check skipped")

    if not args.skip_fleet_check and not offline:
        print("\n  (d) Bahri fleet re-verification against /vessel_find")
        fc = verify_bahri_fleet()
        print(f"      live BAHRI dry-bulk hulls : {len(fc['live'])}")
        if fc["missing_from_live"]:
            print(f"      NO LONGER IN REGISTRY     : {fc['missing_from_live']}")
        if fc["new_since_hardcoded"]:
            print(f"      NEW SINCE Aug 2026 LIST   : {fc['new_since_hardcoded']}")
        if not fc["missing_from_live"] and not fc["new_since_hardcoded"]:
            print("      RESULT: fleet unchanged -- all 8 hulls present, no additions.")
    else:
        print("\n  (d) Fleet re-verification skipped")

    print("\nDone.")


if __name__ == "__main__":
    main()
