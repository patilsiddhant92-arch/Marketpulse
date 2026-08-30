"""MarketPulse UI styles and design tokens (PR-UI-KIT-A)."""

from __future__ import annotations

from nicegui import ui

STYLES_HTML = """
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
          /* =========================================================
             MarketPulse Champion Desk — night field + paper geometry
          ========================================================= */

          :root {
            /* ── SURFACES ── */
            --mp-bg:              #07090e;
            --mp-surface:         #12151c;
            --mp-surface-2:       #1a1d26;
            --mp-surface-offset:  #161922;
            --mp-border:          #2a261c;
            --mp-divider:         #232018;
            --mp-paper:           #f3ead8;
            --mp-paper-ink:       #12151c;

            /* ── TEXT ── */
            --mp-text:            #f3ead8;
            --mp-muted:           #c9c0ae;
            --mp-faint:           #a89f8e;
            --mp-inverse:         #07090e;

            /* ── ACCENT (gold signal, not SaaS blue) ── */
            --mp-primary:         #c9a227;
            --mp-primary-hover:   #e0bc4a;
            --mp-primary-active:  #a8861c;
            --mp-primary-bg:      #3c3214;
            --mp-action-bg:       #c9a227;
            --mp-action-hover:    #e0bc4a;
            --mp-action-text:     #07090e;

            /* ── SEMANTIC SIGNALS (data meaning only — not decoration) ── */
            --mp-good:            #3fb950;
            --mp-good-bg:         #17351f;
            --mp-bad:             #f85149;
            --mp-bad-bg:          #3b1e21;
            --mp-warn:            #d29922;
            --mp-warn-bg:         #3c2f14;
            --mp-info:            #58a6ff;
            --mp-info-bg:         #1c3450;
            --mp-neutral-bg:      #21262d;

            /* ── ROTATION STATES (dark semantic pairs, WCAG AA text) ── */
            --mp-leading:         #56d364;   --mp-leading-bg:   #132d1a;
            --mp-emerging:        #79c0ff;   --mp-emerging-bg:  #152844;
            --mp-improving:       #39c5cf;   --mp-improving-bg: #102f36;
            --mp-weakening:       #e3b341;   --mp-weakening-bg: #332807;
            --mp-lagging:         #ff7b72;   --mp-lagging-bg:   #3b1e21;

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
            --mp-font: 'IBM Plex Sans', 'Inter', system-ui, sans-serif;
            --mp-font-mono: 'IBM Plex Mono', 'JetBrains Mono', monospace;

            --mp-text-xs:   13px;
            --mp-text-sm:   14px;
            --mp-text-base: 15px;
            --mp-text-lg:   17px;
            --mp-text-xl:   22px;

            /* ── TRANSITIONS ── */
            --mp-transition: 160ms cubic-bezier(0.16, 1, 0.3, 1);
          }

          body {
            --q-primary: var(--mp-action-bg) !important;
            --q-grey-8: var(--mp-primary) !important;
            background: var(--mp-bg);
            color: var(--mp-text);
            font-family: var(--mp-font);
            font-size: var(--mp-text-base);
            overflow-x: hidden;
          }

          /* Titles & emphasis */
          .mp-page-title, .mp-section-title, .mp-card-value, .mp-pos, .mp-neg, .mp-symbol {
            font-weight: 700;
          }
          .mp-page-title { font-size: var(--mp-text-xl); font-weight: 800; color: var(--mp-text); letter-spacing: -0.3px; margin-bottom: 2px; }
          .mp-page-subtitle { color: var(--mp-muted); margin-bottom: 6px; font-size: var(--mp-text-sm); }
          .mp-section-title { font-size: var(--mp-text-lg); font-weight: 700; color: var(--mp-text); letter-spacing: 0px; margin: 4px 0 2px; }

          .mp-header {
            background: var(--mp-surface);
            color: var(--mp-text);
            border-bottom: 1px solid var(--mp-border);
            box-shadow: var(--mp-shadow-sm);
            min-height: 48px;
            height: auto;
            padding: 8px 20px;
            font-size: var(--mp-text-base);
            position: sticky;
            top: 0;
            z-index: 3000;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            flex-wrap: wrap;
          }
          .mp-header-brand, .mp-header-meta {
            display: flex;
            align-items: center;
            gap: 8px;
            min-width: 0;
          }
          .mp-header-meta { justify-content: flex-end; }
          .mp-header-meta-item { white-space: nowrap; }
          .mp-header-status {
            display: inline-flex;
            align-items: center;
            white-space: nowrap;
            padding: 2px 7px;
            border-radius: var(--mp-radius-full);
            border: 1px solid transparent;
          }
          .mp-header-status-bad { color: var(--mp-bad); background: var(--mp-bad-bg); border-color: var(--mp-bad); }
          .mp-header-status-good { color: var(--mp-good); background: var(--mp-good-bg); border-color: var(--mp-good); }
          .mp-header-status-warn { color: var(--mp-warn); background: var(--mp-warn-bg); border-color: var(--mp-warn); }
          @media (max-width: 700px) {
            .mp-header { justify-content: flex-start; gap: 4px 10px; }
            .mp-header-brand { flex: 1 1 100%; }
            .mp-header-meta { flex: 1 1 100%; justify-content: flex-start; gap: 5px; }
            .mp-header-meta-item { font-size: 13px !important; }
            .mp-header-status { font-size: 13px !important; }
          }

          /* Freeze top chrome: header + tab row */
          .mp-sticky-nav {
            position: sticky;
            top: 48px;
            z-index: 2990;
            background: var(--mp-surface);
            border-bottom: 1px solid var(--mp-border);
            box-shadow: 0 1px 0 rgba(40,37,29,0.04);
            overflow: hidden;
            width: 100% !important;
            max-width: 100vw !important;
            min-width: 0 !important;
            box-sizing: border-box;
          }
          .mp-tabs {
            background: var(--mp-surface) !important;
            color: var(--mp-text) !important;
            min-height: 40px;
            width: 100% !important;
            max-width: 100% !important;
            min-width: 0 !important;
            overflow: hidden;
          }
          .mp-tabs .q-tabs__content {
            width: 100%;
            max-width: 100%;
            min-width: 0;
            flex: 1 1 auto;
            overflow-x: auto;
            overflow-y: hidden;
            scrollbar-width: thin;
            scrollbar-color: var(--mp-border) transparent;
          }
          .mp-tabs .q-tab {
            text-transform: none !important;
            font-weight: 600 !important;
            font-size: 13px !important;
            min-height: 40px !important;
            padding: 0 16px !important;
            flex: 0 0 auto;
          }
          .mp-tabs .q-tab--active {
            color: var(--mp-primary) !important;
          }
          @media (max-width: 700px) {
            .mp-header {
              position: relative;
              height: auto;
              min-height: 48px;
              padding: 8px 12px;
              flex-wrap: wrap;
              gap: 4px 8px;
            }
            .mp-sticky-nav { top: 0; }
            .mp-tabs .q-tab { padding: 0 12px !important; }
            .q-page, .q-page-container, .nicegui-content { min-width: 0 !important; max-width: 100vw !important; }
            .q-page-container { padding-top: 0 !important; }
          }
          .mp-panels {
            min-height: calc(100vh - 100px);
            min-width: 0;
            max-width: 100%;
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
            width: max-content !important;
            min-width: 0 !important;
          }
          .mp-table-compact .q-table {
            table-layout: auto !important;
            width: max-content !important;
            min-width: 0 !important;
          }
          .mp-up { color: var(--mp-good) !important; font-weight: 700 !important; }
          .mp-down { color: var(--mp-bad) !important; font-weight: 700 !important; }
          .mp-table-compact .q-table th,
          .mp-table-compact .q-table td {
            box-sizing: border-box;
          }
          .mp-table thead tr th,
          .mp-table th.mp-th,
          .mp-table-scroll thead th {
            font-weight: 700 !important;
            background: var(--mp-surface-2) !important;
            color: var(--mp-text) !important;
            text-transform: uppercase;
            font-size: 13px !important;
            letter-spacing: 0.03em;
            padding: 6px 8px !important;
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
            font-size: 14px !important;
            padding: 6px 8px !important;
            border-bottom: 1px solid var(--mp-divider);
            font-weight: 500;
            font-variant-numeric: tabular-nums;
            line-height: 1.35;
            overflow: visible;
            text-overflow: unset;
          }
          .mp-table td.mp-wrap-col,
          .mp-table .q-td.mp-wrap-col {
            white-space: normal !important;
            word-break: break-word;
            max-width: 360px;
            overflow: hidden;
            text-overflow: ellipsis;
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
            background: var(--mp-action-bg) !important;
            color: var(--mp-action-text) !important;
            border-radius: var(--mp-radius-md);
            padding: 6px 14px;
            font-size: var(--mp-text-sm);
            font-weight: 500;
            border: none;
            transition: background var(--mp-transition);
          }
          .mp-primary:hover { background: var(--mp-action-hover) !important; }
          .mp-primary .q-icon, .mp-primary .q-btn__content { color: var(--mp-action-text) !important; }
          .q-btn.bg-primary {
            background: var(--mp-action-bg) !important;
            color: var(--mp-action-text) !important;
          }
          .q-btn.bg-primary:hover { background: var(--mp-action-hover) !important; }
          .q-btn.bg-primary .q-icon,
          .q-btn.bg-primary .q-btn__content { color: var(--mp-action-text) !important; }

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
            background: rgba(63, 185, 80, 0.30);
          }
          /* old heat span rule kept for compatibility but prefer .mp-heat-value */

          /* Mini badges */
          .mp-mini-badge {
            margin-left: 4px;
            padding: 1px 5px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 700;
            vertical-align: middle;
            white-space: nowrap;
          }
          .mp-sector-badge { background: #17351f; color: #56d364; }
          .mp-industry-badge { background: #102f36; color: #39c5cf; }
          .mp-improving-badge { background: #1c3450; color: #79c0ff; }
          .mp-deal-badge { background: #3c2f14; color: #e3b341; }

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

          /* Quasar dark overrides. Menus/dialogs are portaled under body, so
             these rules must be global rather than scoped to a page. */
          .q-tab-panel { background: var(--mp-bg); padding: 16px; }
          .q-field__label { color: var(--mp-muted) !important; }
          .q-field__native,
          .q-field__input,
          .q-field__prefix,
          .q-field__suffix,
          .q-field__append,
          .q-field__prepend,
          .q-field__marginal { color: var(--mp-text) !important; }
          .q-field__control { color: var(--mp-text); background: var(--mp-surface); border-color: var(--mp-border); }
          .q-field--outlined .q-field__control::before { border-color: var(--mp-border) !important; }
          .q-field--outlined:hover .q-field__control::before { border-color: var(--mp-muted) !important; }
          .q-field--outlined.q-field--focused .q-field__control::after { border-color: var(--mp-primary) !important; }
          .q-menu {
            background: var(--mp-surface-2) !important;
            color: var(--mp-text) !important;
            border: 1px solid var(--mp-border) !important;
            border-radius: var(--mp-radius-md) !important;
            box-shadow: 0 14px 32px rgba(0, 0, 0, 0.48) !important;
          }
          .q-menu .q-item { color: var(--mp-text) !important; min-height: 36px; }
          .q-menu .q-item:hover,
          .q-menu .q-item--active,
          .q-menu .q-manual-focusable--focused {
            color: var(--mp-primary) !important;
            background: var(--mp-primary-bg) !important;
          }
          .q-menu .q-item.q-item--active.text-grey-8,
          .q-menu .q-item.q-manual-focusable--focused.text-grey-8 {
            color: var(--mp-primary) !important;
          }
          body .q-menu .q-item.q-item--active.text-grey-8 .q-item__section,
          body .q-menu .q-item.q-item--active.text-grey-8 .q-item__label,
          body .q-menu .q-item.q-item--active.text-grey-8 span {
            color: var(--mp-primary) !important;
          }
          .q-dialog__backdrop { background: rgba(3, 7, 12, 0.72) !important; }
          .q-dialog__inner > .q-card,
          .q-dialog__inner .nicegui-card {
            background: var(--mp-surface) !important;
            color: var(--mp-text) !important;
            border-color: var(--mp-border) !important;
          }
          .q-table__bottom .q-btn:not(.disabled) { color: var(--mp-muted) !important; }
          .q-checkbox__inner { border-color: var(--mp-border); }
          .q-table th { background: var(--mp-surface-offset); color: var(--mp-text); font-weight: 700; }

          /* Thin custom scrollbar (modern, less intrusive than default native scrollbar) */
          ::-webkit-scrollbar { width: 6px; height: 6px; }
          ::-webkit-scrollbar-thumb { background: #3a4555; border-radius: 3px; }
          ::-webkit-scrollbar-thumb:hover { background: #526176; }

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
            max-width: 5.2rem !important;
            width: auto !important;
            white-space: nowrap !important;
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
            font-size: 13px !important;
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
            font-size: 12px;
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
            font-size: 13px;
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
            color: var(--mp-text);
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
            background: rgba(63, 185, 80, 0.30);
          }
          .mp-heat-value {
            font-size: 13px;
            min-width: 32px;
            text-align: right;
            font-weight: 600;
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

          /* Sector Leadership Desk uses the same dark terminal tokens as every
             other active page.  The page still emits a few legacy Tailwind
             utility classes, so scope the compatibility overrides here rather
             than changing the shared utility contract. */
          .mp-sector-page .bg-white { background-color: var(--mp-surface) !important; }
          .mp-sector-page .bg-slate-50 { background-color: var(--mp-surface-2) !important; }
          .mp-sector-page .bg-slate-100 { background-color: var(--mp-neutral-bg) !important; }
          .mp-sector-page .bg-teal-50, .mp-sector-page .bg-teal-50\\/40 { background-color: var(--mp-primary-bg) !important; }
          .mp-sector-page .bg-emerald-50 { background-color: var(--mp-good-bg) !important; }
          .mp-sector-page .bg-blue-50 { background-color: var(--mp-info-bg) !important; }
          .mp-sector-page .bg-amber-50 { background-color: var(--mp-warn-bg) !important; }
          .mp-sector-page .bg-emerald-100 { background-color: var(--mp-good-bg) !important; }
          .mp-sector-page .bg-blue-100 { background-color: var(--mp-info-bg) !important; }
          .mp-sector-page .bg-amber-100 { background-color: var(--mp-warn-bg) !important; }
          .mp-sector-page .border-slate-100,
          .mp-sector-page .border-slate-200,
          .mp-sector-page .border-slate-300 { border-color: var(--mp-border) !important; }
          .mp-sector-page .text-slate-800,
          .mp-sector-page .text-slate-700 { color: var(--mp-text) !important; }
          .mp-sector-page .text-slate-600,
          .mp-sector-page .text-slate-500,
          .mp-sector-page .text-slate-400 { color: var(--mp-muted) !important; }
          .mp-sector-page .text-emerald-800,
          .mp-sector-page .text-emerald-700 { color: var(--mp-good) !important; }
          .mp-sector-page .text-blue-800,
          .mp-sector-page .text-blue-700 { color: var(--mp-info) !important; }
          .mp-sector-page .text-amber-800,
          .mp-sector-page .text-amber-700 { color: var(--mp-warn) !important; }
          .mp-sector-page .text-rose-700 { color: var(--mp-bad) !important; }
          .mp-sector-page [class~="text-[#01696f]"] { color: var(--mp-primary) !important; }
          .mp-sector-page .border-teal-200,
          .mp-sector-page [class~="border-teal-600/30"] { border-color: var(--mp-primary) !important; }
          .mp-sector-page .mp-sector-toolbar,
          .mp-sector-page .mp-sector-summary,
          .mp-sector-page .mp-sector-focus-card { background-color: var(--mp-surface) !important; }
          .mp-sector-page .mp-sector-selected { background-color: var(--mp-primary-bg) !important; }
          .mp-sector-page .mp-sector-unselected { background-color: var(--mp-surface) !important; }
          .mp-sector-page .mp-sector-table-scroll { margin-top: 4px; }
          .mp-sector-page .mp-sector-table .q-table { min-width: 960px; }
          .mp-sector-page .mp-sector-table td { white-space: nowrap !important; }
          .mp-sector-page .mp-sector-table td:first-child { font-weight: 700; }

          /* Sector Intel tree workspace */
          .mp-sector-search { width: min(360px, 100%); }
          .mp-sector-toolbar-help { flex: 1 1 240px; margin: 0; }
          .mp-sector-filter-strip {
            padding: 10px 12px;
            background: var(--mp-surface);
            border: 1px solid var(--mp-border);
            border-radius: var(--mp-radius-lg);
          }
          .mp-filter-label {
            color: var(--mp-muted);
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
          }
          .mp-filter-chip {
            min-height: 30px;
            padding: 3px 10px;
            color: var(--mp-muted) !important;
            background: var(--mp-surface-offset) !important;
            border: 1px solid var(--mp-border) !important;
            border-radius: var(--mp-radius-full) !important;
            font-size: var(--mp-text-xs);
            font-weight: 700;
          }
          .mp-filter-chip:hover {
            color: var(--mp-text) !important;
            border-color: var(--mp-muted) !important;
            background: var(--mp-surface-2) !important;
          }
          .mp-filter-chip-active {
            color: var(--mp-primary) !important;
            background: var(--mp-primary-bg) !important;
            border-color: var(--mp-primary) !important;
          }
          .mp-sector-workspace {
            display: grid;
            grid-template-columns: minmax(320px, 0.42fr) minmax(0, 1fr);
            gap: 12px;
            align-items: start;
            min-width: 0;
          }
          .mp-taxonomy-panel,
          .mp-sector-selection-card {
            padding: 14px !important;
            background: var(--mp-surface) !important;
            border: 1px solid var(--mp-border) !important;
          }
          .mp-taxonomy-panel { min-width: 0; }
          .mp-taxonomy-tree-host {
            max-height: min(68vh, 720px);
            overflow: auto;
            padding: 4px 2px 8px;
            border-top: 1px solid var(--mp-divider);
          }
          .mp-taxonomy-tree {
            color: var(--mp-text);
            font-size: var(--mp-text-xs);
            min-width: 0;
          }
          .mp-taxonomy-tree .q-tree__node-header {
            min-height: 31px;
            padding: 2px 6px;
            border-radius: var(--mp-radius-sm);
            color: var(--mp-text);
            transition: background var(--mp-transition), color var(--mp-transition);
          }
          .mp-taxonomy-tree .q-tree__node-header:hover {
            background: var(--mp-surface-2);
          }
          .mp-taxonomy-tree .q-tree__node--selected > .q-tree__node-header {
            color: var(--mp-primary) !important;
            background: var(--mp-primary-bg) !important;
            box-shadow: inset 2px 0 0 var(--mp-primary);
          }
          .mp-taxonomy-tree .q-tree__node-header-content {
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            color: var(--mp-text) !important;
          }
          .mp-taxonomy-tree .q-tree__node--selected > .q-tree__node-header .q-tree__node-header-content {
            color: var(--mp-primary) !important;
          }
          .mp-taxonomy-tree .q-tree__arrow,
          .mp-taxonomy-tree .q-icon { color: var(--mp-muted); }
          .mp-sector-detail-host { min-width: 0; gap: 8px; }
          .mp-sector-breadcrumb {
            color: var(--mp-muted);
            font-size: 11px;
            line-height: 1.45;
            margin-bottom: 8px;
          }
          .mp-sector-selection-title {
            color: var(--mp-text);
            font-size: 20px;
            font-weight: 800;
            line-height: 1.2;
          }
          .mp-metric-pill {
            padding: 3px 8px;
            color: var(--mp-text);
            background: var(--mp-surface-offset);
            border: 1px solid var(--mp-border);
            border-radius: var(--mp-radius-sm);
            font-family: var(--mp-font-mono);
            font-size: 11px;
            font-weight: 600;
          }
          .mp-empty-state {
            width: 100%;
            padding: 18px;
            color: var(--mp-muted);
            background: var(--mp-surface);
            border: 1px dashed var(--mp-border);
            border-radius: var(--mp-radius-md);
            font-size: var(--mp-text-sm);
          }
          .mp-mini-badge {
            display: inline-flex;
            align-items: center;
            width: fit-content;
            padding: 2px 7px;
            border: 1px solid currentColor;
            border-radius: var(--mp-radius-full);
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.03em;
          }

          @media (max-width: 700px) {
            .mp-sector-page .mp-sector-focus-card { padding: 12px !important; }
            .mp-sector-page .mp-sector-table-scroll { max-width: 100%; }
            .mp-sector-page .mp-sector-table .q-table { min-width: 900px; }
            .mp-sector-workspace { grid-template-columns: minmax(0, 1fr); }
            .mp-taxonomy-tree-host { max-height: 52vh; }
            .mp-sector-search { width: 100%; }
          }

          .mp-desk-split { display: flex; width: 100%; align-items: stretch; }
          .mp-desk-queue { flex: 1 1 58%; min-width: 0; padding-right: 8px; }
          .mp-desk-geometry { flex: 1 1 42%; min-width: 280px; }
          .mp-paper {
            background: var(--mp-paper);
            color: var(--mp-paper-ink);
            padding: 16px 18px;
            border-radius: 2px;
          }
          .mp-paper-title { font-size: 13px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; }
          .mp-paper-kicker { font-size: 11px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; margin: 12px 0 6px; }
          .mp-pass { color: #1f8a4c; font-weight: 700; }
          .mp-fail { color: #c0392b; font-weight: 700; }
          .mp-t-slot {
            flex: 1; text-align: center; padding: 6px 0; font-size: 11px; font-weight: 700;
            font-family: var(--mp-font-mono); border: 1px solid var(--mp-paper-ink);
          }
          .mp-t-on { background: var(--mp-paper-ink); color: var(--mp-paper); }
          .mp-kpi { min-width: 110px; padding: 8px 10px; background: var(--mp-surface); border: 1px solid var(--mp-border); }
          .mp-kpi-label { font-size: 13px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--mp-muted); }
          .mp-kpi-value { font-size: 20px; font-weight: 700; font-family: var(--mp-font-mono); color: var(--mp-text); }
          .mp-primary { background: var(--mp-action-bg) !important; color: var(--mp-action-text) !important; }
          .mp-heat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
            gap: 8px;
            width: 100%;
            margin: 8px 0 16px;
          }
          .mp-heat-tile {
            border: 1px solid var(--mp-border);
            padding: 8px 10px;
            min-height: 72px;
          }
          .mp-heat-tile .name { font-size: 14px; font-weight: 600; color: var(--mp-text); }
          .mp-heat-tile .val { font-family: var(--mp-font-mono); font-size: 18px; font-weight: 700; margin-top: 4px; color: var(--mp-text); }
          .mp-heat-tile .meta { font-size: 13px; color: var(--mp-muted); margin-top: 4px; }
          .mp-trend-chart { width: 100%; height: 240px; }
          .mp-heat-up-2 { background: #17351f; }
          .mp-heat-up-1 { background: #102418; }
          .mp-heat-flat { background: var(--mp-surface); }
          .mp-heat-down-1 { background: #2a1719; }
          .mp-heat-down-2 { background: #3b1e21; }
          .mp-deals-split { align-items: flex-start; }

          @media (min-width: 701px) and (max-width: 1050px) {
            .mp-sector-workspace { grid-template-columns: minmax(0, 1fr); }
            .mp-taxonomy-tree-host { max-height: 48vh; }
          }
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
    min-width: 280px;
    max-width: 340px;
    box-shadow: var(--mp-shadow-sm);
  }
  .mp-deal-card .sym {
    font-weight: 800;
    font-size: 16px;
    letter-spacing: -0.2px;
  }
  .mp-deal-card .meta {
    color: var(--mp-muted);
    font-size: 13px;
  }
  .mp-deal-card .inst-line {
    color: var(--mp-text);
    font-size: 13px;
    line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .mp-deal-grid {
    display: grid;
    grid-template-columns: auto 1fr auto 1fr;
    gap: 4px 10px;
    margin-top: 8px;
    font-size: 13px;
  }
  .mp-deal-grid .k { color: var(--mp-muted); }
  .mp-deal-grid .v { font-family: var(--mp-font-mono); font-weight: 700; color: var(--mp-text); text-align: right; }
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
