# Ras Al Khair (Ma'aden) dry-bulk departure count — Bahri vs other

Reconstructs port calls at the Ma'aden terminal, Ras Al Khair (UN/LOCODE SARAZ)
from 37 pre-paid Datalastic `inradius_history` reports covering
12 Nov 2025 → 29 Jul 2026, and counts **dry-bulk departures split into
Bahri-owned hulls vs everyone else**.

## STATUS: pipeline complete and tested; the run is blocked on data access

The numbers have **not** been produced yet. Both Datalastic hosts are blocked by
this environment's egress policy:

```
api.datalastic.com:443     -> gateway answered 403 to CONNECT (policy denial)
report.datalastic.com:443  -> gateway answered 403 to CONNECT (policy denial)
```

`$DATALASTIC_API_KEY` is also unset in this environment. Neither is worked
around here — the report ZIPs are the entire input, so no counts are reported
rather than reporting guessed ones. See "Running it" below.

What *was* verified live (via the Datalastic MCP connector, which egresses
from outside this container):

* All 37 report IDs exist on the account and are `_DONE_`.
* **The Bahri Dry Bulk fleet is unchanged** — all 8 hulls present, no additions,
  nothing hiding under the `Ore Carrier` or `Self Discharging Bulk Carrier`
  subtypes. Details in the run notes.

## Method

Parameters live at the top of `rak_departures.py`, not buried in the code.

| Rule | Value | Flag |
| --- | --- | --- |
| Centre | 27.55828 N, 49.18322 E | — |
| Alongside radius | 4 NM (scans pulled at 20 NM) | `--radius` |
| New port call when gap exceeds | 24 h | `--gap-hours` |
| Discard calls shorter than | 3 h | `--min-call-hours` |
| Departure | last fix of a call | — |
| Arrival | first fix of a call | — |
| Dry bulk | `type_specific` ∈ {Bulk Carrier, Ore Carrier, Self Discharging Bulk Carrier} | — |
| Monthly bucket | on **departure** date | — |

Two details that matter for correctness:

1. **All 37 windows are pooled before splitting into calls.** This is what makes
   a ship alongside across a window boundary come out as one call instead of
   two. Splitting per-window first is the obvious bug, and is exactly what the
   stitching check below is built to catch.
2. **Seam rows are de-duplicated.** Consecutive windows share an endpoint date
   (w01 ends 2025-11-19, w02 starts 2025-11-19), so the same fix appears in both
   reports. Un-deduplicated, these inflate fix counts and distort call durations.

## Running it

```bash
export DATALASTIC_API_KEY=...          # never written to disk by this script
python3 rak_departures.py              # full run
python3 rak_departures.py --radius 3   # sensitivity test
python3 rak_departures.py --zip-dir ./zips   # use pre-downloaded ZIPs, no report API calls
```

The script **never submits a new report** — it only retrieves finished ones
(free) and calls `/vessel_info` (1 credit/vessel, cached to
`cache/vessel_info.json`, so re-runs cost nothing). Presigned URLs are fetched
fresh each run since they expire after ~6 h; the ZIPs are cached on disk.

`--zip-dir` exists so the 37 ZIPs can be supplied out-of-band if API egress
stays blocked; in that mode no Datalastic call is made at all, provided
`cache/vessel_info.json` is populated.

## Outputs

* `out/rak_portcalls.csv` — every reconstructed call, all vessel types
* `out/rak_drybulk.csv` — the dry-bulk subset
* `out/rak_summary.csv` — by month: total dry-bulk departures, Bahri, other, Bahri %
* the monthly table, printed to console

## Verification built into the run

* **Per-window audit line** — raw fix count, how many survived the radius filter,
  and unique vessels, for each of the 37 windows. Hard-fails on a missing or
  empty window.
* **`meta.json` cross-check** — confirms each ZIP really is the window and centre
  it is supposed to be, catching a mislabelled `report_id`.
* **Window stitching test** — counts call endpoints landing within ±30 min of one
  of the 36 interior window seams, against a Poisson expectation from the seams'
  share of the timeline. Excess clustering means windows are not stitching.
* **Parcel-size sanity** — annualises the departure count and compares the implied
  average parcel against Ma'aden's 15–20 Mt/yr throughput and the observed
  average dwt. Flags both under- and over-counting rather than reporting a
  number straight.
* **Bahri spot-check** — pulls `vessel_history` for 3 Bahri calls spread across
  the period and confirms the ship really was at Ras Al Khair then.
* **Fleet re-verification** — re-checks the hardcoded 8 IMOs against
  `vessel_find` on every run and reports additions/removals.

## Tests

```bash
python3 tests/make_fixtures.py /tmp/rak_fixtures     # synthetic ZIPs
python3 tests/test_pipeline.py /tmp/rak_fixtures     # unit tests
```

The fixtures deliberately plant the hard cases: a call straddling the w05/w06
seam, sub-3h passes, anchorage traffic at 8–18 NM, and duplicated seam rows.

The suite includes a **negative control** — it rebuilds calls per-window
(the stitching bug) and asserts the stitching check *catches* it. It does:
691 seam-clustered endpoints against 17.1 expected, p < 0.0001, with the call
count inflated from 1,157 to 1,480. A check that cannot fail is not a check.

## Caveat to carry into the commercial discussion

`bahri_flag` marks **Bahri-owned hulls only**, matched on IMO. Cargo that Bahri
fixes on chartered-in tonnage reads as "Other". The Bahri share is therefore a
**floor** on their commercial role in Ma'aden's supply chain, not a ceiling.
