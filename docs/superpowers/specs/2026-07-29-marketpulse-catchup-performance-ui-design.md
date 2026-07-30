# MarketPulse Catch-Up, Performance, and Decision UI Design

Date: 2026-07-29
Status: Approved design, pending written-spec review

## 1. Purpose

MarketPulse needs a reliable recovery workflow for missed NSE trading sessions, a genuinely incremental database update, and a faster decision-oriented application.

The work is split into five ordered phases:

1. Manifest-based missed-session discovery, download, archive, and latest-input preparation.
2. Correct incremental database append with full-build reconciliation.
3. Full-build performance improvements.
4. Lazy application loading and query-service cleanup.
5. Decision dashboard, signal history, and outcome analysis.

Download preparation and database mutation remain separate user actions.

## 2. Current-State Findings

- The database contains market data through 2026-07-14.
- On 2026-07-29 at 09:52 IST, NSE had published ten later trading sessions through 2026-07-28.
- NSE can return a previous trading day's bhavcopy for a weekend URL with HTTP 200. The embedded `DATE1` value must therefore match the requested date.
- `Input/archive` contains suffix-based duplicates such as `bulk (47).csv`, making completeness and provenance difficult to determine.
- The existing append process reads new bhavcopies only from `Input/daily`, although catch-up files need to be archived while only the latest set remains in `Input/daily`.
- The append process loads the complete price table, recalculates all historical indicators, rebuilds every derived table and index, and rewrites the complete DuckDB.
- Append currently performs overlapping database backups, causing roughly two additional full-file copies.
- The database contains approximately 1.12 million price rows and 1.12 million indicator rows and is approximately 696 MB.
- The NiceGUI application is a single module of approximately 3,480 lines and contains about 53 database-read call sites.
- All visible tabs are constructed during initial page creation, and each database query normally opens a new connection.
- A local first HTTP response measured approximately 9.8 seconds.
- `strong_rs_stocks_page()` is defined twice.
- Sector Tree, VCP Lab, Backtest, and Journal functions exist but are not exposed by the main navigation.
- Historical indicator rows currently receive the latest loaded 52-week high/low values, which can introduce future-data leakage into historical analysis.

## 3. Goals

### 3.1 Catch-Up

- Determine the database's latest ingested trading date.
- Determine every later NSE trading session for which a complete report set is available.
- Download and validate all eight required reports for every missing session.
- Retain all downloaded files, including `PRDDMMYY.zip`, under a date-specific downloads directory.
- Publish earlier missed sessions to the archive.
- Leave only the latest complete report set in `Input/daily`.
- Stop without appending or rebuilding DuckDB.
- Be safe to rerun without duplicates or silent replacement.

### 3.2 Database

- Append only sessions not already ingested.
- Preserve exact rolling, EMA, RSI, weekly, and monthly indicator continuity.
- Update only affected derived dates and latest snapshots.
- Make normal append transactional and idempotent.
- Preserve a full rebuild as a repair, migration, and reconciliation tool.
- Eliminate historical future-data leakage from date-sensitive reference data.

### 3.3 Application

- Display a useful initial page within 2-4 seconds on a cold start.
- Load pages and expensive datasets only when requested.
- Make common page changes and filters feel immediate.
- Surface data freshness, preparation status, and database status.
- Organize the product around decisions and changes rather than disconnected screeners.

## 4. Non-Goals

- Catch-up will not automatically append the database.
- The initial implementation will not migrate away from NiceGUI or DuckDB.
- The application will not issue unexplained mechanical buy or sell instructions.
- The first phase will not redesign every existing table or visual component.
- Normal catch-up will not silently repair an already-ingested historical date whose source checksum has changed.

## 5. User Commands

`download.bat` will present:

```text
1. Prepare latest NSE trading day
2. Catch up all missing trading days
3. Enter one date manually
```

Date input remains `DDMMYYYY`, for example `03072026`.

The database commands remain separate:

```text
Append_MarketPulse.bat
Rebuild_MarketPulse.bat
```

`Append_MarketPulse.bat` performs a normal or multi-session incremental append. `Rebuild_MarketPulse.bat` creates and validates a complete replacement database.

## 6. Trading-Session Discovery

### 6.1 Starting Point

When DuckDB exists, automatic catch-up starts after:

```sql
SELECT max(trade_date) FROM prices_daily
```

When DuckDB does not exist, automatic catch-up requires a manually entered start date. It must not infer an arbitrary historical start.

Prepared but not ingested dates are identified from valid download manifests. They are shown separately from dates that still need network downloads.

### 6.2 Available Session Detection

For each calendar date after the database date through the current local date:

1. Request or discover the bhavcopy candidate.
2. Require HTTP success and a valid CSV header.
3. Parse a data row and require embedded `DATE1` to equal the candidate date.
4. Treat HTTP 404, a mismatched embedded date, or an unpublished current-day report as "not an available trading session."
5. Do not report the current date as an error when NSE has not yet published it.

The downloader must not rely only on weekdays or a hard-coded holiday calendar.

### 6.3 Preflight Report

Before downloading full report sets, print:

```text
Database through:       14-07-2026
Latest NSE data:        28-07-2026
Missing sessions:       10
Already prepared:        0
Need downloading:       10
```

The user confirms before full downloads begin.

## 7. Download and Validation

Each trading session requires:

- `sec_bhavdata_full_DDMMYYYY.csv`
- `mcapDDMMYYYY.csv`, extracted from `PRDDMMYY.zip`
- `CM_52_wk_High_low_DDMMYYYY.csv`
- `sec_list_DDMMYYYY.csv`
- `PE_DDMMYY.csv`
- `MADDMMYY.csv`
- `bulk.csv`
- `block.csv`

The date directory also retains `PRDDMMYY.zip`.

Files are staged under:

```text
Input/downloads/DDMMYYYY/
```

Each file is validated for:

- Non-empty content.
- Expected report header.
- Expected embedded report/trade date where the format provides one.
- Valid ZIP structure and expected mcap member.
- A parseable mcap file with its expected columns.
- Bulk/block schema or an explicit valid `NO RECORDS` result.
- Absence of HTML/error-page content.

Every non-`NO RECORDS` bulk/block row must contain the requested trading date. A
date-neutral "latest deals" download is invalid for a backdated request when its
rows belong to another date.

No archive or daily file is changed until every required trading session has a complete valid report set.

## 8. Download Manifest

Each date directory contains `manifest.json` with:

- Manifest schema version.
- Requested trading date.
- Discovery status.
- Overall preparation status: `incomplete`, `validated`, or `published`.
- Creation and last-validation timestamps.
- One entry per report containing:
  - Logical report type.
  - Local filename.
  - Source URL.
  - HTTP status.
  - Byte size.
  - SHA-256 checksum.
  - Embedded report date, when available.
  - Validation status and error text.
- Publication destinations.
- Database ingestion status as observed at preparation time.

An interrupted run may leave an `incomplete` manifest and partial files in `Input/downloads`. A rerun revalidates existing files and downloads only missing or invalid entries.

## 9. Archive and Daily Publication

Publication occurs only after all target manifests are `validated`.

### 9.1 Archive Naming

Date-neutral deal filenames become date-specific in the archive:

```text
bulk_DDMMYYYY.csv
block_DDMMYYYY.csv
```

Other reports retain their naturally dated names. ZIP files remain in `Input/downloads` and are not copied to the archive.

Suffixes such as `(2)` are no longer used:

- If the canonical archive path does not exist, publish it.
- If it exists with the same checksum, treat publication as already complete.
- If it exists with a different checksum, stop with a conflict and do not replace it automatically.

### 9.2 Publication Order

1. Create a publication journal describing every intended move/copy.
2. Validate that the current `Input/daily` set has one provable trading date. Derive
   it from bhavcopy `DATE1` and require every other dated report and non-empty deal
   row to agree. If the date cannot be proved, stop without changing the directory.
3. Archive the current contents of `Input/daily` using canonical date-specific names.
4. Publish all earlier missing sessions' CSV files to `Input/archive`.
5. Publish the latest session's eight CSV outputs to a temporary daily directory.
6. Validate the temporary daily directory.
7. Replace `Input/daily` with the validated latest set.
8. Mark affected manifests `published`.
9. Remove the publication journal.

If publication fails, use the journal to restore the previous daily set and remove only files created by the failed publication. Files already present before the run are never deleted.

## 10. Incremental Database Architecture

### 10.1 Ingestion Metadata

Add:

- `ingestion_batches`: batch ID, start/end dates, status, timestamps, application version, and error summary.
- `ingested_reports`: trading date, report type, source checksum, row count, manifest path, and batch ID.
- `indicator_state`: per-symbol recursive state needed to continue EMA and RSI calculations exactly.
- Date-keyed reference history for market cap, PE, price band, and 52-week high/low.

The uniqueness contract is one accepted checksum per trading date and logical report type. A rerun with the same checksums is a no-op.

### 10.2 Append Preflight

Append will:

1. Read `published` manifests in chronological order.
2. Compare them with `ingested_reports`.
3. Reject incomplete report sets.
4. Reject gaps between the database's latest date and the prepared range.
5. Show dates, files, and expected row counts.
6. Require confirmation before opening a write transaction.

Append reads prepared data through manifests and canonical archive/daily paths. It does not depend on all missed bhavcopies remaining in `Input/daily`.

### 10.3 Transaction

Within one DuckDB transaction:

1. Insert deduplicated new price rows.
2. Insert deduplicated deal rows.
3. Insert date-keyed reference rows.
4. Calculate new indicator rows.
5. Calculate breadth and sector-rotation rows for new dates.
6. Calculate screener results and signal-ledger changes for new dates.
7. Refresh latest snapshot tables.
8. Insert ingestion metadata.
9. Run consistency checks.
10. Commit.

Any failed consistency check rolls back the complete batch.

### 10.4 Exact Indicator Continuity

Incremental calculations must match a full-history calculation:

- Rolling values load the required preceding window, including the 252-session return/high/low history.
- Daily EMA values continue from the prior accepted EMA state using the same `adjust=False` recurrence.
- RSI continues from prior Wilder average-gain and average-loss state.
- Weekly and monthly aggregates and recursive states are persisted and updated only when their periods change.
- Cumulative database high continues from the prior accepted high.
- Divergence detection retains the preceding swing context required by the existing rule.
- Cross-sectional RS ranks are calculated across the complete symbol universe for each new date.
- Cross events compare the new value with the actual preceding accepted session.

If an already-ingested historical source changes, normal append stops and requests an explicit repair/rebuild from the earliest affected date.

### 10.5 Reference-Date Correctness

Historical indicators and backtests must join the 52-week, market-cap, PE, and price-band values available for that trading date. A later reference file must not rewrite historical context.

Where an exact daily reference is absent, the join may use the latest prior reference date, never a future date.

## 11. Full Rebuild

Full rebuild will:

1. Read only validated manifests and required static files.
2. Build a new temporary DuckDB.
3. Replay reports in chronological order using the same calculation rules as incremental append.
4. Preserve user-owned journal and watchlist data through an explicit export/import step.
5. Create indexes after bulk loading.
6. Run reconciliation and integrity checks.
7. Create one rotating backup of the accepted database.
8. Atomically replace the database only after validation passes.

Raw CSV-to-Parquet conversion may be added after incremental correctness is established. It is an optimization, not a prerequisite for correctness.

## 12. Backup Policy

- Normal append relies on DuckDB transaction rollback and does not copy the full database twice.
- A rotating backup is created on a schedule and before schema migrations or full replacement.
- Full rebuild creates one backup immediately before a validated atomic replacement.
- User journal/watchlist data is independently exportable.

## 13. Application Architecture

Keep NiceGUI and DuckDB, but split the monolith into:

- Application shell and navigation.
- One module per page.
- Shared table, chart, filter, and status components.
- A query service.
- A decision/signal service.
- Journal/watchlist write service.

Pages are routed or lazily rendered. Opening the application builds only the shell and Today page. Other pages query data when first opened.

The query service:

- Manages read-only connections rather than opening one connection for every small query.
- Combines related metrics into fewer queries.
- Caches immutable/latest snapshot results using a database-version key.
- Uses server-side filtering and pagination for large tables.
- Invalidates caches after a successful append or rebuild.

## 14. Navigation and Pages

### 14.1 Today

- Data readiness and missing-session status.
- Market regime and deterioration warnings.
- Changes since the preceding trading session.
- New, improved, and invalidated setups.
- Leading and weakening groups.
- Important institutional activity.
- Ranked preparation list with evidence and risks.

### 14.2 Market

- Breadth and participation.
- Sector and industry rotation.
- Market risk and concentration.
- Historical regime comparison.

### 14.3 Setups

- Momentum scanner.
- VCP and EMA screens.
- New signals and invalidations.
- Saved watchlists and preparation stages.

### 14.4 Deals

- Institutional buyers and sellers.
- Repeated client activity.
- Deal performance after 5, 10, and 20 sessions.
- Deal and technical confluence.

### 14.5 Research

- Stock detail.
- Historical leaders and backtests.
- Journal.
- Signal outcome analysis.

## 15. Decision Data

Every ranked candidate includes:

- Why it appeared.
- What changed on the latest session.
- Market regime.
- Sector and industry state.
- Relative strength and liquidity.
- Setup, trigger, and setup age.
- Institutional evidence.
- Invalidation condition.
- Data-quality and risk warnings.

The application ranks preparation candidates but does not hide the contributing evidence behind a single unexplained score.

## 16. Signal Ledger and Outcomes

The signal ledger records:

- Signal ID, symbol, setup type, first-seen date, last-seen date, and status.
- Trigger and invalidation details.
- Snapshot of regime, sector state, indicator values, and evidence at first appearance.
- Changes in rank and score while active.
- Exit/invalidation date.
- Forward 5-, 10-, and 20-session return.
- Maximum favourable excursion.
- Maximum adverse excursion.
- Outcome metrics grouped by setup, regime, sector, and liquidity range.

Outcome calculations use only information available as of each evaluation date and are covered by future-leakage tests.

## 17. Performance Targets

Measured on the current machine and dataset:

- One-session append: under 30 seconds.
- Ten-session catch-up append: under 90 seconds.
- Cold first useful application screen: 2-4 seconds.
- Warm page navigation: under 1 second for common pages.
- Failed append: no accepted database changes.
- Full rebuild: under 3-5 minutes after correctness is established.

Targets are acceptance benchmarks, not reasons to weaken reconciliation or validation.

## 18. Correctness and Test Strategy

### 18.1 Downloader

- Today, manual date, and automatic catch-up modes.
- Weekend URL returning a previous session with HTTP 200.
- Exchange holiday.
- Current-day report not yet published.
- Missing one of eight reports.
- Invalid HTML response.
- Corrupt ZIP or absent mcap member.
- Valid bulk/block `NO RECORDS`.
- Interrupted download and resume.
- Identical rerun.
- Archive checksum conflict.
- Publication failure and rollback.

### 18.2 Database

- One-session incremental append.
- Ten-session incremental append.
- Same batch rerun is a no-op.
- Gap rejection.
- Changed historical checksum rejection.
- Transaction rollback after an injected failure.
- Preservation of journal/watchlist data.
- Date-keyed reference joins never use a future date.

### 18.3 Reconciliation

Starting from the same accepted database and manifests:

1. Produce one result with incremental append.
2. Produce another result with a clean full rebuild.
3. Compare primary keys, row counts, date ranges, null patterns, and values for:
   - Prices.
   - Indicators.
   - Deals.
   - Breadth.
   - Sector rotation.
   - Screeners.
   - Signal ledger.
4. Require exact equality for identifiers, dates, booleans, and categories.
5. Treat paired null/NaN values as equal and require floating-point values to match
   with both absolute and relative tolerance of `1e-9` for EMA, RSI, percentiles,
   and derived scores. Any field requiring a wider tolerance must be justified
   explicitly in the test rather than changing the global tolerance.
6. Fail acceptance on any unexplained difference.

### 18.4 Application

- Only Today-page queries run on initial load.
- Other pages load on demand.
- Data freshness uses missing trading sessions, not calendar-day age.
- Cache invalidates when database version changes.
- Empty, stale, partial, and failed-update states are visible.
- Existing reachable workflows remain available after navigation restructuring.
- Broken encoded labels are removed.

## 19. Rollout

### Phase 1: File Preparation

- Add manifest and session discovery.
- Add catch-up mode.
- Add canonical archive naming and rollback publication.
- Retain latest-only daily behavior.

### Phase 2: Incremental Database

- Add ingestion/reference/state schema.
- Implement transactional append.
- Build full-versus-incremental reconciliation tests.
- Switch the normal append command only after reconciliation passes.

### Phase 3: Full Build

- Reuse the calculation engine and validated manifests.
- Remove duplicate backup work.
- Benchmark parsing, calculation, indexing, and write phases.
- Add Parquet only if measured parsing remains material.

### Phase 4: Application Performance

- Split pages and services.
- Add lazy loading, query consolidation, caching, and pagination.
- Remove duplicate/dead definitions and expose intended features.

### Phase 5: Decisions and Outcomes

- Build Today view.
- Add signal ledger and outcome calculations.
- Add explainable ranking, change detection, and risk context.

## 20. Acceptance

The system is accepted when:

- Catch-up correctly identifies and prepares all missing sessions.
- `Input/daily` contains only the latest complete set.
- Earlier complete CSV sets are canonical and discoverable in the archive.
- `Input/downloads` retains complete raw downloads and manifests.
- Catch-up never mutates DuckDB.
- Incremental append matches a full rebuild for the same inputs.
- Historical calculations contain no known future-date reference joins.
- Update and application performance targets are met or a measured bottleneck report explains any remaining variance.
