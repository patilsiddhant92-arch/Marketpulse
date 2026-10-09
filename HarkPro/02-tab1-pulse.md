# Tab 1 — Pulse (spec, locked 2026-10-09)

Was: Desk / Overview. Mockup: `mockups/tab1-pulse.html`.

## 1. Purpose
In under a minute, the trader knows:
- the market mood today compared with recent sessions and with all of history;
- whether participation is expanding or contracting;
- where money moved;
- which groups and stocks deserve attention;
- what risk posture to take tomorrow.

## 2. Global controls (top bar)
| Control | Values | Effect |
|---|---|---|
| As-of date | Any session in the archive (default: latest) | Replays Pulse for that date with point-in-time data |
| Lookback ("Compare today with") | 5D · 10D · 1M · 3M · 1Y | Drives every "vs N days" comparison, the grid columns, sparklines and charts |
| Units | % · # stocks | Breadth shown as percent of stocks or as a count |

Percentiles always use the full archive up to the as-of date (no look-ahead).

## 3. Hero: Mood and "What to do"
- **Mood score 0–100** = average history-percentile of six readings: % above 10 EMA, % above 50 EMA, % above 200 EMA, up-volume %, net new 52W highs, Stage 2 %.
- **Labels** (one fixed meaning each): Strong ≥ 70 · Healthy 55–69 · Mixed 45–54 · Weak 30–44 · Very weak < 30.
- **Direction qualifier**: "and cooling fast" when % above 10 EMA fell more than 10 points over the lookback; "and improving fast" when it rose more than 10 points.
- Shows: score, change vs lookback, sparkline (normal band 45–55 shaded).
- **Commentary**: 4–5 short sentences, each with a number, then a boxed **What to do** line. Rules in `04-writing-style.md`.
- Action rules (first match wins):
  1. Mood ≥ 55 and 10-EMA breadth fell > 10 pts → "The backdrop is strong, but short-term breadth is falling fast. Do not chase breakouts today. Keep your current positions. Add new ones when the 10-day number stops falling."
  2. 10-EMA breadth fell > 10 pts → "Do not add new positions today. Wait for the 10-day number to stop falling."
  3. Mood < 45 → "Take fewer new trades. Use smaller size. Buy only the strongest stocks in leading groups."
  4. Mood 45–54 → "Trade normal setups with care. Keep size normal or smaller until breadth turns up again."
  5. Mood ≥ 55 → "Conditions support new trades. Use normal size. Add only to positions that show a profit."
- One-line link to History Lab: "In N similar past setups, the average stock rose over the next 20 sessions K times."
- **Open item**: the mood score is a prototype. Before release, test it against forward 10/20-day returns in History Lab, and tune the weights.

## 4. Participation grid (breadth)
Rows: % (or #) of all stocks above 10, 20, 50, 100, 200 EMA.

Columns:
- one column per session for the last min(lookback, 10) sessions, Today last;
- for lookbacks > 10: an "N D ago" column;
- Δ over lookback;
- **vs history**: a range bar (min–max of the archive, 10th–90th percentile shaded, marker at today);
- **Pctl**: today's percentile in the archive.

Cell rules:
- **Colour** = change vs the prior session (green up, red down). Intensity scales with the size of the change relative to 2.5σ of that row's 60-day daily changes. Colour never encodes the absolute level.
- **Unusual move**: amber outline when |daily change| > 2σ of that row's own last 60 daily changes.
- **Breadth expansion / contraction flag** (added at Siddhant's request):
  - Measure: one-day relative change in the **count** of stocks above the EMA. Example: 500 → 750 = +50%.
  - Expansion when the change is ≥ the 95th percentile of that row's own history, **and** ≥ +15%, **and** ≥ 100 stocks.
  - Contraction when the change is ≤ the 5th percentile, **and** ≤ −15%, **and** ≤ −100 stocks.
  - Reason for per-row thresholds: the 10 EMA count moves much more than the 200 EMA count. A flat +25% rule fires on about 18% of days for the 10 EMA and almost never for the 200 EMA.
  - Show: cyan (expansion) or rose (contraction) underline plus a small "▲+50%" tag in the cell.
  - Commentary: when today has a flag, the first sentence calls it out: "Breadth expansion. Stocks above their 20-day average went from 500 to 750 (+50%) in one day. A move this big happened on N days in our history." When several rows fire, use the longest average.
- **Expansion log** under the grid: last 8 flagged days, one row per day, with the averages that fired, the count change, and the equal-weight market return over the next 10 and 20 sessions. Above the log: a summary for 20/50/200 EMA (number of events, median next-20D return, hit rate).
  - Local data (2024-05 → 2026-08) shows 20-EMA expansions: 28 events, median +6.2% over 20D, 22 of 28 up. Re-check on the 5-year archive.

## 5. Participation trend chart
Lines: % above 10, 50, 200 EMA over max(lookback, 20) sessions. Shaded band: the 10th–90th percentile of % above 50 EMA in the archive.

## 6. Market internals cards (6)
Each card: value, change vs lookback average, archive percentile, sparkline, one-line meaning.
| Card | Definition | Good direction |
|---|---|---|
| Advancers % | advancers / (advancers + decliners) | up |
| Up-volume % | volume in rising stocks / total volume | up |
| Net new highs | new 52W highs − new 52W lows | up |
| In Stage 2 | % of stocks that pass the trend template | up |
| Breakouts holding | % of recent 20D-high breakouts on RVOL ≥ 1.5 still above breakout close | up |
| India VIX | close | down |

Left out on purpose: McClellan oscillator, TRIN, put-call ratio. They add noise for an EOD cash-market swing desk.

## 7. Money in the market
- **Turnover chart**: total NSE cash turnover per session (all stocks) for max(lookback, 20) sessions, up to 60; delivered value overlaid; dashed 20-day average.
- Headline numbers: turnover today and % vs 20D average; delivered value and delivery share vs its 20D average.
- **Treemap**: sectors sized by today's turnover, coloured by return over 1D / 1W / 1M / 3M (toggle).
- **Rotation bars**: each sector's share of market turnover today minus its 20-day average share (points), diverging green/red, sorted. Shows where money moved in and out.
- Later: RRG scatter for groups (fields already exist in `group_daily`).

## 8. Groups table
Level toggle: **Sector · Industry · Index · Sectoral · Index · Thematic**.

Sector / Industry (all stocks, equal weight; source `group_daily`):
1D / 1W / 1M / 3M return, turnover ₹ Cr, turnover share %, Δ share vs 20D average, delivered ₹ Cr, % of members above 50 EMA, rank, rank change over 1W, RRG quadrant, deal net ₹ Cr (10 sessions), 3-month turnover-share sparkline. Sortable. Industry shows the top 40 by the sort column.

Index (added at Siddhant's request; source `index_daily` + `CANONICAL_44_INDICES` in `App/thematic_engine.py`, 16 sectoral + 28 thematic):
close, 1D / 1W / 1M / 3M return, % from 20 EMA, % from 50 EMA, trend state, 52W-high chip, 30-session sparkline. Sortable.

## 9. Stocks that moved (≥ ₹1,000 Cr only)
Tabs: Gainers · Losers · Turnover · Delivered ₹ · Volume surge (RVOL, turnover ≥ ₹5 Cr). Top 20.
Columns: stock + chips, sector, close, 1D / 1W / 1M %, turnover ₹ Cr, RVOL, delivered ₹ Cr, delivery % and ratio vs its own 20D average, RS percentile, market cap.
Subtitle states the universe: "X of Y stocks pass the ₹1,000 Cr filter".

### Event chips (same everywhere in the app)
| Chip | Rule | Source | Status |
|---|---|---|---|
| DEAL | bulk/block deal in the last 3 sessions | `deals` | ready |
| 52W | fresh 52-week high | `indicators_daily` | ready |
| IPO | listed < 365 days | `stocks_master.ipo_age_days` | ready |
| BAND | price band / surveillance remark | `band_remarks` | ready |
| EXT | (close − 10 EMA) > 3 × ADR% | `indicators_daily` | ready |
| RES | results within 10 sessions | corporate actions / board meetings | **needs ingestion** |
| NEWS | announcement today | NSE announcements | **needs ingestion** |

## 10. Days like today (teaser)
Small card: the 8 closest past sessions by % above 50 EMA, its 5-day change, and % above 10 EMA, excluding the last 25 sessions. Shows the median next 10D and 20D equal-weight return and the hit rate. Links to History Lab for the full study.

## 11. Backend
| Endpoint | Returns |
|---|---|
| `GET /api/v2/pulse/summary?as_of=&lookback=` | mood, labels, commentary sentences, action, flags |
| `GET /api/v2/pulse/breadth?as_of=&sessions=` | per-session % and counts above each EMA, daily change, σ, expansion flags, archive percentiles, min/max/p10/p90 |
| `GET /api/v2/pulse/internals?as_of=&sessions=` | the six cards' series + percentiles |
| `GET /api/v2/pulse/expansions?as_of=&limit=` | flagged days + forward returns + per-row stats |
| `GET /api/v2/pulse/flow?as_of=&sessions=` | market turnover/delivery series; sector share, Δ share, returns |
| `GET /api/v2/pulse/groups?as_of=&level=` | sector / industry / sectoral index / thematic index rows |
| `GET /api/v2/pulse/movers?as_of=&kind=&min_mcap=1000` | top 20 stocks + chips |
| `GET /api/v2/pulse/analogs?as_of=&k=8` | nearest past days + forward returns (shared with History Lab) |

Implementation notes:
- Counts = pct × stocks / 100 from `breadth_daily`. Add stored count columns if rounding matters.
- Percentiles and σ are point-in-time: compute with data up to `as_of` only.
- Equal-weight market series for forward returns: mean of daily stock returns, capped at ±20% a day (store as `market_ew_daily`).
- Market cap filter: use the market cap as of `as_of` (`security_reference_daily`), not today's.
- Commentary generator: a template engine with the fixed glossary (§3). Lint the templates with the STE linter in CI.

## 12. Acceptance checks
- Replaying any past date shows only data known on that date.
- Every number in the commentary matches a number on screen.
- Breadth counts sum correctly against `stocks`.
- Expansion flags reproduce from the stored thresholds.
- Stock lists contain no stock below ₹1,000 Cr on the as-of date.
- Pulse loads in < 1.5 s on the 5-year archive.
