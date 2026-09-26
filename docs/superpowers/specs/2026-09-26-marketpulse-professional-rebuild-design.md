# MarketPulse Professional Rebuild — Design

| Field | Value |
| :--- | :--- |
| **Date** | 2026-09-26 |
| **Status** | Draft for user review |
| **Author** | Claude (Opus 5.5) with Siddhant |
| **Scope** | Data truth + evidence engine + API v2 + complete React UI rebuild |
| **Supersedes** | The UI and data-scope parts of `2026-09-21-marketpulse-usefulness-upgrade-design.md` where they conflict (notably K8 and the tab structure). All other K-decisions stand unless listed in §2. |
| **Live DB at time of audit** | `prices_daily` 2024-05-06 → 2026-09-25, 594 sessions, 2,390 symbols |

---

## 1. Why this rebuild

A six-agent, read-only audit (2026-09-25/26) traced every field in every React tab from UI → API → SQL → table and re-computed values against the live DB. The warehouse (official NSE bhavcopy with delivery, 52W, mcap, band, deals, PR zip) is strong. The app on top of it is not yet trustworthy:

- **Fabricated or broken numbers on screen** — header exposure is always 50% (string `"75% - 100%"` fails `float()` → default 50, `App/api/server.py:203-206`); VCP endpoint invents VDU (0.65/0.85/0.72) and pivot/stop (CMP×1.02/0.96, ×1.025/0.965) (`server.py:734-800`); R:R constant 2.0; Darvas distance-to-pivot always 0; 10-EMA risk constant 1.52%; RS shown as 50 and delivery as 45 when NULL (`server.py:579,593`); Cockpit "1D %" is (close−open)/open.
- **Data errors in the warehouse** — prices never adjusted for splits/bonuses (~227 symbols with fake crashes, e.g. GOODLUCK 2:1 bonus 2026-08-21: 1439.4 → 490.9); 246 deal prints stored twice (bulk ∩ block); `TOTAL` row from the mcap file carries mcap 4.77e7 Cr and poisons Logistics; sector vs-Nifty is NULL on the latest session (append-order bug, `Scripts/append_database.py:~157`); survivorship (universe = today's EQUITY_L).
- **Security** — `debug_symbol` is f-string-interpolated into SQL (`server.py:493,549`) with CORS `*`; DuckDB `COPY … TO` can write files even on a read-only connection.
- **History unused** — 594 sessions of prices/breadth/sector rotation exist; every React tab is a single-day snapshot. No study of the history exists in the app.
- **Terminology unexplained** — metrics (breadth %, 52W counts, RS) are shown without meaning, zones, or how to combine them.

Detailed per-tab findings: Appendix A.

## 2. Decisions (locked with the user, 2026-09-25/26)

| # | Decision |
| :--- | :--- |
| D1 | **React + FastAPI is the only UI.** NiceGUI-only features (portfolio, journal, focused-v2 page, Data Health page) are **not** ported. NiceGUI source stays in the tree; its launcher leaves the daily path. |
| D2 | Current React feature set is the right scope; the work is correctness, history, and polish. No new tabs beyond §7's six. |
| D3 | **Split/bonus adjustment is in scope** (reverses K8). |
| D4 | **Six tabs:** Desk · Screener (Momentum + VCP Workbench merged) · Groups (Sector Intel + Capital Flow merged) · Deals · Charts · Research. Stock 360 is a sidecar plus a full page. |
| D5 | **Refined dark terminal** look; single token file (K11 palette). |
| D6 | **Approach A:** rebuild in place, sub-project by sub-project, app always shippable; libraries: TanStack Query/Table/Virtual, cmdk, lightweight-charts, Pydantic + generated TS types. |
| D7 | **5-year NSE archive backfill** of `sec_bhavdata_full`, `ind_close_all`, PR zips, bulk/block deal archives (depth verified per file before committing to a number). |
| D8 | Regime shown as a **plain-language environment verdict with change-over-time and alerts**, not a percentage band. |
| D9 | Every metric explains itself via one **metric dictionary**. |
| D10 | History is **studied**: market analogs, stock analogs, big-mover fingerprint with catalyst attribution (mcap ≥ ₹1,000 Cr point-in-time), taxonomy-level studies, and time travel. |
| D11 | Existing K-decisions that still hold: K2 (keep `rs_percentile` as peer rank, label honestly), K4 (fail-closed NULLs, no fabricated copy — but the queue keeps the name **VCP** because it now uses `detect_contractions`, so K4's "Stage-2 coil" rename is superseded), K6 (≥₹1,000 Cr default floor), K13 (no implied account equity — the sizer only uses what the user types), K14 (weekly Darvas as a toggle), K15 (RS ≥ 70 not a default Momentum filter), K17 (no official FII/DII). |

## 3. Architecture overview

```
NSE files (daily + archive backfill)
   │  download_nse_reports (staged, checksummed)
   ▼
Ingest & adjust ── prices_daily (raw + adj_*), price_adjustments, universe_history, holiday_calendar
   │
   ▼
Derive (incremental daily; full on rebuild)
   indicators_daily (on adjusted prices)
   regime_daily · group_daily · setup_daily · deal_prints · deal_session_net
   │
   ▼
Evidence engine
   setup_outcomes · environment_calibration · market_analogs · big_move_events · big_move_features
   │
   ▼
FastAPI  /api/v2  →  App/services/*  (no UI imports, parameterized SQL, Pydantic models, session-keyed cache)
   │
   ▼
React shell (tokens, TanStack Query, DataTable, Chart, Ctrl+K, URL state, time travel)
   Desk · Screener · Groups · Deals · Charts · Research · Stock 360
```

User data (watchlist, notes) lives in `Database/marketpulse_user.duckdb`; the market DB is read-only to the API.

## 4. Data-truth layer (sub-project 2)

### 4.1 Inputs and backfill
| File | Today | Backfill target | Used for |
| :--- | :--- | :--- | :--- |
| `sec_bhavdata_full_DDMMYYYY.csv` | 640 archived, from 2024-05-06 | ~5 years | OHLCV, delivery, universe (incl. delisted) |
| `ind_close_all_DDMMYYYY.csv` | not used | ~5 years | All NSE indices OHLC + volume/turnover; replaces MA-file index parsing |
| `PRddmmyy.zip` (`mcap`, `bc`, `bm`, `hl`, `pd`, `an`) | 12 archived | ~5 years | Point-in-time mcap + face value + issue size; corporate actions; board meetings; official 52W highs/lows |
| `CM_52_wk_High_low_*` | 87 archived | as available | Adjusted 52W; adjustment confirmation |
| Bulk / block deals | from 2026-04-29 | ~5 years | Deal history, catalysts, house track records |
| `sec_list`, `PE`, `mcap*.csv`, `MA*.csv` | daily | — | Band/surveillance remarks, P/E, (MA kept only for commentary) |

Backfill rules: probe archive depth and format per file per year first; per-year parsers; resumable, checksummed, rate-limited (≥1 s between requests, retries with jitter); files land in `Input/archive/` (untracked).

### 4.2 Price adjustment
- Table `price_adjustments(symbol, ex_date, factor, kind, source, confidence)`.
- Factor sources, in priority order:
  1. **mcap file** face-value change (split: 10→2 ⇒ ×5) or issue-size jump at constant face value (bonus); cross-checked with the adjusted 52W high/low ratio on ex-date (GOODLUCK: 1672.10→557.37 and 915→305 ⇒ 3.00).
  2. **PR `bc` file** purpose text parsed (`BONUS a:b` ⇒ (a+b)/b; `SPLIT FROM Rs x TO Rs y` ⇒ x/y).
  3. **Gap inference** snapped to clean ratios {1.1, 1.2, 1.25, 1.5, 2, 3, 4, 5, 10}; accepted only with a second agreeing source, else `confidence='unconfirmed'`.
- `Input/reference/adjustments_override.yaml` for manual corrections.
- Demergers and rights: flagged (`kind='demerger'|'rights'`), not adjusted; UI shows a badge.
- `prices_daily` keeps raw columns and adds `adj_open/high/low/close`, `adj_volume`. All indicators, RS, Darvas, VCP, charts, outcomes and studies use adjusted columns. Raw shown only where labelled.

### 4.3 Universe, calendar, taxonomy
- Universe built from bhavcopy rows (series whitelist EQ/BE/BZ), not from today's EQUITY_L; `universe_history(symbol, isin, first_date, last_date, status)`; renames joined by ISIN.
- `holiday_calendar` (NSE trading holidays + special sessions, e.g. Muhurat 2026-11-08) drives freshness, catch-up and gap checks.
- Taxonomy: four levels in the user's naming — **Broad Sector (12) › Sector (22) › Broad Industry (59) › Industry (187)** — with NSE's official names (Macro-Economic Sector › Sector › Industry › Basic Industry) stored alongside for tooltips. Taxonomy is current-mapping only (documented limitation).

### 4.4 Specific fixes
- Deals: one row per print keyed on (trade_date, symbol, client, side, qty, price) with `deal_types[]`.
- Exclude `TOTAL` (and any non-security aggregate row) in every builder.
- Append order: write the session's index rows before computing sector vs-benchmark metrics.
- Placeholder input files → manifest status `degraded`; health shows Partial; previous day's reference data retained.
- Point-in-time: every as-of window bounded `<= as_of`; historical mcap from backfilled PR mcap files.

### 4.5 New stored tables (computed in the EOD run)
- `regime_daily` — pillar inputs, pillar statuses, verdict, rule id, days in state (§6.1).
- `group_daily` — per level × floor: equal- and cap-weighted returns; excess vs Nifty 50 / MidSml 400 at 21/63; JdK RS-Ratio and RS-Momentum; rank and Δ 5/20/63; breadth (% > 50/200 EMA, trend-template %, official new highs); turnover share 5d/20d avg and Δ; delivery-weighted accumulation; deal net 10 sessions.
- `setup_daily` — one row per (queue, symbol, trade_date): trigger, stop, risk %, distance, features snapshot, first_seen, status.
- `deal_session_net` — symbol × day: buy/sell/net by class, unique buying houses, VWAP, vs ADV (NULL if ADV missing), deal price vs close, event type (accumulate / fresh / distribute / transfer-interse / placement / churn).

### 4.6 Safety
- Rebuild writes to a temp DB; preservation failure **aborts** the swap; swap via `os.replace`; writer lock file shared by all writers.
- Dated backups (keep last N) after `CHECKPOINT`; nightly backup of the user DB.
- Failed EOD run sends a Telegram alert; logging streams to file.

## 5. Evidence engine (sub-project 3)

- `setup_outcomes` — for every `setup_daily` signal: trigger fill (next session crossing trigger), stop exit, R-multiple path, hit +1R/+2R before stop, MAE/MFE, days held (horizon 20 sessions default). Identity resets when a symbol leaves a queue for ≥ 5 sessions.
- Aggregates per queue / preset × environment state × group quadrant: n, hit rate, average R, median R, drawdown. **n < 30 ⇒ "insufficient sample"** instead of a number.
- `environment_calibration` — verdict rules validated against setup outcomes (§6.1.5).
- `market_analogs` — standardized daily environment vector; k-NN (k=10) excluding the most recent 60 sessions; stores forward MidSml400 5/20/60 and next-month follow-through.
- Stock analogs — nearest past `setup_daily` rows of the same queue on (base depth, RS, RVOL, group quadrant, environment); returns outcome distribution.
- `big_move_events` + `big_move_features` — see §7.6.
- Study hygiene: point-in-time only, purged/embargoed train–test split, controls matched on date + industry + mcap/ADV bucket (method of `docs/research/2026-09-12-uc-lift-summary.md`), n printed on every statistic.

## 6. Cross-cutting UX principles

### 6.1 Market Environment (replaces the exposure % strip)

**6.1.1 Verdict** — five states: **Favourable** (press) · **Constructive** (normal size) · **Mixed** (selective, half size) · **Weak** (mostly cash) · **Danger** (protect capital). Shown with what changed: "improved from Weak on Mon · 2nd day improving".

**6.1.2 Pillars** — each shows a plain sentence, 1D / 1W / 1M direction, and a status (Healthy / Neutral / Weak):

| Pillar | Question | Inputs | Initial zones (calibrated in §5) |
| :--- | :--- | :--- | :--- |
| Trend | Is the market going up? | MidSml400 and Nifty vs 20/50/200 EMA and slope | Above rising 50 EMA = Healthy; below 200 = Weak |
| Participation | Are most stocks joining? | % > 50 EMA, % > 200 EMA, 10-day A/D line | >60 Healthy, 40–60 Neutral, <40 Weak; direction overrides level by one step |
| Leadership | Are strong stocks getting stronger? | Official new 52W highs − lows (PR `hl`), Stage-2 count | Net highs rising = Healthy; net lows expanding = Weak |
| Follow-through | Are breakouts working now? | Stocks breaking a 20-day high on RVOL ≥ 1.5 in sessions t−10…t−3: % still above breakout close | ≥50% Healthy, 35–50 Neutral, <35 Weak |
| Stress | Hidden selling or fear? | VIX level + 5d change; distribution days (index −0.2% on higher turnover) in 25 sessions | ≥5 distribution days or VIX +20% in a day = Weak |

**Timing note** under Participation: % > 10 EMA is a short-term stretch gauge — >80 stretched (breakouts tend to pull back; wait 2–3 days), <20 washed out (bounces start). It never sets the verdict alone.

**6.1.3 Verdict rules** — a published table mapping pillar statuses to states (e.g. Favourable ⇐ Trend Healthy ∧ Participation ≥ Neutral ∧ Follow-through Healthy; Danger ⇐ Trend Weak ∧ Stress Weak). The matched rule is shown.

**6.1.4 Connected readings** — hand-written divergence rules that fire only when true, each citing values, e.g.: narrow rally (index up 3d, % > 50 EMA falling); leaders holding (new highs rising while index dips); pullback-buy window (% > 10 EMA < 20 inside % > 200 EMA > 60); choppy (participation Neutral+ but follow-through Weak).

**6.1.5 Trust** — 6-month verdict strip under the MidSml400 line; proof table of each queue's outcomes per state from the backfill. **Ship gate:** the verdict must separate outcomes (Favourable/Constructive average R materially above Weak/Danger); otherwise recalibrate.

**6.1.6 Alerts** — Telegram (existing bot) + in-app banner on state change, distribution days reaching 5, follow-through < 35%, VIX spike. Max once per day, after EOD.

### 6.2 Metric dictionary
One server-side dictionary in `Scripts/data/metric_dictionary.yaml`, loaded by `App/services/metrics.py`: `key, plain_name, measures, zones[{range, label, why}], read_with[], definition_sql_ref`. Served in API `meta`; drives every tooltip and zone colour. Example: `rs_percentile` → "Strength rank vs all stocks (0–100)".

### 6.3 Honesty rules
NULL stays NULL (UI "—"); no silent caps (`total` + `returned`); every screen shows `as_of` and freshness; derived labels come from the same functions as the queues (one source of truth); contract tests ban fabricated defaults.

## 7. Tabs

### 7.1 Shell
Top bar: brand · **data as-of chip** (green / amber 1 session stale / red older or degraded; opens Data Health popover) · environment verdict · time-travel date picker (violet "History mode" banner when not latest) · Ctrl+K. Tabs 1–6; watchlist count. Resizable, pinnable Stock 360 sidecar. API-down banner distinct from empty results. Tabs stay mounted; URL holds tab/symbol/preset/filters/group/as_of.

Keys: Ctrl+K palette · 1–6 tabs · J/K rows (sidecar follows) · Enter full Stock 360 · W watchlist · T TradingView · C copy · / filter · Esc closes innermost layer only.

Export: one TradingView formatter (`NSE:`, `-`→`_`, de-dup, optional `###Section`); copies visible filtered sorted rows; reports true count or failure. "Open in Charts" on every list.

### 7.2 Desk
- **Environment panel** (§6.1) + analog one-liner (§7.6).
- **Leading groups strip** — top 5 RRG-Leading groups with rank Δ → Groups.
- **Queues:** Darvas Squeeze, Darvas 10 EMA, VCP.
  - VCP uses `Scripts/minervini_geometry.detect_contractions` (time-ordered swings, strictly shrinking depths, pivot = last-T high, stop = last-T low) plus `vdu_ratio`.
  - Darvas 10 EMA geometry: **proposed** trigger = prior session high, stop = pullback low (min low since touch of 10 EMA). *User to confirm in review.* Until confirmed, trigger/stop render "—".
  - Columns: symbol · Industry quadrant chip (Broad Sector in tooltip) · close · 1D % vs prev close · trigger · stop · distance % · risk % · RVOL · delivery % vs 20d avg · strength rank + Δ5 · excess vs MidSml400 63d · setup age / NEW · results-within-10-sessions warning · deal chip.
  - Full counts, virtualized; D/W/M toggle (Darvas); **New / Dropped since yesterday**; per-queue **evidence line** (hit +2R, avg R, n).
- **Sizer** (sidecar): user-typed ₹ risk (persisted, no default) → shares, position value, % of optional capital, cap warning.

### 7.3 Screener
- Server-side presets returning applied rules as editable chips: Minervini 8/8 (trend_template_pass + RS ≥ 70), Stage 2 leader, EMA stack, EMAs aligned / converge, Near / fresh 52W high, SMA template, Delivery thrust, NR7 / Inside bar, Weekly RSI ≥ 60, Darvas, VCP, UC thrust (lab). Presets replace, never stack.
- Fail-closed filters; "include IPOs" toggle (uses `rs_percentile_ipo`, badged). Lookback, day-volume and 20-day-volume are distinct, correctly labelled controls. Filter by any taxonomy level.
- History columns: strength rank + Δ5/Δ20 spark · days in Stage 2 · days since 52W high · 1M/3M/6M · first seen · New/Dropped vs yesterday.
- Rule debugger (symbol → per-rule pass/fail on the chosen date). Evidence per preset. VCP detail in sidecar (T list, depths, bars, volume ratio, pivot/stop, risk flagged > 8%).

### 7.4 Groups
- Level switcher (four levels) and floor switcher (≥1,000 Cr default / All / Watch 300–1,000), floor stated on screen, TOTAL excluded.
- **Board:** RRG quadrant + days in quadrant · excess vs MidSml400 / Nifty 21/63 · rank + Δ5/20/63 · breadth · money flow (5d/20d smoothed share) · delivery accumulation · 60-session sparks · concentration flag. Sorted by rank vs benchmark.
- **RRG canvas** with 4–8 week tails; click → drill.
- **Drill-down:** breadcrumb; members with strength rank, RS vs sector index, rank history T0/T-5/T-15/T-30, trend template, delivery-accumulation days (10), active setups; group index chart where NSE has one; evidence ("when this group turned Leading, members returned …").
- **Flow panel** replaces Capital Flow: top 5 inflow/outflow groups with persistence and 10-session deal net.

### 7.5 Deals
- Data per §4.4/§4.5. Transfer rule qty ±1% and price ±0.25%; split promoter inter-se vs placement absorbed by FII/DII. `Scripts/data/house_alias.yaml` + behavioural churn/prop flag (round-trip days ≥ 50%). Fund-pattern fixes (FUND/SICAV/PTE/LLC/LP/MASTER ⇒ FPI; PE/VC class; drop TRUSTEE ⇒ DII; NORGES ⇒ FPI).
- **Main table** grouped Accumulate · Fresh buyer · Distribute; columns net ₹ · vs ADV · buying houses (expand to prints) · persistence days · VWAP vs CMP · deal price vs close · alignment chips (>200 EMA, strength rank ≥ 70, within 15% of 52W high).
- Rails: Strategic/Transfer · Churn/Prop · Watch. **House page** with print history and next-open forward returns (min 5 bets; individuals not ranked as funds). **Follow-through panel** per play type vs baseline. Session replay; "NO RECORDS" alert. Deal chips feed Desk/Screener/Groups.

### 7.6 Research
- **Market analogs:** 10 nearest past dates, forward outcomes with spread and agreement warning.
- **Big movers:** events = upper circuit (`high ≥ prev_close × (1 + band/100) × 0.9995`) | +30% in 20 sessions | +50% in 60 sessions; filters mcap ≥ ₹1,000 Cr **as of event date**, EQ, ADV floor. Fingerprint at T-1/T-5/T-20/T-60 vs matched controls (strength rank + Δ, base length/depth, range contraction, volume dry-up then expansion, delivery trend, 52W distance, group state at all four levels, environment state, deals, results ±5). Outputs: out-of-sample lift table; median feature path T-60…T+20 (movers vs controls); **precision** ("of stock-days like this, X% moved within 20 sessions").
- **Catalyst attribution** per event: results ±3 sessions (PR `bm` / events) · deal ±3 · sector-wide (≥ 50% of the Industry moved in-window) · corporate action · unexplained; rolled-up shares.
- **Event browser** with mini-charts; click opens Stock 360 as of that date.
- **Pre-move watch:** stocks matching the strongest traits today, precision printed; labelled research until out-of-sample precision clearly beats base rate.
- **Group studies:** big movers by taxonomy level; forward returns after an Industry enters Leading.

### 7.7 Stock 360 (sidecar + full page)
- Header: price, Δ vs prev close, as-of + staleness, mcap, circuit band, four-level path, adjustment note ("adjusted for bonus 2:1 on 21-Aug").
- Chart: adjusted candles, volume pane coloured by delivery %, EMA 10/20/50/200, RS-line pane (MidSml400 / Nifty) with new-high markers, D/W/M, full history; results/ex-date markers; institutional-only deal markers with net ₹ tooltip; VCP contraction shading; Darvas box.
- Blocks: setup verdicts from the Desk's own predicates; strength block (rank, excess vs benchmarks, 5/15/30 trend); 60-day delivery spark; deals table (client, class, side, value); next event ≤ 14 days; stock analogs; watchlist star; notes.

### 7.8 Charts
- **Source picker inside the tab:** Desk queues (each or all) · Screener preset or last custom run · Groups (any group, any level, searchable tree) · Deals (Accumulate / Fresh / Distribute) · Research (pre-move watch, big-mover events opened at event date) · Watchlist. Sort (strength rank, distance to trigger, setup age, …) and page through the whole list.
- 4 / 6 / 9 tiles synced by **date**; real relative performance vs benchmark for the chosen window; inspect a tile without closing the grid; J/K pages; shared bar cache with Stock 360. "Open in Charts" from every tab.

## 8. API v2 (sub-project 4)

- Routes are thin; logic in `App/services/{market,desk,screener,groups,deals,stock,evidence,research,user}.py`; no NiceGUI imports anywhere in the API process.
- Envelope: `{as_of, freshness, total, returned, rows, meta}`; `offset`/`limit` paging.
- Pydantic response models; `openapi-typescript` generates `frontend/src/api/types.gen.ts` (`npm run gen:api`).
- Parameterized SQL only; symbol validation `^[A-Z0-9&\-_.]{1,20}$`; CORS off in production (same origin), Vite dev origin only in dev.
- Response cache keyed on latest-session fingerprint; 503 + Retry-After on DB lock.
- `/api/v2/health` returns 503 when data is stale/degraded or DB unavailable; includes build/version.
- Endpoints: `market/regime`, `market/health`, `desk/queues`, `desk/queue/{name}`, `desk/diff`, `screener/presets`, `screener/run`, `screener/debug`, `groups/board`, `groups/rrg`, `groups/{id}`, `deals/session`, `deals/house/{id}`, `deals/followthrough`, `stock/{sym}`, `stock/{sym}/bars?tf=D|W|M`, `stock/{sym}/rs`, `stock/{sym}/events`, `stock/{sym}/deals`, `stock/{sym}/analogs`, `evidence/{setup}`, `research/analogs`, `research/big-moves`, `research/big-moves/{id}`, `research/pre-move`, `metrics/dictionary`, `watchlist` (GET/PUT), `notes/{sym}` (GET/PUT). All read endpoints accept `as_of`.
- Old `/api/*` endpoints deleted as each tab migrates.

## 9. UI platform (sub-project 5)

- `frontend/src/styles/tokens.css` (CSS variables) mapped in `tailwind.config.js`; ESLint rule bans raw hex in components; WCAG AA contrast; mono tabular numerals; tables 12–13 px, 28 px rows, min 11 px.
- Components: `DataTable` (TanStack Table + Virtual, `aria-sort`, column visibility, sticky header, keyboard focus, NULL "—"), `Chart` (lightweight-charts wrapper: candles, volume/delivery pane, EMAs, RS pane, markers, D/W/M, date-synced crosshair, `ResizeObserver`), `Metric`, `Spark`, `Chip`, `EmptyState`, `ErrorState`, `Skeleton`, `ErrorBoundary` per tab.
- `apiClient` (relative `/api/v2`) + TanStack Query (retry, abort, stale-while-revalidate).
- `fmt.ts` on `Intl.NumberFormat('en-IN')`: ₹, Cr, L, %, signed %.
- TypeScript `strict`; ESLint (react-hooks) + Prettier; Vitest; lazy-load Charts and Research; desktop-first, usable at 1280 px.

## 10. Build order

1. **Safety & truth hotfixes on the current app** (~1 week): parameterize `debug_symbol`, remove CORS `*`; delete fabricated VCP/R:R/pivot/VDU values and fix exposure parsing; collapse duplicate deal prints; exclude TOTAL; fix vs-Nifty append order; isolate tests from real DBs (`tests/test_stock_drawer_features.py`) and make the suite green; add fastapi/uvicorn/httpx to requirements.
2. **Data foundation** (§4).
3. **Evidence engine** (§5).
4. **API v2** (§8).
5. **UI platform** (§9).
6. **Tabs** in order: Desk → Stock 360 → Charts → Screener → Groups → Deals → Research; each old tab and endpoint removed after verification against the live DB.
7. **Clean-up:** README/runbook, CI (frontend build + typecheck, ruff), untrack ignored Input/archive, Input/downloads and `.superpowers` files, remove NiceGUI launcher from the daily path.

Each step gets its own implementation plan (writing-plans) and lands as small PRs with the suite green.

## 11. Testing

- **Fixture DB** built in `tmp_path`: a bonus stock, a split stock, a delisted stock, a holiday, duplicate bulk/block prints, a TOTAL row, NULL-RS IPO. Unit + contract tests run on it.
- **Golden tests:** GOODLUCK has no fake crash on adjusted series; squeeze badge == Desk predicate; exposure/verdict string survives end-to-end; no API response contains fabricated defaults (50/45/2.0/CMP×k); deals net equals collapsed-print sum.
- **Study tests:** point-in-time guard (no feature uses data after its date); purged split; n reported.
- **`realdb` marker** for live-DB tests, excluded from CI by default.
- **Frontend:** Vitest for `fmt.ts`, TradingView formatter, sort/filter; smoke render of each tab against a fixture API.

## 12. Risks

| Risk | Mitigation |
| :--- | :--- |
| NSE archive depth/format varies by year | Probe first; per-year parsers; resumable checksummed backfill |
| Full rebuild takes hours | Off-hours into temp DB; live DB untouched until swap; daily appends incremental |
| Environment verdict fails to separate outcomes | Ship gate §6.1.5; recalibrate before release |
| Big-move precision low | Watch list stays labelled research with precision shown |
| Scope creep | Six tabs fixed; each sub-project has its own plan |
| Taxonomy not point-in-time | Documented limitation |

## 13. Out of scope

Live data / broker execution; portfolio & journal UI (D1); official FII/DII (K17); shareholding / pledge; mobile layout; ML models in production (research only).

## 14. Resolved items (user accepted 2026-09-26)

1. Darvas 10 EMA geometry: trigger = prior session high, stop = pullback low (min low since the 10 EMA touch). Implemented with the Desk rebuild; until then the hotfix shows "—".
2. Taxonomy display names: Broad Sector › Sector › Broad Industry › Industry, NSE official names in tooltips.
3. Environment zones in §6.1.2 are starting points, calibrated in the evidence engine before release.

---

## Appendix A — Audit findings by tab (2026-09-25/26)

Verified items marked ✔ were re-checked directly against code/DB during brainstorming.

**Header / regime**
- ✔ Exposure always 50% — `server.py:203-206` strips `%` from `"75% - 100%"`, `float("75 - 100")` fails → 50.
- React gate never receives 52W lows (0 vs 104 in NiceGUI); "799 Darvas / 604 VCP" counts are unrelated filters (true queues 71 / 40); playbook text "Breadth is sub-40%" hardcoded; no as-of shown.

**Action Desk**
- "1D %" = (close−open)/open (`server.py:299`); R:R default 2.0 on all rows; distance-to-pivot 0.0 on 80/80 Darvas rows; Darvas 10 EMA risk constant 1.52% (stop = EMA10×0.985); VCP "3T" checks only first three depths (`vcp.py:163-167`); queues capped at 40; duplicate React keys; setup class shows raw queue key; frontend fallback "why now" copy fabricated.

**Momentum**
- ✔ RS `COALESCE(...,50)` (`server.py:579`), delivery `COALESCE(...,45)` (`:593`); lookback only relaxes the day-volume gate; 20D-avg mode silently adds day-volume gate; NULL EMA200 passes Stage-2 filters; weekly RSI filter also requires daily RSI; NR7 hides `vcp_score ≥ 40`; LIMIT 300 silent; presets client-side and stack.

**VCP Workbench**
- ✔ VDU fabricated 0.65/0.85; fallback path fabricates full geometry (`server.py:758-802`); 21/40 "3T" end on widening contraction; `qualifies=True` always; median risk 15.2% vs "3–5%" panel; `detect_contractions` unused by screener.

**Deals**
- ✔ 246 prints duplicated bulk ∩ block (dedupe key includes `deal_type`, `build_database.py:421`); 23/46 Play rows net ≤ 0; `n_houses` counts sellers; transfer rule rupee-only; clientele keyword waterfall misclassifies FPIs (Smallcap World, EuroPacific, Norges→DII, TRUSTEE→DII); NaN RS → 0; Star radar row numbering doubled by duplicates; 2026-09-15 "NO RECORDS" silent; no history used. Backtest (collapsed, mcap ≥ 1,000, next open): FII/DII net buy ≥ 0.3×ADV → T+5 −1.13%, T+20 −3.14% (n=21) vs baseline +0.29% / +2.08% — no standalone edge.

**Sector Intel / Capital Flow**
- ✔ `TOTAL` mcap 4.77e7 Cr in `stocks_master`; ✔ `sector_metrics_daily.rs_vs_nifty_*` 0/280 filled on 2026-09-25 (279/280 on 09-24); rotation state ranked across all names/groups before board filters (Industry board 0 Leading); "Avg RS" is median peer percentile; horizon RS is absolute return; divergence always Sector level and hidden; flow = single-day share difference (POLICYBZR swings Financial Services ~4pp); Capital Flow returns hardcoded 0; "Leading" means different things in the two tabs.

**Stock 360 / Charts**
- OHLC/EMAs correct for clean symbols; ~227 symbols with unadjusted fake crashes; every deal shown as SELL (colour mismatch `InspectorSidecar.tsx:930` vs `server.py:1699`); squeeze badge fires 65 vs Desk 21 on 150 names; no volume pane; EMA50/200 fetched not drawn; tiles synced by bar index; "vs BM" is 1-day difference; BE/BZ NULL delivery shown 0.0%.

**Warehouse**
- `corporate_actions` ratios all 1.0/1.0; `index_constituents` missing from live DB; `signal_outcomes` stale since 2026-08-17; `candidate_daily` only 6 sessions; `high_52w` semantics changed 2026-07-02; `index_daily` starts 2025-01-01; sector-index RS covers ~21% of stocks.

**Engineering**
- Test run: 10 failed / 471 passed / 3 skipped (stale tests after `bbe8ef4`, live-DB-dependent assertions, `-0.0` substring bug); tests write to the real user DB; requirements miss fastapi/uvicorn/httpx; no lint/type tooling; README describes NiceGUI on :8081.
