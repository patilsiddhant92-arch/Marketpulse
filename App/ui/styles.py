"""MarketPulse UI styles and design tokens (PR-UI-KIT-A)."""

from __future__ import annotations

from nicegui import ui

STYLES_HTML = """
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
          /* =========================================================
             MarketPulse Light Theme — UI Standard (definitive)
             Design Direction: Financial analytics dashboard. Tone = precision, sobriety, clarity.
             Bloomberg terminal reborn in light mode — clean white surfaces, warm-neutral chrome,
             one teal accent, data that breathes.
          ========================================================= */

          :root {
            /* ── SURFACES ── */
            --mp-bg:              #f7f6f2;   /* page background — warm off-white */
            --mp-surface:         #ffffff;   /* cards, tables, panels */
            --mp-surface-2:       #f9f8f5;   /* nested card backgrounds */
            --mp-surface-offset:  #f0ede8;   /* hover rows, subtle insets */
            --mp-border:          rgba(40, 37, 29, 0.10);  /* 1px alpha border — adapts naturally */
            --mp-divider:         rgba(40, 37, 29, 0.06);  /* table row dividers */

            /* ── TEXT ── */
            --mp-text:            #28251d;   /* primary — near-black warm */
            --mp-muted:           #6b6760;   /* secondary labels, metadata */
            --mp-faint:           #b0ada8;   /* placeholders, disabled, decorative */
            --mp-inverse:         #f9f8f4;   /* text on dark/accent backgrounds */

            /* ── ACCENT (primary CTA, links, active states) ── */
            --mp-primary:         #01696f;   /* Hydra Teal */
            --mp-primary-hover:   #0c4e54;
            --mp-primary-active:  #0f3638;
            --mp-primary-bg:      #e4f0ef;   /* tinted surface for active tabs, badges */

            /* ── SEMANTIC SIGNALS (data meaning only — not decoration) ── */
            --mp-good:            #22c55e;   /* bright green for positive / up */
            --mp-good-bg:         #dcfce7;
            --mp-bad:             #ef4444;   /* bright red for negative / down */
            --mp-bad-bg:          #fee2e2;
            --mp-warn:            #f59e0b;   /* bright amber for caution */
            --mp-warn-bg:         #fef3c7;
            --mp-info:            #3b82f6;   /* bright blue for neutral */
            --mp-info-bg:         #dbeafe;
            --mp-neutral-bg:      #f3f4f6;

            /* ── ROTATION STATES (sector rotation badges) — bright */
            --mp-leading:         #22c55e;   --mp-leading-bg:   #dcfce7;
            --mp-emerging:        #3b82f6;   --mp-emerging-bg:  #dbeafe;
            --mp-improving:       #06b6d4;   --mp-improving-bg: #cffafe;
            --mp-weakening:       #f59e0b;   --mp-weakening-bg: #fef3c7;
            --mp-lagging:         #ef4444;   --mp-lagging-bg:   #fee2e2;

            /* ── SPACING (4px grid) ── */
            --mp-space-1: 0.25rem;  /* 4px */
            --mp-space-2: 0.5rem;   /* 8px */
            --mp-space-3: 0.75rem;  /* 12px */
            --mp-space-4: 1rem;     /* 16px */
            --mp-space-6: 1.5rem;   /* 24px */
            --mp-space-8: 2rem;     /* 32px */

            /* ── RADIUS ── */
            --mp-radius-sm: 4px;
            --mp-radius-md: 6px;
            --mp-radius-lg: 10px;
            --mp-radius-full: 9999px;

            /* ── SHADOWS ── */
            --mp-shadow-sm: 0 1px 2px rgba(40,37,29,0.06);
            --mp-shadow-md: 0 4px 12px rgba(40,37,29,0.08);

            /* ── TYPOGRAPHY ── */
            --mp-font: 'Inter', 'DM Sans', system-ui, sans-serif;
            --mp-font-mono: 'JetBrains Mono', 'Fira Code', monospace;

            /* ── TYPE SCALE (web app — capped at 20px) — dense dashboard */
            --mp-text-xs:   12px;   /* badges, timestamps, faint metadata */
            --mp-text-sm:   13px;   /* table cells, buttons, nav items */
            --mp-text-base: 14px;   /* default body — dense dashboard standard */
            --mp-text-lg:   16px;   /* section headings */
            --mp-text-xl:   20px;   /* page title only — 1 per page */

            /* ── TRANSITIONS ── */
            --mp-transition: 160ms cubic-bezier(0.16, 1, 0.3, 1);
          }

          body {
            background: var(--mp-bg);
            color: var(--mp-text);
            font-family: var(--mp-font);
            font-size: var(--mp-text-base);
          }

          /* Titles & emphasis */
          .mp-page-title, .mp-section-title, .mp-card-value, .mp-pos, .mp-neg, .mp-symbol {
            font-weight: 700;
          }
          .mp-page-title { font-size: var(--mp-text-xl); font-weight: 800; color: var(--mp-text); letter-spacing: -0.3px; margin-bottom: 2px; }
          .mp-page-subtitle { color: var(--mp-muted); margin-bottom: 6px; font-size: var(--mp-text-xs); }
          .mp-section-title { font-size: var(--mp-text-lg); font-weight: 700; color: var(--mp-text); letter-spacing: 0px; margin: 4px 0 2px; }

          .mp-header {
            background: var(--mp-surface);
            color: var(--mp-text);
            border-bottom: 1px solid var(--mp-border);
            box-shadow: var(--mp-shadow-sm);
            height: 48px;
            padding: 0 20px;
            font-size: var(--mp-text-base);
            position: sticky;
            top: 0;
            z-index: 3000;
          }

          /* Freeze top chrome: header + tab row */
          .mp-sticky-nav {
            position: sticky;
            top: 48px;
            z-index: 2990;
            background: var(--mp-surface);
            border-bottom: 1px solid var(--mp-border);
            box-shadow: 0 1px 0 rgba(40,37,29,0.04);
          }
          .mp-tabs {
            background: var(--mp-surface) !important;
            color: var(--mp-text) !important;
            min-height: 40px;
          }
          .mp-tabs .q-tab {
            text-transform: none !important;
            font-weight: 600 !important;
            font-size: 13px !important;
            min-height: 40px !important;
            padding: 0 16px !important;
          }
          .mp-tabs .q-tab--active {
            color: var(--mp-primary) !important;
          }
          .mp-panels {
            min-height: calc(100vh - 100px);
          }
          .mp-mono-list {
            font-family: var(--mp-font-mono);
            word-break: break-all;
            line-height: 1.45;
            color: var(--mp-text);
          }
          .mp-rank-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border: 1px solid var(--mp-border);
            border-radius: var(--mp-radius-full);
            background: var(--mp-surface);
            font-size: 12px;
          }
          .mp-rank-num {
            font-weight: 700;
            color: var(--mp-primary);
            font-variant-numeric: tabular-nums;
          }

          .mp-rule {
            color: var(--mp-muted);
            background: var(--mp-surface-offset);
            border: 1px solid var(--mp-border);
            padding: 4px 6px;
            border-radius: var(--mp-radius-sm);
            margin: 2px 0;
            font-size: var(--mp-text-xs);
            font-weight: 500;
          }

          /* Cards / Tiles */
          .mp-card, .q-card {
            background: var(--mp-surface);
            border: 1px solid var(--mp-border);
            border-radius: var(--mp-radius-lg);
            box-shadow: var(--mp-shadow-sm);
            padding: 16px;
            transition: box-shadow var(--mp-transition);
          }
          .mp-card:hover, .q-card:hover {
            box-shadow: var(--mp-shadow-md);
          }
          .mp-card-label {
            color: var(--mp-muted);
            font-size: var(--mp-text-xs);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
          }
          .mp-card-value {
            font-size: var(--mp-text-xl);
            font-weight: 700;
            color: var(--mp-text);
            font-variant-numeric: tabular-nums;
          }
          .mp-card-sub { color: var(--mp-muted); font-size: var(--mp-text-xs); }

          /* Badges */
          .mp-badge {
            display: inline-flex;
            align-items: center;
            padding: 1px 7px;
            border-radius: var(--mp-radius-full);
            font-size: var(--mp-text-xs);
            font-weight: 600;
            letter-spacing: 0.01em;
          }
          .mp-good    { background: var(--mp-good-bg);    color: var(--mp-good); }
          .mp-bad     { background: var(--mp-bad-bg);     color: var(--mp-bad); }
          .mp-warn    { background: var(--mp-warn-bg);    color: var(--mp-warn); }
          .mp-info    { background: var(--mp-info-bg);    color: var(--mp-info); }
          .mp-neutral { background: var(--mp-neutral-bg); color: var(--mp-muted); }

          /* Rotation state badges */
          .mp-state-leading   { background: var(--mp-leading-bg);   color: var(--mp-leading); }
          .mp-state-emerging  { background: var(--mp-emerging-bg);  color: var(--mp-emerging); }
          .mp-state-improving { background: var(--mp-improving-bg); color: var(--mp-improving); }
          .mp-state-weakening { background: var(--mp-weakening-bg); color: var(--mp-weakening); }
          .mp-state-lagging   { background: var(--mp-lagging-bg);   color: var(--mp-lagging); }
          .mp-state-neutral   { background: var(--mp-neutral-bg);   color: var(--mp-muted); }

          /* Hide leftover multi-select chip chrome if any page still emits it */
          .q-select__dropdown-icon + .q-chip,
          .mp-toolbar .q-chip { max-width: 9rem; }

          /* Tables — dense terminal style + sticky header (scroll parent = .mp-table-scroll) */
          .mp-table-scroll {
            width: 100%;
            max-height: min(70vh, 720px);
            overflow: auto;
            border: 1px solid var(--mp-border);
            border-radius: var(--mp-radius-sm);
            background: var(--mp-surface);
            -webkit-overflow-scrolling: touch;
          }
          .mp-table-scroll .q-table__middle {
            max-height: none !important;
            overflow: visible !important;
          }
          .mp-table, .q-table, .q-table__container {
            background: var(--mp-surface);
            color: var(--mp-text);
            border: none;
            border-radius: 0;
            font-size: 12.5px;
          }
          .mp-table .q-table, .q-table {
            table-layout: auto !important;
            width: max-content;
            min-width: 100%;
          }
          .mp-table-compact .q-table {
            table-layout: fixed !important;
            width: max-content !important;
            min-width: 0 !important;
          }
          .mp-table-compact .q-table th,
          .mp-table-compact .q-table td {
            box-sizing: border-box;
          }
          .mp-table thead tr th,
          .mp-table th.mp-th,
          .mp-table-scroll thead th {
            font-weight: 700 !important;
            background: #eef1ef !important;
            color: var(--mp-text) !important;
            text-transform: uppercase;
            font-size: 11px !important;
            letter-spacing: 0.03em;
            padding: 10px 10px !important;
            border-bottom: 1px solid var(--mp-border);
            overflow: visible !important;
            text-overflow: clip !important;
            white-space: normal !important;
            line-height: 1.25 !important;
            position: sticky !important;
            top: 0 !important;
            z-index: 20 !important;
            box-shadow: 0 1px 0 var(--mp-border);
          }
          .mp-table td, .mp-table .q-td, .q-table td, .q-table .q-td {
            color: var(--mp-text);
            padding: 6px 10px !important;
            border-bottom: 1px solid var(--mp-divider);
            font-weight: 500;
            font-variant-numeric: tabular-nums;
            line-height: 1.35;
            overflow: visible;
            text-overflow: clip;
          }
          .mp-table td.mp-wrap-col,
          .mp-table .q-td.mp-wrap-col {
            white-space: normal !important;
            word-break: break-word;
            max-width: 360px;
          }
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }
          .mp-table tbody tr:nth-child(even) { background: var(--mp-surface-offset); }
          .mp-table tbody tr:hover { background: var(--mp-surface-2); }

          /* covered by 3-tier weight + global alignment rules above */

          /* Symbol links */
          .mp-symbol {
            color: var(--mp-primary);
            font-weight: 600;
            text-decoration: none;
          }
          .mp-symbol:hover { text-decoration: underline; color: var(--mp-primary-hover); }

          /* Buttons */
          .mp-primary {
            background: var(--mp-primary);
            color: var(--mp-inverse);
            border-radius: var(--mp-radius-md);
            padding: 6px 14px;
            font-size: var(--mp-text-sm);
            font-weight: 500;
            border: none;
            transition: background var(--mp-transition);
          }
          .mp-primary:hover { background: var(--mp-primary-hover); }

          .mp-button {
            background: transparent;
            color: var(--mp-primary);
            border: 1px solid var(--mp-primary);
            border-radius: var(--mp-radius-md);
            padding: 5px 12px;
            font-size: var(--mp-text-sm);
            font-weight: 500;
            transition: background var(--mp-transition);
          }
          .mp-button:hover { background: var(--mp-primary-bg); }

          /* Compact KPI in toolbars */
          .mp-kpi-compact {
            display: inline-flex;
            flex-direction: column;
            padding: 4px 10px;
            border-left: 2px solid var(--mp-border);
          }
          .mp-kpi-compact .label {
            font-size: var(--mp-text-xs);
            color: var(--mp-muted);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
          }
          .mp-kpi-compact .value {
            font-size: 15px;
            color: var(--mp-text);
            font-weight: 700;
            font-variant-numeric: tabular-nums;
          }

          /* Toolbar */
          .mp-toolbar {
            background: var(--mp-surface-2);
            border: 1px solid var(--mp-border);
            border-radius: var(--mp-radius-lg);
            padding: 10px 16px;
          }

          /* Chips / badges base */
          .mp-chip {
            display: inline-flex;
            align-items: center;
            padding: 1px 6px;
            border-radius: var(--mp-radius-full);
            font-size: var(--mp-text-xs);
            font-weight: 600;
            background: var(--mp-surface-offset);
            color: var(--mp-muted);
            border: 1px solid var(--mp-border);
          }

          /* Heat bars */
          .mp-heat {
            position: relative;
            min-width: 70px;
            height: 18px;
            border-radius: 3px;
            overflow: hidden;
            background: var(--mp-surface-offset);
            border: 1px solid var(--mp-border);
          }
          .mp-heat-fill {
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            background: linear-gradient(90deg, #f59e0b, #22c55e);
          }
          /* old heat span rule kept for compatibility but prefer .mp-heat-value */

          /* Mini badges */
          .mp-mini-badge {
            margin-left: 3px;
            padding: 0 3px;
            border-radius: 3px;
            font-size: 8px;
            font-weight: 700;
            vertical-align: middle;
          }
          .mp-sector-badge { background: #dbeafe; color: #1e40af; }
          .mp-industry-badge { background: #ccfbf1; color: #0f766e; }
          .mp-deal-badge { background: #fef3c7; color: #b45309; }

          /* Charts */
          .mp-chart {
            background: var(--mp-surface);
            border: 1px solid var(--mp-border);
            border-radius: var(--mp-radius-md);
            padding: 4px;
          }

          /* Expansion / tree nesting with visual hierarchy */
          .mp-expansion { background: var(--mp-surface); border: 1px solid var(--mp-border); border-radius: var(--mp-radius-md); margin: 3px 0; }
          .mp-nested { margin-left: 16px; background: var(--mp-surface-2); border-left: 3px solid var(--mp-primary); }
          .mp-nested-2 { margin-left: 32px; background: var(--mp-surface-offset); }
          .mp-nested-3 { margin-left: 48px; background: var(--mp-bg); color: var(--mp-muted); }

          /* Tab nav */
          .q-tab { color: var(--mp-muted); font-size: var(--mp-text-sm); font-weight: 500; }
          .q-tab--active { color: var(--mp-primary); border-bottom: 2px solid var(--mp-primary); }

          /* Quasar light overrides for consistency */
          .q-tab-panel { background: var(--mp-bg); padding: 16px; }
          .q-field__label { color: var(--mp-muted); }
          .q-field__native, .q-field__control { color: var(--mp-text); background: var(--mp-surface); border-color: var(--mp-border); }
          .q-checkbox__inner { border-color: var(--mp-border); }
          .q-table th { background: var(--mp-surface-offset); color: var(--mp-text); font-weight: 700; }

          /* Thin custom scrollbar (modern, less intrusive than default native scrollbar) */
          ::-webkit-scrollbar { width: 6px; height: 6px; }
          ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
          ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

          /* =========================================================
             PROFESSIONAL TABLE ALIGNMENT (per industry standards from Bloomberg, TradingView, TOS etc.)
             - Text / identifiers / categories (SYMBOL, SECTOR, INDUSTRY, BROAD INDUSTRY, long symbol lists): LEFT
             - Numeric / quantitative (prices, %, mcap, turnover, vol, shock, etc.): RIGHT + tabular-nums for digit alignment
             - Headers: centered for clean look (common practice)
             - Avoid center on data cells — causes the "ugly ragged" look you pointed out.
             Rules are placed LAST with high specificity + !important to defeat Quasar defaults and any prior global center forces.
          ========================================================= */

          /* Base body default left for text; headers will be overridden per type below for consistency */
          .mp-table td, .mp-table .q-td,
          .q-table td, .q-table .q-td {
            text-align: left !important;
          }

          /* Headers follow the column data alignment for professional look (user feedback: "Shouldnt the header too follow the same?") */
          /* Numeric headers: right (matches their data columns) */
          .mp-table th.numeric, .q-table th.numeric {
            text-align: right !important;
          }
          /* Text / symbol headers: left (matches their data columns) */
          .mp-table th.text-col, .mp-table th.symbol-col,
          .q-table th.text-col, .q-table th.symbol-col {
            text-align: left !important;
          }

          /* Numeric columns: RIGHT + tabular numbers (standard for scannability in trading UIs) */
          .numeric,
          .mp-table td.numeric, .mp-table .q-td.numeric,
          .q-table td.numeric, .q-table .q-td.numeric {
            text-align: right !important;
            font-variant-numeric: tabular-nums;
            font-family: var(--mp-font-mono);
          }

          /* Explicit text columns (including symbol): LEFT (for labels and long lists like SYMBOLS / industries) */
          .text-col,
          .symbol-col,
          .symbols-col,
          .mp-table td.text-col, .mp-table .q-td.text-col,
          .q-table td.text-col, .q-table .q-td.text-col,
          .mp-table td.symbol-col, .mp-table .q-td.symbol-col,
          .q-table td.symbol-col, .q-table .q-td.symbol-col,
          .mp-table td.symbols-col, .mp-table .q-td.symbols-col,
          .q-table td.symbols-col, .q-table .q-td.symbols-col {
            text-align: left !important;
          }
          .symbols-col, .mp-table td.symbols-col, .q-table td.symbols-col {
            white-space: normal !important;
            word-break: break-word !important;
            font-family: var(--mp-font-mono);
            font-size: 11px !important;
            line-height: 1.35;
            max-width: 280px;
          }

          /* Momentum top sector / industry leadership chips */
          .mp-leader-chip {
            min-width: 160px;
            max-width: 240px;
            padding: 8px 10px;
            border-radius: var(--mp-radius-md);
            background: var(--mp-primary-bg);
            border: 1px solid var(--mp-primary);
            box-shadow: var(--mp-shadow-sm);
          }
          .mp-leader-chip-ind {
            background: var(--mp-info-bg);
            border-color: var(--mp-info);
          }
          .mp-leader-kicker {
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.06em;
            color: var(--mp-muted);
          }
          .mp-leader-name {
            font-size: 13px;
            font-weight: 800;
            color: var(--mp-text);
            line-height: 1.25;
            word-break: break-word;
          }
          .mp-leader-meta {
            font-size: 11px;
            color: var(--mp-muted);
            margin-bottom: 4px;
          }

          /* 3-tier weight system for scannability */
          .mp-table .symbol-col, .q-table .symbol-col {
            font-weight: 700 !important;
          }
          .mp-table .numeric, .q-table .numeric {
            font-weight: 600 !important;
          }
          .mp-table .text-col, .q-table .text-col {
            font-weight: 500 !important;
            color: var(--mp-muted);
          }

          /* Enhanced heat/progress bars: number beside bar (no overflow), consistent, high contrast */
          .mp-heat-container {
            display: flex;
            align-items: center;
            gap: 4px;
            min-width: 110px;
          }
          .mp-heat {
            flex: 0 0 70px;
            height: 16px;
            border-radius: 3px;
            overflow: hidden;
            background: var(--mp-surface-offset);
            border: 1px solid var(--mp-border);
          }
          .mp-heat-fill {
            height: 100%;
            background: linear-gradient(90deg, #f59e0b, #22c55e);
          }
          .mp-heat-value {
            font-size: 10px;
            min-width: 28px;
            text-align: right;
            font-weight: 500;
            color: var(--mp-text);
          }

          /* Subtle zebra + hover for scannability (standard in light finance UIs) */
          .mp-table tbody tr:nth-child(even),
          .q-table tbody tr:nth-child(even) {
            background: var(--mp-surface-offset) !important;
          }
          .mp-table tbody tr:hover,
          .q-table tbody tr:hover {
            background: var(--mp-surface-2) !important;
          }

          /* Expand mp-badge usage for all tones/states (pervasive coloring) */
          .mp-badge, .mp-chip {
            font-weight: 600;
          }
          /* Ensure rotation states use exact colors from standard */
          .mp-state-leading { background: var(--mp-leading-bg) !important; color: var(--mp-leading) !important; }
          .mp-state-emerging { background: var(--mp-emerging-bg) !important; color: var(--mp-emerging) !important; }
          .mp-state-improving { background: var(--mp-improving-bg) !important; color: var(--mp-improving) !important; }
          .mp-state-weakening { background: var(--mp-weakening-bg) !important; color: var(--mp-weakening) !important; }
          .mp-state-lagging { background: var(--mp-lagging-bg) !important; color: var(--mp-lagging) !important; }

          /* Consistent green/red for all applicable (prices, %, changes) - high contrast */
          .mp-pos, .positive { color: var(--mp-good) !important; font-weight: 600 !important; }
          .mp-neg, .negative { color: var(--mp-bad) !important; font-weight: 600 !important; }
        </style>
        """


def add_styles() -> None:
    """Inject fonts + MarketPulse CSS into the document head."""
    ui.add_head_html(STYLES_HTML)


# Extra rules injected for premium Deal Flow Desk (PR-DEALS)
DEALS_DESK_CSS = """
<style>
  .mp-deal-card {
    border: 1px solid var(--mp-border);
    border-radius: var(--mp-radius-md);
    background: var(--mp-surface);
    padding: 12px 14px;
    min-width: 200px;
    max-width: 280px;
    box-shadow: var(--mp-shadow-sm);
  }
  .mp-deal-card .sym {
    font-weight: 800;
    font-size: 15px;
    letter-spacing: -0.2px;
  }
  .mp-deal-card .meta {
    color: var(--mp-muted);
    font-size: 12px;
  }
  .mp-chip-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .mp-symbol-chip {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: var(--mp-radius-full);
    background: var(--mp-primary-bg);
    color: var(--mp-primary);
    font-size: 12px;
    font-weight: 600;
    font-family: var(--mp-font-mono);
  }
  .mp-desk-action {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
  }
  .mp-flow-spark {
    height: 140px;
    width: 100%;
  }
</style>
"""


def add_deals_desk_styles() -> None:
    ui.add_head_html(DEALS_DESK_CSS)
