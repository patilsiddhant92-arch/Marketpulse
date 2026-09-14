# Phase 2: Sector/Thematic Index RS + Bench Toggle Design

**Date:** 2026-09-14  
**Status:** Approved for plan  
**Branch:** `feat/truth-contract` (PR #2)  
**Depends on:** Phase 1 true RS vs Nifty 50 / MidSml 400 (shipped)

## Goal

1. Persist official membership for MarketPulse `CANONICAL_44` sectoral + thematic indices (as-is from Index Desk).
2. Compute stock excess RS vs the stock's **mapped** index (membership primary).
3. Compute each of the 44 indices' excess RS vs a broad bench.
4. UI bench control: **NIFTY MIDSML 400 default**, **Nifty 50 selectable**.
5. No screener hard gates in v1.

## Non-goals

- Expanding beyond `CANONICAL_44` (Power / NBFC / Insurance etc. stay mismatch-report only).
- Point-in-time historical constituents (use as-of snapshot `2026-09-14` until a refresh pipeline exists).
- Changing peer `rs_percentile` or Darvas / VCP gates.
- Soft taxonomy as primary mapper (fallback only).

## Inputs already available

| Asset | Status |
|-------|--------|
| `index_daily` OHLC for all 44 + Nifty 50 + MidSml 400 | 420 sessions each |
| Stock true RS vs benches | `rs_vs_nifty50_21d/63d`, `rs_vs_midsml400_21d/63d` on `indicators_daily` |
| Official membership | Index Desk: `/workspace/index-desk/mp44_membership.csv` — **44/44**, **1,283** rows |
| Name map | `mp_index_name` (MP / `index_daily`) ↔ NSE official spelling in same CSV |
| Soft map | `App/thematic_engine.py` `INDEX_THEMATIC_MAP` — fallback only |

## Membership table

Persist as DuckDB table `index_constituents`:

| Column | Notes |
|--------|-------|
| `index_name` | NSE table spelling (e.g. `NIFTY AUTO`) |
| `mp_index_name` | MarketPulse / `index_daily.index_name` (e.g. `Nifty Auto`) |
| `symbol` | NSE equity symbol |
| `as_of_date` | Snapshot date |
| `category` | Sectoral \| Thematic (from `CANONICAL_44_INDICES`) |

Source of truth for v1 seed: copy `mp44_membership.csv` into repo under `Input/reference/mp44_membership.csv` (or `data/`) and load on build/append/migrate.

**Refresh:** Index Desk / niftyindices constituent CSVs (NSE `equity-stockIndices` API currently 404). Re-run seed script; do not invent rows.

## Mapping rules (stock → one index)

1. Collect all `mp_index_name` where `symbol` ∈ `index_constituents`.
2. If **exactly one** → that index.
3. If **several** (286 symbols today):
   - Prefer **Sectoral** over **Thematic** (`CANONICAL_44_INDICES.category`).
   - Then prefer **narrower** name (heuristic: longer `clean_name` / more specific industry-like index, e.g. `Nifty Pvt Bank` over `Nifty Bank`; `Nifty FinSerExBnk` over `Nifty Fin Service` when both Sectoral).
   - Deterministic tie-break: sort by `(category_rank, specificity_score, mp_index_name)` and take first.
4. If **none**: soft `INDEX_THEMATIC_MAP` (industry → sector → tag); if still none → `sector_index_name` NULL and stock-vs-index excess NULL (fail closed).
5. Persist chosen name on indicators as `sector_index_name` (string, nullable).

## RS formulas

Reuse `Scripts/true_rs.py` `excess_vs_index`:

```
excess_Nd = (leg_close_t / leg_close_t-N - 1 - bench_close_t / bench_close_t-N + 1) * 100
```

Fail closed when either leg lacks N aligned sessions.

### Columns (indicators_daily)

| Column | Meaning |
|--------|---------|
| `sector_index_name` | Mapped `mp_index_name` or NULL |
| `rs_vs_sector_index_21d` | Stock excess vs mapped index, 21d |
| `rs_vs_sector_index_63d` | Stock excess vs mapped index, 63d |

Existing bench columns unchanged:

- `rs_vs_nifty50_21d/63d`
- `rs_vs_midsml400_21d/63d`

### Index-vs-bench (new small table or columns on a view)

Table `index_bench_rs_daily` (or enrich thematic leaderboard query):

| Column | Meaning |
|--------|---------|
| `trade_date` | |
| `mp_index_name` | One of 44 |
| `rs_vs_nifty50_21d/63d` | Index excess vs Nifty 50 |
| `rs_vs_midsml400_21d/63d` | Index excess vs MidSml 400 |

## UI

- **Bench control** (Stock 360 header and/or Sector Intel / thematic board): toggle **MidSml 400 (default)** | **Nifty 50**.
- Stock 360 chips:
  - Default: `vs MS400 63d` (and 21d optional); when toggled: `vs N50 …`.
  - If `sector_index_name` set: `vs {short_name} 63d` using `rs_vs_sector_index_*`.
- Thematic / Sector Intel: show each of 44 with excess vs **selected** bench (default MidSml).
- No hard screener filters on these columns in v1.

## Wiring

- Seed / migrate `index_constituents` from CSV.
- Extend `attach_true_rs_columns` (or sibling `attach_sector_index_rs`) in build/append path after membership join.
- Materialize script for one-shot backfill on live DB (chunked, same pattern as Phase 1).
- Thematic leaderboard / sector read model: join `index_bench_rs_daily` or compute on the fly from `index_daily` (420 sessions is enough for 63d).

## Risks

| Risk | Mitigation |
|------|------------|
| Multi-membership ambiguity | Deterministic Sectoral > Thematic + specificity; show chosen name in UI |
| FinSrv25/50 CSV ≈ Fin Service symbols | Noted by Index Desk; re-check on next refresh; still map as-is |
| Name drift MP ↔ NSE | Keep `mp_index_name` as join to `index_daily`; store NSE spelling separately |
| Soft fallback disagreement with membership | Membership always wins when present |
| Snapshot staleness | `as_of_date` column + Index Desk refresh playbook |

## Success criteria

1. `index_constituents` has 44 distinct `mp_index_name` and ≥1,200 rows.
2. ≥70% of latest-session tradable symbols (mcap gate optional) have non-null `sector_index_name` **or** documented soft-fallback rate.
3. `rs_vs_sector_index_63d` non-null for membership-mapped names with ≥63 overlapping sessions.
4. All 44 have non-null `rs_vs_midsml400_63d` on latest `index_daily` date.
5. UI default chip/board uses MidSml 400; toggling to Nifty 50 switches displayed excess without recompute of peer RS.
6. Tests: membership load, mapper determinism, excess unit tests, bench coverage contract.
7. No change to Darvas / VCP / `rs_percentile` gates.

## Open follow-ups (not v1)

- Historical PIT constituents.
- Add Power / NBFC / Insurance to CANONICAL set.
- Screener gates on sector-index excess.
