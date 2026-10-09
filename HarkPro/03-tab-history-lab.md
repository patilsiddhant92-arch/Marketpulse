# New tab — History Lab (draft, 2026-10-09)

Siddhant: "In the stock market, history often repeats itself. Is there a way to study today's scenario playing out similarly in history? This can be a separate tab."

Decision: yes, as its own tab. Pulse keeps a small "Days like today" card that links here. Detailed design comes in its own round, after the core tabs.

## Purpose
Answer three questions with the archive:
1. **When did the market last look like this?** (analog days)
2. **What usually happened next?** (forward paths, hit rates, ranges)
3. **What worked next?** (which groups led, which setups paid)

## Building blocks
### A. Analog finder
- Describe each session with a feature vector: % above 10/20/50/200 EMA and their 5-day changes, net new highs, up-volume %, turnover vs 20D average, India VIX, index trend state, Stage 2 %, breakout follow-through %, mood score.
- Standardise each feature by its history (z-score or percentile). Distance = weighted Euclidean. The user can turn features on and off.
- Pick the top K (default 10) days. Keep picks at least 10 sessions apart so one episode does not fill the list.
- Exclude the last 25 sessions (their outcome is not known yet).

### B. Outcome view
- Fan chart of the equal-weight market, Nifty 50 and Midsmallcap 400 from day 0 to day +60 for each analog. Median path in bold.
- Table: next 5 / 10 / 20 / 60 D return, max drawdown, max run-up, % up.
- Compare with the base rate (all days) so the trader sees if the analog edge is real.
- Sample-size warning when K or the spread makes the result weak.

### C. Event studies (scenario queries)
Pre-built and custom conditions, for example:
- breadth expansion days (from Pulse §4) by row;
- breadth contraction after % above 50 EMA > 60;
- % above 200 EMA crosses back above 50;
- net new highs turn positive after 20 negative sessions;
- turnover > 1.5× its 20D average with advancers > 65%;
- VIX spike > 20% in 5 days.
For each: event list, forward returns, hit rate, and the trend of the edge over time (does it still work?).

### D. What led next
For each analog or event date: the sectors / industries / indices with the best next-20D return, and how they ranked on day 0 (RS, turnover-share change, RRG quadrant). Shows whether "money moving in" on day 0 predicted leadership.

### E. Setup outcomes by regime
Use `setup_outcomes` (VCP, Darvas, breakouts) to show win rate and average R per mood band and per analog cluster. Feeds position sizing in Plan.

### F. Seasonality (later)
Month of year, results season, Budget week, Diwali/Samvat, expiry week.

## Rules
- Point-in-time only. No feature may use data after day 0.
- Use the full 5-year archive. Show the date range used on every panel.
- State the method in plain English under each panel (`04-writing-style.md`).
- History describes; it does not predict. Each panel ends with the base rate and the sample size.

## Data needed
- `market_ew_daily` (equal-weight market series), stored.
- A `session_features` table (one row per session) for the analog finder.
- Index history for the full 5 years (`Scripts/backfill_index_history.py`); local `index_daily` holds only a few weeks.

## Open questions for its design round
- Which features matter most for Siddhant's style (Darvas / VCP / Minervini)?
- Forward measure: equal-weight market, Nifty, Midsmallcap, or the trader's own setups?
- Should a saved scenario raise an alert when it fires again?
