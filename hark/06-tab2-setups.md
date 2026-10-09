# Tab 2 — Setups / Screener (discussion, opened 2026-10-09)

Status: **discussion**. No code until the spec is locked.

## Siddhant's screeners (his words, condensed)
1. **Darvas Squeeze** — the candle sits between the Darvas top box and the 10 EMA. It may cut either line, but if it is in the box, the stock must be on the list.
2. **Darvas 10 EMA** — OHLC above the 10 EMA. Case 1: price retraces to the 10 EMA. Case 2: the 10 EMA catches up to price.
3. **VCP** — based on Manas Arora's teaching (X and YouTube). Current logic needs work.
4. **Momentum** — the current scanner, with sector and industry leaders from the watchlist. Copy stocks by bucket, industry, sector.
Tables must show valuable data.

## Features to keep from the current app
- Chart with more data, kept clean: coloured candles for events and deals, Darvas box, 10 and 20 EMA.
- Basic drawing tools: lines, Fibonacci (TradingView-like).
- RSI with all divergence cases on price vs RSI.
- Chart grid, synced, for the stocks in the screener.
- Copy watchlist in TradingView format (global).
- Symbol click opens TradingView.
- RS score on TradingView.
- Peer view: show a better stock in the same group when there is one.

## Audit: current logic vs Siddhant's definition (data as of 2026-08-13)

### Darvas Squeeze (`Scripts/darvas_squeeze.py::evaluate_squeeze_bar`, params `Scripts/desk_contract.py::DARVAS`)
Box: Pine Darvas, `boxp=5`. Current membership needs ALL of:
| Gate | Current rule | In Siddhant's definition? |
|---|---|---|
| Close in zone | 10 EMA × 0.998 ≤ close ≤ top × 1.002 (wicks may pierce) | Yes |
| Squeeze width | (top − 10 EMA) / top ≤ 5% | No |
| Distance to top | close within 5% of top | No |
| Candle range | (high − low) / close ≤ 4% | No |
| Dry volume | RVOL ≤ 1.0 | No |
| Rising 10 EMA | 10 EMA today > yesterday | No |
| Trend | 10 EMA ≥ 20 EMA × 0.995 | No |
| Pool | mcap ≥ ₹1,000 Cr, ADV ≥ ₹3 Cr, band > 5%, no GSM, close > 200 EMA | Partly (₹1,000 Cr rule) |
| Persistence | stays listed 5 sessions if the coil holds | No |

Counts on 2026-08-13 (≥ ₹1,000 Cr, above 200 EMA, valid box: 856 stocks):
- close inside the zone: **342**
- any part of the candle touches the zone: **556**
- current queue: **120** (111 of them have close in zone; the rest are persistence carry-overs)
- the 5% squeeze-width gate alone removes 197 of the 342.

Conclusion: the current logic is **much stricter** than the stated definition.

### Darvas 10 EMA (`classify_darvas_10ema_frame`)
Needs a rising 10 EMA and close > 10 EMA (wicks may undercut). Three flavours:
- **Pullback** = Siddhant's case 1. Bar touches the 10 EMA, |distance| ≤ 3.5%, RVOL ≤ 1.0.
- **Catch-up** = Siddhant's case 2. Price within 5% of its 5-day high close, 1.5–12% above the 10 EMA, RVOL ≤ 2.2, gap to the EMA shrinking.
- **Trace-back** = not in Siddhant's definition. Touched the 10 EMA in the last 8 sessions, then rose 0.3–18%.
Also: stocks already in Squeeze are removed, and tightening squeezes (≤ 8%) are skipped. No Darvas box condition is used.
Current queue on 2026-08-13: 284.

### VCP (`Scripts/minervini_geometry.detect_contractions` + `Scripts/vcp.py::VCP`)
Fractal swings over 150 sessions, ≥ 2 contractions with strictly shrinking depth, close inside the last contraction. Gates: close ≥ ₹30, within 25% of the 52W high, 20D avg volume ≥ 100k. Volume dry-up = 3D / 20D volume. Queue: 41.

### Momentum (`App/services/momentum.py`)
Parity port of the proven scanner: trigger in the last N sessions, EMA stack, within 25% of 52W high, ≥ 50% above 52W low, buckets by distance from 10 EMA (0–2 / 2–5 / 5–10 / 10%+), TV export with `###bucket` sections, sector/industry leaders. Keep as is.

## Open questions for Siddhant
1. Squeeze "in box": close inside the zone (342 stocks), or any part of the candle (556)?
2. Squeeze extra gates (width ≤ 5%, RVOL ≤ 1, range ≤ 4%, rising 10 EMA): drop them as filters and keep them as a tightness score and columns?
3. 10 EMA: keep or drop Trace-back? "OHLC above 10 EMA": the whole bar (low ≥ 10 EMA), or close above with the wick allowed to touch? Should the name "Darvas" mean a box condition (for example price above the last box top)?
4. VCP: which Manas Arora videos/posts? Hark can pull transcripts and draft rules from them.

## Hark's proposals (to discuss)
- **One board, tags per screener.** Each stock shows once with tags (SQZ, 10E-PB, 10E-CU, VCP, MOM). Stocks in 2+ screeners rank higher (confluence).
- **Columns that help a decision**: trigger, stop, risk % to stop, risk in ADR units, ADR%, RS rating 1–99 + RS-line-at-high flag, group rank + group mood, tightness (squeeze width, range, volume dry-up), delivery vs own 20D habit, distance to 52W high, days in setup, New / Active / Returning, event chips (results in ≤ 10 sessions is a warning), and the screener's past hit rate in today's mood band.
- **Scan count history**: how many stocks pass each screener per day, as a chart. A rising squeeze count is a market signal on its own.
- **Peer swap**: flag when a stock in the same industry has a higher RS, a valid setup and a tighter stop.
- **Review flow**: keyboard J/K through the chart grid, mark Reviewed / Plan / Skip, notes.
- **Charts**: lightweight-charts v5 is already in the app. Drawing tools (trend line, horizontal, Fibonacci) can be built as its plugins. The full TradingView charting library needs a licence application.
- **RSI divergence**: four cases: regular bullish, regular bearish, hidden bullish, hidden bearish. Detect with confirmed pivots, so no repainting.
- **RS on TradingView**: TradingView cannot read MarketPulse data. Options: a Pine script for the RS line vs Nifty 500 plus an approximate IBD-style rating, or put the RS rating into the TV watchlist section names.
- **TV export everywhere**: one global "Copy for TradingView" with grouping by bucket / screener / sector / industry.

---
## Round 2 — Siddhant's answers (2026-10-09)
- **Keep the current app and its calculations**, including RS vs Nifty MidSmallcap 400 and the momentum scanner. The redesign is about a better flow, not new maths.
- **Darvas Squeeze: keep the current strict logic.** Backtest on local history (2024-05-17 to 2026-07-15, ≥ ₹1,000 Cr, above 200 EMA), using bars with close in the zone:
  | Group | Bars | Broke above box top within 20 sessions | Median 20D return | 20D win rate |
  |---|---|---|---|---|
  | Current queue | 36,222 | **77.8%** | −0.70% | 46.7% |
  | Zone only (not in queue) | 107,466 | 60.1% | −1.12% | 45.6% |
  The strict gates find coils that break out far more often. Membership alone does not make money. The breakout and its follow-through do. Recalculate on the full five-year archive.
- **Darvas 10 EMA:** first priority = whole bar (OHLC) above the 10 EMA. Second tier = an undercut of the 10 EMA with the close back near or above it. Two cases: Retrace (price comes to the EMA), Catch-up (the EMA comes to price). Trace-back is not in his definition, so it is folded into Retrace or dropped (to decide in the spec).
- **VCP:** Hark researches Manas Arora itself. Report: `research/manas-arora-vcp.md` (21 rules, each tagged with its source: his own words, someone else's summary, or Hark's inference).
- **Table must show distance to 52W high.**
- **Tab role:** this is Siddhant's analysis tab. He sees the setups and makes his own choice.
- **Pulse → Setups link:** each stock should carry its group's state from Pulse (trending, event/news caution, money flowing out) and the reason. Full cross-tab wiring waits until Deals and Sector Intel are specified.

## Round 3 — momentum inputs and decision table (2026-10-09)
- Momentum also uses the **20D average volume** gate and a **SMA template or EMA template** toggle. Both exist in `App/services/momentum.py` (`min_avg_volume_20d`, `sma50_gt_150`/`sma150_gt_200`/`sma200_rising` vs the EMA stack). Keep both and make the template choice one visible switch.
- The table must hold data that helps him choose between stocks. It must include **delivery % trend over consecutive days** and **turnover 1D / 1W / 1M**, for the stock and for its leading sector/group.

### Proposed decision table (all fields already in `indicators_daily` / `group_daily` unless marked NEW)
| Block | Columns | Source |
|---|---|---|
| Identity | Symbol (→ TradingView), screener tags, New/Active/Returning, days in setup | setup_daily |
| Trade | Trigger, stop, risk % to stop, risk ÷ ADR | setup_daily, adr_20_pct |
| Position | Dist. to 52W high, dist. to 10 EMA, dist. to 50 EMA | away_52w_high_pct, away_10ema_pct |
| Strength | RS vs MidSml400 21D/63D, RS percentile, RS rank change 5/15/30D | rs_vs_midsml400_*, rs_rank_t* |
| Tightness | Squeeze width, range 5D/10D %, ATR% vs its 50D avg, volume dry-up | range_*_pct, atr_pct_avg_*, volume_dryup_pct |
| Delivery | Delivery % today vs own 20D avg, **streak: consecutive days above own 20D avg**, 5-day sparkline, price-up-delivery-up | delivery_pct, avg_delivery_pct_20d (streak NEW, derived) |
| Turnover (stock) | **Turnover 1D / 1W / 1M as multiple of its own 3M average** | turnover_cr (multiples NEW, derived) |
| Group | Group (sector/industry), group state from Pulse, **group turnover share Δ 1D / 1W / 1M**, group rank Δ | group_daily, sector_metrics_daily |
| Risk | Event chips (results soon, deals, surveillance) | security_events (ingestion pending), deals |

Default view shows about 12 columns: tags, symbol, 52W-high distance, 10 EMA distance, RS 63D, risk %, tightness, delivery streak, turnover 1W×, group + state, chips. The other blocks open as column groups.

## Round 4 — Hark's further proposals (2026-10-09, awaiting picks)
1. **Base rate per row**: past results of similar setups (same screener, tightness band, group state, market mood) → hit rate and median R. Source: signal_outcomes.
2. **Near-miss list**: stocks that fail exactly one gate, with the gate named. Keeps the strict Squeeze while showing what is about to qualify.
3. **Why dropped**: for each stock that left since yesterday, the rule that broke.
4. **Room to run**: distance from trigger to the nearest overhead supply (prior swing high / high-volume zone).
5. **Stock character**: this symbol's own past breakout follow-through and failed-breakout count (6M).
6. **Execution checks**: price band (5%/10% circuit), F&O ban, ex-date or results within N sessions, ASM/GSM, pledge (security_risk_daily, corporate_actions).
7. **Size from risk and liquidity**: qty = risk budget ÷ (trigger − stop), capped at a % of 20D ADV.
8. **Hand-off**: export triggers as a TradingView alert list / GTT sheet; "Add to Plan" sends trigger, stop, qty.
9. **Weekly check**: tight weekly closes and weekly position vs the 10-week line.
10. **Concentration warning**: too many picks from one group (needs Plan positions).
