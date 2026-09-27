# True RS vs Benchmark — Design

**Date:** 2026-09-14  
**Branch:** feat/truth-contract (PR #2)  
**Status:** Design locked for review — **no implementation until Siddhant approves this file**  
**Backfill source (locked):** NSE CM Market Activity date archives (not Yahoo)

## Problem

Action Desk `rs_percentile` is a **cross-sectional peer rank** of multi-quarter stock returns. It does **not** answer: "Did this stock outperform Nifty 50 / MidSml 400 over N sessions?"

Sector metrics already have `rs_vs_nifty_21d/63d` (group return minus Nifty 50). Stocks do not.

## Goals

1. Persist **stock excess return vs Nifty 50** and **vs NIFTY MIDSML 400** for 21d and 63d (primary desk horizons).
2. Backfill `index_daily` for those benches to **>=252 sessions** via official NSE CM Market Activity reports (date-walk).
3. Keep existing `rs_percentile` unchanged (complementary, not replaced).
4. Optional soft **stock vs sectoral index** RS via taxonomy / `INDEX_THEMATIC_MAP` — phase 2.
5. Official NSE thematic **constituent membership** — out of scope.

## Non-goals

- Replacing IBD-style or peer `rs_percentile` formulas.
- Yahoo Finance backfill as source of truth (existing `backfill_index_history.py` stays available but is not this plan's path).
- Index constituent lists / membership-pure thematic RS.
- Wiring new RS into screener hard gates in v1 (display + contract first).

## Current facts

| Asset | Reality |
|---|---|
| `index_daily` | Already has Nifty 50, `NIFTY MIDSML 400`, 100+ sectoral/thematic names from MA files |
| Coverage (live DB) | ~52 sessions (2026-07-02 to 2026-09-11) — too short for 63d/252d excess |
| Ingest path | `Scripts/index_history.py` (`parse_market_activity`, `load_all_market_activity_history`) used by `build_database` / staged MA files |
| Download | `Scripts/download_nse_reports.py` label `market activity` / `CM-MARKET-ACTIVITY-REPORT` |
| User URL pattern | NSE reports API with `CM - Market Activity Report` and `date=DD-Mon-YYYY` |
| Stock RS today | Cross-sectional rank in `build_database.py` to `indicators_daily.rs_percentile*` |
| Sector vs Nifty | `sector_metrics_daily.rs_vs_nifty_*` via `Scripts/sector_metrics.py` |

## Definitions (contract)

For each stock `s` and trade_date `t`:

```
ret_N(s,t)     = close(s,t) / close(s,t-N_sessions) - 1
ret_N(idx,t)   = close(idx,t) / close(idx,t-N_sessions) - 1
rs_vs_idx_Nd   = (ret_N(s,t) - ret_N(idx,t)) * 100   # excess percentage points
```

- Session lag uses **trading sessions** in the stock calendar; index close must exist on the same `trade_date` (inner join). Fail closed to NULL if either leg missing.
- Index name keys (exact `index_daily.index_name`):
  - Nifty 50 → `"Nifty 50"`
  - Mid-small → `"NIFTY MIDSML 400"` (confirm spelling against live DB; do not invent aliases without a map)

### New columns on `indicators_daily`

| Column | Meaning |
|---|---|
| `rs_vs_nifty50_21d` | Excess % pts vs Nifty 50 over 21 sessions |
| `rs_vs_nifty50_63d` | Excess % pts vs Nifty 50 over 63 sessions |
| `rs_vs_midsml400_21d` | Excess % pts vs NIFTY MIDSML 400 over 21 sessions |
| `rs_vs_midsml400_63d` | Excess % pts vs NIFTY MIDSML 400 over 63 sessions |

Optional later (not v1): `rs_vs_nifty50_252d`, percentile-of-excess ranks.

### Display (v1, after data exists)

- Stock 360 / AD inspector: chips `vs N50 63d: +4.2` / `vs MS400 63d: -1.1` (NULL → hide or `n/a`).
- Do **not** hard-gate Darvas / VCP on these in v1.

## Backfill approach (locked)

1. Date-walk NSE CM Market Activity archives for each missing trading day until Nifty 50 and NIFTY MIDSML 400 each have **>=252** distinct sessions (prefer >=400 for headroom).
2. Stage files using existing download/stage conventions under the project's NSE input folders (extend `download_nse_reports.py` or a thin sibling that hits the reports API with the same session headers NSE expects).
3. Parse via `index_history.parse_market_activity` / `load_all_market_activity_history` — no parallel parser.
4. Merge into `index_daily`, re-run `build_index_features`.
5. Recompute stock excess columns in indicator build / append path.
6. Honesty: if backfill < 63 sessions for an index, leave stock `rs_vs_*_63d` NULL (fail closed). Never fabricate.

### Rate-limit / ops notes

- NSE endpoints need browser-like headers/cookies; reuse patterns from `download_nse_reports.py`.
- Throttle date-walk; resume from last staged date; idempotent re-parse.

## Phase 2 (deferred)

- Soft `rs_vs_sector_index_63d`: map stock sector/industry to canonical sectoral index via `INDEX_THEMATIC_MAP`, then same excess formula.
- Official constituent membership tables — separate project.

## Success criteria

1. Spec approved by Siddhant.
2. After build: `index_daily` has >=252 sessions for `"Nifty 50"` and `"NIFTY MIDSML 400"`.
3. `indicators_daily` has the four columns; smoke: median `|rs_vs_nifty50_63d|` finite for liquid names; NULL when history short.
4. Existing `rs_percentile` tests still green; AD queues unchanged.
5. UI chips optional in same PR or follow-up — data contract first is enough to call phase 1 done.

## Risks

| Risk | Mitigation |
|---|---|
| NSE blocks scrapes | Session headers, throttle, manual drop-in of MA files still parse |
| Index name drift | Single canonical map + assert in tests |
| Calendar mismatch stock vs index | Inner join on `trade_date`; NULL if index missing that day |
| Confusing traders (percentile vs excess) | Different labels: keep `RS%ile` vs `vs N50` |

## Approval

Reply **approve spec** to proceed to implementation against `docs/superpowers/plans/2026-09-14-true-rs-vs-bench.md`.  
Reply with edits if anything should change first.
