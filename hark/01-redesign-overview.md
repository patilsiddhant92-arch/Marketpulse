# Redesign overview

## Problem
MarketPulse has strong data (breadth, groups, RS, VCP/Darvas, deals, delivery) but the UI does not organise it around how a trader works. Readings are mostly "today only". Commentary is too technical.

## Goal
A professional end-of-day swing-trading decision system for NSE. Each evening the trader should answer, in this order:
1. **Market mood** — attack, be selective, or defend? (Pulse)
2. **Setups** — which stocks are actionable tomorrow? (Setups / Screener)
3. **Plan** — entry, stop, size, heat; hand-off to broker alerts/GTT. (Plan + Journal)
4. **Review** — what happened to past signals and trades? (Plan + Journal, History Lab)

## Competitor benchmark (2026-10-09)
| Product | What it does well that we lack |
|---|---|
| Deepvue | Fast screens, RS line, theme/group ranks, clean watchlists |
| MarketSmith India | RS Rating 1–99, Group Rank, composite ratings, pattern recognition |
| TC2000 | Scans with alerts, chart-driven workflow, broker link |
| Chartink | Free-form scan language, scan alerts, backtest counts |
| StockEdge | Delivery, deals, FII/DII, India-specific money-flow views |
| TraderSync / Edgewonk | Trade journal, tags, mistakes, outcome statistics |

### Gaps to close
- Alerts and GTT / broker hand-off.
- Real positions and a trading journal.
- Sell rules and trailing stops.
- Volatility-aware sizing (ADR%) and an "extended" flag.
- Easy-to-read RS rating and group rank.
- Techno-fundamental data (earnings growth, results dates).
- Chart replay.
- Scans as first-class objects: count history, outcome evidence, alerts.
- A decision ledger: signal → plan → order → trade → outcome.

## Tab map (working names)
| # | Tab | Purpose |
|---|---|---|
| 1 | **Pulse** | Market mood vs history, breadth, money flow, groups, movers |
| 2 | Setups | One ranked board of candidates (merges today's separate queues) |
| 3 | Plan + Journal | Order-ready plan, positions, journal, review |
| 4 | Groups | Sector / industry / index deep dive, RRG |
| 5 | Deals | Bulk/block deals with context |
| 6 | Charts / Stock 360 | One stock: chart, ratings, events, history |
| 7 | Research | Free-form research and data tools |
| 8 | **History Lab** | How today's scenario played out in the past (new) |

## Build principles
- History first. Every number shows where it sits against the past.
- One idea per panel. The top of each tab says what to do.
- No claim without data. Empty sources show as "not available", never as a guess.
- ₹1,000 Cr filter on stock lists; all stocks for market-wide statistics.
- Point-in-time correctness: a past date must show what was known on that date.
- Backend first: each panel gets a typed `/api/v2/...` endpoint before UI work.
