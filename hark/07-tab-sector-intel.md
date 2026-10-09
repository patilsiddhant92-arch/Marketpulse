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
