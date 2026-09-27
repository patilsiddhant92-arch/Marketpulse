# Parity audit — old React workspaces vs the rebuilt app (2026-09-27)

Branch `feat/p2-parity-audit` (from `feat/truth-contract` @ d07c49d). Old app = commit `d871ff9`
(`frontend/src/components/*`, `App.tsx`, `utils/*`, `App/api/server.py`).

Principle: every feature the user had exists in the new app unless there is an explicit reason
(fabricated / incorrect values — spec `2026-09-26-marketpulse-professional-rebuild-design.md` Appendix A).
Momentum and Deals are restored separately and are **not** in this audit; the Screener route was not edited.

Status legend: **PRESENT** (already in the new app) · **RESTORED** (this branch, commit) ·
**REPLACED** (same job done differently/better, no loss of information) · **DROPPED** (on purpose, reason) ·
**SCREENER** (belongs in the Screener, left for the controller).

Commits on this branch:

| Commit | What |
| :--- | :--- |
| `0c123be` | API: `/api/v2/stock/{sym}/profile`, `/api/v2/stock/{sym}/peers`, `/api/v2/market/accumulators` (+ tests, openapi, types) |
| `1c27c3d` | Stock 360: Trend template & footprint block, Industry peers block, sizer quick ₹10k/25k/50k |
| `58e271c` | Groups: Strong preset + clear, clickable leaders, optional old columns, per-group leaders copy-to-TV + Charts, Accumulators view |
| `a249ccf` | Charts: 1/2/8/12 tiles, Candles/Line (grid + per tile), pan/zoom sync on/off, Center, add symbol / remove tile |
| `55b6d07` | Shell/Desk: Space = watchlist, M = Charts, Breadth button + key hints, Desk “All queues” sectioned TV copy |
| `d9001e2` | Charts: adding a symbol to a long source never silently cuts the list |
| `058c4ae` | Desk watchlist panel: TradingView + CSV copy |


---

## 1. App shell (`App.tsx`)

| # | Old item | New location / status |
| :-- | :--- | :--- |
| 1 | Six workspace tabs (Cockpit, Momentum, Deals, VCP, Sector, Flow) | PRESENT — six tabs Desk / Screener / Groups / Deals / Charts / Research (`shell/tabs.ts`), keys 1–6 |
| 2 | Key **C** copies `NSE:SYM` of the selected stock | PRESENT — `shell/useShortcuts.ts` (dash → underscore, which the old key skipped) |
| 3 | Key **T** opens TradingView chart | PRESENT — `useShortcuts.ts` |
| 4 | Key **M** toggles the Tiles window | RESTORED `55b6d07` — M opens the Charts tab |
| 5 | Key **Space** stages / unstages the selected stock | RESTORED `55b6d07` — Space toggles the watchlist (W also does); ignored on focused buttons/links |
| 6 | **Esc** closes the Tiles window | PRESENT — layer stack (`lib/layers.ts`); Charts Esc leaves the expanded tile |
| 7 | “⊞ Tiles Window” header button | PRESENT — Charts tab (5) and “Open in Charts” on every list |
| 8 | “📊 Breadth Radar” header button | RESTORED `55b6d07` — “Breadth” button in the top bar (also in the Environment drawer) |
| 9 | Keyboard hint strip (C / T / M / Space) | RESTORED `55b6d07` — key list in the Ctrl K button tooltip; command palette lists tabs |
| 10 | Default selected symbol `HAL`, default tiles `HAL,MTARTECH,ROSSTECH,PARAS` | DROPPED — hard-coded demo symbols, not user data |
| 11 | Persistent Inspector sidecar | PRESENT — Stock 360 sidecar (`shell/StockSidecar.tsx`, resizable/pinnable) |
| 12 | Selected symbol shared across tabs | PRESENT — `?sym=` in the URL (`ShellContext`) |

## 2. Market exposure header (`ExposureGateHeader.tsx`, `/api/market/regime`)

| # | Old item | New location / status |
| :-- | :--- | :--- |
| 13 | Exposure % band (“Exposure 75–100%”) | DROPPED — always 50% (`server.py:203-206` parse bug, Appendix A); replaced by the Environment verdict |
| 14 | State label + action bias / playbook text | REPLACED — verdict + action (“selective, half size”) + what-changed (`shell/environment.tsx`); old playbook text was hard-coded (“Breadth is sub-40%”) |
| 15 | Max position size text | DROPPED — derived from the broken exposure band |
| 16 | Tape: advancers / decliners / net / advance-volume % | PRESENT — Desk › Today market strip (`today/TodayView.tsx`), Participation pillar |
| 17 | Trend breadth > 20 / 50 / 200 EMA + near-52W count | PRESENT — Participation / Leadership pillars, Environment drawer, breadth drawer |
| 18 | Click breadth → 180-session drawer | PRESENT — drawer link + RESTORED top-bar button (#8) |
| 19 | India VIX + 1D change | PRESENT — Desk Environment panel (5-day change) and Today strip (1-day change) |
| 20 | Stage-2 pool count button | REPLACED — Leadership pillar (Stage-2 count, net new highs); the old “799 Darvas / 604 VCP” counts were unrelated filters (Appendix A) |
| 21 | Top-3 leading themes with 5D return → Sector tab | PRESENT — Desk “Leading groups” panel (RRG Leading, rank Δ) → Groups |
| 22 | As-of date | PRESENT — freshness chip + as-of on every screen (old header had none) |

## 3. Action Desk / Cockpit (`CockpitWorkspace.tsx`, `/api/candidates/cockpit`)

| # | Old item | New location / status |
| :-- | :--- | :--- |
| 23 | Queue tabs: VCP · Darvas 10 EMA · Darvas Squeeze | PRESENT — Desk queue tabs (`desk/QueuePanel.tsx`), plus D/W/M for Darvas |
| 24 | “Primary Setups” (all three queues in one list) | RESTORED `55b6d07` — “All queues” copies one sectioned TradingView list (`###Darvas Squeeze,…,###Darvas 10 EMA,…,###VCP,…`); the combined grid is Charts › `queue:all` |
| 25 | Count of qualified setups | PRESENT — counts on each queue tab, full (old list capped at 40) |
| 26 | As-of | PRESENT |
| 27 | Copy All to TV (`NSE:A,NSE:B`, deduped, `-`→`_`) | PRESENT — “TradingView” copies visible rows in table order (`###Queue,NSE:…`) |
| 28 | Symbol cell → TradingView link | PRESENT — T key / Stock 360 “TradingView” link; row click opens Stock 360 |
| 29 | Sector column | REPLACED — Industry column with quadrant chip; full path in tooltip |
| 30 | CMP | PRESENT — Close |
| 31 | 1D % | PRESENT — vs previous close (old was close vs open, Appendix A) |
| 32 | Setup class chip | PRESENT — queue tab + Darvas 10 EMA “Flavor”; old chip showed the raw queue key |
| 33 | Squeeze % column (squeeze queue) | PRESENT — “Squeeze” column |
| 34 | RVOL badge | PRESENT |
| 35 | Dist to pivot (colour zones) | PRESENT — “Dist.” (metric-dictionary zones, warn when past trigger) |
| 36 | Risk % (≤5 green, >8 red) | PRESENT — “Risk” + wide-risk flag > 8% |
| 37 | Why now / rationale text | REPLACED — WhyCard in Stock 360 + context chips; old fallback text was fabricated (Appendix A) |
| 38 | ★ Watchlist button per row | PRESENT — W / Space key, ★ in Stock 360, star marker in the row |
| 39 | Default sort: distance asc / squeeze asc | PRESENT — `DEFAULT_SORT` per queue |
| 40 | 3-state column sort, nulls last | PRESENT — `ui/DataTable.tsx` (`sortUndefined: 'last'`) |
| 41 | Row click selects symbol for the Inspector | PRESENT — J/K focus follows into the sidecar |

## 4. VCP Workbench (`VcpWorkbenchWorkspace.tsx`, `/api/screener/vcp`)

| # | Old item | New location / status |
| :-- | :--- | :--- |
| 42 | VCP candidate list | PRESENT — Desk › VCP queue (true `detect_contractions` geometry) |
| 43 | Header: Stage 2 · T1>T2>T3 · VDU ≤ 0.80 | PRESENT — queue description tooltip + evidence line |
| 44 | Count confirmed + as-of | PRESENT |
| 45 | Copy All to TV | PRESENT — queue TradingView copy |
| 46 | Contraction sequence (wave_sequence) | PRESENT — “Ts” + “Last T” columns; full T list in Stock 360 Setups and Screener VCP detail |
| 47 | VDU ratio + ✓ when confirmed | PRESENT — “VDU” column (zone colour); old 0.65/0.85 values were fabricated (Appendix A) |
| 48 | Pivot trigger / stop loss | PRESENT — Trigger / Stop (fallback geometry was fabricated, now NULL) |
| 49 | Risk % / Dist to pivot | PRESENT |
| 50 | ★ Watchlist per row | PRESENT |
| 51 | Position sizer panel: pivot, stop, risk (“target 3–5%”) | PRESENT — Stock 360 Setups block Levels + Sizer row |
| 52 | Risk budget buttons ₹10k / ₹25k / ₹50k (default ₹25k) | RESTORED `1c27c3d` — quick 10k/25k/50k buttons next to the typed ₹ risk; no silent default (spec §7.2) |
| 53 | Suggested shares + total position value | PRESENT — Sizer row (shares, position value, % of capital, cap warning) |
| 54 | “Add to Active Watchlist” button | PRESENT — ★ Watch in Stock 360 |

## 5. Sector Matrix (`SectorWorkspace.tsx`, `/api/sector/rotation`, `/api/sector/{group}/stocks`)

| # | Old item | New location / status |
| :-- | :--- | :--- |
| 55 | Level: Broad Industry / Sector / Industry | PRESENT — four levels incl. Broad Sector (`GroupsRoute.tsx`) |
| 56 | ≥ ₹1,000 Cr floor badge | PRESENT — floor switcher (≥1,000 Cr / All / Watch) with the floor stated |
| 57 | Horizon 10D / 30D / 63D | REPLACED — Ret 21d, Exc 21d/63d, rank Δ5/Δ20/Δ63, Health 21d, Index 1Y; old “horizon RS” was an absolute return mislabelled as RS (Appendix A) |
| 58 | “N of M groups” count | PRESENT — table total + glance band |
| 59 | Rotation-state chips with live counts | PRESENT — RRG quadrant chips with counts |
| 60 | “All” chip | PRESENT — no chip selected = all |
| 61 | “✨ Strong (L+E+I)” preset | RESTORED `58e271c` — “Strong” chip = Leading + Improving (RRG has no Emerging) |
| 62 | “Clear (n active)” button | RESTORED `58e271c` — “clear (n)” |
| 63 | Empty result + “Reset filters” | PRESENT — empty state “Clear the filter or quadrant chips” |
| 64 | Group name + (n stocks) | PRESENT — Group + Stocks columns; thin / 1-stock flags |
| 65 | Rotation state badge | REPLACED — RRG quadrant + days + “falling/narrow” note; old label kept as optional **Old state** column RESTORED `58e271c` |
| 66 | Stage 2 % (count/total + bar) | REPLACED — TT % (all 8 trend-template terms, a superset) and >200E %; a separate Stage-2 % needs a new stored group column (follow-up if wanted) |
| 67 | Avg RS (+ median) | RESTORED `58e271c` — optional **Med RS** column (the old “Avg RS” was the median); Health/RS-Ratio are the ranked measures |
| 68 | > 50 EMA % / > 200 EMA % | PRESENT — >50E / >200E |
| 69 | 52W highs | PRESENT — NH (optional) |
| 70 | Flow: turnover ₹ Cr | RESTORED `58e271c` — optional **T/O ₹Cr** column |
| 71 | Flow: share Δ (pp) with 🔥 | REPLACED — Flow Δ (5d vs 20d share, smoothed) + Flow d persistence; single-day share Δ swung ~4pp on one stock (Appendix A) |
| 72 | Flow: share % of tape | PRESENT — T/O 5d share; 1-day share RESTORED as optional **T/O 1d** |
| 73 | Leader chips (click → Inspector, RS, 1D, TV link) | RESTORED `58e271c` — Leaders column chips open Stock 360 (RS / 1D / TV inside it) |
| 74 | “Tiles” button → group members ≥1,000 Cr above 200 EMA | PRESENT — “charts” link for the selected group, drill “Open in Charts”, Charts source `group:` |
| 75 | Group member list (`/api/sector/{group}/stocks`) | PRESENT — Group drill members (`groups/GroupDrill.tsx`) |

## 6. Capital Flow Radar (`CapitalFlowDashboard.tsx`, `/api/market/capital-flow`)

| # | Old item | New location / status |
| :-- | :--- | :--- |
| 76 | Level Sectors / Industries | PRESENT — Groups level switcher drives the Money flow panel |
| 77 | Timeframe 1D / 5D / 1M share deltas | REPLACED — smoothed 5d-vs-20d share with 10-session persistence (spec §7.4 flow panel); single-day deltas were noise and “returns hardcoded 0” (Appendix A) |
| 78 | Refresh button | PRESENT — automatic query refresh / retry on error |
| 79 | Universe note (mcap / ADV / CMP floors, n names) | PRESENT — floor label + How to read |
| 80 | Top inflow / outflow clusters (ranked) | PRESENT — Money flow Inflow / Outflow top 5 |
| 81 | Cluster rotation-state chip | PRESENT — drill; quadrant on the board row |
| 82 | Share Δ | PRESENT |
| 83 | Turnover ₹ Cr / share % | PRESENT — row tooltip (5d vs 20d share) + optional board columns (#70, #72) |
| 84 | “Stage 2” (%>200 EMA) | PRESENT — >200E on the board |
| 85 | Deals net ₹ Cr | PRESENT — 10-session deal net (PROP excluded) |
| 86 | Per-cluster “TV” copy of leaders | RESTORED `58e271c` — copy icon per flow row (`###Group,NSE:…`) |
| 87 | Per-cluster “⊞” tiles of leaders | RESTORED `58e271c` — chart icon per flow row → Charts `group:` source |
| 88 | Pacesetter chips + TV links | PRESENT — drill members; leaders on the board (#73) |
| 89 | Top stock capital accumulators table | RESTORED `0c123be` + `58e271c` — Groups › **Accumulators** view (`/api/v2/market/accumulators`), full list (old capped at 25) |
| 90 | Accumulator columns: symbol, sector & industry, mcap, CMP, 1D, turnover, surge, delivery %, ticket ratio, RS | RESTORED — same columns + Dlv %× |
| 91 | Tags Whale 🏛️ / Deliv 📦 / Acc Vol 📈 | RESTORED — Whale / Deliv / Acc vol chips (same rules: ticket ≥ 1.25×, delivery_spike, price_up_delivery_up) |
| 92 | Search filter | RESTORED — the Groups filter box filters symbol / name / sector / industry |
| 93 | Copy All (n) to TV | RESTORED — “TradingView (n)” copies rows as shown |
| 94 | Tiles View of accumulators | RESTORED — “Open in Charts” |
| 95 | “+ Stage” per row | RESTORED — ★ per row |

## 7. Inspector sidecar (`InspectorSidecar.tsx`, `/api/stock/{sym}/chart`, `/peers`)

| # | Old item | New location / status |
| :-- | :--- | :--- |
| 96 | Candles + EMA 10/20 | PRESENT — Stock 360 chart EMA 10/20/50/200, adjusted prices |
| 97 | SMA 50/150/200 toggle | REPLACED — EMA 50/200 drawn; SMA terms shown as the trend-template checklist (#101) |
| 98 | Darvas top / floor step lines | PRESENT — Darvas boxes (shaded, breakout / breakdown markers) |
| 99 | 5-session dotted future projection of box / 10 EMA | DROPPED — a flat extension of today’s levels drawn as future bars; the box and trigger/stop lines carry the same levels without inventing bars |
| 100 | Deal markers | PRESENT — institutional deal markers with correct side (old showed every deal as SELL, Appendix A) |
| 101 | Minervini 8-point template checklist (score/8, per-criterion ✓/✗) | RESTORED `0c123be`/`1c27c3d` — “Trend template & footprint” block; the same eight terms as the stored `trend_template_pass_n` (NULL = “no data”, never ✗) |
| 102 | Darvas box geometry card (top / floor, squeeze %) | PRESENT — Setups block (box bottom, squeeze %, trigger = box top) |
| 103 | Institutional footprint tags (Acc Vol, Deliv Surge, Whale, NR7) | RESTORED `1c27c3d` |
| 104 | Turnover vs 20D avg (₹ Cr, %) | RESTORED `1c27c3d` |
| 105 | Delivery ratio vs 20D baseline | PRESENT — Delivery % ×20d (Trend & activity); 20d avg shown in the footprint block |
| 106 | 5-session activity trail (1D %, RVOL, delivery %) | RESTORED `1c27c3d` |
| 107 | Order ticket ratio | RESTORED `1c27c3d` |
| 108 | Peer rank #x of y + industry | RESTORED `1c27c3d` — Industry peers block header |
| 109 | Peers tab: group, parent sector, rank | RESTORED — block meta; taxonomy path in the header |
| 110 | Peers “Copy All (n)” (`NSE:A,NSE:B`) | RESTORED — “TV (n)”, byte-identical text (verified live) |
| 111 | Peers “Tiles View (2x2)” | RESTORED — “Charts” opens stock + peers |
| 112 | “Better options in this industry” | RESTORED — “Stronger, near 10 EMA” chips (higher rank and within ±3% of 10 EMA; rule stated) |
| 113 | Peers table (#, symbol, RS, CMP, 1D, 10 EMA dist) | RESTORED — same columns, click opens that stock |
| 114 | Deals tab (last 10) | PRESENT — Bulk / block deals block (client, class, side, ₹ Cr) |
| 115 | ★ Watchlist toggle, TradingView link | PRESENT |
| 116 | “Select a stock…” empty state with J/K hint | PRESENT — sidecar closes when nothing is selected; J/K on tables |

## 8. Multi-chart Tiles window (`MultiChartModal.tsx`)

| # | Old item | New location / status |
| :-- | :--- | :--- |
| 117 | Layouts 1 / 2 / 2x2 / 2x3 / 2x4 / 3x3 / 3x4 | RESTORED `a249ccf` — tiles 1 / 2 / 4 / 6 / 8 / 9 / 12 (was 4 / 6 / 9) |
| 118 | Global Candles / Line toggle | RESTORED `a249ccf` |
| 119 | Per-tile Candles / Line toggle | RESTORED `a249ccf` (grid switch resets overrides, as before) |
| 120 | Sync ON/OFF (pan / zoom) | RESTORED `a249ccf` — date-based range sync (crosshair sync was already there) |
| 121 | Center (re-center all) | RESTORED `a249ccf` |
| 122 | Pagination + `[` `]` / arrow keys | PRESENT — pager, J/K and `[` `]` |
| 123 | Page x of y (a–b of n) | PRESENT |
| 124 | Symbol pool drawer: add symbol | RESTORED `a249ccf` + `d9001e2` — “Add symbol” (turns the source into an editable list) |
| 125 | Remove symbol from pool | RESTORED `a249ccf` — × on tiles of an editable list |
| 126 | Load industry peers of benchmark | REPLACED — Stock 360 peers “Charts” button (#111) and Charts source `group:industry:…` |
| 127 | Quick select All / Top 4 / 6 / 9 / Clear, checkboxes | REPLACED — tile count + paging over the whole list; sort menu |
| 128 | Benchmark stock + “vs BM” badge | REPLACED — return vs MidSml400 over 1M/3M/6M; old badge was a 1-day difference (Appendix A) |
| 129 | Tile: click symbol to edit it | REPLACED — add / remove on editable lists |
| 130 | Tile: price, 1D % | PRESENT |
| 131 | Tile: peer-rank badge / 👑 leader | REPLACED — context chips (group Health, setups, deals) + Stock 360 peers rank |
| 132 | Tile: RS badge | PRESENT — “RS” rank on every tile |
| 133 | Tile: TV link, inspect in sidecar, maximize | PRESENT — symbol → Stock 360, expand, big chart (F) |
| 134 | Candle count adapts to layout | PRESENT — per-timeframe initial bars; tiles resize |
| 135 | EMA 10/20, Darvas lines, deal dots on tiles | PRESENT — EMAs, Darvas boxes toggle, trigger/stop lines |
| 136 | Open from Sector / Flow / Peers / accumulators | PRESENT/RESTORED — “Open in Charts” everywhere incl. new Accumulators and peers |

## 9. Breadth drawer, staging basket, utils, legacy endpoints

| # | Old item | New location / status |
| :-- | :--- | :--- |
| 137 | 180-session breadth drawer: 15/30/60/180 horizon | PRESENT — `components/MarketBreadthDrawer.tsx` (legacy endpoint still served) |
| 138 | KPI strip (state, >20/50/200, A/D, turnover) | PRESENT |
| 139 | History table incl. EXP turnover flag | PRESENT |
| 140 | Staging basket bar (chips, remove, clear) | PRESENT — `components/StagingBasketDrawer.tsx` on every tab except Desk/Stock page |
| 141 | Basket “Copy for TradingView” + “CSV” | PRESENT (bar, old text) + RESTORED `058c4ae` on the Desk watchlist panel (bar is hidden there) |
| 142 | Basket persisted? (old: in memory only) | PRESENT — server-side watchlist |
| 143 | `utils/clipboard.ts` (execCommand fallback) | PRESENT — `lib/clipboard.ts` (reports real success) |
| 144 | `utils/tableSort.ts` (3-state, nulls last) | PRESENT — DataTable |
| 145 | `utils/benchmarks` InfoTooltip / badges | PRESENT — metric dictionary tooltips + zone colours |
| 146 | TradingView formats | PRESENT — one formatter (`lib/tradingview.ts`): `NSE:`, `-`→`_`, de-dup, optional `###Section`. Sectioned “bucket” text (`###Name,NSE:…`) is identical to the old Momentum/Deals format; peers copy is byte-identical; the old VCP/Flow/basket copies used `", "` separators, which TradingView imports the same way (the basket bar still uses them) |
| 147 | `/api/export/symbols` (tradingview / chartink / dhan / raw) | DROPPED — never called by the old UI; the client formatter covers TradingView and the basket CSV covers raw lists |
| 148 | `/api/candidates/cockpit`, `/api/screener/vcp`, `/api/sector/rotation`, `/api/market/capital-flow`, `/api/stock/{sym}/chart`, `/peers`, `/api/sector/{group}/stocks` | REPLACED — v2 endpoints (`desk/queue/*`, `groups/*`, `stock/*`, new `stock/{sym}/profile`, `stock/{sym}/peers`, `market/accumulators`); legacy cockpit/vcp/breadth/regime still served for the NiceGUI/legacy paths |

## 10. Left for the Screener (controller)

None of the audited workspaces has a feature that must live in the Screener: the VCP Workbench list is the Desk
VCP queue and its detail is in Stock 360 / Screener `VcpDetail` already. (Momentum is being restored separately.)

## Counts

- Audited items: **148**
- PRESENT: **89** · RESTORED: **38** · REPLACED: **16** (information kept, method corrected) · DROPPED: **5** (#10, #13, #15, #99, #147) · SCREENER: **0**
  (first status word per row; several PRESENT rows also got a restored control, e.g. #18, #136, #141)

## Verification

- Live DB read-only (uvicorn :8796, `MP_DB_PATH` = live, user DB = temp copy), Vite :5196, Claude Browser:
  HAL profile checklist 6/8 = stored `trend_template_pass_n` 6; ACE 8/8; peers for ACE (#1 of 4, Construction
  Vehicles) and the copied text `NSE:ACE,NSE:BEML,NSE:AJAXENGG,NSE:TIL`; Accumulators 107 rows on 2026-09-25
  (WHIRLPOOL ₹2,583 Cr, +1,038%); Strong chip = 55 groups; leader chip opens Stock 360; flow copy
  `###Financial Technology (Fintech),NSE:PAYTM,NSE:MOBIKWIK,NSE:STYL`; Charts 12 tiles in Line mode rendered,
  add / remove symbol; Desk “All queues” = 314 symbols in 3 sections (same as Charts `queue:all`); Space toggles
  the watchlist, M opens Charts.
- Tests: `tests/test_api_v2_parity.py` (6) + `tests/test_api_v2_contract.py` (109, new URLs in the envelope list);
  vitest 224 passed; `tsc --noEmit` clean; eslint 0 errors (1 pre-existing warning); `vite build` ok.
