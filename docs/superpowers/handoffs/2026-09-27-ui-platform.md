# UI platform hand-off (sub-project 5)

| Field | Value |
| :--- | :--- |
| **Date** | 2026-09-27 |
| **Branch** | `feat/w4-ui-platform` (from `feat/truth-contract` @ d871ff9) |
| **Spec** | `docs/superpowers/specs/2026-09-26-marketpulse-professional-rebuild-design.md` §2 D4–D9, §6, §7, §8, §9 |
| **For** | Tab builders (Desk, Stock 360, Charts, Screener, Groups, Deals, Research) |

## 1. Stack and commands

React 19 · TypeScript strict · Vite 8 (dev port **5199**, proxies `/api` → `127.0.0.1:8000`) · Tailwind 3 on design tokens · TanStack Query 5 / Table 9 / Virtual 3 · cmdk · lightweight-charts 5 · react-router 8 · Vitest + Testing Library.

```bash
npm ci
npm run dev          # http://localhost:5199
npm run build        # tsc --noEmit && vite build
npm run typecheck
npm test             # vitest run
npm run lint         # eslint (bans raw hex outside legacy files)
npm run format       # prettier
npm run gen:api      # openapi-typescript openapi.json -> src/api/types.gen.ts
```

## 2. Where things live

```
src/styles/tokens.css      all colours (RGB triples), fonts, sizes  — the ONLY place for raw colours
src/lib/fmt.ts             en-IN formatters (NULL -> "—")
src/lib/*.ts               layers (Esc stack), tradingview, clipboard, storage, tokens, indicators
src/api/types.gen.ts       generated — never edit
src/api/types.ts           THE import point for API types + derived EndpointMap
src/api/client.ts          apiGet / apiPut, ApiError, envelope helpers
src/api/query.ts           createQueryClient, useApiQuery (injects ?as_of), retry policy
src/metrics/dictionary.ts  useMetricsDictionary, useMetric(key), zoneFor, toneForZone
src/ui/                    component kit (barrel: src/ui/index.ts)
src/shell/                 Shell, TopBar, environment strip/drawer, palette, sidecar, URL state
src/routes/                one file per tab + registry.tsx + legacy.tsx (temporary bridge)
src/components/, utils/, types.ts   LEGACY — delete as each tab migrates
```

## 3. How a tab plugs in

1. Edit (or replace) the route file: `src/routes/DeskRoute.tsx`, `ScreenerRoute.tsx`, `GroupsRoute.tsx`, `DealsRoute.tsx`, `ChartsRoute.tsx` (lazy), `ResearchRoute.tsx` (lazy), `StockRoute.tsx` (`/stock/:sym`, lazy). Default export, no props.
2. `src/routes/registry.tsx` maps tab id → component. Keep Charts/Research lazy.
3. Tabs are **kept mounted** after first visit (hidden, not unmounted) and each has its own `ErrorBoundary` (reset on `as_of` change). Don't rely on unmount for cleanup of cross-tab state.
4. Drop the `LegacyFrame` wrapper and the legacy component import when the rebuild lands; delete the legacy file once nothing imports it. Remove the matching old `/api/*` endpoint (spec §8).
5. The active tab's `<section>` has `data-active="true"`; give your filter input `data-filter-input` and the `/` key focuses it.

### Reading data

```tsx
import { useApiQuery } from '../api/query';

const q = useApiQuery('desk/queue/{name}', { params: { name: 'vcp' }, query: { tf: 'D', limit: 500 } });
// q.data: Envelope<QueueRow>  -> { as_of, freshness, total, returned, rows, meta }
```

- Endpoint keys are the path after `/api/v2/`, with `{param}` templates. Query and row types come from the generated OpenAPI types; a typo is a compile error.
- `as_of` comes from the URL automatically (don't pass it). Override with `{ asOf: '2026-03-12' | null | false }` in the 3rd argument.
- Query keys always include `as_of`, so time travel re-keys every query.
- Errors are `ApiError` with `kind`: `network` (server down / proxy 502/504), `not_found` (404, e.g. endpoint not deployed), `busy` (503, `retryAfterMs` from Retry-After), `client`, `server`, `parse`, `aborted`. Retries: never on 4xx; 503 up to 3 using Retry-After; network/5xx twice with backoff.
- `isUnavailable(env)` is true when `meta.status === 'unavailable'`; show `meta.reason`.
- Non-envelope endpoint: `/api/v2/health` (used by the shell's freshness chip — you shouldn't need it).
- Writes: `apiPut('watchlist', { symbols })`, `apiPut('notes/{sym}', { body }, { params: { sym } })`.

### Shell API (`useShell()` from `src/shell/ShellContext.tsx`)

| Member | Use |
| :--- | :--- |
| `symbol`, `openSymbol(sym \| null)` | Stock 360 sidecar symbol (URL `?sym=`). Call from row focus so the sidecar follows J/K. |
| `openStockPage(sym)` | Full Stock 360 page (Enter on a row). |
| `openCharts(symbols?)` | "Open in Charts" (`/charts?syms=A,B`). |
| `goTab(id)` | Navigate keeping `as_of`/`sym`. |
| `watchlist`, `isWatched`, `toggleWatch`, `removeWatch`, `clearWatch` | Watchlist (localStorage today; wire to `/api/v2/watchlist` in the Stock 360 step). |
| `recent`, `paletteOpen/setPaletteOpen`, `breadthOpen/setBreadthOpen` | Palette recall; legacy breadth drawer. |

URL helpers (`src/shell/urlState.ts`): `useAsOf()`, `useSidecarSymbol()`, `useUrlParam(name, { push? })` for tab state (preset, filters, group, view), `useGlobalSearch()`, `isSymbol()`, `isISODate()`. Tab-specific params are dropped on tab switch; `as_of` and `sym` survive.

Global keys already handled by the shell: Ctrl/Cmd+K, 1–6, W (watch selected), T (TradingView), C (copy `NSE:SYM`), `/`. Esc closes the innermost layer via `useEscapeLayer(open, onClose)` from `src/lib/layers.ts` — use it for any popover/drawer you build.

## 4. Component API (`import { … } from '../ui'`)

### DataTable\<T\>

| Prop | Type | Notes |
| :--- | :--- | :--- |
| `columns` | `DataTableColumn<T>[]` | see below; keep stable (`useMemo` / module scope) |
| `rows` | `readonly T[]` | keep stable; use a module-level empty array fallback |
| `getRowId` | `(row, i) => string` | required, stable (symbol) |
| `label` | `string` | accessible name |
| `total` | `number \| null` | pass `envelope.total`; shows "N of M rows (paged)" / "total unknown" |
| `loading`, `error`, `onRetry`, `emptyState` | | skeleton / ErrorState / EmptyState when no rows |
| `initialSort` or `sorting` + `onSortingChange` | `SortSpec[]` = `{id, desc}[]` | controlled mode for URL-held sort |
| `columnVisibility` + `onColumnVisibilityChange` | `Record<id, boolean>` | optional controlled visibility |
| `activeRowId`, `onActiveRowChange(row)` | | J/K/Arrow/Home/End/PgUp/PgDn focus; wire to `openSymbol` |
| `onRowActivate(row)` | | Enter / double-click |
| `onRowClick(row)` | | |
| `onSortedRowsChange(rows)` | | current visible order — feed the TradingView export / Open in Charts |
| `rowHeight` (28), `toolbar`, `hideToolbar`, `className` | | give the table a bounded height (flex parent) |

`DataTableColumn<T>`: `id`, `header`, `accessor` (key or fn), `format?: FormatKind` (`num|int|pct|signedPct|signed|inr|cr|lakh|rupeesCompact|ratio|date|text`; numeric kinds right-align and sort descending first), `digits?`, `cell?(value, row)` (gets non-null values only unless `renderNull`), `metricKey?` (header tooltip from the dictionary), `headerTitle?`, `align?`, `width?` (px, default 96 / 140 text), `grow?`, `sortable?`, `hideable?`, `defaultHidden?`, `sortDescFirst?`, `sticky?`.
NULL / NaN / '' render as "—" and sort **last in both directions**.

### Chart

| Prop | Type | Notes |
| :--- | :--- | :--- |
| `bars` | `OHLCBar[]` (`{time, open, high, low, close, volume?, delivery_pct?}`) | adjusted, oldest first. `toOHLC(BarRow[])` in `routes/StockRoute.tsx` drops incomplete rows. |
| `timeframe`, `onTimeframeChange` | `'D'\|'W'\|'M'` | toggle shown only when the handler is passed |
| `resample` | `boolean` (true) | resample daily bars client-side; set false if you fetch `tf=W/M` bars |
| `emaPeriods` | `number[]` (10/20/50/200) | computed client-side on displayed closes |
| `overlays` | `{id, label, data: {time, value}[], color?: TokenName, dashed?}[]` | Darvas box, pivots, server EMAs |
| `volume` | `boolean` (true) | pane 1, opacity by delivery % |
| `rs` | `{label, data: {time, value, new_high?}[]} \| null` | RS pane with new-high dots |
| `markers` | `{time, kind, text?}[]` | kinds: `split, bonus, demerger, results, ex_date, deal_buy, deal_sell, custom`; snapped onto W/M bars |
| `syncGroup` | `string` | date-synced crosshair across charts with the same group (Charts grid) |
| `logScale`, `height`, `initialBars` (150), `showLegend`, `onCrosshairTime(iso)`, `label`, `className` | | sizes via ResizeObserver; give it a sized parent |

### Metric
`metricKey` (dictionary key), `value`, `format` (`num`), `digits`, `label` (override plain_name), `showLabel` (true), `delta` + `deltaFormat` (`signed`), `size` `sm|md|lg`, `zoneColor` (true). Tooltip = plain name, measures, zones (current one highlighted), read-with + why, caveats. No dictionary entry → raw value, neutral colour.

### Others
- `Spark` — `values` (NULL breaks the line), `label` (required, aria), `width` 72, `height` 20, `tone` `auto|up|down|neutral|accent`, `baseline`, `showLastDot`.
- `Chip` — `children`, `tone` `neutral|positive|negative|warn|info|accent|violet`, `size` `xs|sm`, `title`, `icon`, `onClick` (renders a button), `selected`.
- `EmptyState` — `title`, `detail`, `action`, `icon`, `compact` (a real empty result).
- `ErrorState` — `error`, `onRetry`, `title`, `compact`; `describeError(error)` maps ApiError kinds to copy (API unreachable / Not available yet / Database busy, retrying in Ns / …).
- `Skeleton` (`width`, `height`), `SkeletonRows` (`rows`, `columns`, `rowHeight`, `label`).
- `ErrorBoundary` — `name`, `resetKeys`, `fallback?`. The shell already wraps each tab.
- `Tooltip` — `content`, `side`, `delay`; portal-rendered, never clipped.
- `Drawer` — `open`, `onClose`, `title`, `width`, `side`, `actions`; modal, Esc-aware.

### Metric dictionary
`useMetric(key)` → `{ def, zoneFor(value), toneFor(value), isLoading }`; `useMetricsDictionary()` → `{ byKey, … }`. Fetched once (`staleTime: Infinity`). Served tones map `good→positive`, `neutral`, `caution→warn`, `bad→negative`; `TONE_TEXT[tone]` gives the text class.

### Formatting (`src/lib/fmt.ts`)
`fmtNum, fmtInt, fmtINR, fmtCr` (value in Cr), `fmtL`, `fmtRupeesCompact` (rupees → Cr/L), `fmtCompactIN` (counts), `fmtPct, fmtSignedPct, fmtSigned, fmtRatio, fmtDate, fmtDateShort, fmtWeekday, fmtDateWithDay, fmtValue(v, kind, digits)`, `DASH`. Percent inputs are in percent units.

### Environment
`useEnvironment()` (`src/shell/environment.tsx`) returns `{ q, view, unavailable }`; `view` is `toEnvironmentView(rows)` from `regimeView.ts` (verdict, derived what-changed line, pillars in spec order with metrics/notes, readings, verdict history). Reuse it for the Desk Environment panel instead of re-reading the regime endpoint.

## 5. Styling rules
- Colours only through tokens: `bg-bg|surface|surface-2|surface-3`, `border-line|line-strong`, `text-fg|fg-2|fg-3`, `accent up down warn info violet`, verdict `v-favourable…v-danger`; alpha works (`bg-up/10`). Canvas code: `tokenColor('up', 0.5)`.
- Numbers: `num` class (mono, tabular, slashed zero). Tables `text-table` (12.5px), rows 28px, nothing below `text-2xs` (11px).
- Desktop-first, check at 1280 px.
- ESLint fails on any raw hex outside the legacy files; `src/styles/tokens.test.ts` fails if a text token drops below 4.5:1 on any surface.

## 6. Testing
- `src/test/setup.ts` gives jsdom element sizes (so virtual rows render) and a ResizeObserver stub.
- Pattern for a tab smoke test: `src/shell/Shell.test.tsx` — `createMemoryRouter(routes, { initialEntries })`, `<App router queryClient />`, stub `fetch` with fixture envelopes, `vi.mock` heavy legacy components.
- Don't render `Chart` in jsdom (canvas); test its data mapping instead.

## 7. Known gaps / next steps
- Watchlist and notes are local (localStorage); switch to `/api/v2/watchlist` and `/api/v2/notes/{sym}` in the Stock 360 step.
- No symbol-search endpoint: Ctrl+K accepts any valid typed symbol plus watchlist/recent. Add `symbols` to API v2 if full search is wanted.
- The regime schema has no `what_changed`, pillar question or rule text; the UI derives the change line from `previous_verdict / changed_on / days_in_state` and uses the §6.1.2 questions. If the API later serves them, prefer the served text.
- Legacy views ignore `as_of` (a violet notice says so).
- Main bundle is ~820 kB (legacy workspaces + charts); shrinks as legacy files are deleted.
