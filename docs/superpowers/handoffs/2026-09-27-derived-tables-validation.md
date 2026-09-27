# Step 2d — derived tables: live-DB validation (2026-09-27)

Branch `worktree-agent-acf86433fc3b6986e` (base d871ff9, same as feat/w2-derived). Package `Scripts/derived/`,
column docs in `Scripts/derived/SCHEMA.md`, tests `tests/test_derived_*.py` (42 synthetic tests, no live-DB access).

**Input:** live `Database/marketpulse.duckdb` opened `read_only=True`, frames loaded in-process (594 sessions,
2024-05-06 → 2026-09-25, **unadjusted** prices). **Output:** written only to a scratch DuckDB in the session scratchpad.
Nothing under `Database/` was written.

## Run

`build_derived_tables(prices, indicators, index_daily, master, deals, breadth, reference, setup_workers=3)` →
`write_derived_tables(scratch_con, tables)` → `incremental_setup_args(scratch_con)` → incremental re-run.

| Builder | Full build (s) | Rows | Incremental pass (s)¹ |
| :--- | ---: | ---: | ---: |
| regime_daily | 3.3 | 594 | 22.5 |
| group_daily | 13.5 | 317,799 | 101.9 |
| setup_daily | 640.5 (3 workers) | 189,603 | 80.0 (last 5 sessions recomputed) |
| deal_session_net | 10.4 | 3,500 | 8.6 |
| write (4 tables + indexes) | 22.5 | | |

¹ The second pass ran while the machine was saturated by other agents: group_daily did identical work in 13.5 s vs 101.9 s.
Treat those numbers as upper bounds. An earlier unloaded measurement: group_daily 29 s under tracemalloc, setup_daily incremental (5 sessions) 21 s.

- Builder errors: none. **Incremental setup_daily == full rebuild: True** (frame-equal).
- group_daily meets the < 60 s target on 1.25 M indicator rows (13.5 s; peak ≈ 1 GB).
- setup_daily full history costs ≈ 1 ms per candidate window (detect_contractions / classify_darvas_10ema_frame): ~11 min
  with 3 workers on 594 sessions (18.6 min serial under load). A 5-year rebuild should use `setup_workers=3`; daily appends use
  `incremental_setup_args` (seconds to tens of seconds).
- Squeeze queue on 2026-09-25 = **71** names, the same as the "true queue 71" count from the spec audit.

## rows
| t | n | lo | hi |
|---|---|---|---|
| regime_daily | 594 | 2024-05-06 | 2026-09-25 |
| group_daily | 317799 | 2024-05-06 | 2026-09-25 |
| setup_daily | 189603 | 2024-05-17 | 2026-09-25 |
| deal_session_net | 3500 | 2026-04-29 | 2026-09-25 |

## last 60
| date | verdict | rule_id | n_days | T P L F S | midsml | pct50 | pct200 | nh | nl | ft | dd | vix | timing_state | readings | alert |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-03 | Mixed | R9 | 7.0 | NNHNN | 21111.0 | 61.0 | 41.0 | 130.0 | 17.0 | 50.0 | 4.0 | 11.8 | normal | 0 | False |
| 2026-07-06 | Favourable | R6 | 1.0 | HNHHH | 21198.0 | 59.0 | 41.0 | 132.0 | 17.0 | 51.0 | 3.0 | 11.8 | normal | 0 | True |
| 2026-07-07 | Mixed | R9 | 1.0 | NNHNN | 21110.0 | 56.0 | 40.0 | 92.0 | 15.0 | 45.0 | 4.0 | 11.7 | normal | 0 | True |
| 2026-07-08 | Weak | R4 | 1.0 | NWHWW | 20740.0 | 44.0 | 36.0 | 68.0 | 35.0 | 30.0 | 4.0 | 14.7 | normal | 2 | True |
| 2026-07-09 | Mixed | R9 | 1.0 | NWHNN | 21045.0 | 50.0 | 38.0 | 83.0 | 38.0 | 40.0 | 4.0 | 13.4 | normal | 1 | True |
| 2026-07-10 | Mixed | R9 | 2.0 | NWHHN | 21331.0 | 57.0 | 40.0 | 97.0 | 24.0 | 50.0 | 4.0 | 12.3 | normal | 0 | False |
| 2026-07-13 | Mixed | R9 | 3.0 | NNHHN | 21353.0 | 58.0 | 41.0 | 111.0 | 22.0 | 52.0 | 4.0 | 13.3 | normal | 0 | False |
| 2026-07-14 | Mixed | R9 | 4.0 | NWHNN | 21205.0 | 52.0 | 40.0 | 94.0 | 26.0 | 47.0 | 4.0 | 13.8 | normal | 0 | False |
| 2026-07-15 | Mixed | R9 | 5.0 | NNHNN | 21315.0 | 54.0 | 41.0 | 85.0 | 25.0 | 47.0 | 4.0 | 13.3 | normal | 0 | False |
| 2026-07-16 | Mixed | R9 | 6.0 | NNHNN | 21263.0 | 53.0 | 40.0 | 82.0 | 27.0 | 42.0 | 4.0 | 12.9 | normal | 0 | False |
| 2026-07-17 | Mixed | R9 | 7.0 | NWHNN | 21165.0 | 50.0 | 39.0 | 51.0 | 39.0 | 37.0 | 4.0 | 13.2 | normal | 0 | False |
| 2026-07-20 | Mixed | R9 | 8.0 | NWNNN | 21244.0 | 51.0 | 39.0 | 62.0 | 44.0 | 42.0 | 4.0 | 13.0 | normal | 0 | False |
| 2026-07-21 | Mixed | R9 | 9.0 | NWNNN | 21327.0 | 52.0 | 40.0 | 82.0 | 34.0 | 44.0 | 4.0 | 12.6 | normal | 0 | False |
| 2026-07-22 | Mixed | R9 | 10.0 | NWNNW | 21083.0 | 47.0 | 38.0 | 84.0 | 42.0 | 38.0 | 5.0 | 13.3 | normal | 0 | True |
| 2026-07-23 | Mixed | R9 | 11.0 | NWNNW | 20864.0 | 43.0 | 37.0 | 63.0 | 45.0 | 39.0 | 5.0 | 13.5 | normal | 1 | False |
| 2026-07-24 | Mixed | R9 | 12.0 | NWNNW | 20831.0 | 44.0 | 37.0 | 51.0 | 58.0 | 35.0 | 5.0 | 14.0 | normal | 1 | False |
| 2026-07-27 | Mixed | R9 | 13.0 | NWNNW | 21071.0 | 48.0 | 38.0 | 83.0 | 37.0 | 43.0 | 5.0 | 12.7 | normal | 0 | False |
| 2026-07-28 | Mixed | R9 | 14.0 | NWNNW | 21037.0 | 44.0 | 37.0 | 81.0 | 33.0 | 44.0 | 5.0 | 12.6 | normal | 0 | False |
| 2026-07-29 | Mixed | R9 | 15.0 | NNNNN | 21249.0 | 47.0 | 39.0 | 67.0 | 35.0 | 46.0 | 4.0 | 12.0 | normal | 0 | False |
| 2026-07-30 | Mixed | R9 | 16.0 | NNNNN | 21139.0 | 44.0 | 38.0 | 79.0 | 32.0 | 43.0 | 4.0 | 12.2 | normal | 0 | False |
| 2026-07-31 | Favourable | R6 | 1.0 | HNNHN | 21234.0 | 46.0 | 39.0 | 85.0 | 34.0 | 50.0 | 4.0 | 11.8 | normal | 1 | True |
| 2026-08-03 | Favourable | R6 | 2.0 | HNHHH | 21504.0 | 54.0 | 42.0 | 119.0 | 19.0 | 59.0 | 3.0 | 11.9 | normal | 0 | False |
| 2026-08-04 | Favourable | R6 | 3.0 | HNHHH | 21472.0 | 53.0 | 42.0 | 125.0 | 15.0 | 60.0 | 3.0 | 12.2 | normal | 0 | False |
| 2026-08-05 | Favourable | R6 | 4.0 | HHHHH | 21557.0 | 56.0 | 42.0 | 138.0 | 17.0 | 63.0 | 3.0 | 12.1 | normal | 0 | False |
| 2026-08-06 | Favourable | R6 | 5.0 | HHHHH | 21515.0 | 55.0 | 43.0 | 136.0 | 27.0 | 59.0 | 3.0 | 12.2 | normal | 0 | False |
| 2026-08-07 | Favourable | R6 | 6.0 | HHHHH | 21546.0 | 54.0 | 43.0 | 122.0 | 29.0 | 55.0 | 3.0 | 12.2 | normal | 0 | False |
| 2026-08-10 | Favourable | R6 | 7.0 | HNHHH | 21607.0 | 54.0 | 43.0 | 144.0 | 39.0 | 52.0 | 3.0 | 12.3 | normal | 0 | False |
| 2026-08-11 | Constructive | R7 | 1.0 | HNHNH | 21615.0 | 51.0 | 42.0 | 128.0 | 41.0 | 49.0 | 2.0 | 11.9 | normal | 1 | True |
| 2026-08-12 | Mixed | R9 | 1.0 | HWHNH | 21634.0 | 50.0 | 41.0 | 111.0 | 49.0 | 48.0 | 2.0 | 11.7 | normal | 1 | True |
| 2026-08-13 | Constructive | R7 | 1.0 | HNHNH | 21657.0 | 50.0 | 41.0 | 113.0 | 48.0 | 46.0 | 2.0 | 11.4 | normal | 1 | True |
| 2026-08-14 | Mixed | R9 | 1.0 | NWHNH | 21549.0 | 48.0 | 41.0 | 100.0 | 41.0 | 42.0 | 2.0 | 11.3 | normal | 0 | True |
| 2026-08-17 | Mixed | R9 | 2.0 | NWHNH | 21584.0 | 46.0 | 40.0 | 105.0 | 59.0 | 43.0 | 2.0 | 11.3 | normal | 0 | False |
| 2026-08-18 | Mixed | R9 | 3.0 | NWNNH | 21543.0 | 46.0 | 40.0 | 119.0 | 55.0 | 45.0 | 2.0 | 11.4 | normal | 1 | False |
| 2026-08-19 | Mixed | R9 | 4.0 | NWNNH | 21461.0 | 44.0 | 39.0 | 109.0 | 56.0 | 44.0 | 3.0 | 11.3 | normal | 1 | False |
| 2026-08-20 | Mixed | R9 | 5.0 | NWNNH | 21555.0 | 47.0 | 40.0 | 117.0 | 56.0 | 44.0 | 2.0 | 10.8 | normal | 0 | False |
| 2026-08-21 | Mixed | R9 | 6.0 | NNNNH | 21597.0 | 48.0 | 40.0 | 105.0 | 34.0 | 47.0 | 2.0 | 11.2 | normal | 0 | False |
| 2026-08-24 | Mixed | R9 | 7.0 | NNNNH | 21591.0 | 47.0 | 41.0 | 106.0 | 47.0 | 49.0 | 2.0 | 11.5 | normal | 0 | False |
| 2026-08-25 | Mixed | R9 | 8.0 | NNNNH | 21643.0 | 47.0 | 41.0 | 89.0 | 53.0 | 46.0 | 2.0 | 11.1 | normal | 0 | False |
| 2026-08-26 | Mixed | R9 | 9.0 | NNNHH | 21689.0 | 49.0 | 42.0 | 92.0 | 46.0 | 50.0 | 1.0 | 10.6 | normal | 0 | False |
| 2026-08-27 | Mixed | R9 | 10.0 | NWNNH | 21665.0 | 47.0 | 41.0 | 92.0 | 38.0 | 47.0 | 1.0 | 11.1 | normal | 1 | False |
| 2026-08-28 | Mixed | R9 | 11.0 | NNNHH | 21690.0 | 48.0 | 41.0 | 108.0 | 46.0 | 51.0 | 1.0 | 10.7 | normal | 1 | False |
| 2026-08-31 | Mixed | R9 | 12.0 | NWNNH | 21658.0 | 47.0 | 40.0 | 129.0 | 75.0 | 50.0 | 1.0 | 11.2 | normal | 1 | False |
| 2026-09-01 | Mixed | R9 | 13.0 | NWNNH | 21482.0 | 44.0 | 40.0 | 119.0 | 72.0 | 44.0 | 1.0 | 11.5 | normal | 2 | False |
| 2026-09-02 | Mixed | R9 | 14.0 | NWNNH | 21355.0 | 42.0 | 39.0 | 94.0 | 85.0 | 41.0 | 2.0 | 11.6 | normal | 2 | False |
| 2026-09-03 | Mixed | R9 | 15.0 | NWNNH | 21495.0 | 45.0 | 40.0 | 105.0 | 72.0 | 46.0 | 2.0 | 11.3 | normal | 2 | False |
| 2026-09-04 | Mixed | R9 | 16.0 | NWNNH | 21478.0 | 47.0 | 40.0 | 115.0 | 45.0 | 49.0 | 2.0 | 10.7 | normal | 2 | False |
| 2026-09-07 | Mixed | R9 | 17.0 | NWNNH | 21415.0 | 46.0 | 40.0 | 127.0 | 48.0 | 48.0 | 2.0 | 11.2 | normal | 2 | False |
| 2026-09-08 | Mixed | R9 | 18.0 | NNNNH | 21449.0 | 45.0 | 41.0 | 133.0 | 51.0 | 49.0 | 2.0 | 11.2 | normal | 2 | False |
| 2026-09-09 | Mixed | R9 | 19.0 | NNHNH | 21351.0 | 45.0 | 40.0 | 119.0 | 76.0 | 48.0 | 3.0 | 11.9 | normal | 2 | False |
| 2026-09-10 | Mixed | R9 | 20.0 | NWHNH | 21299.0 | 43.0 | 39.0 | 97.0 | 86.0 | 49.0 | 3.0 | 11.8 | normal | 1 | False |
| 2026-09-11 | Mixed | R9 | 21.0 | NWNNN | 21227.0 | 41.0 | 39.0 | 71.0 | 107.0 | 45.0 | 4.0 | 12.3 | normal | 0 | False |
| 2026-09-15 | Weak | R4 | 1.0 | NWNWN | 20751.0 | 32.0 | 34.0 | 78.0 | 137.0 | 32.0 | 4.0 | 13.4 | washed_out | 0 | True |
| 2026-09-16 | Weak | R4 | 2.0 | NWNWN | 20745.0 | 31.0 | 34.0 | 36.0 | 163.0 | 31.0 | 4.0 | 13.2 | washed_out | 0 | False |
| 2026-09-17 | Weak | R4 | 3.0 | NWNWN | 20925.0 | 34.0 | 35.0 | 46.0 | 99.0 | 33.0 | 4.0 | 12.3 | normal | 0 | False |
| 2026-09-18 | Mixed | R9 | 1.0 | NWNNN | 21239.0 | 38.0 | 37.0 | 84.0 | 64.0 | 42.0 | 4.0 | 11.4 | normal | 0 | True |
| 2026-09-21 | Mixed | R9 | 2.0 | NWNNN | 21184.0 | 39.0 | 37.0 | 106.0 | 55.0 | 47.0 | 4.0 | 11.3 | normal | 0 | False |
| 2026-09-22 | Mixed | R9 | 3.0 | NWWNN | 21158.0 | 40.0 | 37.0 | 98.0 | 54.0 | 46.0 | 4.0 | 11.0 | normal | 0 | False |
| 2026-09-23 | Mixed | R9 | 4.0 | NNWNN | 21305.0 | 44.0 | 39.0 | 102.0 | 33.0 | 48.0 | 4.0 | 10.4 | normal | 1 | False |
| 2026-09-24 | Weak | R5 | 1.0 | NWWNW | 20924.0 | 38.0 | 37.0 | 92.0 | 60.0 | 45.0 | 4.0 | 12.7 | normal | 1 | True |
| 2026-09-25 | Mixed | R9 | 1.0 | NWWNN | 20905.0 | 40.0 | 37.0 | 75.0 | 81.0 | 48.0 | 4.0 | 12.2 | normal | 1 | True |

## verdict distribution (all sessions)
| verdict | n |
|---|---|
| Mixed | 264 |
| Weak | 135 |
| Danger | 99 |
| Constructive | 56 |
| Favourable | 31 |
| NULL | 9 |

## rule distribution
| rule_id | n |
|---|---|
| R0 | 9 |
| R1 | 82 |
| R2 | 17 |
| R3 | 16 |
| R4 | 99 |
| R5 | 20 |
| R6 | 31 |
| R7 | 42 |
| R8 | 14 |
| R9 | 264 |

## example readings
- 2026-09-25 `leaders_holding`: Leaders holding: 473 new 52W highs in 5 sessions (vs 315 before) while MidSml400 is -1.6% over 5 sessions.
- 2026-09-23 `benchmark_split`: Benchmark split: Nifty 50 -1.7% vs its 50 EMA, MidSml400 +0.3%.
- 2026-08-13 `narrow_rally`: Narrow rally: MidSml400 up 3 sessions (+0.2%) while stocks above 50 EMA fell from 54% to 50%.
- 2026-07-31 `hidden_selling`: Hidden selling: trend Healthy but 4 distribution days in 25 sessions.
- 2025-06-25 `choppy`: Choppy: participation Neutral (55%) but only 33% of breakouts are holding.

## reading counts
| id | n |
|---|---|
| benchmark_split | 106 |
| hidden_selling | 98 |
| leaders_holding | 44 |
| narrow_rally | 6 |
| choppy | 2 |

## recent alerts
- 2026-09-25: Environment improved: Weak -> Mixed (rule R9).
- 2026-09-24: Environment worsened: Mixed -> Weak (rule R5).; India VIX spiked +22.6% to 12.7.
- 2026-09-18: Environment improved: Weak -> Mixed (rule R9).
- 2026-09-15: Environment worsened: Mixed -> Weak (rule R4).; Follow-through fell to 32% (< 35%).
- 2026-08-14: Environment worsened: Constructive -> Mixed (rule R9).
- 2026-08-13: Environment improved: Mixed -> Constructive (rule R7).

## setup last session
| queue | n | n_new | med_risk | med_dist | null_stop |
|---|---|---|---|---|---|
| darvas_10ema | 200 | 15.0 | 4.9 | 1.3 | 1.0 |
| darvas_squeeze | 71 | 14.0 | 4.8 | 2.5 | 0.0 |
| vcp | 39 | 6.0 | 7.6 | 3.3 | 0.0 |

## setup per session avg
| queue | n_rows | per_session | setups |
|---|---|---|---|
| vcp | 12863 | 23.0 | 1650 |
| darvas_squeeze | 44499 | 76.1 | 10235 |
| darvas_10ema | 132241 | 226.4 | 22092 |

## groups: top sector 1000cr last
| group_name | members | r21 | ex63 | rsr | rsm | q | rank | d5 | a50 | flow | deals10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Forest Materials | 7 | 11.9 | 20.1 | 106.0 | 101.1 | Leading | 1.0 | 0.0 | 86.0 | -0.0 | 0.0 |
| Healthcare | 131 | 4.1 | 10.7 | 104.4 | 100.6 | Leading | 2.0 | 0.0 | 63.0 | 0.0 | -307.0 |
| Telecommunication | 19 | 6.7 | 7.8 | 103.0 | 101.3 | Leading | 3.0 | 5.0 | 32.0 | -0.1 | 144.0 |
| Oil, Gas & Consumable Fuels | 37 | 1.4 | 12.4 | 103.3 | 99.1 | Weakening | 4.0 | -1.0 | 50.0 | -0.7 | -0.0 |
| Textiles | 43 | 3.4 | 9.8 | 102.0 | 100.3 | Leading | 5.0 | 1.0 | 51.0 | -0.1 | 279.0 |
| Realty | 38 | 2.0 | 9.3 | 102.4 | 101.2 | Leading | 6.0 | 1.0 | 47.0 | 0.3 | -19.0 |
| Chemicals | 104 | 1.9 | 8.9 | 102.7 | 100.3 | Leading | 7.0 | -2.0 | 43.0 | -0.4 | -70.0 |
| Capital Goods | 261 | 2.2 | 7.4 | 103.0 | 100.2 | Leading | 8.0 | 1.0 | 50.0 | -0.3 | 253.0 |

## deal events
| event_type | n | net_cr |
|---|---|---|
| churn | 1875 | -726.0 |
| distribute | 820 | -42695.0 |
| fresh | 408 | 9014.0 |
| transfer_interse | 193 | -15.0 |
| accumulate | 188 | 1084.0 |
| placement | 16 | -132.0 |

## Reading the table above

- `T P L F S` = Trend, Participation, Leadership, Follow-through, Stress status initials (H/N/W, `-` = NULL).
- 9 NULL verdicts (R0) are the first sessions, when the 10-session A/D line and other windows aren't formed yet. Leadership is NULL for the first ~252
  sessions of a symbol's history unless an official 52W snapshot exists (official snapshots start 2026-07-02 in this DB).
- The verdict flips between Mixed and Weak on single sessions (e.g. 09-22 → 09-24 → 09-25) because Participation sits on the 40 line and the
  one-step direction override moves it. The rules have **no hysteresis**. This is a calibration item for §6.1.5 (for example, require 2 sessions
  to change state, or a band around 40/60).
- The VIX spike rule (+20 %/day) fired at VIX 12.7 (from 10.35). The spec says +20 %, but at low VIX levels this is noisy. Calibration candidate.
- `hidden_selling` (98 sessions) and `benchmark_split` (106) fire often. `choppy` fires only twice.

## Caveats

- Prices are unadjusted in this DB. Split/bonus symbols distort returns, breakouts, new highs/lows and mcap scaling until the adjusted rebuild lands.
  The builders don't assume a date span.
- Market cap is point-in-time only from 2026-07-02 (security_reference_daily). Before that it is `price_scaled_current` (today's share count),
  and the row-level `mcap_basis` column says so.
- deal_session_net covers 2026-04-29 onward. group_daily.deal_net_10s_cr is NULL until a full 10-session window is covered.
- darvas_10ema averages 226 names per session. The desk only displays the top 40, but the queue itself is that large.


## w6 calibration — hysteresis, VIX spike level, follow-through minimum (2026-09-27)

Branch `feat/w6-regime-calibration`. Same inputs as above: live `Database/marketpulse.duckdb` opened `read_only=True`
(indicators_daily, index_daily, breadth_daily copied into the session scratchpad), `build_regime_daily(index_daily,
indicators, breadth=breadth)` run with the old code (b668419) and the new code on the same frames. Nothing under
`Database/` was written. Rules: `Scripts/derived/SCHEMA.md` → regime_daily → Hysteresis; code: `regime.HYSTERESIS`.

**Rule changes**

1. **Pillar hysteresis.** A pillar status changes only if the input clears the zone line by a margin (Participation 2 pts,
   Follow-through 2 pts, Trend 0.5 % vs EMA, Leadership 2, Stress 1 VIX pt) or stays across for 2 sessions.
   `{p}_status_raw` keeps the unsmoothed status. Distribution days: the margin applies only to improving moves.
2. **Verdict confirmation.** The published verdict follows the rules on the smoothed pillars (`candidate_verdict`) only after
   the new state holds 2 sessions. Moves **into Danger** are immediate, whether the smoothed or the raw statuses say Danger.
   Held sessions show `rule_id = RH`. `raw_verdict` (the old behaviour) is published for audit.
3. **VIX spike** now needs a level: +20 % in a day **to ≥ 18**, or +30 % over 5 sessions **to ≥ 16**. It no longer
   fires on 2026-09-24 (12.7), 2026-07-08 (14.7) or 2026-03-02 (17.1). It now fires on multi-day surges with no single
   +20 % day (2024-05-06…09, 2026-03-05…09, 2026-03-25). Alert only on the first session of a spike: 7 alerts in 594 sessions (was 8).
4. **Follow-through** is NULL ("Insufficient data") below **30** breakouts (was 10). Live median is about 450 per window,
   so the same 8 early sessions are NULL as before. The follow-through alert now fires when the smoothed status turns Weak.

**Verdict changes, last 250 sessions (2025-09-22 → 2026-09-25)**

| | before | after |
|---|---:|---:|
| Verdict changes | **49** | **26** |
| Verdict streaks | 50 | 27 |
| Streaks lasting 1 session | 21 | 1 |
| Median streak (sessions) | 2.5 | 6 |
| `alert_state_change` | 50 | 26 |
| Danger sessions | 39 | 46 |

Pillar status changes over the same window (raw → smoothed): Trend 26 → 21, Participation 50 → 42, Leadership 26 → 27,
Follow-through 61 → 42, Stress 45 → 41 (raw, after the VIX fix) → 29. The raw verdict under the new VIX and follow-through
rules changes 47 times. Hysteresis removes most of the rest.

Verdict distribution over the last 250 sessions, before → after: Mixed 123 → 124, Weak 57 → 48, Danger 39 → 46,
Constructive 19 → 18, Favourable 12 → 14. Danger rises because entries stay immediate but exits need 2 sessions (the
asymmetry is deliberate). Participation still changes 42 times: most of those changes come from the one-step direction
override (the sign of the 5-session change in % > 50 EMA, margin 1 pt). The override is the next thing to calibrate if
Participation should be steadier.

**Last 30 sessions** (`before` = old verdict; `T P L F S` = smoothed statuses)

| date | before | raw_verdict | candidate | **verdict** | rule_id | days | T P L F S | P level | FT % | VIX | dd |
|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|
| 2026-08-14 | Mixed | Mixed | Mixed | **Favourable** | RH | 9 | HWHNH | 44.2 | 42.5 | 11.3 | 2 |
| 2026-08-17 | Mixed | Mixed | Mixed | **Mixed** | R9 | 1 | NWHNH | 42.8 | 42.9 | 11.3 | 2 |
| 2026-08-18 | Mixed | Mixed | Mixed | **Mixed** | R9 | 2 | NWNNH | 43.2 | 45.0 | 11.4 | 2 |
| 2026-08-19 | Mixed | Mixed | Mixed | **Mixed** | R9 | 3 | NWNNH | 41.8 | 43.7 | 11.3 | 3 |
| 2026-08-20 | Mixed | Mixed | Mixed | **Mixed** | R9 | 4 | NWNNH | 43.6 | 44.1 | 10.8 | 2 |
| 2026-08-21 | Mixed | Mixed | Mixed | **Mixed** | R9 | 5 | NWNNH | 44.1 | 46.7 | 11.2 | 2 |
| 2026-08-24 | Mixed | Mixed | Mixed | **Mixed** | R9 | 6 | NNNNH | 44.1 | 49.1 | 11.5 | 2 |
| 2026-08-25 | Mixed | Mixed | Mixed | **Mixed** | R9 | 7 | NNNNH | 44.0 | 45.5 | 11.1 | 2 |
| 2026-08-26 | Mixed | Mixed | Mixed | **Mixed** | R9 | 8 | NNNNH | 45.6 | 50.2 | 10.6 | 1 |
| 2026-08-27 | Mixed | Mixed | Mixed | **Mixed** | R9 | 9 | NNNNH | 43.6 | 46.9 | 11.1 | 1 |
| 2026-08-28 | Mixed | Mixed | Mixed | **Mixed** | R9 | 10 | NNNNH | 44.8 | 50.6 | 10.7 | 1 |
| 2026-08-31 | Mixed | Mixed | Mixed | **Mixed** | R9 | 11 | NNNNH | 43.5 | 49.8 | 11.2 | 1 |
| 2026-09-01 | Mixed | Mixed | Mixed | **Mixed** | R9 | 12 | NWNNH | 41.9 | 44.0 | 11.5 | 1 |
| 2026-09-02 | Mixed | Mixed | Mixed | **Mixed** | R9 | 13 | NWNNH | 40.6 | 41.4 | 11.6 | 2 |
| 2026-09-03 | Mixed | Mixed | Mixed | **Mixed** | R9 | 14 | NWNNH | 42.4 | 46.0 | 11.3 | 2 |
| 2026-09-04 | Mixed | Mixed | Mixed | **Mixed** | R9 | 15 | NWNNH | 43.7 | 48.8 | 10.7 | 2 |
| 2026-09-07 | Mixed | Mixed | Mixed | **Mixed** | R9 | 16 | NWNNH | 43.0 | 48.4 | 11.2 | 2 |
| 2026-09-08 | Mixed | Mixed | Mixed | **Mixed** | R9 | 17 | NNNNH | 42.8 | 49.4 | 11.2 | 2 |
| 2026-09-09 | Mixed | Mixed | Mixed | **Mixed** | R9 | 18 | NNHNH | 42.2 | 48.4 | 11.9 | 3 |
| 2026-09-10 | Mixed | Mixed | Mixed | **Mixed** | R9 | 19 | NWHNH | 41.1 | 48.7 | 11.8 | 3 |
| 2026-09-11 | Mixed | Mixed | Mixed | **Mixed** | R9 | 20 | NWNNN | 40.0 | 45.4 | 12.3 | 4 |
| 2026-09-15 | Weak | Weak | Weak | **Mixed** | RH | 21 | NWNWN | 32.7 | 31.9 | 13.4 | 4 |
| 2026-09-16 | Weak | Weak | Weak | **Weak** | R4 | 1 | NWNWN | 32.6 | 30.6 | 13.2 | 4 |
| 2026-09-17 | Weak | Weak | Weak | **Weak** | R4 | 2 | NWNWN | 34.5 | 33.4 | 12.3 | 4 |
| 2026-09-18 | Mixed | Mixed | Mixed | **Weak** | RH | 3 | NWNNN | 38.0 | 41.9 | 11.4 | 4 |
| 2026-09-21 | Mixed | Mixed | Mixed | **Mixed** | R9 | 1 | NWNNN | 38.1 | 46.9 | 11.2 | 4 |
| 2026-09-22 | Mixed | Mixed | Mixed | **Mixed** | R9 | 2 | NWWNN | 38.4 | 45.5 | 11.0 | 4 |
| 2026-09-23 | Mixed | Mixed | Mixed | **Mixed** | R9 | 3 | NWWNN | 41.6 | 48.4 | 10.3 | 4 |
| 2026-09-24 | Weak | Mixed | Mixed | **Mixed** | R9 | 4 | NWWNN | 37.8 | 45.0 | 12.7 | 4 |
| 2026-09-25 | Mixed | Mixed | Mixed | **Mixed** | R9 | 5 | NWWNN | 38.5 | 47.6 | 12.2 | 4 |

- The 09-24 Mixed → Weak → Mixed flip is gone. The VIX move to 12.7 no longer counts as a spike, so Stress stays Neutral
  and R5 doesn't fire.
- 09-15: the pillars turned Weak decisively (Participation 32.7, Follow-through 31.9), but the verdict held Mixed for one
  session (RH) and moved to Weak on 09-16. 09-18: the candidate improved to Mixed. The verdict held Weak (RH) and became
  Mixed on 09-21.
- Moves into Danger are never delayed. Other moves lag by at most one session.

**Tests:** `tests/test_derived_regime.py` has 25 tests, all passing. New tests: participation and follow-through flip-flop
before vs held after, crossing by the margin is immediate, the verdict needs 2 sessions, Danger is immediate (including raw-only Danger),
a low-level VIX jump is not flagged, the 5-day surge rule, the 30-breakout minimum, and an end-to-end check that trend
hovering around the 200 EMA gives ≥ 20 raw changes but ≤ 2 published ones. Also passing: `test_derived_build`,
`test_api_v2_contract`, `test_api_v2_helpers` and `test_regime_band` (106 tests).
