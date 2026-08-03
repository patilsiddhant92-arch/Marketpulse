# MarketPulse Focused Watchlist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the focused decision workflow from `2026-08-03-marketpulse-focused-watchlist-design.md`, including point-in-time data, canonical candidates, persistent watchlist states, risk geometry, signal outcomes, and decision-first UI.

**Architecture:** Add focused, importable services under `Scripts/` and a runtime migration command rather than putting new business logic into `App/app.py`. The existing tables remain compatible; new tables are additive and are materialized by the full/incremental pipelines. The UI consumes a shared read/write service and keeps specialist pages available under Research.

**Tech Stack:** Python 3.12+, pandas, DuckDB, NiceGUI, pytest, existing NSE CSV/ZIP inputs.

## Global Constraints

- Historical joins must use the latest reference record where `reference.effective_date <= indicator.trade_date`.
- The first implementation will not replace NiceGUI or DuckDB.
- Database migrations must not run implicitly from normal UI startup.
- Candidate score weights are versioned and every displayed score includes pillar contributions and data-quality flags.
- Risk is a penalty/gate, not an alpha score.
- The model is research-only and is not included in the production candidate score.
- User-owned journal and watchlist data must survive rebuilds.
- Existing research and journal workflows remain available after navigation restructuring.
- All production changes require a failing test before implementation and green regression verification.

---

## Task 1: Establish test harness and migration primitives

**Files:**
- Create: `Scripts/migrations.py`
- Create: `Scripts/schema.sql`
- Create: `tests/conftest.py`
- Create: `tests/test_migrations.py`
- Modify: `Scripts/config.py`
- Modify: `Scripts/requirements.txt`

**Interfaces:**
- Produces `run_migrations(db_path: Path) -> None`.
- Produces `schema_version(db_path: Path) -> int`.
- Produces additive tables: `schema_migrations`, `security_reference_daily`, `corporate_actions`, `price_adjustment_factors`, `index_daily`, `security_events`, `candidate_daily`, `watchlist_candidates`, `signal_ledger`, `signal_outcomes`, `ingestion_batches`, and `ingested_reports`.

- [ ] **Step 1: Write the failing migration tests** for a new DuckDB file, idempotent reruns, required columns, and preservation of an existing `trade_journal` table.
- [ ] **Step 2: Run `py -m pytest tests/test_migrations.py -q` and confirm failure because the migration module/tables do not exist.**
- [ ] **Step 3: Implement schema versioning with one transaction per migration and additive `CREATE TABLE IF NOT EXISTS` statements.**
- [ ] **Step 4: Add the test-only dependency declaration and shared temporary database fixture.**
- [ ] **Step 5: Run the focused tests and then `py -m pytest -q`; keep any pre-existing failures documented rather than hiding them.**
- [ ] **Step 6: Commit `test: add database migration contract`.**

## Task 2: Point-in-time reference history and corporate-action factors

**Files:**
- Create: `Scripts/reference_history.py`
- Create: `Scripts/corporate_actions.py`
- Create: `tests/test_reference_history.py`
- Create: `tests/test_corporate_actions.py`
- Modify: `Scripts/build_database.py`
- Modify: `Scripts/append_database.py`

**Interfaces:**
- `build_security_reference_history(mcap, bands, pe, high52) -> pd.DataFrame` returns one row per symbol/effective date with source dates and checksum.
- `asof_reference(reference, trade_dates) -> pd.DataFrame` performs a backward-only as-of join.
- `build_adjustment_factors(actions, prices) -> pd.DataFrame` returns `symbol, trade_date, price_factor, volume_factor`.
- `apply_adjustment_factors(prices, factors) -> pd.DataFrame` adjusts OHLC and volume without changing raw source columns.

- [ ] **Step 1: Write failing tests proving a later 52-week file cannot alter an earlier date, duplicate reference rows collapse by checksum, and a split factor prevents a false return spike.**
- [ ] **Step 2: Run both focused test files and verify the expected missing-function failures.**
- [ ] **Step 3: Implement normalized reference loaders, date-keyed as-of joins, corporate-action normalization, and cumulative price/volume factors.**
- [ ] **Step 4: Integrate the reference table into the rebuild/append data frames so `high_52w`, `low_52w`, market cap, PE, and band values are joined by trade date.**
- [ ] **Step 5: Add reconciliation assertions that no reference effective date exceeds its indicator trade date.**
- [ ] **Step 6: Run the focused and full test suites; commit `feat: make historical references point in time`.**

## Task 3: Market Activity index parser and event-risk model

**Files:**
- Create: `Scripts/index_history.py`
- Create: `Scripts/events.py`
- Create: `tests/test_index_history.py`
- Create: `tests/test_events.py`
- Modify: `Scripts/config.py`
- Modify: `Scripts/build_database.py`
- Modify: `Scripts/download_nse_reports.py`

**Interfaces:**
- `parse_market_activity(path: Path, trade_date: date) -> pd.DataFrame` returns the `index_daily` columns defined in the design.
- `build_index_features(index_daily) -> pd.DataFrame` adds 5/20/63/126/252-session returns, EMAs, distance-to-EMA, highs, volatility, and trend state.
- `normalize_events(rows) -> pd.DataFrame` validates event types and deduplicates by the schema key.
- `event_risk_for_date(events, symbol, trade_date) -> dict` returns next-event dates, session distances, and `event_risk`.

- [ ] **Step 1: Write failing parser tests for common NSE Market Activity layouts, malformed rows, and date-keyed deduplication.**
- [ ] **Step 2: Write failing event tests for 1/3/5/10-session windows and no-event behavior.**
- [ ] **Step 3: Implement parsers tolerant of header rows and numeric commas while rejecting HTML/error content.**
- [ ] **Step 4: Materialize index and event tables during rebuild and append when source files are present; empty valid inputs produce empty tables rather than failing the build.**
- [ ] **Step 5: Add benchmark/sector index mapping from the existing sector mapping with a stable unmapped value.**
- [ ] **Step 6: Run focused tests and commit `feat: add index context and event risk`.**

## Task 4: Canonical candidate engine and risk geometry

**Files:**
- Create: `Scripts/candidate_engine.py`
- Create: `tests/test_candidate_engine.py`
- Modify: `Scripts/build_database.py`
- Modify: `Scripts/config.py`

**Interfaces:**
- `SCORE_VERSION = "focused-v1"`.
- `score_candidates(indicators, breadth, rotations, deals, index_features, events, master, as_of) -> pd.DataFrame` returns the complete `candidate_daily` schema.
- `calculate_risk_geometry(row: Mapping[str, Any]) -> dict` returns trigger, invalidation, first resistance, distance, initial risk, and reward-to-risk.
- `classify_market_gate(breadth_row, index_rows, rotation_rows) -> str` returns Constructive, Selective, Defensive, or Risk-Off.
- `explain_candidate(row) -> tuple[str, str, str]` returns why-now, latest-change, and risk-summary text.

- [ ] **Step 1: Write failing unit tests for pillar weights, score reproducibility, market gate states, valid/invalid risk geometry, and no double counting of the existing VCP components.**
- [ ] **Step 2: Run the focused tests and confirm they fail before the scoring service exists.**
- [ ] **Step 3: Implement normalized leadership, setup, participation, context, and risk-quality pillars using the design weights: 30/25/20/15/10.**
- [ ] **Step 4: Implement trigger/invalidation selection, setup age, state proposal, explanations, and data-quality flags.**
- [ ] **Step 5: Add deterministic rank-overall and rank-in-sector ordering with stable symbol tie-breaking.**
- [ ] **Step 6: Materialize `candidate_daily` after each successful build/append and verify stored total equals pillar contributions.**
- [ ] **Step 7: Run focused and regression tests; commit `feat: add canonical candidate scoring`.**

## Task 5: Persistent watchlist lifecycle and shared decision service

**Files:**
- Create: `Scripts/watchlist_service.py`
- Create: `Scripts/query_service.py`
- Create: `tests/test_watchlist_service.py`
- Create: `tests/test_query_service.py`
- Modify: `Scripts/migrations.py`
- Modify: `Scripts/build_database.py`
- Modify: `Scripts/append_database.py`

**Interfaces:**
- `transition_candidate(previous, current) -> tuple[str, str]` returns the next lifecycle state and auditable reason.
- `persist_candidate_snapshot(db_path, candidate_rows, trade_date) -> None` upserts candidate snapshots without deleting history.
- `load_today_snapshot(db_path, limit=15) -> pd.DataFrame` returns the focused list and market context.
- `load_watchlist(db_path, states=None) -> pd.DataFrame` returns persistent lifecycle rows.
- `invalidate_query_cache(db_path) -> None` invalidates the database-version cache after a write.

- [ ] **Step 1: Write failing lifecycle tests covering Observe→Prepare→Triggered→Invalidated, Expired/Removed/Completed, deterministic reasons, and temporary filter failure.**
- [ ] **Step 2: Implement lifecycle transitions and an append-only state history JSON payload.**
- [ ] **Step 3: Add query-service connection reuse, parameterized filters, pagination, and cache keys based on DB mtime/status version.**
- [ ] **Step 4: Integrate candidate snapshots into rebuild/append and preserve user-owned watchlist rows during full replacement.**
- [ ] **Step 5: Run focused tests and commit `feat: persist watchlist lifecycle`.**

## Task 6: Signal ledger and forward outcomes

**Files:**
- Create: `Scripts/signal_service.py`
- Create: `Scripts/outcomes.py`
- Create: `tests/test_signal_service.py`
- Create: `tests/test_outcomes.py`
- Modify: `Scripts/build_database.py`
- Modify: `Scripts/append_database.py`

**Interfaces:**
- `update_signal_ledger(existing, candidate_rows, trade_date) -> pd.DataFrame` creates/updates signal IDs and state history.
- `future_session_values(prices, symbol, as_of, horizons=(5,10,20,60)) -> dict` uses exact future trading sessions.
- `calculate_outcome(prices, signal) -> dict` returns forward returns, MFE, MAE, trigger-to-invalidation, and timing fields.
- `summarize_outcomes(outcomes, group_fields) -> pd.DataFrame` groups by setup, score bucket, regime, sector, liquidity, cap, event risk, and setup age.

- [ ] **Step 1: Write failing tests for signal creation/update/invalidation and exact future-session window boundaries.**
- [ ] **Step 2: Write failing tests proving unresolved windows are excluded and MFE/MAE do not read outside the requested horizon.**
- [ ] **Step 3: Implement the ledger and outcome calculations with point-in-time snapshots.**
- [ ] **Step 4: Materialize `signal_ledger`, `signal_outcomes`, and an outcome summary view during the daily build.**
- [ ] **Step 5: Add date-grouped walk-forward validation helpers and baseline comparison metrics for research-only model outputs.**
- [ ] **Step 6: Run focused tests and commit `feat: add signal outcomes and walk-forward metrics`.**

## Task 7: Manifest-aware ingestion and transactional pipeline integration

**Files:**
- Create: `Scripts/ingestion_manifest.py`
- Create: `Scripts/transactional_append.py`
- Create: `Scripts/reconcile_database.py`
- Create: `tests/test_ingestion_manifest.py`
- Create: `tests/test_transactional_append.py`
- Create: `tests/test_reconciliation.py`
- Modify: `Scripts/daily_pipeline.py`
- Modify: `Scripts/append_database.py`
- Modify: `download.bat`
- Modify: `Append_MarketPulse.bat`
- Create: `Rebuild_MarketPulse.bat`

**Interfaces:**
- `read_manifest(path: Path) -> Manifest` validates schema and checksums.
- `discover_prepared_sessions(downloads_dir, database_date) -> SessionPlan` identifies validated, missing, and gap dates.
- `append_batch(db_path, session_plan) -> None` performs one DuckDB transaction and rolls back all writes on failure.
- `reconcile_databases(incremental_db, rebuilt_db, tables, tolerance=1e-9) -> list[str]` returns unexplained differences.

- [ ] **Step 1: Write failing tests for manifest idempotency, missing-set rejection, gap rejection, changed checksum rejection, and rollback on injected failure.**
- [ ] **Step 2: Implement manifest readers and ingestion metadata tables without changing the accepted database.**
- [ ] **Step 3: Implement transactional append using staged frames and a single commit, including candidate/watchlist/signal tables.**
- [ ] **Step 4: Add full-versus-incremental reconciliation for identifiers, nulls, booleans, categories, and floating values.**
- [ ] **Step 5: Update batch commands so download preparation and database append remain separate actions; add explicit full rebuild entry point.**
- [ ] **Step 6: Run all ingestion/reconciliation tests on temporary DuckDBs and commit `feat: add manifest-aware transactional ingestion`.**

## Task 8: Decision-first application shell and pages

**Files:**
- Create: `App/query_service.py`
- Create: `App/components.py`
- Create: `App/pages/today.py`
- Create: `App/pages/watchlist.py`
- Create: `App/pages/research.py`
- Create: `App/pages/market.py`
- Create: `App/pages/setups.py`
- Create: `App/pages/deals.py`
- Create: `App/pages/stock_detail.py`
- Create: `App/pages/journal.py`
- Create: `tests/test_app_queries.py`
- Modify: `App/app.py`
- Modify: `Scripts/config.py`

**Interfaces:**
- `render_today(db_path: Path) -> None` renders gate, changes, and at most 15 candidates.
- `render_watchlist(db_path: Path) -> None` renders persistent states and transition details.
- `render_research(db_path: Path) -> None` links to existing specialist pages.
- `load_app_snapshot(db_path: Path) -> dict[str, pd.DataFrame]` loads only Today-required data.

- [ ] **Step 1: Write failing query tests for Today-only loading, 15-row default limit, state persistence, and hidden Research accessibility.**
- [ ] **Step 2: Extract shared data access and visual helpers from `App/app.py` without changing existing query semantics.**
- [ ] **Step 3: Implement the Today page with readiness, gate, changes, focused candidates, score pillars, risk geometry, and event warnings.**
- [ ] **Step 4: Implement Watchlist state filtering and Research links while preserving existing specialist render functions.**
- [ ] **Step 5: Change navigation to Today/Watchlist/Research as the primary workflow and lazy-load all specialist page content.**
- [ ] **Step 6: Run an import/startup smoke test and UI query tests; commit `feat: add decision-first application workflow`.**

## Task 9: Classifier research corrections and final verification

**Files:**
- Create: `Scripts/validation.py`
- Create: `tests/test_validation.py`
- Modify: `Scripts/train_vcp_classifier.py`
- Modify: `Scripts/build_database.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing tests for maximum-future-high labels, date-grouped splits, no overlap between train/test dates, and baseline metrics.**
- [ ] **Step 2: Correct labels and expanding-window validation; keep model probability out of `candidate_daily.total_score`.**
- [ ] **Step 3: Add validation commands for point-in-time leakage, candidate consistency, incremental/full reconciliation, and unresolved outcome exclusion.**
- [ ] **Step 4: Run `py -m pytest -q`, `py -m py_compile Scripts/*.py App/*.py`, and a read-only schema/build smoke test against the existing database.**
- [ ] **Step 5: Run the application import/startup smoke test and capture measured performance for append, rebuild, and first Today query.**
- [ ] **Step 6: Commit `test: add focused-watchlist verification suite`.**

## Verification and Handoff

- [ ] Inspect `git diff --check` and `git status --short`.
- [ ] Confirm no migration runs implicitly from normal UI startup.
- [ ] Confirm the existing `trade_journal` rows and user-owned watchlist rows survive a rebuild in a temporary database test.
- [ ] Confirm all new tables have primary-key/unique constraints matching the design.
- [ ] Confirm no claim of complete implementation is made until the full test and reconciliation commands pass.
