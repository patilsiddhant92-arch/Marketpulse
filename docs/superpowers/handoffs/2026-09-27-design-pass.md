# Design pass: refined dark terminal (G3)

| Field | Value |
| :--- | :--- |
| **Date** | 2026-09-27 |
| **Branch** | `feat/g3-premium-design` (from `feat/truth-contract` @ 1d43fe7) |
| **Spec** | `docs/superpowers/specs/2026-09-26-marketpulse-professional-rebuild-design.md` §2 D5, §9 |
| **Scope** | Frontend only: `styles/tokens.css`, `tailwind.config.js`, `ui/*`, `shell/*`, plus a header band and layout wrapper per tab |
| **Method** | Live DB (read-only) through uvicorn :8793 + Vite :5193; every tab captured at 1440×900 with headless Chrome, before and after |

## 1. Critique (before)

The app worked, but it looked like the old app ported over: functional, not premium.

| Area | What was wrong |
| :--- | :--- |
| **Hierarchy** | Every tab opened straight into controls and a wide table. Nothing told you the day's story at a glance. On Screener, five stacked control bars (presets, rules, floors, summary, row count) came before the first row. |
| **Density** | The density was right for a terminal, but everything carried the same weight: 11px uppercase headers, 12.5px cells, 13px body. The eye had no entry point. |
| **Typography** | No type scale above 13px, except the Desk verdict (24px). Big numbers (breadth, matches, net flow) were the same size as cell values. Inter and IBM Plex Mono were loaded but only used at two sizes. |
| **Colour semantics** | Green and red were on every %-cell *and* every chip, so colour stopped meaning anything. Zone colour and sign colour competed. The "New vs yesterday" rail was a wall of bordered amber pills. |
| **Spacing / elevation** | Flat 1px borders on a near-black page, 4px radius, no elevation. Panels, bars and tables all merged together. The zebra (`surface/40` on `bg`) was invisible. |
| **Chrome** | Top bar (44px) plus a separate environment strip (30px) used 74px before any tab content. The environment verdict also showed a third time on Desk. |
| **Charts** | Charts tab was the strongest screen (charts are prominent). Elsewhere, sparklines were only in table cells, and no KPI had a trend. |
| **Empty / loading** | A pulse skeleton, and small plain icons on empty/error states. The two were hard to tell apart at a glance. |
| **Numbers** | Tabular mono numerals and right alignment were already consistent (good). |
| **Consistency** | Section headers were hand-rolled per tab (`text-2xs font-semibold uppercase` repeated). Deals, Groups and Research each had their own header rhythm. |

## 2. Design-system changes

**Tokens (`styles/tokens.css`)**
- Cool blue-black surfaces at about +5 L per step (`bg 8/10/15` → `surface-3 28/33/44`) and a softer `line`. Text steps `fg / fg-2 / fg-3` still pass WCAG AA on every surface (`tokens.test.ts` passes, 44 checks).
- Semantic colours tuned slightly (`accent`, `up`, `down`, `warn`, `info`, `violet`) and the verdict scale kept. New Tailwind `zone-good/neutral/caution/bad` aliases.
- Elevation: `--shadow-card` (inset top highlight + soft drop) and `--shadow-pop`. `--radius-card: 6px`.
- Motion: `--dur-fast 150ms`, `--dur-base 200ms`, `--ease-out`, plus `mp-fade-in` and `mp-shimmer` primitives. `prefers-reduced-motion` now also clamps the iteration count, so the infinite shimmer and ping stop.
- `.mp-label` (11px / 600 / 0.06em / uppercase) is the one label style.
- `.mp-tr` row styles: opaque layered zebra, hover and active backgrounds. Sticky cells inherit them, so pinned columns match their row.

**Tailwind**
- Type scale `text-label 11 < body 13 < text-title 15 < text-kpi 22 < text-display 28`.
- `shadow-card/pop`, `rounded-card`, `duration-fast/base`, `ease-out`.

**`lib/cn.ts`: latent bug fixed**
- tailwind-merge did not know the custom font sizes, so `cn('text-table', 'text-fg')` silently dropped the size (it read both classes as colours). It now knows `2xs / table / label / title / kpi / display`.

**Components (`ui/`)**
- `Card` (base / raised / inset) and `SectionHeader` (bar / plain). `Panel` is rebuilt on them, with the same API plus `icon`.
- `KpiTile`: label, big tabular value, delta pill (`auto` / `invert` / `neutral`), caption, area sparkline, and zone colour from the metric dictionary (with its tooltip) or an explicit tone. A thin tone rail sits on the left. Variants: `hero` (display size, tinted wash) and `compact`. Can be clickable/selected.
- `KpiList`: a band tile holding a ranked top-3 list.
- `GlanceBand`: one card, tiles separated by hairlines, optional right `aside`, and a `compact` variant.
- `DataTable`:
  - calmer header (`tracking 0.05em`, the sorted column in accent) and a 36px toolbar
  - visible zebra, 150ms hover, accent-rail active row, `bg-surface` body
  - **column-group headers** (`column.group`, via `columnGroupRuns`)
  - **heat-tinted cells** (`column.heat(v,row) → -1..1`, via `heatStyle`, tokens only)
- `Chip`: `variant: soft | outline | dot`, softer fills. New `Badge`.
- `Spark`: `area` fill.
- `Skeleton`: shimmer.
- `EmptyState` / `ErrorState`: icon discs (neutral vs tone-tinted) and fade-in. The ErrorState retry button is more visible.
- `Tooltip`: 6px radius, pop shadow, fade-in.

**Shell**
- Top bar is 48px:
  - logo mark + wordmark
  - tabs with small key caps and a 2px accent underline
  - the **environment strip is folded into a top-bar pill** (verdict dot + word + pillar squares, what-changed on wide screens, click opens the drawer)
  - freshness chip with a brief "live" ping
  - consistent 28px controls
- Net result: 26px more vertical space for every tab. The history banner uses the label style.

## 3. Story headers ("at a glance" bands)

All bands reuse queries each tab already makes. There are no new endpoints. The Deals band reads `deals/houses` with the Houses view's own default query, so the cache is shared.

| Tab | Band |
| :--- | :--- |
| **Desk** | **Verdict hero** (display-size word in verdict colour, action, pillar squares, what-changed; click opens the drawer) · **Above 50 EMA** (Δ, 60-session spark, 10-EMA in caption) · **Above 200 EMA** · **Net new highs** (Δ, spark, advancers and distribution days in caption) · **India VIX** (5-day change, inverted colour) · **Squeeze / 10 EMA / VCP queue** tiles (count, +new pill, "n new · m dropped"; click switches the queue below). Leading groups moved to the top of the right rail. |
| **Screener** | Preset · passing (hero count, as-of) · New today · Dropped · Top group (industry with most matches) · Strength ≥ 90 (median strength) · Evidence hit +2R (or "n=0, too few"). |
| **Groups** | Market · MidSml400 21d (hero, "x of y groups down over 21 sessions") · Healthy groups (median health) · Weak groups (mixed) · Leading vs peers (# falling in absolute terms) · Top 3 by Health (click drills in) · aside with group count, floor and as-of. The old context-sentence row is removed (its facts are in the band). |
| **Deals** (Today) | Net flow ex-PROP (hero, buy/sell totals) · Accumulate (+ fresh buyers) · Distribute (strategic, churn) · Biggest net buys top 3 (click opens Stock 360) · Top house this session (click opens the house drawer). |
| **Charts** | Slim band that replaces the old info row: Source · Symbols · Up today (x / n) · Median strength · Page; aside holds as-of, paged/partial warnings and the key hints. |
| **Research** | Analogs say (hero: "70% lower" at 20 sessions, median) · Nearest match (distance, verdict then, 20d outcome) · Most recent analog (20d outcome, 60d) · Median next 60 sessions (up/down, n) · Follow-through median (n). |

Parallel-work note: the Desk and Groups internals are untouched. Desk changed only `DeskRoute` (band on top, leading groups into the rail) and `desk/EnvironmentPanel.tsx`, which is now the band (same export name). `SidePanels` got a one-line change that calms the diff chips. Groups changed only the header area of `GroupsRoute`.

## 4. Before / after (1440×900, live DB, session Fri 25 Sep 2026)

| Tab | Before | After |
| :--- | :--- | :--- |
| Desk | The verdict panel and a tiny breadth row shared the top with leading groups; the queue tab counts were the only queue summary. | One band reads left to right: *Mixed, selective half size → 34.6% above 50 EMA (+1.0) → NNH −21 → VIX 12.16 (+6.8% 5d) → Squeeze 76 (+26)*. Breadth is readable from across the room. |
| Screener | Five control bars, then the table. "313 matches" was a small line of text. | Band first: **313** passing · **21** new · **18** dropped · top group **Pharmaceuticals (40)** · **152** at strength ≥ 90. The controls follow. |
| Groups | A dense one-line sentence and a separate health count line. | **−3.6%** market line in red, **47** healthy / **54** weak, **45** leading, top 3 by Health one click from a drill. |
| Deals | Event chips only; no totals. | **−₹414.2 Cr** net flow ex-PROP, **1** accumulate / **15** distribute, biggest buys, top house. |
| Charts | The info row carried only the as-of and a hint. | A slim band (≈48px) with source, **314** symbols, **211/314** up today and median strength; the charts stay dominant. |
| Research | The analog summary sat inside the view. | Band headline **70% lower** over 20 sessions, nearest match 9 Jun 2026, follow-through 39.9%. |
| All | 74px of chrome; flat panels; invisible zebra. | 48px top bar holding the environment pill; card elevation; visible zebra and hover; shimmer skeletons. |

Screenshots were captured locally (headless Chrome `--screenshot`, 1440×900). They are not committed to keep the repo lean; re-capture with the same command against a dev server.

## 5. Verification

- `npx tsc --noEmit`: clean.
- `npx eslint src`: 0 errors. One warning (TanStack Virtual `incompatible-library`) was already there.
- `npx vitest run`: 24 files / 198 tests pass, plus new `lib/glance.test.ts`, `ui/KpiTile.test.tsx` and the DataTable helper tests.
  - `GroupsDeals.test.tsx` now asserts the Deals band and has a 15s budget on the drill test (three sequential fetch-render steps).
  - Under a loaded machine, the `/stock/:sym` and drill tests can hit the default 5s timeout. They pass on a quiet run.
- `npm run build`: builds. The main chunk is about 992 kB, down as legacy code is deleted.

## 6. Follow-ups (not done here)

- Adopt `column.group` / `column.heat` in the Screener and Groups column specs, e.g. group "Returns 1M/3M/6M" and heat-tint the return columns instead of colouring the text red/green. The API exists and is tested; it is not wired into any route, to avoid clashing with parallel work.
- Screener's summary row now repeats the band. It can shrink to the actions and the dropped popover once the tests are moved to the band.
- Research views have large empty areas below short content (analogs fan). They need a layout pass inside `routes/research/*`.
- The `envstrip` height token is unused now and can be removed with the legacy breadth drawer.
