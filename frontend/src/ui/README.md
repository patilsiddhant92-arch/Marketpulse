# One UI standard across the six tabs

Every tab (Pulse, Setups, Sector Intel, Deals, Charts, Research) builds from these pieces. Use them instead of a
tab-local copy; tab kits (`routes/groups/kit.tsx`, `routes/research/LabParts.tsx`, `screener/cells.tsx`) re-export
the moved ones so older imports keep working.

| Need | Component | Notes |
|---|---|---|
| Long / sortable list | `DataTable` | Virtualised, keyboard rows, NULL = "—" sorted last. Role `grid`. |
| Short study / evidence table | `StaticTable` | No sort, same header and row look. (Was Research `SimpleTable`.) |
| Status / label | `Chip` (`tone`, `variant`) | Tones map to the colour tokens: positive = up, negative = down, warn, info, accent, violet, neutral. |
| Group state | `GroupStateChip` | Favour / Neutral / Caution + reason. Data from `context/groupState.ts` (Pulse-owned). |
| Deal icon beside a symbol | `DealIcon` / `SymbolWithDeal` | One `/deals/flags` request per as_of (`context/dealFlags.ts`). |
| Signed number | `SignedNum` | Coloured by sign with the up / down tokens. |
| Toggle (views, levels, windows) | `Segmented` | `role="radiogroup"`. |
| Source honesty | `SourceNote` | ok / computed live (partial) / unavailable with the server reason. |
| Drawer | `Drawer` | Right-hand panel with Esc layer. Deals, Research and Setups drawers use it. |
| Nothing matched | `EmptyState` | A real, successful empty result. |
| API failed | `ErrorState` | Distinct from empty. |
| Data gap | `DataGapBanner`, `DataGapList`, `DataWarningChip` | A window spans missing sessions, a study stops at a gap, served gap lists. |

Colours: Tailwind token classes only (`text-up`, `bg-warn/10`, ...). Canvas / SVG code reads tokens with
`lib/tokens.ts` `tokenColor()`; no hex literals in tab code. The chart (`ui/Chart.tsx`, `charts/*`) keeps its own styling.
