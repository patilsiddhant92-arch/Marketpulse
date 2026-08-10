# MarketPulse Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax and end with a focused verification.

**Goal:** Make the existing MarketPulse application a trustworthy EOD swing-trading decision desk before any visual redesign.

**Architecture:** Keep the legacy NiceGUI shell and research pages as the first release surface. Add a versioned decision layer that materializes one `focused-v2` snapshot after a validated EOD append, and make Today/Candidates read only that snapshot. Keep market data read-only to the UI and migrate manual portfolio/journal state to a separate user database. Ingest the existing PR ZIP reports before materializing decisions.

**Tech Stack:** Python 3.12, NiceGUI, DuckDB, pandas, NumPy, pytest, NSE CSV/TXT/ZIP inputs, Windows PowerShell.

## Global Constraints

- Do not edit or regenerate files under `Input/` during tests.
- Do not rebuild or migrate the production database in place; use a verified copy and record hashes.
- Do not replace the existing UI shell until workflow parity is demonstrated.
- `Today` must never silently fall back from `focused-v2` to `focused-v1`.
- Every `Today` row must satisfy `market_cap_cr >= 1000`, minimum 20-day traded value, price-band, trigger/stop, maximum risk, and minimum reward-to-risk gates.
- Blocked candidates remain visible only in Candidates with explicit machine-readable reasons.
- All candidate scores and pillar values are clipped to `0..100` and carry a score version.
- Manual portfolio, journal, settings, and event history writes go to the user database.
- Do not expose the app beyond `127.0.0.1` in this recovery.
- Do not claim a release until the browser smoke test and all release gates in the recovery design pass.

## Worktree and baseline

Work in `D:\Sid\MarketPulse2.0\.worktrees\marketpulse-recovery` on branch `codex/marketpulse-recovery`. The production checkout and local NSE files remain untouched. Use the shared project virtual environment at `D:\Sid\MarketPulse2.0\.venv` and pass `--basetemp .pytest-tmp` to pytest because the host temp root is permission-restricted.

---

### Task 1: Establish a reproducible recovery baseline and audit command

**Files:**

- Create: `tests/test_recovery_audit.py`
- Create: `Scripts/recovery_audit.py`
- Modify: `tests/test_app_queries.py`
- Create: `docs/implementation/marketpulse-recovery-baseline.md`

**Interfaces:**

```python
@dataclass(frozen=True)
class RecoveryAudit:
    database_date: date | None
    candidate_date: date | None
    score_versions: dict[str, int]
    latest_candidate_count: int
    below_market_cap_count: int
    missing_market_cap_count: int
    portfolio_count: int
    pr_table_counts: dict[str, int]

def audit_database(db_path: Path) -> RecoveryAudit: ...
```

- [ ] **Step 1: Write the failing audit tests.** Create a temporary DuckDB with `candidate_daily`, `portfolio_positions`, and optional PR tables. Assert that the audit returns the latest dates, version counts, below-threshold count, missing-market-cap count, and table counts without writing to the database.
- [ ] **Step 2: Run the focused tests and verify the expected failure.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_recovery_audit.py -q
  ```

  Expected: import/function failure because `audit_database` does not exist.
- [ ] **Step 3: Implement the read-only audit.** Use `duckdb.connect(..., read_only=True)`, detect optional tables through `information_schema`, and return zero counts for absent PR tables. Do not initialize schemas or create files.
- [ ] **Step 4: Replace the stale navigation assertion.** Assert the actual legacy shell contract (`Today`, `Sector Intel`, `Momentum`, `Deals`, `Portfolio`) and add a separate test that the recovery adds `Candidates` and `Data Health` without removing those pages.
- [ ] **Step 5: Run the focused tests and record the production audit.** Save the output, including the current `focused-v1`/market-cap discrepancy, to `docs/implementation/marketpulse-recovery-baseline.md`. The command must use an explicit production path and read-only mode.
- [ ] **Step 6: Commit the baseline.**

  ```powershell
  git add tests/test_recovery_audit.py tests/test_app_queries.py Scripts/recovery_audit.py docs/implementation/marketpulse-recovery-baseline.md
  git commit -m "test: establish MarketPulse recovery baseline"
  ```

---

### Task 2: Implement and materialize the hard decision gates

**Files:**

- Create: `Scripts/decision_policy.py`
- Create: `tests/test_decision_policy.py`
- Create: `tests/test_decision_snapshot.py`
- Modify: `Scripts/candidate_engine.py`
- Modify: `Scripts/materialize_decision_tables.py`
- Modify: `Scripts/schema.sql`
- Modify: `Scripts/migrations.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class DecisionPolicy:
    score_version: str = "focused-v2"
    min_market_cap_cr: float = 1000.0
    min_avg_traded_value_cr_20d: float = 10.0
    min_price_band_pct: float = 10.0
    min_prepare_score: float = 65.0
    max_distance_to_trigger_pct: float = 5.0
    max_initial_risk_pct: float = 8.0
    min_reward_to_risk: float = 1.5
    expiry_sessions: int = 20

@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    blocking_reasons: tuple[str, ...]
    warning_reasons: tuple[str, ...]

def evaluate_candidate_eligibility(row: Mapping[str, Any], policy: DecisionPolicy) -> EligibilityResult: ...
def materialize_decision_date(db_path: Path, as_of: date, policy: DecisionPolicy) -> pd.DataFrame: ...
```

- [ ] **Step 1: Write boundary tests before changing scoring.** Cover exactly ₹1,000 Cr, ₹999.99 Cr, missing market cap, traded value, price band, stop width, trigger distance, and reward-to-risk. Assert low/missing market-cap rows are blocked, not eligible.
- [ ] **Step 2: Run the policy tests and verify the expected failure.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_decision_policy.py -q
  ```
- [ ] **Step 3: Implement the immutable policy and eligibility result.** The minimum market-cap rule must treat missing values as a blocker, never as a warning. Store `eligibility_status`, `blocking_reasons`, and `warning_reasons` in `candidate_daily`.
- [ ] **Step 4: Remove synthetic risk geometry from the focused-v2 path.** A missing pivot/support/resistance returns `risk_geometry_missing` and cannot enter `Prepare`.
- [ ] **Step 5: Make `focused-v2` explicit in materialization.** Materialize only the requested `(trade_date, score_version)` partition, preserve prior dates, and return a non-empty report containing the candidate date and counts.
- [ ] **Step 6: Add a snapshot contract test.** Seed a temporary database with valid, low-cap, and missing-cap rows; materialize; assert the stored version is `focused-v2`, the latest snapshot date is correct, and a Today-eligible query returns no row below ₹1,000 Cr.
- [ ] **Step 7: Run focused decision tests and commit.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_decision_policy.py tests/test_decision_snapshot.py tests/test_candidate_engine.py -q
  git add Scripts/decision_policy.py Scripts/candidate_engine.py Scripts/materialize_decision_tables.py Scripts/schema.sql Scripts/migrations.py tests/test_decision_policy.py tests/test_decision_snapshot.py tests/test_candidate_engine.py
  git commit -m "feat: enforce focused-v2 decision gates"
  ```

---

### Task 3: Ingest all usable NSE PR ZIP inputs

**Files:**

- Create: `Scripts/pr_report_ingestion.py`
- Create: `tests/test_pr_report_ingestion.py`
- Modify: `Scripts/schema.sql`
- Modify: `Scripts/migrations.py`
- Modify: `Scripts/events.py`
- Modify: `Scripts/corporate_actions.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class PRReportBundle:
    trade_date: date
    events: pd.DataFrame
    corporate_actions: pd.DataFrame
    risk_daily: pd.DataFrame
    top_value: pd.DataFrame

def parse_pr_zip(path: Path, trade_date: date) -> PRReportBundle: ...
def upsert_pr_bundle(db_path: Path, bundle: PRReportBundle, source_checksum: str) -> dict[str, int]: ...
```

- [ ] **Step 1: Add sanitized fixtures extracted from one existing PR ZIP.** Include one announcement, board meeting, corporate action, price-band hit, high/low row, top-value row, duplicate row, malformed row, and an empty report. Do not include personal or broker-identifying text.
- [ ] **Step 2: Write parser and deduplication tests.** Assert the mapping `an -> security_events`, `bm -> security_events`, `bc -> corporate_actions`, `bh/hl -> security_risk_daily`, and `tt -> top_value_daily`. Assert source checksum and stable conflict keys.
- [ ] **Step 3: Run the parser tests and verify the expected failure.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_pr_report_ingestion.py -q
  ```
- [ ] **Step 4: Implement tolerant parsing.** Normalize symbols, dates, event categories, ratios, and numeric values. Preserve uncertain announcements as `other`; never infer positive or negative sentiment. Keep raw prices unchanged and materialize adjustment factors separately.
- [ ] **Step 5: Add tables and indexes.** Create `security_risk_daily` and `top_value_daily`, and add source checksum columns/keys to all PR-derived tables. Migrations must be idempotent.
- [ ] **Step 6: Add candidate context columns.** Store next-event date/risk, recent band-hit count, recent high/low participation, and top-value membership in the decision snapshot.
- [ ] **Step 7: Run parser, event, and corporate-action tests and commit.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_pr_report_ingestion.py tests/test_events.py tests/test_corporate_actions.py -q
  git add Scripts/pr_report_ingestion.py Scripts/schema.sql Scripts/migrations.py Scripts/events.py Scripts/corporate_actions.py tests/test_pr_report_ingestion.py
  git commit -m "feat: ingest NSE PR event and risk reports"
  ```

---

### Task 4: Wire append, PR ingestion, and decision materialization into one EOD transaction

**Files:**

- Modify: `Scripts/download_nse_reports.py`
- Modify: `Scripts/daily_pipeline.py`
- Modify: `Scripts/append_database.py`
- Modify: `Scripts/transactional_append.py`
- Modify: `Scripts/ingestion_manifest.py`
- Modify: `Scripts/reconcile_database.py`
- Create: `tests/test_pipeline_recovery.py`
- Modify: `Scripts/pipeline_health.py`

**Interfaces:**

```python
def validate_session_manifest(session_dir: Path) -> ValidationReport: ...
def append_session_transactionally(market_db: Path, session_dir: Path) -> AppendReport: ...
def materialize_decision_date(db_path: Path, as_of: date, policy: DecisionPolicy) -> pd.DataFrame: ...
```

- [ ] **Step 1: Write integration tests for complete, duplicate, partial, checksum-changed, and gap sessions.** Assert a partial or checksum-changed session leaves the accepted market database and decision snapshot unchanged.
- [ ] **Step 2: Run the pipeline tests and verify the expected failure.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_pipeline_recovery.py -q
  ```
- [ ] **Step 3: Preserve the downloaded PR ZIP in the session manifest.** `download_nse_reports.py` must record the ZIP checksum and extracted report names; it must not silently discard the ZIP after extracting market cap.
- [ ] **Step 4: Run the append, PR upsert, and focused-v2 materialization only after manifest validation.** Use one transaction for the accepted market session and write `ingestion_batches`/`ingested_reports` with row counts and checksums.
- [ ] **Step 5: Make duplicate runs no-ops and ensure materialization is idempotent.** A second run for the same session must not duplicate events, candidates, signals, or outcomes.
- [ ] **Step 6: Make Data Health fail when the decision snapshot is absent, stale, or has a different date/version from the accepted market session.**
- [ ] **Step 7: Run pipeline, manifest, transactional, reconciliation, and health tests and commit.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_pipeline_recovery.py tests/test_ingestion_manifest.py tests/test_transactional_append.py tests/test_reconciliation.py -q
  git add Scripts/download_nse_reports.py Scripts/daily_pipeline.py Scripts/append_database.py Scripts/transactional_append.py Scripts/ingestion_manifest.py Scripts/reconcile_database.py Scripts/pipeline_health.py tests/test_pipeline_recovery.py
  git commit -m "feat: make EOD decisions transactional and auditable"
  ```

---

### Task 5: Isolate user data and make portfolio operations functional

**Files:**

- Create: `Scripts/user_data.py`
- Create: `App/user_data_service.py`
- Create: `tests/test_user_data_migration.py`
- Create: `tests/test_portfolio_commands.py`
- Modify: `Scripts/config.py`
- Modify: `App/app.py`

**Interfaces:**

```python
def migrate_user_data(market_db: Path, user_db: Path, backup_dir: Path) -> MigrationReport: ...
def upsert_position(user_db: Path, command: PositionCommand) -> Position: ...
def mark_sold(user_db: Path, command: ExitCommand) -> Position: ...
def delete_position(user_db: Path, symbol: str, confirmed: bool) -> None: ...
```

- [ ] **Step 1: Write migration tests with the existing 14 legacy open positions and a journal/event row.** Assert exact counts, normalized types, and a checksum before/after migration.
- [ ] **Step 2: Write command tests.** Reject unknown symbols, non-positive quantity/price, stop >= entry, target <= entry, future dates, and unconfirmed destructive actions. Assert every mutation writes an event.
- [ ] **Step 3: Run the user-data tests and verify the expected failure.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_user_data_migration.py tests/test_portfolio_commands.py -q
  ```
- [ ] **Step 4: Implement idempotent migration and explicit backup.** Never drop the legacy tables automatically; copy into the user database inside a transaction and emit a migration report.
- [ ] **Step 5: Route the legacy Portfolio page writes through the user-data service.** Keep the existing layout, but connect Add/Edit/Sell/Reopen/Delete and add stop, target, thesis, and invalidation fields.
- [ ] **Step 6: Add action-oriented risk calculations.** Show P&L, open risk, portfolio weight, R multiple, stop distance, target distance, sector/industry exposure, and event/technical warnings.
- [ ] **Step 7: Run focused portfolio tests and commit.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_user_data_migration.py tests/test_portfolio_commands.py -q
  git add Scripts/user_data.py App/user_data_service.py App/app.py Scripts/config.py tests/test_user_data_migration.py tests/test_portfolio_commands.py
  git commit -m "feat: protect and operate portfolio data"
  ```

---

### Task 6: Connect the decision snapshot to the existing UI without replacing its visual language

**Files:**

- Create: `App/decision_read_model.py`
- Create: `App/candidates_page.py`
- Create: `App/data_health_page.py`
- Create: `tests/test_decision_read_model.py`
- Create: `tests/test_ui_recovery_contracts.py`
- Modify: `App/app.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class DecisionSnapshot:
    as_of: date
    score_version: str
    market_gate: str
    eligible: pd.DataFrame
    blocked: pd.DataFrame
    excluded_by_market_cap: int
    stale: bool

def load_decision_snapshot(db_path: Path, expected_date: date | None = None) -> DecisionSnapshot: ...
```

- [ ] **Step 1: Write read-model tests.** Assert missing/stale snapshots produce an explicit diagnostic state, eligible rows are all ≥₹1,000 Cr, blocked rows retain reasons, and Today/Candidates share ordering and filters.
- [ ] **Step 2: Run the read-model tests and verify the expected failure.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_decision_read_model.py -q
  ```
- [ ] **Step 3: Implement the read model using read-only DuckDB.** Select only the latest `focused-v2` session; never substitute `focused-v1`. Normalize pandas dates/timestamps before passing rows to NiceGUI.
- [ ] **Step 4: Replace only the decision content of `today_page`.** Keep the existing header, theme, research cards, TradingView/copy actions, and navigation. Render a concise queue with symbol, state, score, why-now, trigger, invalidation, risk, RR, event, and data freshness.
- [ ] **Step 5: Add `Candidates` beside the existing tabs.** Provide state, market cap, liquidity, sector, industry, event risk, max trigger distance, max stop width, and minimum RR filters. Show blocked names and reasons in a diagnostic view.
- [ ] **Step 6: Add `Data Health` beside the existing tabs.** Display market date, decision date/version, PR ingestion counts, manifest status, user-data migration status, last pipeline error, and log path.
- [ ] **Step 7: Run UI/read-model tests and commit.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_decision_read_model.py tests/test_ui_recovery_contracts.py tests/test_app_queries.py -q
  git add App/decision_read_model.py App/candidates_page.py App/data_health_page.py App/app.py tests/test_decision_read_model.py tests/test_ui_recovery_contracts.py tests/test_app_queries.py
  git commit -m "feat: connect audited decisions to the existing UI"
  ```

---

### Task 7: Shadow comparison, browser verification, and release checkpoint

**Files:**

- Create: `Scripts/compare_score_versions.py`
- Create: `tests/test_score_comparison.py`
- Modify: `README.md`
- Modify: `docs/operations/eod-runbook.md`
- Create: `docs/implementation/recovery-release-checklist.md`

- [ ] **Step 1: Write comparison tests.** Assert counts, overlap, rejected symbols/reasons, rank changes, score distributions, and data-quality flags for `focused-v1` versus `focused-v2`.
- [ ] **Step 2: Run the comparison tests and verify the expected failure.**
- [ ] **Step 3: Implement a read-only comparison report.** Evaluate at least 20 resolved sessions or all available sessions if fewer exist; include 5/10/20/60-session returns, MFE, MAE, hit rate, median drawdown, and grouping by regime, setup, sector state, liquidity, and event risk.
- [ ] **Step 4: Start the recovery app on `127.0.0.1:8080` from the recovery worktree only.** Verify desktop and 390px views with the Chrome connector: all seven legacy/recovery destinations are reachable, Today is nonblank only when the snapshot is current, no page-level horizontal overflow exists, Portfolio actions are functional, and the browser console has no application errors.
- [ ] **Step 5: Run the final verification commands.**

  ```powershell
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp -q
  & 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m py_compile App\app.py App\decision_read_model.py App\candidates_page.py App\data_health_page.py Scripts\*.py
  git diff --check
  git status --short
  ```

- [ ] **Step 6: Write the release checklist.** Include database backup/restore, user-data migration checksum, duplicate append no-op, PR ingestion counts, decision materialization, market-cap audit, browser checks, and explicit rollback to the legacy decision view.
- [ ] **Step 7: Commit the release evidence.**

  ```powershell
  git add Scripts/compare_score_versions.py tests/test_score_comparison.py README.md docs/operations/eod-runbook.md docs/implementation/recovery-release-checklist.md
  git commit -m "docs: add MarketPulse recovery release gates"
  ```

## Execution order

Complete Tasks 1–4 before changing UI behavior. Task 5 may run after Task 2 but must finish before release. Task 6 is the first user-visible change. Task 7 is the release checkpoint; do not switch the production default or merge the branch before its gates pass.
