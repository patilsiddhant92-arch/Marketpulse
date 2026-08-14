# Institution Leaderboard Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore per-institution ordered stock lists and TradingView copy icons in the Deals leaderboard, with compact column sizing.

**Architecture:** Extend the advanced deals read model with a client-symbol latest-date aggregation and a full TradingView-formatted `symbol_list`. Add a short display preview in the Deals page, reuse the existing table copy slot, and add an opt-in compact table mode so other tables are unaffected.

**Tech Stack:** Python 3, DuckDB, pandas, NiceGUI, pytest.

## Global Constraints

- Preserve the default Deals open-path query budget of at most two read queries.
- Apply compact table styling only when explicitly requested by the institution leaderboard.
- Preserve TradingView formatting as `NSE:SYMBOL` with hyphens converted to underscores.
- Do not modify unrelated dirty worktree files.

---

### Task 1: Add ordered institution stock lists to the advanced read model

**Files:**
- Modify: `App/deals_read_model.py`
- Test: `tests/test_deals_desk.py`

**Interfaces:**
- Produces `clients.symbol_list`: comma-separated ordered `NSE:SYMBOL` values.
- Keeps `clients.symbols` as the distinct stock count.

- [ ] **Step 1: Write the failing regression test**

Add an advanced-query test with one institution buying `NEWEST` on 2026-08-10, `MIDDLE` on 2026-08-09, and `OLDEST` on 2026-08-07. Assert:

```python
data = query_deals_advanced(db, side="BUY", min_value_cr=0, lookback_days=10)
clients = data["clients"].set_index("client_name")
assert clients.loc["Fund A", "symbols"] == 3
assert clients.loc["Fund A", "symbol_list"] == "NSE:NEWEST,NSE:MIDDLE,NSE:OLDEST"
```

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run: `& .venv\Scripts\python.exe -m pytest tests\test_deals_desk.py -q`

Expected: FAIL because `symbol_list` is not present in the advanced clients result.

- [ ] **Step 3: Implement the minimal grouped aggregation**

Add a `client_symbol_dates` CTE after `filtered_deals`, grouping by `client_name, symbol` and calculating `max(trade_date)`. Add a client-level `string_agg` ordered by that date descending and symbol ascending. Format each token as `NSE:` plus uppercase symbol with hyphens converted to underscores, then join it to the existing clients aggregation without changing current filters or metrics.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `& .venv\Scripts\python.exe -m pytest tests\test_deals_desk.py -q`

Expected: PASS, including all existing default-path tests.

### Task 2: Restore the copy icon and compact leaderboard layout

**Files:**
- Modify: `App/pages/research/deals.py`
- Modify: `App/app.py`
- Modify: `App/ui/styles.py`
- Test: `tests/test_deals_desk.py`

**Interfaces:**
- `table_from_df(..., compact=False)` remains backward-compatible.
- `compact=True` adds `mp-table-compact` only to the requested table.

- [ ] **Step 1: Write the failing wiring assertions**

Extend the Deals wiring test to assert that the Deals page creates `symbol_preview` and `copy_symbols`, passes `copy_symbols=True`, and passes `compact=True` for the Institution leaderboard.

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run: `& .venv\Scripts\python.exe -m pytest tests\test_deals_desk.py::test_app_wires_deals_to_research_module -q`

Expected: FAIL because the current Deals page disables copying and has no compact mode.

- [ ] **Step 3: Implement the minimal page wiring**

After loading `clients_df`, preserve the full `symbol_list`, derive a five-symbol `symbol_preview` with `+N more`, and add an empty `copy_symbols` column for the existing body slot. Pass visible columns in this order: institution, latest deal, buy, sell, net, active days, copy, stocks. Hide only `symbol_list` and call `table_from_df` with `copy_symbols=True` and `compact=True`.

- [ ] **Step 4: Implement opt-in compact table sizing**

Add `compact: bool = False` to `table_from_df`. Include `symbol_preview` as a text column and label it `Stocks`. For compact tables, assign explicit widths: institution 240px, date 112px, money fields 88px, active days 88px, copy 54px, and stocks 260px. Add `mp-table-compact` to the table class and CSS that prevents the generic table from stretching the Stocks column.

- [ ] **Step 5: Run the focused test and verify it passes**

Run: `& .venv\Scripts\python.exe -m pytest tests\test_deals_desk.py -q`

Expected: PASS.

### Task 3: Verify the local change

**Files:**
- Inspect: `App/deals_read_model.py`
- Inspect: `App/pages/research/deals.py`
- Inspect: `App/app.py`
- Inspect: `App/ui/styles.py`

- [ ] **Step 1: Run the full test suite**

Run: `& .venv\Scripts\python.exe -m pytest -q`

Expected: exit code 0 with zero failed tests.

- [ ] **Step 2: Compile changed Python modules**

Run: `& .venv\Scripts\python.exe -m py_compile App\deals_read_model.py App\pages\research\deals.py App\app.py`

Expected: exit code 0.

- [ ] **Step 3: Inspect the final diff**

Run: `git diff -- App/deals_read_model.py App/pages/research/deals.py App/app.py App/ui/styles.py tests/test_deals_desk.py`

Confirm only the requested query, UI, table sizing, and regression-test changes are present. Leave all unrelated existing worktree changes untouched.
