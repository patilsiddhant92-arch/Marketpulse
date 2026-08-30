# MarketPulse P0–P2 Hardening Design

**Status:** Approved for implementation by the user request to fix the audit roadmap.

## Objective

Turn MarketPulse from an informative EOD research cockpit into a safer, clearer swing-trading decision desk. The implementation must make freshness, market regime, candidate state, sector universe, risk geometry, portfolio heat, and signal evidence explicit before adding new visual polish.

## Product decisions

1. Sector rotation always uses the full NSE taxonomy universe. The ₹1,000 Cr rule applies only to stock-candidate views and is displayed as a separate stock-eligibility rule.
2. Prepare and Observe are separate states. A Risk-Off market may still produce technically interesting Observe rows, but it must not present them as actionable Prepare rows.
3. Every decision surface carries one shared as-of/freshness state. Stale data is visible and non-actionable; Health and the header cannot disagree.
4. Existing focused-v2 data remains compatible, but corrected indicator semantics receive explicit versioned columns and a score-version bump when they affect candidate ranking.
5. Fundamentals are not fabricated from PE snapshots. The app exposes a visible “fundamentals unavailable” state and an evidence/calibration surface using the existing signal outcome tables.
6. The user/market database boundary is preserved. Portfolio writes remain isolated to the user database.

## Architecture

Add small pure read-model helpers for freshness, candidate gating, portfolio summaries, and signal evidence. Keep the NiceGUI router as a composition layer, but make the active pages consume those read models instead of embedding ambiguous SQL and state rules. Use additive DuckDB migrations for persisted data contracts and keep legacy column aliases during the transition.

The active decision flow becomes:

`Freshness → Market posture → Sector level/status → Prepare/Observe candidate → Stock 360 risk/event summary → Portfolio risk action`.

## Scope

### P0: decision safety

- Shared NSE-session freshness and stale-action banner.
- Explicit Risk-Off gate and separate Prepare/Observe counts.
- Candidate context fields visible in the Screener.
- Corrected ATR/high-distance/RS/geometry semantics with regression tests.
- Sector metrics presence/schema validation and full-universe rotation labels.
- Consistent market-cap null and threshold handling.

### P1: decision-desk usability

- Level-aware Sector Intel with strict/branch status filtering.
- Stock 360 action summary.
- Deals universe/filter transparency and client-type persistence/readout.
- Portfolio risk budget, heat, concentration, sizing guidance, and risk-field editing.
- Loading/error/empty states and compact table presets.

### P2: evidence and maintainability

- Signal outcome calibration cards and regime/setup breakdowns.
- CI test gate and migration/data-contract checks.
- Explicit fundamentals-unavailable state and provider boundary for future point-in-time fundamentals.
- Targeted extraction of remaining decision logic from the largest modules without deleting legacy user workflows.

## Non-goals

- No invented fundamental values or scraped source without an auditable point-in-time provider.
- No intraday execution, broker integration, or automatic trade placement.
- No deletion of user-owned Input files or portfolio data.

## Verification

Every behavior change receives a failing test before production code. The final gate includes the full pytest suite, Python compilation, temporary DuckDB migration/read-model tests, and live Codex-browser checks for freshness, status semantics, dark controls, sector levels, Stock 360, Deals, Portfolio, and Health.
