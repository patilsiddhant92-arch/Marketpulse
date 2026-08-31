# MarketPulse 2.0: Premium Trading-Desk UI Design

**Date:** 2026-08-31
**Status:** Design approved in conversation; implementation not started
**Scope:** Visual system, information hierarchy, tables, charts, responsive behavior, and Stock 360 presentation

## Design decision

MarketPulse should feel like an institutional trading desk and decision cockpit for an EOD swing trader. The product should lead the eye through one repeatable sequence:

```text
Market posture → leadership groups → Prepare queue → Stock 360 confirmation
```

The recommendation is a refined dark graphite interface with a warm gold hierarchy accent. Green, red, amber, cyan, and blue remain semantic signals rather than decoration. The visual system should make the existing market data easier to scan without changing the underlying data pipeline, scoring logic, or user workflows.

This is a focused visual redesign, not a greenfield rewrite. The existing NiceGUI + DuckDB architecture, page routing, read-only market database, user database, EOD workflow, and existing research surfaces remain the product spine.

## Current context

The current application already has several useful foundations:

- `App/app.py` owns the NiceGUI shell and routes the active pages: Desk, Momentum, Template, Sectors, Deals, Portfolio, and Health.
- `App/ui/styles.py` contains shared dark tokens, typography, status colors, table rules, buttons, toolbars, and responsive overrides.
- `App/ui/table.py` contains tested `ColumnSpec` contracts for swing and screener tables.
- `App/ui/widgets.py` contains reusable KPI, heatmap, line-chart, grouped-chart, and deal-flow components.
- `App/ui/shell.py` contains page headers, empty states, and filter-bar primitives.
- `App/ui/stock_drawer.py` provides the Stock 360 dialog and its technical, institutional, risk, and event tabs.
- `App/pages/desk.py`, `App/candidates_page.py`, `App/pages/screener.py`, and the research pages already expose the core data needed for a premium desk.

The main visual problem is inconsistency rather than lack of capability. The shared stylesheet mixes a dark terminal palette with legacy light-theme utility classes, page-specific compatibility overrides, hardcoded chart colors, and overlapping table rules. The renderer has explicit width logic, but the active table CSS also uses `width: max-content` and auto layout in places, so a long text field can donate too much or too little space to neighboring columns. The result is a product that contains the right primitives but does not yet feel like one product.

## Goals

1. Give every page the same premium visual language and spacing rhythm.
2. Make the Desk page the clearest first-paint experience for the trader's morning sequence.
3. Make tables dense enough for research but comfortable enough for sustained reading.
4. Make numeric columns, symbols, states, and evidence visually distinct without relying on color alone.
5. Give charts a consistent theme, scale, legend, tooltip, and responsive behavior.
6. Preserve meaningful content at desktop, tablet, and phone widths without page-level horizontal overflow.
7. Use progressive disclosure so the primary view remains focused while advanced columns and diagnostics remain available.
8. Keep visual changes testable through shared components and stable contracts.

## Non-goals

- No new market data source, live ticker, WebSocket feed, broker integration, or order-entry workflow.
- No change to candidate scoring, EOD calculations, database schemas, or signal semantics in this UI slice.
- No new sixth score, visual similarity score, or decorative “health” score.
- No replacement of NiceGUI, Quasar, DuckDB, or the existing local-first application model.
- No large illustration system, stock photography, animated trading wallpaper, or decorative graphics that compete with data.
- No broad cleanup of unrelated business logic in `App/app.py`.
- No attempt to make the visual redesign hide stale, missing, or non-actionable data.

The existing EOD swing-desk product design remains the source of truth for domain naming and future Desk/Watch/Research information architecture. This document defines how those surfaces should look and behave.

## Alternatives considered

### A. Refined institutional dark desk — selected

Keep the existing dark terminal direction, replace conflicting tokens with one neutral graphite palette, reduce visual noise, and use warm gold as a restrained hierarchy accent. This preserves the product's current identity, works well for dense tables and charts, and lets green/red carry market meaning.

### B. Light research-terminal interface

Use a warm white canvas, ink text, thin gray rules, and teal/gold accents. This would make long tables comfortable in bright environments, but it would require a larger migration of existing dark page overrides and would weaken the current champion-desk identity.

### C. High-contrast neon trading interface

Use a black canvas with vivid cyan, lime, red, and magenta accents. This would feel energetic, but it would over-emphasize secondary signals, reduce calm reading time, and make dense tables look like a monitoring console rather than a decision workspace.

The selected direction gives MarketPulse a distinctive identity while requiring the least conceptual disruption.

## Experience principles

### Signal hierarchy over surface decoration

The strongest contrast belongs to the current decision, the symbol, the actionable price levels, and the market state. Borders, shadows, and fills are supporting structure only.

### One glance, one answer

Every primary surface should answer what the trader needs next. A Desk view should not require opening several competing tables before the trader knows whether the tape is constructive, which groups lead, and which names deserve confirmation.

### Data density with breathing room

Density comes from removing duplicated labels and unnecessary wrappers, not from shrinking type or stacking more cards. Use a 4px spacing grid and a stable row rhythm.

### Color carries meaning

Green means positive participation or flow, red means negative movement or risk, amber means caution, and blue/cyan means contextual information. Gold marks hierarchy and primary actions; it does not mean “good.”

### Progressive disclosure

The default view shows the smallest useful set of columns. Advanced columns, diagnostic reasons, and longer evidence are available through a deliberate control or Stock 360 rather than forcing every detail into the first table.

### Stable behavior beats clever motion

Use short transitions for hover and state changes. Do not animate the initial dashboard, continuously pulse data, or make a chart move while the trader is reading it. Honor reduced-motion preferences.

## Visual system

### Color tokens

The implementation should consolidate shared values in `App/ui/styles.py`. Page code and chart builders should consume semantic tokens rather than literal hex values.

| Token | Suggested value | Purpose |
| --- | --- | --- |
| `--mp-bg` | `#080C12` | Main application canvas |
| `--mp-surface` | `#101721` | Primary panels and table body |
| `--mp-surface-raised` | `#151F2B` | Headers, hover, selected context |
| `--mp-surface-offset` | `#0C131D` | Alternating rows and quiet inset areas |
| `--mp-border` | `#263447` | Structural borders and dividers |
| `--mp-text` | `#F1F4F8` | Primary text and important values |
| `--mp-muted` | `#98A7BA` | Secondary labels and explanatory text |
| `--mp-faint` | `#6E7E93` | Timestamps, units, and low-priority metadata |
| `--mp-primary` | `#D8AC3D` | Brand accent, active tab, primary action |
| `--mp-primary-bg` | `#3A2F18` | Soft gold context |
| `--mp-good` | `#45D483` | Positive movement, passing state, constructive flow |
| `--mp-good-bg` | `#163526` | Positive state background |
| `--mp-bad` | `#F27C84` | Negative movement, invalidation, failure |
| `--mp-bad-bg` | `#3A2027` | Negative state background |
| `--mp-warn` | `#F0BE58` | Caution, stale data, surveillance |
| `--mp-warn-bg` | `#3A2F18` | Caution state background |
| `--mp-info` | `#74A9FF` | Contextual information and links |
| `--mp-info-bg` | `#182B46` | Informational state background |
| `--mp-cyan` | `#5AD3D0` | Rotation and flow context |

Rules:

- Use color pairs with readable foreground/background contrast. Normal text must target WCAG AA contrast, with extra care for muted text in filled panels.
- Keep gold for hierarchy, focus, active navigation, and primary actions. Do not use gold for every number or every card.
- Pair state color with a word, icon, shape, or explicit pass/fail text. Color alone must never carry the meaning.
- Keep chart series mappings stable across pages. A series should not change color because it appears in a different panel.
- Remove legacy light-theme declarations from active page scopes once those pages consume the shared tokens.

### Typography

Use the existing IBM Plex family as the product voice:

- IBM Plex Sans for navigation, headings, labels, descriptions, and controls.
- IBM Plex Mono for prices, percentages, scores, dates, ranks, and aligned numeric evidence.
- Body text should remain approximately 14–15px at the normal desktop scale.
- Page titles should be concise and visually strong without relying on extra-bold weights.
- Section titles should be short, with a clear 8–12px relationship to the content below them.
- Use tabular figures for changing or aligned numbers.
- Use sentence case for table headers and section copy. Reserve uppercase lettering for small eyebrows, status labels, and compact metadata.
- Keep line height comfortable for wrapped evidence text; do not solve a width problem by shrinking text below a readable size.

### Spacing, geometry, and elevation

Use the existing 4px grid as a formal contract:

- Page gutters: 24px on wide desktop, 16px on tablet, 12px on phone.
- Section spacing: 24px between major regions, 16px between related blocks, 8px between label and value.
- Control gaps: 8px normally, 12px when groups need a visible separation.
- Panel padding: 16–20px; compact table regions may use 12–16px.
- Radius: 8–12px for panels, 6–8px for controls, and full radius only for compact status pills.
- Shadows: reserved for dialogs, menus, and one elevated focus surface. Static data panels use border and contrast, not stacked shadows.
- The main page should be a fluid canvas with a centered maximum content width of approximately 1,440–1,600px. Tables may occupy the full inner width.

The design should never create empty “air” through repeated `mt-*`, `mb-*`, and wrapper padding. Each visual grouping owns one spacing boundary.

## Application shell

### Header

The header is the persistent trust layer for the EOD product:

```text
[MarketPulse · Champion desk]       [Desk] [Momentum] [Research] ...       [EOD OK] [As of] [Actionable]
```

It should show, in a compact arrangement:

- MarketPulse brand and the “Champion desk” product label.
- Flat, readable navigation consistent with NiceGUI's current tab routing.
- Database/session date and pipeline status.
- Actionable or non-actionable state when applicable.
- A TradingView link as a secondary utility, not the visual focus.

The header and navigation remain sticky on desktop. On smaller widths, navigation becomes a horizontally scrollable strip and metadata wraps below the brand without causing body overflow.

### Page canvas

Every page should use the same shell primitive:

1. Optional eyebrow in gold.
2. One concise page title.
3. One sentence explaining the page's job.
4. Optional status banner directly below the header.
5. Main content with consistent section spacing.

Page-specific layout classes should be scoped under a single app root. Global Quasar selectors should be kept to a small compatibility layer; they should not be repeatedly overridden by individual pages.

### Status banners

Stale, missing, and non-actionable data states should be visible but compact. A banner includes a short state label and a useful next action or explanation. It must not push the main table far below the fold or look like an ordinary metric card.

Examples:

- `EOD data ready · 30 Aug 2026`
- `Research only · database is behind the expected session`
- `No decision snapshot for this session · run the EOD pipeline`

## Desk page composition

The Desk is the flagship surface and should make the preview direction real in the application.

### First viewport

The first viewport should contain the following in order:

1. **Page header:** “Morning opportunity set” or the approved Desk title, with session and score-version context.
2. **Regime strip:** market posture, Nifty/index context where available, advance/decline, breadth above 50/200 EMA, fresh highs, and session turnover as available.
3. **Leadership strip:** the top industry/group names with rank, rank change, and one or two supporting metrics.
4. **Queue controls:** Prepare, Observe, Blocked/diagnostic states, copy action, and a compact advanced-column control.
5. **Prepare queue:** the primary table, limited to the most relevant rows by default.
6. **Participation chart:** a line/area chart beside the queue on desktop and below it on smaller widths.

Below the first viewport, show deal-flow confirmation, what changed, sector/industry detail, and secondary research links. Do not repeat the same metric in multiple cards unless the second occurrence answers a different question.

### Regime strip

Use 4–6 equal visual units inside one bounded region. The posture unit is slightly emphasized with a soft semantic background; the others remain quiet. Each unit has:

- a short label;
- one prominent value;
- one unit or context line;
- an explicit state when one exists.

Avoid tall cards with large icons. The strip should feel like a professional tape header rather than a marketing KPI wall.

### Leadership tiles

Leadership tiles are compact, data-bearing tiles rather than decorative cards. Each tile shows:

- rank and rank change;
- group or industry name;
- one RS/breadth value;
- optional positive/negative flow indicator.

Use two or three columns on desktop and stack on phone. The top group should be identifiable without requiring a tooltip.

### Queue controls

State controls should read as a single control group. The active state uses the primary pairing; inactive states remain quiet. The controls must retain visible text and counts, not only colored dots.

The default view should show no more than the first 15 Prepare rows when that is the product contract. “Show all” is explicit. Advanced columns remain available without making the default table unreadable.

## Table system

Tables are the core product surface and receive the strictest layout contract.

### Single source of truth

`ColumnSpec` in `App/ui/table.py` becomes the canonical source for:

- label;
- semantic group;
- preferred width;
- alignment;
- wrapping policy;
- optional responsive priority.

The active renderer in `App/app.py` should consume these specs instead of rebuilding widths from scattered column-name heuristics. Existing tested width totals remain valid where they describe an existing page contract; new Desk columns should have a named contract and a reviewable total.

### Width policy

Use a fixed table layout for standard tables and `width: 100%` inside their containing region. Use horizontal overflow only on the table wrapper when the declared contract cannot fit the available viewport.

Recommended width bands:

| Column type | Preferred width | Behavior |
| --- | ---: | --- |
| Symbol/action identifier | 104–128px | No wrap; primary clickable text |
| State | 84–104px | Compact text + semantic chip |
| Industry/sector | 150–200px | Wrap once or ellipsize with accessible detail |
| Numeric price/score | 72–104px | Right-aligned, tabular figures |
| Percentage/distance | 64–92px | Right-aligned, no wrap |
| R:R / rank | 56–76px | Right-aligned, no wrap |
| Evidence/deal summary | 140–220px | Wrap to two lines where useful |
| Event/action | 96–140px | Wrap only when the label carries meaning |

The renderer must not let a long sentence or symbol list expand the whole table. Do not use `width: max-content` for the primary Desk table; reserve it for a deliberately wide research table inside `.mp-table-scroll`.

### Alignment and hierarchy

- Symbol, group, state, evidence, and event text align left.
- Prices, percentages, scores, ranks, turnover, volume, and R:R align right.
- Header alignment follows the data column alignment.
- Symbols use the strongest text weight and the primary accent only on interaction/hover.
- Numeric values use mono figures and a consistent decimal policy.
- Units belong in the header or a concise secondary label, not repeated awkwardly in every cell.
- Keep actions to one compact cell; use `360°`, `TV`, and `Copy` only when those actions are actually available.

### Row rhythm and states

- Standard row target: 36–40px.
- Compact research row target: 32–36px without shrinking the type.
- Header target: 40–48px with one clear bottom rule.
- Hover changes the row surface subtly and preserves text contrast.
- Zebra striping, if retained, should be low contrast and never compete with state colors.
- Selected or focused rows use an inset accent or accessible focus state, not a full saturated fill.
- Empty tables preserve the page rhythm with a compact message and useful hint.

### Responsive tables

At desktop widths, tables should fit the main content canvas without arbitrary extra margins. At tablet and phone widths:

- keep the symbol and primary action columns visible;
- hide or demote lower-priority columns through the existing column chooser or named responsive priorities;
- use `.mp-table-scroll` only when the remaining contract cannot fit;
- keep scrolling inside the table wrapper, never on the whole page;
- prevent the header, filter controls, and table from creating horizontal body overflow.

### Long content

Long evidence and deal summaries may wrap to two lines. They must have a stable max width, readable line height, and an accessible way to inspect the full value. Do not use forced word breaks on ordinary text unless the content is a symbol list or machine identifier.

## Chart system

Charts should explain a market relationship, not fill an empty panel.

### Shared chart rules

- Centralize ECharts options and theme values in one reusable chart helper.
- Resolve CSS variables before passing colors to chart APIs that cannot parse them.
- Use a transparent chart background and a quiet, neutral grid.
- Keep chart titles short and place units in the axis label or subtitle.
- Use a legend only when direct labeling is not enough.
- Use the shared tooltip style and axis pointer on interactive charts.
- Keep series colors stable: gold for the primary measure, blue/cyan for context, green/red only when the series itself represents positive/negative meaning.
- Avoid smoothing that changes the perceived turning point of financial data; use a restrained curve only for presentation where it does not alter interpretation.
- Disable initial animation and use short, reduced-motion-aware transitions for data changes.

### Desk charts

The first Desk chart is the participation trend:

- Advance percentage;
- Above 50 EMA;
- Above 200 EMA;
- shared date axis;
- visible latest values;
- tooltip on hover/touch;
- no more than the readable number of date ticks at narrow widths.

Secondary chart roles:

- grouped line chart for top industry/sector trend;
- grouped bars for buy vs sell deal flow;
- heatmap for compact signed-return comparison;
- sparklines for row-level context only when a row already has a clear label.

Charts should stack at narrow widths. Every chart needs a concise accessible name/description and must remain useful when color is not available.

## Stock 360 presentation

Stock 360 is the confirmation workspace, not a second dashboard. The dialog should use the same surface tokens, typography, tab styling, and table contract as the main Desk.

Recommended visual order:

1. **Header:** symbol, current state, last price, market/industry context, and direct TradingView action.
2. **Setup:** trend-template status, stage context, RS values, 52-week position, RVOL, and delivery.
3. **VCP / setup geometry:** contraction depth bars or a compact geometry view, pivot, invalidation/stop, 3T/2T state, and setup class. A legacy scalar must not dominate the header.
4. **Flow:** PROP-labeled flow, institution flow, Bulk/Block type, persistence, and size versus ADV.
5. **Risk:** trigger, stop, R:R, `why_now`, and explicit skip/warning wording.
6. **Events:** next event date and results-week risk before the headline list.

The dialog should be wide enough for the primary content but fit inside 95vw. On small screens, it becomes a full-width stacked surface. Avoid nesting cards inside cards; use section headers, separators, and two-column metric rows.

## Research, Portfolio, and Health surfaces

### Research

Research pages should feel like specialists inside the same product. Preserve their ability to show deeper tables and charts, but reuse the shell, section titles, filters, table alignment, empty states, and chart theme. The Sectors surface should privilege an industry leaderboard before optional taxonomy drill-down.

### Portfolio

Portfolio uses the same numeric typography and table alignment. Risk values should be prominent and readable, while action controls remain visually secondary until needed. Avoid turning every holding into a colorful tile.

### Health

Health is an operator surface. Use a calm diagnostic layout with clear pass/warn/fail states, timestamps, and row counts. It may use more explanatory text than Desk, but it should not introduce a separate color system or typography system.

## Component and file boundaries

The implementation should keep visual responsibilities local:

| Area | Planned responsibility |
| --- | --- |
| `App/ui/styles.py` | Shared tokens, global shell rules, table primitives, state pairs, responsive root rules |
| `App/ui/shell.py` | Page header, status banner, regime strip primitive, filter-bar layout, empty state |
| `App/ui/table.py` | `ColumnSpec`, table presets, width/alignment/wrap contracts |
| `App/ui/widgets.py` | KPI/leadership tiles, chart option builders, heatmap, deal-flow, compact evidence rows |
| `App/pages/desk.py` | Desk composition and page-level data binding |
| `App/pages/research/*` | Research-specific content using shared shell and table/chart primitives |
| `App/ui/stock_drawer.py` | Stock 360 visual hierarchy and tab content using shared primitives |
| `App/app.py` | Routing, style bootstrap, and compatibility glue; no new large visual rule blocks |
| `tests/test_table_spec.py` and focused UI tests | Contract checks for widths, alignment, style tokens, and startup-safe rendering |

New helpers should have one purpose and accept already-prepared data. They should not query the market database merely to render a visual component.

## Data and interaction flow

The visual layer consumes existing read models:

```text
read model / DataFrame
        ↓
page builder selects the named view contract
        ↓
shared component renders tokens + geometry + state
        ↓
NiceGUI interaction opens an existing detail or updates local filters
```

The redesign must not move market writes into `App/`, recompute scoring on a button click, or hide a stale snapshot behind a polished surface. If a field is unavailable, show the approved empty/unknown state rather than inventing a value.

Local presentation interactions include state filters, table pagination, column visibility, chart range controls where already supported, and opening Stock 360. They should update the smallest possible host rather than repainting the entire page.

## Error, empty, and loading states

Every major surface needs an intentional state for:

- no database;
- stale or non-actionable session;
- no rows in the selected state;
- missing optional columns;
- empty history for a chart;
- partial data where a metric is not computable.

The layout remains stable in these states. Use concise copy, a visible reason, and the next safe action. Do not fill missing data with a fake zero, generic success color, or empty decorative card.

## Accessibility and responsive acceptance

The redesign is accepted only if:

- every interactive element has a visible label or accessible name;
- keyboard focus remains visible and the tab order is native;
- state meaning is present in text as well as color;
- normal and muted text remain readable against their actual surfaces;
- controls have usable touch targets without breaking the 320px layout;
- tables do not force body-level horizontal scrolling;
- dialogs, menus, charts, and tables do not clip text at supported widths;
- charts include accessible labels and remain interpretable in light/dark system conditions if a theme toggle is introduced later.

The primary QA widths are 1,440px, 1,024px, 768px, and 390px. A final pass should also test one intermediate width around 600px because it is where filters and two-column regions commonly collide.

## Verification plan

### Automated checks

- Keep the existing startup and read-only market database tests passing.
- Extend table contract tests to verify the active renderer consumes named specs, keeps numeric alignment, and does not reintroduce unrestricted auto layout for the primary table.
- Add focused tests for shared style/token presence and the default Desk column contract.
- Add a startup render check for missing database, stale snapshot, empty queue, and optional-column absence.
- Run `py_compile` for changed UI modules and the focused pytest suite before claiming completion.

### Browser and visual checks

For each implementation slice:

1. Start the local app with the normal launch path.
2. Inspect Desk, Sectors, Deals, Portfolio, Health, and Stock 360 at the primary desktop width.
3. Inspect the same surfaces at tablet and phone widths.
4. Verify that only table wrappers scroll horizontally when required.
5. Check long headers, long industries, evidence text, empty states, stale banners, and dialog content.
6. Check hover, focus, tooltips, pagination, column controls, and Stock 360 open/close behavior.
7. Capture before/after screenshots for the Desk first viewport and the densest table.

Success is visual and functional: the user should be able to identify the tape, leading groups, queue state, trigger/stop, and next confirmation action without hunting across unrelated page regions.

## Rollout plan

### Slice 1: Token and shell consolidation

- Introduce the final semantic token set.
- Add one app root and remove conflicting active-page color overrides.
- Normalize header, tabs, page header, status banners, toolbar geometry, and global spacing.
- Keep behavior unchanged.

### Slice 2: Table contract activation

- Make `ColumnSpec` the renderer's width/alignment source.
- Replace unrestricted auto layout for standard tables.
- Add stable numeric/text/symbol classes and responsive priorities.
- Verify the densest existing tables before moving the Desk.

### Slice 3: Desk first viewport

- Recompose the Desk around the regime strip, leadership strip, queue controls, queue table, and participation chart.
- Add compact leadership and “what changed” widgets only where the data exists.
- Keep the primary queue readable at the first desktop viewport.

### Slice 4: Stock 360 and research consistency

- Apply the same visual hierarchy to Stock 360.
- Migrate Sectors and Deals to shared table/chart/card primitives.
- Normalize Portfolio and Health without introducing new domain behavior.

### Slice 5: Responsive and visual QA

- Test all acceptance widths and edge states.
- Remove leftover page-specific spacing and literal chart colors.
- Document the stable component contracts for future pages.

Each slice should be independently testable and reviewable. If a global style change breaks a legacy page, scope the new rule under the migrated page root and continue the migration rather than widening the global override.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Global CSS changes break legacy pages | Scope the new system under the app root and migrate pages in slices |
| Fixed widths create clipping on small screens | Use wrapper-level overflow, responsive priorities, and browser checks at 390px/600px |
| Long evidence dominates a table | Give evidence columns named max widths and move full detail to Stock 360 |
| Hardcoded ECharts colors drift from the theme | Centralize chart option builders and resolve semantic tokens once per render |
| More cards increase visual noise | Cap top-level summary units and use transparent structural layout for repeated content |
| Polished UI hides stale data | Keep session/as-of/actionable state in the header and use explicit banners |
| `app.py` remains a visual god file | Keep new primitives in `App/ui/` and limit `app.py` to routing and compatibility glue |

## Completion criteria

The premium UI redesign is complete when:

1. The Desk first viewport follows the approved institutional trading-desk composition.
2. Shared colors, typography, spacing, table, chart, and status contracts are used across active pages.
3. The primary table has stable, readable widths and no accidental extra whitespace or body-level overflow.
4. Numeric/text alignment and tabular figures are consistent across tables.
5. Charts are attractive because they clarify participation, rotation, or flow—not because they add decoration.
6. Stock 360 feels like the same product and presents confirmation in a deliberate order.
7. Empty, stale, and missing-data states remain honest and visually coherent.
8. Automated checks and browser checks pass at the defined widths.
9. The implementation does not change the market data, scoring, or database ownership boundaries described above.

## Next approval gate

This document is the proposed implementation contract for the approved visual direction. Implementation should begin only after the user reviews this file and confirms that the scope, palette, Desk composition, table policy, and rollout order are correct.
