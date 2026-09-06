# MarketPulse Premium UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved Institutional Midnight visual system across MarketPulse's active NiceGUI surfaces while preserving the existing market data, scoring, storage, and interaction behavior.

**Architecture:** Consolidate the visual contract in `App/ui/styles.py`, make `ColumnSpec` the single source of truth for table geometry, and let shared shell/widget helpers provide page headers, status states, tiles, and themed charts. Migrate the application shell, Desk, research surfaces, Portfolio, Health, and Stock 360 to those shared contracts in small slices so legacy page code remains functional.

**Tech Stack:** Python, NiceGUI/Quasar, pandas, DuckDB read-only market queries, ECharts, pytest, and the existing local browser companion for visual inspection.

**Spec:** `docs/superpowers/specs/2026-08-31-marketpulse-premium-ui-design.md`

## Global Constraints

- Keep the existing NiceGUI, Quasar, DuckDB, EOD workflow, page routing, and read-only market database boundaries.
- Do not change candidate scoring, signal semantics, database schemas, market queries, or user-data write behavior.
- Use the Institutional Midnight palette: graphite/navy surfaces, warm gold hierarchy, and green/red/amber/blue/cyan semantic states.
- Use IBM Plex Sans for interface text and IBM Plex Mono with tabular figures for prices, percentages, scores, ranks, dates, and aligned numeric evidence.
- Keep page gutters at 24px desktop, 16px tablet, and 12px phone; use the 4px spacing grid and 8–12px panel radii.
- Standard tables use fixed layout inside `.mp-table-scroll`; body-level horizontal overflow is prohibited.
- State meaning must be present in text as well as color; empty, stale, missing, and non-actionable data remain explicit.
- Preserve existing user edits and unrelated dirty files in the worktree.

---

### Task 1: Lock the Institutional Midnight theme contract

**Files:**
- Modify: `App/ui/styles.py`
- Create: `tests/test_ui_theme_contract.py`
- Test: `tests/test_table_spec.py`

**Interfaces:**
- Produces the semantic CSS tokens consumed by every page: `--mp-bg`, `--mp-surface`, `--mp-surface-raised`, `--mp-surface-offset`, `--mp-border`, `--mp-text`, `--mp-muted`, `--mp-faint`, `--mp-primary`, `--mp-primary-bg`, `--mp-good`, `--mp-good-bg`, `--mp-bad`, `--mp-bad-bg`, `--mp-warn`, `--mp-warn-bg`, `--mp-info`, `--mp-info-bg`, and `--mp-cyan`.
- Produces stable shared classes: `.mp-app-shell`, `.mp-page-canvas`, `.mp-page-header`, `.mp-section`, `.mp-panel`, `.mp-regime-strip`, `.mp-kpi-tile`, `.mp-table-scroll`, `.mp-table`, `.mp-status-banner`, `.mp-control-bar`, and `.mp-stock-dialog`.

- [ ] **Step 1: Write the failing theme contract tests**

```python
from App.ui.styles import STYLES_HTML


def test_institutional_midnight_tokens_are_centralized() -> None:
    expected = {
        "--mp-bg: #080c12",
        "--mp-surface: #101721",
        "--mp-surface-raised: #151f2b",
        "--mp-primary: #d8ac3d",
        "--mp-good: #45d483",
        "--mp-bad: #f27c84",
        "--mp-warn: #f0be58",
        "--mp-cyan: #5ad3d0",
    }
    css = STYLES_HTML.lower().replace(" ", "")
    assert all(token.replace(" ", "") in css for token in expected)


def test_shared_surface_contract_has_responsive_canvas_and_no_gradient() -> None:
    css = STYLES_HTML.lower()
    assert ".mp-app-shell" in css
    assert ".mp-page-canvas" in css
    assert ".mp-panel" in css
    assert "overflow-x: hidden" in css
    assert "linear-gradient" not in css


def test_standard_table_contract_is_fixed_and_fluid() -> None:
    css = STYLES_HTML.lower()
    assert "table-layout: fixed !important" in css
    assert "width: 100% !important" in css
    assert "width: max-content !important" not in css
```

- [ ] **Step 2: Run the new tests to verify the expected RED failure**

Run: `py -m pytest tests/test_ui_theme_contract.py -q`

Expected: FAIL because the existing stylesheet still exposes the earlier dark-terminal token values and unrestricted `max-content` table rules.

- [ ] **Step 3: Replace the conflicting token block and last-mile CSS rules**

Keep the existing class names for compatibility, but make the selected palette authoritative. Add the new app-root/canvas/panel/status/control rules near the shared shell rules. Change standard table rules to the following contract:

```css
.mp-table-scroll {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  overflow-y: auto;
  border: 1px solid var(--mp-border);
  border-radius: var(--mp-radius-md);
}

.mp-table-shell .q-table,
.mp-table .q-table,
.q-table {
  table-layout: fixed !important;
  width: 100% !important;
  min-width: 768px;
}
```

Add reduced-motion handling and scoped responsive gutters. Remove the active `width: max-content !important` and `table-layout: auto !important` declarations rather than overriding them with another page-specific exception.

- [ ] **Step 4: Run the theme and existing table tests**

Run: `py -m pytest tests/test_ui_theme_contract.py tests/test_table_spec.py -q`

Expected: PASS with no warnings or failures.

- [ ] **Step 5: Inspect the diff for unrelated visual or data changes**

Run: `git diff --check` and `git diff -- App/ui/styles.py tests/test_ui_theme_contract.py tests/test_table_spec.py`.

Expected: only theme/table CSS and contract tests are changed.

### Task 2: Activate named table geometry and alignment

**Files:**
- Modify: `App/ui/table.py`
- Modify: `App/app.py` in `table_from_df` (the shared DataFrame renderer)
- Modify: `tests/test_table_spec.py`
- Create: `tests/test_table_renderer_contract.py`

**Interfaces:**
- `ColumnSpec` gains `wrap: bool = False` and `responsive_priority: int = 1` after the existing `group` field, preserving current positional construction.
- `column_spec_for(key: str, *, compact: bool = False) -> ColumnSpec` returns a named width/alignment/wrap contract.
- `column_specs_for(keys: list[str], *, compact: bool = False) -> tuple[ColumnSpec, ...]` returns the ordered contracts used by a renderer.
- Existing `SWING_COLUMNS`, `SCREENER_COLUMNS`, and `fixed_table_css()` remain import-compatible.

- [ ] **Step 1: Write failing tests for named geometry and renderer alignment**

```python
from App.ui.table import column_specs_for


def test_named_specs_keep_text_left_numeric_right_and_rationale_wrapped() -> None:
    specs = {item.key: item for item in column_specs_for(["symbol", "industry", "day_pct", "why_now"])}
    assert specs["symbol"].width_px == 112
    assert specs["symbol"].align == "left"
    assert specs["industry"].width_px == 176
    assert specs["industry"].wrap is True
    assert specs["day_pct"].align == "right"
    assert specs["why_now"].responsive_priority == 0


def test_unknown_columns_get_a_stable_fallback_contract() -> None:
    spec = column_specs_for(["new_metric"])[0]
    assert spec.width_px == 92
    assert spec.align == "left"
    assert spec.wrap is False
```

```python
from App.app import table_from_df


def test_table_renderer_uses_named_spec_styles(monkeypatch) -> None:
    # The test captures the column definitions passed to NiceGUI's table.
    # It asserts the real renderer's output contract, not a copied width map.
    captured = {}
    monkeypatch.setattr("App.app.ui.table", lambda **kwargs: captured.update(kwargs) or _FakeTable())
    table_from_df(pd.DataFrame({"symbol": ["ABC"], "day_pct": [1.25], "industry": ["Software"]}), "Queue")
    columns = {column["name"]: column for column in captured["columns"]}
    assert columns["symbol"]["align"] == "left"
    assert "width:112px" in columns["symbol"]["style"]
    assert columns["day_pct"]["align"] == "right"
    assert "white-space:nowrap" in columns["day_pct"]["style"]
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `py -m pytest tests/test_table_spec.py tests/test_table_renderer_contract.py -q`

Expected: FAIL because the named spec functions do not yet exist and `table_from_df` still rebuilds widths from its local heuristic dictionary.

- [ ] **Step 3: Implement the canonical specs in `App/ui/table.py`**

Use the approved width bands and keep the existing swing/screener totals. Define named contracts for `symbol`, `state`, `candidate_state`, `setup_class`, `industry`, `broad_industry`, `sector`, `group_name`, `why_now`, `latest_change`, `risk_summary`, `warning_reasons`, `trigger_price`, `invalidation_price`, `distance_to_trigger_pct`, `reward_to_risk`, `rs_percentile`, `day_pct`, `week_pct`, `month_pct`, `rvol`, `market_cap_cr`, `t_o_today`, `t_o_1w`, `t_o_1m`, `event_risk`, `actions`, and the existing research fields. Return a 92px left-aligned non-wrapping fallback for unknown text columns and preserve numeric inference in the renderer.

- [ ] **Step 4: Refactor `table_from_df` to consume `column_specs_for`**

Replace the inline width branches with:

```python
spec_by_key = {
    spec.key: spec for spec in column_specs_for(display_cols, compact=compact)
}
spec = spec_by_key[col]
align = spec.align
wrap = spec.wrap
width = spec.width_px
```

Keep the current data formatting, tone slots, symbol action slot, column chooser, pagination, copy behavior, and Stock 360 event unchanged. Generate the style from the spec, applying `mp-wrap-col` only when `spec.wrap` is true. Use `headerClasses` that match the data alignment.

- [ ] **Step 5: Run the renderer, table, and startup tests**

Run: `py -m pytest tests/test_table_spec.py tests/test_table_renderer_contract.py tests/test_nicegui_startup.py -q`

Expected: PASS, with the existing 768px and 1040px contract totals unchanged.

### Task 3: Normalize shell, tiles, and chart primitives

**Files:**
- Modify: `App/ui/shell.py`
- Modify: `App/ui/widgets.py`
- Modify: `App/app.py` (`section_header`, `app_header`, `metric_card`, main content host)
- Create: `tests/test_ui_primitives.py`

**Interfaces:**
- `page_shell(title, subtitle="", *, eyebrow="")` emits `.mp-page-header` and preserves its current call signature.
- `status_banner(message, *, tone="info", action="") -> None` emits a compact `.mp-status-banner` with explicit text state.
- `section_panel(title="", *, subtitle="")` remains a NiceGUI context-compatible container for page sections.
- `chart_theme() -> dict[str, Any]` returns shared ECharts colors for background, text, grid, and stable series palette.
- `compact_kpi_row` and `deal_flow_card` retain their current arguments and interaction callbacks.

- [ ] **Step 1: Write failing primitive tests**

```python
from App.ui.widgets import chart_theme


def test_chart_theme_matches_institutional_midnight_semantics() -> None:
    theme = chart_theme()
    assert theme["text"] == "#98A7BA"
    assert theme["grid"] == "#263447"
    assert theme["series"][0] == "#D8AC3D"
    assert theme["series"][1] == "#74A9FF"
    assert theme["good"] == "#45D483"
    assert theme["bad"] == "#F27C84"
```

```python
from App.ui.styles import STYLES_HTML


def test_shared_primitives_have_compact_spacing_and_focus_rules() -> None:
    css = STYLES_HTML.lower()
    assert ".mp-status-banner" in css
    assert ".mp-kpi-tile" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
```

- [ ] **Step 2: Run the primitive tests to verify RED**

Run: `py -m pytest tests/test_ui_primitives.py -q`

Expected: FAIL because `chart_theme` and the new shell classes are not yet defined.

- [ ] **Step 3: Implement the shell primitives**

Update `page_shell` to use one header wrapper and no duplicated vertical margins. Add `status_banner` with `mp-status-banner mp-status-{tone}` classes. Add a `section_panel` context manager using `ui.element("section")` and `.mp-section mp-panel`. Keep `empty_state`, `skeleton_line`, and `filter_bar`, but move their geometry to the shared classes.

- [ ] **Step 4: Implement and consume the shared chart theme**

Add:

```python
def chart_theme() -> dict[str, Any]:
    return {
        "text": "#98A7BA",
        "grid": "#263447",
        "series": ["#D8AC3D", "#74A9FF", "#45D483", "#F27C84", "#5AD3D0", "#F0BE58"],
        "good": "#45D483",
        "bad": "#F27C84",
    }
```

Use it in `flow_spark`, `line_chart`, and `grouped_line_chart`. Keep animation disabled, add `axisPointer`, a stable tooltip text style, and preserve existing empty-history handling. Do not add decorative chart series.

- [ ] **Step 5: Normalize the global header and page host**

Wrap the current header brand/meta content with the new app-shell classes, add an accessible `aria-label` to the navigation container, make `section_header` delegate to `page_shell`, and apply `.mp-app-shell .mp-page-canvas` to the main content host. Keep the existing tab names and click routing.

- [ ] **Step 6: Run primitive and startup tests**

Run: `py -m pytest tests/test_ui_primitives.py tests/test_nicegui_startup.py tests/test_market_ui_readonly.py -q`

Expected: PASS.

### Task 4: Migrate active pages to the shared Institutional Midnight surface

**Files:**
- Modify: `App/pages/desk.py`
- Modify: `App/pages/screener.py`
- Modify: `App/pages/research.py`
- Modify: `App/pages/research/sector_board.py`
- Modify: `App/pages/research/sector_intel.py`
- Modify: `App/pages/research/deals.py`
- Modify: `App/pages/sma_template.py`
- Modify: `App/data_health_page.py`
- Modify: `App/app.py` only where a page-level wrapper is needed
- Create: `tests/test_active_page_theme_contract.py`

**Interfaces:**
- Page builders continue accepting their current database paths, callbacks, and prepared DataFrames.
- No page adds a new database query solely for presentation.
- Every active page root uses a stable page class (`mp-page-desk`, `mp-page-screener`, `mp-page-research`, `mp-page-portfolio`, `mp-page-health`) and shared panels/tables.

- [ ] **Step 1: Write failing page contract tests**

```python
from pathlib import Path


def test_active_page_modules_use_shared_page_roots() -> None:
    expected = {
        "App/pages/desk.py": "mp-page-desk",
        "App/pages/screener.py": "mp-page-screener",
        "App/pages/research.py": "mp-page-research",
        "App/data_health_page.py": "mp-page-health",
    }
    for path, marker in expected.items():
        assert marker in Path(path).read_text(encoding="utf-8")


def test_legacy_light_surface_utilities_are_scoped_or_removed() -> None:
    text = Path("App/pages/research/sector_intel.py").read_text(encoding="utf-8")
    assert "bg-gradient-to-r" not in text
    assert "shadow-md" not in text
```

- [ ] **Step 2: Run the page contract tests to verify RED**

Run: `py -m pytest tests/test_active_page_theme_contract.py -q`

Expected: FAIL because the active page roots and the final removal of the light gradient surface have not been applied.

- [ ] **Step 3: Add page roots and standardize section geometry**

Wrap each builder body in its page root. Replace repeated `mt-*`/`mb-*` spacing on primary section headings with `.mp-section` ownership. Keep all current labels, filters, callbacks, table data, expansion behavior, and empty messages. Make Desk's first regions visually ordered as page header → actionable status → regime/KPI strip → trend chart → tables, using existing data.

- [ ] **Step 4: Standardize tiles, controls, and tables**

Use `.mp-kpi-tile`/`.mp-kpi-compact` for summary metrics, `.mp-control-bar` for filter groups, `.mp-panel` for bounded chart/table sections, and `.mp-table-scroll` for table overflow. Replace page-local light utility classes in sector research with semantic shared classes while retaining the taxonomy tree and drill-down interactions.

- [ ] **Step 5: Run page contracts and read-only regression tests**

Run: `py -m pytest tests/test_active_page_theme_contract.py tests/test_desk_research_surfaces.py tests/test_sector_runtime_wiring.py tests/test_market_ui_readonly.py -q`

Expected: PASS.

### Task 5: Bring Stock 360 into the same confirmation workspace

**Files:**
- Modify: `App/ui/stock_drawer.py`
- Modify: `App/ui/t_graph.py`
- Modify: `App/ui/vcp_chart.py`
- Modify: `tests/test_stock_360_contract.py`

**Interfaces:**
- `open_stock_360_modal` keeps the same public signature and data query behavior.
- Existing tabs remain available; their visual order and content hierarchy are changed only through shared classes.
- `tradingview_url` and copy/close callbacks remain unchanged.

- [ ] **Step 1: Write failing Stock 360 visual contract tests**

```python
from pathlib import Path


def test_stock_360_uses_shared_confirmation_sections() -> None:
    text = Path("App/ui/stock_drawer.py").read_text(encoding="utf-8")
    for marker in ("mp-stock-dialog", "mp-confirmation-header", "mp-confirmation-section", "mp-risk-grid"):
        assert marker in text


def test_stock_360_does_not_use_light_text_utility_colors() -> None:
    text = Path("App/ui/stock_drawer.py").read_text(encoding="utf-8")
    assert "text-green-600" not in text
    assert "text-red-600" not in text
    assert "text-blue-600" not in text
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run: `py -m pytest tests/test_stock_360_contract.py -q`

Expected: FAIL because the drawer still uses page-local light utility colors and nested generic card geometry.

- [ ] **Step 3: Add the shared Stock 360 hierarchy**

Apply `.mp-confirmation-header`, `.mp-confirmation-section`, `.mp-risk-grid`, and `.mp-metric-tile` to the existing header, Overview, Institutional Pedigree, Risk & Setup Geometry, and Corporate Events sections. Replace light semantic utilities with `mp-good`, `mp-bad`, `mp-warn`, and `mp-info`. Keep the dialog within `95vw`, make the inner content scroll, and stack the metric grids below 700px.

- [ ] **Step 4: Verify Stock 360 and focused-v2 behavior**

Run: `py -m pytest tests/test_stock_360_contract.py tests/test_candidate_semantics.py tests/test_decision_read_model.py -q`

Expected: PASS.

### Task 6: Full verification and visual QA

**Files:**
- Modify: `docs/superpowers/specs/2026-08-31-marketpulse-premium-ui-design.md` to mark implementation status after verification
- Modify: `tests/test_table_spec.py` only if an assertion reflects the final approved contract

- [ ] **Step 1: Compile every changed UI module**

Run:

```powershell
py -m py_compile App/app.py App/ui/styles.py App/ui/table.py App/ui/shell.py App/ui/widgets.py App/ui/stock_drawer.py App/ui/t_graph.py App/ui/vcp_chart.py App/pages/desk.py App/pages/screener.py App/pages/research.py App/pages/research/sector_board.py App/pages/research/sector_intel.py App/pages/research/deals.py App/pages/sma_template.py App/data_health_page.py
```

Expected: exit code 0 and no syntax errors.

- [ ] **Step 2: Run the complete focused UI/regression suite**

Run:

```powershell
py -m pytest tests/test_ui_theme_contract.py tests/test_ui_primitives.py tests/test_table_spec.py tests/test_table_renderer_contract.py tests/test_active_page_theme_contract.py tests/test_stock_360_contract.py tests/test_nicegui_startup.py tests/test_market_ui_readonly.py tests/test_desk_research_surfaces.py tests/test_sector_runtime_wiring.py tests/test_candidate_semantics.py tests/test_decision_read_model.py -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 3: Start the application using the normal launch path**

Run the existing local app entry point without changing environment or database configuration. Confirm the page responds on loopback and capture the Desk first viewport.

- [ ] **Step 4: Inspect the required widths and surfaces**

At 1,440px, 1,024px, 768px, 600px, and 390px inspect Desk, Momentum, Template, Sectors, Deals, Portfolio, Health, and Stock 360. Verify sticky header/nav, no body-level horizontal scroll, table wrapper-only scrolling, fixed numeric alignment, long text wrapping, responsive filters, empty/stale banners, chart labels, keyboard focus, and dialog close/open behavior.

- [ ] **Step 5: Run final diff hygiene checks**

Run: `git diff --check` and `git status --short`.

Expected: no whitespace errors; only the intended UI implementation files are changed in addition to pre-existing user changes.

- [ ] **Step 6: Update the spec status and report evidence**

Only after the commands above pass, update the design spec status from implementation-not-started to implemented/verified and report the exact test command and result, the visual surfaces inspected, and any remaining non-blocking limitations.
