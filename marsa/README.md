# MARSA — a Gulf grain-flow intelligence engine

*Maritime Arrivals & Regional Supply Analytics. مرسى — anchorage.*

Reconstruct KSA dry-bulk port calls from AIS, capture berth draughts **live**,
and turn Δdraught into cargo tonnage — weeks ahead of any official figure, plus
a berth-level performance measure no official figure covers at all.

This is the Phase 0 / Phase 1 code foundation: the two divergent Drive copies of
`arrivals_pipeline.py` converged onto one codebase, an idempotent SQLite store,
incremental runs, and — most importantly — the **live draught capture that must
start now**, because that history compounds and cannot be backfilled.

---

## Why "start now"

`inradius_history` returns position, speed, course and destination — **no
draught**. Draught is crew-reported and only observable live, so a laden import,
a ballast call and an export loading are indistinguishable in the historical
data. Δdraught is what separates them, and it can only be captured going forward.
Every week `draught_capture` doesn't run is a week of Δdraught that will never
exist. Run it daily from day one.

## Quickstart

```bash
cd marsa
pip install -r requirements.txt          # requests, openpyxl
cp .env.example .env                      # then paste your ROTATED key (see below)

# Phase 0 — start the compounding history (safe, cheap, runs anywhere):
python -m marsa.draught_capture --plan            # show plan, spend nothing
python -m marsa.draught_capture --ports mine      # daily live capture
python -m marsa.discover_berths --ports mine      # help fill the grain geofences

# Phase 1 — historical backfill (needs unfirewalled net; resumable, idempotent):
python -m marsa.arrivals_pipeline --estimate --year 2025   # projection, no spend
python -m marsa.arrivals_pipeline --year 2025             # one calendar year
python -m marsa.arrivals_pipeline --since-last            # incremental catch-up
```

Outputs land in `out/` (git-ignored): `marsa.db` (the SQLite store of record),
`ksa_arrivals.csv` / `.xlsx`, and cached report ZIPs under `out/raw/`.

## Build order

- **Phase 0 — prove it.** `draught_capture` daily + fill the grain-berth
  geofences (`discover_berths`, then edit `config.py`). Nothing downstream turns
  ship movements into *grain* flow until those geofences are populated.
- **Phase 1 — the data platform.** `arrivals_pipeline` (converged), SQLite keyed
  on `(uuid, arrival_date)` so re-runs are idempotent, `--since-last`, weekly
  schedule. *(this foundation)*
- **Phase 2 — the physics.** TPC model (`tpc.py`, seeded here), draught state
  machine, per-call tonnage with confidence. **Publish nothing** until three
  months of calibration against a published benchmark (GASTAT).
- **Phase 3 — upstream.** Fleet watchlist, origin-terminal geofences, ETA model,
  commodity classifier.
- **Phase 4 — the product.** Weekly index, dashboard, API.

## Package layout

| Module | Role |
|---|---|
| `config.py` | Ports, grain-berth geofences, classification, constants — the single source of truth |
| `datalastic_client.py` | Datalastic API wrapper: async report lifecycle + live GETs (`vessel_pro` carries draught) |
| `geofence.py` | Great-circle distance + grain-berth inference (pure, unit-tested) |
| `storage.py` | SQLite store; idempotent `(uuid, arrival_date)` upsert; `draught_snapshots` append-only |
| `tpc.py` | Displacement physics: TPC and *indicative* Δdraught→tonnage (Phase 2 seed) |
| `arrivals_pipeline.py` | Phase 1 historical backfill (converged Folder-A logic) |
| `draught_capture.py` | **Phase 0** live draught capture — the forward-only history |
| `discover_berths.py` | Pulls port `terminals[]` to help fill the grain geofences |

## Credit budget (Datalastic Starter, ~20k/month)

- **Live capture:** 1 credit/vessel found + 3 credits per new dry-bulk hull/day
  (`vessel_pro`), capped by `--max-pro`. ~50–100 credits/day across six ports.
- **Backfill:** a flat ~100 credits per 7-day window per port. A full year × 6
  ports ≈ 31k credits, so run **`--year` by year** and let the ZIP cache resume
  across monthly cycles. `--estimate` prints the projection before any spend.

## Data honesty (read before quoting a number)

- **AIS has no cargo field.** "Grain" is *inferred* from berth geofence, with a
  confidence. With geofences empty every call reads `Unknown` — that is honest,
  not broken. Don't quote grain tonnage until the geofences are filled *and* the
  physics is calibrated.
- **Tonnage is indicative until calibrated.** `tpc.py` ignores salinity and
  trim bias by design; both are calibratable against GASTAT, not guessable.
- **AIS is not truth.** Gaps, spoofing and transponder silence are real and
  worst on the Red Sea approaches to Jeddah/Yanbu. Carry confidence intervals
  from day one.

## Security & licensing

- **The API key was leaked** in plaintext across four Drive files. It has been
  removed from all source here. **Rotate it in the Datalastic dashboard** and
  put the new one in `.env` (git-ignored) before first use. Never commit `.env`.
- **Redistribution rights.** A Datalastic Starter plan almost certainly does not
  permit redistributing AIS-derived data commercially. Phases 0–2 as an internal
  capability are clean; settle the licence (and the employment/IP question)
  before Phase 4.

## Tests

```bash
pip install pytest && python -m pytest -q      # 16 tests, all network-free
```
