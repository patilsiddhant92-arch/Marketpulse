# MarketPulse EOD Near-Term Technical Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the near-term technical-desk changes in the approved EOD design while leaving all fundamentals and technofunda scoring on hold.

**Architecture:** Preserve the existing DuckDB EOD pipeline and user/market database split. Extract pure indicator and clientele modules behind compatibility adapters, then update read models and UI progressively so existing focused-v2 data remains authoritative. Use additive schema migrations for new columns and table metadata.

**Tech Stack:** Python 3.14, pandas, NumPy, DuckDB, pytest, NiceGUI, GitHub Actions, PowerShell.

## Global Constraints

- Home remains `focused-v2` until the user explicitly un-holds fundamentals.
- No screener.in scrape, XBRL, yfinance, fundamentals job, `screener_daily`, or technofunda score in this implementation.
- `indicators_daily.atr_14` remains the current SMA ATR; Wilder is additive as `atr_14_wilder`.
- All current `is_hft` names map to `clientele=PROP` and are included by default.
- Marketpulse remains the only product repository; `nsetools-marketpulse` is reference-only.
- Existing uncommitted `Input/` changes are user-owned and must not be deleted or overwritten.

---

### Task 1: Add focused implementation documentation

**Files:**
- Create: `docs/superpowers/specs/2026-08-16-marketpulse-eod-near-term-implementation-design.md`
- Create: `docs/superpowers/plans/2026-08-16-marketpulse-eod-near-term-implementation-plan.md`

- [ ] **Step 1: Review the approved design against the source design**

Confirm that this plan contains only PRs 0, 0b, 1a, 1b, 1c, 2, 3a, 3b, 4, 5, and 9, and explicitly excludes every fundamentals action.

- [ ] **Step 2: Run the baseline suite**

Run: `py -m pytest`

Expected baseline: `78 passed` with only the existing PR-ingestion FutureWarnings.

- [ ] **Step 3: Commit only the two documentation files**

Run:

```powershell
git add docs/superpowers/specs/2026-08-16-marketpulse-eod-near-term-implementation-design.md docs/superpowers/plans/2026-08-16-marketpulse-eod-near-term-implementation-plan.md
git commit -m "docs: plan near-term EOD technical desk implementation"
```

Do not stage or commit any existing `Input/` changes.

### Task 2: Extract and test current indicator formulas

**Files:**
- Create: `Scripts/indicators.py`
- Create: `tests/test_indicators_golden.py`
- Modify: `Scripts/build_database.py`

**Interfaces:**
- `ema(close: pd.Series, span: int) -> pd.Series`
- `rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series`
- `atr_sma(high, low, close, period: int = 14) -> pd.Series`
- `atr_wilder(high, low, close, period: int = 14) -> pd.Series`
- `rvol(volume: pd.Series, window: int = 20) -> pd.Series`
- `rs_quarterly_mix(close: pd.Series) -> pd.Series`
- `distance_below_high(close, high) -> pd.Series`

- [ ] **Step 1: Write failing formula tests**

Cover EMA against pandas `ewm`, Wilder RSI on a hand-computed series, current SMA ATR with `min_periods=5`, Wilder ATR as a separate function, RVOL against a rolling mean, RS missing-history behavior, and distance returning zero for a new high.

- [ ] **Step 2: Run only the new tests and verify the expected missing-module failures**

Run: `py -m pytest tests/test_indicators_golden.py -q`

Expected: collection or assertion failures because `Scripts.indicators` does not yet provide the new functions.

- [ ] **Step 3: Implement the pure functions**

Keep `atr_sma` identical to production:

```python
true_range(high, low, close).rolling(period, min_periods=5).mean()
```

Implement Wilder ATR with `ewm(alpha=1 / period, adjust=False, min_periods=period)`. Do not change production RS or distance semantics in the extraction commit; add corrected helpers separately.

- [ ] **Step 4: Replace local formula bodies in `build_database.py` with calls to the module**

Preserve all current column names and values for `rsi_14`, `atr_14`, `atr_pct`, `rvol`, and `rs_percentile`.

- [ ] **Step 5: Run formula and regression tests**

Run: `py -m pytest tests/test_indicators_golden.py tests/test_candidate_engine.py tests/test_reference_history.py -q`

Expected: all selected tests pass.

### Task 3: Add versioned indicator columns and migration coverage

**Files:**
- Modify: `Scripts/indicators.py`
- Modify: `Scripts/build_database.py`
- Modify: `Scripts/schema.sql`
- Modify: `Scripts/migrations.py`
- Create: `tests/test_indicator_migration.py`

- [ ] **Step 1: Write failing migration tests**

Assert schema version 4 adds `atr_14_wilder`, `atr_pct_wilder`, `distance_below_52w`, `base_quality_score`, and `setup_class` without replacing `atr_14`.

- [ ] **Step 2: Run the migration test and verify it fails before implementation**

Run: `py -m pytest tests/test_indicator_migration.py -q`

Expected: failure because schema version 4 and additive columns are absent.

- [ ] **Step 3: Implement the migration and additive calculations**

Use `CURRENT_SCHEMA_VERSION = 4`. Keep the current SMA ATR in `atr_14`; calculate Wilder ATR into new columns. Calculate `distance_below_52w` as a non-negative drawdown (`0` at or above the high). Rename only new explanatory fields to `base_quality_score`; keep legacy `vcp_score`/`vcp_state` columns for focused-v2 compatibility during the transition.

- [ ] **Step 4: Run migration, indicator, and full regression tests**

Run: `py -m pytest tests/test_indicator_migration.py tests/test_indicators_golden.py tests/test_migrations.py -q` and then `py -m pytest`.

Expected: all tests pass; no test mutates the tracked local database.

### Task 4: Persist and expose PROP clientele

**Files:**
- Create: `Scripts/data/clientele_keywords.yaml`
- Modify: `Scripts/institutional_engine.py`
- Modify: `App/deals_read_model.py`
- Modify: `App/pages/research/deals.py`
- Modify: `Scripts/telegram_deals.py`
- Modify: `Scripts/schema.sql`
- Modify: `Scripts/migrations.py`
- Create: `tests/fixtures/deals/classify_cases_3a.csv`
- Create: `tests/fixtures/deals/classify_cases_3b.csv`
- Modify: `tests/test_institutional_engine.py`
- Modify: `tests/test_deals_desk.py`

- [ ] **Step 1: Write failing classification and default-inclusion tests**

Cover HRTI, QE SECURITIES, MILLENNIUM, DII mutual fund, FII, super investor, obvious corporate, broker exclusion, and individual cases. Assert `clientele`, `clientele_sub`, `is_prop`, `needs_review`, and compatibility keys. Add a deals desk test proving PROP rows appear with default arguments.

- [ ] **Step 2: Run the new tests and confirm they fail against the current classifier**

Run: `py -m pytest tests/test_institutional_engine.py tests/test_deals_desk.py -q`

Expected: new taxonomy and PROP-default assertions fail.

- [ ] **Step 3: Implement the deterministic waterfall**

Use the YAML file as the source for keyword groups. First match PROP, then DII, FII, HNI, constrained CORPORATE, and OTHER. Tag explicit conflicts such as MILLENNIUM with `needs_review=True`. Preserve `tier`, `category`, and `is_hft` outputs for compatibility.

- [ ] **Step 4: Change filtering defaults**

Make `clientele=None` mean all clientele. Keep `exclude_hft` as a deprecated alias: when explicitly true, omit PROP; when omitted, include PROP. Update the Deals checkbox to default off for exclusion and include clientele chips. Ensure Telegram produces ALL, PROP, and INST views using the same classifier.

- [ ] **Step 5: Persist schema fields and run the deal test set**

Add `clientele`, `clientele_sub`, `is_prop`, and `needs_review` through migration 4 and run:

```powershell
py -m pytest tests/test_institutional_engine.py tests/test_deals_desk.py tests/test_indicator_migration.py -q
```

### Task 5: Remove Gemini thematic runtime dependency and compute taxonomy metrics

**Files:**
- Modify: `App/pages/research/sector_intel.py`
- Modify: `App/sector_read_model.py`
- Modify: `Scripts/build_database.py`
- Create: `Scripts/sector_metrics.py`
- Modify: `Scripts/schema.sql`
- Modify: `Scripts/migrations.py`
- Create: `tests/test_sector_metrics.py`
- Modify: `tests/test_sector_intel.py`
- Modify: `tests/test_thematic_tracker.py`

- [ ] **Step 1: Write failing runtime-wiring and metric tests**

Assert Sector Intel imports no `NEXTGEN_TECH_UNIVERSE`, defaults to taxonomy, and computes deterministic breadth, cap-weighted return-vs-Nifty, top-three ADV concentration, setup density, and clientele-separated deal flow from temporary DuckDB fixtures.

- [ ] **Step 2: Run the tests and verify failure against the thematic default**

Run: `py -m pytest tests/test_sector_metrics.py tests/test_sector_intel.py tests/test_thematic_tracker.py -q`

Expected: failures because the current page imports and defaults to the thematic universe.

- [ ] **Step 3: Implement `Scripts/sector_metrics.py` and `sector_metrics_daily`**

Use as-of `security_reference_daily.market_cap_cr`, `index_daily` Nifty 50 returns, and taxonomy fields from `stocks_master`. Persist one row per date/level/group. Do not invent sector-index constituents or load example theme YAML.

- [ ] **Step 4: Make Sector Intel taxonomy-only**

Remove the thematic toggle and runtime import, switch the title/copy to computed taxonomy metrics, and retain the stock drawer/deep-dive behavior where possible. Leave `App/thematic_read_model.py` unused by the runtime; existing historical tests may be replaced with a runtime-removal assertion.

- [ ] **Step 5: Run sector and full regression tests**

Run: `py -m pytest tests/test_sector_metrics.py tests/test_sector_intel.py tests/test_thematic_tracker.py -q` and then `py -m pytest`.

### Task 6: Fixed-width dark terminal table

**Files:**
- Create: `App/ui/table.py`
- Modify: `App/app.py`
- Modify: `App/ui/styles.py`
- Create: `tests/test_table_spec.py`

- [ ] **Step 1: Write failing table-spec tests**

Assert `SWING_COLUMNS` totals 768px, `SCREENER_COLUMNS` totals 1040px, every column has an explicit positive width, and the rendered table CSS uses `table-layout: fixed` without a `why_now` column.

- [ ] **Step 2: Run the new tests and confirm the current auto-layout implementation fails**

Run: `py -m pytest tests/test_table_spec.py -q`

Expected: module/spec or assertion failures because no fixed spec exists.

- [ ] **Step 3: Implement `ColumnSpec`, specs, and fixed renderer**

Move the stable dataframe-to-row/column logic into `App/ui/table.py`. Keep `table_from_df` as a compatibility wrapper that delegates to the new renderer. Use the approved column widths, 28px rows, compact padding, sticky headers, and drawer/tooltip for `why_now`.

- [ ] **Step 4: Apply dark terminal tokens and remove gradients from the active table path**

Update `App/ui/styles.py` to the approved dark tokens, fixed table CSS, solid heat fills, and terminal typography. Keep non-active legacy page styles only where necessary for compatibility.

- [ ] **Step 5: Run UI contract tests and full regression tests**

Run: `py -m pytest tests/test_table_spec.py tests/test_today_premium.py tests/test_ui_recovery_contracts.py -q` and then `py -m pytest`.

### Task 7: Thin router and focused-v2 Screener tab

**Files:**
- Create: `App/pages/screener.py`
- Modify: `App/app.py`
- Modify: `App/candidates_page.py`
- Modify: `tests/test_today_premium.py`
- Modify: `tests/test_ui_recovery_contracts.py`

- [ ] **Step 1: Write failing navigation/read-model tests**

Assert the active tab labels are Screener, Sectors, Deals, Portfolio, and Health; Screener calls `load_decision_snapshot` only; and the three focused-v2 chips select Prepare, Observe, and Blocked/DIAG rows without importing fundamentals.

- [ ] **Step 2: Run the tests and confirm current seven-tab navigation fails the new contract**

Run: `py -m pytest tests/test_today_premium.py tests/test_ui_recovery_contracts.py -q`

Expected: failure because Today/Candidates/Momentum/Sector Intel/Data Health are still separate active tabs.

- [ ] **Step 3: Implement `App/pages/screener.py` using focused-v2 only**

Reuse `load_decision_snapshot`, the existing eligibility/status fields, the stock drawer, and `SWING_COLUMNS`. Do not create or query `screener_daily`.

- [ ] **Step 4: Update `app.py` navigation and quarantine legacy pages**

Keep the market/user DB split and current portfolio/deals/health builders. Route the active five tabs through the new table and put unused labs behind `MP_LEGACY_PAGES=1` rather than deleting code in the same change.

- [ ] **Step 5: Run UI tests, import/compile checks, and the full suite**

Run:

```powershell
py -m py_compile App/app.py App/pages/screener.py App/ui/table.py Scripts/indicators.py Scripts/sector_metrics.py
py -m pytest
```

### Task 8: CI and input-artifact hygiene

**Files:**
- Modify: `.github/workflows/eod.yml`
- Create: `.github/workflows/test.yml`
- Modify: `.gitignore`

- [ ] **Step 1: Write a workflow contract test**

Assert the PR workflow invokes `pytest`, the EOD workflow does not use `git add -A Input`, and archive/download artifacts are ignored while `Input/daily` remains available locally.

- [ ] **Step 2: Run the contract test and verify current workflow failure**

Run: `py -m pytest tests/test_ci_contract.py -q`

Expected: failure because the test workflow is absent and EOD commits all Input files.

- [ ] **Step 3: Implement the workflows and ignore rules**

Add a PR pytest workflow, replace broad Input commits with artifact upload/cache behavior, and ignore only archive/download artifacts. Do not remove existing local files or alter the user's tracked daily changes.

- [ ] **Step 4: Run workflow contract tests and the final suite**

Run: `py -m pytest tests/test_ci_contract.py -q` and then `py -m pytest`.

### Task 9: Final verification and local handoff

**Files:**
- No additional production files.

- [ ] **Step 1: Run focused checks**

Run:

```powershell
py -m pytest tests/test_indicators_golden.py tests/test_indicator_migration.py tests/test_institutional_engine.py tests/test_deals_desk.py tests/test_sector_metrics.py tests/test_table_spec.py tests/test_ci_contract.py -q
```

- [ ] **Step 2: Run the complete suite**

Run: `py -m pytest`

Expected: all tests pass with no new warnings attributable to the implementation.

- [ ] **Step 3: Inspect the final diff and preserve unrelated user changes**

Run: `git status --short` and `git diff --stat`. Confirm no `Input/` file was staged or modified by the implementation.

- [ ] **Step 4: Report local results**

Report changed files, tests passed, any known compatibility shims, and the fact that nothing was pushed remotely.

