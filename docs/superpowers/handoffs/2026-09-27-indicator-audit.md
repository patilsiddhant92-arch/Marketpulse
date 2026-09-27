# Indicator & screening audit — 2026-09-27

**Question:** "Are all indicators and other parameters for screening correct?"
**Answer:** Yes for every stored indicator and every screen/queue the React app shows — they match an
independent re-implementation exactly (max relative error ≤ 1.3e-15, zero membership differences).
One real bug was found and fixed in a *derived* breadth count (official new 52-week highs/lows were
double-counted the day after a breakout); two open items and several documented conventions are
listed below.

Branch `feat/g1-indicator-audit`. DB: `Database/marketpulse.duckdb` (5-year rebuild, last session
2026-09-25), opened read-only.

## Method

- `Scripts/audit/indicator_reference.py` — independent reference (plain numpy loops; imports no
  production indicator/predicate code) on adjusted OHLCV `COALESCE(adj_*, raw)` from `prices_daily`.
- `Scripts/audit/run_indicator_audit.py --out <dir>` — sections `stored, rs, pit, darvas, screens, queues`
  (reproducible; ~13 min, < 1 GB; the universe reference rows are cached as a pickle in `<dir>`).
- **Sample:** 60 symbols — 15 large (≥ ₹50k Cr), 16 mid, 15 small, plus split/bonus stocks (GOODLUCK,
  HEGAM, NAZARA, BERGEPAINT, ZYDUSWELL, AARTECH, SETFGOLD 1:100, LANCER, ADFFOODS), recent listings (RSL,
  BATLIBOI, UPHOT 22 bars, ANNAPURNA) and data-gap stocks (MBECL, HEGAM demerger, LANCER). Every session
  of their history = **75,541 rows**; highlighted dates 2021-03-15, 2021-11-10, 2022-06-20, 2023-02-14,
  2023-10-05, 2024-08-06, 2025-07-15, 2026-09-25.
- Tolerance 1e-6 relative (denominator max(|ref|, 1)). Screens/queues: 2026-09-25, reference values vs
  `screener.run` / `desk.queue_rows` called in-process (read-only DB, copy of the user DB).

## Results — stored indicators (60 symbols × full history)

| Indicator | Rows compared | Max error | Verdict |
|---|---|---|---|
| EMA 10/20/50/100/150/200 (after `span-1` warm-up) | 75,001 / 74,401 / 72,692 / 69,892 / 67,172 / 64,522 | 0 | **PASS** + CONVENTION (seed, below) |
| SMA 50/150/200 | 72,692 / 67,172 / 64,522 | 5e-16 | **PASS** |
| `sma_200_rising` (SMA200 > SMA200 20 sessions ago) | 75,541 | 0 flips | **PASS** |
| RSI(14) Wilder | 74,701 | 0 | **PASS** + CONVENTION (seed) |
| True range / ATR14 (SMA, min 5) / ATR14 Wilder / ATR % | 75,541 / 75,301 / 74,761 / 75,301 | 6e-16 | **PASS** (SMA-ATR is the documented `atr_14`) |
| ADR 20 % (min 5 bars) | 75,301 | 6e-16 | **PASS** |
| Returns 1d (close/prev_close) / 5d / 21d / 63d / 126d | 75,481 / 75,241 / 74,281 / 71,908 / 68,395 | 0 | **PASS** (on each symbol's first stored row — DB start or listing — 1d uses NSE's prev close; 60 rows the reference leaves NULL) |
| RVOL (vs mean of 20 *preceding* bars, min 5) | 75,241 | 0 | **PASS** (documented: today excluded from baseline) |
| Avg volume 20d, delivery % 20d avg, delivery qty 20d avg | 75,301 / 71,044 / 71,044 | 7e-16 | **PASS** |
| `delivery_spike`, `price_up_delivery_up` | 75,541 | 0 flips | **PASS** |
| Turnover Cr (= lakhs/100), 20d avg traded value | 75,541 / 75,301 | 1.3e-15 | **PASS** |
| High/low 20d, 252d | 75,421 | 0 | **PASS** |
| `away_52w_high_pct`, `away_52w_low_pct`, `distance_below_52w` (identities on stored 52W) | 75,426 | 0 | **PASS** |
| 52W high/low source | 75,421 | — | **CONVENTION** (NSE official; see below) |
| Weekly RSI (`rsi_14_w`) | 71,580 | 0 | **PASS** + CONVENTION (week visibility) |
| NR7 | 75,541 | 0 flips | **PASS** + CONVENTION (zero-range bars) |
| Inside bar, `new_20d_high` | 75,541 | 0 flips | **PASS** |
| `away_10ema_pct` | 75,001 | 0 | **PASS** |
| Minervini trend template (8 criteria) — count / pass | 75,541 | 1 row off by one / 0 pass flips | **PASS** (the one row: MBECL 2020-11-23, flat locked price, close = SMA50 = 4.95, rolling-sum residue decides `close > sma_50`) |
| RS percentile (whole universe, 8 dates) | 17,197 rows (15,353 ranked) | 0 | **PASS** |
| `rs_rank_t5` = RS 5 own sessions earlier (2026-09-25) | 2,418 | 0 | **PASS** |
| Darvas box (Pine `boxp=5`), top & bottom | 75,541 bars | 0 mismatches | **PASS** |
| Darvas box window dependence (last 252 bars vs full history, 14,339 end bars) | 14,339 | 0 differ | **PASS** |

RS reproduced from the documented formula: 0.4·Q1 + 0.2·Q2 + 0.2·Q3 + 0.2·Q4 of non-overlapping
63-session returns over the symbol's own sessions, NULL without 252 prior sessions, ranked daily as
average rank / count × 100 across every symbol with a score.

## Results — point-in-time

Production per-symbol pass (`build_database._calc_single_symbol_indicators`) on prices truncated at t vs
full history, 17 symbols × 3 dates (46 checks), every column compared at t: only the swing-point **RSI
divergence flags** (daily/weekly/monthly) differ (3 flips). **CONVENTION (documented)** in
`incremental_append.py`'s docstring — a swing at t needs bar t+1, so the incremental append rewrites the
recent month; no screen, preset or Desk queue reads these flags. RS ranks, returns, 52W as-of joins and
the reference loops are causal by construction.

## Results — screener presets (2026-09-25, universe with market cap ≥ ₹1,000 Cr = 1,521)

Reference indicator values + the served snapshot's floors, taxonomy and data-gap guard, evaluated
against each preset's rules, vs `screener.run`:

| Preset | API | Reference | Only one side | Verdict |
|---|---|---|---|---|
| minervini_8of8 | 313 | 313 | 0 | **PASS** |
| stage2_leader | 209 | 209 | 0 | **PASS** |
| ema_stack | 250 | 250 | 0 | **PASS** |
| emas_converge | 297 | 297 | 0 | **PASS** |
| near_52w_high | 101 | 101 | 0 | **PASS** |
| fresh_52w_high | 40 | 40 | 0 | **PASS** |
| sma_template | 295 | 295 | 0 | **PASS** |
| delivery_thrust | 33 | 33 | 0 | **PASS** |
| nr7_inside | 122 | 122 | 0 | **PASS** |
| weekly_rsi_60 | 254 | 254 | 0 | **PASS** |

## Results — Desk queues (2026-09-25)

Independent pool (mcap ≥ 1,000 Cr, reference 20D ADV ≥ 3 Cr, band > 5 % or unknown, no GSM / STAGE 2,
no -RE, close > 200 EMA or unknown) = 710 symbols.

| Queue | Reference | setup_daily | API (`desk.queue_rows`) | Geometry | Verdict |
|---|---|---|---|---|---|
| Darvas Squeeze (truth table + 5-session persistence) | 76 | 76 | 76 | trigger = box top, stop = EMA10 × 0.985: 76/76 exact | **PASS** |
| Darvas 10 EMA | — (flavor classifier not re-implemented) | 214 | 214 | spec §14.1 trigger = high of t, stop = min low since the 10 EMA touch (Catch-up: none): 214/214 exact; rising EMA10, close > EMA10, high ≥ EMA10, in pool, not in squeeze: 214/214 | **PASS** |
| VCP (150-session window, ≥ 2 strictly shrinking Ts ≥ 3 % / ≥ 8 bars, stop < close ≤ pivot, close ≥ 30, ≥ −25 % from 52W high, 20D vol ≥ 100k) | 42 | 42 | 42 | pivot, stop and every T depth: 42/42 exact; sanity (shrinking, ≥ 3 %, ≥ 8 bars, inside base): 0 violations | **PASS** |

## Findings

### FAIL — fixed

1. **Official new 52W highs/lows double-counted** (`Scripts/derived/_common.new_high_low_flags`, feeds
   `regime_daily.new_highs/new_lows/net_new_highs*` and `group_daily.new_highs_52w/pct_new_highs_52w`).
   NSE's `CM_52_wk_High_low` snapshot effective on session t covers sessions up to **t−1** (verified on
   3 dates: 86–93 % exact vs intraday highs through t−1; 84–90 % if t is included). The flag compared
   today's high with the *prior row's* official value, which covers only up to t−2, so the session after
   every breakout counted again. Since snapshots began (2026-07-02): 1,389 of 6,911 new-high flags
   spurious (≈ 20 %; e.g. 2026-09-24: 119 reported vs 71). Fix: fold the prior session's own high/low in
   (`max(prior high_52w, prior high)`; a no-op for the 252-session fallback era). Test:
   `tests/test_derived_regime.py::test_new_high_not_counted_again_the_day_after_a_breakout_with_official_snapshots`.
   **Needs a derived-tables rebuild** (regime_daily, group_daily) — indicators_daily is unaffected.

### FAIL — open (not fixed here)

2. **Participation breadth counts unknown EMAs as "below"** — `Scripts/build_database.build_breadth_daily`
   uses `(close > ema_N).mean()` over all rows, so recent listings without a 50/200 EMA count as below;
   `regime._breadth` computes the fail-closed version (unknown excluded) but then overrides it with
   `breadth_daily`. 2026-09-25: above 200 EMA 37.5 % served vs 43.8 % fail-closed; above 50 EMA 34.6 %
   vs 37.3 %; above 10 EMA 37.0 % vs 37.2 %. Not changed because the regime zones were calibrated on the
   served series and `breadth_daily` is only rewritten for new dates by the incremental append (a fix
   needs a full rebuild + zone re-calibration). Decide which definition the Participation pillar should use.
3. **VCP definition differs between the Desk queue and the live/"why not" path** —
   `App/services/desk.py::_vcp` (used by `screener._queue_predicate_checks` VCP diagnostics and by the
   live fallback when `setup_daily` is missing) uses a 252-session window, close ≤ pivot × 1.03 and no
   52W gate; the queue actually served (`setup_daily`, `Scripts/derived/setup_daily.py::_vcp`) uses 150
   sessions, close ≤ pivot and the ≥ −25 %-from-52W-high gate. On 2026-09-25 the live path yields 68 vs
   42 (26 extra: 16 close in (pivot, 1.03·pivot], 5 fewer than 2 Ts in 150 bars, 5 fail the 52W gate).
   The debug's final "In the VCP queue" row is authoritative and correct, but its geometry lines can
   read "pass" for a stock not in the queue; the desk docstring says "close ≤ pivot × 1.03". Fix belongs
   in App/services (other agents are editing desk.py): make `_vcp` mirror setup_daily (150 / pivot /
   52W gate) or call the same helper.
4. **`indicators_daily.is_fresh_52w_high` is always FALSE** (0 of 3.48 M rows) — defined as
   `trade_date == high_52w_date`, impossible because the NSE snapshot lags a session. Unused by the app
   (the screener's "Fresh 52W high" uses `high ≥ high_52w`, which is correct). Drop it or redefine as
   `high_price >= high_52w` (needs a full rebuild).

### CONVENTION — intentional / documented, not changed

- **EMA seed:** first close (`ewm(adjust=False)`), shown from bar `span`. TradingView-style SMA seeding
  differs by < 7e-5 relative after 5×span bars, but for young listings EMA200 differs by up to 16.7 %
  (bars 200–250), 7.4 % (250–400), 2.1 % (400–600); EMA50 up to 7.5 % in bars 50–60. Affects close>200 EMA
  gates for stocks listed after ~2024 only.
- **RSI seed:** first 1-bar change, shown from bar 14. Vs Wilder's SMA seed: up to 35 RSI points in bars
  14–30, 2.8 in 60–100, 0.006 after 150, 0 after 250.
- **52-week high/low:** NSE official snapshot (× cumulative price factor) from 2026-07-02, covering
  sessions up to t−1; before that the trailing 252-session high/low *including* t. `high ≥ high_52w`
  therefore means "broke the 52W high today" in both eras; 48 stocks on 2026-09-25 close above their
  `high_52w` by design. NSE values differ > 1 % from our own adjusted calendar-year high for 330 of 2,952
  symbols on 2026-09-25 (median +2 %; outliers are NSE not adjusting a corporate action, e.g. TEMBO 837 vs
  83.7, or our unexplained gaps, e.g. MBECL/LANCER — the serving data-gap guard NULLs those rows).
- **Weekly RSI:** weeks end Friday; Mon–Thu rows show the last completed week, Friday shows the current
  week; a week whose Friday is a holiday is visible from the next Monday.
- **NR7:** zero-range (locked) bars are "no range" — never NR7 and they void the 7-bar window: 755 of
  12,460 textbook NR7 days (6 %) are not flagged. `Scripts/indicators.nr7` (textbook) is a different,
  unused definition.
- **RS universe:** every symbol with a score (EQ/BE/BZ, ETFs included); quarter lags count the symbol's
  own sessions (suspensions look further back in calendar time); pct includes the stock itself (top = 100).
- **RVOL** excludes today from the 20-bar baseline; **ATR14** (`atr_14`) is the SMA of TR with 5-bar
  minimum (Wilder in `atr_14_wilder` / `atr_pct_primary`).
- **"Stage 2" has two meanings:** screener `days_in_stage2` = close > EMA200 and EMA50 > EMA200;
  regime `stage2_count` = trend template 8/8. The `stage2_leader` description says "rising EMA stack"
  but no slope rule exists (order only).
- **Trend template** criterion 3 = SMA200 above its value 20 sessions ago ("rising ≥ 1 month").

### Out of scope

`screener_results` and `candidate_daily` (`Scripts/candidate_engine.py`) are not read by the v2 API/React
app. `group_daily` was only checked for the new-high fix above.

## Rebuild needed

| Change | Rebuild |
|---|---|
| New-high/low flag fix | derived tables (`regime_daily`, `group_daily`) — next EOD derived step or a derived-only rebuild recomputing history from 2026-07-02 |
| Open items 2 / 4 (if taken) | full indicators rebuild (+ regime zone re-calibration for 2) |
| Open item 3 (if taken) | none (serving code) |
