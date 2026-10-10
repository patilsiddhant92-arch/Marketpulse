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
2. ~~Choppy periods~~: answered by the professional approach in §11 (two axes: index range vs trend × breakouts paying vs failing).
3. Big-move thresholds in §5 (D +30%/20s, W +50%/13w, M +100%/12m): right for your style?
4. Can I run these studies on your 5-year archive? I need the daily files from 2021 or the built DB (the repo has about 18 months).

## 11. Round 1b: how professionals define "choppy", and the approach chosen (2026-10-09)
Siddhant had no past periods in mind and asked for the professional approach.

**What professionals use**
- **Breakout traders** (O'Neil, Minervini, Stockbee/Bonde, Qullamaggie) don't define chop on the index chart. They ask one question: *are breakouts working right now?*
  - Bonde reads breadth (stocks above their MAs, new highs) and his Market Monitor breadth crossovers.
  - Minervini watches his own failed breakouts. 3–5 quick stop-outs in 2–3 weeks means reduce exposure.
  - O'Neil uses distribution days and follow-through days.
- **Technicians** measure the index's path:
  - **Choppiness Index** (Dreiss): above 61.8 is choppy, below 38.2 trending.
  - **ADX**: below 20 means no trend.
  - **Kaufman efficiency ratio**: net move ÷ total path; near 0 is chop.
- Fixed thresholds don't travel well between markets. Read each one against its own history (our standing rule).

**Approach chosen: two axes, not one label**
| | Breakouts paying | Breakouts failing |
|---|---|---|
| **Index trending** | Press: full size | Narrow: index up, few leaders work |
| **Index in a range** | Stock-picker's market: trade leaders only | **Chop: sit out or size down** |
- Index axis: Range if Choppiness(14) is in the top 40% of its own history or the efficiency ratio(20) is in the bottom 40%, on the equal-weight ≥ ₹1,000 Cr market. Otherwise Trend.
- Breakout axis: share of 50-day-high breakouts on ≥ 1.5× volume still above their breakout close 5 sessions later, over the trailing 10 sessions. Failing = below its own median.
- Both readings use point-in-time percentiles: each day is ranked only against earlier days.

**First test** (local data, Jul 2024–Aug 2026, ~465 sessions; `tools/regime_study/choppy.py` + `quadrant.py`). Each quadrant is scored by what the **next 10 sessions'** breakouts did:
| Quadrant | Days | Next breakouts holding after 5 sessions | EW market next 20 sessions |
|---|---|---|---|
| Trend + paying | 84 | **51.6%** | +1.5% |
| Range + paying | 161 | 48.8% | +0.6% |
| Trend + failing | 91 | 43.1% | +0.9% |
| Range + failing (chop) | 129 | **40.4%** | −0.9% |
| All days | | 45.8% | |
- The order is the one you'd expect, and the gap matters for a breakout trader: in chop, breakouts held about 4 in 10 times; in Press, about 5 in 10.
- On 2026-08-13 (the last session before the data gap): Choppiness 77, ER 0.16, so the index was ranging. Breakouts were still holding (49%), which puts it in the stock-picker's market. Today's reading needs the missing Aug–Oct daily files.
- A single-label rule (choppy if 2 of 3 legs agree) was tried first. It labelled 57% of days choppy, too loose to be useful, and was dropped.
- Caveats: one short sample of overlapping windows. Re-run on the 5-year archive before locking thresholds, and add the past-episode table (how long each chop lasted and how it ended).

**In the app**: Pulse shows the quadrant (one line + its record). Research View 1 shows the quadrant ribbon over the archive, the past episodes of the current quadrant, and what followed them.

## 12. Round 1c: "How could we have caught it?" case studies (2026-10-09)
Siddhant's ask: use our own screener to show where MTARTECH, STLTECH and other big movers gave entries.
Window: 2025-08-13 to 2026-08-13 (local data, before the gap). Tools are in `tools/bigmove_study/`:
- `caught.py SYM…` runs a case study for each symbol.
- `caught.py` with no arguments runs the scorecard for all movers.
- `precision.py` runs the false-alarm check.
Presets use the exact rules from `App/services/screener.py`. A "fresh" fire means the preset is true today and was false for the previous 5 sessions.

**MTARTECH** (1,396 on 29 Aug 2025 → 8,374 on 19 Jun 2026, +500%)
- First flags: Delivery thrust + EMAs converge on 12 Sep 2025 at 1,679 (20% off the low).
- Then Near 52W high and the VCP flag on 17 Sep, and Fresh 52W high on 22 Sep.
- Minervini 8/8 came last, on 14 Oct at 2,128 (52% off the low).
- Re-entry ladder: enter on the first fresh fire of Delivery thrust / EMAs converge / VCP / Fresh or Near 52W high; exit on a close below the 20 EMA; repeat. 6 trades:
  - +47%
  - +1.7%
  - +29.7%
  - +79.6% (7 Apr → 8 Jun)
  - −8.9%
  - +9.1%
  - Compounded **+246%**.
**STLTECH** (86 on 27 Jan 2026 → 661 on 13 Aug 2026, +666%)
- Delivery thrust on 30 Jan at 106 (23% off the low), then EMAs converge + VCP on 2 Feb.
- Minervini 8/8 came only on 26 Feb at 164 (91% off the low).
- Ladder, 3 trades:
  - +62.9%
  - +180.6% (8 Apr Near 52W high → 2 Jul)
  - +1.5%
  - Compounded **+364%**.

**All 226 stocks ≥ ₹1,000 Cr that doubled (low → peak) in the window**
| Preset | Movers caught | Entry above the low | Room left to peak (median) |
|---|---|---|---|
| VCP flag | 93% | +37% | +77% |
| Delivery thrust | 91% | +37% | +76% |
| EMAs converge | 60% | **+28%** | +85% |
| Near / Fresh 52W high | 85% | +68–71% | +45% |
| Stage 2 / EMA stack | 82% | +63% | +46–48% |
| Minervini 8/8 / SMA template | 62–64% | +58–62% | +48–51% |
- Early-structure signals (Delivery thrust, EMAs converge, VCP) fire roughly 30 points nearer the low than the trend-template family. The template is a confirmation, not an entry.
- Ladder across all 226: median +31% vs a median move of +136%, median 3 trades. A plain 20 EMA exit gives back most of the move: it captures the strongest leg and misses the rest.

**Honest check (precision.py)**: a preset that "caught" 90% of the winners may fire on everything.
- Across all fresh fires from Aug 2025 to Feb 2026, the share followed by +50% within 120 sessions:
  - All stock-days: 9.5% (base rate).
  - Single presets: 9–12%.
  - With RS ≥ 80: 11–14%. Best were EMAs converge 14.1%, VCP 13.2% and Delivery thrust 13.1%.
- So no single screener hit picks the winner. The edge comes from:
  - stacking evidence (RS + structure + delivery);
  - small losses on the ~87% that don't run;
  - **re-entering** the ones that keep setting up.

**Desk bug found (look-ahead)**
- MTARTECH and STLTECH never appear in `setup_daily` (Darvas/10 EMA/VCP queues) on any date.
- Cause: `Scripts/derived/setup_daily.py` `_pool` falls back to *today's* `stocks_master.band` when there is no point-in-time band, and the reference band only starts in Jul 2026. Both are in BE / 5% band now, so the whole history was excluded. 248 stocks are in BE on 13 Aug.
- This hides exactly the stocks that ran hardest (they get moved to 5% bands *because* they ran).
- Fix: use the series as of each date (EQ → band > 5%) or leave the band unknown before the reference starts. Then rebuild setup_daily. This is a main-app fix, so it needs the user's OK.

**Proposed Research view: Case study**
- Type a symbol (or pick one from the big-mover list). The chart shades the move and marks every preset's fresh fire with its letter, plus the ladder's entries/exits and P&L.
- A table lists the first fire per preset (entry, % off the low, room left).
- The scorecard above works as the "which screen finds them earliest" panel, always shown with its precision so it never oversells.
- Next studies:
  - Exit test: 10 vs 20 vs 50 EMA, and the Darvas box low.
  - Pre-move traits vs matched controls (View 3).
  - Out-of-sample on the 5-year archive.

## 13. Round 1d: what separates a runner from a fizzle (multi-timeframe, weeks/months) (2026-10-10)
Siddhant: one signal on one day isn't enough. Study EMA position, weekly and monthly structure, accumulation over weeks/months, and improvement.
The scripts are `tools/bigmove_study/premove.py` + `premove_split.py`.

**Design (professional "model book" method, with controls)**
- Event: a ≥ ₹1,000 Cr stock first closes 20% above its 120-session low (an *early lift*, the moment you would notice it).
- Events run Nov 2024–Feb 2026: 756 in all, 156 runners and 600 fizzles.
  - Runner: +50% within 120 sessions.
  - Fizzle: never +15%.
  - Base runner rate: 20.6%.
- 30 traits, measured at the event close:
  - **D**aily: EMA 20/50/200 position, RSI, distance to 52W high/low.
  - **W**eekly: 10W/30W position + slope, weekly RSI, higher weekly lows.
  - **M**onthly: 10M EMA, monthly RSI, 6M/12M return.
  - **A**ccumulation over 10–13 weeks: up/down volume, accumulation − distribution weeks, delivery vs 6M, traded value vs 6M.
  - **I**mprovement: RS now/1M/3M change, template checks and gain, 200 EMA slope.
  - **B**ase: 50d range, ATR vs avg, days from low.

**Findings**
1. **Two different families. Don't mix them.**
   - *Turnaround lifts* (below the 200 EMA): 329 events, 25.8% runners. Beaten-down, deep below the 30W/10M averages, and a fast, forceful lift.
   - *Trend lifts* (above the 200 EMA): 254 events, 14.2% runners. In this window the turnaround family produced more runners, which a pure Minervini screen never sees.
2. **Force of the lift matters in both.** Top vs bottom third of the 50-day range: 42.7% vs 10.0% runners (turnaround), 22.4% vs 5.9% (trend). Fewer days from the low also helps.
3. **Inside the trend family, the profile is *early, not extended*.**
   - The 10W only a little above the 30W (21.2% vs 5.9% when far above), with the 30W rising.
   - Close well above the 20 EMA (20.0% vs 5.9%).
   - Trend-template checks rising over the last month (18.8% vs 9.4%).
4. **The accumulation counts were weak in this sample.** Up/down volume, accum − distribution weeks and delivery vs 6M gave lifts of only 1.1–1.37×, and often the "wrong" side (runners had *less* visible accumulation). Silent accumulation as measured from EOD volume/delivery is not visible here. It may need deals, shareholding changes, or a longer window.
5. **Regime dominates.** Runner rate by quarter of the event:
   - 2025 Q1: 40.0% (the March 2025 bottom)
   - 2026 Q1: 30.5%
   - 2025 Q3: 7.5%
   - 2024 Q4: 8.5%
   The same chart is worth 4–5× more in a good tape, so this ties to the regime quadrant in §11.
6. **Out-of-sample check.**
   - A 10-trait count was picked on Nov 2024–Jun 2025 and tested on Jul 2025–Feb 2026 (250 events, base 18.4%).
   - Score 0–3: 13.2%. Score 6–7: 33.3%. Score 8–10: 28.6%.
   - About 1.6–1.8× the base rate, but the picked traits mostly describe the *turnaround* family. Needs the 5-year archive before anything is locked.

**Caveats**
- One 2-year sample with a crash-and-recovery inside it, and overlapping windows.
- A +50% target favours volatile, beaten-down stocks. The next round should measure moves in ATR units and vs the market.

**Proposed Research View 3 ("Before the big moves"), revised**
- Two tabs: *Trend lifts* and *Turnaround lifts*. Each shows:
  - the trait profile (runner vs fizzle medians);
  - today's early lifts scored by trait count;
  - the regime quadrant as a multiplier.
- Case study per stock (section 12): a D/W/M strip showing which traits were on in the 13 weeks before the lift, plus the entry ladder.

**Desk look-ahead fix**: `HarkPro/patches/setup_daily-band-lookahead.patch`. Before the reference band exists, it uses the series traded that day (BE/BZ → 5%, else unknown) and never back-fills today's band. Applied on branch hark/harkpro with the user's OK (2026-10-10). 15/15 setup_daily tests pass. Spot check: MTARTECH now enters the Desk 10 EMA queue on 2025-09-12 and STLTECH has 147 rows (both 0 before); RELIANCE is unchanged. Run a full setup_daily rebuild after pulling.
