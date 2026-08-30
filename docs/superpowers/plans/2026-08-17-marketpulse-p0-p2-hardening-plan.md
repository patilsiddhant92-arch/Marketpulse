# MarketPulse P0–P2 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved P0, P1, and P2 audit roadmap so MarketPulse presents truthful EOD context, actionable candidate states, explicit risk, and measurable signal evidence.

**Architecture:** Add pure read-model helpers around the existing DuckDB schema, then wire the helpers into the active NiceGUI pages. Preserve the read-only market database/user database split, use additive migrations for new contracts, and keep compatibility aliases for legacy focused-v2 columns.

**Tech Stack:** Python, pandas, NumPy, DuckDB, pytest, NiceGUI, GitHub Actions, PowerShell.

## Global Constraints

- Sector rotation is full-universe; ₹1,000 Cr filters stock candidates only.
- Risk-Off rows may remain visible as Observe, but no Risk-Off row may be shown as Prepare.
- A stale market snapshot is non-actionable and must be reported identically by header, Health, and Screener.
- No invented fundamentals; expose an explicit unavailable state until an auditable point-in-time provider exists.
- User portfolio writes stay in the isolated user database.
- Existing uncommitted Input files are user-owned and must not be deleted or staged.

---

### Task 1: Shared freshness and non-actionable stale state

**Files:**
- Create: `App/market_status.py`
- Modify: `Scripts/pipeline_health.py`
- Modify: `App/app.py`
- Modify: `App/data_health_page.py`
- Modify: `App/pages/screener.py`
- Test: `tests/test_market_status.py`
- Modify: `tests/test_pipeline_recovery.py`

**Interfaces:**
- `expected_nse_session(reference_date: date | None = None, holidays: set[date] | None = None) -> date`
- `load_market_status(db_path: Path, status_path: Path | None, today: date | None = None) -> MarketStatus`
- `MarketStatus.actionable: bool`, `.database_date`, `.decision_date`, `.status`, `.message`

- [ ] Write failing tests for weekend handling, a weekday database one session behind, and a matching database/decision session.
- [ ] Run `py -m pytest tests/test_market_status.py tests/test_pipeline_recovery.py -q` and verify the new tests fail.
- [ ] Implement the pure session/status helpers; pass the expected session into `assess_pipeline`.
- [ ] Wire the header, Health, and Screener to the same status object; render a visible stale/non-actionable banner.
- [ ] Run the focused tests and then the existing pipeline tests.

### Task 2: Candidate gate, explainability, and corrected indicator semantics

**Files:**
- Modify: `Scripts/candidate_engine.py`
- Modify: `Scripts/decision_policy.py`
- Modify: `Scripts/build_database.py`
- Modify: `Scripts/indicators.py`
- Modify: `Scripts/schema.sql`
- Modify: `Scripts/migrations.py`
- Modify: `App/pages/screener.py`
- Test: `tests/test_candidate_engine.py`
- Test: `tests/test_candidate_semantics.py`
- Modify: `tests/test_indicator_migration.py`

**Interfaces:**
- `DecisionPolicy.block_prepare_in_risk_off: bool = True`
- `calculate_risk_geometry(..., max_reward_to_risk: float = 10.0)` returns `geometry_valid=False` and `geometry_warning` for outliers.
- New persisted columns: `atr_pct_primary`, `distance_to_high_pct_corrected`, `rs_percentile_primary`, `geometry_warning`.

- [ ] Write failing tests proving Risk-Off converts a would-be Prepare row to Observe, new highs have zero high-distance, short history does not receive a zero-filled RS score, and outlier R:R is invalid.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Implement the minimum corrected formulas and versioned columns; preserve legacy aliases for reads.
- [ ] Add the candidate context fields to the Screener table and separate Prepare from Observe.
- [ ] Run candidate, indicator, migration, and full regression tests.

### Task 3: Taxonomy-level Sector Intel and full-universe contracts

**Files:**
- Modify: `App/sector_read_model.py`
- Modify: `App/pages/research/sector_intel.py`
- Modify: `Scripts/sector_metrics.py`
- Modify: `Scripts/build_database.py`
- Test: `tests/test_sector_taxonomy_tree.py`
- Test: `tests/test_sector_runtime_wiring.py`
- Test: `tests/test_sector_universe_contract.py`

- [ ] Write failing tests for 12/22/59/186 level counts, stock-only market-cap eligibility, strict versus branch status filtering, and missing `sector_metrics_daily` reporting.
- [ ] Run the new tests and verify failure.
- [ ] Add a level selector, level-specific counts, strict/branch status mode, and full-universe/stock-eligibility copy.
- [ ] Make missing sector metrics a visible degraded state rather than a silent fallback.
- [ ] Run sector tests and full regression tests.

### Task 4: Stock 360 and Deals decision transparency

**Files:**
- Modify: `App/ui/stock_drawer.py`
- Modify: `App/deals_read_model.py`
- Modify: `App/pages/research/deals.py`
- Modify: `Scripts/institutional_engine.py`
- Modify: `Scripts/schema.sql`
- Modify: `Scripts/migrations.py`
- Test: `tests/test_stock_360_contract.py`
- Modify: `tests/test_deals_desk.py`
- Modify: `tests/test_deal_clientele_v2.py`

- [ ] Write failing tests for Stock 360 action fields, transparent Deals universe gates, persisted clientele fields, and null-market-cap rejection.
- [ ] Run the focused tests and verify failure.
- [ ] Add a Stock 360 summary containing action state, market regime, sector/industry state, event risk, trigger, invalidation, R:R, and data freshness.
- [ ] Make Deals display buy/sell/net, client types, market-cap/EMA200 gates, and flow-universe labels; reject missing market cap by default.
- [ ] Run focused and full tests.

### Task 5: Portfolio risk desk and sizing guidance

**Files:**
- Create: `App/portfolio_read_model.py`
- Modify: `App/user_data_service.py`
- Modify: `App/app.py`
- Test: `tests/test_portfolio_read_model.py`
- Modify: `tests/test_portfolio_commands.py`

- [ ] Write failing tests for portfolio heat, sector concentration, missing stop warnings, and quantity guidance from account equity/risk budget.
- [ ] Run the new tests and verify failure.
- [ ] Implement pure portfolio summary/sizing functions with explicit account-equity and max-risk inputs.
- [ ] Expose planned risk, max risk %, account equity, heat, concentration, and sizing guidance in the Portfolio UI.
- [ ] Run portfolio tests and full regression tests.

### Task 6: P2 evidence, CI, and explicit fundamentals boundary

**Files:**
- Create: `App/evidence_read_model.py`
- Modify: `App/data_health_page.py`
- Modify: `App/ui/styles.py`
- Modify: `.github/workflows/eod.yml`
- Modify: `.github/workflows/test.yml`
- Modify: `App/app.py`
- Test: `tests/test_evidence_read_model.py`
- Modify: `tests/test_ci_contract.py`
- Modify: `tests/test_ui_recovery_contracts.py`

- [ ] Write failing tests for outcome summaries, empty-evidence handling, CI pytest invocation, and fundamentals-unavailable copy.
- [ ] Run the focused tests and verify failure.
- [ ] Implement outcome summaries by score version, regime, state, and horizon; add an Evidence panel to Health.
- [ ] Add explicit fundamentals-unavailable status and provider boundary copy; remove misleading “technofunda” wording from active decision copy.
- [ ] Add CI pytest and compile checks without staging Input files.
- [ ] Run focused and full regression tests.

### Task 7: Live verification and handoff

**Files:**
- No additional production files.

- [ ] Run `py -m pytest -q` and compile all active modules.
- [ ] Start/reload the app and inspect Screener, Momentum, Sectors, Deals, Portfolio, Health, Stock 360, and open dropdowns in Codex browser.
- [ ] Verify stale state, Prepare/Observe semantics, sector counts, dark controls, Deals labels, portfolio heat, and Evidence output.
- [ ] Inspect `git diff --stat` and ensure user-owned Input files were not staged or deleted.
- [ ] Request a final code review and report any explicitly deferred items.
