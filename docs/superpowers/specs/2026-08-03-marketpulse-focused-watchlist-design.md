# MarketPulse Focused Watchlist and Decision Engine Design

Date: 2026-08-03  
Status: Proposed implementation specification  
Repository: `patilsiddhant92-arch/Marketpulse`

## 1. Purpose

MarketPulse already has broad NSE end-of-day coverage, strong technical feature engineering, market breadth, sector rotation, bulk/block deal analysis, screeners, VCP analysis, stock research, backtests, and a trade journal.

The next stage is not to add more disconnected indicators or screens. The goal is to convert the existing system into a focused daily decision workflow that answers:

1. Is the market environment supportive for new positions?
2. Which stocks require attention today?
3. What changed since the previous session?
4. What is the trigger, invalidation, and risk for each candidate?
5. Which candidates improved, stalled, triggered, or failed?
6. Which signals have historically worked in comparable regimes?

The product should behave as a decision system rather than a collection of screeners.

## 2. Current System Summary

MarketPulse currently uses the following NSE inputs:

- Daily security bhavcopy with OHLC, volume, turnover, trades, delivery quantity, and delivery percentage.
- Equity universe and sector/industry mappings.
- Market capitalization.
- Security price bands.
- Symbol and adjusted PE.
- Adjusted 52-week high and low.
- Bulk deals.
- Block deals.
- NSE Market Activity report downloads.

The derived system includes:

- Daily, weekly, and monthly EMA features.
- Multi-period returns.
- Cross-sectional relative-strength percentiles.
- RSI and divergence flags.
- ATR and volatility contraction.
- Volume and delivery measures.
- VCP component scores and states.
- Candlestick and structural screeners.
- Breadth and participation regimes.
- Sector and industry rotation.
- Institutional deal enrichment.
- Today preparation ranking.
- Focus List ranking.
- Momentum Scanner rules.
- Journal and historical leader analysis.

## 3. Main Findings

### 3.1 Point-in-time reference leakage

The historical indicator build currently merges the latest loaded 52-week high and low across all historical rows. Market capitalization, PE, and price-band data are also treated primarily as latest snapshots.

This can contaminate historical:

- Near-52-week-high signals.
- Distance-to-high features.
- VCP classifications.
- Candidate rankings.
- Backtests.
- Machine-learning labels and validation.

All historical calculations must use information available on or before the evaluated trading date.

### 3.2 Multiple ranking engines

The Today preparation list, Focus List, and Momentum Scanner use overlapping but different rules and weights. A stock can therefore receive inconsistent priority depending on the page being viewed.

The system needs one canonical candidate engine. Pages may apply different views and filters, but must not independently redefine the investment thesis.

### 3.3 Navigation reflects tools rather than decisions

The application exposes many top-level tabs. Lazy loading improves speed, but the navigation still requires the user to decide which tool to inspect before the application has identified what matters.

The primary workflow should be:

- Today.
- Watchlist.
- Research.

Existing specialist pages should remain available under Research.

### 3.4 The downloaded Market Activity report is not fully used

The Market Activity file includes official index-level daily OHLC data for broad-market, size, sector, strategy, and thematic indices. It should be parsed into a historical index table and used for benchmark-relative and sector-relative analysis.

### 3.5 Watchlist candidates lack explicit decision levels

Candidate pages provide setup evidence, but do not consistently calculate:

- Trigger price.
- Invalidation price.
- Distance to trigger.
- Initial risk percentage.
- First resistance.
- Reward-to-risk estimate.

A candidate without these values still requires a second manual analysis step before action.

### 3.6 Outcome validation is not yet the ranking authority

The system has many manually weighted features, but does not yet use a complete signal ledger to show expected outcomes by setup, market regime, sector state, liquidity, and candidate score bucket.

The ranking system should become evidence-driven through walk-forward outcome analysis.

## 4. Goals

### 4.1 Product goals

- Reduce the primary navigation to a decision-first workflow.
- Surface a maximum of 10 to 15 high-priority candidates on the main Today page.
- Persist candidate states across sessions.
- Explain every rank through independent score pillars.
- Show what changed since the prior trading session.
- Show trigger, invalidation, and risk before a stock reaches Triggered state.
- Preserve all existing research tools without making them primary navigation items.

### 4.2 Data goals

- Make all historical features point-in-time correct.
- Adjust historical prices and volumes for corporate actions.
- Parse the NSE Market Activity report into index history.
- Create benchmark-relative and sector-relative strength features.
- Normalize institutional deal activity by liquidity and market capitalization.
- Add event-risk data for results, board meetings, and material corporate events.

### 4.3 Validation goals

- Track every signal from first appearance through invalidation or expiry.
- Calculate forward returns, maximum favourable excursion, and maximum adverse excursion.
- Validate setup performance using date-grouped walk-forward testing.
- Prevent future leakage through automated tests.
- Version every scoring formula and retain pillar-level contributions.

## 5. Non-Goals

- The application will not provide unexplained mechanical buy or sell instructions.
- The first implementation will not replace NiceGUI or DuckDB.
- The first implementation will not add large numbers of new oscillators or candlestick patterns.
- PE will not become a dominant short-term ranking factor.
- Derivatives data will not penalize non-F&O stocks.
- Bulk and block deal value will not be treated as positive evidence without normalization and context.

## 6. Recommended Product Structure

### 6.1 Today

The Today page is the only required starting screen.

It should contain:

#### Market gate

- Current regime: Constructive, Selective, Defensive, or Risk-Off.
- Breadth trend.
- Nifty 500 trend.
- Large-cap, mid-cap, and small-cap participation.
- Sector concentration.
- Deterioration warnings.

#### What changed

- New candidates.
- Candidates that improved state.
- Candidates that deteriorated.
- Newly triggered candidates.
- Invalidated candidates.
- New institutional activity.
- Major event-risk changes.

#### Focused preparation list

Show no more than 10 to 15 names by default.

Required columns:

- Symbol.
- Watchlist state.
- Why now.
- Latest change.
- Leadership score.
- Setup score.
- Participation score.
- Context score.
- Risk score.
- Trigger price.
- Invalidation price.
- Distance to trigger.
- Initial risk percentage.
- Event warning.
- Setup age.

### 6.2 Watchlist

The Watchlist owns persistent candidate lifecycle state.

Each candidate must be in one of these states:

```text
Observe -> Prepare -> Triggered -> Invalidated
```

Optional terminal states:

```text
Expired
Removed
Completed
```

State definitions:

#### Observe

The stock has leadership or accumulation evidence but does not yet have a sufficiently mature setup.

#### Prepare

The setup is actionable enough to define trigger and invalidation levels, but the trigger has not occurred.

#### Triggered

The defined trigger condition has occurred with required confirmation.

#### Invalidated

The stock violated the invalidation rule, lost structural quality, or failed after triggering.

The watchlist should preserve a stock across sessions. Temporary failure of one filter must not silently delete its history.

### 6.3 Research

Research should contain the existing specialist tools:

- Market Health.
- Sector Rotation.
- Strong Groups.
- Screeners.
- VCP Lab.
- Momentum Scanner.
- Deals.
- Stock Detail.
- Sector Tree.
- Leaders Study.
- Journal.

These pages should consume shared feature and candidate services rather than recalculate conflicting rankings.

## 7. Point-in-Time Data Architecture

### 7.1 Security reference history

Create a date-keyed table:

```sql
CREATE TABLE security_reference_daily (
    symbol TEXT,
    effective_date DATE,
    source_date DATE,
    market_cap_cr DOUBLE,
    pe DOUBLE,
    adjusted_pe DOUBLE,
    price_band DOUBLE,
    band_remarks TEXT,
    high_52w DOUBLE,
    high_52w_date DATE,
    low_52w DOUBLE,
    low_52w_date DATE,
    source_checksum TEXT,
    PRIMARY KEY (symbol, effective_date)
);
```

Historical joins must use the latest record where:

```sql
reference.effective_date <= indicator.trade_date
```

A future-dated reference must never be applied to an earlier indicator row.

### 7.2 Corporate action history

Create:

```sql
CREATE TABLE corporate_actions (
    symbol TEXT,
    ex_date DATE,
    action_type TEXT,
    ratio_from DOUBLE,
    ratio_to DOUBLE,
    cash_amount DOUBLE,
    description TEXT,
    source_checksum TEXT,
    PRIMARY KEY (symbol, ex_date, action_type, description)
);
```

Create an adjustment-factor table:

```sql
CREATE TABLE price_adjustment_factors (
    symbol TEXT,
    trade_date DATE,
    price_factor DOUBLE,
    volume_factor DOUBLE,
    PRIMARY KEY (symbol, trade_date)
);
```

All long-history indicators, returns, highs, lows, and backtests should use adjusted OHLCV.

### 7.3 Index history

Parse the NSE Market Activity file into:

```sql
CREATE TABLE index_daily (
    trade_date DATE,
    index_name TEXT,
    previous_close DOUBLE,
    open_price DOUBLE,
    high_price DOUBLE,
    low_price DOUBLE,
    close_price DOUBLE,
    change_value DOUBLE,
    return_1d_pct DOUBLE,
    PRIMARY KEY (trade_date, index_name)
);
```

Derived index features:

- Return over 5, 20, 63, 126, and 252 sessions.
- EMA 20, 50, and 200.
- Distance from EMA.
- New 20-day and 52-week highs.
- Index volatility.
- Trend state.

### 7.4 Event history

Create:

```sql
CREATE TABLE security_events (
    symbol TEXT,
    event_date DATE,
    event_type TEXT,
    headline TEXT,
    source_id TEXT,
    source_checksum TEXT,
    PRIMARY KEY (symbol, event_date, event_type, source_id)
);
```

Initial event types:

- Financial results.
- Board meeting.
- Dividend.
- Bonus.
- Split.
- Rights issue.
- Merger or demerger.
- Major corporate announcement.

Derived fields:

- Days to next result.
- Days to next board meeting.
- Event within 1, 3, 5, or 10 sessions.
- Event-risk state.

## 8. Canonical Candidate Engine

Create a materialized daily table:

```sql
CREATE TABLE candidate_daily (
    trade_date DATE,
    symbol TEXT,
    score_version TEXT,
    candidate_state TEXT,
    leadership_score DOUBLE,
    setup_score DOUBLE,
    participation_score DOUBLE,
    context_score DOUBLE,
    risk_score DOUBLE,
    total_score DOUBLE,
    rank_overall INTEGER,
    rank_in_sector INTEGER,
    why_now TEXT,
    latest_change TEXT,
    risk_summary TEXT,
    trigger_price DOUBLE,
    invalidation_price DOUBLE,
    first_resistance DOUBLE,
    distance_to_trigger_pct DOUBLE,
    initial_risk_pct DOUBLE,
    reward_to_risk DOUBLE,
    setup_first_seen DATE,
    setup_age_sessions INTEGER,
    event_risk TEXT,
    data_quality_flags TEXT,
    PRIMARY KEY (trade_date, symbol, score_version)
);
```

### 8.1 Pillar 1: Leadership

Leadership should measure independent relative performance.

Recommended features:

- Existing multi-quarter RS percentile.
- Pure 12-month RS percentile.
- 3-month RS percentile.
- Return versus Nifty 500 over 20 and 60 sessions.
- Return versus mapped sector index over 20 and 60 sessions.
- RS-line slope.
- RS-line new high.
- Rank improvement over 5 and 20 sessions.

Example normalized pillar:

```text
Leadership =
    25% multi-quarter RS percentile
  + 15% 12-month RS percentile
  + 15% 3-month RS percentile
  + 20% benchmark-relative strength
  + 15% sector-relative strength
  + 10% rank acceleration
```

Do not reward raw one-month return again if it is already substantially represented in relative-strength features.

### 8.2 Pillar 2: Setup

Recommended features:

- Trend qualification.
- Contraction quality.
- Volume dry-up.
- Pivot proximity.
- Tightness near high.
- EMA support quality.
- Trigger clarity.
- Setup age.
- Failed-trigger history.

The existing VCP components should feed this pillar rather than being added again as an independent total-score feature.

### 8.3 Pillar 3: Participation

Recommended normalized features:

- Turnover z-score versus 20-day history.
- Delivery-percentage z-score.
- Delivery-quantity z-score.
- Close location in the daily range.
- Up-volume versus down-volume over 20 sessions.
- Bulk/block deal value divided by 20-day traded value.
- Deal quantity divided by session volume.
- Net deal value divided by market capitalization.
- Repeated-client activity with recency decay.

Absolute deal value must not dominate the score.

### 8.4 Pillar 4: Context

Recommended features:

- Market gate.
- Nifty 500 trend.
- Size-index trend.
- Sector index trend.
- Equal-weighted sector breadth.
- Sector rotation state.
- Industry rotation state.
- Sector and industry rank acceleration.

A strong stock in a weak group may remain Observe rather than Prepare unless stock-specific strength is exceptional.

### 8.5 Pillar 5: Risk

Risk is a penalty or gate, not an alpha score.

Recommended factors:

- Average traded value.
- Impact cost when available.
- Price band restriction.
- ATR percentage.
- Extension above support.
- Distance to invalidation.
- Failed breakout state.
- Event proximity.
- Corporate-action discontinuity.
- Data-quality warnings.

### 8.6 Total score

Initial proposed structure:

```text
Total score =
    30% Leadership
  + 25% Setup
  + 20% Participation
  + 15% Context
  + 10% Risk Quality
```

This is an initial version only. Weights must later be calibrated through walk-forward outcome analysis.

Every saved score must include:

- Score version.
- Pillar contributions.
- Data-quality flags.
- State transition reason.

## 9. Trigger and Invalidation Framework

Every Prepare candidate must have explicit levels.

### 9.1 Trigger candidates

Possible trigger definitions:

- Break above pivot or recent resistance.
- New 20-day high with minimum turnover confirmation.
- Close above a defined setup high.
- Reclaim of 20 EMA, 50 EMA, or 200 EMA with confirmation.
- Breakout from NR7, inside bar, or tight-range structure.

The trigger definition must be stored as structured fields, not only text.

### 9.2 Invalidation candidates

Possible invalidation definitions:

- Close below setup low.
- Close below 20 EMA or 50 EMA, depending on setup.
- Close below the most recent contraction low.
- Failed breakout followed by loss of pivot.
- Excessive extension without confirmation.

### 9.3 Risk calculations

Calculate:

```text
distance_to_trigger_pct = (trigger_price / close_price - 1) * 100
initial_risk_pct = (trigger_price / invalidation_price - 1) * 100
reward_to_risk = (first_resistance - trigger_price) / (trigger_price - invalidation_price)
```

Rows with missing or invalid risk geometry must not advance to Prepare.

## 10. Signal Ledger and Outcome Engine

Create:

```sql
CREATE TABLE signal_ledger (
    signal_id TEXT PRIMARY KEY,
    symbol TEXT,
    setup_type TEXT,
    score_version TEXT,
    first_seen_date DATE,
    last_seen_date DATE,
    trigger_date DATE,
    invalidation_date DATE,
    expiry_date DATE,
    status TEXT,
    initial_score DOUBLE,
    peak_score DOUBLE,
    trigger_price DOUBLE,
    invalidation_price DOUBLE,
    market_regime TEXT,
    sector_state TEXT,
    industry_state TEXT,
    feature_snapshot JSON,
    state_history JSON
);
```

Create outcome fields or a related table for:

- Forward close return after 5, 10, 20, and 60 sessions.
- Maximum favourable excursion over 5, 10, 20, and 60 sessions.
- Maximum adverse excursion over 5, 10, 20, and 60 sessions.
- Trigger-to-invalidation result.
- Time to trigger.
- Time to failure.

Outcome summaries must be available by:

- Setup type.
- Score bucket.
- Market regime.
- Sector state.
- Liquidity bucket.
- Market-cap bucket.
- Event-risk state.
- Setup age.

## 11. Machine-Learning Validation Changes

The current VCP classifier should not be production-facing until the following are corrected:

- If the target is a move occurring within 20 sessions, use maximum future high over the next 20 sessions rather than only the twentieth-session close.
- Split training and test data by complete dates, not arbitrary rows.
- Prevent the same trading date from appearing in both training and test sets.
- Use walk-forward or expanding-window validation.
- Report out-of-sample precision, recall, ROC AUC, PR AUC, hit rate, and calibration.
- Compare the model against simple baselines.
- Include transaction-risk and drawdown outcomes, not only target hits.
- Train only on point-in-time-correct features.

The model should initially be displayed as a research probability, not included in the production candidate score.

## 12. Additional NSE Data Priorities

### Priority 1

#### Corporate actions

Required for adjusted historical data and leakage-free indicators.

#### Market Activity indices

Already downloaded and immediately useful for benchmark and sector context.

#### Results and board-meeting calendar

Required for event-risk warnings.

### Priority 2

#### Daily volatility and impact cost

Use as liquidity and risk gates.

#### Short-selling and margin-trading disclosures

Use as contextual warnings for speculative participation.

### Priority 3

#### F&O bhavcopy and open interest

Use only for F&O-eligible stocks as an optional confirmation pillar.

Possible fields:

- Futures open-interest change.
- Price/open-interest quadrant.
- Rollover.
- Basis.
- Option open-interest concentration.
- MWPL usage.

#### Shareholding, insider trading, SAST, and pledge changes

Use in Stock Detail and deeper research rather than as dominant daily-ranking inputs.

## 13. Indicators to Add

### Required

- Stock relative strength versus Nifty 500.
- Stock relative strength versus mapped sector index.
- RS-line slope and RS-line new high.
- Turnover z-score.
- Delivery z-score.
- Up-volume/down-volume ratio.
- Normalized institutional deal activity.
- Trigger price.
- Invalidation price.
- Distance to trigger.
- Initial risk percentage.
- Reward-to-risk estimate.
- Setup age.
- Days since improvement.
- Failed-trigger count.
- Event-risk state.
- Historical setup expectancy.

### De-emphasize

- Additional generic oscillators.
- Additional candlestick pattern counts.
- Raw PE as a short-term ranking signal.
- Raw deal value.
- Multiple scores representing the same momentum evidence.
- A total score without pillar-level explanation.

## 14. Application Architecture

Refactor the application toward:

```text
App/
  app.py
  shell.py
  pages/
    today.py
    watchlist.py
    research.py
    market.py
    setups.py
    deals.py
    stock_detail.py
    journal.py
  components/
    tables.py
    charts.py
    filters.py
    status.py
  services/
    query_service.py
    candidate_service.py
    watchlist_service.py
    signal_service.py
    journal_service.py

Scripts/
  ingestion/
  features/
  signals/
  outcomes/
  migrations/
  validation/
```

Architecture requirements:

- Database migrations must not run implicitly from normal UI startup.
- The application must use a shared query service.
- Latest snapshot queries should be cached by database version.
- Candidate tables should be materialized after successful EOD ingestion.
- Pages should not independently recreate scoring SQL.
- User-owned watchlist and journal data must survive rebuilds.

## 15. Testing Strategy

### 15.1 Point-in-time tests

- A reference file dated after a historical row must never affect that row.
- Rebuilding with a later 52-week file must not change earlier historical features.
- Corporate actions must not create false return spikes or EMA crosses.
- Index-relative features must use only data available on the evaluated date.

### 15.2 Candidate consistency tests

- Today and Focus List must return the same candidate order when using the same filters and score version.
- Every displayed total score must equal the stored pillar sum.
- Every Prepare candidate must have a valid trigger and invalidation.
- Candidate state transitions must be deterministic and auditable.

### 15.3 Incremental build tests

- Incremental append must match a full rebuild for the same source set.
- Appending the same manifest twice must be a no-op.
- A failed append must leave the accepted database unchanged.
- Candidate and signal history must not be overwritten by a rebuild.

### 15.4 Outcome tests

- Forward-return calculations must use exact future trading sessions.
- MFE and MAE windows must not include bars outside the requested horizon.
- Walk-forward folds must not share dates.
- Historical outcome summaries must exclude unresolved forward windows.

### 15.5 UI tests

- Today must load without constructing all Research pages.
- Primary navigation must contain Today, Watchlist, and Research.
- State changes must persist after restart.
- Hidden research pages must remain accessible.
- No candidate should disappear without a stored transition reason.

## 16. Implementation Phases

### Phase 1: Correctness foundation

- Add date-keyed reference tables.
- Add corporate-action ingestion and adjustment factors.
- Remove future reference leakage.
- Add reconciliation tests.
- Rebuild historical features.

Acceptance criteria:

- Historical features are stable when later reference files are added.
- Corporate actions do not create false signals.
- Incremental and full builds reconcile.

### Phase 2: Market context

- Parse Market Activity index data.
- Build index history and trend features.
- Map stocks to sector indices.
- Add benchmark-relative and sector-relative strength.
- Add market gate states.

Acceptance criteria:

- Every candidate has benchmark and sector-relative context where mappings exist.
- Today shows official index context alongside stock-derived breadth.

### Phase 3: Canonical candidate engine

- Create `candidate_daily`.
- Implement five score pillars.
- Move Today and Focus List to the canonical service.
- Add score versioning and explanations.
- Normalize deal activity.

Acceptance criteria:

- Candidate order is consistent across pages.
- Every rank is explainable by stored pillar contributions.
- No duplicated page-specific scoring formula remains.

### Phase 4: Persistent watchlist states

- Add Observe, Prepare, Triggered, and Invalidated state logic.
- Add trigger and invalidation calculations.
- Add setup age and deterioration tracking.
- Create the Watchlist page.
- Simplify primary navigation.

Acceptance criteria:

- Candidate lifecycle persists across sessions.
- Every state transition has a reason.
- Prepare candidates have valid risk geometry.

### Phase 5: Signal outcomes

- Create the signal ledger.
- Calculate forward returns, MFE, and MAE.
- Build expectancy views by setup and regime.
- Add setup calibration reports.

Acceptance criteria:

- Every material setup can be evaluated using point-in-time outcomes.
- Historical evidence is visible beside the candidate decision.

### Phase 6: Event and optional derivatives context

- Add results and board-meeting calendars.
- Add event-risk flags.
- Add volatility and impact-cost data.
- Optionally add F&O confirmation for eligible stocks.

Acceptance criteria:

- Event risk is visible before a stock reaches Triggered state.
- Derivatives fields do not penalize cash-only securities.

### Phase 7: Model research

- Correct classifier labels.
- Add date-grouped walk-forward validation.
- Compare models with deterministic baselines.
- Display probability only in research views until validated.

Acceptance criteria:

- Model metrics are fully out-of-sample.
- Model performance is stable across regimes and liquidity groups.
- The model adds measurable value beyond the deterministic score.

## 17. Definition of Done

The focused-watchlist redesign is complete when:

- Historical calculations are point-in-time correct.
- Corporate actions are handled consistently.
- Market Activity index data is parsed and used.
- One canonical candidate table powers all focused views.
- The main navigation is decision-first.
- Candidates persist through a defined lifecycle.
- Trigger, invalidation, and risk are visible before action.
- Deal activity is normalized.
- Every score is versioned and explainable.
- Signals have audited outcome histories.
- Walk-forward tests show how the system performs by regime.
- Existing research and journal capabilities remain available.

## 18. Recommended Immediate Work Order

The first implementation sequence should be:

1. Point-in-time security-reference history.
2. Corporate-action adjustment.
3. Market Activity index parser.
4. Benchmark-relative and sector-relative strength.
5. Canonical candidate table and shared score service.
6. Persistent watchlist lifecycle.
7. Trigger and invalidation framework.
8. Signal ledger and outcome analytics.
9. Event-risk ingestion.
10. Optional derivatives confirmation and model research.

Do not add more tabs or generic indicators before these items are complete.
