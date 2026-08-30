# MarketPulse EOD Technical Desk — Near-Term Implementation Design

**Status:** Approved for local implementation

**Source:** `2026-08-16-marketpulse-eod-technofunda-design.md`

## Objective

Turn MarketPulse into a trustworthy EOD swing/technical desk while leaving all fundamental-source and technofunda work parked. The home product remains the existing `focused-v2` decision queue.

## Scope

The implementation covers the near-term PRs in the source design:

1. Remove the Gemini thematic universe from the runtime path and make Sector Intel taxonomy-first.
2. Stop committing downloaded/archive input artifacts in CI while preserving local daily files.
3. Extract indicator formulas into a pure, testable module; pin the current SMA ATR definition; add Wilder ATR and corrected distance/RS columns additively.
4. Make PROP a first-class deal clientele and include it by default in read models and Telegram lists.
5. Replace the sector view's thematic presentation with computed taxonomy metrics.
6. Move the UI toward a dark, fixed-width terminal table and make the app router thinner without changing the user database boundary.
7. Merge Today and Candidates into a focused-v2 Screener page with `Prepare`, `Observe`, and `Blocked / DIAG` states.

## Explicitly out of scope

- No screener.in, XBRL, yfinance, promoter, pledge, revenue, PAT, ROE, ROCE, FCF, or other new fundamental source.
- No `fundamentals_job`, `funda.yml`, `technofunda_score.py`, `screener_daily`, or `MP_HOME_LIST` flip.
- No change to the focused-v2 ₹1,000 Cr / ₹10 Cr ADV policy.
- No overwrite of `indicators_daily.atr_14`; it remains the production SMA ATR.
- No adoption of `nsetools-marketpulse`.
- No deletion of user-owned or pre-existing `Input/` changes.

## Architecture

`Scripts/indicators.py` will contain pure pandas functions for EMA, Wilder RSI, current SMA ATR, parallel Wilder ATR, RVOL, RS, distance, and base-quality helpers. `Scripts/build_database.py` remains the orchestration layer and calls those functions, preserving existing output columns and adding only explicitly versioned columns.

Deals will expose the new `clientele` taxonomy while retaining deprecated `tier`, `category`, and `is_hft` compatibility fields for one release. PROP is included by default; legacy `exclude_hft=True` remains a compatibility alias that omits PROP only when explicitly passed.

The UI will use a fixed column specification in `App/ui/table.py`, while legacy pages continue to receive the existing `table_from_df` callable during the transition. The active navigation will become Screener, Sectors, Deals, Portfolio, and Health; legacy labs remain reachable only through an explicit environment flag until fully removed.

## Verification

Every behavior change gets a failing test first. The existing 78-test suite must remain green, with new tests covering indicator formulas, additive schema columns, clientele classification fixtures, default PROP inclusion, fixed table widths, taxonomy-only Sector Intel wiring, and Screener focused-v2 reads. Full-pipeline or DuckDB rebuild tests will use temporary databases and will not mutate the local market database.

