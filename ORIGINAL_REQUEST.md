# Original User Request

## Initial Request — 2026-09-14T12:38:25Z

Comprehensive audit, calculation verification, screener enhancement, and UI/UX stabilization for MarketPulse 2.0 — eliminating data fog, fixing UI interactions (sorting, arrows, toggles), and aligning trading logic (Darvas, VCP, RS, UC Thrust) with institutional and expert standards.

Working directory: d:\Sid\MarketPulse2.0
Integrity mode: development

## 🛠️ Relevant MCPs & Skills

| Tool / Skill | Role & Application |
|---|---|
| chrome-devtools-mcp | UI/Browser testing: inspect rendered Streamlit app, test clickable elements (stock arrows, timeframe toggles, sort headers), capture visual bugs, check console logs and network payload. |
| gemini-api-docs | Reference documentation for any LLM-powered insights or agentic features in MarketPulse. |
| /learn & agy-customizations | Persist verified trading rules (e.g., Manas Arora VCP parameters, Darvas 200EMA filter invariant) into workspace rules and skills. |
| MarketPulse Invariants (GEMINI.md) | Enforce core invariants: no silent truncation on symbol copy, flexible clipboard callbacks, no artificial stop-loss filtering, float near-zero formatting deadband, DuckDB cache invalidation. |

---

## Requirements

### R1. Critical UI Interaction & Navigation Fixes
- Column Sorting: Fix the sorting logic across all dataframe/table renderers so sorting lowest-to-highest and highest-to-lowest correctly orders numerical, percentage, and string columns without inverted or corrupted state.
- Stock Name Arrow Action: Fix the clickable arrow icon/button beside stock names across all tables to ensure it reliably triggers its intended action (e.g., TradingView chart pop-up, deep link, or stock inspection card).
- Global Tag Readability: Audit global badge/tag styling (contrast ratio, background colors, font size) to ensure readability across both light and dark themes.

### R2. Screener Logic & Invariant Enforcement
- DARVAS Squeeze EMA200 Invariant: In the Momentum tab (and any related screener), enforce that close > EMA200 is strictly respected for DARVAS Squeeze candidates (avoid showing stocks below 200 EMA).
- DARVAS Multi-Timeframe Support: Verify whether Darvas Squeeze and Darvas 10 EMA calculate correctly on Daily, Weekly, and Monthly timeframes; introduce an explicit Timeframe Toggle (Daily / Weekly / Monthly) directly in the screener control panel.
- VCP Screener Upgrade (Manas Arora Model): Upgrade the Volatility Contraction Pattern (VCP) detection logic incorporating Manas Arora's core principles:
  - Progressive contraction stages (T1 -> T2 -> T3/T4 with decreasing contraction depths).
  - Volume dry-up on the right side / final contraction.
  - Clear pivot / breakout readiness detection relative to 50 EMA and 200 EMA.
- UC Thrust Radar Audit: Verify mathematical formulas and detection rules for Upper Circuit (UC) thrust; validate signal accuracy against historical daily candle data, and create clear user guidance/field instructions on how to interpret and trade the radar.

### R3. Benchmark Relative Strength (RS) & Screener Alignment
- Benchmark RS Audit: Audit Relative Strength calculations to ensure they default to NIFTYMIDSML400 as the benchmark across all screener engines and charts.
- RS Screener Consistency: Verify RS percentile ranks, RS rating calculations, Mansfield RS, and momentum slopes across all RS screeners to ensure mathematical correctness and zero drift.

### R4. Sector Intel & Market Trends Overhaul
- Default Sector Intel View: Set the default view in Sector Intel across all pages and tabs to Broad Industry.
- Indices Verification: Audit calculations and data integrity for both broad Sectoral Indices and Thematic Indices.
- Data Fog Elimination: Remove visual clutter, redundant indicators, and duplicate metrics in Market Trends and Sector Intel to deliver a high-signal, clean executive view.

### R5. Data Consistency, Global Headers & Peer Status
- Standardized Column Headers & Colors: Establish a unified global naming convention and color palette for table headers (e.g., Price/Return, Volume, RS, Valuation, Momentum) so headers remain consistent across the entire application.
- Peer Status Alignment: Review peer comparison metrics against screener inputs; resolve any ambiguous or conflicting labels so peer data directly matches screener criteria.

### R6. Educational & Trading Artifacts Audit
- Trading Playbook & Field Guide: Audit the Trading Playbook and Field Guide tabs/cards for content quality, accuracy, relevance to active swing traders, and clarity of actionable rules.

---

## Acceptance Criteria

### 1. UI & Controls
- [ ] Clicking any column header sorts correctly ascending and descending on both numerical and textual data.
- [ ] The stock arrow link/action successfully opens the target view/chart for all tables.
- [ ] Tags/badges pass standard contrast accessibility tests.
- [ ] Screener timeframes can be toggled between Daily, Weekly, and Monthly for Darvas setups.

### 2. Screener Mathematics & Filters
- [ ] Zero stocks trading below EMA200 appear in DARVAS Squeeze momentum screens.
- [ ] VCP screener identifies multi-contraction stages and volume drying up consistent with the Manas Arora framework.
- [ ] UC Thrust Radar formulas are documented and verified with unit test / data check.
- [ ] RS screeners correctly benchmark against NIFTYMIDSML400 with consistent ratings across tabs.

### 3. Layout & Readability
- [ ] Sector Intel defaults to "Broad Industry" on initial load and across relevant navigation routes.
- [ ] Sector and Thematic index calculations are verified against raw closing data.
- [ ] Market Trends and Sector Intel screens are decluttered with clear hierarchy (Data Fog eliminated).
- [ ] Column header names and theme colors follow a single global dictionary/style system.
- [ ] Trading Playbook and Field Guide are reviewed, refined, and documented for practical user utility.
