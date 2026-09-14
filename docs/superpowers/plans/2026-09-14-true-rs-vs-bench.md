# True RS vs Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill Nifty 50 + NIFTY MIDSML 400 from NSE CM Market Activity archives to >=252 sessions, then persist stock excess RS columns vs those benches without changing peer `rs_percentile`.

**Architecture:** Extend existing MA download/parse (`download_nse_reports.py` + `index_history.py`) for date-walk backfill into `index_daily`; add a pure function that computes stock minus index excess returns; wire into `build_database` / `append_database` indicator materialization; optional thin UI chips later.

**Tech Stack:** Python, DuckDB, pandas, existing NSE report downloader, pytest.

## Global Constraints

- Backfill source = **NSE CM Market Activity only** (no Yahoo as SoT for this work).
- Fail closed: missing index/stock history → NULL excess, never invent.
- Do not change Darvas / VCP / `rs_percentile` gates in v1.
- Canonical index names: `"Nifty 50"`, `"NIFTY MIDSML 400"` (assert against DB).
- Windows-safe paths; ASCII in why_now / notify strings.
- Spec: `docs/superpowers/specs/2026-09-14-true-rs-vs-bench-design.md`

---

### Task 1: Index name contract + coverage probe

**Files:**
- Create: `tests/test_true_rs_bench_contract.py`

**Interfaces:**
- Produces: documented assertions for exact `index_name` strings and minimum session counts

- [ ] **Step 1: Write failing coverage test** (names exist; session count gate)
- [ ] **Step 2: Run test — document current counts (~52) as baseline**
- [ ] **Step 3: Commit** `test: true-RS bench name + coverage contract`

---

### Task 2: NSE MA date-walk downloader

**Files:**
- Modify: `Scripts/download_nse_reports.py` (or Create: `Scripts/backfill_ma_index_archives.py` reusing HTTP helpers)
- Test: `tests/test_ma_backfill_daterange.py`

**Interfaces:**
- Consumes: existing market-activity download/stage conventions
- Produces: `download_ma_for_dates(start, end) -> list[Path]` staged under Input/

- [ ] **Step 1: Write failing test for date URL shape** (`date=04-Aug-2026` style)
- [ ] **Step 2: Implement date-walk + resume + throttle**
- [ ] **Step 3: Dry-run 5 known dates; assert parse returns Nifty 50 + MIDSML rows**
- [ ] **Step 4: Commit** `feat: NSE MA archive date-walk for index backfill`

---

### Task 3: Merge MA history into index_daily >=252 sessions

**Files:**
- Modify: `Scripts/index_history.py` if merge helpers needed
- Modify: `Scripts/append_database.py` or Create: `Scripts/rebuild_index_daily_from_ma.py`
- Test: `tests/test_index_daily_backfill_merge.py`

**Interfaces:**
- Consumes: staged MA via `load_all_market_activity_history` / `parse_market_activity_history`
- Produces: updated `index_daily` with `build_index_features`

- [ ] **Step 1: Failing test — after merge fixture, Nifty 50 session count >= N**
- [ ] **Step 2: Implement idempotent rebuild of index_daily from all staged MA**
- [ ] **Step 3: Run backfill on WIN-AICT until >=252 sessions for both benches**
- [ ] **Step 4: Commit** `feat: index_daily MA backfill to 252+ sessions`

---

### Task 4: Stock excess RS pure function + unit tests

**Files:**
- Create: `Scripts/true_rs.py`
- Test: `tests/test_true_rs.py`

**Interfaces:**
- Produces: `excess_vs_index(stock_close, index_close, sessions) -> Series` (excess * 100, NULL if either leg missing)

- [ ] **Step 1: Write failing tests** (known synthetic series)
- [ ] **Step 2: Implement minimal function**
- [ ] **Step 3: Tests green**
- [ ] **Step 4: Commit** `feat: excess_vs_index helper for true RS`

---

### Task 5: Materialize four columns on indicators_daily

**Files:**
- Modify: `Scripts/build_database.py` (near rs_percentile)
- Modify: `Scripts/append_database.py` if append recomputes indicators
- Modify: migrations / CREATE TABLE lists if explicit
- Test: extend `tests/test_true_rs.py` + live smoke

**Interfaces:**
- Consumes: `excess_vs_index`, `index_daily` closes for both benches
- Produces: `rs_vs_nifty50_21d`, `rs_vs_nifty50_63d`, `rs_vs_midsml400_21d`, `rs_vs_midsml400_63d`

- [ ] **Step 1: Failing test that indicators include columns after compute hook**
- [ ] **Step 2: Wire compute into build/append**
- [ ] **Step 3: Rebuild or append on WIN-AICT; spot-check RELIANCE / a midcap**
- [ ] **Step 4: Commit** `feat: indicators_daily true RS vs Nifty50 and MidSml400`

---

### Task 6: UI chips (optional same PR)

**Files:**
- Modify: `App/ui/stock_drawer.py` inspector header strip
- Modify: `App/pages/action_desk.py` only if inspector already shows RS%ile

- [ ] **Step 1: Show `vs N50 63d` / `vs MS400 63d` when not null**
- [ ] **Step 2: Manual click on AD 360 / inspector**
- [ ] **Step 3: Commit** `feat(ui): show excess RS vs N50/MS400 chips`

---

### Task 7: Verification gate

- [ ] **Step 1: Run** `pytest tests/test_true_rs.py tests/test_true_rs_bench_contract.py tests/test_action_desk.py -q`
- [ ] **Step 2: SQL probe session counts >=252; NULL rate sanity**
- [ ] **Step 3: Push PR #2 with note linking design + plan**

## Out of scope (do not implement in this plan)

- Yahoo SoT backfill
- Sector-index soft RS (phase 2)
- Constituent membership
- Changing screener hard gates to require excess RS
