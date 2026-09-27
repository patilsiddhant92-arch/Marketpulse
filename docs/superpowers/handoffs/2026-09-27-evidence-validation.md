# Evidence engine — validation run (2026-09-27)

Branch `feat/e1-evidence`. Spec: `docs/superpowers/specs/2026-09-26-marketpulse-professional-rebuild-design.md` §5, §6.1.5, §7.6.
Code: `Scripts/evidence/` (package), `App/services/evidence.py`, `App/services/research.py`, tests `tests/test_evidence_*.py` (29 tests).

## How it was run

- Input: a **copy** of the live DB (`Database/marketpulse.duckdb`, 594 sessions 2024-05-06 → 2026-09-25, 1.25 M indicator rows),
  opened read-only. `regime_daily` / `group_daily` / `setup_daily` came from the derived-tables agent's validation DB
  (`--derived-db`), because the live DB does not have them yet. PR archive `Input/archive/backfill/pr` (605 zips in range)
  gave point-in-time market cap, board meetings (results dates) and corporate actions.
- Command:
  `python -m Scripts.evidence.run --db <copy>.duckdb --derived-db <derived>.duckdb --out <evidence>.duckdb --pr-dir Input/archive/backfill/pr`
- The CLI never writes `--db` (it refuses `--out == --db`; a test checks the market file hash is unchanged).

## Timings, memory, row counts

| stage | seconds | working set / peak MB |
| --- | --- | --- |
| load (DuckDB → pandas; PR archive from cache) | 6.5 | 695 / 1,150 |
| point-in-time mcap | 3.3 | 675 / 1,150 |
| setups (setup_daily + historical momentum) | 3.4 | 734 / 1,150 |
| setup outcomes + context | 4.2 | 739 / 1,150 |
| market analogs | 1.8 | 745 / 1,150 |
| stock-day features | 7.0 | 990 / 1,272 |
| big moves (events, controls, lift, precision, paths, catalysts, studies) | 30 | 756 / 1,272 |
| **build total** | **≈ 57** | **peak 1.26 GB** |
| write 17 tables | 4.2 | |

- First run parses the PR zips (~75 s for 605 zips) and caches them next to the output DB (`pr_archive_<hash>.pkl`).
- Without `setup_daily`, the historical darvas_squeeze / vcp / momentum queues are built from indicators: +4 s
  (VCP kernel re-implements `detect_contractions` on precomputed fractals: identical output, 126 s → 9 s).
- **Scaling check:** the same build on a 2× synthetic copy (2.49 M rows, all queues historical) took 107 s with a
  2.0 GB peak. Linear extrapolation to the 5-year rebuild (~5 M rows, ~1,700 sessions): **~4 min and ~4 GB**, plus
  ~3.5 min for the first PR-archive parse (1,750 zips; cached afterwards). Inside the 10 min / 6 GB budget.
- Machine note: during this session the system commit charge sat at 58–64 of 65 GB because
  `DellSupportAssistRemedationService` held ~25 GB private memory; two runs failed with MemoryError on small
  allocations until it eased. Not caused by this job.

| table | rows |
| --- | --- |
| setup_outcomes | 36,670 |
| setup_outcome_stats | 164 |
| environment_calibration | 30 |
| market_env_daily | 594 |
| market_analogs | 3,900 (390 query sessions × 10) |
| market_analog_validation | 3 |
| big_move_events | 2,355 eligible (7,186 candidates) |
| big_move_features | 760,800 (long) |
| big_move_controls | 5,253 |
| big_move_lift | 50 (25 features × {all, upper_circuit}) |
| big_move_precision | 30 |
| big_move_paths | 972 |
| big_move_catalyst_stats | 15 |
| big_move_group_stats | 266 |
| group_entry_study | 8 |
| pre_move_watch | 7,182 (last 60 sessions) |
| evidence_meta | 16 |

Sources recorded in `evidence_meta`: price basis **raw** (no `adj_*` columns yet; picked up automatically when they
land), market cap **pr_mcap for all 1,244,446 stock-days** (no fallback needed on this range), environment =
`regime_daily.verdict`, group quadrant = `group_daily.rrg_quadrant` (Industry, floor all).

## Definitions (short)

- **Setup outcome** (one row per setup identity; identity resets after ≥ 5 absent sessions): fill = next session's
  high ≥ that day's trigger while the symbol is in the queue, entry = max(open, trigger); R = entry − stop;
  exit = stop (low ≤ stop; gap-down fills at the open) or the close of the 20th session; `hit_1r`/`hit_2r` = target
  reached strictly before the stop day (same-day tie counts as stop). `open` (not enough forward bars) and `no_fill`
  rows have no R and are never counted. Aggregates: n < 30 ⇒ "insufficient sample", numbers NULL.
- **Momentum** (evidence-only queue): Minervini template passes, strength rank ≥ 70, within 15 % of the 52W high,
  close ≥ 10 EMA; trigger = 10-day high, stop = 10-day low, dropped if risk > 15 %.
- **Market analogs:** 16-feature daily vector (breadth % > 10/50/200 EMA, A/D 5/20-day, net new 252-day highs,
  MidSml400 and Nifty vs 50/200 EMA and returns, VIX level and 5-day change, breakout follow-through). z-scored with
  statistics known on the query date only; k = 10 nearest by Euclidean distance among dates ≥ 60 sessions earlier,
  picked ≥ 10 sessions apart (distinct episodes).
- **Big move:** confirmation day = upper circuit (high ≥ prev close × (1 + band) × 0.9995) | close ≥ 1.30 × lowest
  close of the previous 20 sessions | close ≥ 1.50 × lowest close of the previous 60. Episodes end after 20 quiet
  sessions. Event date T = the circuit day, else the session after the look-back low. Eligible: EQ, mcap at T−1
  ≥ ₹1,000 Cr (point-in-time), 20-day ADV ≥ ₹1 Cr, ≥ 60 sessions of history. `confirmed_date` is when the move
  became knowable (the API hides events before it, and nulls 60-session outcomes while the window is open).
- **Controls:** same T−1 date, same Industry and mcap quintile (fallback Broad Industry → Sector → adjacent
  quintile), no confirmation day in [T−20, T+60], up to 3 per event, seed 42.
- **Hygiene:** every feature is computed from rows dated ≤ its date (tests truncate data and compare); lift is
  reported on a chronological split with a 60-session embargo (test ≥ 2025-10-09, train ends 60 sessions earlier); the watch-list
  rule and traits are selected on train and their precision is printed from test.

## 1. Setup outcomes per queue (all environments)

| queue | n closed | signals | fill % | hit 1R % | hit 2R % | win % | avg R | median R | MAE % | MFE % | days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| darvas_10ema | 17,359 | 22,092 | 79.7 | 41.6 | 23.5 | 25.5 | −0.16 | −1.00 | −5.5 | 7.4 | 10.5 |
| darvas_squeeze | 6,463 | 10,235 | 64.1 | 45.9 | 25.0 | 30.2 | −0.15 | −1.00 | −5.4 | 7.1 | 11.9 |
| vcp | 975 | 1,650 | 61.5 | 36.2 | 16.4 | 33.8 | −0.16 | −1.00 | −7.2 | 8.1 | 14.2 |
| momentum | 1,768 | 2,693 | 70.9 | 36.3 | 14.3 | 42.7 | −0.04 | −0.27 | −7.5 | 9.2 | 16.1 |
| **all** | 26,565 | 36,670 | 73.9 | 42.1 | 23.0 | 28.1 | −0.15 | −1.00 | −5.7 | 7.5 | 11.4 |

Read: with the Desk's own stops (squeeze: 10 EMA × 0.985; VCP: last-T low; 10 EMA: lowest low since the touch) the
median trade is stopped out (−1 R); ~42 % reach +1 R first but the 20-session hold gives most of it back. Nothing is
positive on average over this 2024-05 → 2026-09 window.

### Per environment state and the §6.1.5 ship gate

| queue | Favourable | Constructive | Mixed | Weak | Danger |
| --- | --- | --- | --- | --- | --- |
| all | −0.41 (n 1,808) | −0.03 (3,173) | −0.19 (14,384) | −0.01 (4,748) | −0.12 (2,452) |
| darvas_10ema | −0.49 (1,041) | −0.03 (1,934) | −0.20 (9,315) | +0.03 (3,204) | −0.22 (1,865) |
| darvas_squeeze | −0.36 (509) | −0.07 (922) | −0.18 (3,735) | −0.08 (913) | +0.16 (384) |
| vcp | −0.42 (74) | +0.09 (89) | −0.19 (463) | −0.08 (270) | −0.26 (79) |
| momentum | −0.05 (184) | +0.07 (228) | −0.11 (871) | −0.09 (361) | +0.49 (124) |

(avg R, n.) **Ship gate FAILS for every queue**: avg R(Favourable+Constructive) − avg R(Weak+Danger) = −0.12 R
(all; Welch t −3.1; n 4,981 vs 7,200), −0.13 (10 EMA), −0.17 (squeeze), −0.02 (VCP), −0.04 (momentum).
"Favourable" is the *worst* state for new setups in this sample (breakouts bought late in extended markets).
Per §6.1.5 the verdict rules must be recalibrated before the proof table ships; `environment_calibration` is the
table to re-run after any rule change. Group quadrant helps a little: setups in a Leading Industry averaged
−0.09 R (n 6,652) vs −0.26 Lagging (6,708) and −0.29 Improving (5,076).

## 2. Market analogs for 2026-09-25 (first 5 of 10)

| rank | analog date | distance | MidSml400 +5 | +20 | +60 | next-month follow-through % | verdict then |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-06-09 | 0.425 | +2.1 % | +2.2 % | +5.2 % | 47.4 | Mixed |
| 2 | 2025-09-01 | 0.550 | +0.9 % | −0.4 % | +4.1 % | 46.8 | Mixed |
| 3 | 2025-08-04 | 0.581 | −1.9 % | −0.2 % | +2.8 % | 40.6 | Weak |
| 4 | 2026-02-13 | 0.585 | +0.0 % | −7.7 % | +2.0 % | 30.7 | Weak |
| 5 | 2026-01-30 | 0.673 | +1.7 % | +2.5 % | +3.6 % | 41.8 | Danger |

All 10: +20-session median ≈ −0.3 %, 4 up / 6 down ⇒ the API flags "analogs disagree". 60-session: 8 of 10 positive.
**Skill check** (`market_analog_validation`, analog-mean vs realised forward return over all query dates; overlapping
windows so n is serially correlated): corr 0.12 (5d, n 385), 0.27 (20d, n 370), 0.07 (60d, n 330); sign agreement
45–51 %. Treat analogs as context, not a forecast, until the 5-year history is in.

## 3. Big movers: fingerprint features (T−1, movers vs matched controls)

2,355 eligible events (UC 804, +30 %/20d 1,247, +50 %/60d 304); median move 27 % (UC) / 47 % / 49 %; median mcap
₹3,000–6,200 Cr. 1,193 test events, 1,011 train.

All events — top by lift, with n:

| trait (T−1) | movers % | controls % | lift | movers with trait | n movers / controls | lift train → test | stable OOS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 20-day range ≥ 25 % | 34.1 | 17.0 | 2.01 | 804 | 2,355 / 5,253 | 1.70 → 2.40 | yes |
| delivery spike | 13.2 | 8.4 | 1.57 | 310 | 2,355 / 5,253 | 1.33 → 1.75 | yes |
| RVOL ≥ 1.5 | 23.9 | 16.1 | 1.49 | 562 | 2,355 / 5,253 | 1.31 → 1.61 | yes |
| 10-day range ≥ 15 % | 49.3 | 33.3 | 1.48 | 1,160 | 2,355 / 5,253 | 1.32 → 1.70 | yes |
| 5-day delivery ≥ 1.2 × 20-day | 5.1 | 3.9 | 1.28 | 119 | 2,348 / 5,245 | 1.29 → 1.30 | yes |
| results meeting within ±5 sessions | 19.9 | 16.9 | 1.18 | 469 | 2,355 / 5,253 | 1.12 → 1.22 | no |
| corporate action within ±5 | 0.5 | 0.2 | 2.23 | 11 | 2,355 / 5,253 | 2.96 → 2.23 | no (11 hits) |
| deal (ex-PROP) in last 5 sessions | 2.9 | 1.4 | 2.11 | 11 | 379 / 872 | test only (deals start 2026-04-29) | no |
| 50-day base depth ≤ 25 % | 21.4 | 38.0 | 0.56 | 505 | 2,355 / 5,253 | 0.63 → 0.50 | (negative) |
| within 10 % of 52W high | 5.8 | 7.4 | 0.79 | 137 | 2,355 / 5,253 | 0.75 → 0.80 | (negative) |

Upper-circuit events only (T = the circuit day, so no trough bias): delivery spike **2.28** (139 of 804; 1.97 → 2.71),
RVOL ≥ 1.5 **2.00** (224; 1.93 → 2.10), 20-day range ≥ 25 % **1.94** (205; 1.58 → 2.43), **results meeting within
±5 sessions 1.52** (218; 1.82 → 1.35), 10-day range 1.36, 20-day return ≥ 10 % 1.33 — all stable out of sample.
Strength rank, Leading group (any level), tight bases, dry-up and VCP-style contraction show **no** lift (≈ 1.0).

Caveat: for +30 %/+50 % events T−1 is the look-back low by construction, which depresses return and 52W-distance
traits vs controls; read those on the UC subset (`big_move_lift.subset = 'upper_circuit'`, API
`meta.context.lift_upper_circuit`).

Median path (movers vs controls): RVOL 0.73 vs 0.72 at T−60 → 0.90 vs 0.78 at T−1 → 1.45 on T; 10-day range 12.7 vs
11.3 % at T−60 → 14.8 vs 12.6 % at T−1; delivery % dips on T (37.7 vs 47.8) as speculative volume arrives.
Movers are wider-ranging, not quieter, before the move.

**Precision** (eligible stock-days, test period, base rate 8.1 % start a big move within 20 sessions): the watch rule
chosen on train is *20-day range ≥ 25 % & 10-day range ≥ 15 %*: 12.3 % (n 33,837 stock-days; train 10.4 % vs 7.0 %)
= 1.52× base. Range ≥ 25 % & delivery spike: 12.7 % (n 5,100). This is mostly a volatility effect; the pre-move
watch (~120 names/day) stays labelled research.

**Catalysts** (±3 sessions, post-hoc): results 15.9 %, sector-wide (≥ 50 % of the Industry up ≥ 10 % over
T−1…T+19) 30.6 %, deal 1.8 % (10.8 % where deal data exists, n 398), corporate action 0.3 %, unexplained 54.4 %.

**Taxonomy:** by Broad Sector, Industrials lead (634 events, 4.9 per 1,000 eligible stock-days, lift 1.34); by
Industry (n ≥ 30): Aerospace & Defense 1.81 (59 events, median move 54 %), Other Textile Products 1.65, Other Electrical
Equipment 1.64, Gems & Jewellery 1.53, Heavy Electrical Equipment 1.49. **Group entering Leading** (RRG, equal-weight
members minus MidSml400): no follow-through — Industry +20d −0.49 pts (n 1,656, 42 % positive), +60d −1.71 pts
(n 1,537); same sign at every level.

## Wiring into the EOD run (controller)

After `write_derived_tables` (needs regime_daily / group_daily / setup_daily in the same DB):

```python
from Scripts.evidence import build_evidence_tables, write_evidence_tables
tables = build_evidence_tables(con, pr_dir=ROOT / "Input/archive/backfill/pr", cache_dir=ROOT / "Database")
write_evidence_tables(con, tables)   # CREATE OR REPLACE the 17 tables
```

Full recompute each night (≈ 1 min today, ≈ 4 min on 5 years). The API reads the tables directly
(`/api/v2/evidence/{setup}`, `/research/analogs`, `/research/big-moves[/{id}]`, `/research/pre-move`,
`/research/group-studies` (new), `/stock/{sym}/analogs`).

## Known gaps

- Prices are raw until `prices_daily.adj_*` exists (split/bonus ex-dates can fake or hide moves; the loader switches
  automatically). Taxonomy is current-mapping. Band for UC is point-in-time only from 2026-07 (else current band).
- Deals only from 2026-04-29 ⇒ deal traits have no train period; `deal_session_net` is not used yet.
- Ship gate fails (above) — verdict rules need recalibration; analogs show little skill on 2.4 years.
- Stock analogs return 30 neighbours (distribution needs n ≥ 30); UI may show the first 10.
- New route `/research/group-studies` (`GroupStudyRow`); `openapi.json` and `types.gen.ts` regenerated.
