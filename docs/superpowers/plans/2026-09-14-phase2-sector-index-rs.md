# Phase 2: Sector/Thematic Index RS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Persist official CANONICAL_44 membership, map each stock to one index as-is, materialize stock-vs-index and index-vs-bench excess RS, default UI bench MidSml400 with Nifty50 selectable.

**Architecture:** Seed `index_constituents` from Index Desk CSV → deterministic mapper → reuse `excess_vs_index` → wire build/append + one-shot materialize → Stock 360 / Sector Intel bench toggle.

**Tech stack:** Python, DuckDB, pandas, pytest, existing `Scripts/true_rs.py`, `App/thematic_engine.py`.

**Spec:** `docs/superpowers/specs/2026-09-14-phase2-sector-index-rs-design.md`

## File map

| File | Role |
|------|------|
| `Input/reference/mp44_membership.csv` | Seed membership (copy from Index Desk) |
| `Scripts/index_constituents.py` | Load CSV, ensure table, mapper `resolve_sector_index(symbol, …)` |
| `Scripts/true_rs.py` | Extend with sector-index + index-vs-bench helpers |
| `Scripts/materialize_sector_index_rs.py` | One-shot live DB materialize |
| `Scripts/build_database.py` | Hook after true RS attach |
| `App/ui/stock_drawer.py` | Bench toggle + vs sector-index chip |
| `App/thematic_engine.py` or sector read model | Index-vs-bench on leaderboard |
| `tests/test_index_constituents.py` | Load + mapper determinism |
| `tests/test_sector_index_rs.py` | Excess + columns |

---

### Task 1: Seed membership into repo + DuckDB

**Files:** Create `Input/reference/mp44_membership.csv`, `Scripts/index_constituents.py`, `tests/test_index_constituents.py`

- [ ] **Step 1:** Copy Index Desk `mp44_membership.csv` into `Input/reference/`.
- [ ] **Step 2:** Implement `ensure_index_constituents(con, csv_path)` → table with category join from `CANONICAL_44_INDICES`.
- [ ] **Step 3:** Test: 44 distinct `mp_index_name`, row count ≥ 1200, RELIANCE maps into expected oil/energy set.
- [ ] **Step 4:** Commit `feat: seed index_constituents from official mp44 membership`

### Task 2: Deterministic stock → index mapper

**Files:** `Scripts/index_constituents.py`, tests

- [ ] **Step 1:** Failing tests for: single membership; multi Sectoral vs Thematic; Pvt Bank vs Bank; none → soft fallback stub; none+no soft → NULL.
- [ ] **Step 2:** Implement `resolve_sector_index(symbol, membership_df, master_row=None, soft_map=INDEX_THEMATIC_MAP) -> str | None`.
- [ ] **Step 3:** Tests green; commit `feat: resolve_sector_index membership-primary mapper`

### Task 3: Stock-vs-mapped-index excess columns

**Files:** `Scripts/true_rs.py`, `Scripts/build_database.py`, `Scripts/materialize_sector_index_rs.py`, tests

- [ ] **Step 1:** Add `attach_sector_index_rs(indicators, index_daily, membership)` → sets `sector_index_name`, `rs_vs_sector_index_21d/63d`.
- [ ] **Step 2:** Wire into `calc_indicators` after Phase 1 true RS (or materialize-only first if build cost high).
- [ ] **Step 3:** One-shot materialize on WIN-AICT; spot-check INFY / HDFCBANK / RELIANCE.
- [ ] **Step 4:** Commit `feat: rs_vs_sector_index_21d/63d on indicators_daily`

### Task 4: Index-vs-bench RS for all 44

**Files:** `Scripts/true_rs.py` or `Scripts/index_bench_rs.py`, thematic leaderboard consumer, tests

- [ ] **Step 1:** `compute_index_bench_rs(index_daily, benches=(Nifty50, MidSml400), sessions=(21,63))` → frame for 44 names.
- [ ] **Step 2:** Persist `index_bench_rs_daily` on build/materialize OR compute live in thematic board (prefer persist for AD speed).
- [ ] **Step 3:** Assert latest date: 44 non-null `rs_vs_midsml400_63d`.
- [ ] **Step 4:** Commit `feat: index_bench_rs_daily vs N50 and MidSml400`

### Task 5: UI bench toggle + chips

**Files:** `App/ui/stock_drawer.py`, Sector Intel / thematic UI as needed, `Scripts/config.py` labels

- [ ] **Step 1:** Bench toggle MidSml400 (default) | Nifty 50; drive which bench chips display.
- [ ] **Step 2:** Show `vs {sector_index} 63d` when `sector_index_name` present.
- [ ] **Step 3:** Thematic/Sector Intel columns use selected bench excess.
- [ ] **Step 4:** Commit `feat(ui): MidSml default bench toggle + sector-index RS chips`

### Task 6: Verification gate

- [ ] **Step 1:** `pytest tests/test_index_constituents.py tests/test_sector_index_rs.py tests/test_true_rs.py -q`
- [ ] **Step 2:** Live smoke: membership count, mapper coverage %, sample chips.
- [ ] **Step 3:** Push to PR #2; note FinSrv25/50 watchout for next Index Desk refresh.

## Global constraints

- Fail closed; never invent constituents or excess.
- Membership wins over soft map.
- ASCII in notify / why_now strings.
- Windows-safe paths; work on WIN-AICT when cloud agents unavailable.
