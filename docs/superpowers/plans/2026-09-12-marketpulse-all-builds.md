# MarketPulse All-Builds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MarketPulse a trustworthy NSE EOD swing desk: honest labels, unified Darvas Squeeze, canonical sector intel, a 10-second Action Desk path, plus a lab-only upper-circuit research spike that only graduates to UI if lift is real.

**Architecture:** Keep NiceGUI + DuckDB, official NSE EOD spine, cash equities only. No Screening Mantis clone. Ship Slice 1 truth fixes before new screens. UC work is read-only research against `marketpulse.duckdb` until contracts are proven.

**Tech Stack:** Python, NiceGUI, DuckDB, pytest, existing `Scripts/` pipeline and `App/` pages.

**Spec source:** `docs/MARKETPULSE-AUDIT-AND-UPGRADE-DESIGN.md` (2026-09-08d) + Chief of Staff audit plan (2026-09-12). User locked **all** first builds.

## Global Constraints

- Market DB remains read-only from the UI; writes only via EOD scripts / migrations.
- Do not invent vs-Nifty / VIX when index history is insufficient (~48 sessions) — show insufficient-history, never synthetic RRG from filled RS.
- `rs_percentile` stays min_count=4 universe; IPO adaptive scores only as separate columns if added.
- Darvas daily: one predicate shared by Action Desk queue and chart drawer; evaluate last bar after box computed on ≥252 sessions (or persisted series).
- No new UC screener in production nav until out-of-sample lift + false-positive notes exist.
- Prefer keep list: Action Desk, Momentum, Deals, Sectors (rebuild), Darvas; do not promote dead `screener_page` focused-v2 wrapper.
- Tests first for contract changes (`tests/test_sector_rotation_contract.py`, Darvas tests, Action Desk queue tests).
- Work on local tree `D:\Sid\MarketPulse2.0` until GitHub is connected for cloud PRs.

---

## File map (expected touch points)

| Area | Files |
| :--- | :--- |
| Sector read model | `Scripts/sector_read_model.py`, `Scripts/migrations.py`, sector metrics/rotation builders, `App/pages/sector_board.py`, optionally mount/retire `App/pages/sector_intel.py` |
| Darvas unify | `App/indicators/darvas.py`, `App/pages/action_desk.py`, `App/ui/stock_drawer.py`, `tests/test_darvas.py`, Action Desk Darvas queue tests |
| Action Desk truth | `App/pages/action_desk.py`, `App/ui/market_health.py`, playbook/copy sources, column registry `App/ui/columns.py` |
| UC lab | new notebook or `Scripts/research/` + write-up under `docs/`; read-only DuckDB queries; no nav tab until graduation |

---

## Workstream A — Canonical sector read model

### Task A1: Lock canonical source + fail-closed tests

**Files:** `tests/test_sector_rotation_contract.py`, `Scripts/sector_read_model.py`

- [ ] Write failing tests: UI rotation ranks must not come from null `rs_vs_nifty_*` synthetic Leading/Lagging; `sector_rotation` is canonical when rows exist for as-of date.
- [ ] Run tests; confirm fail on current behaviour where applicable.
- [ ] Change read model: prefer `sector_rotation` for rotation UI; never call `_computed_sector_overview` for ranks when vs-Nifty is all-null; return empty + insufficient-history badge instead.
- [ ] Run tests; pass.
- [ ] Commit: `fix(sector): fail closed on null vs-Nifty synthetic rotation`

### Task A2: Broad Industry board + honest toggles

**Files:** `App/pages/sector_board.py`, sector query helpers

- [ ] Default board grain = Broad Industry (59), not Industry (58) costume label.
- [ ] Fix toggle labels to real counts from taxonomy (Sector 22 / Broad Industry 59 / Industry 187 as exposed).
- [ ] Default sort named column `turnover_share_delta_5d` (compute live if not migrated yet); subtitle Δ SHARE 5D.
- [ ] Weekly toggle labelled honestly as 5D % sort of daily rows until weekly contract ships.
- [ ] Tests for label counts + default level.
- [ ] Commit: `fix(sector): Broad Industry board with named Δ-share sort`

### Task A3: Persist share/delta/leaders (optional same PR if small)

**Files:** `Scripts/migrations.py`, rotation builders, append path

- [ ] Add columns: `turnover_share_pct`, `turnover_share_delta_1d`, `turnover_share_delta_5d`, `adv_pct`, `leader_symbols` per design §7.4.
- [ ] Backfill or compute-on-read with same formulas; extend contract tests.
- [ ] Commit: `feat(sector): persist turnover share deltas and leaders`

### Task A4: Action Desk Step 2 uses same leading-group truth

**Files:** `App/pages/action_desk.py`

- [ ] Replace average stock-RS top-4 with same canonical board sort (named Δ-share or agreed column).
- [ ] Test Step 2 symbols/groups match board for fixed fixture date.
- [ ] Commit: `fix(action-desk): leading sectors from canonical rotation`

---

## Workstream B — Unify daily Darvas Squeeze

### Task B1: Single predicate + lookback contract

**Files:** `App/indicators/darvas.py`, `tests/test_darvas.py`

- [ ] Extract shared defaults: `max_squeeze_pct`, `max_candle_range_pct`, `ema20` alignment, `require_ohlc_inside`, lookback ≥252 for box then evaluate last bar.
- [ ] Failing tests for former desk/chart split (5.0/4.0/45 vs 3.5/3.5/full) becoming one contract (pick design defaults; document in test names).
- [ ] Implement; pass tests.
- [ ] Commit: `fix(darvas): one daily squeeze contract and ≥252 box lookback`

### Task B2: Wire Action Desk + chart drawer to shared API

**Files:** `App/pages/action_desk.py`, `App/ui/stock_drawer.py`

- [ ] Both call shared helper; remove divergent kwargs.
- [ ] Update tests that previously encoded the split (`test_action_desk_darvas_squeeze_queue`, candlestick darvas test).
- [ ] Commit: `fix(darvas): desk and chart share squeeze API`

### Task B3: Evidence columns on Darvas matrix

**Files:** `App/pages/action_desk.py`, `App/ui/columns.py`

- [ ] Show `squeeze_pct`, `darvas_top` (or top_box), `candle_range_pct` in matrix (not only inspector).
- [ ] Cap queue length for human TV paste (e.g. head 15–30 with “show more”), keep full export optional.
- [ ] Commit: `feat(darvas): evidence columns and sane queue length`

---

## Workstream C — Action Desk 10-second truth

### Task C1: Rename lying labels

**Files:** `App/pages/action_desk.py`, `App/ui/market_health.py`

- [ ] Queue 1 label: stop calling RS≥70 near-20d-high “VCP”; name the actual predicate.
- [ ] Market-health card: stop mapping `vcp_candidates` count to “Recent breakout”.
- [ ] Tests/snapshots for visible strings if present.
- [ ] Commit: `fix(action-desk): honest queue and health labels`

### Task C2: Exposure + playbook = code

**Files:** playbook sources, `action_desk.py` exposure card

- [ ] Wire exposure to `breadth_daily` same as strip (one universe).
- [ ] Remove or regenerate unsourced hit-rate copy (82/71/56 etc.) from live/tested functions only — else delete numbers.
- [ ] Commit: `fix(action-desk): exposure and playbook match live code`

### Task C3: Peel dead morning tax

**Files:** `App/app.py` tab_specs / legacy flags

- [ ] Confirm focused-v2 wrapper stays unmounted; document in README.
- [ ] Optional: hide emoji chrome behind a denser morning mode (YAGNI unless quick).
- [ ] Commit: `chore(ui): document dead screener wrapper; trim morning friction`

---

## Workstream D — Upper-circuit research spike (lab)

### Task D1: Event definition + sample

**Files:** new `Scripts/research/uc_events.py` or notebook under `docs/research/`

- [ ] Define band-correct limit-up events from prices + `stocks_master.band` (do not assume 10/20 for all).
- [ ] Build event table and matched controls (sector/liquidity).
- [ ] Write short method note in `docs/research/2026-09-12-uc-pre-event-method.md`.

### Task D2: Feature lift at T-1 / T-5 / T-10

- [ ] Features: Darvas/squeeze flags, RVOL, delivery, deals prior sessions, sector RS/state, distance to 52w, EMA stack — **pre-event only**.
- [ ] Compare event vs control; time-split OOS.
- [ ] Deliver lift table + honesty on FP rate to `docs/research/`.

### Task D3: Graduation gate (no UI until pass)

- [ ] If 2–3 simple conditions show stable lift, draft screener rule for Screener Desk review.
- [ ] If not, document “do not add screener” and stop.
- [ ] Commit docs only until graduation approved.

---

## Execution order

1. A1 → A2 → A4 (A3 can follow A2)
2. B1 → B2 → B3
3. C1 → C2 → C3
4. D1 → D2 → D3 in parallel from the start (read-only)

## Done when

- Trader sees one Darvas truth, honest sector leadership, Action Desk labels that match predicates, and a UC research write-up with a clear graduate / do-not-ship decision.
- pytest contract suites green for touched areas.
