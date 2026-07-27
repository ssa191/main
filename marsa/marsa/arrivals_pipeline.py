#!/usr/bin/env python3
"""
KSA dry-bulk arrivals — historical backfill (converged).

Pulls Datalastic AIS area-history for a set of Saudi ports, isolates dry-bulk
vessels, reconstructs each port call (anchorage -> berth -> departure), computes
days in port, enriches ship size, dedups vessels caught in two overlapping port
scans, infers grain vs non-grain by berth, and UPSERTs into SQLite so re-runs
are idempotent.

This is the convergence of the two divergent Drive copies onto Folder A's logic:
scan-grouping, the report-queue credit guard (``_submit_with_slot``), batched
submit-then-poll (``fetch_windows``), and the fixed 7-day window grid. The
storage sink and ``--since-last`` are new.

WHY THIS RUNS OUTSIDE THE CLAUDE CLOUD SANDBOX / CI
---------------------------------------------------
The history uses Datalastic's async ``inradius_history`` report (POST /report ->
poll -> download ZIP). That POST + binary-ZIP download is firewalled in some
sandboxes. Run it where the network can reach api.datalastic.com. Plain Python
(requests, optional openpyxl).

USAGE
-----
    pip install requests openpyxl
    export DATALASTIC_API_KEY="..."          # or put it in .env (git-ignored)
    python -m marsa.arrivals_pipeline --estimate          # projection only
    python -m marsa.arrivals_pipeline --year 2025         # one calendar year
    python -m marsa.arrivals_pipeline --ports jeddah,kap  # subset
    python -m marsa.arrivals_pipeline --since-last        # incremental catch-up

RESUMABILITY
------------
Every 7-day report ZIP is cached under out/raw/. Re-running skips windows already
downloaded, so if you hit the monthly credit quota you can stop and continue next
cycle with no rework and no repeat spend. Reconstructed calls UPSERT into SQLite,
so a partial re-run never duplicates rows.

DATA-HONESTY NOTES
------------------
* AIS carries NO cargo field. "Grain / Non-grain" is INFERRED from the berth the
  ship occupied vs. the grain_berths geofences in config.py, with a confidence.
  Fill those geofences or every row reads "Unknown" (see config.py).
* Arrival/departure/days are AIS-derived and approximate (see reconstruct()).
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

from . import config, storage
from .config import PORTS, MY_PORTS
from .datalastic_client import Datalastic, DatalasticError
from .geofence import haversine_nm, infer_grain

RAW = Path(config.RAW_DIR)

# A position is a 5-tuple, not a dict. Busy ports yield millions of them and a
# 6-key dict holding a datetime costs ~511 bytes each - enough to OOM a 16 GB
# box partway through Jeddah. The tuple below is ~210 bytes: epoch float instead
# of datetime, and the vessel id lives in the dict key rather than every row.
P_TS, P_LAT, P_LON, P_SPEED, P_DIST = range(5)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fmt_ts(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def date_windows(frm: date, to: date, window_days: int):
    d = frm
    while d < to:
        w_end = min(d + timedelta(days=window_days), to)
        yield d.isoformat(), w_end.isoformat()
        d = w_end


def parse_ts(v):
    if v is None or v == "":
        return None
    try:
        return datetime.fromtimestamp(float(v), tz=timezone.utc)
    except (ValueError, TypeError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(str(v), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_epoch(v):
    """Timestamp as a float epoch. Avoids building a datetime per position."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        pass
    dt = parse_ts(v)
    return dt.timestamp() if dt else None


def pick(row, *names):
    low = {k.lower(): v for k, v in row.items()}
    for n in names:
        if n.lower() in low and str(low[n.lower()]).strip() != "":
            return low[n.lower()]
    return None


# ---------------------------------------------------------------------------
# 1. pull the raw area-history report for one port over one window (cached)
# ---------------------------------------------------------------------------

def _credits(cli):
    """Credit balance for the progress line. Cosmetic - never fatal. A DNS
    blip here once killed a 3-hour backfill mid-flight."""
    try:
        return f"{cli.stat()['requests_remaining']}"
    except Exception:
        return "?"


def _submit_with_slot(cli, port, frm, to, tries=60):
    """Submit one window, waiting if the account's report queue is full.

    Datalastic caps how many reports may be pending at once and answers an
    over-cap submit with 400 "You already have pending report". That is a
    back-pressure signal, not a bad request - treating it as a failure would
    silently drop the window and leave a hole in the history. So wait for a
    slot. A killed run leaves its in-flight reports pending server-side, which
    is exactly when this path matters.
    """
    for attempt in range(tries):
        try:
            return cli.submit_report("inradius_history",
                                     lat=port["lat"], lon=port["lon"],
                                     radius=port["scan_radius_nm"],
                                     **{"from": frm, "to": to})
        except DatalasticError as e:
            if not (e.status == 400
                    and "pending report" in str(e.payload).lower()):
                raise
            if attempt == 0:
                print("    (report queue full - waiting for a slot)", flush=True)
            time.sleep(config.POLL_SECONDS)
    raise DatalasticError(
        f"Report queue still full after {tries * config.POLL_SECONDS}s",
        status=400)


def fetch_windows(cli, port, wins):
    """Submit a batch of windows, then poll them together.

    Datalastic builds inradius_history reports server-side and that dominates
    the runtime (~9 min each), so submitting the whole batch up front collapses
    N serial waits into one concurrent one. Yields (frm, to, zip_path) as each
    report lands - zip_path is None for a window that failed, and the caller
    skips it. Order is completion order, not window order, which is fine: the
    positions are pooled per vessel and sorted by timestamp in reconstruct().
    """
    pending = []  # (frm, to, zip_path, report_id)
    for frm, to in wins:
        zip_path = RAW / f"{port['unlocode']}_{frm}_{to}.zip"
        if zip_path.exists():
            yield frm, to, zip_path
            continue
        try:
            sub = _submit_with_slot(cli, port, frm, to)
        except DatalasticError as e:
            print(f"    ! submit failed {frm}: {e}", file=sys.stderr)
            yield frm, to, None
            continue
        pending.append((frm, to, zip_path, sub["report_id"]))

    if not pending:
        return
    print(f"    {len(pending)} report(s) building server-side...", flush=True)

    deadline = time.time() + config.REPORT_TIMEOUT
    while pending and time.time() < deadline:
        still = []
        for frm, to, zip_path, rid in pending:
            try:
                data = cli.report_status(rid)
            except DatalasticError as e:
                print(f"    ! status failed {frm}: {e}", file=sys.stderr)
                yield frm, to, None
                continue
            status = data.get("status")
            if status in ("_PENDING_", "_IN_PROGRESS_"):
                still.append((frm, to, zip_path, rid))
                continue
            if status != "_DONE_":
                print(f"    ! {frm} unexpected status {status}", file=sys.stderr)
                yield frm, to, None
                continue
            url = data.get("result_url")
            if not url:
                print(f"    ! no result_url for {frm}", file=sys.stderr)
                yield frm, to, None
                continue
            try:
                cli.download_report(url, str(zip_path))
            except DatalasticError as e:
                print(f"    ! download failed {frm}: {e}", file=sys.stderr)
                yield frm, to, None
                continue
            print(f"    + {frm}" + " " * 24, flush=True)
            yield frm, to, zip_path
        pending = still
        if pending:
            print(f"    ...{len(pending)} still building", end="\r", flush=True)
            time.sleep(config.POLL_SECONDS)

    for frm, to, _zp, rid in pending:
        print(f"    ! timed out {frm} (report {rid})", file=sys.stderr)
        yield frm, to, None


def rows_from_zip(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        for nm in z.namelist():
            if not nm.lower().endswith((".csv", ".txt")):
                continue
            with z.open(nm) as fh:
                for r in csv.DictReader(io.TextIOWrapper(fh, "utf-8", errors="replace")):
                    yield r


# ---------------------------------------------------------------------------
# 2. reconstruct port calls from position pings
# ---------------------------------------------------------------------------

def reconstruct(port, positions_by_vessel):
    calls = []
    for vid, pts in positions_by_vessel.items():
        pts.sort(key=lambda p: p[P_TS])
        if not pts:
            continue
        visit, last = [], None
        for p in pts:
            if last is not None and p[P_TS] - last > config.VISIT_GAP_HRS * 3600:
                calls.append(_summarize(port, vid, visit))
                visit = []
            visit.append(p)
            last = p[P_TS]
        if visit:
            calls.append(_summarize(port, vid, visit))
    return [c for c in calls
            if c and c.get("_min_dist_nm", 99) <= port["port_radius_nm"]]


def _summarize(port, vid, visit):
    if not visit:
        return None
    arr, dep = visit[0], visit[-1]
    days = round((dep[P_TS] - arr[P_TS]) / 86400, 2)

    # Datalastic gives distance_nm from the scan centre (== port centre here);
    # fall back to haversine if absent.
    def pdist(p):
        return (p[P_DIST] if p[P_DIST] is not None
                else haversine_nm(p[P_LAT], p[P_LON], port["lat"], port["lon"]))

    min_dist = min(pdist(p) for p in visit)
    anchored = any((p[P_SPEED] is not None and p[P_SPEED] <= config.ANCHOR_SPEED_KN)
                   for p in visit[:3])
    grain, conf = infer_grain(port, [(p[P_LAT], p[P_LON]) for p in visit])
    # type/name/mmsi/imo are NOT in the report - filled by resolve_and_filter()
    return {
        "port": port["label"], "vessel_name": "",
        "mmsi": "", "imo": "",
        "uuid": vid,
        "type_specific": "",
        "arrival_utc": _fmt_ts(arr[P_TS]),
        "departure_utc": _fmt_ts(dep[P_TS]),
        "days_in_port": days,
        "arrived_anchored": "Yes" if anchored else "Unknown",
        "grain_flag": grain, "grain_confidence": conf,
        "_min_dist_nm": round(min_dist, 2),
        "dwt": "", "gross_tonnage": "", "length_m": "", "breadth_m": "",
        "year_built": "", "size_class": "",
    }


# ---------------------------------------------------------------------------
# 3. size enrichment - resolve uuids to vessel type/specs, keep dry-bulk
# ---------------------------------------------------------------------------

def resolve_and_filter(cli, calls):
    """The report gives only uuids. Look up each vessel's type + specs once,
    keep only dry-bulk calls, and fill name/mmsi/imo/size."""
    cache = {}
    kept = []
    total = len({c["uuid"] for c in calls if c["uuid"]})
    print(f"  resolving {total} unique vessels (type + size lookup)...", flush=True)
    for c in calls:
        uid = c["uuid"]
        if not uid:
            continue
        if uid not in cache:
            try:
                cache[uid] = cli.vessel_info(uuid=uid) or {}
            except DatalasticError:
                cache[uid] = {}
        d = cache[uid]
        if not config.is_dry_bulk(d.get("type_specific"), d.get("type")):
            continue
        c["vessel_name"] = d.get("name", "") or d.get("name_ais", "")
        c["mmsi"] = d.get("mmsi", "")
        c["imo"] = d.get("imo", "")
        c["type_specific"] = d.get("type_specific") or d.get("type") or ""
        c["dwt"] = d.get("deadweight", "")
        c["gross_tonnage"] = d.get("gross_tonnage", "")
        c["length_m"] = d.get("length", "")
        c["breadth_m"] = d.get("breadth", "")
        c["year_built"] = d.get("year_built", "")
        c["size_class"] = config.size_class(c["dwt"])
        kept.append(c)
    print(f"  kept {len(kept)} dry-bulk calls (of {len(calls)} total)", flush=True)
    return kept


# ---------------------------------------------------------------------------
# 4. cross-port dedup - a ship inside two overlapping scans is assigned to the
#    nearest port (smallest closest-approach) for the same arrival day.
# ---------------------------------------------------------------------------

def dedup_across_ports(calls):
    by_key = defaultdict(list)
    for c in calls:
        # uuid last-resort: before enrichment (or when a lookup returns no
        # identity) imo/mmsi/name are all "", which would collapse every vessel
        # arriving on the same day into a single call.
        vk = c["imo"] or c["mmsi"] or c["vessel_name"] or c["uuid"]
        day = c["arrival_utc"][:10]
        by_key[(vk, day)].append(c)
    kept = []
    for group in by_key.values():
        kept.append(min(group, key=lambda c: c.get("_min_dist_nm", 99)))
    kept.sort(key=lambda c: (c["port"], c["arrival_utc"]))
    return kept


# ---------------------------------------------------------------------------
# estimate + run
# ---------------------------------------------------------------------------

def estimate(sel, frm, to):
    ndays = (to - frm).days
    nwin = -(-ndays // config.WINDOW_DAYS)
    per_port = nwin * config.REPORT_CREDITS
    total = per_port * len(sel)
    print(f"Coverage: {frm} -> {to} ({ndays} days, {nwin} windows/port)")
    print(f"Ports: {', '.join(PORTS[p]['label'] for p in sel)}")
    print(f"History credits: {nwin} reports x {config.REPORT_CREDITS} = "
          f"~{per_port:,} /port x {len(sel)} ports = ~{total:,} credits")
    print("Plus ~1 credit per unique vessel for size enrichment (a few thousand "
          "over multi-year spans).")
    cap = 20000 // config.REPORT_CREDITS
    print(f"Note: a report costs a flat {config.REPORT_CREDITS} credits "
          f"regardless of window length, so a 20,000/month quota covers only "
          f"~{cap} windows. Chunk by --year to stay under the cap. ZIPs cache, "
          "so runs resume cleanly.")


def run(sel, frm, to, db_path=config.DB_PATH):
    RAW.mkdir(parents=True, exist_ok=True)
    conn = storage.connect(db_path)
    cli = Datalastic()
    st = cli.stat()
    print(f"Key {st['key_status']} | credits remaining: {st['requests_remaining']}")
    estimate(sel, frm, to)

    all_calls = []
    for pk in sel:
        port = PORTS[pk]
        wins = list(date_windows(frm, to, config.WINDOW_DAYS))
        print(f"\n=== {port['label']} ({port['unlocode']}) - {len(wins)} windows ===")
        by_vessel = defaultdict(list)
        for start in range(0, len(wins), config.BATCH_SIZE):
            batch = wins[start:start + config.BATCH_SIZE]
            ncached = sum(1 for wf, wt in batch
                          if (RAW / f"{port['unlocode']}_{wf}_{wt}.zip").exists())
            print(f"  [{start+1}-{start+len(batch)}/{len(wins)}] {batch[0][0]} "
                  f"-> {batch[-1][1]} ({ncached} cached) "
                  f"(credits left: {_credits(cli)})", flush=True)
            for wf, wt, zp in fetch_windows(cli, port, batch):
                if not zp:
                    continue
                # inradius_history has NO type/name/mmsi/imo - only uuid.
                for r in rows_from_zip(zp):
                    lat = pick(r, "lat", "latitude")
                    lon = pick(r, "lon", "longitude")
                    ts = parse_epoch(pick(r, "last_pos_epoch", "last_position_epoch",
                                          "epoch", "last_pos_utc", "last_position_UTC",
                                          "timestamp", "time", "datetime"))
                    uid = pick(r, "uuid", "mmsi", "imo")
                    if not uid or lat in (None, "") or lon in (None, "") or ts is None:
                        continue
                    sp = pick(r, "speed")
                    dist = pick(r, "distance_nm")
                    by_vessel[uid].append((
                        ts, float(lat), float(lon),
                        float(sp) if sp not in (None, "") else None,
                        float(dist) if dist not in (None, "") else None))
        calls = reconstruct(port, by_vessel)
        print(f"  {len(calls)} port calls (any type) - resolving vessel types next",
              flush=True)
        all_calls.extend(calls)

    # The report gave only uuids; look up type+size per vessel and keep dry-bulk.
    all_calls = resolve_and_filter(cli, all_calls)
    all_calls = dedup_across_ports(all_calls)

    n = storage.upsert_calls(conn, all_calls)
    ncsv = storage.export_csv(conn)
    write_xlsx(all_calls, sel)
    preview(all_calls)
    print(f"\nDone. Upserted {n} calls -> {db_path} "
          f"({ncsv} total rows exported to {config.CSV_PATH} + .xlsx)")


def write_xlsx(calls, sel):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        print("  (openpyxl missing - skipping .xlsx)")
        return
    wb = Workbook()
    wb.remove(wb.active)
    hf = PatternFill("solid", fgColor="1F4E78")
    ff = Font(bold=True, color="FFFFFF")

    def sheet(name, rows):
        ws = wb.create_sheet(name[:31])
        ws.append([f.replace("_", " ").strip().title() for f in config.FIELDS])
        for cell in ws[1]:
            cell.fill = hf
            cell.font = ff
        for c in rows:
            ws.append([c.get(k, "") for k in config.FIELDS])
        ws.freeze_panes = "A2"
        for col in ws.columns:
            w = max((len(str(x.value)) for x in col if x.value), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(w + 2, 40)

    sheet("All KSA", calls)
    for pk in sel:
        lbl = PORTS[pk]["label"]
        sheet(lbl, [c for c in calls if c["port"] == lbl])
    Path(config.CSV_PATH).parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(Path(config.CSV_PATH).with_name("ksa_arrivals.xlsx")))


def preview(calls, n=30):
    if not calls:
        print("No calls found.")
        return
    cols = ["port", "vessel_name", "size_class", "dwt", "arrival_utc",
            "departure_utc", "days_in_port", "grain_flag"]
    w = {c: max(len(c), *(len(str(r.get(c, ""))) for r in calls[:n])) for c in cols}
    line = " | ".join(c.ljust(w[c]) for c in cols)
    print("\n" + line)
    print("-" * len(line))
    for r in calls[:n]:
        print(" | ".join(str(r.get(c, "")).ljust(w[c]) for c in cols))
    if len(calls) > n:
        print(f"... {len(calls)-n} more rows in the DB/CSV/XLSX")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _resolve_range(a, floor):
    """Return (frm, to) from the argparse namespace, honouring --since-last."""
    today = date.today()
    if a.since_last:
        conn = storage.connect(config.DB_PATH)
        last = storage.latest_arrival_date(conn)
        conn.close()
        if not last:
            print("--since-last: store is empty, falling back to last 2 years.")
            return max(today - timedelta(days=365 * 2), floor), today
        # Re-scan from a few days before the last recorded arrival so a call
        # that straddled the previous run's cutoff is completed, not split.
        anchor = datetime.strptime(last, "%Y-%m-%d").date() - timedelta(days=3)
        return max(anchor, floor), today
    if a.years_back:
        return max(today - timedelta(days=365 * a.years_back), floor), today
    if a.year:
        frm = max(date(a.year, 1, 1), floor)
        to = min(date(a.year, 12, 31), today)
        if frm >= to:
            sys.exit(f"year {a.year} has no valid range "
                     f"(floor {floor}, today {today})")
        return frm, to
    to = datetime.strptime(a.to, "%Y-%m-%d").date() if a.to else today
    frm = (datetime.strptime(a.frm, "%Y-%m-%d").date() if a.frm
           else max(to - timedelta(days=365 * 2), floor))
    return frm, to


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ports", default="mine",
                    help="comma list of keys, 'mine' (the six), or 'all'. keys: "
                    + ",".join(PORTS))
    ap.add_argument("--from", dest="frm", default=None)
    ap.add_argument("--to", default=None)
    ap.add_argument("--year", type=int, help="shortcut: whole calendar year")
    ap.add_argument("--years-back", type=int, dest="years_back",
                    help="shortcut: from N years ago until today")
    ap.add_argument("--since-last", action="store_true", dest="since_last",
                    help="incremental: resume from the latest arrival in the DB")
    ap.add_argument("--batch", type=int, default=config.BATCH_SIZE,
                    help=f"reports submitted concurrently (default {config.BATCH_SIZE})")
    ap.add_argument("--db", default=config.DB_PATH, help="SQLite path")
    ap.add_argument("--estimate", action="store_true",
                    help="print cost/coverage projection and exit (no credits spent)")
    a = ap.parse_args(argv)

    if a.batch < 1:
        sys.exit("--batch must be >= 1")
    config.BATCH_SIZE = a.batch

    ports_arg = MY_PORTS if a.ports == "mine" else a.ports
    sel = list(PORTS) if ports_arg == "all" else [p.strip() for p in ports_arg.split(",")]
    bad = [p for p in sel if p not in PORTS]
    if bad:
        sys.exit(f"unknown port key(s): {bad}. valid: {list(PORTS)}")

    floor = datetime.strptime(config.DATA_START, "%Y-%m-%d").date()
    frm, to = _resolve_range(a, floor)

    if a.estimate:
        estimate(sel, frm, to)
        return
    try:
        run(sel, frm, to, db_path=a.db)
    except DatalasticError as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
