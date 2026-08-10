# MarketPulse Recovery Design

**Date:** 2026-08-10  
**Status:** Approved direction; implementation starts after plan review  
**Goal:** Restore a trustworthy EOD swing-trading decision workflow on the existing MarketPulse UI before attempting a visual redesign.

## Problem

The current production path is the legacy NiceGUI application in `App/app.py`. The partially integrated Luna branch is not the production path, its decision tables contain only `focused-v1`, and its read model does not enforce the ₹1,000 Cr market-cap gate. NSE PR ZIPs are downloaded, but only the market-cap CSV is consumed; announcements, corporate actions, band hits, high/low participation, and top-value membership are not persisted. Portfolio data and controls are also split between legacy tables and an unconnected user-data path.

The recovery must therefore prioritize data authority and operational correctness over navigation or styling changes.

## Product outcome

For every accepted NSE session, the app will provide one auditable snapshot for a swing trader:

1. `Today` shows a small ranked queue of names that pass the hard universe gates, including market cap, liquidity, price band, trigger geometry, stop width, and reward-to-risk.
2. `Candidates` exposes both eligible and blocked names with explicit reasons and the same filters used by `Today`.
3. `Portfolio` reads migrated user positions and supports create, edit, stop/target updates, sell, reopen, and delete with event history.
4. NSE PR inputs are visible as event, corporate-action, band, high/low, and top-value context rather than silently discarded.
5. `Data Health` distinguishes fresh market data from a missing or stale decision snapshot.

The existing research pages and their current visual language remain available until the replacement decision flow reaches parity.

## Architecture

Keep Python, NiceGUI, pandas, and DuckDB. Use the current `App/app.py` navigation as the first release surface and extract only the decision services needed to make it testable. The market database is read-only from the UI. A separate user database stores portfolio, journal, settings, and event history. The EOD pipeline stages and validates all reports, appends market data transactionally, ingests PR ZIP contents, then materializes a versioned `focused-v2` decision snapshot.

The decision layer has three explicit boundaries:

- **Universe gate:** `market_cap_cr >= 1000`, valid NSE equity series, minimum 20-day traded value, acceptable price band, and usable reference data.
- **Evidence/scoring:** bounded pillar scores and normalized trend, setup, participation, regime, event, and deal evidence.
- **Action state:** `Triggered`, `Prepare`, `Observe`, or blocked, with trigger, invalidation, risk, reward-to-risk, age, and reasons stored in `candidate_daily`.

`Today` consumes only the latest materialized decision snapshot. It may never silently fall back to an older score version. If the snapshot is absent or stale, the UI shows a diagnostic state instead of presenting misleading candidates.

## Data flow

```text
NSE reports + existing Input/downloads PR ZIP
        -> staged manifest/checksum validation
        -> market append transaction
        -> PR/event/corporate-action ingestion
        -> focused-v2 materialization for the accepted session
        -> Today / Candidates / Portfolio / Data Health read models
```

The production database is never rebuilt in place during tests. Temporary DuckDB copies and verified backups are mandatory for migrations, materialization, and reconciliation.

## Scope boundaries

### Included in recovery

- Correct market-cap and eligibility enforcement.
- Real focused-v2 materialization and historical comparison in shadow mode.
- PR ZIP ingestion for `an`, `bm`, `bc`, `bh`, `hl`, and `tt` reports.
- Separate user-data migration and functional portfolio commands.
- Legacy UI parity, explicit freshness/error states, and Chrome desktop/mobile verification.

### Deferred until the recovery passes

- New visual theme or complete navigation redesign.
- Automatic order placement or broker integration.
- Predictive ML claims or weight optimization.
- Public deployment or unauthenticated remote access.

## Release gates

The recovery cannot be called complete until all of the following are true:

- Latest `Today` rows are from the accepted market session and `focused-v2`.
- No `Today` row has market cap below ₹1,000 Cr or missing market cap.
- `Today` and `Candidates` agree under identical filters.
- Every blocked row exposes a machine-readable reason.
- PR-derived events and actions have non-zero ingestion counts for a fixture session and appear in candidate context.
- Portfolio CRUD and migration preserve rows and event history across a market-data rebuild.
- Data Health reports a failed/stale decision snapshot rather than `Healthy`.
- Existing research workflows remain reachable and the browser has no application-caused console errors at desktop and 390px widths.
- Focused-v1 and focused-v2 have been compared across at least 20 resolved sessions, or all available resolved sessions if fewer exist; the default switch is explicit and reversible.

## Verification baseline

The recovery branch starts from `main` at `c997afd`. The existing test suite currently reports one stale legacy-navigation assertion plus environment-specific pytest temporary-directory permission errors. These baseline issues must be isolated and corrected before claiming the recovery suite is green.
