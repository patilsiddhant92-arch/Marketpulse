# Decisions log

Newest at the bottom. Each line: date · decision · reason.

## 2026-10-08 — Redesign kick-off
- Redesign MarketPulse around a swing trader's evening routine: market mood → setups → plan → review. Reason: the app has a lot of data but no clear order of work.
- First mockup: Brief / Setups / Plan / Review modes plus an Intel rail (Groups, Deals, Research, Charts). Reference only now (`mockups/redesign-v1-workflow.html`).

## 2026-10-09 — Benchmark and process
- Benchmarked Deepvue, MarketSmith India, TC2000, Chartink, StockEdge, TraderSync and Edgewonk. Gaps are listed in `01-redesign-overview.md`.
- Process: one tab at a time, discuss, lock the spec, then build. Tab names can change.
- Tab order: Pulse → Setups/Screener → Plan+Journal → Groups → Deals → Charts/Stock 360 → Research.

## 2026-10-09 — Tab 1 rules from Siddhant
- Stock lists: market cap ≥ ₹1,000 Cr only. Breadth, rotation, money flow: all stocks.
- Commentary in plain English with a reason and a number behind each claim.
- Use the historical database to the full. Show useful infographics.
- Global event chips on stocks: deals, news/announcements, results, IPO, band/surveillance.
- Commentary style: Siddhant pointed to ASD-STE100 (aircraft manual standard) and the `danyuchn/asd-ste100-skill` repo. Decision: adopt the STE principles in "STE-flavoured" mode (short sentences, active voice, one idea per sentence, one meaning per word). Do not claim formal STE compliance. Reason: the official FAQ says STE is not meant as a general writing language, and its dictionary cannot be redistributed.

## 2026-10-09 — Tab 1 round 2
- Siddhant: "Overview should not be just today's data. It is how today looks with respect to the past N days." Decision: every Pulse reading shows a lookback comparison (5D / 10D / 1M / 3M / 1Y) and a percentile against the full archive.
- Rename Desk / Overview → **Pulse**.
- Mockup v2 built on real data (`mockups/tab1-pulse.html`).

## 2026-10-09 — Tab 1 closed (spec locked)
- Siddhant approved the overall Pulse design.
- Added: **breadth expansion / contraction flag**. Example: stocks above 20 EMA go from 500 to 750 in a day (+50%). Pulse must flag and call out this kind of move. Spec in `02-tab1-pulse.md` §4.
- Added: **index view in Groups**: official NSE sectoral (16) and thematic (28) indices, beside sectors and industries. Spec in §8.
- Added: **History Lab** as a separate tab: study how today's scenario played out in the past. Pulse keeps a small "Days like today" card that links to it. Spec draft in `03-tab-history-lab.md`.
- Mood stays one score with a direction qualifier (for example "Strong, and cooling fast"). Reason: Siddhant accepted the mockup as it was. We can split it into Backdrop and Momentum later if the single score confuses.
- As-of date picker (replay any past session) is in the spec. Reason: it follows from "use history to the full". Can be dropped from v1 if it slows the build.
- Next round: Tab 2, Setups / Screener.

## 2026-10-09 — Tab 2 opened
- Siddhant listed his four screeners (Darvas Squeeze, Darvas 10 EMA, VCP per Manas Arora, Momentum) and the chart/TV features to keep. Audit and questions in `06-tab2-setups.md`.
- Finding: the current Squeeze logic is much stricter than his definition (120 listed vs 342 with close in zone on 2026-08-13).
- Round 2: keep current calculations (RS vs MidSml400, momentum). Keep strict Squeeze (77.8% vs 60.1% box breakouts within 20D). 10 EMA: whole bar above first, undercut-and-close-near second. VCP research saved in research/manas-arora-vcp.md. Cross-tab wiring deferred.
- Round 3: momentum keeps the 20D avg volume gate and the SMA/EMA template toggle. Decision table proposed with delivery streak and turnover 1D/1W/1M multiples (stock and group).
- Round 4: 10% band OK, 5% band out, no F&O chip; results-within-N highlights the row; "Act faster" dropped.

## 2026-10-09 — Tab 2 Setups LOCKED
- Spec at the end of `06-tab2-setups.md`; mockup `mockups/tab2-setups.html` (457 setups as of 2026-08-13, validated in jsdom with no JS errors).
- Every setup row carries its Industry group state (Favour / Neutral / Caution) with a numeric reason. Prototype: squeezes in Favour groups were up after 20 sessions 47% of the time vs 41% in Caution.
- Next tab: Plan + Journal.

## 2026-10-09 — Sector Intel opened (moved ahead of Plan + Journal)
- Siddhant asked for Sector Intel next. Round 1 audit, evidence and proposals are in `07-tab-sector-intel.md`.
- Evidence (local 18 months): % trend template and % new highs predict the next 21 sessions best; turnover-share Δ (money flow) shows no edge; Broad Industry gives about twice the signal of Industry; group Health adds little for stocks with RS ≥ 80.
- Proposed: one group state across tabs, Broad Industry by default, a "Broadening now" list, flow demoted, Map/Today/Accumulators out of this tab. Waiting on Siddhant.

## 2026-10-09 — Sector Intel rounds 2–3
- TT% dropped (hard to read). Readings tested over N days. Near-52W-high %, new highs over 5–10D, A/D over 10–20D and up-day delivery share make up the score. Turnover means attention, not direction. Delivery % vs its own average showed no edge.
- No setup references in this tab for now (Siddhant).
- Pulse mood + a "Is group ranking working now?" gauge shown beside the score. Cooling-fast breadth halves the edge, and the ranking's recent record predicts its next month.
- Mockup v1 `mockups/tab-sector-intel.html`. All thresholds stay provisional until the 5-year point-in-time recheck.

## 2026-10-09 — Deals round 1
- Audit + 2-year evidence study in 08-tab-deals.md. A deal buy on its own isn't a signal. It confirms a strong chart (+3.1% vs +0.9% for the strong chart alone). Placements are positive (+1.9%, 65%). Churn and poor-record houses are reliable warnings. A good house record does not persist.
- Proposed: 3 views (Today / Building / Houses), evidence-based verdict chips, out-of-sample house grades, equal-weight benchmark, NSE CSV backfill. Waiting on feedback.
- Round 1b (study2.py): the deal price acts as a level. Holding it for 3 sessions on a strong chart = +5.2%; absorbed distribution +1.8%; placement + strong chart +2.6% (76%); quiet-day churn −3.7%. Building view becomes Deal watch (holding / lost / reclaimed).
