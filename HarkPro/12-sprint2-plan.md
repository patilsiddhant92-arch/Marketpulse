# 12. Sprint 2: the build list (2026-10-10)

Siddhant approved the chart design and decisions 1-3, then said "go through the build list". Merge to main: NOT YET. Line alerts: dropped.

| Agent | Scope | Branch | Worktree |
|---|---|---|---|
| chart | Chart v2 (Clean/Info) + chart tools | hark/s2-chart | work/wt2/chart |
| diverg | RSI divergence engine + endpoint + Setups scanner | hark/s2-diverg | work/wt2/diverg |
| cleanup | Decisions 1-3, dead views, TV copy, typed Deals API | hark/s2-cleanup | work/wt2/cleanup |
| wiring | Group state source, deal icon, source picker, UI standard | hark/s2-wiring | work/wt2/wiring |
| extras | Research trait strip + signal log, fund alerts, research_lab in pipeline | hark/s2-extras | work/wt2/extras |

The rules from 11-implementation-plan.md still apply: your own worktree only, commit as Hark, never push, DB read-only, tests + tsc must pass. You may regenerate `frontend/src/api/types.gen.ts`; Hark regenerates it again at merge.

## Chart v2 (approved design): see mockups/chart-v2/mode_IDEAFORGE_clean.png and _info.png
- **Clean** toggle: EMA 10/20/200 (50 optional), Darvas as shaded boxes (top line green, bottom red, faint fill; the current box is brighter) + dotted 5-bar top extension and EMA10 projection, volume bars at the bottom of the price pane with the 20D avg line, RSI 14 pane + SMA 14 of RSI + divergence lines (the latest bright, older faded). Style: Candles / Line / Vol candles (candle width = volume / 20-bar avg, clamped 0.35-3x, TradingView volume candles). D/W/M.
- **Info** toggle adds: status chips (e.g. Failed breakout / Below box a-b / On FII deal ₹x) + stat chips (−x% from 52W high, ATR%, ₹Cr/day, Deliv%, RSI), event candles (deal B/P/S/C/T, box breakout ↑ / breakdown ↓ coloured; gap and vol-spike only as small dots), one deal note callout per deal cluster (net buy ₹Cr + who, churn ₹Cr), deal price lines, Darvas buy stop (box top + 1 tick) and stop (box bottom − 1 tick) lines, right-axis value tags (last, EMAs, box, deal lines), "The read" (3-4 rule-generated plain-English lines, 04-writing-style) and a Key levels grid (distance from the last close).
- Candle colours: Events / Normal (green/red) switch, global.
- Premium: an OHLC + volume legend that follows the crosshair (the last bar by default), smooth wheel/pinch zoom + pan, a tap/click on a candle opens its story (OHLC, events, deals that day).
- Settings are global (localStorage) and the same chart component is used in every tab's drawer.
- Chart tools: rectangle, measure, long/short position, anchored VWAP, compare (overlay a 2nd symbol in %), bar replay. NO line alerts.

## Divergence API contract (diverg builds it, chart consumes it)
`GET /api/v2/charts/{sym}/divergences?tf=D|W|M&as_of=` -> Envelope rows:
`{side: "bull"|"bear", type: "Strong"|"Medium"|"Weak"|"Hidden", p1_date, p2_date, p1_price, p2_price, p1_rsi, p2_rsi, confirm_date, trigger_price, stop_price, status: "watching"|"triggered"|"failed"}`
Rules (prototype at tools/divergence/detect_prototype.py): 3-bar pivots on low (bull) / high (bear), confirmed 3 bars after the pivot (no look-ahead); pivots 5-60 bars apart; "equal" = within 0.5 ATR(14) for price, 2 RSI points for RSI. Regular bull needs an RSI pivot < 40 and RSI never > 60 between; bear mirrored (> 60, never < 40). Hidden bull needs close > EMA50 and RSI2 < 50; hidden bear mirrored. Trigger = the high between the lows (bull) / the low between the highs (bear); stop = the 2nd pivot's low/high.
`GET /api/v2/setups/divergences?tf=&side=&types=&as_of=` -> today's confirmed divergences across the ≥ ₹1,000 Cr universe (symbol, group, type, side, confirm_date, trigger, distance to trigger %, RSI, the Pulse group state when available).

## Result (2026-10-10 14:00)
All five branches merged into hark/harkpro. tsc clean, vitest 319/319 (45 files), pytest 181 passed across the API v2, tab, deals, research, incremental and divergence suites plus 85 new tests. openapi up to date. Legacy NiceGUI tests can't run here (nicegui not installed); their failures are unchanged.

### Needs action on the user's PC
- **Full DB rebuild.** The new `rsi_divergence_type` column makes the first nightly append fall back to a full recompute (deliberate, so the old look-ahead flags are wiped). The family-transfer rule also only shows in Deals after the derived tables are rebuilt.

### Calls made (open to change)
- "The read" is built client-side (chartRead.ts), so it also works in replay and on W/M bars. No backend endpoint.
- Fund alerts: followed AND good-record FII/DII AND strong chart (stricter than 08 §5.3's "or").
- Sector Intel group state now uses the Pulse source (all stocks, per 07 §4.1), so some states change.
- Divergence "equal price" = 0.5 ATR, which makes Medium the most common type; tighten it if the scanner is noisy. Monthly is thin until the 5-year data lands.

### Left for next pass
- RS pane in Stock 360 (Chart v2 has none yet). The Deals drawer chart, Charts grid tiles and group/index charts still use ui/Chart. Old ui/volumeCandleSeries.ts draws black candles (Chart v2 has its own fix).
- Deals side colours to tokens, stockContext.dealsHref points at an old view, two Research QuadrantChips, a few custom Pulse tables.
- A followed house only alerts if it's in the top 3 buyers.
