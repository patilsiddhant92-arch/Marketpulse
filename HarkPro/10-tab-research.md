# Research (merged with History Lab): round 1 (2026-10-09)

Siddhant: "For the historical and research tab: stocks' behaviour before blasting moves on daily, weekly and monthly; index study compared to today; when did we see a similar trend in the last market? Like currently the market is choppy. Was there a similar situation before, and what happened then? You can add more value and enhance it with more analysis and studies that help."

Decision: **Research and History Lab become one tab** (working name *Research*). `03-tab-history-lab.md` is merged into this file and kept for reference.

## 1. What exists today (main @ 56a58b8)
- The Research tab (spec 7.6) has five views: Market analogs, Big movers, Pre-move watch, Group studies and Setup evidence.
- All of them read evidence-engine tables (`market_analogs`, `big_move_*`, `group_entry_study`, `pre_move_watch`) built by `Scripts/evidence`. When those tables are missing, a view shows "unavailable".
- Big-move events are defined as +30%/+50% within 60 sessions (or an upper circuit), with lift/precision vs controls.
- Local data covers May 2024 to Oct 2026 (565 sessions, with a gap from 13 Aug to 8 Oct). Real conclusions need Siddhant's 5-year archive, so every study must run there.

## 2. The tab: five questions, one view each
| # | View | Question it answers |
|---|---|---|
| 1 | **Market now vs then** | What kind of market is this (trend, choppy, correction), and when did it look like this before? |
| 2 | **What happened next** | After those similar periods: index paths, how long the phase lasted, how it ended, what led out |
| 3 | **Before the big moves** | What did stocks look like on D/W/M before they blasted? Which of today's stocks look like that? |
| 4 | **Index study** | Nifty / MidSml400 / Smallcap250 / equal-weight market today vs past cycles (drawdown, recovery, time) |
| 5 | **Scorecard** | Are our own signals (Setups, Deals verdicts, group ranking, Pulse mood) working lately? |

Pre-move watch is cut as a separate view. It folds into view 3 ("Looks like pre-move today") once its precision has been tested out of sample. Group studies move to Sector Intel evidence.

## 3. View 1: Market now vs then (regime + analogs)
**Regime label each day** (rule-based, so it's explainable; thresholds tested in round 2):
| Regime | Proposed reading (equal-weight market + MidSml400) |
|---|---|
| Trending up | 50 EMA rising, price > 50 EMA, efficiency ratio(20) > 0.35, breadth above 50 EMA > 55% |
| Choppy / range | efficiency ratio(20) < 0.2, price crossed the 20 EMA ≥ 4 times in 20 sessions, 20-session range < 6%, breakout follow-through < 40% |
| Correction | price < 50 EMA, 50 EMA falling, drawdown from the 52W high 8–20% |
| Bear | drawdown > 20%, or price < 200 EMA with the 200 EMA falling |
| Recovery | up from a correction/bear low ≥ 10% and breadth expanding (Pulse breadth-expansion flag) |
- **Efficiency ratio** = net move ÷ sum of daily moves (Kaufman). Near 0 is chop; near 1 is a clean trend. It is the cleanest single "choppy" number. ADX(14) is shown beside it.
- **Analogs**: the nearest 10 past days by a feature vector (breadth %, EMA slopes, efficiency ratio, drawdown, VIX, new highs, follow-through). Picks are at least 10 sessions apart. Feature on/off as in the History Lab draft. The existing `market_analogs` table is the starting point.
- **Display**: a regime ribbon under the index chart for the whole archive. Today's regime and how many sessions it has lasted. A list of the 10 nearest past episodes, each with its date range.

## 4. View 2: What happened next
For today's regime and for the analog days:
- **Duration**: how long past choppy phases lasted (median and range), and how many sessions this one has run.
- **Exit**: % of past choppy phases that ended in an up-trend vs a correction. Triggers that came first (breadth thrust, new-high expansion, VIX spike).
- **Forward paths**: a fan chart of the market +5/+10/+20/+60 sessions, compared with the base rate of all days.
- **What worked in it**: Darvas squeeze, 10 EMA, VCP and momentum hit rates in each regime (from the scorecard data). Example output: "In chop, breakouts failed 62% of the time; 10 EMA pullbacks held up better". The answer is unknown until it's tested.
- **Who led out**: the groups whose breadth turned first in the 10 sessions before each chop ended.

## 5. View 3: Before the big moves (D / W / M)
- **Events**: daily (+30% in 20 sessions), weekly (+50% in 13 weeks), monthly (+100% in 12 months). Stocks ≥ ₹1,000 Cr at the time. The first day of the move is t0.
- **Traits at t0 vs matched controls** (same date, same mcap band, no big move):
  - base length and depth
  - contraction count (VCP T)
  - distance from the 52W high
  - RS percentile and the RS line's new high before price
  - volume dry-up (10D/50D)
  - delivery % vs its own average
  - up/down volume
  - tightness: weekly closes within 1.5% (3+ weeks)
  - group state (Sector Intel)
  - market regime
  - recent deals
  - results within 10 sessions
  - float/promoter pledge
- **Output**: lift (how much more common a trait is before big moves than in controls) and **precision** (of stocks with the trait, how many went on to move). Precision matters more; lift alone flatters rare traits.
- **Paths**: median price, volume and RSI path from t−60 to t+60 for each timeframe. The "typical" pre-move chart is drawn as a template.
- **Today**: stocks whose traits match the top-precision combination, labelled *research*, with the out-of-sample hit rate beside them. Not a setup until it beats Setups.
- **Post-mortems**: each big mover of the last month with a one-line "what it looked like before" and a link to Charts.

## 6. View 4: Index study
- Nifty 50, MidSml400, Smallcap250 and the equal-weight ≥ ₹1,000 Cr market on one % chart.
- Overlay today's path from its last major low/high against past cycles, aligned on day 0.
- A **drawdown table** with every fall > 8% since the archive starts: depth, sessions down, sessions to recover, what breadth did at the low. Today's row is highlighted.
- **Leadership**: large vs mid vs small over 20/60 sessions (ratio lines), with the past share of time each led.
- **Seasonality** (light): month-of-year and results-season returns, with sample size, only if the 5-year sample shows something.

## 7. View 5: Scorecard (the honesty view)
- Every verdict the app shows (Setups rows, Deals verdicts, Sector Intel ranks, Pulse mood) is logged on the day it's shown.
- 5/10/20 sessions later it's graded vs the equal-weight market.
- **A monthly table**: hit rate, average excess, and trend vs its own history.
- **Rule**: a signal that has lagged the market for 3 months in a row gets a "not working now" chip everywhere it shows (as Sector Intel's "working now" gauge does).
- This also gives the "what worked in this regime" data for View 2.

## 8. More studies I'd add (value adds)
1. **Breakout follow-through rate** (% of box breakouts still above the breakout price after 5 sessions). The best live "is the market paying breakouts?" reading. It goes to Pulse.
2. **Post-results drift**: a gap-up on results + close in the top 25% of range → next 20/60 sessions.
3. **Failed-breakout reversal**: a stock that broke out and closed back inside the box within 3 sessions. How often it was a top.
4. **Sector rotation clock**: the order in which groups led in past recoveries.
5. **RSI divergence record** (from Charts §6): does a bearish divergence near highs actually precede falls in this market?

## 9. Build notes
- The studies run in `Scripts/evidence`, writing tables. The tab only reads, as it does now. Each study prints its sample size and date range.
- Point-in-time rules: today's taxonomy and mcap leak into the past (see 05-data-gaps). Studies must use as-of mcap where it exists and flag where it doesn't.

## 10. Open questions for Siddhant
1. The merge (one Research tab with five views) and the cut of Pre-move watch as its own view: OK?
2. Does the "choppy" definition in §3 match what you see now? Name 2–3 past periods you remember as choppy, and I'll check the rule labels them correctly.
3. Big-move thresholds in §5 (D +30%/20s, W +50%/13w, M +100%/12m): right for your style?
4. Can I run these studies on your 5-year archive? I need the daily files from 2021 or the built DB (the repo has about 18 months).
