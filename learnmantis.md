# Screening Mantis review — learnings for MarketPulse

**Source:** [Screening Mantis](https://www.screeningmantis.com/)  
**Reviewed:** 2026-09-03  
**Site data label during review:** 2026-09-02  
**Access:** public signed-out surface plus authenticated Siddhant Patil Chrome session  
**Default live result:** 1,538 stocks matching; 100 initially rendered  
**Visible subscription price:** ₹500 per month through Razorpay

This is a product and implementation review, not an endorsement of the site's signals. The useful lesson is the way Screening Mantis turns a large end-of-day universe into a compact decision workspace: market regime first, then filters and ranking, then a single-stock chart and notes.

The recommended direction for MarketPulse is to extend the existing decision desk around those workflows. We should not build a separate Mantis clone or introduce a second data universe. Preserve the current product constraints: NiceGUI + DuckDB, official NSE end-of-day data, cash equities only, no live ticker, and no unverified earnings/XBRL feed.

## Executive decision

Borrow these ideas first:

- A compact, clickable market-health strip above every screener.
- A real sector-flow board that combines return trend, breadth, turnover share, benchmark-relative strength, and rank change.
- A consistent Daily / Weekly timeframe switch whose labels and calculations change together.
- A dense but understandable stock table with optional columns and per-column threshold controls.
- Benchmark-relative RS momentum separated from universe percentile rank.
- RS rank history at fixed trading-session lookbacks.
- A technical chart drawer that is connected to the same table filters and supports notes.
- Visible active-filter chips and one-click presets.

Do not copy these decisions blindly:

- Three watchlists, saved templates, sharing, notes, and richer research controls are valuable, but they require a clear local persistence model rather than an account/paywall layer.
- The public signed-out session gated Sectors and Darvas. The authenticated Chrome session unlocked the full Sectors workspace, so its live sector-ranking, turnover, CMF, and RS panels were subsequently verified. Darvas's actual page was not retested.
- Avoid presenting a score as a recommendation. Show the inputs, data date, universe, and calculation window.
- Do not add a live quote dependency or scrape an opaque provider merely to reproduce a cell.

The strongest near-term product move is a first-class Sector Rotation workspace built on MarketPulse's existing sector board and sector intelligence pages, backed by a repaired canonical sector-metrics read model.

## 1. Review scope and access findings

### What was directly verified

The public landing page and signed-out screener were inspected interactively, followed by the authenticated Sectors workspace in the user's Chrome profile. The following were directly verified:

- Landing-page positioning and feature claims.
- Stocks table, default filters, search, sorting, market-cap scope, sector scope, Daily / Weekly switch, and Show more stocks.
- Seven market-health tiles and their historical drill-down charts.
- Optional column picker and per-column configuration dialogs.
- Recommended preset buttons.
- Historical comparison date picker.
- Individual stock chart drawer with EMA, pivot, DarvasBox, volume, RSI, and notes affordance.
- The full 22-step built-in product tour.
- Sectors navigation with Nifty Indices, Sector Ranking, Turnover Rotation, Sector Turnover, Turnover A/D, Chaikin Money Flow, and Relative Strength panels.
- The live sector-ranking table, sortable columns, Daily/Weekly toggles, sector-to-stock drilldown, 15-session turnover heatmaps, four-point CMF comparison, and sector RS leadership chart.

### What was not directly verifiable

Clicking Sectors or Darvas while signed out opened a premium-access card instead of the underlying view. The authenticated Chrome session changed the Sectors result, but not the limits of what was verified:

- The actual Darvas published watchlist and its result columns were not inspected.
- Chaikin Money Flow is directly visible as a sector panel; its UI label and hover values were verified, but the site's exact aggregation formula was not disclosed.
- Saved filters, watchlists, research notes, and filter sharing were confirmed as gated or sign-in flows, but their persistence behavior was not inspected.

The premium card said:

> Premium research access
>
> Unlock saved views, advanced filters, watchlists, research notes, and premium scanner signals.
>
> ₹500 / month

It also showed a promo-code field, a recurring monthly-access note, a Continue to secure payment button, and Close.

### Access matrix

| Area | Directly usable in reviewed session | Finding |
|---|---:|---|
| Stocks screener | Yes | Full free table and controls were usable. |
| Market health | Yes | Seven tiles, current percentages, change markers, and history charts. |
| Daily / Weekly | Yes | Same table switches timeframe-specific indicators and labels. |
| Market-cap and sector scopes | Yes | Multi-select controls, reflected in result count and active chips. |
| Search | Yes | In-place filter by symbol/company/sector. |
| Stock chart | Yes | Technical drawer with EMA, pivots, DarvasBox, volume, RSI, and notes. |
| Sectors | Yes, authenticated | Full sector workspace was visible in the authenticated Chrome profile; signed-out access showed a gate. |
| Darvas | Not retested | The original signed-out session showed a premium-access gate; the authenticated page was not inspected in this follow-up. |
| Saved templates | No | Sign-in or premium flow. |
| Watchlists | No | Sign-in or premium flow. |
| Notes persistence | No | The chart and table expose notes controls, but persistence was not tested. |
| Filter sharing | No | Share button became enabled after a filter was active, then opened premium access. |

## 2. Product positioning and information architecture

The landing page describes Screening Mantis as “A custom screener for Indian equities.” Its promise is a single workspace for:

- Daily and weekly technical analysis.
- Market breadth.
- Sector rotation.
- Relative-strength ranking.

The feature story is coherent:

1. Read the market's overall participation.
2. Narrow by capitalization and sector.
3. Apply technical, momentum, breakout, earnings, and watchlist conditions.
4. Compare relative strength and historical price behavior.
5. Open a stock chart for visual confirmation.
6. Save, annotate, or share the resulting research set.

The app shell reinforces that sequence. The header contains global search, feedback, tour, theme, Sign in, and Sign up. The market-health strip sits above the Stocks / Sectors / Darvas navigation. Scope controls and timeframe controls are global to the screener. The table then acts as the main research canvas.

This is a useful pattern for MarketPulse: the user should not have to navigate through separate pages just to answer “Is the market healthy?”, “Which groups are attracting money?”, and “Which names satisfy the setup?”

## 2A. Authenticated Sectors workspace — verified follow-up

The authenticated Chrome session exposed the full Sectors workspace that was hidden behind the public signed-out gate. This materially changes the earlier assessment: sector rotation is not just a landing-page claim; it is implemented as a multi-panel research page.

### Page structure

The Sectors page keeps the global market-health strip and the Stocks / Sectors / Darvas navigation. Under that, a sticky row of section anchors contains:

- Nifty Indices.
- Sector Ranking.
- Turnover Rotation.
- Sector Turnover.
- Turnover A/D.
- Chaikin Money Flow.
- Relative Strength.

The page is one long research surface. The anchor buttons scroll to their corresponding panel while the header remains available. This is better for comparative work than forcing the analyst to open seven separate pages: the technical index view, the money-flow table, the three turnover heatmaps, CMF history, and RS leadership are all part of one sector context.

### Nifty Indices panel

The first panel is labelled Sectoral indices and states that it contains 21 NSE sectoral/thematic indices updated after each scan.

It has three mutually exclusive table modes:

- Daily.
- Weekly.
- Both.

The index table contains:

- Index name.
- Price.
- Percentage change, with a selectable price-change period.
- Daily RSI.
- Daily EMA position.
- Percentage from the selected daily EMA.
- Daily EMA cross and age.
- Daily pivot.
- Weekly pivot.
- RS rank history at T-30, T-15, T-5, and T0.

The Both mode adds the weekly equivalents in the same row:

- W-RSI.
- W-EMAs.
- W-% from 20EMA.
- W-EMA cross and age.

The current table showed NIFTY PHARMA, NIFTY METAL, NIFTY MIDSML HLTH, NIFTY HEALTHCARE, NIFTY IT, NIFTY PVT BANK, NIFTY OIL AND GAS, NIFTY REALTY, NIFTY PSU BANK, NIFTY CHEMICALS, NIFTY BANK, NIFTY CONSR DURBL, NIFTY ENERGY, NIFTY COMMODITIES, NIFTY PSE, NIFTY INFRA, NIFTY MEDIA, NIFTY FIN SERVICE, NIFTY CONSUMPTION, NIFTY AUTO, and NIFTY FMCG.

Example from Both mode:

| Index | Daily RSI | Weekly RSI | Daily % from 20EMA | Weekly % from 20EMA | Daily EMA age | Weekly EMA age | Daily pivot | Weekly pivot | RS T-30 → T0 |
|---|---:|---:|---:|---:|---|---|---|---|---|
| NIFTY PHARMA | 58.3 | 74.3 | +0.7% | +5.7% | — | 20 days | Near Pivot | R1 | 80 → 99 |
| NIFTY METAL | 51.6 | 58.2 | -0.1% | +3.0% | 23 days | 68 days | Near Pivot | R1 | 28 → 94 |
| NIFTY MIDSML HLTH | 52.3 | 69.2 | -0.0% | +4.8% | — | 20 days | Near Pivot | R1 | 66 → 90 |

This is a useful separation from stock-level sector rotation. The index table answers whether the official sector/thematic index is technically healthy; the ranking table below aggregates the underlying stocks.

### Sector Ranking panel

The panel is labelled Money Flow → Sector ranking and says: “Most recent trading day, click a column to sort.”

The table has two grouped headers:

| Group | Columns |
|---|---|
| Sector Rotation | Turnover, % change, Share %, Δ Share (pt), A/D Net |
| Sector Health | Avg RSI, % > 20EMA, % BO in last 10 days |
| Leaders | Three named leader stocks, each an action button |

The % change and Δ Share columns each have a Daily / Weekly toggle. Daily is the default. The table has no permanent numeric rank column; its order changes when a header is clicked. This is a good choice for research because “ranking” is driven by the metric the analyst chooses, but the current sort should be made more prominent in our implementation.

The current table contained 58 broad sector/industry groups. The labels are more granular than the 22-sector taxonomy currently used by MarketPulse: for example, NBFC, Capital Markets, Oil & Gas, IT Services, Pharmaceuticals, Auto Components, Private Banks, and Specialty Chemicals appear as separate rows.

#### Current values observed

| Group | Stocks | Turnover | D % change | Share | D Δ share | A/D net | Avg RSI | % >20EMA | % BO last 10 days | Example leaders |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NBFC | 62 | ₹9,091.3 Cr | +0.28% | 8.67 | +4.02 | +0.63 | 45 | +23% | +19% | IFCI, TFCILTD, FINKURVE |
| Oil & Gas | 15 | ₹2,127.6 Cr | +3.16% | 2.03 | +1.40 | +0.93 | 59 | +80% | +20% | DOLPHIN, PRABHA, ASIANENE |
| Automobiles | 18 | ₹7,188.2 Cr | -1.94% | 6.86 | -0.38 | -0.95 | 44 | +22% | +11% | ATHERENERG, BAJAJ-AUTO, OLAELEC |
| Pharmaceuticals | 99 | ₹6,109.3 Cr | +0.75% | 5.83 | +0.02 | +0.15 | 51 | +53% | +27% | MOREPENLAB, SYNCOMF, BLISSGVS |
| Packaging | 12 | ₹498.9 Cr | +0.55% | 0.48 | -2.54 | -0.19 | 56 | +67% | +33% | UFLEX, COMSYN, TCPLPACK |

The table is especially useful because it prevents a false conclusion from any single measure. Automobiles has a large turnover share but negative price change and negative A/D net. Oil & Gas has a smaller share but strong daily change, breadth, and A/D. Packaging has strong health percentages but declining turnover share. Those are materially different research situations.

#### Daily / Weekly toggle behavior

For NBFC, the live table showed:

- Daily percentage change: +0.28%.
- Weekly percentage change after switching the control to W: -2.20%.
- Daily share change: +4.02 points.
- Weekly share change after switching the control to W: +3.59 points.
- A/D net: +0.63.

The A/D net cell does not show a unit in the header or tooltip; the hover value is simply 0.63. MarketPulse should label the unit and denominator explicitly.

#### Sorting and drilldown

Clicking Turnover sorted the table descending. The leading rows then became:

1. NBFC — ₹9,091.3 Cr.
2. Automobiles — ₹7,188.2 Cr.
3. Private Banks — ₹6,483.0 Cr.
4. Pharmaceuticals — ₹6,109.3 Cr.
5. IT Services — ₹5,394.2 Cr.
6. Capital Markets — ₹5,083.3 Cr.
7. Metals & Mining — ₹4,972.7 Cr.
8. Electrical Equipment — ₹3,731.8 Cr.

Clicking a sector-name button drilled into Stocks, kept the global market-health strip, added a Sector = NBFC active chip, and returned 62 matching stocks. This is an important interaction: sector rotation does not stop at a chart; it creates a reproducible candidate universe.

### Turnover heatmaps

The three turnover panels are compact heatmaps. Cells are intentionally quiet by default: they use green, red, and neutral intensity rather than printing 58 × 15 numbers. Hovering a cell reveals the exact value. Each heatmap has a sector-name button so the analyst can move from a visual pattern to the corresponding stock set.

#### Share of turnover

Title: Share of turnover  
Subtitle: Daily sector share of total market turnover, last 15 sessions

Columns are the last 15 trading sessions:

02-09, 01-09, 31-08, 28-08, 27-08, 26-08, 25-08, 24-08, 21-08, 20-08, 19-08, 18-08, 17-08, 14-08, 13-08.

Hover example:

- NBFC: 8.67% share, +4.02 percentage points.

The current row ordering starts with the most prominent rotation-table groups rather than alphabetic order. A future MarketPulse heatmap should either preserve a documented order or provide a sort selector so color patterns are not reinterpreted accidentally.

#### Turnover vs own history

Title: Turnover vs own history  
Subtitle: Today's turnover vs the sector's own trailing 9-session average

This answers a different question from share of market turnover. A large sector can have a high share but normal activity; a smaller sector can have a low share but unusually high activity relative to its own history.

Hover example:

- NBFC: ₹9,091.3 Cr, or 1.57x its own trailing 9-session average.

The denominator is group-specific, not the total market. This is a high-value normalization to copy.

#### Advance/decline net flow

Title: Advance/decline net flow  
Subtitle: Daily net advancing vs declining turnover by sector, last 15 sessions

The heatmap uses the same 15-session columns and maps positive and negative net turnover flow by color.

Hover example:

- NBFC: 0.63.

Unlike a simple count of advancing stocks, this view is turnover-weighted. It can show whether the money moving inside a group is concentrated in advancing or declining names. The formula and units should be made explicit before reproducing it in MarketPulse.

### Chaikin Money Flow

The panel is labelled Money Flow → Chaikin Money Flow and states:

“20-session sector-average CMF across Today, 1 Week Ago, 2 Weeks Ago, and 1 Month Ago.”

It has five columns:

- Today, dated 02-09.
- 1W ago.
- 2W ago.
- 1M ago.
- Trend.

The first four cells are color-coded heatmap values. Hovering reveals the exact 20-period CMF:

- NBFC: -0.082.
- Oil & Gas: +0.124.

The current trend labels were:

- Neutral: 33 groups.
- Accumulating: 3 groups.
- Distributing: 19 groups.
- Weakening: 1 group.
- Improving: 2 groups.

Examples:

- Accumulating: Oil & Gas, Aerospace & Defense, Packaging.
- Improving: Paper Products, Industrial Products.
- Weakening: Restaurants.
- Distributing: Jewellery & Watches, Utilities, Cement, Railways, Realty, Automobiles, FMCG, IT Services, and others.

The trend is not merely the sign of today's CMF. It is a classification across the four historical points, because a group can have a negative current reading but still be improving, or a positive reading but be distributing. MarketPulse should model the trend as a state transition with visible historical inputs.

The site's exact CMF aggregation was not disclosed. If we implement it, aggregate the money-flow-volume numerator and volume denominator for all stocks in the group before dividing; do not average individual stock CMF ratios.

### Relative-strength leadership

The lower panel is labelled Sector Breadth → Relative-strength leadership and states:

“Average RS rank by sector, today (T-0) vs 5 sessions ago (T-5), sorted by T-0.”

It is a horizontal two-series bar chart with:

- T-0 (today).
- T-5 (5 sessions ago).
- A 0–100 percentile axis.
- 58 sector/industry labels sorted by today's value.

Current chart examples:

| Group | T-0 | T-5 | Change |
|---|---:|---:|---:|
| Sugar | 82.0 | 82.9 | -0.9 |
| Information Technology | 77.5 | 49.0 | +28.5 |
| Oil & Gas | 74.0 | 62.9 | +11.1 |
| Iron & Steel Products | 67.5 | 61.6 | +5.9 |
| Packaging | 66.7 | 61.5 | +5.2 |
| Restaurants | 65.1 | 77.9 | -12.8 |
| Automobiles | 34.9 | 56.6 | -21.7 |
| Media & Entertainment | 31.7 | 48.7 | -17.0 |
| Education | 36.6 | 52.1 | -15.5 |
| FMCG | 30.5 | 29.0 | +1.5 |

This chart is not a turnover chart. It shows the average stock-level RS rank of each group and its short-term change. The combination of the charts is what makes the page useful:

- Turnover share shows where attention or activity is concentrated.
- Turnover versus own history shows abnormal group activity.
- A/D net flow shows whether turnover is supporting advancers.
- CMF provides accumulation/distribution context.
- RS leadership shows whether the underlying names are outperforming.

### What the authenticated Sectors view teaches us

The sector page has four layers, from broadest to most actionable:

1. Official index technical condition.
2. Group-level rotation and health table.
3. Historical turnover and money-flow heatmaps.
4. RS leadership and sector-to-stock drilldown.

MarketPulse should adopt this structure in the existing research area. The first release does not need seven separate navigation destinations; one page with sticky anchors and a shared scope/date header will be enough.

## 3. Default screener workflow

### Header and global controls

The signed-out screener displayed:

- Search placeholder: “Search symbol, company, or sector”.
- Feedback.
- Tour.
- Dark-theme toggle.
- Sign in and Sign up.

The first navigation level was:

- Stocks.
- Sectors.
- Darvas.

The global scope controls were:

- Market-cap scope.
- Sector scope.
- Daily / Weekly timeframe.

The default screener showed:

2026-09-02 · 1,538 stocks match

and initially rendered 100 rows with a Show more stocks action. The active default sort was RSI descending.

### Market-cap scope

The market-cap picker was a multi-select menu with:

- All market cap.
- Large Cap.
- Mid Cap.
- Small Cap.
- Micro Cap.

Selecting Small Cap changed the scope chip to SC and returned 538 stocks. Selecting Micro Cap as well showed SC + Mic and returned 1,248 stocks. Clearing the choices restored the all-cap universe.

The control is useful because it is global and immediately changes the population against which the breadth, ranks, and filters are interpreted. For MarketPulse, the selected scope should be carried into every metric label and tooltip. “RS percentile” without saying “within current universe” is ambiguous.

### Sector scope

The sector picker was also multi-select and exposed a broad taxonomy, including groups such as:

- Aerospace & Defense.
- Automobiles and Auto Components.
- Banks, NBFC, Insurance, and Capital Markets.
- Cement, Construction & Engineering, Building Products, and Realty.
- Chemicals, Fertilizers & Agrochemicals, Paints, and Pharmaceuticals.
- FMCG, Food Products, Restaurants, Retail, and Textiles.
- IT Services, Online Services, Media & Entertainment, and Telecom.
- Metals & Mining, Oil & Gas, Power, Renewable Energy, and Utilities.

Selecting Pharmaceuticals alone returned 99 stocks; clearing the sector restored 1,538. This is a simple interaction, but it makes the universe boundary explicit before the user interprets a scan.

### Search

Searching for BODAL filtered the table in place to one row for BODALCHEM. There was no disruptive result page or suggestion overlay. A clear-search control restored the full result. The site also states in its tour that symbol search should not disturb active filters, which is the right behavior for research.

One small copy issue was visible: the empty/singular state said “1 stock matches” rather than using singular grammar. This is minor, but it is a useful polish item if we build the same interaction.

### Daily and Weekly

Switching from Daily to Weekly changed both the table labels and the underlying period semantics:

| Daily presentation | Weekly presentation |
|---|---|
| RSI | W-RSI |
| EMAs | W-EMAS |
| % from 20EMA | W-% FROM 20EMA |
| EMA Cross | W-EMA CROSS |
| Cross age in days | Cross age in weeks |

Price, 1D%, pivots, breakout, earnings, historical comparison, and notes remained in the table. The important design principle is that timeframe-specific signals are visibly marked, rather than silently changing their calculation while retaining a Daily label.

## 4. Market-health strip

The market-health strip is the clearest Mantis feature to bring into MarketPulse. It provides a quick regime read before the user opens a filter panel.

### Observed default cards

| Card | Current reading | Displayed change | Meaning |
|---|---:|---:|---|
| Advance / decline | -21.5% | 6.9 pts | Participation balance across the active universe. |
| Above 20 EMA | 37.1% | 1.7 pts | Short/intermediate trend participation. |
| Above 200 EMA | 49.9% | 0.5 pts | Long-term trend participation. |
| RSI above 60 | 17.2% | 0.7 pts | High-momentum participation. |
| Above daily pivot | 31.9% | 1.8 pts | Short-term price-location participation. |
| Near 52-week high | 25.9% | 0.6 pts | Leadership and breakout proximity. |
| Recent breakout | 12.2% | 1.0 pts | Recent qualifying breakout participation. |

The card layout combines a primary percentage with a smaller point-change marker and a directional visual. The percentage answers “how broad is the condition now?”; the change answers “is it improving or deteriorating?”.

The Advance / decline tile used a net-style percentage, while the other cards used the share of stocks meeting a condition. That distinction should be made explicit in MarketPulse labels and tooltips.

### History interaction

Each card was clickable. Clicking it opened a centered line-chart modal with:

- Metric-specific title.
- Description: “Market breadth history across the active universe.”
- Segment buttons: All, LC, MC, SC, Micro.
- A roughly five-month history from late April through 2026-09-02.
- A latest endpoint label.

The segment buttons changed the chart values. For example, Advance / decline ended at -21.5% for All and -33.9% for LC. This is stronger than a static KPI because the user can distinguish a single-day shock from a persistent deterioration.

The other observed history endpoint values were:

- Above 20 EMA: 37.1%.
- Above 200 EMA: 49.9%.
- RSI above 60: 17.2%.
- Above daily pivot: 31.9%.
- Near 52-week high: 25.9%.
- Recent breakout: 12.2%.

The chart date ticks were approximately 04-28, 06-16, 08-01, 09-22, 11-07, 12-24, 02-11, 04-06, 05-27, 07-16, and 09-02. The exact tick formatting was compact and suited to the modal.

### Collapse behavior

The strip had a Hide market health button. Collapsing it replaced the strip with a Show market health control and reduced vertical pressure on the table. The expanded/collapsed state was exposed through aria-expanded.

### MarketPulse implementation implication

MarketPulse already has a useful source for much of this in App/market_summary.py and the breadth_daily table. The implementation should add a presentation layer rather than duplicate calculations:

- Use the latest breadth_daily row for the current cards.
- Use a fixed history window for the trend line.
- Recalculate the same cards for the selected cap scope where the data supports it.
- Make cards clickable and route to the existing visual history pattern.
- Keep “net advance/decline” separate from “percentage above condition”.
- Display the data date and active universe beside the strip.
- Add a staleness state when the latest EOD load is older than the expected trading session.

## 5. Stocks table: structure and metric catalog

The table grouped columns into research concepts rather than presenting one undifferentiated list:

- Price & Volume.
- EMAs.
- Pivots.
- Breakout Stocks.
- Relative Strength.
- Earnings Reaction.
- Price Moves.

The visible daily table included:

| Group | Columns observed |
|---|---|
| Identity | #, My Watchlist, Cap, Ticker, Sector |
| Price & volume | Price, 1D%, RSI, Vol Spike 1D/9D, Gap Opening |
| Trend | EMAs, % from 20EMA, EMA Cross 10x20 |
| Pivots | D-Pivot, W-Pivot |
| Breakout | 52W high, BO gain%, Stage 2 |
| Relative strength | RS (momentum), RS rank history T-30 / T-15 / T-5 / T0 |
| Earnings | Next earn., Past earn., -1D%, E-Day%, +1D% |
| Price moves | Hist. price, Gain% since |
| Research | Notes |

The table is intentionally dense. Its usability comes from the optional-column menu, concise headers, hover explanations, color conventions, and inline configuration rather than from reducing the number of available metrics.

### Identity and price

**Cap**

Market-cap segment for the stock. It mirrors the global cap scope and makes the row's classification visible.

**Ticker**

NSE symbol. The chart icon next to the ticker opens the full technical detail drawer.

**Sector**

Sector classification used by the global sector filter.

**Price**

Latest close in rupees for the displayed data date.

**1D%**

Percentage price change over the selected period. The site's help text says the period can be one day, one week, or one month; this is separate from the Daily / Weekly technical timeframe.

### RSI and volume

**RSI**

14-period RSI on the active technical timeframe. A green or red dot indicates whether RSI is above or below its own 14-period moving average. The RSI threshold can be configured from the column gear.

The key lesson is to keep the raw oscillator and the trend-of-oscillator cue together. The dot provides a fast directional read without requiring another full column.

**Volume spike**

Yesterday's volume divided by the prior nine-day average volume in the default Daily view. It flags a sudden single-day expansion. The averaging window is configurable.

**Gap opening**

Today's open versus yesterday's close. Gaps beyond a threshold are highlighted; the threshold is configurable. The default dialog value was 3%, with a range from 0% to 30% in 0.5% steps.

### EMAs and trend

**EMAs**

Price position relative to the 10, 20, 50, and 200 EMAs. Green means price is above the EMA, red below, and grey indicates insufficient history.

**Percentage from EMA**

Distance from a selected EMA period. The period picker offered 10, 20, 50, and 200, with 20 as the default.

**EMA Cross**

Direction and age of a fast/slow EMA cross. The default pair was 10 x 20. The configuration dialog offered fast periods 5, 9, 10, 20, 50 and slow periods 20, 50, 100, 200.

**200EMA slope**

Available in the optional-column menu. It is the slope over the last 10 candles and indicates whether the long-term trend is rising.

The MarketPulse equivalent should expose the configured pair and timeframe in the header or tooltip. A generic “EMA Cross” is not enough when a user can compare Daily and Weekly signals.

### Pivots and price location

**D-Pivot**

Price position relative to daily R1, PP, and S1. The cells indicate the zone, and the value can be filtered from a dropdown.

**W-Pivot**

The same idea using weekly pivot levels.

This is a good example of a categorical technical filter: users should be able to select zones such as above R1, between PP and R1, or below S1 rather than having to express every range as numeric inequalities.

**52W high**

Percentage distance below the 52-week high. The column gear configured “within” a percentage of the high. The default was 10%.

### Breakouts and Stage 2

**BO gain%**

Gain on the latest qualifying breakout candle. The help text described a qualifying breakout as at least 3% gain on at least 2x average volume. The gear offered minimum gain and maximum candles ago; observed defaults were 5% and 10 candles.

**BO vol**

Optional breakout-volume field. It should be the breakout volume relative to its reference average, with the reference window shown in the tooltip.

**Vol dry**

Optional post-breakout volume behavior. Lower volume relative to the breakout candle is treated as drying volume, which is presented as healthy consolidation behavior.

**Retrace%**

Optional measure of how far price retraced into the breakout move, expressed as a fraction of the total move.

**Stage 2**

Weinstein-style Stage 2 checklist score out of seven, based on price, long-term average, EMA trend, and RS rules. The product landing page describes qualified Stage 2 and base-breakout scoring.

For MarketPulse, a seven-point score should always provide an expandable checklist. “6/7” is not actionable enough unless the missing rule is visible.

### Relative strength

**RS (momentum)**

Short-term relative-strength momentum versus the Nifty750 benchmark. This is distinct from a percentile rank within the current stock universe.

**RS rank history**

Percentile RS rank at T-30, T-15, T-5, and T0 trading-session points. The columns allow sorting and visual comparison of acceleration or deterioration.

**RS slope**

Optional RS-line slope over the last 30 days.

This separation is one of the most valuable Mantis design choices:

- Benchmark-relative momentum asks whether the stock is outperforming the chosen market benchmark.
- Universe percentile asks how the stock ranks against the current screen population.
- Rank history asks whether that standing is improving or fading.

MarketPulse should retain all three concepts and name them explicitly.

### Earnings reaction

The table exposed:

- Next earnings date.
- Past earnings date.
- Price change one day before the last earnings event.
- Earnings-day change.
- Price change one day after the event.

This is a useful event-reaction view, but it should remain optional in MarketPulse until a trusted, point-in-time corporate-event source is available. The table must not imply that a missing event is a neutral event.

### Historical comparison

The Hist. price and Gain% since columns were controlled by a historical date picker. The calendar disabled dates without price history. Selecting 2026-09-01 changed the header to GAIN% SINCE 01 09 26; BODALCHEM showed a historical price of ₹126.8 and a gain of +13.2%. The selection was then restored to 2026-09-02.

This is a compact way to answer “what has worked since the signal date?” and is particularly useful for review and post-screener study. It should use trading-session dates and show the selected date in the column header.

### Notes

Notes were available as a free-text research field in the table and chart drawer. The tour also described a way to show only noted stocks. MarketPulse already has a local-user data model, so this is a natural feature once the persistence scope is explicit.

## 6. Optional columns and configuration UX

The Optional Columns menu was scrollable, grouped, and included Reset to default. The complete grouping observed was:

| Group | Optional or available fields |
|---|---|
| Watchlist | My Watchlist |
| Stock Info | Cap, Sector, Ticker |
| Price & Volume | Price, 1D%, RSI, W-RSI, Avg volume, Volume spike, Gap Opening |
| EMAs | EMAs, W-EMAs, % from EMA, W-% from EMA, EMA cross, W-EMA cross, 200EMA slope |
| Pivots | D-Pivot, W-Pivot |
| Breakout Stocks | BO gain%, BO vol, Vol dry, Retrace% |
| Relative Strength | RS slope, RS (momentum), RS rank history |
| Earnings | Next earn., Past earn., -1D%, E-Day%, +1D% |
| Price Moves | Hist. price, Gain% since |
| Additional | Monthly setup, Stage 2, Notes |

The Daily / Weekly switch changed which timeframe-specific columns were visible by default. Daily showed daily RSI/EMAs/cross fields; Weekly showed their W-prefixed variants.

### Configuration dialogs observed

| Column | Control | Observed default |
|---|---|---|
| RSI | Numeric minimum; enabled as a filter on Apply | 60 |
| Volume spike | Average-over window selector | 9 days |
| Gap opening | Numeric absolute threshold | 3% |
| EMA cross | Fast and slow period selectors | 10 x 20 |
| 52W high | Maximum distance from high | 10% |
| BO gain | Minimum gain and maximum age | 5%; 10 candles |
| Percentage from EMA | EMA period selector | 20 EMA |

The interaction model is compact:

1. Select a column from the optional menu.
2. Use the gear next to the column to define a threshold or reference window.
3. Apply the setting.
4. See the resulting condition as an active chip.
5. Remove or revise the chip without reopening a large filter drawer.

For example, applying the default RSI configuration produced a D-RSI >= 60 chip. Applying the default gap configuration produced Gap >= 3%. The exact chip text makes the active screen reproducible.

### About/help copy

The per-column About content did useful explanatory work. It explained both the formula and the interpretation, including:

- Avg volume: five-day average volume divided by 20-day average; above 1x suggests expansion.
- 200EMA slope: last-10-candle slope; positive means long-term trend is rising.
- Vol dry: post-breakout volume relative to breakout volume; lower is healthier drying.
- Retrace%: fraction of the breakout move retraced.
- Monthly setup: a bullish anchor month followed by one to three consecutive tight-range months.
- RS slope: RS-line slope over the last 30 days.

MarketPulse should reuse this explanatory standard. Every non-obvious cell needs three things:

- What is calculated.
- The period and denominator.
- How to interpret the result, including important missing-data cases.

## 7. One-click presets, filters, and active state

### Recommended presets

The preset row included:

- EMAs Aligned.
- EMAs Converge.
- RSI > MA.
- Breakout stocks.
- IPO stocks.

On Weekly, the timeframe-specific names used W prefixes for the first three.

In the Daily view, the observed result counts were:

| Preset | Result count |
|---|---:|
| EMAs Aligned | 293 |
| EMAs Converge | 4 |
| RSI > MA | 4 |
| Breakout stocks | 0 |
| IPO stocks | 0 |

These were behavioral observations from the reviewed data date, not expected permanent counts.

### Filters and chips

The Filters button opened a premium-access card in the signed-out session. The built-in tour nevertheless described a broader filter system combining:

- RSI.
- EMA conditions.
- Breakouts.
- Pivot zones.
- Earnings.
- Review/watchlist states.
- Other technical conditions.

When an individual column setting or preset was active, the screen displayed removable active-filter chips. There was also a Clear all action.

One important observed UX issue: activating all five recommended presets produced zero stocks, and Clear all removed explicit parameter chips but did not deactivate the preset buttons. Each preset had to be toggled off individually. If we implement presets in MarketPulse, active preset state and generated filter state must share one source of truth. A clear action should visibly clear both.

### Sort state

The tour called out the active sort column and direction. This is a small but important feature in a dense grid. MarketPulse should make the sort indicator and direction readable in the header and preserve it when the user opens and closes a chart.

### Sign-in and premium flows

The following actions opened a sign-in or premium gate in the observed session:

- My filters.
- Save filter.
- Watchlists.
- Filters.
- Share active filters.

Share active filters was initially disabled. After activating EMAs Aligned it became enabled, but clicking it opened premium access and did not place a link in the clipboard during the review.

The implementation lesson is not to hide functionality behind a vague disabled state. If a feature is unavailable, explain whether the reason is no active filter, no account, no saved-data store, or subscription access.

## 8. Stock chart drawer

Clicking the chart icon for BODALCHEM opened a right-side technical drawer while the table remained behind it.

### Header

The drawer showed:

- BODALCHEM.
- ₹143.5.
- +13.21%.
- 02 09 26.
- Bodal Chemicals Ltd.
- Commodity Chemicals.
- Small cap.

The header also exposed:

- Add to Watchlist 1.
- Add to Watchlist 2.
- Add to Watchlist 3.
- Copy chart image.
- Copy live chart link.
- Close.

Observed status badges included:

- D: EMA10/20/50/200.
- BO 20.0%.
- D RSI 94.4.
- W RSI 85.7.
- Daily / Weekly markers.
- 52W High -5.5%.

The exact badges are less important than the pattern: the chart opens with the same screen context and surfaces the highest-value signals before the user inspects candles.

### Chart controls

The drawer offered:

- Timeframe: Daily, Weekly, 3M, 6M, 12M.
- Pivot overlay checkbox.
- DarvasBox overlay checkbox.
- EMA overlay checkbox with 10, 20, 50, and 200 controls.
- Set as default.
- Add notes.

The chart stack contained:

1. Candlesticks with EMA lines and optional pivot/Darvas overlays.
2. Volume pane.
3. RSI(14) pane with RSI and its moving average.

Checking Pivot added horizontal pivot levels. Checking DarvasBox added a green box overlay. The chart-level DarvasBox overlay was available independently; the authenticated follow-up did not retest the full Darvas navigation page.

The Set as default control was described as saving the current timeframe and indicators as the default view for every stock's chart. This is a useful preference, but it should be stored per user and should not silently affect another analyst's view.

### MarketPulse fit

MarketPulse already has a stock drawer/chart surface. The Mantis pattern suggests prioritizing:

- Table row to chart continuity.
- Data-date and benchmark badges in the drawer header.
- Explicit Daily / Weekly overlays.
- EMA, pivot, Darvas, volume, and RSI in one synchronized view.
- Notes anchored to a stock and date.
- Copy/export actions that preserve the active screen context.

Do not add a chart indicator merely because Mantis has it. Every overlay needs a corresponding reproducible input in the EOD database.

## 9. Built-in tour: complete interaction inventory

The 22-step tour is valuable because it reveals the intended workflow more clearly than the landing copy.

1. Read market participation: breadth helps decide whether fresh setups have support; click a tile for history.
2. Collapse market health to create vertical room.
3. Jump to a symbol: search ticker or sector without disturbing active filters.
4. Choose a view: Stocks is the main table; Sectors is described as rotation/ranking/turnover/CMF and was verified in the authenticated session; Darvas is described as a published watchlist from screener conditions.
5. Set market-cap scope.
6. Narrow to a sector.
7. Switch Daily / Weekly.
8. Load up to three saved filter templates; sign in is required to save.
9. Save current filters as a template.
10. Filter by watchlist or export to Excel.
11. Open Filters to combine technical, breakout, pivot, earnings, and review conditions.
12. Configure visible table columns.
13. Configure/filter a column: gears set thresholds such as RSI, EMA cross, and volume windows; checkboxes enable filters; dropdowns select sectors or pivot zones.
14. Interpret the RSI trend dot: RSI above or below its own average.
15. Use one-click conditions.
16. Read active removable chips.
17. Share the exact screen.
18. Read the active sort column and direction.
19. Add notes and show only noted stocks.
20. Use three inline watchlist toggles.
21. Sort or compare RS history at T-30, T-15, T-5, and T0.
22. Open a chart with candles, EMA/Pivot/Darvas overlays, earnings reactions, notes, and a saved default view.

The sequence is almost a product specification for a research loop. MarketPulse can adopt the sequence while using its own data and existing page structure.

## 10. Feature translation for MarketPulse

### Capability comparison

| Screening Mantis pattern | Current MarketPulse building block | Recommended action |
|---|---|---|
| Market-health strip | breadth_daily and App/market_summary.py | Add clickable cards and fixed-history drilldowns. |
| Cap/sector scope | Existing sector and universe filters | Make scope visible in every result label and metric tooltip. |
| Daily / Weekly screener | Daily and weekly indicator fields | Add explicit W labels and consistent timeframe semantics. |
| Dense stock table | Desk/research tables | Add optional columns, grouped fields, and inline configuration. |
| Historical price comparison | Existing EOD price history | Add trading-session date picker and Gain% since column. |
| RS momentum and rank history | rs_percentile and relative-strength fields | Separate benchmark-relative momentum from universe rank; persist T-30/T-15/T-5/T0. |
| Sector rotation | App/pages/research/sector_board.py and sector_intel.py | Make one canonical sector-flow page with rank, trend, breadth, turnover, and leaders. |
| Sector ranking matrix | group_tape and sector read model | Add turnover, daily/weekly change, share, share delta, A/D net, average RSI, EMA breadth, breakout breadth, and leaders. |
| Turnover heatmaps | group_trend and turnover summaries | Add 15-session share, own-history multiple, and turnover-weighted A/D heatmaps with exact hover values. |
| Chaikin Money Flow | No canonical CMF field currently | Add 20-session group CMF at T0, T-5, T-10, and T-20 only after documenting the aggregation formula. |
| Sector-index technical table | Index data and existing technical indicators | Add the 21-index Daily / Weekly / Both view with pivot, EMA, RSI, and RS-history fields. |
| Sector RS leadership | RS percentile fields | Add average group rank at T0 versus T-5, sorted by T0, with the selected taxonomy and population shown. |
| Sector taxonomy drilldown | App/pages/research/sector_intel.py | Retain taxonomy mode but add a clear flow/rotation mode. |
| Top-group trend chart | group_trend in App/market_summary.py | Extend from return-only to breadth, turnover share, and benchmark-relative lines. |
| Stage 2 / breakout scoring | VCP and technical indicator pipeline | Expose checklist components, not just a total. |
| Chart drawer | Existing stock drawer and VCP chart surfaces | Add Mantis-style badges and synchronized overlays where data exists. |
| Notes/watchlists | Local user database/UI | Store locally with stock/date/user scope; keep market data read-only. |
| Saved filters | Existing local app configuration patterns | Implement local templates before considering any account service. |
| Excel export | Existing export/report paths | Export the active universe, filters, data date, and visible columns. |

### The important product distinction

Mantis is strongest as a front-end research workflow. Its value is not any one proprietary-looking cell. The value is the chain:

market participation → group flow → filtered candidates → relative-strength confirmation → chart review → note/watchlist.

MarketPulse already has pieces of this chain. The highest return is to connect the pieces and repair the data contract before adding more indicators.

## 11. Existing MarketPulse sector and breadth mapping

The repository already contains several relevant components:

### App/market_summary.py

The current summary layer provides:

- Latest tape and breadth data.
- A breadth history window.
- Index context.
- Session turnover.
- Movers and stock turnover.
- Group-level tape by sector or industry.
- Daily, weekly, and monthly group return summaries.
- Average RS, advance percentage, above-50-EMA percentage, turnover windows, and RS rank.
- A 21-session group trend series for high-turnover groups.
- Near-high summaries.

This means the Mantis market-health and group-flow ideas can be built on existing read models rather than starting from the UI.

### App/pages/research/sector_board.py

The current sector board already describes itself as:

> Who took the rupees. Day / week / month trend. Not a classification tree.

It includes:

- Sector/industry toggle.
- Group tape.
- 21-day line trend for the top six groups by turnover.
- Day-return heatmap.
- Group table.
- Names in the top group.

This is already directionally close to the Mantis sector-rotation promise. The next step is to make the dashboard answer flow questions more directly: rank change, turnover share change, breadth, and benchmark-relative strength should sit beside returns.

### App/pages/research/sector_intel.py

The current sector intelligence page has:

- Taxonomy level selection.
- Minimum market-cap control.
- Focus cards.
- Leaderboard with rank and 5D trend.
- Sector/group status.
- Why-focus explanation.
- RS score.
- 5D, 1M, and 3M returns.
- Percentage above 50 EMA.
- 52-week highs.
- Volume share.
- Top leader stocks.
- Deep-dive stock table.

This is the right home for taxonomy analysis. It should coexist with a separate “flow” mode or be simplified into one page with a clear mode switch. Taxonomy and rotation answer different questions and should not be visually conflated.

### Scripts/sector_metrics.py and schema

The deterministic sector-metrics pipeline already has fields for:

- Point-in-time taxonomy.
- Stock count.
- Benchmark-relative returns over 21 and 63 sessions.
- 50-EMA and 200-EMA breadth.
- Top-three advance concentration.
- Near-52-week-high percentage.
- Advance total.
- Technical/fundamental pass counts.
- Deal metrics.
- Rotation state.

The schema and current product specifications also point toward persisting rank change, rotation rank, rotation score, and related history. Those fields should be filled from one canonical computation rather than being recomputed inconsistently by individual pages.

## 12. Local data audit and a blocker to fix first

The local MarketPulse database was read-only audited while preparing this review.

### Current freshness and universe

- Latest indicators_daily date: 2026-09-02.
- Latest breadth_daily date: 2026-09-02.
- Latest sector_metrics_daily date: 2026-09-02.
- Latest sector_rotation date: 2026-09-02.
- indicators_daily rows on the latest date: 2,398.
- breadth_daily latest universe: 2,398 stocks.
- sector_metrics_daily latest rows: 280 across Broad Industry, Broad Sector, Industry, and Sector levels.

Mantis's default free screener had 1,538 stocks, so the two products currently use different universes or filters. That is acceptable, but the UI must never compare their percentages as if they came from the same population.

### Latest local breadth row

The latest breadth row reported:

| Metric | Value |
|---|---:|
| Stocks | 2,398 |
| Advancers | 902 |
| Decliners | 1,468 |
| Unchanged | 28 |
| Advance percentage | 37.61% |
| Advance-volume percentage | 59.00% |
| Above 10 EMA | 33.61% |
| Above 20 EMA | 36.49% |
| Above 50 EMA | 42.20% |
| Above 100 EMA | 43.04% |
| Above 200 EMA | 39.07% |
| New 20-day highs | 59 |
| New 50-day highs | 49 |
| New 100-day highs | 41 |
| Near 52-week highs | 409 |
| VCP candidates | 649 |
| Five-day average advance percentage | 39.38% |
| Twenty-day average advance percentage | 43.33% |
| Five-day change in above-50-EMA breadth | -7.24 points |
| Twenty-day change in above-200-EMA breadth | -3.31 points |
| Breadth state | Weakening |

This is enough to support a first market-health strip, although Mantis's exact RSI-above-60, daily-pivot, and recent-breakout universe metrics will need explicit local computations.

### Sector read-model precedence issue

The database contains a populated sector_rotation table with 22 current Sector rows, including returns, ranks, RS percentiles, turnover, and rotation states. Sample rows included Healthcare at rank 1 with Leading and Oil/Gas at rank 2 with Weakening.

However, App/sector_read_model.py prefers sector_metrics_daily when that table exists. In the current database, the latest sector_metrics_daily rows had null benchmark-relative returns and blank rotation_state for the relevant sector metrics. As a result, query_sector_rotation_overview returned:

- Null or zero 5D/1M/3M values in the computed overview.
- Zero rank change.
- Derived state rather than the populated sector_rotation state.

This is the most important implementation caveat discovered. Before adding a Mantis-like sector view, decide which table is canonical and enforce it consistently:

1. Either complete sector_metrics_daily so it contains all fields required by the sector board.
2. Or allow the read model to use sector_rotation for rotation outputs and sector_metrics_daily for taxonomy/fundamental outputs.
3. Add a contract test that fails if the selected source produces null returns, null RS, or zeroed rank history on a date where the alternate source is populated.

Until this is fixed, a polished sector-rotation UI could look correct while showing incomplete or misleading values.

### Available stock fields

The current indicators_daily data includes:

- Symbol and trade date.
- Previous close and close.
- Turnover.
- EMA 10, 20, 50, and 200.
- Five-day and one-month returns.
- RSI 14.
- Average volume and relative volume.
- 200-EMA rising flag.
- Weekly EMA 10 and 200.
- Weekly RSI 14.
- Distance below 52-week high.
- RS percentiles over one year and three months.
- VCP state and candidate flag.

This supports much of the stock-table foundation. Weekly EMA 20/50, pivots, exact breakout age, monthly setup, event reaction, and RS rank history should be added only where their definitions and source data are clear.

## 13. Recommended MarketPulse implementation plan

### Phase 0 — repair the data contract

Do this before UI expansion:

- Choose the canonical sector rotation source and document source precedence.
- Populate or explicitly null every displayed sector field.
- Persist rank, rank change, score, turnover share, breadth, and benchmark-relative returns at the same point-in-time date.
- Add a trading-calendar/session-key helper for T0, T-5, T-15, and T-30.
- Add universe and taxonomy-level fields to every sector metric query.
- Add data-quality checks for stale dates, null rates, duplicate groups, and mismatched stock counts.
- Keep raw, derived, and presentation fields separate.

### Phase 1 — market-health strip

Add a shared component above the research table:

- Advance/decline net or breadth percentage, labeled precisely.
- Above 20 EMA.
- Above 200 EMA.
- RSI above threshold.
- Above daily pivot.
- Near 52-week high.
- Recent breakout.
- Current data date.
- Active universe and cap/sector scope.
- Change versus prior trading session and optional five-/20-session change.
- Click-to-history modal.
- Collapse/expand state.

Reuse the existing breadth_daily history rather than making each page calculate its own trend.

### Phase 2 — sector rotation / flow workspace

Build a single clear “Rotation” mode in the existing sector research area:

Top summary:

- Leading group.
- Improving group.
- Weakening group.
- Lagging group.
- Total turnover and turnover share.
- Advance/decline breadth.

Main visual:

- Rank-versus-time or rank-change table.
- 21-session trend lines for selected groups.
- Return, RS versus Nifty, breadth, turnover share, and near-highs as switchable series.
- Small heatmap for group returns and breadth.

Detail table:

- Rank.
- Rank change over five and 20 sessions.
- Rotation state.
- 1D, 5D, 1M, and 3M return.
- RS versus benchmark.
- RS percentile within the selected taxonomy level.
- Percentage above 50 EMA and 200 EMA.
- Advance percentage.
- Turnover share and change in share.
- Near-52-week-high percentage.
- Top leaders with chart links.

The page should state whether a group is strong because of broad participation, a few concentrated leaders, or turnover without price confirmation. This is more useful than a single “rotation score”.

### Phase 3 — stock screener and chart continuity

Add the highest-value free-surface patterns:

- Grouped optional columns.
- Column-level About/help.
- Gear-driven thresholds.
- Active removable chips.
- One-click presets.
- Correct Clear all behavior.
- Trading-session historical comparison.
- RS rank history.
- Chart header badges.
- Pivot/Darvas/EMA/volume/RSI overlays.
- Notes tied to stock and date.
- Export containing active filters and data metadata.

Implement local persistence for:

- Filter templates.
- Three watchlists.
- Notes.
- Chart default preferences.

Keep the feature local and auditable before introducing remote accounts or payments.

### Phase 4 — validation and research quality

Add automated tests and fixtures for:

- Breadth card values against the latest breadth_daily row.
- Cap and sector scope counts.
- Daily versus Weekly field selection.
- T-5/T-15/T-30 session alignment.
- Sector rank and rank-change calculations.
- Turnover-share aggregation.
- Concentration versus breadth interpretation.
- Empty and stale data states.
- Clear-all preset state.
- Export metadata.

Add a small analyst-facing “How this is calculated” panel for each score and composite.

## 14. Data and formula guidance

### Breadth

Use stock-level membership at a point in time:

- Above EMA: close above the specified EMA.
- RSI above threshold: RSI above threshold on the selected timeframe.
- Above pivot: close in the selected pivot zone.
- Near high: distance below rolling 52-week high within the selected threshold.
- Recent breakout: qualifying event within the selected trading-session age.

Always retain numerator, denominator, universe identifier, and session date. A percentage without those fields cannot be audited.

### Sector aggregation

For each taxonomy level and trade date:

- Aggregate turnover before calculating turnover share.
- Calculate advance percentage from stock counts, not the average of per-stock percentages.
- Calculate benchmark-relative return against a named index and defined lookback.
- Expose both broad participation and top-leader concentration.
- Use a weighted metric only when the weighting scheme is shown.

For Chaikin Money Flow, if added later, aggregate the money-flow volume numerator and volume denominator across the group before dividing. Do not average stock-level CMF ratios; that creates a different statistic.

### RS rank history

T-30, T-15, T-5, and T0 must mean trading sessions. Do not subtract calendar days. Missing sessions and IPO histories should be displayed as unavailable, not as zero.

Store:

- Benchmark-relative return or RS-line definition.
- Lookback.
- Universe.
- Percentile population.
- Session date.
- Rank and total eligible count.

### Composite scores

If MarketPulse combines return, breadth, turnover, RS, and near-highs into a score:

- Show each component.
- Normalize within the selected taxonomy level.
- Publish weights in the tooltip.
- Add confidence or data-coverage status.
- Avoid a score when too many components are missing.
- Make “Leading”, “Improving”, “Weakening”, and “Lagging” explainable from visible rules.

## 15. UI and copy recommendations

Adopt the clarity of Mantis's dense table while improving a few weak points:

- Put the data date next to every primary screener result.
- Show “within current universe” on percentile metrics.
- Distinguish “net advance/decline” from “percentage advancing”.
- Use singular/plural-safe count copy.
- Keep Daily / Weekly in every timeframe-specific header.
- Show the selected historical date in the column header.
- Explain why a filter is disabled or gated.
- Make Clear all clear presets, chips, column thresholds, and scope only when the action says it will.
- Keep premium-like capabilities local and reversible in MarketPulse.
- Avoid unexplained red/green colors; include symbols or text for accessibility.
- Show “insufficient history” rather than grey cells with no explanation.

## 16. What to defer

Defer these until the core data contract and sector board are reliable:

- Replicating the premium subscription/access model.
- A published Darvas watchlist page.
- Remote account sync.
- Live filter-sharing links.
- An earnings-reaction module without a trusted event source.
- A large number of additional setup scores.
- Copying Mantis's exact proprietary-looking formulas.

The public review identified the interaction model. The authenticated follow-up verified the actual Sectors panels and their live behavior, but not the full Darvas page or any inaccessible account-specific persistence behavior.

## 17. Acceptance criteria for a first implementation

The first Mantis-inspired release should be considered successful when an analyst can:

1. See the current market regime and its recent history without leaving the screener.
2. Confirm the active data date, universe, cap scope, sector scope, and timeframe.
3. Sort groups by a documented rotation score and inspect the component values.
4. See whether group strength is broad or concentrated.
5. Click from a leading group to its filtered stocks.
6. Apply a technical threshold and see a precise removable chip.
7. Switch Daily / Weekly without ambiguous labels.
8. Compare RS rank at T0, T-5, T-15, and T-30 trading sessions.
9. Open a stock chart without losing the table state.
10. Record a local note and export the current research set with filters and metadata.
11. Receive an honest empty, stale, or insufficient-history state.
12. Verify the displayed sector values against the canonical database source.

## Final recommendation

Screening Mantis is worth learning from because it packages breadth, sector flow, relative strength, screening, and chart review into one continuous loop. Its most transferable idea is not a particular indicator; it is the information hierarchy.

For MarketPulse, implement the work in this order:

1. Repair sector-metric source precedence and fill missing rotation fields.
2. Add the clickable market-health strip.
3. Upgrade the existing sector board into an explainable rotation/flow view.
4. Add grouped optional screener columns, chips, and session-based RS history.
5. Tighten stock-drawer continuity, notes, and exports.

That path gives MarketPulse the better sector rotation and data-trend experience requested here while preserving its existing data discipline and local-first architecture.
