# Tab: Deals (round 1, 2026-10-09)

## 1. What the app does today
Eight views: Today · Repeated · Play · Star funds · Leaderboard · Prop/churn · Follow-through · Houses.
- **Data**: `deals` (NSE bulk + block files) → `deal_session_net` (one row per stock-session), built by `Scripts/derived/deal_session_net.py`. The rules are shared with the live API through `Scripts/derived/deal_rules.py`.
- **Prints** are collapsed: a print that appears in both the bulk and block files counts once. PROP desks are excluded from every net.
- **Event per stock-session** (first match wins): transfer_interse · placement (matched buy/sell, buyers all FII/DII) · churn (round trips or PROP-only) · accumulate · fresh · distribute.
- **Play tiers** (`desk_tier`): conviction / fresh / distribution / transfer / churn / quarantined, set by hand-picked thresholds (≥ ₹20 Cr, ≥ 0.5× ADV, ≥ 2 houses, repeat).
- **Houses**: a "bet" is a non-PROP buy of ≥ ₹5 Cr. Catalyst score = 40% win rate (T+20 ≥ +5%) + 30% average peak run-up + 15% T+20 + 15% speed. Tiers run from "Star Catalyst" to "Laggard".
- **Follow-through**: T+5/T+20 from the next open, per event type, against an all-stocks baseline.

### Calculation audit
| Item | Verdict |
|---|---|
| Collapse, PROP exclusion, transfer matching, next-open entry | Correct. No look-ahead in the entry. |
| Excess return vs NIFTY MidSml 400 | **Blank locally**: only 32 sessions of index history. Use the equal-weight ≥ ₹1,000 Cr average instead (always available). |
| House "win" = T+20 ≥ +5% absolute | Gets inflated in a rising market. Measure against the market over the same sessions. |
| House peak run-up | Uses the best high reached within 60 sessions, which no trader can capture, and counts unfinished windows. **Today's buys also feed their own house's score** (circular). |
| Catalyst score / Star tiers | Hand-weighted and never validated. The study (section 2) shows a good past record does **not** carry forward. |
| Play tier thresholds | Not tested. In the study, size and number of houses add nothing. |
| History | Locally only 75 deal sessions (29 Apr 2026 on). Too few to judge any rule. |

## 2. Evidence study (HarkPro/tools/deals_study/study.py)
- **Data**: 65,991 NSE bulk/block prints, Apr 2024 to Oct 2026, from NSE's historical endpoint (`fetch_nse_history.py`, the CSV mode returns full data; JSON caps at 70 rows). That gives 19,080 stock-sessions through the app's own `build_deal_session_net`.
- **Method**: stocks ≥ ₹1,000 Cr. Entry at the next open; exit at the close T+5 / T+20. Excess = return minus the equal-weight average of all ≥ ₹1,000 Cr stocks over the same sessions. Deals up to 14 Jul 2026 (local price gap after 13 Aug).
- **Universe**: market cap = today's share count × price (approximation).

| Reading | n | Excess T+20 | Beat market | t |
|---|---|---|---|---|
| Baseline (all stocks, same dates) | 713k | 0.0% | 45% | |
| **Placement** (FII/DII absorb a block) | 382 | **+1.9%** | **65%** | 4.9 |
| Distribute (net selling) | 837 | +1.0% | 49% | 2.0 |
| Distribute + strong chart | 79 | +5.0% | 66% | 2.7 |
| **Net buy + strong chart** (>200 EMA, RS ≥ 70, ≤ 15% off high) | 83 | **+3.1%** | 55% | 2.0 |
| Strong chart alone (no deal condition) | 66k | +0.9% | 51% | |
| Net buy + weak chart | 173 | −1.5% | 43% | −1.5 |
| Accumulate (repeat buying) | 115 | −0.2% | 56% | ~0 |
| Fresh (single net buy) | 480 | +0.3% | 43% | ~0 |
| Net buy size 1–3× ADV | 157 | −1.3% | 40% | −1.4 |
| ≥ 2 buying houses | 59 | −0.5% | 48% | ~0 |
| Net buyer FII / DII / Corporate / Other | 93 / 78 / 177 / 281 | −1.3 / +0.9 / −1.2 / +1.2% | | all \|t\| < 1.5 |
| **Churn** (PROP / round trips) | 4,241 | **−2.0%** | **38%** | −9.3 |
| House with a good prior record (≥ 5 finished bets, avg > +3%) | 301 | −1.4% | 41% | −2.1 |
| **House with a poor prior record** (avg < 0) | 1,627 | **−3.1%** | **38%** | −9.0 |
| Group: industry with 3+ net-buy deal stocks in 10 sessions | 138 | +0.7% | 52% | 2.1 |

**Reading it**
1. On its own, a deal buy is not a buy signal. Net buying, repeat buying, size and cluster all sit near zero.
2. A deal buy **on a strong chart** adds about +2 pts over the strong chart alone. Deals confirm a setup; they don't create one.
3. **Placements** are the one clean positive: institutions taking a promoter or corporate block.
4. **Churn is a reliable warning**: PROP/HFT-dominated names lag by about 2% over 20 sessions.
5. A good house record **doesn't persist**, but a bad record does. So the "Star funds" idea is unsupported. A "poor-record buyer" flag is supported.
6. Distribution into a strong chart was followed by gains: supply being absorbed. Don't treat selling as bearish on its own.
7. Group deal count (parked item): weak, +0.7%. Show it as context only, not a score input.

Caveats: about 2 years and one market regime. Overlapping windows and same-day clusters inflate t. House names are merged crudely. Recheck on the 5-year archive before locking any number.

## 3. Proposals (for discussion)
1. **Cut eight views to three**:
   - **Today**: every deal stock with a plain-English verdict.
   - **Building**: the multi-session window that replaces Repeated, Play and Prop/churn.
   - **Houses**: the record, graded out of sample.

   Follow-through stops being its own tab: it becomes a "what usually follows" line on each event.
2. **Verdict chip per stock, from the evidence**:
   - Confirms setup (net buy on a strong chart)
   - Placement
   - Absorbed (distribution on a strong chart)
   - Noise (fresh/accumulate on a weak chart)
   - Churn warning
   - Poor-record buyer
3. **Fix the maths**:
   - Excess against the equal-weight universe.
   - House record out of sample only, using finished T+20 bets before each bet date.
   - Win means beating the market, and peak run-up is dropped.
   - Retire the catalyst score and the Play tiers.
4. **Backfill deal history** in the pipeline from the NSE CSV endpoint (about 2 years in about 3 minutes). Keep it updated daily as now.
5. **Cross-tab links**:
   - The verdict chip appears on Setups rows.
   - Industry deal count joins Sector Intel as a context column (the parked item).
   - Stock360 gets the deal timeline.
6. **Readout example**: "SBI MF and HDFC MF took 2.1 crore shares from the promoter at ₹412, 0.8% under the close. Placements like this beat the market about 2 in 3 times over the next month."

## 4. Round 1b: what can we do better (study2.py, same data and method)
Question: does price action around the deal add an edge? The confirmation tests enter at the close k sessions after the deal and measure the next 20 sessions against the market.

| Reading | n | vs market T+20 | Beat % | t |
|---|---|---|---|---|
| Net buy, enter next open (base) | 587 | +0.2% | 46% | 0.4 |
| Net buy, close T+3 **above** buy price | 328 | +1.0% | 47% | 1.4 |
| Net buy, close T+3 **below** buy price | 265 | −1.1% | 42% | −1.3 |
| **Net buy + strong chart, T+3 above buy price** | 40 | **+5.2%** | 60% | 3.0 |
| **Placement + strong chart** | 115 | **+2.6%** | **76%** | 4.4 |
| Placement at ≥ 3% discount / within 3% | 19 / 363 | +1.7 / +1.9% | 58 / 65% | |
| **Distribution, T+3 back above sell price** (absorbed) | 450 | **+1.8%** | 52% | 2.7 |
| Distribution, T+3 below sell price | 379 | −0.6% | 43% | −0.9 |
| Net buy after a prior 1M of +10..+30% | 154 | +1.8% | 49% | 1.6 |
| Net buy after > +30% (extended) / < −10% (falling) | 62 / 81 | −1.7 / −2.1% | 37 / 43% | |
| Net buy + delivery ≥ 1.5× its 20D average | 97 | +1.2% | 54% | 1.0 |
| Net buy + delivery below its 20D average | 203 | −0.6% | 43% | −0.6 |
| Deal-day candle (close location, day change) | | about 0 | | |
| Churn on a quiet day (RVOL < 3) | 1,203 | **−3.7%** | 35% | −8.9 |
| Churn on a hype day (RVOL ≥ 3) | 2,803 | −1.2% | 39% | −4.6 |

**What this adds**
1. **The deal price is a level.** Whether price holds it over the next 3 sessions separates good deals from bad ones by about 2 pts. Strong chart + holding = +5.2%. So don't act on the deal night: put it on a 3-session watch.
2. **Absorbed distribution** (price back above the sellers' price) is a positive, not a warning.
3. **Placement + strong chart** is the best single reading (76% beat the market).
4. **Context filters**: skip buys after a > 30% month or a falling knife. A delivery spike helps a little. The deal-day candle tells you nothing.
5. **Quiet-day churn** is the strongest negative (−3.7%).

**Proposal changes**
- **Building → Deal watch**: every deal of the last 10 sessions with its deal price drawn as a level. The status reads "holding / lost / reclaimed" with sessions counted, and the verdict upgrades after T+3.
- Verdict chips gain **Holding deal price**, **Absorbed** and **Extended**.
- Charts / Stock360 draw buy/sell deal prices as horizontal lines.
- Next data source to test: NSE insider (PIT/SAST) disclosures. Promoter open-market buying is a different signal from bulk/block deals.

## 5. Round 2: the user's list (2026-10-09)
The user asked for: deal candles on charts, deals by sector/group, better drill-downs, fund tracking + alerts, a shorter Telegram message, and a deal icon in the other tabs.

### 5.1 Fund evidence (study3_funds.py)
| Buyer (≥ ₹5 Cr non-PROP buy) | n | vs market T+20 | Beat % | t |
|---|---|---|---|---|
| FII | 947 | +1.2% | 53% | 4.3 |
| DII | 825 | +0.9% | 46% | 3.2 |
| Corporate | 1,373 | −2.6% | 38% | −6.7 |
| Other (trading firms, HNI) | 2,374 | −2.7% | 41% | −9.0 |
| FII with a good prior record / poor record | 264 / 208 | +1.1 / 0.0% | | |
| Good-record house buying a strong chart | 206 | **+2.1%** | 58% | 3.0 |
| Poor-record house buying a strong chart | 241 | −0.1% | 52% | |
| Any buy on a strong chart | 757 | +0.8% | 56% | |

The rank correlation between a house's prior record and its next bet is 0.09: weak but real. **Who the buyer is matters more than their record**: FII/DII positive, Corporate/Other negative. Fund alerts are justified only for FII/DII houses with a good out-of-sample record buying a strong chart.

### 5.2 Telegram (Scripts/telegram_deals.py) audit
- 08-Oct-2026 output: **6 messages, about 7,200 characters**.
- Inter-se transfers are listed as BUYs and SELLs (PI Opportunities AIF / Pioneer: ICICIBANK, RELIANCE, KAJARIACER, INDGN).
- "Conviction" includes net-negative names (GCSL −₹4.4 Cr, AGARWALEYE −₹1,181 Cr).
- It uses the old tiers; nothing in it is ranked by evidence.

New format: **one message, at most about 1,200 characters, only what's actionable, each line one verdict**:
```
📊 Deals · 08 Oct · Market: correction (stay light)
✅ Confirms setup (strong chart + FII/DII buy)
  XYZ  ₹42 Cr · SBI MF · hold ₹412 to confirm
🏦 Placement on a strong chart
  ABC  ₹180 Cr promoter → 3 MFs @ ₹1,020 (-0.8%)
🔁 Absorbed (sellers' price reclaimed)
  DEF  sold @ ₹640, now ₹655
👀 Watch day 3: holding / lost
  GHI holding +2.1% · JKL lost -1.4%
⚠️ Avoid: churn / poor-record buyer
  MNO, PQR
Skipped: 4 transfers, 37 churn, 12 below ₹1,000 Cr
TV: NSE:XYZ,NSE:ABC,NSE:DEF,NSE:GHI
```
Empty sections are dropped. The breadth block moves to the Pulse message (one line here). There's an optional /deals detail command for the full list.

### 5.3 Proposed designs
1. **Deal candles (Charts, Stock360, chart grid)**:
   - The candle keeps its colour; the deal day gets a tinted outline plus a 1-letter tag above or below.
   - Tags: **B** net buy (teal) · **S** net sell (orange) · **P** placement (blue) · **T** transfer (grey) · **C** churn (grey, faded).
   - Hover shows "B ₹42 Cr · SBI MF (DII, good record) · @ ₹412".
   - A dashed deal-price line runs for 20 sessions, labelled holding / lost.
2. **Deals by group**:
   - The Sector Intel board gets a "Deals 10D" column: net-buy names / net-sell names / flow ₹ Cr (ex transfers and churn).
   - A chip shows at 3+ net-buy names. It's context only (evidence +0.7%, weak).
   - The group drill lists its deal stocks with their verdicts.
   - The Deals tab gets a "By group" switch.
3. **Drill-downs**:
   - **Stock drawer**: verdict + "what usually follows"; a 20-session mini chart with deal lines; who bought and who sold (the counterparty explains transfers); each buyer's class + record grade; holding status since the deal.
   - **House drawer**: class, out-of-sample grade, open positions vs market since entry, recent buys, and a Follow button.
4. **Fund tracking**:
   - A Followed houses list.
   - The grade shows only for FII/DII (good / mixed / poor, from finished past bets only).
   - **Alert 1**: a followed or good-record FII/DII house buys a strong chart.
   - **Alert 2**: day 3, holding or lost.
   - No "star" label for Corporate/Other.
5. **Deal icon in other tabs** (reuses `stockContext`):
   - One small icon on any stock row in Pulse movers, Setups, Sector Intel drill, Charts, Stock360 and the Plan/Journal.
   - Colour = verdict: green confirm · blue placement · teal absorbed · amber watch · grey churn · red avoid.
   - Tap = a 2-line popover plus a link to Deals.
   - Rule: the icon shows only within 10 sessions of the deal.

### 5.4 Mockup v1
`HarkPro/mockups/tab-deals.html` is built by `HarkPro/tools/deals_mockup/extract.py` from local data as of 2026-08-13, the last session before the price gap, so day-3 states can be shown. It has six views:
- **Today**: every deal stock, sorted by verdict; noise is hidden behind a toggle.
- **Deal watch**: holding / lost / reclaimed, with filters.
- **Houses**: class evidence, out-of-sample grades, Follow.
- **By group**
- **Telegram**: one message, about 1,000 characters.
- **In other tabs**: a demo of the deal icon popover, plus candles with B/S/P/C/T tags and dashed deal-price lines.

The stock drawer shows the verdict, the deal-candle chart, buyers and sellers with their grades, and the next action. The jsdom test is /workspace/work/pulse/t5.js.

### 5.5 Mockup v1.1 (user feedback)
- **Deal-day candle colour**: the deal-day candle is filled in the deal's own colour (teal buy, blue placement, orange sell, grey churn/transfer) with a letter on top. It replaces the green/red that day. Charts show deal-price lines for the 3 latest deals only.
- **History view** (new tab): every stock ≥ ₹1,000 Cr with a deal in the last **5 / 10 / 20 deal sessions**, including churn, prop desks and transfers.
  - Each stock gets one square per session, oldest first.
  - Patterns: Repeated buying (2+ buy sessions, no selling), Single buy, Selling only, Buying and selling, Prop desk/churn only, Transfers only.
  - Each row: buy/sell session counts, net ₹ Cr, prop ₹ Cr, avg deal price and now vs deal.
  - Each pattern carries its evidence note.
  - As of 13 Aug, 10 sessions: 3 repeated buying, 16 single buy, 16 selling only, 2 mixed, 55 churn-only, 7 transfers.
- **Rule gap found**: APOLLOPIPE 2026-08-13 is labelled accumulate, but Anil Laxmichand Shah bought ₹12.6 Cr while Kiran Anil Shah sold ₹12.6 Cr. That's a family transfer the transfer rule missed (likely a price mismatch beyond ±0.25%). Its "repeated buying" streak needs re-checking once deal_rules is fixed.

### 5.6 Mockup v1.2 (user feedback)
- **One colour** for the whole deal-day candle is confirmed.
- **Copy to TradingView** on every list in the Deals tab (Today, Watch, History, Houses, By group). It copies the rows on screen with current filters as `###<list title>,NSE:SYM,...`. Symbols are mapped TradingView-style: `-` and `&` become `_`, e.g. NSE:BAJAJ_AUTO.
  - A tab with 2+ lists also gets "Copy every list (sections)", one `###` section per list.
  - Paste into Add symbol, or save as .txt for watchlist Import list.
- **Fund diversification into groups** (Houses view):
  - (a) "Where FII/DII money went · by group": non-prop FII/DII buys over 10 deal sessions by industry, with house count, FII ₹ and DII ₹. As of 13 Aug, E-Retail had 26 houses, Fintech 13, Healthcare services 13.
  - (b) Each house row gets a "Spread across groups" cell: group count + top-3 industry shares. The phone card shows a stacked bar per fund.
  - Context only: no forward-return test yet on "many houses in one group".
