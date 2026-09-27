# Derived tables — schema

Built by `Scripts/derived` (`build_derived_tables` → `write_derived_tables`, CREATE OR REPLACE each run).
Spec: `docs/superpowers/specs/2026-09-26-marketpulse-professional-rebuild-design.md` §4.5, §6.1, §7.2–7.5.

General rules

- **Point-in-time.** A row dated *t* only uses data dated ≤ *t* (one documented exception: `mcap_basis =
  'price_scaled_current'`, see group_daily).
- **NULL means unknown**, never zero and never a default. A pillar status of NULL is "Insufficient data" in the UI.
- Percent columns (`*_pct`) are in percent units (`12.5` = 12.5 %). Money is ₹ crore (`*_cr`).
- JSON columns are `VARCHAR` holding a JSON array/object (parse on the API side).
- Dates are `TIMESTAMP` at midnight (session date).
- "Sessions" are the trade dates present in `indicators_daily`.

---

## regime_daily — Market Environment (§6.1)

One row per session. Index: `trade_date`.

### Verdict

| Column | Type | Meaning | NULL when |
| :--- | :--- | :--- | :--- |
| trade_date | TIMESTAMP | Session | never |
| verdict | VARCHAR | `Favourable` · `Constructive` · `Mixed` · `Weak` · `Danger` — the published, smoothed verdict (see Hysteresis) | rule R0 (insufficient data) |
| verdict_guidance | VARCHAR | press · normal size · selective, half size · mostly cash · protect capital | verdict NULL |
| rule_id | VARCHAR | Rule behind the published verdict (`R0`…`R9`, table below), or `RH` when the verdict is being held while a different candidate confirms | never |
| rule_text | VARCHAR | Plain text of that rule; for `RH`: "Held at X: today's pillars match Y (rule Rn) …" | never |
| raw_verdict | VARCHAR | Rules applied to the raw (unsmoothed) pillar statuses — the pre-hysteresis verdict, for audit | raw rule R0 |
| raw_rule_id | VARCHAR | Rule matched by raw_verdict | never |
| candidate_verdict | VARCHAR | Rules applied to the smoothed pillar statuses today; becomes `verdict` once it holds 2 sessions (Danger at once) | rule R0 |
| candidate_rule_id | VARCHAR | Rule matched by candidate_verdict | never |
| pillars_known | BIGINT | Number of pillars with a non-NULL status (0–5) | never |
| days_in_state | DOUBLE | Consecutive sessions with this (published) verdict (1 = changed today) | verdict NULL |
| state_since | TIMESTAMP | First session of the current verdict streak | verdict NULL |
| previous_state | VARCHAR | Verdict of the streak before the current one | first streak, or previous streak was NULL |
| state_change | VARCHAR | `improved` / `worsened` (current vs previous_state) | previous_state NULL |
| state_change_date | TIMESTAMP | Date of the change into the current state (= state_since when a previous state exists) | previous_state NULL |

Verdict rules (`Scripts.derived.regime.VERDICT_RULES`, also `verdict_rules_table()`), evaluated top-down, first match wins.
A condition lists the statuses that satisfy it; a NULL pillar never satisfies a condition.

| rule_id | verdict | conditions |
| :--- | :--- | :--- |
| R0 | NULL | Trend or Participation NULL, or fewer than 4 pillars known |
| R1 | Danger | Trend Weak ∧ Stress Weak |
| R2 | Danger | Trend Weak ∧ Participation Weak ∧ Follow-through Weak |
| R3 | Weak | Trend Weak |
| R4 | Weak | Participation Weak ∧ Follow-through Weak |
| R5 | Weak | Stress Weak ∧ Leadership Weak |
| R6 | Favourable | Trend Healthy ∧ Participation ≥ Neutral ∧ Follow-through Healthy ∧ Leadership ≠ Weak ∧ Stress ≠ Weak |
| R7 | Constructive | Trend Healthy ∧ Participation ≥ Neutral ∧ Follow-through ≥ Neutral ∧ Stress ≠ Weak |
| R8 | Constructive | Trend Neutral ∧ Participation Healthy ∧ Follow-through Healthy ∧ Stress ≠ Weak |
| R9 | Mixed | default |
| RH | (held) | Published verdict kept: today's candidate differs and has not held 2 sessions yet |

### Hysteresis (w6 calibration, `Scripts.derived.regime.HYSTERESIS`)

Deterministic and point-in-time: each session uses only its own inputs, the previous session's raw status and the previous
smoothed state, so a truncated rebuild reproduces every earlier row.

- **Pillar status.** `{p}_status_raw` is today's zone status. The published `{p}_status` moves off its previous value only
  when (a) the move is *decisive* — the status recomputed with every input nudged by the margin **against** the move still
  clears the line — or (b) the raw status has been on the new side for **2 sessions in a row** (it then moves to the less
  extreme of the two). NULL inputs give NULL at once; the first known session after NULL starts fresh.
- **Margins:** Trend 0.5 % of price vs each EMA, 0.05 pt on the 50 EMA slope · Participation 2 pts on the level, 1 pt on the
  5-session change in % > 50 EMA · Leadership 2 on the 10-day net-new-highs average, 1 on its 5-session change ·
  Follow-through 2 pts · Stress 1 VIX point on the 25 / 18 lines, 2 pts on the VIX 5-session change, 1 distribution day
  **against improving moves only** (reaching 5 is Weak at once; leaving Weak needs ≤ 3 or 2 sessions at 4). The VIX spike
  is an event and is never damped.
- **Verdict.** `candidate_verdict` = rules on smoothed statuses. The published `verdict` changes to the candidate only after
  the candidate has held **2 sessions**, except a move **into Danger** — when either the candidate or `raw_verdict` is
  Danger the verdict is Danger that session (protecting capital beats stability; `rule_id` then names the raw rule when
  only the raw statuses say Danger). Leaving Danger needs the usual 2 sessions. `days_in_state`, `state_since`,
  `previous_state`, `state_change` and `alert_state_change` all follow the published verdict.

### Pillars

For each pillar `p` ∈ `trend, participation, leadership, follow_through, stress`:

| Column | Type | Meaning | NULL when |
| :--- | :--- | :--- | :--- |
| {p}_status | VARCHAR | `Healthy` / `Neutral` / `Weak` after hysteresis (zones below; see Hysteresis) | inputs missing |
| {p}_status_raw | VARCHAR | Zone status of today's inputs, no hysteresis | inputs missing |
| {p}_dir_1d, {p}_dir_1w, {p}_dir_1m | VARCHAR | `improving` / `deteriorating` / `flat` — change of the pillar's goodness score vs 1 / 5 / 21 sessions ago | score missing now or then |
| {p}_text | VARCHAR | Plain sentence citing the inputs | inputs missing |

Goodness scores (direction): trend = MidSml400 % vs its 50 EMA (flat ±0.25 pt); participation = level (±1 pt); leadership =
10-day average net new highs (±1); follow-through = % (±2 pt); stress = −India VIX (±0.25; falling VIX = improving).

Initial zones (`ZONES`, calibrated later by the evidence engine):

| Pillar | Healthy | Weak | Neutral |
| :--- | :--- | :--- | :--- |
| Trend | MidSml400 close > its 50 EMA, 50 EMA higher than 5 sessions ago, and Nifty 50 > its 200 EMA | MidSml400 close < its 200 EMA | otherwise |
| Participation | level > 60 | level < 40 | 40–60; then **one step up** if 10-session A/D sum > 0 and % > 50 EMA rose over 5 sessions, **one step down** if both negative |
| Leadership | 10-day avg (new 52W highs − lows) > 0 and higher than 5 sessions ago | avg < 0 and lower than 5 sessions ago | otherwise |
| Follow-through | ≥ 50 % | < 35 % | 35–50 %; NULL ("Insufficient data") when < 30 breakouts |
| Stress | ≤ 3 distribution days, VIX < 18 and VIX 5-session change ≤ +10 % | ≥ 5 distribution days, or a VIX spike, or VIX ≥ 25 | otherwise (a known Weak condition decides even if other inputs are missing) |

VIX spike (`vix_spike`): India VIX **+20 % in a day closing ≥ 18**, or **+30 % over 5 sessions closing ≥ 16**. The spec's bare
+20 % fired on noise at low levels (live: +22.6 % to 12.7 on 2026-09-24; +26 % to 14.7 on 2026-07-08). 18 is the Stress
Healthy ceiling (≈ 86th percentile of live VIX 2024-05 → 2026-09); 16 (≈ 77th percentile) catches fear that builds over
several sessions without one +20 % day (e.g. 2026-03-05…09, 2024-05 election run-up).

Follow-through minimum 30 (was 10): at n = 10 one stock moves the % by 10 points (binomial SE ≈ 16 pts); at 30 the SE is
≈ 9 pts. Live median is ≈ 450 breakouts per window, so only thin early sessions go NULL.

### Pillar inputs

| Column | Type | Meaning | NULL when |
| :--- | :--- | :--- | :--- |
| midsml_close | DOUBLE | NIFTY MIDSML 400 close (index_daily) | index row missing |
| midsml_ema20 / midsml_ema50 / midsml_ema200 | DOUBLE | EMA of the index close (adjust=False), on the index's own history | < span sessions of index history |
| midsml_ema50_slope_pct | DOUBLE | 50 EMA vs 5 index sessions ago, % | as above |
| midsml_ret_1d_pct / midsml_ret_5d_pct | DOUBLE | Index return, % | history too short |
| nifty_close, nifty_ema50, nifty_ema200 | DOUBLE | Nifty 50 close and EMAs | as above |
| stocks | DOUBLE | Rows in indicators_daily that session (all series, TOTAL excluded) | never |
| above_10ema_pct / above_50ema_pct / above_200ema_pct | DOUBLE | % of stocks with close > EMA (denominator: stocks with that EMA). From breadth_daily when passed, else computed | no data |
| advancers / decliners | DOUBLE | Close vs previous close | no data |
| ad_line_10d | DOUBLE | Σ(advancers − decliners) over 10 sessions | < 10 sessions |
| above_50ema_chg_5d | DOUBLE | Change in % > 50 EMA vs 5 sessions ago (points) | < 6 sessions |
| participation_level | DOUBLE | mean(% > 50 EMA, % > 200 EMA) | either missing |
| participation_direction | VARCHAR | `up` / `down` / `none` (the one-step override) | never |
| participation_source | VARCHAR | `breadth_daily` or `indicators_daily` | no data |
| new_highs / new_lows | DOUBLE | Official new 52W highs / lows: high_t > high_52w of the prior session (lows mirrored). Source: indicators_daily.high_52w/low_52w = NSE CM_52_wk / PR `hl` snapshots via security_reference_daily, as-of (never future), 252-session fallback. A row counts only if the prior value is an official snapshot or the symbol has > 252 sessions of history | < 50 % of the session's rows valid |
| net_new_highs | DOUBLE | new_highs − new_lows | either NULL |
| net_new_highs_10d_avg / net_new_highs_10d_chg_5d | DOUBLE | 10-session mean; its change vs 5 sessions ago | window incomplete |
| stage2_count / stage2_pct | DOUBLE | Stocks with trend_template_pass (count, % of known) | column missing |
| breakouts_n | DOUBLE | Breakout events in sessions t−10…t−3: close > prior session's 20-day high on RVOL ≥ 1.5 | never (0 allowed) |
| breakouts_holding | DOUBLE | Of those, closing above their breakout close on t | never |
| follow_through_pct | DOUBLE | breakouts_holding / breakouts_n × 100 | < 30 breakouts |
| vix_close, vix_1d_pct, vix_5d_pct | DOUBLE | India VIX close and % changes | VIX row missing |
| vix_spike | BOOLEAN | +20 % 1D to ≥ 18, or +30 % 5D to ≥ 16 (Stress Weak) | never (False when VIX missing) |
| midsml_dist_day | BOOLEAN | MidSml400 down ≥ 0.2 % on higher index turnover than the prior session | index/turnover missing |
| distribution_days_25 | DOUBLE | Distribution days in the last 25 MidSml400 sessions | < 25 index sessions |
| nifty_distribution_days_25 | DOUBLE | Same on Nifty 50 (context only) | as above |
| distribution_source | VARCHAR | `index turnover_cr` (used) or `index volume` fallback | index row missing |

### Timing, readings, alerts

| Column | Type | Meaning | NULL when |
| :--- | :--- | :--- | :--- |
| timing_state | VARCHAR | `stretched` (% > 10 EMA > 80), `washed_out` (< 20), `normal` | % > 10 EMA missing |
| timing_note | VARCHAR | Plain note citing % > 10 EMA; never sets the verdict | normal / missing |
| connected_readings | VARCHAR (JSON) | `[{"id", "text"}]` of the §6.1.4 readings that fire today (text cites values); `[]` if none | never |
| connected_readings_n | BIGINT | Number of readings fired | never |
| alert_state_change | BOOLEAN | Published verdict differs from the previous session's (both non-NULL) | never |
| alert_distribution_5 | BOOLEAN | distribution_days_25 reached ≥ 5 today (was < 5) | never |
| alert_follow_through_low | BOOLEAN | Smoothed follow_through_status turned Weak today (was Neutral/Healthy) | never |
| alert_vix_spike | BOOLEAN | First session of a VIX spike (vix_spike today, not yesterday) | never |
| alert_any | BOOLEAN | Any alert today (send max once per day, after EOD) | never |
| alerts | VARCHAR (JSON) | `[{"id", "text"}]` for the alerts above | never |

Connected readings (`CONNECTED_READINGS`): `narrow_rally` (MidSml400 up each of 3 sessions ∧ % > 50 EMA below 3 sessions ago) ·
`leaders_holding` (MidSml400 5-session return < 0 ∧ new highs in last 5 sessions > previous 5) · `pullback_buy_window`
(% > 10 EMA < 20 ∧ % > 200 EMA > 60) · `choppy` (Participation ≥ Neutral ∧ Follow-through Weak) · `hidden_selling`
(Trend Healthy ∧ ≥ 4 distribution days) · `benchmark_split` (Nifty 50 and MidSml400 on opposite sides of their 50 EMA).

---

## group_daily — taxonomy groups (§4.5, §7.4)

One row per `(trade_date, level, floor, group_name)` where the group has ≥ 1 member that session.
Column names are the ones `App/services/groups.py::_GD_FIELDS` reads first (checked by tests/test_derived_group_daily.py).
Membership is decided per session here; the live fallback fixes members at as_of — identical on the as_of session
(verified: board ranks for all / 1000 / watch × 4 levels on 2026-09-25 match the live service, 0 mismatches).
Indexes: `(trade_date, level, floor)`, `(level, group_name)`.

| Column | Type | Meaning | NULL when |
| :--- | :--- | :--- | :--- |
| trade_date | TIMESTAMP | Session | never |
| level | VARCHAR | `Broad Sector` · `Sector` · `Broad Industry` · `Industry` (stocks_master broad_sector / sector / broad_industry / industry; current mapping) | never |
| floor | VARCHAR | `all` · `1000cr` (member mcap ≥ ₹1,000 Cr that session) · `watch` (₹300 Cr ≤ mcap < ₹1,000 Cr that session). API floors `all` / `1000` / `watch` read these rows (App/services/groups.py `_gd_floor_values`) | never |
| group_name | VARCHAR | Group label | never |
| members | BIGINT | Member stocks that session | never |
| mcap_total_cr | DOUBLE | Σ member mcap | no member mcap known |
| mcap_basis | VARCHAR | `reference_asof` (security_reference_daily.market_cap_cr as-of, ≤ 10 days old, for ≥ half the members) or `price_scaled_current` (stocks_master mcap × close_t / close on its market_cap_date — uses today's share count, i.e. **not** point-in-time) | never |
| ret_ew_1d / 5d / 21d / 63d | DOUBLE | Equal-weight mean of member returns over h sessions (each member's own sessions), %. A member's return is excluded (not filled) when its window contains a 1-day move ≤ −35 % or ≥ +100 % (unadjusted corporate action; `SPLIT_DOWN`/`SPLIT_UP`, shared with the live API) | no member has a clean h-session window |
| ret_cw_1d / 5d / 21d / 63d | DOUBLE | Cap-weighted return, weights = mcap at the start of the window (mcap_t × close_{t−h}/close_t), % | no member mcap |
| excess_nifty_21d / 63d | DOUBLE | ret_ew − Nifty 50 return (same horizon, index sessions), pts | either missing |
| excess_midsml_21d / 63d | DOUBLE | ret_ew − MidSml400 return, pts | either missing |
| excess_cw_midsml_21d / 63d | DOUBLE | ret_cw − MidSml400 return, pts | either missing |
| rs_ratio | DOUBLE | JdK-style RS-Ratio = 100 × EMA10(RS) / EMA50(RS), RS = equal-weight group index / MidSml400 | < 50 group sessions or no benchmark |
| rs_momentum | DOUBLE | 100 × rs_ratio / rs_ratio 10 group-sessions ago | < 60 group sessions |
| rrg_quadrant | VARCHAR | `Leading` (ratio ≥ 100, mom ≥ 100) · `Weakening` (≥ 100, < 100) · `Lagging` (< 100, < 100) · `Improving` (< 100, ≥ 100) | ratio/momentum NULL |
| days_in_quadrant | DOUBLE | Consecutive group sessions in this quadrant | quadrant NULL |
| rank_score | DOUBLE | mean(excess_midsml_21d, excess_midsml_63d) | either missing |
| rank | DOUBLE | 1 = strongest within (trade_date, level, floor); only groups with ≥ 3 members and a score | < 3 members or no score |
| rank_n | DOUBLE | Groups ranked that day in this level × floor | never |
| rank_chg_5d / 20d / 63d | DOUBLE | rank h group-sessions ago − rank today (positive = moved up) | either rank NULL |
| pct_above_50ema / pct_above_200ema | DOUBLE | % of members with close > EMA (denominator: members with that EMA) | no member has the EMA |
| pct_trend_template | DOUBLE | % of members passing trend_template_pass | column NULL for all |
| new_highs_52w / pct_new_highs_52w | DOUBLE | Members making an official new 52W high (definition as regime_daily.new_highs), count / % | < 50 % of members valid |
| turnover_cr | DOUBLE | Σ member turnover | never (0 allowed) |
| turnover_share_pct | DOUBLE | Group turnover / Σ over all groups of the same level × floor that session, % | total 0 |
| turnover_share_5d_avg / 20d_avg | DOUBLE | Rolling mean of turnover_share_pct over 5 / 20 group sessions | window incomplete |
| turnover_share_delta | DOUBLE | 5d avg − 20d avg (money flow), pts | either NULL |
| turnover_share_5d_chg_5d | DOUBLE | 5d avg vs 5 group-sessions ago, pts | window incomplete |
| top1_turnover_share_pct | DOUBLE | Largest member's share of group turnover, % | group turnover 0 |
| concentration_flag | BOOLEAN | top1 share ≥ 50 % and ≥ 3 members | never |
| delivery_value_cr | DOUBLE | Σ delivery_qty × close | no delivery data (e.g. BE series) |
| deliv_acc_1d_pct | DOUBLE | (delivery value on up days − on down days) / delivery value, % (−100…100) | no delivery |
| deliv_acc_10d_pct | DOUBLE | Same over the last 10 group sessions (sums) | no delivery in window |
| acc_day_members_pct | DOUBLE | % of members with an accumulation day (close up ∧ delivery % > its 20-day average) | inputs missing |
| deal_net_10s_cr | DOUBLE | Σ bulk/block net value (BUY − SELL, collapsed prints, PROP excluded) over the last 10 group sessions | deals not passed, or window starts before the first deal date |

---

## setup_daily — Desk queues (§7.2)

One row per `(queue, symbol, trade_date)` while the symbol is in the queue. Indexes: `(trade_date, queue)`, `(symbol)`.

| Column | Type | Meaning | NULL when |
| :--- | :--- | :--- | :--- |
| trade_date | TIMESTAMP | Session | never |
| queue | VARCHAR | `darvas_squeeze` · `darvas_10ema` · `vcp` | never |
| symbol | VARCHAR | NSE symbol | never |
| setup_id | VARCHAR | `{queue}:{symbol}:{first_seen YYYYMMDD}` — identity; resets after ≥ 5 absent sessions | never |
| first_seen | TIMESTAMP | First session of this identity | never |
| setup_age_sessions | BIGINT | Sessions since first_seen, inclusive (1 = new today) | never |
| status | VARCHAR | `new` (first session) · `active` (also in queue the previous session) · `returning` (back after 1–4 absent sessions) | never |
| signal_date | TIMESTAMP | Squeeze: bar that qualified (may be ≤ 4 sessions back when persisting). 10 EMA: the 10 EMA touch (Pullback / Trace-back) or t (Catch-up). VCP: end of the last contraction | never |
| close_price | DOUBLE | Close on t | never |
| trigger_price | DOUBLE | Squeeze: Darvas TopBox. 10 EMA: high of t. VCP: last-T high (pivot) | not computable |
| stop_price | DOUBLE | Squeeze: 10 EMA × 0.985 (desk contract). 10 EMA: lowest low from signal_date to t. VCP: last-T low | 10 EMA Catch-up (no touch) |
| risk_pct | DOUBLE | (trigger − stop) / trigger × 100 | trigger/stop NULL or stop ≥ trigger |
| distance_to_trigger_pct | DOUBLE | (trigger / close − 1) × 100 | trigger NULL |
| rvol, delivery_pct, avg_delivery_pct_20d, rs_percentile, away_52w_high_pct, atr_pct | DOUBLE | Snapshot from indicators_daily on t (rs_percentile is the peer rank, K2) | source NULL |
| adv_cr | DOUBLE | avg_traded_value_cr_20d (turnover_cr fallback) | both NULL |
| mcap_cr | DOUBLE | Market cap on t (see mcap_basis) | no master/reference |
| mcap_basis | VARCHAR | `reference_asof` or `price_scaled_current` (as group_daily) | mcap NULL |
| features | VARCHAR (JSON) | Queue-specific snapshot. Squeeze: darvas_top, darvas_bottom, squeeze_pct, squeeze_pct_5d_ago, tightening, candle_range_pct, squeeze_age, box_age_sessions, failed_low, ema_floor, persisted. 10 EMA: flavor (Pullback/Trace-back/Catch-up), away_10ema_pct, thrust_pct, ema_10. VCP: n_contractions, depths_pct[], bars[], volume_ratios[], weeks, footprint, vdu_ratio (3-day / 20-day volume), sessions_since_last_t | never (values inside may be null) |

Queue definitions reuse the desk predicates (see the module docstring of `setup_daily.py`); pool = mcap ≥ ₹1,000 Cr,
20-day ADV ≥ ₹3 Cr, band > 5 % (NULL passes), no GSM/`STAGE 2` remark, no `-RE`/`_RE`, close > 200 EMA (or 200 EMA NULL).
Windows: squeeze on full history (box warm-up 300 bars in incremental runs), 10 EMA on the last 60 sessions, VCP on the last 150.
Full builds cost ~1 ms per candidate window (10 EMA, VCP); pass `setup_workers` to parallelise, or run incrementally (`incremental_setup_args`).

---

## deal_session_net — bulk/block flow per symbol × session (§4.5, §7.5)

One row per `(trade_date, symbol)` with ≥ 1 deal print. Indexes: `(trade_date)`, `(symbol)`.
Prints are collapsed on (trade_date, symbol, client, side, quantity, price) first. A print flagged `deals.is_prop` is PROP
whatever its clientele; value = `deals.deal_value_cr` (qty × price / 1e7 when missing) — as the live API
(`App.services.universe.collapsed_prints_sql`). Event rules are **one module**, `Scripts/derived/deal_rules.py`, imported by
both this builder and the live fallback in `App/services/deals.py`, so stored and live labels cannot drift.

| Column | Type | Meaning | NULL when |
| :--- | :--- | :--- | :--- |
| trade_date, symbol | TIMESTAMP, VARCHAR | Key | never |
| n_prints / n_clients | BIGINT | Collapsed prints / distinct clients | never |
| deal_types | VARCHAR | e.g. `Bulk`, `Block+Bulk` | never |
| buy_qty / sell_qty / net_qty | DOUBLE | Shares | never |
| buy_value_cr / sell_value_cr / net_value_cr / gross_value_cr | DOUBLE | Σ print value (deal_value_cr, else qty × price / 1e7) | never |
| net_value_cr_ex_prop | DOUBLE | Net excluding PROP clients (used for events and ADV) | never |
| net_value_cr_fii / _dii / _prop / _corporate / _hni / _other | DOUBLE | Net by client class (deals.clientele, else institutional_engine.classify_client) | never (0 if none) |
| buying_houses / selling_houses | DOUBLE | Non-PROP clients that are net buyers / net sellers that day | never |
| buy_vwap / sell_vwap / vwap | DOUBLE | Value-weighted prices (vwap = all prints) | no prints on that side |
| close_price | DOUBLE | prices_daily close on t | symbol not in prices (e.g. SME) |
| deal_price_vs_close_pct / buy_vwap_vs_close_pct | DOUBLE | (vwap / close − 1) × 100 | close NULL |
| adv_cr | DOUBLE | 20-day average traded value as of the **previous** session (indicators, else prices turnover) | < 20 sessions of history |
| net_vs_adv | DOUBLE | net_value_cr_ex_prop / adv_cr (× ADV) | adv NULL/0 |
| deal_qty_pct_volume | DOUBLE | max(buy_qty, sell_qty) / session volume × 100 | volume NULL |
| round_trip_value_cr | DOUBLE | Σ over clients of min(buy value, sell value) the same day | never |
| round_trip_ex_prop_cr | DOUBLE | Same, non-PROP clients only (churn input) | never |
| gross_ex_prop_cr | DOUBLE | Gross value of non-PROP prints (churn denominator) | never |
| prop_value_cr | DOUBLE | Gross PROP value | never |
| matched_value_cr | DOUBLE | BUY value matched by SELLs from other clients: print by print (qty ±1 %, price ±0.25 %), or in aggregate (non-PROP buy vs sell qty ±1 %, VWAPs ±0.25 %, no client on both sides); the larger | never (0) |
| matched_buyers_institutional | BOOLEAN | All matched buyers are FII/DII | no match |
| net_buy_sessions_10 | DOUBLE | Sessions with net_value_cr_ex_prop > 0 (rounded to 1e-6 Cr, so float noise is not a buy) among the last 10 market sessions (incl. t) | never |
| event_type | VARCHAR | First matching rule below | no rule matched (not expected) |
| event_rule | VARCHAR | Text of the matched rule | as above |

Event rules (`deal_rules.EVENT_RULES`, top-down): `transfer_interse` (matched value ≥ 50 % of buy value, buyers not all
FII/DII) · `placement` (same, buyers all FII/DII) · `churn` (PROP removed first: non-PROP round trips ≥ 50 % of non-PROP
gross, or net ex-PROP = 0 after rounding) ·
`accumulate` (net ex-PROP > 0 with another net-buy session in the prior 9) · `fresh` (net ex-PROP > 0, none in the prior 9) ·
`distribute` (net ex-PROP < 0).
