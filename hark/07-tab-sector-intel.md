# Tab — Sector Intel (now "Groups")

Status: **Round 1: audit + evidence + proposals** (2026-10-09). Nothing locked yet.
Siddhant moved this tab ahead of Plan + Journal.

## 1. What exists today (code audit)

Route `frontend/src/routes/GroupsRoute.tsx` (+ `routes/groups/*`, `today/TodayGroups.tsx`), API `App/services/groups.py`,
nightly table `group_daily` (built by `Scripts/derived/group_daily.py`).

| Part | What it shows |
|---|---|
| Glance band | Market line vs Desk verdict, Health split, quadrant counts, top 3 by Health |
| Controls | Level (Broad Sector 12 · Sector 22 · Broad Industry 58 · Industry 171), floor (1000 Cr / all / watch), 5 views, name filter, quadrant chips, "Strong" preset, show thin |
| **Board** view | ~36 columns (about 22 visible by default): Health + 21d spark, RRG quadrant + note, trend arrow, 21d return, 1Y index spark, >50E, Rank MS + Δ5/Δ20/Δ63, rank spark, excess 21/63, RS line, RS-R, RS-M, >200E, TT %, turnover share 5d, flow Δ, flow days, delivery acc, deals 10s, Top-1, leaders… |
| Side rail | RRG (6-week tails, top 8 per quadrant) + Money-flow inflow/outflow lists with TradingView copy |
| **Map** view | Taxonomy treemap sized by turnover, coloured by Health or 21d return |
| **Today** view | 1D movers by group with contributors, participation, catalysts |
| **Rotation** view | Groups × 12 weeks coloured by weekly Health |
| **Accumulators** view | Stocks with a turnover surge on an up day |
| Drill | Breadcrumb, sub-groups, group EW index (50/200 EMA), members in Desk queues, movers, 120-session sparks, member table (RS, excess, TT, delivery, deals, setups) |

**Health** = 0.40 × peer RRG + 0.35 × the group's own trend + 0.25 × breadth. Zones: ≥ 65 Healthy, 45–65 Mixed, < 45 Weak.
**RRG** = z-scores across groups at the same level, so about half of all groups sit right of 100 by construction.

## 2. Problems found

1. **Three vocabularies for one question.** Health zones (Healthy / Mixed / Weak), RRG quadrants (Leading / Improving / Weakening / Lagging) and the Tab 2 group state (Favour / Neutral / Caution) all answer "is this group good?". They can disagree on the same row.
2. **The default grain is too thin.** At Industry level with the 1000 Cr floor, on 2026-08-13: 171 groups, 51 have < 3 members, 48 have 3–5, and 59 have one stock with ≥ 50% of the turnover. About two thirds of the "groups" are one or two stocks.
3. **Too many views and columns.** 5 views and ~36 columns. Map and Today repeat what Pulse already shows (treemap, rotation bars, groups table, movers). Accumulators is a stock list, not a group view.
4. **Sort order is not backed by evidence** (section 3). The default sort is Health. Money flow gets a whole side panel.
5. **Readings are today-only.** No percentile of a group's reading against its own history (standing rule).
6. **No index view here.** Sectoral / thematic indices live only in Pulse.
7. **Fresh-clone board is empty.** `index_daily` holds 32 sessions of NIFTY MIDSML 400 locally, so `health`, `rrg_quadrant` and `rank` are null in every `group_daily` row. The default sort column is blank. (On the full archive this works.)
8. **Point-in-time.** Today's taxonomy and today's market cap are applied to past dates (survivorship and look-ahead in every history spark and rank change).

## 3. Evidence: which group readings predict the next 21 sessions?

Script: `hark/tools/sector_study/study.py <Level>`. Local data from 2024-10-01 to 2026-07 (440 signal days; windows that cross the 13 Aug–8 Oct gap are excluded).
Groups with ≥ 3 members, 1000 Cr floor. Target = the group's forward 21-session equal-weight return minus the median group's.
IC = average daily rank correlation. Health and RRG were recomputed against an equal-weight market proxy, because MidSml400 history is missing locally.

| Reading | IC Industry | IC Broad Industry | IC Sector |
|---|---|---|---|
| % members passing trend template | **0.093** | **0.116** | **0.169** |
| % members at 52-week high | 0.058 | 0.092 | 0.135 |
| 21D return | 0.039 | 0.094 | 0.099 |
| Health (composite) | 0.041 | 0.078 | 0.068 |
| Delivery accumulation 10d | 0.033 | 0.077 | 0.060 |
| RS-Momentum (RRG y) | 0.027 | 0.080 | 0.100 |
| % above 50 EMA | 0.037 | 0.047 | 0.058 |
| Rank MS (mean 21/63 excess) | 0.026 | 0.047 | 0.031 |
| 63D return | 0.009 | 0.008 | −0.009 |
| **Turnover-share Δ (money flow)** | **0.003** | 0.024 | 0.027 |

What this says:
- **Quality of leadership predicts best**: how many members pass the trend template and how many make new highs.
- **Money flow (turnover-share Δ) predicts nothing** on its own, in every half-year tested. Flow up + price down did no better than flow down + price down.
- **Broad Industry roughly doubles the signal of Industry** (Health top-minus-bottom quintile 1.2 pts vs 0.8 pts).
- **Health is unstable**: its IC was 0.13 in 2024 H2, −0.06 in 2025 H1, +0.07 in 2025 H2. Its 21-session persistence is 0.39, so leadership rotates in about a month.
- **RRG**: Leading +0.33 median, Lagging −0.24 (Broad Industry). Improving and Weakening are close to zero.
- **For leader stocks the group adds little.** Stocks with RS ≥ 80 beat the median stock over 21 sessions 52% of the time in the weakest Health quintile and 54% in the strongest. For all stocks it is 50% vs 52%. Groups help find where new leaders appear; they are not a veto on a stock that already leads.

Limits: about 18 months, one market cycle, current taxonomy and market cap (point-in-time gap). Recheck on the five-year archive before locking any threshold.

## 4. Proposal

**Purpose:** answer two questions each evening.
1. *Where is leadership broadening?* (where the next setups will come from)
2. *Is this group's move broad, or one stock?*

Pulse keeps the today glance (treemap, rotation bars, groups table). Sector Intel is the deep dive.

### 4.1 One group state across tabs
Use the Tab 2 state (**Favour / Neutral / Caution**) as the only label on every tab, with its numeric reason.
Health stays as a number with its three parts shown. RRG stays as a chart, not as a row label.

### 4.2 Default grain: Broad Industry (58)
Industry becomes the drill level. Groups with < 5 members fold into their Broad Industry on the board. The one-stock flag stays.

### 4.3 Leadership board (one view, about 12 default columns)
State + reason · members · **% trend template** (and 10-session change) · **new highs this week** · 21D return vs median group · RS-Momentum · % above 50 EMA · delivery accumulation · Health · rank change 1W / 1M · each reading's percentile vs the group's own 2 years · top 3 leaders (TradingView copy).
Turnover share and deals move to an optional "Flow" column group with a note: no forward edge measured.

### 4.4 "Broadening now" list
Groups where TT % rose over 10 sessions, new highs increased, and the group came from the bottom half. Base rate shown beside it. This replaces the money-flow side panel. Thresholds to backtest.

### 4.5 Group page (drill)
Plain-English summary ("12 of 18 members are above the 50 EMA. Four made new highs this week. The move is broad.") · EW index chart with 50/200 EMA and the MidSml400 RS line · breadth, TT % and new-high history with percentile bands · members ranked by RS with Tab 2 setup tags · leaders vs laggards · sub-groups · deals and results dates (when data exists).

### 4.6 Indices view
16 sectoral + 28 thematic indices (from Pulse), with 1W/1M/3M, RS vs MidSml400, % of constituents above 50 EMA, and their percentile.

### 4.7 Rotation history
Keep the 12-week grid, coloured by the shared state. Add "weeks in state".

### 4.8 Drop or move
Map and Today → already in Pulse. Accumulators → Setups or Deals. Board side panel money flow → Flow column group.

### 4.9 Data work first
1. Backfill `index_daily` (5 years of MidSml400 + sectoral indices): otherwise Health, RRG and Rank are null.
2. Point-in-time taxonomy and market cap for history.
3. Store group TT %, new highs and state per session in `group_daily` (most exist), plus their 2-year percentiles.
4. Rerun section 3 on the full archive; lock thresholds only after that.

## 5. Questions for Siddhant (round 1)
1. Default grain Broad Industry (58), with Industry as drill?
2. Demote money flow to an optional column group, and drop Map / Today / Accumulators from this tab?

## 6. Proposed board columns (answer to "what data will I see")
Prototype rows: `python hark/tools/sector_study/sample_board.py` (Broad Industry, 1000 Cr floor, groups ≥ 5 members, as of 2026-08-13).

| Column | Meaning |
|---|---|
| State | Favour / Neutral / Caution, shared with Pulse and Setups, with the numeric reason on hover |
| Members | Stocks ≥ ₹1,000 Cr in the group |
| TT % | % of members passing the trend template (default sort) |
| TT Δ10 | Change in TT % over 10 sessions, points |
| TT pctile | Today's TT % vs the group's own 2-year history |
| New highs 1W | Members that made a 52-week high in the last 5 sessions |
| 21D vs median | Group 21D equal-weight return minus the median group's, points |
| RS-Mom | RRG momentum vs peers (100 = average) |
| > 50 EMA | % of members above their 50 EMA |
| Delivery acc | Delivery-weighted accumulation over 10 sessions |
| Health | 0–100 composite, parts shown on hover |
| Rank Δ 1W / 1M | Places climbed by Health rank |
| Leaders | Top 3 by RS percentile, click for Stock 360, copy to TradingView |
| Flow (optional group) | Turnover share 5D, Δ vs 20D, deals net 10 sessions |

## 7. Round 2 — Siddhant: "TT% in simple English? Why not turnover, delivery, A/D, near 52W high, for N days? Sector, industry, index too. Chart grid of industries."

**TT % in simple English:** the share of a group's stocks that are in a clean uptrend (price above the 50, 150 and 200-day averages, those averages stacked and rising, and price near its 52-week high and well off its low). It is close to "near 52W high" but harder to read. Proposal: replace it with **% near 52W high**.

### Test of the readings Siddhant named (`hark/tools/sector_study/study2_readings.py`)
Same set-up as section 3 (stocks ≥ ₹1,000 Cr, groups ≥ 3, forward 21 sessions vs the median group, Oct 2024 – Jul 2026). "Top / bottom" = % of days the top / bottom fifth of groups beat the median group.

| Reading | Best N | IC Sector | IC Broad Ind | IC Industry | Top vs bottom (Broad Ind) |
|---|---|---|---|---|---|
| % of members within 10% of 52W high | level | **0.160** | **0.103** | **0.094** | 55% vs 45% |
| Members making a new 52W high | 5–10d | 0.147 | 0.103 | 0.069 | 57% vs 46% |
| Advance / decline (net % of members up) | 10–20d | 0.114 | 0.081 | 0.048 | 54% vs 44% |
| Change in % near 52W high | 20d | 0.101 | 0.087 | 0.049 | 55% vs 45% |
| Return | 20d | 0.098 | 0.098 | 0.035 | 56% vs 45% |
| Up-day share of delivery value | 10d | 0.078 | 0.077 | 0.036 | 54% vs 44% |
| Turnover vs own 3M average | 1d | 0.047 | 0.049 | 0.017 | 52% vs 46% |
| Turnover share vs own 3M average | 1d | 0.049 | 0.051 | 0.018 | 52% vs 46% |
| Delivery value vs own 3M average | 5d | 0.043 | 0.053 | 0.004 | 52% vs 46% |
| Delivery % vs own 20D average | any | ≈ 0 | ≈ 0 | ≈ 0.02 | ≈ 49% vs 49% |
| Trend template % (for reference) | level | 0.167 | 0.119 | 0.097 | 52% vs 46% |

Findings:
- **% near 52W high is the best single reading** and the easiest to read. It stayed positive in 2025 H1, when Health turned negative.
- **N matters.** A/D 1D is weak (0.03); A/D 10–20D is two to three times stronger. One-day readings are noise.
- **Turnover alone does not say which way the money goes.** It tells you attention, not direction. Split by up days (up-day share of delivery) it becomes useful.
- **Delivery % vs its own average has no edge** at group level.
- **A 4-part score** (near-high %, new highs 10D, A/D 10D, up-day delivery share 10D, equal rank weights) beats any single reading: Sector IC 0.174 (62% vs 40%), Broad Industry 0.124 (59% vs 43%), Industry 0.080. It dipped below zero in Jul–Aug 2026, so it is a guide, not a rule.
- Index level could not be tested: `index_daily` holds 32 sessions locally. Same readings, computed from index constituents, once history and constituents are loaded.

### Revised board (all levels: Sector · Broad Industry · Industry · Index)
Columns, in this order, each with N = 1D / 1W / 2W / 1M selectable and a percentile vs the group's own 2 years:
1. Group · state · members
2. **Near 52W high %** (+ change over N)
3. **New 52W highs** (count over N)
4. **A/D** (net % up over N)
5. **Up-day delivery share** (over N)
6. **Turnover ×** vs own 3M average (attention), and turnover share Δ
7. Return over N vs median group
8. Leadership score (the 4-part rank, default sort)
9. Leaders (top 3 by RS)

### Chart grid of groups
9 cards per page, the same grid as Setups (Lightweight Charts, synced crosshair). Each card: the group's equal-weight index (candles from member OHLC, rebased) with 10/20/50 EMA, RS line vs MidSml400, and a lower pane with % near 52W high. Index level uses real index OHLC. Order follows the board sort. Click a card to open the group page.

## 8. Round 3: Siddhant said "no setups reference in this tab (for now); yes to mood beside the score and the 5-year recheck"

### Decisions
- No setup counts or links to Tab 2 in this tab for now.
- Show the Pulse mood and a **"Is group ranking working now?"** gauge beside the score.
- Every threshold stays provisional until we recheck it on the five-year archive with point-in-time data.

### Evidence: does the market state change how well the group score works?
4-part score (2W window), Oct 2024 – Jul 2026. Top / bottom = % of days the top / bottom fifth of groups beat the median group over the next 21 sessions.

| Condition | Sector IC | Broad Ind IC | Broad Ind top vs bottom | Industry IC |
|---|---|---|---|---|
| Mood < 45 | 0.152 | 0.106 | 58% vs 44% | 0.089 |
| Mood 45–55 | 0.212 | 0.153 | 61% vs 42% | 0.105 |
| Mood ≥ 55 | 0.179 | 0.128 | 58% vs 44% | 0.050 |
| 10 EMA breadth **cooling fast** (−10 pts in 10 days) | 0.133 | **0.061** | 55% vs 46% | 0.049 |
| Steady | 0.221 | 0.156 | 59% vs 43% | 0.102 |
| Improving fast | 0.187 | 0.170 | 63% vs 41% | 0.099 |

- The **mood level** barely matters. The **direction** does: when short-term breadth is falling fast, the ranking works about half as well. (Correction to round 2: the H1 2025 failure was the cooling-fast phases, not weak mood as such.)
- **The ranking's own recent record predicts its next month.** If its realised correlation over the 63 sessions that ended 21 sessions ago was > 0.05, the next correlation averaged 0.164 at Broad Industry. Otherwise it averaged 0.042. This becomes the "Working / Not working" gauge. It uses only data known on the day.

### Mockup v1: `mockups/tab-sector-intel.html`
Rebuild: `python hark/tools/sector_mockup/extract.py [AS_OF]`. Built for 2026-08-13: 22 sectors, 58 broad industries, 171 industries, 44 indices (price only). Tested in jsdom with no JS errors.
- Context strip: Pulse mood with direction, the "working now" gauge (on 13 Aug: Working, top fifth 58% vs bottom 42%), and a plain-English verdict.
- Board: level (Sector / Broad Industry / Industry / Index), window (1D / 1W / 2W / 1M), state filter, sortable. Columns: score, near-52W-high % (+ change, own percentile), new highs (distinct members), A/D, up-day delivery share, turnover ×, share Δ, return vs median, leaders (TradingView links). Copy-leaders button.
- Chart grid: 9 per page in board order. Each card has equal-weight candles, 10 / 20 / 50 EMA, an RS line and a near-high pane. The crosshair is synced.
- Group panel: large chart, plain-English read-out, members by RS.
- Index level: price returns only. Breadth needs constituent lists (data gap).
- Note: the study's "new highs" counted new-high days. The mockup counts distinct members. Both will be rechecked on the archive.

### 5-year recheck (to run on Siddhant's machine)
`python hark/tools/sector_study/study2_readings.py` and `mood_series.py` on the full database. Before the run, add point-in-time market cap (`security_reference_daily`) and taxonomy history. Lock the thresholds only after this run.

### Round 3b: Siddhant's feedback on mockup v1
- **"Everything green makes no sense."** v1 coloured any positive number green. After a broad rally that turns most of the board green, and the colour said nothing. Now colour means rank against the other groups on the same day: green = top 20%, red = bottom 20%, plain = middle. The state dot keeps its own meaning (Favour / Neutral / Caution).
- **Turnover was missing as a value.** Added **Turnover ₹Cr/day** (window average) and **Share %** of all-stock turnover, next to Turnover × and Share Δ.
- **Parked for later (Siddhant): deal count per group** (bulk/block deals in the window, maybe net buy/sell value). Revisit in the Deals round.

### Round 3c: Are the current app's group calculations correct? (audit, 2026-10-09)
Independent recompute for 2026-08-13, Broad Industry, compared with `group_daily`:
- Exact match: members (1000cr floor), % above 50 EMA, 1D EW return, turnover ₹Cr, turnover share, 5D/20D share averages; 10D delivery accumulation within 0.03 pts.
- 21D EW return: matches except Ferrous Metals (2.7 pts). The app drops a stock whose window contains a split-like jump. The app is the more correct one.
- Formulas reviewed in `Scripts/derived/group_daily.py` + `_common.py`: no bugs found. New 52W highs use the prior session's official high (no look-ahead).
- **Health, RRG and Rank are blank locally**: they need MidSml400 history, and only 32 sessions exist. The formulas look right, but no one has tested them against forward returns, and they overlap each other.
- **Point-in-time limits**: taxonomy is today's. Market cap is as-of only from 2026-07-02 (security_reference_daily); before that it is today's share count × price (documented approximation, ~94% of rows).
- **Windows count rows, not sessions**: across the 13 Aug – 8 Oct local gap, the 8 Oct "1D" and 5D/20D values span two months. The cause is the data gap. A guard (NULL when the window spans more than N calendar days) is worth adding.
- Minor: `avg_delivery_pct_20d` includes today, so "delivery above its 20D average" compares a day with an average that contains it.
