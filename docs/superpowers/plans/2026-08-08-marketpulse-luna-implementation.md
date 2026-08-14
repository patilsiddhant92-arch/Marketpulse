# MarketPulse Swing-Trader OS — Luna Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert MarketPulse from a collection of EOD reports into a reliable personal swing-trading decision system that produces a small, explainable action queue, manages open-position risk, preserves historical outcomes, and uses the NSE inputs already downloaded.

**Architecture:** Keep Python, NiceGUI, pandas, and DuckDB. Make `App/app.py` a thin composition root; move decision logic, user-data writes, and UI components into focused modules. Introduce a versioned `focused-v2` decision policy in shadow mode, persist all daily candidate states and outcomes, and move manual portfolio/journal data into a separate user database so market-data rebuilds cannot destroy it.

**Tech Stack:** Python 3.12+, NiceGUI 3.13, DuckDB, pandas, NumPy, pytest, NSE CSV/TXT/ZIP reports, Windows PowerShell/batch launchers.

**Source documents:**

- `docs/superpowers/specs/2026-08-03-marketpulse-focused-watchlist-design.md`
- Live Codex browser audit completed 2026-08-08 at desktop, default, and 390px mobile widths.
- Current baseline: `29 passed, 1 failed`; the failure is the stale legacy-navigation assertion in `tests/test_app_queries.py`.

## Global Constraints

- Do not replace NiceGUI or DuckDB in this program.
- Never edit, delete, rename, or regenerate files under `Input/` as part of tests.
- Never run a full rebuild against the only copy of `Database/marketpulse.duckdb`; use a temporary database or a verified backup.
- Manual portfolio, portfolio-event, journal, settings, and annotation data must live in `Database/marketpulse_user.duckdb` after migration.
- Normal UI startup must be read-only against the market database and must not run schema migrations.
- Default the application host to `127.0.0.1`; non-loopback exposure is out of scope until authentication is designed and tested.
- `focused-v1` remains available for comparison until `focused-v2` passes the release gates in Task 11.
- Every decision score is bounded to `0..100`, versioned, and reproducible from stored pillar contributions.
- A candidate cannot enter `Prepare` without valid trigger, invalidation, risk, liquidity, and reward-to-risk geometry.
- A high-risk event within three trading sessions blocks automatic transition to `Triggered` but does not hide the candidate.
- No page may contain a private ranking formula; all Today/Candidates/Portfolio decision context comes from shared services.
- Add failing tests before behavior changes. Commit after every task only when its focused tests pass.

## Target File Structure

```text
App/
  app.py                         # composition root only
  shell.py                       # header, responsive navigation, page registry
  services/
    database.py                  # market/user DB connections and read models
    candidate_service.py         # Today and Candidates queries
    portfolio_service.py         # validated user-position commands and read model
    health_service.py            # pipeline/source freshness read model
  components/
    action_card.py               # candidate decision card
    data_table.py                # responsive progressive-disclosure table
    market_gate.py               # regime summary
    portfolio_risk.py            # position-risk summary
  pages/
    today.py
    candidates.py
    portfolio.py
    research.py
    data_health.py

Scripts/
  decision_policy.py             # focused-v2 thresholds and state rules
  candidate_engine.py            # feature-to-candidate transformation
  regime_service.py              # curated benchmark market gate
  materialize_decision_tables.py # daily history materialization
  user_data.py                   # user DB migration/backup helpers
  pr_report_ingestion.py         # PR ZIP events/actions/bands/highs/top-value
  pipeline_health.py             # manifests and freshness status

tests/
  test_decision_policy.py
  test_candidate_engine_v2.py
  test_candidate_history.py
  test_user_data.py
  test_portfolio_service.py
  test_pr_report_ingestion.py
  test_pipeline_integration.py
  test_app_read_models.py
  test_ui_contracts.py
```

---

## Phase 0 — Establish a Safe, Reproducible Baseline

### Task 1: Luna preflight, backups, and executable acceptance fixtures

**Files:**

- Create: `tests/fixtures/decision_day.py`
- Create: `tests/test_current_data_audit.py`
- Modify: `tests/test_app_queries.py`
- Create: `docs/implementation/luna-baseline.md`

**Interfaces:**

- Produces `make_decision_day() -> dict[str, pd.DataFrame]` with deterministic indicators, breadth, rotations, deals, indices, events, and master frames.
- Produces a documented baseline containing test status, DB date, candidate counts, state counts, and quality-gate violations.

- [ ] **Step 1: Create an isolated branch/worktree.** Use branch `codex/marketpulse-luna-v2`. Confirm `git status --short` and record pre-existing untracked `Input/` files without staging them.
- [ ] **Step 2: Copy the current market and user databases to a timestamped backup directory outside `Database/`.** Verify SHA-256 hashes before any migration test. Do not use the production files in tests.
- [ ] **Step 3: Replace the stale navigation test with the desired top-level contract.** The test must assert exactly `Today`, `Candidates`, `Portfolio`, `Research`, and `Data Health`; initially it must fail because the shell does not yet provide that contract.
- [ ] **Step 4: Add the deterministic decision-day fixture.** Include: one liquid valid setup, one illiquid setup, one `RR < 1.5` setup, one stop wider than 8%, one 5% price-band stock, one event-risk stock, and one candidate in each lifecycle transition.
- [ ] **Step 5: Add read-only production audit assertions.** Record, but do not fail on, counts for `Prepare` with low liquidity, `RR < 1.5`, stop over 8%, missing industry state, and setup age equal to one.
- [ ] **Step 6: Run `py -m pytest -q`.** Expected at this point: the new navigation contract fails and all unrelated existing tests pass.
- [ ] **Step 7: Commit `test: establish Luna decision-system baseline`.**

---

## Phase 1 — Protect User Data and Fix the Decision Authority

### Task 2: Move manual data to a dedicated user database

**Files:**

- Create: `Scripts/user_data.py`
- Create: `App/services/database.py`
- Create: `tests/test_user_data.py`
- Modify: `Scripts/config.py`
- Modify: `Scripts/migrations.py`
- Modify: `Scripts/build_database.py`
- Modify: `App/app.py`

**Interfaces:**

```python
USER_DB_PATH: Path
initialize_user_db(user_db: Path) -> None
migrate_user_tables(market_db: Path, user_db: Path) -> MigrationReport
backup_user_db(user_db: Path, backup_dir: Path) -> Path
market_query(sql: str, params: Sequence[Any] = ()) -> pd.DataFrame
user_command(sql: str, params: Sequence[Any] = ()) -> None
```

- [ ] **Step 1: Write failing migration tests.** Seed temporary `trade_journal`, `portfolio_positions`, and `portfolio_events` tables with text/date/decimal values; assert exact row and DuckDB type preservation in the user DB.
- [ ] **Step 2: Add user DB schema version 1.** Include `trade_journal`, `portfolio_positions`, `portfolio_events`, and `portfolio_settings`. Add risk fields to positions: `stop_price`, `target_price`, `thesis`, `invalidation_note`, `setup_type`, `planned_risk_inr`, and `max_risk_pct`.
- [ ] **Step 3: Implement idempotent migration.** Copy within a DuckDB transaction, explicitly cast the known `trade_journal` text/date/decimal columns to the schema in `ensure_journal_table()`, verify counts and per-table checksums, then mark migration complete. Never drop the old tables automatically.
- [ ] **Step 4: Make the market DB read-only in application services.** All manual writes must route through `user_command`; market queries must route through `market_query`.
- [ ] **Step 5: Remove `ensure_runtime_schema()` and table creation from normal `main()` startup.** Provide an explicit command: `py Scripts/user_data.py --migrate --backup`.
- [ ] **Step 6: Remove manual-table preservation from market rebuilds only after the migrated user DB passes checksum verification.** Until then, keep the old preservation path as a compatibility fallback.
- [ ] **Step 7: Run `py -m pytest tests/test_user_data.py tests/test_migrations.py -q` and a temporary full-rebuild preservation test.**
- [ ] **Step 8: Commit `feat: isolate and protect MarketPulse user data`.**

### Task 3: Define the `focused-v2` policy and a correct market gate

**Files:**

- Create: `Scripts/decision_policy.py`
- Create: `Scripts/regime_service.py`
- Create: `tests/test_decision_policy.py`
- Modify: `Scripts/candidate_engine.py`
- Modify: `tests/test_candidate_engine.py`

**Interfaces:**

```python
SCORE_VERSION = "focused-v2"

@dataclass(frozen=True)
class DecisionPolicy:
    min_market_cap_cr: float = 1000.0
    min_avg_traded_value_cr_20d: float = 10.0
    min_price_band_pct: float = 10.0
    min_prepare_score: float = 65.0
    max_distance_to_trigger_pct: float = 5.0
    max_initial_risk_pct: float = 8.0
    min_reward_to_risk: float = 1.5
    expiry_sessions: int = 20

classify_market_gate(breadth_row, benchmark_rows, size_rows) -> MarketGate
evaluate_candidate_eligibility(row, policy) -> EligibilityResult
propose_candidate_state(previous, current, policy) -> StateTransition
```

**Required regime rules:**

- `Constructive`: Nifty 500 above 50/200 EMA, `above_50ema_pct >= 55`, `above_200ema_pct >= 50`, and `advance_pct >= 50`.
- `Selective`: Nifty 500 above 200 EMA and `above_50ema_pct >= 45`, without meeting Constructive.
- `Defensive`: Nifty 500 above 200 EMA but `above_50ema_pct < 45`, or breadth is deteriorating for two sessions.
- `Risk-Off`: Nifty 500 below 200 EMA and `above_200ema_pct < 40`.
- Sector/thematic indices may explain context but must never independently force the market gate to Risk-Off.

- [ ] **Step 1: Write tests demonstrating the existing bug.** A defensive thematic index among otherwise constructive benchmark/size indices must not force `Risk-Off`.
- [ ] **Step 2: Write boundary tests for every policy threshold.** Test equality and one unit below/above for market cap, traded value, band, score, trigger distance, stop width, and RR.
- [ ] **Step 3: Implement immutable policy/result dataclasses.** Results must contain `eligible`, `blocking_reasons`, `warning_reasons`, and the proposed lifecycle state.
- [ ] **Step 4: Implement curated-index classification.** Normalize index names and explicitly select Nifty 500 plus configured large/mid/small-cap indices; ignore unrelated strategy/thematic indices for the gate.
- [ ] **Step 5: Make high event risk a visible blocker for `Triggered`, not a reason to delete the candidate.**
- [ ] **Step 6: Run `py -m pytest tests/test_decision_policy.py tests/test_candidate_engine.py -q`.**
- [ ] **Step 7: Commit `feat: add focused-v2 decision policy and market gate`.**

### Task 4: Rebuild the canonical score, normalized deal evidence, and risk geometry

**Files:**

- Create: `tests/test_candidate_engine_v2.py`
- Modify: `Scripts/candidate_engine.py`
- Modify: `Scripts/schema.sql`
- Modify: `Scripts/migrations.py`

**Interfaces:**

```python
score_candidates(..., policy: DecisionPolicy, score_version: str) -> pd.DataFrame
calculate_risk_geometry(row: Mapping[str, Any]) -> RiskGeometry
normalize_deal_evidence(deals, indicators, master, as_of) -> pd.DataFrame
validate_pillar_math(row: Mapping[str, Any]) -> None
```

**Required score:**

```text
total_score =
    0.30 * leadership_score
  + 0.25 * setup_score
  + 0.20 * participation_score
  + 0.15 * context_score
  + 0.10 * risk_score
```

Each pillar and total must be clipped to `0..100`. Deal evidence must use net value, value/20-day turnover, value/market-cap, client repetition, and recency decay; raw deal crore value cannot be added directly to total score.

- [ ] **Step 1: Add failing tests for score bounds and exact pillar math.** Include extreme raw returns and deals to prove total score never exceeds 100.
- [ ] **Step 2: Add risk-geometry tests.** A missing structural pivot/stop must yield a blocking flag, not synthetic `close * 1.02`/`close * 0.94` levels. Require `trigger > invalidation`, `0 < risk <= 8`, and `RR >= 1.5` for Prepare.
- [ ] **Step 3: Add sector/industry mapping tests.** Match the exact `sector_rotation.level` and `group_name` conventions and populate both states; never silently default every industry to `Unknown`.
- [ ] **Step 4: Implement normalized deal evidence.** Preserve buy, sell, net, repeated-client count, and normalization denominators in stored columns so the explanation can be audited.
- [ ] **Step 5: Replace the permissive `_score(..., default=50)` behavior for missing critical inputs.** Missing evidence contributes a neutral value only when explicitly allowed and adds a data-quality flag.
- [ ] **Step 6: Save `eligibility_status`, `blocking_reasons`, `warning_reasons`, and structured trigger/invalidation types in `candidate_daily`.**
- [ ] **Step 7: Run the focused tests and commit `feat: make candidate scoring bounded and auditable`.**

---

## Phase 2 — Persist the Decision Lifecycle and Measure It

### Task 5: Materialize all daily candidates without resetting lifecycle state

**Files:**

- Create: `tests/test_candidate_history.py`
- Modify: `Scripts/materialize_decision_tables.py`
- Modify: `Scripts/watchlist_service.py`
- Modify: `Scripts/signal_service.py`
- Modify: `Scripts/outcomes.py`
- Modify: `Scripts/daily_pipeline.py`

**Interfaces:**

```python
materialize_decision_date(db_path: Path, as_of: date, score_version="focused-v2") -> int
backfill_decision_history(db_path: Path, start: date, end: date, score_version="focused-v2") -> BackfillReport
transition_candidate(previous, current, policy) -> StateTransition
update_signal_ledger(existing, candidates, trade_date) -> pd.DataFrame
```

- [ ] **Step 1: Write a three-session lifecycle test.** Prove `Observe -> Prepare -> Triggered`, a subsequent close below invalidation produces `Invalidated`, `setup_first_seen` remains unchanged, and age increments by trading sessions.
- [ ] **Step 2: Write a no-overwrite test.** Materializing 2026-08-08 must leave 2026-08-07 `candidate_daily`, signal history, and resolved outcomes unchanged.
- [ ] **Step 3: Change materialization to delete/upsert only one `(trade_date, score_version)` partition.** Never clear earlier dates.
- [ ] **Step 4: Derive state from the prior trading session and stored policy, not from total score alone.** Store the transition reason and prior state.
- [ ] **Step 5: Add a resumable backfill CLI.** Example: `py Scripts/materialize_decision_tables.py --backfill --start 2024-01-01 --score-version focused-v2`; commit every 20 sessions and record progress.
- [ ] **Step 6: Compute 5/10/20/60-session returns, MFE, and MAE only when each window is resolved.** Add grouped summaries by regime, setup, score bucket, sector state, liquidity bucket, and event risk.
- [ ] **Step 7: Run `py -m pytest tests/test_candidate_history.py tests/test_signal_service.py tests/test_outcomes.py -q`.**
- [ ] **Step 8: Commit `feat: persist candidate lifecycle and outcomes`.**

### Task 6: Create one application read model for Today and Candidates

**Files:**

- Create: `App/services/candidate_service.py`
- Create: `tests/test_app_read_models.py`
- Modify: `App/query_service.py`
- Modify: `App/pages/today.py`
- Create: `App/pages/candidates.py`
- Modify: `App/app.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class TodayReadModel:
    market_gate: dict
    action_queue: pd.DataFrame
    portfolio_alerts: pd.DataFrame
    changes: pd.DataFrame
    group_summary: pd.DataFrame
    data_as_of: date

load_today(db_path: Path, user_db: Path, limit: int = 10) -> TodayReadModel
load_candidates(db_path: Path, filters: CandidateFilters) -> pd.DataFrame
```

- [ ] **Step 1: Write query tests proving Today reads only `focused-v2` canonical tables.** Searches of the page/service files must find no `prep_score`, `near_score`, or inline weighted SQL.
- [ ] **Step 2: Define deterministic action-queue ordering.** `Triggered` first, then `Prepare`, then `Observe`; within state sort by eligibility, score, trigger distance, and symbol.
- [ ] **Step 3: Deduplicate queues.** A symbol appears once on Today with multiple evidence badges; Top 10, Near Entry, and institutional confluence become facets of the same row rather than separate lists.
- [ ] **Step 4: Return at most 10 action rows by default.** Exclude blocking failures from the primary queue but expose them in Candidates with their reasons.
- [ ] **Step 5: Include `why_now`, `latest_change`, trigger, stop, risk %, RR, normalized net deal, event warning, setup age, and data-quality state in every action row.**
- [ ] **Step 6: Add query-session reuse and snapshot caching.** Cache immutable latest-session read models by market DB modification time plus pipeline status version; invalidate after accepted pipeline/user commands and never share a writable DuckDB connection between requests.
- [ ] **Step 7: Run `py -m pytest tests/test_app_read_models.py tests/test_app_queries.py -q`.**
- [ ] **Step 8: Commit `refactor: make canonical candidates the only UI authority`.**

---

## Phase 3 — Rebuild the Swing-Trader Workflow

### Task 7: Implement decision-first Today and Candidates pages

**Files:**

- Create: `App/components/action_card.py`
- Create: `App/components/market_gate.py`
- Create: `App/components/data_table.py`
- Modify: `App/pages/today.py`
- Modify: `App/pages/candidates.py`
- Create: `tests/test_ui_contracts.py`

**Today order:**

1. Data freshness and market gate.
2. Portfolio risk alerts requiring action.
3. Maximum 10-candidate action queue.
4. What changed since the prior session.
5. Compact sector/industry context; full tables live under Research.

**Action card contract:**

```text
SYMBOL · STATE · SCORE/100
Why now | What changed
Trigger | Stop | Risk % | RR | Distance
Sector/industry state | Net deal | Event risk | Age
[TradingView] [Add/update plan]
```

- [ ] **Step 1: Write source/DOM contract tests.** Today must render action queue before group tables; score labels must include `/100`; every card must expose Trigger, Stop, Risk, RR, and Why now.
- [ ] **Step 2: Implement progressive disclosure.** Show six decision fields initially; put diagnostic pillars and raw metrics behind a details expansion.
- [ ] **Step 3: Implement Candidates filters.** State, eligibility, sector, industry, setup, event risk, liquidity, max trigger distance, max stop width, and minimum RR.
- [ ] **Step 4: Provide explicit empty/error states.** Distinguish “no valid candidates,” “decision tables stale,” “pipeline failed,” and “database unavailable.”
- [ ] **Step 5: Keep TradingView links and copy actions but generate copy text from the filtered canonical rows only.**
- [ ] **Step 6: Run UI contract and read-model tests; manually inspect Today at 1440x900 before proceeding.**
- [ ] **Step 7: Commit `feat: add decision-first Today and Candidates UI`.**

### Task 8: Turn Portfolio into an open-risk manager

**Files:**

- Create: `App/services/portfolio_service.py`
- Create: `App/components/portfolio_risk.py`
- Create: `App/pages/portfolio.py`
- Create: `tests/test_portfolio_service.py`
- Modify: `App/app.py`

**Interfaces:**

```python
validate_position(command: PositionCommand, latest: MarketSnapshot) -> ValidationResult
upsert_position(command: PositionCommand) -> Position
mark_sold(command: ExitCommand) -> Position
calculate_position_risk(position: Position, cmp: float) -> PositionRisk
load_portfolio_dashboard(market_db: Path, user_db: Path) -> PortfolioReadModel
```

**Required calculated fields:**

- Initial risk INR and percentage.
- Current open risk to stop.
- R multiple achieved.
- Portfolio weight and total risk contribution.
- Distance to stop and target.
- Sector/industry exposure.
- Event warning.
- Technical deterioration: below stop, below 20/50 EMA, RS deterioration, failed breakout, or group weakening.

- [ ] **Step 1: Write validation tests.** Reject unknown symbols, quantity/price <= 0, future buy/sell dates, stop >= entry, target <= entry, implausible entry deviations without confirmation, and deletes without an explicit selected symbol.
- [ ] **Step 2: Add corporate-action warning behavior.** If an entry differs materially from nearby historical prices or a split/bonus exists after purchase, display a reconciliation warning and require confirmation; never silently alter the user’s record.
- [ ] **Step 3: Implement account settings.** Store account equity and default maximum risk percentage in `portfolio_settings`; position sizing is guidance, not an automatic trade instruction.
- [ ] **Step 4: Replace the 24-column primary table with an action-oriented open-risk table.** Default columns: symbol, P&L, weight, open risk, R multiple, stop distance, action state, event. Put technical diagnostics in row details.
- [ ] **Step 5: Add confirmation dialogs for Delete and Mark Sold.** Disable destructive buttons until a valid position is loaded.
- [ ] **Step 6: Preserve the complete event history for create, edit, stop change, target change, sell, reopen, and delete.**
- [ ] **Step 7: Run `py -m pytest tests/test_portfolio_service.py tests/test_user_data.py -q`.**
- [ ] **Step 8: Commit `feat: turn portfolio into an open-risk manager`.**

### Task 9: Consolidate Research and add Data Health

**Files:**

- Modify: `App/pages/research.py`
- Create: `App/pages/data_health.py`
- Create: `App/services/health_service.py`
- Create: `Scripts/pipeline_health.py`
- Modify: `App/app.py`
- Create: `tests/test_pipeline_health.py`

**Research sections:** Sector Intel, Momentum, Deals, Stock Detail, Market Health, Screeners, VCP Lab, Backtests, and Journal. They remain lazy-loaded and consume shared query helpers.

**Data Health must show:** database date, latest expected NSE session, source file completeness, manifest/checksum status, row counts, candidate materialization date, user DB backup age, last pipeline duration, last error, and a link/path to the log.

- [ ] **Step 1: Write health-state tests for Healthy, Stale, Partial, Failed, and Missing DB.**
- [ ] **Step 2: Move Sector Intel, Momentum, and Deals under Research without deleting their implementations.** Present a small research selector/cards rather than all tools as top-level tabs.
- [ ] **Step 3: Remove repeated data from Research overview.** Sector group overview appears once; expanding a group loads its stock table underneath the selected row.
- [ ] **Step 4: Make table presets purposeful.** Each research screen defines `decision`, `diagnostic`, and `all columns` views; default to decision.
- [ ] **Step 5: Implement Data Health using status/manifests rather than inference from UI labels.**
- [ ] **Step 6: Run tests and commit `feat: consolidate research and expose data health`.**

---

## Phase 4 — Use the Inputs Already Downloaded

### Task 10: Parse PR ZIP events, corporate actions, band hits, highs/lows, and top-value lists

**Files:**

- Create: `Scripts/pr_report_ingestion.py`
- Create: `tests/test_pr_report_ingestion.py`
- Modify: `Scripts/schema.sql`
- Modify: `Scripts/migrations.py`
- Modify: `Scripts/download_nse_reports.py`
- Modify: `Scripts/daily_pipeline.py`

**Input mapping:**

- `anDDMMYYYY.txt` -> corporate announcements -> `security_events`.
- `bmDDMMYYYY.txt` -> board meetings -> `security_events`.
- `bcDDMMYYYY.csv` -> dividends/bonus/splits/rights -> `corporate_actions`.
- `bhDDMMYYYY.csv` -> daily price-band hits -> `security_risk_daily`.
- `hlDDMMYYYY.csv` -> new-high/new-low participation -> `security_risk_daily` and breadth context.
- `ttDDMMYYYY.csv` -> top traded-value membership -> liquidity/participation context.
- `pr/pd` remain reference sources; do not duplicate canonical bhavcopy rows.

**Interfaces:**

```python
parse_pr_zip(path: Path, trade_date: date) -> PRReportBundle
normalize_announcement(text: str) -> EventClassification
upsert_pr_bundle(db_path: Path, bundle: PRReportBundle) -> IngestionResult
```

- [ ] **Step 1: Add fixtures extracted from a real PR ZIP with personally identifying institution text removed.** Include malformed lines, duplicate announcements, multiple corporate actions, and empty files.
- [ ] **Step 2: Write parser/deduplication tests.** Keys must include symbol, effective date, event/action type, and source checksum.
- [ ] **Step 3: Classify only high-confidence event categories in production.** Financial results, board meeting, dividend, bonus, split, rights, merger/demerger, order/contract, fund raise, and regulatory action; store uncertain items as `other`, never invent sentiment.
- [ ] **Step 4: Build adjustment factors for split/bonus/rights events and test that they prevent false price/EMA jumps.** Keep raw OHLCV unchanged and materialize adjusted columns separately.
- [ ] **Step 5: Add event proximity, recent band-hit count, new-high participation, and top-turnover membership to candidate context/risk explanations.**
- [ ] **Step 6: Run `py -m pytest tests/test_pr_report_ingestion.py tests/test_events.py tests/test_corporate_actions.py -q`.**
- [ ] **Step 7: Commit `feat: use NSE PR reports for event and risk context`.**

### Task 11: Make daily ingestion manifest-aware, incremental, and transactional

**Files:**

- Modify: `Scripts/daily_pipeline.py`
- Modify: `Scripts/append_database.py`
- Modify: `Scripts/ingestion_manifest.py`
- Modify: `Scripts/transactional_append.py`
- Modify: `Scripts/reconcile_database.py`
- Create: `tests/test_pipeline_integration.py`

**Interfaces:**

```python
prepare_session_manifest(session_dir: Path) -> Manifest
validate_session_manifest(manifest: Manifest) -> ValidationReport
append_session_transactionally(market_db: Path, manifest: Manifest) -> AppendReport
reconcile_incremental_with_rebuild(...) -> ReconciliationReport
```

- [ ] **Step 1: Write integration tests for complete, duplicate, partial, checksum-changed, and gap sessions.** A partial session must not modify the accepted database.
- [ ] **Step 2: Replace the current full-history recomputation in `daily_pipeline._run_append()` with staged incremental transforms plus a single DuckDB transaction.**
- [ ] **Step 3: Populate `ingestion_batches` and `ingested_reports` for every accepted report.** Record checksum, row count, trade date, status, and duration.
- [ ] **Step 4: Materialize only the new decision date after the market transaction succeeds.** A decision failure must be visible in Data Health and must not label the pipeline fully healthy.
- [ ] **Step 5: Reconcile a representative 20-session incremental database with a fresh rebuild.** Require identical primary keys and categorical fields; floating columns use `1e-9` tolerance.
- [ ] **Step 6: Measure runtime.** Record download, append, feature, decision, and total durations in status JSON; target a warm append below 10 minutes without weakening correctness.
- [ ] **Step 7: Run the ingestion, transaction, reconciliation, and full test suites.**
- [ ] **Step 8: Commit `perf: make EOD ingestion incremental and auditable`.**

---

## Phase 5 — Responsive Shell, Diagnostics, and Release Gates

### Task 12: Implement the responsive shell and eliminate browser console errors

**Files:**

- Create: `App/shell.py`
- Modify: `App/app.py`
- Modify: `App/components/data_table.py`
- Modify: `tests/test_ui_contracts.py`

**Required top-level navigation:** `Today`, `Candidates`, `Portfolio`, `Research`, `Data Health`.

- [ ] **Step 1: Move header/navigation/page registry to `App/shell.py`.** Keep `App/app.py` responsible for configuration, service construction, and `ui.run()` only.
- [ ] **Step 2: Change `_ui_run_kwargs()` to default to `127.0.0.1`.** Add a test proving non-loopback binding happens only when `MP_HOST` is explicitly set; document that such exposure has no authentication in this release.
- [ ] **Step 3: Fix the 60 repeated Vue/NiceGUI errors.** Remove `document.createElement` from the inline `body-cell-copy_symbols` Vue expression in `App/app.py`; route clipboard work through a tested NiceGUI/Python callback or a small registered component method.
- [ ] **Step 4: Add responsive breakpoints.** At `<= 640px`, use a horizontally scrollable or compact navigation control, stack all two-column grids, render candidate/portfolio cards, and prevent document-level horizontal overflow.
- [ ] **Step 5: At desktop widths, constrain the content measure, keep the action queue above the fold, and use horizontal table scrolling only inside diagnostic table containers.**
- [ ] **Step 6: Add accessible names and confirmation semantics.** Every icon-only button needs a label/tooltip; selected tabs expose state; forms have visible labels and error text.
- [ ] **Step 7: Run the app and inspect in the Codex browser at 1440x900, the normal viewport, and 390x844.** Acceptance: all five destinations reachable, no clipped Portfolio nav, no page-level horizontal scrollbar, primary actions visible, and browser console contains zero errors/warnings caused by application code.
- [ ] **Step 8: Commit `fix: add responsive error-free application shell`.**

### Task 13: Shadow validation, production switch, and operator handoff

**Files:**

- Create: `Scripts/compare_score_versions.py`
- Create: `docs/operations/eod-runbook.md`
- Create: `docs/operations/decision-model.md`
- Modify: `README.md`
- Modify: `Scripts/config.py`

**Release gates:**

- All tests pass.
- Market/user DB migrations verified from backups.
- `focused-v2` total/pillars always `0..100`.
- Zero `Prepare` rows violate market-cap, liquidity, price-band, trigger/stop, `risk <= 8%`, or `RR >= 1.5` gates.
- Every latest candidate has sector and industry state or an explicit mapping/data-quality warning.
- Candidate history contains more than one session; ages and state transitions are not reset.
- Today and Candidates return the same rank/order under identical filters.
- Portfolio destructive actions require confirmation and preserve event history.
- Incremental/rebuild reconciliation passes.
- UI passes desktop/mobile/browser-console acceptance.

- [ ] **Step 1: Run `focused-v1` and `focused-v2` side-by-side.** Generate a report with counts, overlaps, rejected symbols/reasons, rank changes, score distribution, and data-quality flags.
- [ ] **Step 2: Review at least 20 historical sessions or all available resolved sessions if fewer.** Compare 5/10/20-session return, MFE, MAE, hit rate, and median drawdown by regime; do not optimize weights on the same window used for the final comparison.
- [ ] **Step 3: Make the UI score version configurable, defaulting to `focused-v1` until all non-performance release gates pass.** Switch the default to `focused-v2` in one explicit commit.
- [ ] **Step 4: Run final verification:**

```powershell
py -m pytest -q
py -m py_compile Scripts\*.py App\*.py App\services\*.py App\components\*.py App\pages\*.py
git diff --check
git status --short
```

- [ ] **Step 5: Run a temporary database rebuild, a duplicate append no-op, a new-session append, decision materialization, user-data checksum verification, and HTTP/browser smoke test.**
- [ ] **Step 6: Document recovery.** Include restore market DB, restore user DB, rerun one session, rebuild decision history, inspect a failed manifest, and revert the score-version switch.
- [ ] **Step 7: Commit `docs: add MarketPulse EOD and decision-model runbooks`.**
- [ ] **Step 8: Create a release checkpoint for the user.** Do not delete `focused-v1` or legacy Research renderers until the user has used `focused-v2` for at least 20 live sessions.

---

## Luna Execution Rules

1. Execute tasks sequentially; do not start a later phase while an earlier phase has red focused tests.
2. At the start of each task, restate its files, interfaces, and acceptance tests.
3. Do not stage `Input/`, production databases, backups, logs, or generated screenshots.
4. Prefer extracting tested services over adding more functions to `App/app.py`.
5. Preserve old behavior behind compatibility paths until the replacement passes its release gate.
6. After each task, report: changed files, tests run with exact counts, database mutations performed, remaining risks, and commit hash.
7. Stop and ask the user before changing policy thresholds, score weights, account-risk defaults, or event classifications specified in this plan.
8. Never describe a candidate as a buy/sell instruction. Present evidence, trigger, invalidation, risk, and historical context.

## Program Definition of Done

MarketPulse is ready for daily personal use as a swing-trader operating system when the EOD pipeline produces one auditable `focused-v2` snapshot; Today shows no more than 10 actionable names with valid risk geometry; Portfolio highlights open risk and required actions; Research retains detailed diagnostics without dominating navigation; downloaded NSE events/actions are reflected in context; user data survives rebuilds independently; outcome history measures what worked; desktop/mobile browser checks are clean; and every release gate above has fresh verification evidence.
