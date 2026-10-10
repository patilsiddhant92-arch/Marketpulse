# 11. Implementation sprint (2026-10-10)

Siddhant asked us to build every tab that's pending, with several agents in parallel. After that comes the cross-tab pass: one UI standard everywhere and the data wired between tabs.

| Tab | Spec | Agent branch | Worktree |
|---|---|---|---|
| Pulse (was Desk) | 02-tab1-pulse.md (locked) + mockups/tab1-pulse.html | hark/impl-pulse | work/wt/pulse |
| Setups / Screener | 06-tab2-setups.md (locked spec at end) + mockups/tab2-setups.html | hark/impl-setups | work/wt/setups |
| Sector Intel (Groups) | 07-tab-sector-intel.md + mockups/tab-sector-intel.html + stock-heatmap.html | hark/impl-sectors | work/wt/sectors |
| Deals | 08-tab-deals.md + mockups/tab-deals.html (v1.2) | hark/impl-deals | work/wt/deals |
| Charts | 09-tab-charts.md | hark/impl-charts | work/wt/charts |
| Research (+History Lab) | 10-tab-research.md (§§1-13) | hark/impl-research | work/wt/research |

## Rules for every agent
- Work only in your own worktree and branch. Commit there as `Hark <patilsiddhant92@gmail.com>`. Never push, and never touch main. Hark merges into hark/harkpro.
- Backend: put the new service code in `App/services/<tab>*.py` and the new endpoints in a NEW router file, `App/api/v2/routes_<tab>.py`. Register it with one line in `App/api/v2/__init__.py`. Don't rewrite `routes.py`.
- Frontend: keep your work inside your tab's route folder (`frontend/src/routes/<tab>/` or the existing tab folder). Shared files (`shell/tabs.ts`, `routes/registry.tsx`, `ui/`, `api/types.ts`): add only, keep edits minimal, and list every one in your report.
- Reuse `frontend/src/ui` components. Don't restyle globally; the cross-tab UI standard pass comes next.
- `Database/marketpulse.duckdb` is shared (a symlink). Open it read-only. Test pipeline changes on a temp DB.
- Tests: pytest for your services, vitest for your folder, plus `npx tsc --noEmit`. All must pass before you commit.
- Commentary follows 04-writing-style.md. Standing rules from the README apply: lists ≥ ₹1,000 Cr, breadth on all stocks, every reading vs history.
- Open questions in a round-1 doc: take the doc's recommended default and list it as an assumption.

## Result (2026-10-10 09:45)
All six branches are merged into hark/harkpro. The merged checks pass: openapi regenerated, tsc clean, pytest 260 passed (new tab suites + contract + setup_daily), vitest 303 passed across all folders.
Merge notes: GroupsDeals.test.tsx was deleted because both of the old views it tested were replaced.

### Backlog for the cross-tab pass
- One shared Pulse mood / group state service. Today Sector Intel and Setups each compute their own; Pulse is the source.
- Wire the deal feeds everywhere: `/deals/flags` → the stockContext deal icon on every list; `/deals/markers` or `/charts/{sym}/deal-candles` → one deal-candle source for all charts. Charts in other tabs' drawers should use the global chart settings.
- Charts source picker: add the Pulse movers, Deals Watch/History/house buys and Setups views; drop "Pre-move watch".
- Tab labels/hints: Screener → Setups? Research hint. Remove the legacy Today/Setups views from Pulse once Setups owns the queues. Delete the unused old Groups/Research/Deals view files.
- TradingView copy: map `&` → `_` in the shared helper. Type the Deals endpoints with response models.
- Shared Chart: add range shading + coloured markers (Research case chart built its own).
- Wire Scripts/research_lab.py into the daily pipeline; fund alerts need a user-DB follow table.
- Research §14: the regime breakout axis had look-ahead. Fixed, and the quadrants are now nearly flat (42.6–48.5%). Re-test on the 5-year archive before Pulse leans on it.
- Data gaps that blank features locally: security_events, corporate_actions, security_risk_daily, index history (32 sessions), rs_vs_midsml400_63d, as-of mcap/taxonomy.
