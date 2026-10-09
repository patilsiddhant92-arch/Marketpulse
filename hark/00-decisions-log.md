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
