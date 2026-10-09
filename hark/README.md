# hark/ — MarketPulse redesign workbook

This folder holds the design discussions between Siddhant and Hark for the MarketPulse redesign.
We design one tab at a time. We lock each tab's spec before we write production code.

| File | What it holds | Status |
|---|---|---|
| [00-decisions-log.md](00-decisions-log.md) | Every decision, by date, with the reason | Running |
| [01-redesign-overview.md](01-redesign-overview.md) | Goals, competitor benchmark, gaps, tab map, build principles | Agreed |
| [02-tab1-pulse.md](02-tab1-pulse.md) | Tab 1 **Pulse** (was Desk / Overview): full spec | **Locked 2026-10-09** |
| [03-tab-history-lab.md](03-tab-history-lab.md) | New tab **History Lab**: study how today's setup played out in the past | Draft, to schedule |
| [04-writing-style.md](04-writing-style.md) | House style for all commentary (plain English, STE-inspired) | Agreed |
| [05-data-gaps.md](05-data-gaps.md) | Data that the specs need but the pipeline lacks or gets wrong | Open |
| [06-tab2-setups.md](06-tab2-setups.md) | Tab 2 **Setups / Screener**: discussion rounds + locked spec | **Locked 2026-10-09** |
| [07-tab-sector-intel.md](07-tab-sector-intel.md) | Sector Intel (Groups): audit, evidence, rounds 1–3, mockup, stock heatmap | Mockup v1, ready to lock |
| [08-tab-deals.md](08-tab-deals.md) | Deals: audit, 2.5-year evidence study, rounds 1–2, mockup v1.2 | Mockup v1.2, ready to lock |
| mockups/tab-sector-intel.html | Sector Intel mockup (board, chart grid, group panel) | v1 |
| mockups/stock-heatmap.html | TradingView-style stock heatmap (home: Sector Intel or Pulse, undecided) | v1 |
| mockups/tab-deals.html | Deals mockup: Today, Watch, History, Houses, By group, Telegram, In other tabs | v1.2 |
| mockups/screenshots/deals/ | Phone-size sample screenshots of the Deals mockup | Samples |
| tools/deals_mockup/ | `extract.py` rebuilds the Deals mockup; `screenshots.py` draws the phone PNGs (Pillow) | Prototype |
| tools/deals_study/ | Deals evidence studies (study.py, study2.py, study3_funds.py) + NSE history fetch | Research |
| mockups/tab1-pulse.html | Clickable Pulse mockup on real data (open in a desktop browser) | v2 |
| mockups/redesign-v1-workflow.html | First workflow-first mockup (Brief / Setups / Plan / Review) | Reference |
| tools/pulse_mockup/ | Script that rebuilds the Pulse mockup from `Database/marketpulse.duckdb` | Prototype |

## Tab order for the design rounds
1. Pulse — **done**
2. Setups / Screener — **done**
3. Sector Intel (Groups) — **mockup done**, lock pending
4. Deals — **mockup done**, lock pending
5. Plan + Journal
6. Charts / Stock 360
7. Research
8. History Lab (new, from the Pulse round)

## Standing rules (apply to every tab)
- Stock lists show only stocks with market cap ≥ ₹1,000 Cr.
- Breadth, rotation and money-flow calculations use **all** stocks.
- Every reading is shown relative to history (today vs the past N sessions, and its percentile in the full archive). A today-only number is not enough.
- Commentary follows [04-writing-style.md](04-writing-style.md).
- Event chips appear only when data backs them.
- Tab names can change as the redesign goes on.

## Rebuild the Pulse mockup
```
python hark/tools/pulse_mockup/extract.py 2026-08-13
```
Pass the as-of date. On a machine with the full 5-year archive, use the latest session.

- `mockups/tab2-setups.html`: Tab 2 Setups mockup (local data to 2026-08-13). Rebuild: `python hark/tools/setups_mockup/extract.py [AS_OF]` from the repo root.
- `research/manas-arora-vcp.md`: Manas Arora VCP research with sources.
