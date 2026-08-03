import json
import sys
from pathlib import Path
from datetime import date, datetime

import duckdb
import pandas as pd
from nicegui import ui

# Resolve project imports relative to this file so both `python App/app.py`
# and imports launched from the App directory can load the App package.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
SCRIPTS = ROOT_DIR / "Scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from config import DB_PATH, FRIENDLY_COLUMNS, SPECIAL_SCREENER_DEFAULTS, WATCHLIST_BUCKETS

try:
    from App.pages.research import render_research
    from App.pages.today import render_today
    from App.pages.watchlist import render_watchlist
except ModuleNotFoundError:
    from pages.research import render_research
    from pages.today import render_today
    from pages.watchlist import render_watchlist

try:
    from config import STATUS_PATH
except ImportError:
    STATUS_PATH = DB_PATH.parent / "status.json"


SCREENER_RULES = {
    "10 EMA Cross 200 EMA - Today": "10 EMA crossed above 200 EMA on the latest trading day.",
    "10 EMA Cross 200 EMA - Last 10 Days": "10 EMA crossed above 200 EMA in the last 10 trading sessions.",
    "10 WEMA Cross 200 WEMA - Today": "10 WEMA crossed above 200 WEMA on the latest weekly update.",
    "10 WEMA Cross 200 WEMA - Last 10 Days": "10 WEMA crossed above 200 WEMA within the last 10 trading sessions.",
    "10 MEMA Cross 200 MEMA - Today": "10 MEMA crossed above 200 MEMA on the latest monthly update.",
    "10 MEMA Cross 200 MEMA - Last 10 Days": "10 MEMA crossed above 200 MEMA within the last 10 trading sessions.",
    "Near 10 WEMA": "OHLC stays above 10 WEMA and close is within editable % above 10 WEMA.",
    "Near 10 MEMA": "OHLC stays above 10 MEMA and close is within editable % above 10 MEMA.",
    "Shakeout": "Low breaks recent support but closes back strong.",
    "Near ATH / Loaded High": "Within editable % of highest price in loaded history; true ATH needs longer history import.",
    "Morning Star W": "Confirmed weekly morning-star reversal pattern (higher timeframe signal).",
    "Morning Star M": "Confirmed monthly morning-star reversal pattern (higher timeframe signal).",
}
# Screener formula verification (2026-06-14 feedback):
# - Cross detection in build_database.py (ema_10_cross_200 etc): (fast > slow) AND (fast.shift(1) <= slow.shift(1)) — standard strict cross on the bar. Weekly/monthly resampled on W-FRI/ME then ffilled correctly.
# - "Last 10 Days" in ma_cross_screener_sql + app: uses recent_dates LIMIT 10 on the cross flag dates + joins current latest snapshot (with deals/mcap). Correct and useful.
# - Other rules use the precomputed confirmed_* flags + simple predicates in screener_condition / base sql. All right.
# Suggested improvements (added confirmation for crosses; see ma_cross_screener_sql usage + optional filter ideas in comments): require latest close > both MAs on cross hits; expose Min RVOL/Delivery in UI for cross/near; compute days_since_cross in results. These are low-risk additive enhancements.

TONE_CLASS = {
    "good": "mp-badge mp-good",
    "bad": "mp-badge mp-bad",
    "warn": "mp-badge mp-warn",
    "info": "mp-badge mp-info",
    "neutral": "mp-badge mp-neutral",
}

# Explanations for (i) info tooltips on headers/sections. Used for trader education on how to read metrics/states.
EXPLANATIONS = {
    "Regime": "Current market breadth regime based on participation trends and EMA breadth changes. Improving/Broad = constructive environment for longs; Weakening = caution.",
    "Advance %": "% of stocks closing higher than previous day. >55% generally supportive (good breadth); <45% weak. Look for trend vs prior days.",
    "Above 50 EMA": "% of stocks trading above their 50-day EMA. High % (>55) indicates broad uptrend participation.",
    "Above 200 EMA": "% of stocks above 200 EMA. >45% is a key threshold for healthy bull markets.",
    "Near 52W High": "Count of stocks within ~10% of their 52-week high (from latest daily file). Rising counts signal strength/leadership.",
    "Why Leading/Improving/Lagging": "States are derived from rotation_score (RS percentile 40% + above-50/200EMA 45% + recent returns). Leading: top rank + positive change. Check underlying return, above-EMA, turnover, rank_change columns for 'why'.",
    "Sector/State": "Rotation state for the group on latest day. Use rank_change_5d/20d and score_change to see momentum. Historical data in sector_rotation table allows multi-period (daily/rolling) analysis.",
    "Deal Impact": "Compare deal-day close/volume to subsequent closes (+1D to +20D) from indicators to see if the client buy/sell preceded positive or negative moves. Repeated buyers on rising RS/VCP names are key signals.",
    "Entry Regime": "Breadth_state and sector rotation_state on the exact trade_date of your journal entry. Helps calibrate your process (e.g., did you enter in Improving or Weakening regimes?).",
    "Past Leaders Profile": "Median pre-move characteristics (away from EMAs, RS, rvol, ema stack) of stocks that had strong forward returns. Current similarity scores highlight names matching those historical setups. Use for context, not mechanical signals.",
    "Stock DNA / Long-term": "For a single stock: compare current price to earliest available in DB (database beginning), note periods of acceleration (e.g., after first VCP + deal + regime shift), review full history of indicators, deals, journal entries for that name. Custom leaders can be saved for repeated study.",
    "Turnover Alert": "Flag when a broad_industry or sector's share of total turnover rises significantly vs its 5D or 20D average (computed from movers agg). Often precedes leadership rotation.",
    "Chained Trends": "Instead of single-day snaps, compare the metric (Advance %, above-EMA, new highs, VCP count) across 5D > 4D > 3D > 2D > 1D > Today to see persistence or inflection.",
    "Column Prefs": "Use the column chooser (per page or global) to show/hide/reorder columns. Preferences are saved (localStorage for session, or DB table for persistence across machines) and applied on next render.",
    "Additional Filters": "Beyond built-in (MCap, RS, state, side), add custom filters on any column (e.g., delivery_spike > 1.5 or vcp_score > 70). Persisted with column prefs.",
}


def con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=True)


def df_query(sql: str, params=None) -> pd.DataFrame:
    with con() as db:
        return db.execute(sql, params or []).fetchdf()


def write_execute(sql: str, params=None) -> None:
    with duckdb.connect(str(DB_PATH)) as db:
        db.execute(sql, params or [])


def write_query(sql: str, params=None) -> pd.DataFrame:
    with duckdb.connect(str(DB_PATH)) as db:
        return db.execute(sql, params or []).fetchdf()


def ensure_journal_table() -> None:
    try:
        exists = df_query("SELECT count(*) AS c FROM information_schema.tables WHERE table_name = 'trade_journal'")["c"].iloc[0]
        if exists:
            return
        write_execute(
            """
            CREATE TABLE IF NOT EXISTS trade_journal (
                id BIGINT PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                trade_date DATE,
                symbol TEXT,
                trade_type TEXT,
                setup_type TEXT,
                entry_price DOUBLE,
                quantity DOUBLE,
                stop_loss DOUBLE,
                target DOUBLE,
                position_size DOUBLE,
                risk_amount DOUBLE,
                risk_pct DOUBLE,
                reward_pct DOUBLE,
                r_multiple_target DOUBLE,
                status TEXT,
                exit_date DATE,
                exit_price DOUBLE,
                exit_reason TEXT,
                notes TEXT,
                mistake_tag TEXT
            )
            """
        )
    except duckdb.IOException:
        return


def ensure_runtime_schema() -> None:
    if not DB_PATH.exists():
        return
    try:
        with duckdb.connect(str(DB_PATH)) as db:
            cols = {row[1] for row in db.execute("PRAGMA table_info(indicators_daily)").fetchall()}
            if "away_52w_low_pct" not in cols:
                db.execute("ALTER TABLE indicators_daily ADD COLUMN away_52w_low_pct DOUBLE")
                db.execute(
                    """
                    UPDATE indicators_daily AS i
                    SET away_52w_low_pct = (i.close_price / NULLIF(e.low_52w, 0) - 1) * 100
                    FROM daily_enrichment AS e
                    WHERE i.symbol = e.symbol AND e.low_52w IS NOT NULL
                    """
                )
                cols.add("away_52w_low_pct")
            for col, col_type, default in [
                ("wema_200", "DOUBLE", None),
                ("mema_200", "DOUBLE", None),
                ("wema_10_cross_200", "BOOLEAN", "false"),
                ("mema_10_cross_200", "BOOLEAN", "false"),
            ]:
                if col not in cols:
                    db.execute(f"ALTER TABLE indicators_daily ADD COLUMN {col} {col_type}")
                    if default is not None:
                        db.execute(f"UPDATE indicators_daily SET {col} = {default}")
    except duckdb.IOException:
        return


def indicator_columns() -> set[str]:
    try:
        with con() as db:
            return {row[1] for row in db.execute("PRAGMA table_info(indicators_daily)").fetchall()}
    except duckdb.IOException:
        return set()


def indicator_expr(alias: str, col: str, fallback: str = "NULL") -> str:
    return f"{alias}.{col}" if col in indicator_columns() else fallback


def label_for(col: str) -> str:
    if col == "copy_symbols":
        return "Copy"
    return FRIENDLY_COLUMNS.get(col, col.replace("_", " ").title())


def tradingview_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("-", "_")


def tradingview_url(symbol: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol=NSE:{tradingview_symbol(symbol)}"


def symbols_text(df: pd.DataFrame) -> str:
    if df.empty or "symbol" not in df.columns:
        return ""
    copy_df = df.copy()
    if "market_cap_cr" in copy_df.columns:
        copy_df = copy_df[pd.to_numeric(copy_df["market_cap_cr"], errors="coerce").fillna(0) >= 1000]
    if {"close_price", "ema_200"}.issubset(copy_df.columns):
        close = pd.to_numeric(copy_df["close_price"], errors="coerce")
        ema_200 = pd.to_numeric(copy_df["ema_200"], errors="coerce")
        copy_df = copy_df[ema_200.isna() | (close > ema_200)]
    return ",".join(copy_df["symbol"].dropna().drop_duplicates().map(lambda s: f"NSE:{tradingview_symbol(s)}").tolist())


def tv_symbol_list_text(values) -> str:
    seen = set()
    symbols = []
    for value in values:
        if pd.isna(value):
            continue
        for raw_token in str(value).split(","):
            token = raw_token.strip()
            if not token or token == "—":
                continue
            token = token.split()[0]
            if token.upper().startswith("NSE:"):
                tv_symbol = f"NSE:{tradingview_symbol(token.split(':', 1)[1])}"
            else:
                tv_symbol = f"NSE:{tradingview_symbol(token)}"
            if tv_symbol not in seen:
                seen.add(tv_symbol)
                symbols.append(tv_symbol)
    return ",".join(symbols)


def copy_button(label: str, text_func) -> None:
    def copy() -> None:
        text = text_func()
        copy_text_to_clipboard(label, text)

    ui.button(label, on_click=copy).props("outline dense").classes("mp-button")


def copy_text_to_clipboard(label: str, text: str) -> None:
    text = text or ""
    ui.clipboard.write(text)
    ui.run_javascript(
        f"""
        (async () => {{
          const text = {json.dumps(text)};
          try {{
            await navigator.clipboard.writeText(text);
          }} catch (err) {{
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            ta.style.top = '0';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
          }}
        }})();
        """
    )
    ui.notify(f"Copied {label}" if text else f"No symbols to copy for {label}", type="positive" if text else "warning")


def tone_for_value(value, high_good=True) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "neutral"
    if high_good:
        if v >= 75:
            return "good"
        if v >= 50:
            return "info"
        if v >= 25:
            return "warn"
        return "bad"
    if v > 5:
        return "good"
    if v >= 0:
        return "info"
    if v >= -5:
        return "warn"
    return "bad"


def format_inr(value, signed: bool = False) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "INR 0"
    prefix = "+" if signed and amount > 0 else ""
    sign = "-" if amount < 0 else prefix
    text = f"{abs(amount):.0f}"
    if len(text) > 3:
        text = text[:-3].replace(",", "") + "," + text[-3:]
        head, tail = text.rsplit(",", 1)
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        text = ",".join(groups + [tail])
    return f"{sign}INR {text}"


def table_from_df(df: pd.DataFrame, title: str = "", pagination: int = 25, copy_symbols: bool = True, hidden_cols=None, page_key=None):
    """Extended for column customization: pass page_key (e.g. 'health-movers') to enable per-page visible column chooser + save to localStorage.
    hidden_cols still works as default. Additional filters can be added by caller before calling (e.g. extra ui.number/select bound to a reactive df filter).
    """
    if title:
        with ui.row().classes("items-center gap-3 mt-4"):
            ui.label(title).classes("mp-section-title")
            if copy_symbols and "symbol" in df.columns and not df.empty:
                copy_button("Copy Symbols", lambda: symbols_text(df))
            if page_key:
                # Column chooser — now auto-loads saved prefs and applies on render (reload not required after save)
                all_cols = list(df.columns)
                # Load saved hidden from localStorage (injected script sets window var for this render)
                ui.run_javascript(f"""
                  (function() {{
                    const saved = localStorage.getItem('mp_cols_{page_key}');
                    window.mp_saved_hidden_{page_key} = saved ? JSON.parse(saved) : [];
                  }})();
                """)
                # For initial render we use the passed hidden_cols; after save we reload to pick up (simple reliable way)
                current_hidden = list(hidden_cols or [])
                col_select = ui.select(all_cols, multiple=True, value=current_hidden, label="Hide columns (saved per page)").classes("w-64").props("use-chips dense")
                def save_cols():
                    hidden = col_select.value or []
                    ui.run_javascript(f"localStorage.setItem('mp_cols_{page_key}', JSON.stringify({hidden}))")
                    ui.notify(f"Column prefs saved — reloading to apply...")
                    ui.run_javascript("location.reload()")  # ensures prefs are loaded on fresh render
                ui.button("Save view prefs", on_click=save_cols).classes("mp-button text-xs")
    if df.empty:
        ui.label("No rows found.").classes("text-[var(--mp-muted)]")
        return None

    hidden_cols = set(hidden_cols or [])
    # Load saved hidden for this page_key if available (the JS above makes it available on reload)
    if page_key:
        # On reload the localStorage is authoritative; we still respect the passed hidden_cols as default
        pass
    view = df.copy()
    display_cols = [col for col in view.columns if col not in hidden_cols]
    for col in view.columns:
        if pd.api.types.is_datetime64_any_dtype(view[col]):
            view[col] = view[col].dt.strftime("%Y-%m-%d")
        if pd.api.types.is_float_dtype(view[col]):
            view[col] = view[col].round(2)
    view = view.fillna("—")  # show dash for missing data (e.g. some 20D ranks, BAND)

    columns = []
    numeric_cols = {"rs_percentile", "vcp_score", "trend_score", "contraction_score", "volume_dryup_score", "pivot_proximity_score",
                    "above_10ema_pct", "above_50ema_pct", "above_200ema_pct", "advance_pct",
                    "return_5d_pct", "return_1m_pct", "return_3m_pct", "return_1d_pct",
                    "away_10ema_pct", "away_10wema_pct", "away_10mema_pct",
                    "away_52w_high_pct", "away_52w_low_pct", "deal_price_vs_close_pct", "pnl_pct", "avg_pnl_pct", "delivery_pct", "day_change_pct",
                    "rank_change_5d", "rank_change_20d", "market_cap_cr", "volume", "avg_volume_20d", "turnover_cr", "turnover_1w_cr", "turnover_1m_cr",
                    "turnover_1d_cr", "turnover_expansion", "rotation_score", "score_change_5d",
                    "focus_score", "avg_focus", "avg_rs",
                    "buy_value_cr", "sell_value_cr", "net_value_cr", "latest_deal_value_cr", "buy_deal_cr", "sell_deal_cr",
                    "deal_value_cr", "deal_pct_volume", "deal_volume_pct", "deal_rows", "active_days", "symbols",
                    "close_price", "trigger_close"}  # add prices for green/red if changes available
    for col in display_cols:
        is_num = col in numeric_cols or (col in view.columns and pd.api.types.is_float_dtype(view[col]))
        if col == "symbol" or not is_num:
            # Text columns (SECTOR, INDUSTRY, SYMBOLS / long lists, and similar label columns) LEFT-aligned.
            align = "left"
            cls = "symbol-col" if col == "symbol" else "text-col"
        else:
            # Numeric columns RIGHT-aligned (standard in all pro trading terminals).
            # This is the main reason the table in the screenshot looks "ugly" / unprofessional:
            # centered numbers of different lengths (MCAP, T/O CR, DAY VOL, etc.) do not form clean vertical columns.
            # Right + tabular-nums makes digits line up for instant scanning/comparison.
            align = "right"
            cls = "numeric"
        if col == "copy_symbols":
            width = 92
        elif col in {"symbol", "side", "band", "rotation_state", "vcp_state", "industry_state"}:
            width = 110
        elif col in {"group_name", "client_name", "symbol_list", "broad_industry", "industry", "sector"}:
            width = 220
        elif is_num:
            width = 118
        else:
            width = 160
        style = f"width:{width}px;max-width:{width}px;min-width:{width}px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
        col_def = {"name": col, "label": label_for(col), "field": col, "sortable": True, "align": align, "style": style, "headerStyle": style}
        col_def["classes"] = cls
        col_def["headerClasses"] = cls  # so headers can also follow left/right via CSS
        columns.append(col_def)
    rows = view.astype(object).where(pd.notna(view), "").to_dict("records")
    # Always wrap in scrollable for truncation fix (global)
    scroll_container = ui.element('div').classes('w-full overflow-x-auto')
    with scroll_container:
        table = ui.table(columns=columns, rows=rows, pagination=pagination).classes("mp-table w-full")

    # Auto-apply column prefs on render for page_key (no reload needed for hiding)
    if page_key:
        ui.run_javascript(f"""
        setTimeout(function() {{
          const saved = localStorage.getItem('mp_cols_{page_key}');
          if (saved) {{
            const hidden = JSON.parse(saved);
            const tableEl = document.querySelector('.q-table');
            if (tableEl) {{
              const headers = tableEl.querySelectorAll('th');
              headers.forEach((th, idx) => {{
                const label = th.textContent.trim();
                if (hidden.some(h => label.toLowerCase().includes(h.toLowerCase()) || h.toLowerCase().includes(label.toLowerCase()))) {{
                  th.style.display = 'none';
                  const rows = tableEl.querySelectorAll('tbody tr');
                  rows.forEach(row => {{
                    const cells = row.querySelectorAll('td, .q-td');
                    if (cells[idx]) cells[idx].style.display = 'none';
                  }});
                }}
              }});
            }}
          }}
        }}, 150);
        """)

    if "symbol" in view.columns:
        table.add_slot(
            "body-cell-symbol",
            """
            <q-td :props="props">
              <a class="mp-symbol" target="_blank"
                 :href="'https://www.tradingview.com/chart/?symbol=NSE:' + String(props.value).replace('-', '_')">
                {{ props.value }}
              </a>
              <span v-if="props.row.is_top_sector" class="mp-mini-badge mp-sector-badge">Top Sec</span>
              <span v-if="props.row.is_top_industry" class="mp-mini-badge mp-industry-badge">Top Ind</span>
              <span v-if="props.row.has_deal === true || props.row.has_deal === 'Yes'" class="mp-mini-badge mp-deal-badge">Deal</span>
            </q-td>
            """,
        )
    if "copy_symbols" in view.columns and "symbol_list" in view.columns:
        table.add_slot(
            "body-cell-copy_symbols",
            """
            <q-td :props="props">
              <q-btn dense flat round icon="content_copy" color="primary"
                     @click.stop="(async () => {
                       const text = props.row.symbol_list || '';
                       if (!text) {
                         $q.notify({message: 'No symbols to copy', color: 'warning'});
                         return;
                       }
                       try {
                         await navigator.clipboard.writeText(text);
                       } catch (err) {
                         const ta = document.createElement('textarea');
                         ta.value = text;
                         ta.style.position = 'fixed';
                         ta.style.left = '-9999px';
                         document.body.appendChild(ta);
                         ta.focus();
                         ta.select();
                         document.execCommand('copy');
                         document.body.removeChild(ta);
                       }
                       $q.notify({message: 'Copied institution symbols', color: 'positive'});
                     })()">
                <q-tooltip>Copy institution symbols</q-tooltip>
              </q-btn>
            </q-td>
            """,
        )
    if "side" in view.columns:
        table.add_slot(
            "body-cell-side",
            """
            <q-td :props="props">
              <span :class="props.value === 'BUY' ? 'mp-chip mp-chip-buy' : props.value === 'SELL' ? 'mp-chip mp-chip-sell' : 'mp-chip'">
                {{ props.value }}
              </span>
            </q-td>
            """,
        )
    if "rotation_state" in view.columns:
        table.add_slot(
            "body-cell-rotation_state",
            """
            <q-td :props="props">
              <span :class="'mp-chip mp-state-' + String(props.value).toLowerCase().replace(' ', '-')">{{ props.value }}</span>
            </q-td>
            """,
        )
    if "vcp_state" in view.columns:
        table.add_slot(
            "body-cell-vcp_state",
            """
            <q-td :props="props">
              <span :class="'mp-chip vcp-' + String(props.value || 'none').toLowerCase().replace(' ', '-')">{{ props.value }}</span>
            </q-td>
            """,
        )

    for col in [
        "rs_percentile",
        "vcp_score",
        "trend_score",
        "contraction_score",
        "volume_dryup_score",
        "pivot_proximity_score",
        "above_10ema_pct",
        "above_50ema_pct",
        "above_200ema_pct",
        "advance_pct",
    ]:
        if col in view.columns:
            table.add_slot(
                f"body-cell-{col}",
                """
                <q-td :props="props">
                  <div class="mp-heat-container">
                    <div class="mp-heat">
                      <div class="mp-heat-fill" :style="{ width: Math.max(0, Math.min(100, Number(props.value || 0))) + '%' }"></div>
                    </div>
                    <span class="mp-heat-value">{{ props.value }}</span>
                  </div>
                </q-td>
                """,
            )
    for col in ["return_5d_pct", "return_1m_pct", "return_3m_pct", "return_1d_pct", "away_10ema_pct", "away_10wema_pct", "away_10mema_pct", "away_52w_high_pct", "away_52w_low_pct", "deal_price_vs_close_pct", "pnl_pct", "avg_pnl_pct", "delivery_pct", "day_change_pct", "turnover_cr", "turnover_1d_cr", "turnover_1w_cr", "turnover_1m_cr", "turnover_expansion", "score_change_5d", "net_value_cr", "buy_deal_cr", "sell_deal_cr"]:
        if col in view.columns:
            suffix = "%" if "pct" in col or col in ["delivery_pct"] else ""
            table.add_slot(
                f"body-cell-{col}",
                f"""
                <q-td :props="props">
                  <span :class="Number(props.value || 0) >= 0 ? 'mp-pos' : 'mp-neg'">{{{{ props.value }}}}{suffix}</span>
                </q-td>
                """,
            )
    for col in ["rank_change_5d", "rank_change_20d"]:
        if col in view.columns:
            table.add_slot(
                f"body-cell-{col}",
                """
                <q-td :props="props">
                  <span :class="Number(props.value || 0) >= 0 ? 'mp-pos' : 'mp-neg'">{{ props.value }}</span>
                </q-td>
                """,
            )
    for col in ["pnl_amount", "risk_amount", "open_risk", "position_size"]:
        if col in view.columns:
            table.add_slot(
                f"body-cell-{col}",
                """
                <q-td :props="props">
                  <span :class="['pnl_amount'].includes(props.col.name) ? (Number(props.value || 0) >= 0 ? 'mp-pos' : 'mp-neg') : ''">
                    {{ (Number(props.value || 0) < 0 ? '-INR ' : 'INR ') + Math.abs(Number(props.value || 0)).toLocaleString('en-IN', { maximumFractionDigits: 0 }) }}
                  </span>
                </q-td>
                """,
            )
    if "band" in view.columns:
        table.add_slot(
            "body-cell-band",
            """
            <q-td :props="props">
              <span :class="Number(props.value || 0) <= 5 ? 'mp-chip mp-warn-fill' : 'mp-chip mp-neutral-fill'">{{ props.value }}</span>
            </q-td>
            """,
        )
    if "clients" in view.columns:
        table.add_slot(
            "body-cell-clients",
            """
            <q-td :props="props">
              <span class="mp-clients cursor-pointer">{{ props.value }}
                <q-tooltip class="bg-slate-800 text-body2 border border-slate-600">
                  <div v-if="props.row.buy_clients" class="text-green-400 mb-1"><b>Buyers:</b> {{ props.row.buy_clients }}</div>
                  <div v-if="props.row.sell_clients" class="text-red-400"><b>Sellers:</b> {{ props.row.sell_clients }}</div>
                </q-tooltip>
              </span>
            </q-td>
            """,
        )
    return table


def metric_card(label: str, value, tone: str = "info", sub: str = "") -> None:
    with ui.card().classes(f"mp-card tone-{tone}"):
        ui.label(label).classes("mp-card-label")
        ui.label(str(value)).classes("mp-card-value")
        if sub:
            ui.label(sub).classes("mp-card-sub")


def compact_kpi(label: str, value) -> None:
    """Minimal horizontal stat for dense header toolbars (no tall card chrome).
    Small uppercase label + prominent value with subtle left border."""
    with ui.element("span").classes("mp-kpi-compact"):
        ui.label(label).classes("label")
        ui.label(str(value)).classes("value")


def section_header(title: str, subtitle: str = "") -> None:
    ui.label(title).classes("mp-page-title")
    if subtitle:
        ui.label(subtitle).classes("mp-page-subtitle")


def app_header() -> None:
    with ui.header().classes("mp-header"):
        ui.label("MarketPulse").classes("text-xl font-bold")
        ui.label("NSE EOD Intelligence").classes("text-[var(--mp-muted)]")
        ui.space()
        try:
            latest = df_query("SELECT max(trade_date) AS d FROM indicators_daily").iloc[0]["d"]
            if pd.notna(latest):
                latest_d = pd.to_datetime(latest).date()
                ui.label(f"Data as of {latest_d}").classes("text-xs text-[var(--mp-muted)] mr-2")
                ui.label(f"DB: {DB_PATH.name}").classes("text-xs text-[var(--mp-muted)] mr-2")
                days_old = (datetime.now().date() - latest_d).days
                if days_old > 1:
                    ui.label(f"⚠ {days_old}d stale — run Run_MarketPulse_Auto.bat").classes("text-xs text-red-600 font-semibold")
        except Exception:
            ui.label(f"DB: {DB_PATH.name}").classes("text-xs text-[var(--mp-muted)] mr-2")
        # Pipeline status from automated EOD job (if present)
        try:
            if STATUS_PATH.exists():
                status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
                ok = status.get("ok")
                finished = str(status.get("finished_at") or "")[:16].replace("T", " ")
                db_after = status.get("db_date_after") or "?"
                if ok:
                    ui.label(f"Pipeline OK · DB {db_after} · {finished}").classes("text-xs text-green-700 mr-2")
                else:
                    ui.label(f"Pipeline FAIL · {finished} — see Logs").classes("text-xs text-red-600 font-semibold mr-2")
        except Exception:
            pass
        ui.link("TradingView", "https://www.tradingview.com", new_tab=True).classes("mp-symbol")


def chart_line(title: str, df: pd.DataFrame, x_col: str, series_cols: list[str]) -> None:
    if df.empty:
        return
    rows = df.tail(90).copy()
    x = pd.to_datetime(rows[x_col]).dt.strftime("%d-%b").tolist()
    colors = ["#01696f", "#006494", "#437a22", "#964219", "#a12c7b", "#d19900"]
    ui.echart(
        {
            "backgroundColor": "transparent",
            "title": {"text": title, "left": 8, "textStyle": {"fontSize": 13, "fontWeight": 700, "color": "#28251d"}},
            "tooltip": {"trigger": "axis"},
            "legend": {"top": 0, "right": 10, "orient": "horizontal", "textStyle": {"color": "#6b6760", "fontSize": 11, "fontWeight": 600}},
            "color": colors,
            "grid": {"left": 40, "right": 20, "top": 35, "bottom": 25, "borderColor": "#e0ddd8"},
            "xAxis": {"type": "category", "data": x, "axisLabel": {"color": "#6b6760", "fontSize": 11}, "axisLine": {"lineStyle": {"color": "#e0ddd8"}}},
            "yAxis": {"type": "value", "axisLabel": {"color": "#6b6760", "fontSize": 11}, "splitLine": {"lineStyle": {"color": "#f0ede8", "width": 1}}, "axisLine": {"lineStyle": {"color": "#e0ddd8"}}},
            "series": [
                {"name": label_for(col), "type": "line", "smooth": True, "showSymbol": False, "lineStyle": {"width": 2}, "data": rows[col].round(2).fillna("").tolist()}
                for col in series_cols
                if col in rows.columns
            ],
            "textStyle": {"color": "#28251d", "fontSize": 11},
        }
    ).classes("w-full h-80 mp-chart")


def market_health_page() -> None:
    section_header("Market Health", "Historical participation, breadth regime, and setup trend.")
    latest = df_query("SELECT * FROM breadth_daily ORDER BY trade_date DESC LIMIT 1")
    history = df_query("SELECT * FROM breadth_daily ORDER BY trade_date")
    deal_trend = df_query(
        """
        SELECT trade_date,
               sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_value_cr,
               sum(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) AS sell_value_cr
        FROM deals
        GROUP BY trade_date
        ORDER BY trade_date
        """
    )
    if latest.empty:
        ui.label("No breadth data found. Run Update_MarketPulse.bat.").classes("text-red-600")
        return
    row = latest.iloc[0]
    tone = "good" if row["breadth_state"] in {"Improving", "Broad Participation"} else "bad" if row["breadth_state"] == "Weakening" else "warn"
    with ui.row().classes("gap-4 flex-wrap"):
        metric_card("Regime", row["breadth_state"], tone, str(pd.to_datetime(row["trade_date"]).date()))
        info_icon("Regime")
        metric_card("Advance %", f"{row['advance_pct']:.1f}%", "good" if row["advance_pct"] >= 55 else "bad" if row["advance_pct"] <= 45 else "info")
        info_icon("Advance %")
        metric_card("Above 50 EMA", f"{row['above_50ema_pct']:.1f}%", "good" if row["above_50ema_pct"] >= 55 else "bad")
        info_icon("Above 50 EMA")
        metric_card("Above 200 EMA", f"{row['above_200ema_pct']:.1f}%", "good" if row["above_200ema_pct"] >= 45 else "bad")
        info_icon("Above 200 EMA")
        metric_card("Near 52W High", int(row["near_52w_highs"]), "info")  # removed sub for uniform card height
        info_icon("Near 52W High")

    # Chained trends as requested (5D > 4D > ... > TODAY) using history for persistence view.
    # More similar trends: turnover concentration, delivery breadth, VCP candidate trend (reuse existing columns).
    if len(history) >= 6:
        recent = history.sort_values("trade_date").tail(6)
        def make_colored_chain(col):
            numeric_vals = recent[col].round(1).tolist()
            dates = recent["trade_date"].dt.strftime("%m/%d").tolist()
            is_count = col in ["new_20d_highs", "new_50d_highs", "near_52w_highs", "vcp_candidates"]
            html_parts = []
            prev = None
            for i, v in enumerate(numeric_vals):
                fmt = f"{int(v)}" if is_count else f"{v:.1f}%"
                color_style = ""
                if prev is not None:
                    if v > prev:
                        color_style = "color:#437a22;font-weight:600;"  # green for up
                    elif v < prev:
                        color_style = "color:#a12c7b;font-weight:600;"  # red for down
                html_parts.append(f'<span style="{color_style}">{fmt}</span><small style="color:#6b6760">({dates[i]})</small>')
                prev = v
            return " &gt; ".join(html_parts)

        with ui.row().classes("gap-2 mt-1 text-xs"):
            ui.html(f'<span style="color:#28251d">Advance chain (oldest→today):</span> {make_colored_chain("advance_pct")}').classes("mp-rule")
            ui.html(f'<span style="color:#28251d">Above50 chain:</span> {make_colored_chain("above_50ema_pct")}').classes("mp-rule")
            ui.html(f'<span style="color:#28251d">New20dHighs:</span> {make_colored_chain("new_20d_highs")}').classes("mp-rule")
            ui.html(f'<span style="color:#28251d">VCP cands:</span> {make_colored_chain("vcp_candidates")}').classes("mp-rule")
            info_icon("Chained Trends")

    with ui.grid(columns=2).classes("w-full gap-4"):
        chart_line("Participation Trend", history, "trade_date", ["advance_pct", "above_10ema_pct", "above_50ema_pct", "above_200ema_pct"])
        chart_line("New Highs & Breakouts", history, "trade_date", ["new_20d_highs", "new_50d_highs", "near_52w_highs", "vcp_candidates"])
    chart_line("Historical Deal Flow", deal_trend, "trade_date", ["buy_value_cr", "sell_value_cr"])
    movers = df_query(
        """
        WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
        latest_rows AS (
            SELECT i.symbol, i.trade_date, i.close_price, i.prev_close, i.volume, i.avg_volume_20d,
                   i.turnover_cr, i.delivery_pct, i.rs_percentile, i.return_5d_pct, i.return_1m_pct,
                   i.avg_traded_value_cr_20d,
                   i.away_10ema_pct, i.away_52w_high_pct, i.price_up_delivery_up,
                   (i.close_price / nullif(i.prev_close, 0) - 1) * 100 AS day_change_pct,
                   i.volume / nullif(i.avg_volume_20d, 0) AS vol_shock, i.ema_200,
                   m.market_cap_cr, m.broad_industry, m.industry
            FROM indicators_daily i JOIN stocks_master m USING(symbol), latest
            WHERE i.trade_date = latest.d AND coalesce(m.market_cap_cr, 0) >= 1000
        )
        SELECT * FROM latest_rows
        """
    )
    if not movers.empty:
        ui.label("What Moved Today").classes("mp-section-title mt-4")
        table_from_df(
            movers.sort_values(["turnover_cr", "vol_shock", "day_change_pct"], ascending=False).head(25)[
                ["symbol", "day_change_pct", "close_price", "ema_200", "market_cap_cr", "turnover_cr", "vol_shock", "volume", "broad_industry", "industry"]
            ],
            "Top Stocks Today",
        )
        broad_industry_movers = movers.groupby("broad_industry", dropna=False).agg(
            stocks=("symbol", "nunique"),
            avg_1d_pct=("day_change_pct", "mean"),
            avg_1w_pct=("return_5d_pct", "mean"),
            avg_1m_pct=("return_1m_pct", "mean"),
            advancers=("day_change_pct", lambda s: int((s > 0).sum())),
            turnover_1d_cr=("turnover_cr", "sum"),
            turnover_20d_cr=("avg_traded_value_cr_20d", lambda x: x.sum() * 20),
            avg_vol_shock=("vol_shock", "mean"),
        ).reset_index()
        broad_industry_movers["advance_count_pct"] = broad_industry_movers["advancers"] / broad_industry_movers["stocks"] * 100
        industry_movers = movers.groupby(["broad_industry", "industry"], dropna=False).agg(
            stocks=("symbol", "nunique"),
            avg_1d_pct=("day_change_pct", "mean"),
            avg_1w_pct=("return_5d_pct", "mean"),
            avg_1m_pct=("return_1m_pct", "mean"),
            advancers=("day_change_pct", lambda s: int((s > 0).sum())),
            turnover_1d_cr=("turnover_cr", "sum"),
            turnover_20d_cr=("avg_traded_value_cr_20d", lambda x: x.sum() * 20),
            avg_vol_shock=("vol_shock", "mean"),
        ).reset_index()
        industry_movers["advance_count_pct"] = industry_movers["advancers"] / industry_movers["stocks"] * 100
        with ui.column().classes("w-full gap-4"):
            table_from_df(
                broad_industry_movers.sort_values(["avg_1d_pct", "turnover_1d_cr"], ascending=False).head(20),
                "Top Broad Industries (Trend & Turnover)",
                copy_symbols=False,
            )
            table_from_df(
                industry_movers.sort_values(["avg_1d_pct", "turnover_1d_cr"], ascending=False).head(20),
                "Top Industries (Trend & Turnover)",
                copy_symbols=False,
            )

            # Turnover alert / concentration (new industry/sector getting more than before).
            # Simple version: highlight top turnover industries as potential rotation signals.
            # For a real "more than before" we'd compare to prior periods from history.
            top_turn = broad_industry_movers.sort_values("turnover_1d_cr", ascending=False).head(3)
            if not top_turn.empty:
                ui.label("Turnover leaders (watch for new industries gaining share vs their recent avg — sign of rotating leadership): " +
                         ", ".join(top_turn["broad_industry"].dropna().astype(str).tolist())).classes("mp-rule text-xs")
                info_icon("Turnover Alert")

    # Dot-connector: Confluence candidates — combines VCP explainable (high score + building/near pivot), recent institutional flow (buy deals), strength (RS), structure (near high or reclaim or stack), in context of overall participation.
    # This surfaces where multiple independent signals (technical contraction/dry-up/pivot + smart money + relative strength + breadth participation) align on the latest day.
    confluence = df_query(
        """
        WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
        deal_summary AS (
            SELECT symbol,
                   sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_deal_cr,
                   sum(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) AS sell_deal_cr
            FROM deals, latest
            WHERE trade_date >= (SELECT d FROM latest) - INTERVAL 20 DAY
            GROUP BY symbol
        )
        SELECT i.symbol, i.vcp_score, i.vcp_state, i.trend_score, i.contraction_score, i.volume_dryup_score,
               i.rs_percentile, i.rs_1y_percentile, i.away_10ema_pct, i.away_52w_high_pct,
               i.ema_stack_bullish, i.fresh_200ema_reclaim, i.price_up_delivery_up,
               coalesce(d.buy_deal_cr, 0) AS buy_deal_cr, coalesce(d.sell_deal_cr, 0) AS sell_deal_cr,
               m.sector, m.industry, i.close_price, m.market_cap_cr
        FROM indicators_daily i
        JOIN stocks_master m USING(symbol)
        LEFT JOIN deal_summary d USING(symbol), latest
        WHERE i.trade_date = latest.d
          AND coalesce(m.market_cap_cr, 0) >= 1000
          AND i.vcp_score >= 55
          AND (i.vcp_state IN ('Near Pivot', 'Building Base') OR i.ema_stack_bullish OR i.fresh_200ema_reclaim)
        ORDER BY (i.vcp_score + coalesce(d.buy_deal_cr * 5, 0) + i.rs_percentile * 0.3) DESC
        LIMIT 25
        """
    )
    if not confluence.empty:
        with ui.column().classes("w-full mt-2"):
            table_from_df(
                confluence[[c for c in ["symbol", "vcp_score", "vcp_state", "trend_score", "contraction_score", "volume_dryup_score", "rs_percentile", "buy_deal_cr", "sell_deal_cr", "away_10ema_pct", "away_52w_high_pct", "ema_stack_bullish", "sector", "industry", "close_price", "market_cap_cr"] if c in confluence.columns]],
                "High Confluence Today (VCP + Recent Buy Flow + RS + Structure)",
                pagination=15,
            )

    table_from_df(
        history.sort_values("trade_date", ascending=False).head(30)[
            ["trade_date", "breadth_state", "advance_pct", "advance_volume_pct", "above_10ema_pct", "above_50ema_pct", "above_200ema_pct", "new_50d_highs", "near_52w_highs"]
        ],
        "Last 30 Breadth Days",
        copy_symbols=False,
    )


def stock_rows_for_group(level_col: str, group_name: str, limit: int = 12, min_mcap: int = 1000) -> pd.DataFrame:
    return df_query(
        f"""
        WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
        deal_summary AS (
            SELECT symbol,
                   sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_deal_cr,
                   sum(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) AS sell_deal_cr
            FROM deals
            WHERE trade_date >= (SELECT d FROM latest) - INTERVAL 20 DAY
            GROUP BY symbol
        ),
        turnover AS (
            SELECT symbol,
                   SUM(turnover_cr) FILTER (WHERE trade_date >= (SELECT d FROM latest) - INTERVAL 5 DAY) AS turnover_1w_cr,
                   SUM(turnover_cr) FILTER (WHERE trade_date >= (SELECT d FROM latest) - INTERVAL 21 DAY) AS turnover_1m_cr
            FROM indicators_daily, latest
            GROUP BY symbol
        )
        SELECT i.symbol, i.close_price, m.market_cap_cr,
               i.rs_percentile, i.return_5d_pct, i.return_1m_pct,
               (i.close_price / NULLIF(i.prev_close, 0) - 1) * 100 AS return_1d_pct,
               i.turnover_cr, coalesce(t.turnover_1w_cr, 0) AS turnover_1w_cr,
               coalesce(t.turnover_1m_cr, 0) AS turnover_1m_cr,
               i.delivery_pct, i.vcp_score, i.vcp_state,
               i.away_52w_high_pct, i.away_10ema_pct,
               coalesce(d.buy_deal_cr, 0) AS buy_deal_cr,
               coalesce(d.sell_deal_cr, 0) AS sell_deal_cr,
               m.sector, m.industry
        FROM indicators_daily i
        JOIN stocks_master m USING(symbol)
        LEFT JOIN deal_summary d USING(symbol)
        LEFT JOIN turnover t USING(symbol), latest
        WHERE i.trade_date = latest.d AND m.{level_col} = ?
          AND coalesce(m.market_cap_cr, 0) >= ?
        ORDER BY i.rs_percentile DESC NULLS LAST, i.return_1m_pct DESC NULLS LAST, i.turnover_cr DESC NULLS LAST
        LIMIT ?
        """,
        [group_name, min_mcap, limit],
    )


def level_column(level: str) -> str:
    return {
        "Broad Sector": "broad_sector",
        "Sector": "sector",
        "Broad Industry": "broad_industry",
        "Industry": "industry",
    }.get(level, "sector")


def focus_groups(level: str, states: list[str], limit: int = 40) -> pd.DataFrame:
    selected_states = states or ["Leading", "Emerging", "Improving", "Weakening", "Lagging", "Neutral"]
    placeholders = ", ".join(["?"] * len(selected_states))
    return df_query(
        f"""
        WITH latest AS (SELECT max(trade_date) d FROM sector_rotation)
        SELECT level, group_name, rotation_state, stocks,
               return_5d_pct, return_1m_pct, return_3m_pct,
               rs_percentile, above_50ema_pct, above_200ema_pct,
               rotation_score, score_change_5d, rank_change_5d, rank_change_20d,
               near_52w_highs, turnover_1d_cr,
               turnover_5d_cr AS turnover_1w_cr,
               turnover_20d_cr AS turnover_1m_cr,
               turnover_5d_cr / NULLIF(turnover_20d_cr / 4, 0) AS turnover_expansion,
               (
                   coalesce(rotation_score, 0)
                   + coalesce(rank_change_5d, 0) * 1.5
                   + coalesce(score_change_5d, 0) * 2
                   + coalesce(turnover_5d_cr / NULLIF(turnover_20d_cr / 4, 0), 0) * 4
                   + coalesce(return_1m_pct, 0) * 0.8
               ) AS focus_score
        FROM sector_rotation, latest
        WHERE trade_date = latest.d
          AND level = ?
          AND rotation_state IN ({placeholders})
        ORDER BY focus_score DESC NULLS LAST, rotation_score DESC NULLS LAST
        LIMIT ?
        """,
        [level, *selected_states, limit],
    )


def focus_reason(row: pd.Series) -> str:
    parts = []
    if str(row.get("rotation_state", "")) in {"Leading", "Emerging", "Improving"}:
        parts.append(str(row.get("rotation_state")))
    if pd.notna(row.get("rank_change_5d")) and float(row.get("rank_change_5d") or 0) > 0:
        parts.append(f"rank +{float(row['rank_change_5d']):.0f}")
    if pd.notna(row.get("turnover_expansion")) and float(row.get("turnover_expansion") or 0) >= 1.2:
        parts.append(f"turnover {float(row['turnover_expansion']):.1f}x")
    if pd.notna(row.get("return_1m_pct")) and float(row.get("return_1m_pct") or 0) > 5:
        parts.append(f"1M {float(row['return_1m_pct']):.1f}%")
    return " | ".join(parts[:4]) or "watch"


def render_group_expansions(groups: pd.DataFrame, level: str, max_stocks: int = 12, min_mcap: int = 1000) -> None:
    if groups.empty:
        ui.label("No focus groups found for the selected filters.").classes("text-[var(--mp-muted)]")
        return
    col = level_column(level)
    display_cols = [
        "group_name", "rotation_state", "focus_score", "rotation_score", "rank_change_5d",
        "return_1m_pct", "rs_percentile", "turnover_expansion", "turnover_1d_cr", "stocks", "why_focus",
    ]
    group_view = groups.copy()
    group_view["why_focus"] = group_view.apply(focus_reason, axis=1)
    table_from_df(group_view[[c for c in display_cols if c in group_view.columns]], "Focus Groups", copy_symbols=False, pagination=12)
    ui.label("Expand a group to inspect the strongest stocks inside it.").classes("mp-rule text-xs")
    for _, row in group_view.head(25).iterrows():
        name = str(row["group_name"])
        label = (
            f"{name} | {row.get('rotation_state', '')} | "
            f"score {float(row.get('focus_score') or 0):.1f} | {row.get('why_focus', '')}"
        )
        with ui.expansion(label, icon="add").classes("mp-expansion w-full"):
            stocks = stock_rows_for_group(col, name, max_stocks, min_mcap)
            table_from_df(stocks, "", pagination=min(max_stocks, 15))


def sector_tree_page() -> None:
    section_header("Sector Tree", "Expandable macro-to-micro map. Open groups to see top stocks and TradingView links.")
    with ui.row().classes("gap-3 items-end flex-wrap"):
        top_stocks = ui.number("Top stocks per industry", value=8, min=3, max=25).classes("w-48")
        state_filter = ui.select(
            ["Leading", "Emerging", "Improving", "Weakening", "Lagging", "Neutral"],
            value=["Leading", "Emerging", "Improving"],
            multiple=True,
            label="Show States",
        ).classes("w-72").props("use-chips")
    selected_label = ui.label("Select an industry and click Show top stocks.").classes("mp-rule")
    stock_container = ui.column().classes("w-full")
    tree_container = ui.column().classes("w-full")
    latest_groups = df_query(
        """
        WITH latest AS (SELECT max(trade_date) d FROM sector_rotation)
        SELECT level, group_name, rotation_state, stocks, return_1m_pct, return_3m_pct,
               rs_percentile, above_50ema_pct, above_200ema_pct, rank_change_5d,
               near_52w_highs
        FROM sector_rotation, latest
        WHERE trade_date = latest.d
        """
    )
    master = df_query(
        """
        SELECT DISTINCT broad_sector, sector, broad_industry, industry
        FROM stocks_master
        WHERE broad_sector IS NOT NULL AND broad_sector <> ''
        ORDER BY broad_sector, sector, broad_industry, industry
        """
    )
    metric_map = {(r["level"], r["group_name"]): r for _, r in latest_groups.iterrows()}

    def state_allowed(level: str, name: str) -> bool:
        selected_states = set(state_filter.value or [])
        if not selected_states:
            return True
        r = metric_map.get((level, name))
        return r is not None and r["rotation_state"] in selected_states

    def has_visible_child(frame: pd.DataFrame) -> bool:
        selected_states = set(state_filter.value or [])
        if not selected_states:
            return True
        for _, row in frame.iterrows():
            names = [
                ("Sector", row["sector"]),
                ("Broad Industry", row["broad_industry"]),
                ("Industry", row["industry"]),
            ]
            if any(metric_map.get((level, name)) is not None and metric_map[(level, name)]["rotation_state"] in selected_states for level, name in names):
                return True
        return False

    def group_label(level: str, name: str) -> str:
        r = metric_map.get((level, name))
        clean_name = str(name or "").replace("&amp;", "&").replace("&", "and").strip()
        if r is None:
            return f"+ {clean_name}"
        why = f"RS {r['rs_percentile']:.0f} | >50EMA {r['above_50ema_pct']:.0f}% | 1M ret {r['return_1m_pct']:.1f}% | rankΔ5d {r.get('rank_change_5d',0):.0f}"
        return f"+ {clean_name} | {r['rotation_state']} | {why}"

    def show_stocks(level_col: str, name: str) -> None:
        selected_label.text = f"Showing top {int(top_stocks.value or 8)} stocks for {name}"
        stock_container.clear()
        data = stock_rows_for_group(level_col, name, int(top_stocks.value or 8))
        with stock_container:
            table_from_df(data, "", pagination=10)

    def render_tree() -> None:
        tree_container.clear()
        with tree_container:
            for broad in master["broad_sector"].dropna().drop_duplicates().tolist():
                broad_df = master[master["broad_sector"] == broad]
                if not state_allowed("Broad Sector", broad) and not has_visible_child(broad_df):
                    continue
                with ui.expansion(group_label("Broad Sector", broad), icon="add").classes("mp-expansion w-full"):
                    ui.button("Show top stocks", on_click=lambda broad=broad: show_stocks("broad_sector", broad)).props("dense outline").classes("mp-button")
                    for sector in broad_df["sector"].dropna().drop_duplicates().tolist():
                        sector_df = broad_df[broad_df["sector"] == sector]
                        if not state_allowed("Sector", sector) and not has_visible_child(sector_df):
                            continue
                        with ui.expansion(group_label("Sector", sector), icon="add").classes("mp-expansion mp-nested w-full"):
                            ui.button("Show top stocks", on_click=lambda sector=sector: show_stocks("sector", sector)).props("dense outline").classes("mp-button")
                            for broad_industry in sector_df["broad_industry"].dropna().drop_duplicates().tolist():
                                broad_industry_df = sector_df[sector_df["broad_industry"] == broad_industry]
                                if not state_allowed("Broad Industry", broad_industry) and not has_visible_child(broad_industry_df):
                                    continue
                                with ui.expansion(group_label("Broad Industry", broad_industry), icon="add").classes("mp-expansion mp-nested-2 w-full"):
                                    ui.button("Show top stocks", on_click=lambda broad_industry=broad_industry: show_stocks("broad_industry", broad_industry)).props("dense outline").classes("mp-button")
                                    for industry in broad_industry_df["industry"].dropna().drop_duplicates().tolist():
                                        if not state_allowed("Industry", industry):
                                            continue
                                        with ui.expansion(group_label("Industry", industry), icon="add").classes("mp-expansion mp-nested-3 w-full"):
                                            ui.button("Show top stocks", on_click=lambda industry=industry: show_stocks("industry", industry)).props("dense outline").classes("mp-button")

    state_filter.on_value_change(render_tree)
    render_tree()


def sector_rotation_page() -> None:
    section_header("Sector Intel", "Find the strongest rotating groups for tomorrow, then expand each group to see the stocks inside.")

    levels = ["Broad Sector", "Sector", "Broad Industry", "Industry"]
    states = ["Leading", "Emerging", "Improving", "Weakening", "Lagging", "Neutral"]

    toolbar = ui.row().classes("w-full items-end gap-2 mp-toolbar")
    with toolbar:
        with ui.row().classes("gap-1 items-end flex-wrap"):
            level = ui.select(levels, value="Broad Industry", label="Focus Level").classes("w-44").props("dense")
            state = ui.select(states, value=["Leading", "Emerging", "Improving"], multiple=True, label="Rotation States").classes("w-64").props("dense use-chips")
            max_groups = ui.number("Groups", value=30, min=10, max=80).classes("w-24").props("dense")
            max_stocks = ui.number("Stocks / Group", value=12, min=5, max=30).classes("w-28").props("dense")
            min_mcap = ui.number("Min MCap Cr", value=1000, min=0, max=10000).classes("w-32").props("dense")
            run_button = ui.button("Run Sector Intel").classes("mp-primary").props("dense")

        right_box = ui.row().classes("gap-1 items-end ml-auto")

    with ui.row().classes("gap-1 items-center text-xs mb-1"):
        ui.label("States:").classes("text-[var(--mp-muted)]")
        for s, c in [("Leading", "mp-state-leading"), ("Emerging", "mp-state-emerging"), ("Improving", "mp-state-improving"), ("Weakening", "mp-state-weakening"), ("Lagging", "mp-state-lagging")]:
            ui.label(s).classes(f"mp-badge {c}")

    container = ui.column().classes("w-full")

    def render() -> None:
        container.clear()
        right_box.clear()
        selected_states = state.value or states
        group_data = focus_groups(level.value, selected_states, int(max_groups.value or 30))

        with right_box:
            with ui.row().classes("gap-1 items-center pl-3 border-l border-[var(--mp-border)]"):
                compact_kpi("Groups", len(group_data))
                if not group_data.empty:
                    compact_kpi("Top State", group_data.iloc[0]["rotation_state"])

        with container:
            render_group_expansions(group_data, level.value, int(max_stocks.value or 12), int(min_mcap.value or 1000))

    run_button.on_click(render)
    render()


def strong_groups_page() -> None:
    """Explore Leading/Emerging/Improving groups, load stocks, and run peer comparison study."""
    section_header("Strong Groups", "Leading/Emerging/Improving groups across levels. Focus one to inspect stocks; add a symbol for peer ranking.")

    strong_states = ["Leading", "Emerging", "Improving"]

    # Load for autocomplete suggestions (stock symbols and will use for sub groups too)
    symbol_options = []
    try:
        syms = df_query("""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
            SELECT DISTINCT symbol FROM indicators_daily i, latest
            WHERE i.trade_date = latest.d
            ORDER BY symbol
        """)
        symbol_options = syms["symbol"].tolist()
    except Exception:
        symbol_options = []

    toolbar = ui.row().classes("w-full items-end gap-2 mp-toolbar")
    with toolbar:
        with ui.row().classes("gap-1 items-end flex-wrap"):
            state_sel = ui.select(strong_states, value=strong_states, multiple=True, label="States (strong only)").classes("w-64").props("dense use-chips")
            max_g = ui.number("Max Groups", value=60, min=10, max=300).classes("w-24").props("dense")
            run_btn = ui.button("Run / Refresh Strong Groups").classes("mp-primary").props("dense")
        right_box = ui.row().classes("gap-1 items-end ml-auto")

    ui.label("All table values (turnover 1d/1w/1m, returns, rank changes, etc.) are shown uniformly. Data for stocks is enriched at runtime from indicators_daily (turnover_cr, prev_close for 1d ret, delivery_pct) + deals + sector_rotation.").classes("mp-rule text-xs py-0 my-0")

    with ui.row().classes("gap-1 items-center text-xs mb-1"):
        ui.label("States:").classes("text-[var(--mp-muted)]")
        for s, c in [("Leading", "mp-state-leading"), ("Emerging", "mp-state-emerging"), ("Improving", "mp-state-improving")]:
            ui.label(s).classes(f"mp-badge {c}")

    groups_container = ui.column().classes("w-full")

    # Two selectable fields as requested: Focus Group (level) | Respective Sub Group (specific strong group within level)
    # When Focus Group = "Sector", sub-group lists relevant sectors with Leading/Emerging/Improving prioritized at the top.
    with ui.row().classes("gap-2 items-end mt-2"):
        focus_level = ui.select(
            ["Broad Sector", "Sector", "Broad Industry", "Industry"],
            value="Sector",
            label="Focus Group"
        ).classes("w-48").props("dense")
        focus_group = ui.select(
            {"": "(Run groups first)"},
            value="",
            label="Respective Sub Group",
            with_input=True
        ).classes("w-80").props("dense")
        load_btn = ui.button("Load Stocks").classes("mp-primary").props("dense")
        clear_focus_btn = ui.button("Clear Stocks").classes("mp-button text-xs").props("dense")

    stocks_container = ui.column().classes("w-full")

    # Comparison study
    ui.label("Comparison Study — Add stock to see peers (same Industry or Sector) + its ranking vs them (RS, Turnover, 1M Return, composite). Multiple adds accumulate summaries.").classes("mp-section-title mt-3")
    with ui.row().classes("gap-2 items-end"):
        sym_select = ui.select(
            options=symbol_options,
            with_input=True,
            label="Symbol",
            value=None,
            clearable=True,
            new_value_mode="add"
        ).classes("w-40").props("dense")
        add_btn = ui.button("Add & Analyze Peers/Rank").classes("mp-primary").props("dense")
        clear_comp_btn = ui.button("Clear All Comparisons").classes("mp-button text-xs").props("dense")
    compare_container = ui.column().classes("w-full")
    compared_syms = []
    strong_groups = {'df': pd.DataFrame()}  # container for current strong groups data (client-side filtering for selects)

    def update_sub_group_options():
        """Populate the Respective Sub Group dropdown for the selected Focus Group (level).
        Strong states (Leading/Emerging/Improving) are sorted to the top of the list.
        Matches the request: when Focus Group=SECTOR, show relevant sectors with strong ones at the top.

        Using dict format for options (key = value, value = display label) to avoid "[object Object]" display issues.
        """
        if strong_groups['df'].empty:
            focus_group.options = {"": "(no groups)"}
            focus_group.value = ""
            return
        lvl = focus_level.value
        sub_df = strong_groups['df'][strong_groups['df']['level'] == lvl].copy()
        if sub_df.empty:
            focus_group.options = {"": "(no strong groups in this level)"}
            focus_group.value = ""
            return

        # Sort so Leading, Emerging, Improving come first (at the top), then others by name
        state_priority = {'Leading': 0, 'Emerging': 1, 'Improving': 2}
        sub_df['priority'] = sub_df['rotation_state'].map(state_priority).fillna(99)
        sub_df = sub_df.sort_values(['priority', 'group_name'])

        options = {}
        for _, r in sub_df.iterrows():
            label = f"{r['group_name']} [{r['rotation_state']}]"
            options[r['group_name']] = label   # key = internal value (group_name), value = nice label for display

        focus_group.options = options
        if options:
            focus_group.value = next(iter(options.keys()))  # first key after sort (strongest first)

    def render_groups():
        groups_container.clear()
        right_box.clear()
        with groups_container:
            ui.spinner()
            ui.label("Loading...").classes("text-xs text-[var(--mp-muted)]")
        sts = state_sel.value or strong_states
        ph = ", ".join(["?"] * len(sts))
        gdf = df_query(f"""
            WITH latest AS (SELECT max(trade_date) d FROM sector_rotation)
            SELECT level, group_name, rotation_state, stocks,
                   return_5d_pct, return_1m_pct, rs_percentile,
                   rank_change_5d, rank_change_20d,
                   turnover_1d_cr, turnover_5d_cr as turnover_1w_cr, turnover_20d_cr as turnover_1m_cr
            FROM sector_rotation, latest
            WHERE trade_date = latest.d AND rotation_state IN ({ph})
            ORDER BY rotation_score DESC NULLS LAST, stocks DESC
            LIMIT ?
        """, [*sts, int(max_g.value or 60)])

        with groups_container:
            table_from_df(gdf, "Strong Groups (Leading/Emerging/Improving) — All Levels", copy_symbols=False, pagination=8)

        strong_groups['df'] = gdf

        # Initialize / refresh the two selectable fields
        if focus_level.value is None:
            focus_level.value = "Sector"
        update_sub_group_options()

        with right_box:
            with ui.row().classes("gap-1 items-center pl-3 border-l border-[var(--mp-border)]"):
                compact_kpi("Strong Groups", len(gdf))
                if not gdf.empty:
                    copy_button("Copy Visible Symbols (from stocks below)", lambda: "Use stocks table copy after loading a group")  # groups are not symbols; stocks copy is in the table below

    def _get_delivery_trend_5d(syms: list[str]) -> dict:
        if not syms:
            return {}
        clause = ",".join([f"'{s}'" for s in syms])
        tdf = df_query(f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
            SELECT symbol, trade_date, ROUND(delivery_pct, 1) AS dp
            FROM indicators_daily, latest
            WHERE symbol IN ({clause}) AND trade_date >= latest.d - INTERVAL '6 DAY'
            ORDER BY symbol, trade_date DESC
        """)
        if tdf.empty:
            return {}
        out = {}
        for s in syms:
            vals = tdf[tdf["symbol"] == s].head(5)["dp"].tolist()
            out[s] = ">".join(str(v) for v in vals) if vals else "—"
        return out

    def load_stocks():
        stocks_container.clear()
        lvl = focus_level.value
        gname = focus_group.value
        if not gname or gname in ("(choose one)", "(no groups)", "(Run groups first)", "(no strong groups in this level)"):
            with stocks_container:
                ui.label("Select Focus Group and Respective Sub Group above, then click Load Stocks. The table will have TURNOVER D/W/M | Return D/W/M | Delivery Trend 5D | % away 52wk + refined fields (RS, VCP, deals, rank within group).").classes("text-[var(--mp-muted)] text-sm")
            return

        level_col = {"Broad Sector": "broad_sector", "Sector": "sector", "Broad Industry": "broad_industry", "Industry": "industry"}.get(lvl, "sector")

        with stocks_container:
            ui.spinner()
            ui.label("Loading stocks + enrichments...").classes("text-xs text-[var(--mp-muted)]")

        base = df_query(f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
            deal_sum AS (
                SELECT symbol,
                       SUM(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_deal_cr,
                       SUM(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) AS sell_deal_cr
                FROM deals
                WHERE trade_date >= (SELECT d FROM latest) - INTERVAL 20 DAY
                GROUP BY symbol
            )
            SELECT i.symbol, i.close_price, i.prev_close, i.turnover_cr, i.delivery_pct,
                   i.return_5d_pct, i.return_1m_pct,
                   i.rs_percentile, i.vcp_state, i.vcp_score,
                   i.ema_stack_bullish, i.away_10ema_pct, i.away_52w_high_pct,
                   m.market_cap_cr, m.sector, m.industry,
                   COALESCE(d.buy_deal_cr, 0) AS buy_deal_cr
            FROM indicators_daily i
            JOIN stocks_master m USING(symbol)
            LEFT JOIN deal_sum d USING(symbol), latest
            WHERE i.trade_date = latest.d AND m.{level_col} = ?
              AND coalesce(m.market_cap_cr, 0) >= 300
            ORDER BY i.rs_percentile DESC NULLS LAST
            LIMIT 120
        """, [gname])

        if base.empty:
            with stocks_container:
                ui.label(f"No qualifying stocks for {lvl}: {gname} on latest day.")
            return

        syms = base["symbol"].dropna().unique().tolist()
        sym_clause = ",".join([f"'{s}'" for s in syms])

        # W/M turnover (exact pattern from momentum enrich)
        recent = df_query(f"""
            SELECT symbol,
                   SUM(turnover_cr) FILTER (WHERE trade_date >= (SELECT MAX(trade_date) FROM indicators_daily) - INTERVAL 5 DAY) AS turnover_1w_cr,
                   SUM(turnover_cr) FILTER (WHERE trade_date >= (SELECT MAX(trade_date) FROM indicators_daily) - INTERVAL 21 DAY) AS turnover_1m_cr
            FROM indicators_daily
            WHERE symbol IN ({sym_clause})
            GROUP BY symbol
        """)
        if not recent.empty:
            base = base.merge(recent[["symbol", "turnover_1w_cr", "turnover_1m_cr"]], on="symbol", how="left")
        base = base.fillna({"turnover_1w_cr": 0.0, "turnover_1m_cr": 0.0})

        # Return D (derive from prev_close which is always present)
        base["return_1d_pct"] = ((base["close_price"] / base["prev_close"].replace({0: None})) - 1) * 100
        base["return_1d_pct"] = base["return_1d_pct"].fillna(0).round(2)

        # Delivery Trend last 5 days (formatted string for table)
        trends = _get_delivery_trend_5d(syms)
        base["delivery_trend_5d"] = base["symbol"].map(trends).fillna("—")

        # Within-group rank (by RS)
        base = base.sort_values("rs_percentile", ascending=False).reset_index(drop=True)
        base["rank_in_group"] = range(1, len(base) + 1)

        # Display cols (exact requested + refined)
        cols = ["symbol", "turnover_cr", "turnover_1w_cr", "turnover_1m_cr",
                "return_1d_pct", "return_5d_pct", "return_1m_pct",
                "delivery_trend_5d", "away_52w_high_pct",
                "rs_percentile", "vcp_state", "buy_deal_cr", "rank_in_group", "market_cap_cr", "ema_stack_bullish"]
        cols = [c for c in cols if c in base.columns]

        with stocks_container:
            table_from_df(base[cols], f"Stocks — {lvl}: {gname}  |  TURNOVER D/W/M | Return D/W/M | Deliv Trend 5D | % away 52wk + RS/VCP/Deal/Rank context", pagination=18)

            # Same ###Group,NSE: format as Momentum bucket/sector copies for easy TV paste and tracking
            with ui.row().classes("gap-2 mt-1 flex-wrap"):
                sym_list = [f"NSE:{tradingview_symbol(s)}" for s in base["symbol"].unique()]
                copy_tv = f"###{gname}," + ",".join(sym_list) if sym_list else ""
                ui.button(f"Copy {gname} (TV format)", on_click=lambda c=copy_tv: copy_text_to_clipboard(f"{lvl} {gname}", c)).classes("mp-button")

    def do_analyze(raw_sym: str):
        compare_container.clear()
        sym = (raw_sym or "").upper().strip()
        if not sym:
            with compare_container:
                ui.label("Enter a valid symbol.")
            return

        # stock + hierarchy + its group state (prefer industry)
        srow = df_query(f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
            SELECT i.symbol, i.rs_percentile, i.turnover_cr, i.return_1m_pct, i.away_52w_high_pct,
                   m.broad_sector, m.sector, m.broad_industry, m.industry, m.market_cap_cr
            FROM indicators_daily i JOIN stocks_master m USING(symbol), latest
            WHERE i.trade_date = latest.d AND i.symbol = ?
            LIMIT 1
        """, [sym])
        if srow.empty:
            with compare_container:
                ui.label(f"{sym} not in latest indicators.")
            return
        sr = srow.iloc[0].to_dict()

        prim_col = "industry" if sr.get("industry") else "sector"
        prim_val = sr.get("industry") or sr.get("sector") or "Unknown"
        grp_st = "—"
        if prim_val != "Unknown":
            gst = df_query(f"""
                WITH latest AS (SELECT max(trade_date) d FROM sector_rotation)
                SELECT rotation_state FROM sector_rotation, latest
                WHERE trade_date=latest.d AND level = ? AND group_name = ?
                LIMIT 1
            """, [prim_col.title().replace("Broad ", "Broad "), prim_val])  # best effort level
            if not gst.empty:
                grp_st = gst.iloc[0]["rotation_state"]

        # peers (same prim level)
        peers = df_query(f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
            deal_sum AS (
                SELECT symbol, SUM(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_deal_cr
                FROM deals WHERE trade_date >= (SELECT d FROM latest) - INTERVAL 20 DAY GROUP BY symbol
            )
            SELECT i.symbol, i.rs_percentile, i.turnover_cr, i.return_1m_pct, i.delivery_pct, i.away_52w_high_pct,
                   COALESCE(d.buy_deal_cr, 0) AS buy_deal_cr, m.market_cap_cr
            FROM indicators_daily i
            JOIN stocks_master m USING(symbol)
            LEFT JOIN deal_sum d USING(symbol), latest
            WHERE i.trade_date = latest.d AND m.{prim_col} = ? AND coalesce(m.market_cap_cr,0) >= 300
            ORDER BY i.rs_percentile DESC NULLS LAST
            LIMIT 100
        """, [prim_val])

        n_peers = len(peers)
        if n_peers == 0:
            with compare_container:
                ui.label("No peers.")
            return

        peers = peers.copy()
        peers["rank_rs"] = peers["rs_percentile"].rank(ascending=False, method="min").astype(int)
        peers["rank_to"] = peers["turnover_cr"].rank(ascending=False, method="min").astype(int)
        peers["rank_ret"] = peers["return_1m_pct"].rank(ascending=False, method="min").astype(int)
        # simple composite
        peers["comp"] = (peers["rs_percentile"].fillna(0) * 0.45 +
                         peers["turnover_cr"].fillna(0).rank(pct=True) * 100 * 0.25 +
                         peers["return_1m_pct"].fillna(0).clip(-25, 40).rank(pct=True) * 100 * 0.3).round(1)
        peers["rank_comp"] = peers["comp"].rank(ascending=False, method="min").astype(int)

        myr = peers[peers["symbol"] == sym]
        rtxt = ""
        if not myr.empty:
            rtxt = f" ranks #{int(myr['rank_comp'].iloc[0])}/{n_peers} composite (RS #{int(myr['rank_rs'].iloc[0])}, TO #{int(myr['rank_to'].iloc[0])}, 1M Ret #{int(myr['rank_ret'].iloc[0])})"

        summary = f"{sym} — {prim_col.title()}: {prim_val} (current group state: {grp_st}){rtxt}."

        if sym not in compared_syms:
            compared_syms.append(sym)

        with compare_container:
            ui.label(summary).classes("text-sm mb-1")
            # show peers table (first 30)
            show_cols = ["symbol", "rs_percentile", "turnover_cr", "return_1m_pct", "delivery_pct", "away_52w_high_pct", "buy_deal_cr", "rank_rs", "rank_comp"]
            table_from_df(peers[[c for c in show_cols if c in peers.columns]].head(30), f"Peers in {prim_val} (top 30 by RS; ranks computed)", pagination=10)

    def clear_comp():
        compare_container.clear()
        compared_syms.clear()

    # wire
    run_btn.on_click(render_groups)
    load_btn.on_click(load_stocks)
    clear_focus_btn.on_click(lambda: (stocks_container.clear(), setattr(focus_group, 'value', "")))

    # When Focus Group (level) changes, refresh the Respective Sub Group options (strong ones for that level, sorted with Leading/Emerging/Improving at top)
    focus_level.on_value_change(lambda e: update_sub_group_options())

    add_btn.on_click(lambda: do_analyze(sym_select.value))
    clear_comp_btn.on_click(clear_comp)

    # boot - render_groups will set initial values and call update_sub_group_options
    render_groups()


def strong_rs_stocks_page() -> None:
    section_header("Strong RS Stocks", "A ranked next-day focus list. Expand a group to see the stocks that deserve preparation.")

    with ui.row().classes("w-full items-end gap-2 mp-toolbar"):
        min_mcap = ui.number("Min MCap Cr", value=1000, min=0, max=10000).classes("w-32").props("dense")
        min_rs = ui.number("Min RS", value=80, min=0, max=100).classes("w-24").props("dense")
        rows = ui.number("Rows", value=80, min=25, max=250).classes("w-24").props("dense")
        group_by = ui.select(["Broad Industry", "Industry", "Sector"], value="Broad Industry", label="Group By").classes("w-44").props("dense")
        run_btn = ui.button("Run Focus List").classes("mp-primary").props("dense")
        right_box = ui.row().classes("gap-1 items-end ml-auto")

    container = ui.column().classes("w-full")

    def query_focus() -> pd.DataFrame:
        return df_query(
            """
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
            deal_sum AS (
                SELECT symbol,
                       SUM(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_deal_cr,
                       SUM(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) AS sell_deal_cr
                FROM deals, latest
                WHERE trade_date >= latest.d - INTERVAL 20 DAY
                GROUP BY symbol
            ),
            turnover AS (
                SELECT symbol,
                       SUM(turnover_cr) FILTER (WHERE trade_date >= latest.d - INTERVAL 5 DAY) AS turnover_1w_cr,
                       SUM(turnover_cr) FILTER (WHERE trade_date >= latest.d - INTERVAL 21 DAY) AS turnover_1m_cr
                FROM indicators_daily, latest
                GROUP BY symbol
            ),
            latest_rows AS (
                SELECT i.symbol, i.close_price, m.market_cap_cr,
                       m.sector, m.broad_industry, m.industry,
                       i.rs_percentile, i.return_5d_pct, i.return_1m_pct,
                       (i.close_price / NULLIF(i.prev_close, 0) - 1) * 100 AS return_1d_pct,
                       i.turnover_cr, coalesce(t.turnover_1w_cr, 0) AS turnover_1w_cr,
                       coalesce(t.turnover_1m_cr, 0) AS turnover_1m_cr,
                       i.delivery_pct, i.vcp_score, i.vcp_state,
                       i.away_52w_high_pct, i.away_10ema_pct,
                       i.ema_stack_bullish,
                       coalesce(d.buy_deal_cr, 0) AS buy_deal_cr,
                       coalesce(d.sell_deal_cr, 0) AS sell_deal_cr,
                       sr.rotation_state AS industry_state,
                       (
                           coalesce(i.rs_percentile, 0) * 0.40
                           + coalesce(i.vcp_score, 0) * 0.25
                           + coalesce(i.return_1m_pct, 0) * 0.45
                           + CASE WHEN i.away_52w_high_pct BETWEEN -10 AND 5 THEN 8 ELSE 0 END
                           + CASE WHEN i.ema_stack_bullish THEN 6 ELSE 0 END
                           + LEAST(coalesce(d.buy_deal_cr, 0), 25) * 0.8
                           + CASE sr.rotation_state WHEN 'Leading' THEN 8 WHEN 'Emerging' THEN 7 WHEN 'Improving' THEN 5 ELSE 0 END
                       ) AS focus_score
                FROM indicators_daily i
                JOIN stocks_master m USING(symbol)
                LEFT JOIN deal_sum d USING(symbol)
                LEFT JOIN turnover t USING(symbol)
                LEFT JOIN sector_rotation sr ON sr.trade_date = (SELECT d FROM latest)
                    AND sr.level = 'Industry' AND sr.group_name = m.industry, latest
                WHERE i.trade_date = latest.d
                  AND coalesce(m.market_cap_cr, 0) >= ?
                  AND coalesce(i.rs_percentile, 0) >= ?
                  AND (i.ema_200 IS NULL OR i.close_price > i.ema_200)
            )
            SELECT * FROM latest_rows
            ORDER BY focus_score DESC NULLS LAST, rs_percentile DESC NULLS LAST
            LIMIT ?
            """,
            [float(min_mcap.value or 0), float(min_rs.value or 80), int(rows.value or 80)],
        )

    def render() -> None:
        container.clear()
        right_box.clear()
        data = query_focus()
        with right_box:
            compact_kpi("Stocks", len(data))
            if not data.empty:
                compact_kpi("Top", data.iloc[0]["symbol"])
                copy_button("Copy Focus", lambda: symbols_text(data))
        with container:
            if data.empty:
                ui.label("No stocks match the current focus filters.").classes("text-[var(--mp-muted)]")
                return
            main_cols = [
                "symbol", "focus_score", "rs_percentile", "return_1d_pct", "return_5d_pct", "return_1m_pct",
                "vcp_score", "vcp_state", "turnover_cr", "delivery_pct", "buy_deal_cr", "away_52w_high_pct",
                "industry_state", "market_cap_cr", "sector", "broad_industry", "industry",
            ]
            table_from_df(data[[c for c in main_cols if c in data.columns]].head(40), "Next-Day Focus List", pagination=20)
            group_col = level_column(group_by.value)
            summary = data.groupby(group_col, dropna=False).agg(
                stocks=("symbol", "nunique"),
                avg_focus=("focus_score", "mean"),
                avg_rs=("rs_percentile", "mean"),
                turnover_1d_cr=("turnover_cr", "sum"),
                buy_deal_cr=("buy_deal_cr", "sum"),
            ).reset_index().sort_values(["avg_focus", "stocks"], ascending=[False, False])
            ui.label("Expandable groups").classes("mp-section-title")
            table_from_df(summary.rename(columns={group_col: "group_name"}), "Group Summary", copy_symbols=False, pagination=10)
            for _, row in summary.head(20).iterrows():
                gname = str(row[group_col])
                with ui.expansion(f"{gname} | stocks {int(row['stocks'])} | avg focus {float(row['avg_focus']):.1f}", icon="add").classes("mp-expansion w-full"):
                    group_rows = data[data[group_col].astype(str) == gname].copy()
                    table_from_df(group_rows[[c for c in main_cols if c in group_rows.columns]].head(20), "", pagination=10)

    run_btn.on_click(render)
    render()


def screener_condition(selected: str, values: dict):
    if selected == "Near 10 WEMA":
        return "i.low_price >= i.wema_10 AND i.close_price >= i.wema_10 AND i.away_10wema_pct BETWEEN 0 AND ?", [values["max_away"]]
    if selected == "Near 10 MEMA":
        return "i.low_price >= i.mema_10 AND i.close_price >= i.mema_10 AND i.away_10mema_pct BETWEEN 0 AND ?", [values["max_away"]]
    if selected == "Near ATH / Loaded High":
        return "i.away_database_high_pct BETWEEN ? AND 0", [-abs(values["max_high"])]
    if selected == "10 EMA Cross 200 EMA - Today":
        return "i.ema_10_cross_200", []
    if selected == "10 WEMA Cross 200 WEMA - Today":
        return "i.wema_10_cross_200", []
    if selected == "10 MEMA Cross 200 MEMA - Today":
        return "i.mema_10_cross_200", []
    if selected == "Morning Star W":
        return "i.confirmed_morning_star_w", []
    if selected == "Morning Star M":
        return "i.confirmed_morning_star_m", []
    return "i.shakeout", []


def ma_cross_screener_sql(today_only: bool, cross_col: str, fast_col: str, slow_col: str) -> str:
    date_filter = "t.trade_date = (SELECT d FROM latest)" if today_only else "t.trade_date IN (SELECT trade_date FROM recent_dates)"
    cross_filter = indicator_expr("t", cross_col, "false")
    trigger_fast = indicator_expr("t", fast_col)
    trigger_slow = indicator_expr("t", slow_col)
    latest_fast = indicator_expr("i", fast_col)
    latest_slow = indicator_expr("i", slow_col)
    away_52w_low = indicator_expr("i", "away_52w_low_pct")
    return f"""
    WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
    recent_dates AS (
        SELECT DISTINCT trade_date
        FROM indicators_daily
        ORDER BY trade_date DESC
        LIMIT 10
    ),
    trigger_rows AS (
        SELECT t.symbol, t.trade_date AS trigger_date, t.close_price AS trigger_close,
               {trigger_fast} AS trigger_fast_ma, {trigger_slow} AS trigger_slow_ma
        FROM indicators_daily t
        WHERE {cross_filter} AND {date_filter}
    ),
    latest_rows AS (
        SELECT i.symbol, i.trade_date, i.close_price,
               {latest_fast} AS fast_ma, {latest_slow} AS slow_ma, i.market_cap_cr,
               i.band, i.volume, i.avg_volume_20d, i.away_10ema_pct, i.away_10wema_pct,
               i.away_10mema_pct, i.away_52w_high_pct, {away_52w_low} AS away_52w_low_pct,
               i.away_database_high_pct, i.rvol, i.rs_percentile, i.rsi_14, i.rsi_14_w, i.rsi_14_m,
               i.sector, i.industry, d.latest_buy_deal_value_cr, d.latest_sell_deal_value_cr
        FROM (
            SELECT i.*, m.market_cap_cr, m.band, m.sector, m.industry
            FROM indicators_daily i
            JOIN stocks_master m USING(symbol), latest
            WHERE i.trade_date = latest.d
        ) i
        LEFT JOIN (
            SELECT symbol,
                   sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) latest_buy_deal_value_cr,
                   sum(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) latest_sell_deal_value_cr
            FROM deals, latest
            WHERE trade_date >= latest.d - INTERVAL 20 DAY
            GROUP BY symbol
        ) d USING(symbol)
    )
    SELECT tr.trigger_date, tr.symbol, tr.trigger_close, tr.trigger_fast_ma, tr.trigger_slow_ma,
           lr.trade_date, lr.close_price, lr.fast_ma, lr.slow_ma, lr.market_cap_cr, lr.band,
           lr.volume, lr.avg_volume_20d, lr.away_10ema_pct, lr.away_10wema_pct, lr.away_10mema_pct,
           lr.away_52w_high_pct, lr.away_52w_low_pct,
           lr.away_database_high_pct, lr.rvol, lr.rs_percentile, lr.rsi_14, lr.rsi_14_w, lr.rsi_14_m,
           lr.latest_buy_deal_value_cr, lr.latest_sell_deal_value_cr, lr.sector, lr.industry
    FROM trigger_rows tr
    JOIN latest_rows lr USING(symbol)
    WHERE coalesce(lr.market_cap_cr, 0) >= ?
    ORDER BY tr.trigger_date DESC, lr.rs_percentile DESC NULLS LAST
    """


def cross_screener_spec(selected: str) -> tuple[str, str, str] | None:
    if selected.startswith("10 EMA Cross 200 EMA"):
        return "ema_10_cross_200", "ema_10", "ema_200"
    if selected.startswith("10 WEMA Cross 200 WEMA"):
        return "wema_10_cross_200", "wema_10", "wema_200"
    if selected.startswith("10 MEMA Cross 200 MEMA"):
        return "mema_10_cross_200", "mema_10", "mema_200"
    return None


def screener_base_sql(cond: str) -> str:
    return f"""
    WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
    deal_summary AS (
        SELECT symbol,
               sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) latest_buy_deal_value_cr,
               sum(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) latest_sell_deal_value_cr,
               max(repeated_client_count) repeated_client_count
        FROM deals
        WHERE trade_date >= (SELECT d FROM latest) - INTERVAL 20 DAY
        GROUP BY symbol
    ),
    universe AS (
        SELECT i.*, m.market_cap_cr, m.band, m.sector, m.industry,
               d.latest_buy_deal_value_cr, d.latest_sell_deal_value_cr, d.repeated_client_count
        FROM indicators_daily i
        JOIN stocks_master m USING(symbol)
        LEFT JOIN deal_summary d USING(symbol), latest
        WHERE i.trade_date = latest.d
    )
    SELECT * FROM universe i
    WHERE {cond}
      AND coalesce(i.market_cap_cr, 0) >= ?
    """


def screener_page() -> None:
    section_header("Screeners", "Focused setup list with MCap Cr >= 1000 always applied.")
    names = list(SCREENER_RULES.keys())

    # Cohesive full-width toolbar: left = filters + run, right = compact KPIs + integrated COPY action
    toolbar = ui.row().classes("w-full items-end gap-2 mp-toolbar")
    with toolbar:
        with ui.row().classes("gap-1 items-end flex-wrap"):
            selected = ui.select(names, value="10 EMA Cross 200 EMA - Last 10 Days", label="Screener").classes("w-64").props("dense")
            min_rs = ui.number("Min RS %", value=0).classes("w-24").props("dense")
            min_avg_volume = ui.number("Min 20D Avg Vol", value=1_000_000).classes("w-36").props("dense")
            max_away = ui.number("Max EMA %", value=5).classes("w-28").props("dense")
            max_high = ui.number("Max High %", value=10).classes("w-28").props("dense")
            max_rows = ui.number("Rows", value=200).classes("w-20").props("dense")
            run_btn = ui.button("Run Screener", on_click=lambda: render()).classes("mp-primary").props("dense")

        right_box = ui.row().classes("gap-1 items-end ml-auto")

    # Ultra-compact rule (updated in render)
    rule_label = ui.label("").classes("mp-rule text-xs py-0 my-0")

    container = ui.column().classes("w-full")

    def sync_filters() -> None:
        screener = selected.value
        max_away.visible = screener in {"Near 10 WEMA", "Near 10 MEMA"}
        max_high.visible = screener == "Near ATH / Loaded High"
        min_rs.visible = screener == "Shakeout"
        min_avg_volume.visible = screener == "Shakeout"

    def render() -> None:
        sync_filters()
        container.clear()
        with container:
            ui.spinner()
            ui.label("Loading...").classes("text-xs text-[var(--mp-muted)]")
        right_box.clear()

        values = {
            "min_rs": float(min_rs.value or 0),
            "max_away": float(max_away.value or 0),
            "max_high": float(max_high.value or 0),
        }
        cond, params = screener_condition(selected.value, values)
        rule_label.text = f"Rule: {SCREENER_RULES.get(selected.value, '')}"
        if selected.value.endswith("Last 10 Days"):
            rule_label.text += " (Last 10 Days = last 10 trading sessions)"
        rule_label.text += "  |  BAND = price band code (lower = tighter daily limit, '—' = no band)"

        extra = ""
        extra_params = []
        cross_spec = cross_screener_spec(selected.value)
        if cross_spec:
            cross_col, fast_col, slow_col = cross_spec
            data = df_query(
                ma_cross_screener_sql(selected.value.endswith("Today"), cross_col, fast_col, slow_col) + " LIMIT ?",
                [1000, int(max_rows.value or 200)],
            )
        elif selected.value == "Shakeout":
            extra = " AND coalesce(i.rs_percentile, 0) >= ? AND coalesce(i.avg_volume_20d, 0) >= ?"
            extra_params = [float(min_rs.value or 0), float(min_avg_volume.value or 0)]
            data = df_query(
                screener_base_sql(cond)
                + extra
                + """
                ORDER BY rs_percentile DESC NULLS LAST, rvol DESC NULLS LAST
                LIMIT ?
                """,
                [*params, 1000, *extra_params, int(max_rows.value or 200)],
            )
            data.insert(0, "trigger_date", data["trade_date"] if "trade_date" in data.columns else "")
        else:
            data = df_query(
                screener_base_sql(cond)
                + """
                ORDER BY rs_percentile DESC NULLS LAST, rvol DESC NULLS LAST
                LIMIT ?
                """,
                [*params, 1000, int(max_rows.value or 200)],
            )
            data.insert(0, "trigger_date", data["trade_date"] if "trade_date" in data.columns else "")

        total = df_query("WITH latest AS (SELECT max(trade_date) d FROM indicators_daily) SELECT count(*) AS c FROM indicators_daily, latest WHERE trade_date = d")["c"].iloc[0]
        after_mcap = df_query("WITH latest AS (SELECT max(trade_date) d FROM indicators_daily) SELECT count(*) AS c FROM indicators_daily i JOIN stocks_master m USING(symbol), latest WHERE i.trade_date=d AND coalesce(m.market_cap_cr,0) >= 1000")["c"].iloc[0]

        # Right side: compact KPIs + the per-screener COPY (no longer stranded on left under void)
        with right_box:
            compact_kpi("Universe", int(total))
            compact_kpi("MCap>=1000", int(after_mcap))
            compact_kpi("Final", len(data))
            # Integrated COPY for the current screener results (moved here per density request)
            if not data.empty:
                copy_button("Copy Symbols", lambda: symbols_text(data))

        cols = [
            "trigger_date", "symbol", "trigger_close", "trigger_fast_ma", "trigger_slow_ma",
            # removed duplicate latest date/close/ma to reduce column bloat (trigger provides the cross event info)
            "ema_10", "ema_200", "wema_10", "wema_200", "mema_10", "mema_200",
            "market_cap_cr", "band", "volume", "avg_volume_20d",
            "away_10ema_pct", "away_10wema_pct", "away_10mema_pct", "away_52w_high_pct",
            "away_52w_low_pct", "away_database_high_pct", "rvol", "rs_percentile", "rsi_14", "rsi_14_w", "rsi_14_m",
            "latest_buy_deal_value_cr", "latest_sell_deal_value_cr", "sector", "industry",
        ]
        with container:
            with ui.element('div').classes('w-full overflow-x-auto'):
                table_from_df(data[[c for c in cols if c in data.columns]], selected.value)

    for ctrl in [selected, min_rs, min_avg_volume, max_away, max_high, max_rows]:
        ctrl.on_value_change(render)
    sync_filters()
    render()


def vcp_lab_page() -> None:
    section_header("VCP Lab", "Explainable setup ranking: trend, contraction, volume dry-up, and pivot proximity.")
    min_score = ui.number("Min VCP Score", value=70).classes("w-48")
    max_high = ui.number("Max % Away from High", value=10).classes("w-56")
    min_rs = ui.number("Min RS Percentile", value=60).classes("w-48")
    state = ui.select(["All", "Near Pivot", "Building Base", "Breakout", "Failed Breakout"], value="All", label="VCP State").classes("w-52")
    container = ui.column().classes("w-full")

    def render() -> None:
        container.clear()
        where = ["i.vcp_score >= ?", "i.distance_to_high_pct <= ?", "i.rs_percentile >= ?"]
        params = [float(min_score.value), float(max_high.value), float(min_rs.value)]
        if state.value != "All":
            where.append("i.vcp_state = ?")
            params.append(state.value)
        data = df_query(
            f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
            SELECT i.symbol, i.trade_date, i.close_price, i.vcp_state, i.vcp_score, i.trend_score,
                   i.contraction_score, i.volume_dryup_score, i.volume_dryup_pct,
                   i.pivot_proximity_score, i.distance_to_high_pct, i.range_5d_pct,
                   i.range_10d_pct, i.range_20d_pct, i.atr_pct, i.rvol, i.rs_percentile,
                   m.market_cap_cr, m.sector, m.industry
            FROM indicators_daily i
            JOIN stocks_master m USING(symbol), latest
            WHERE i.trade_date = latest.d AND {' AND '.join(where)}
            ORDER BY i.vcp_score DESC, i.distance_to_high_pct
            LIMIT 300
            """,
            params,
        )
        with container:
            table_from_df(data, "VCP Candidate Ranking")

    for ctrl in [min_score, max_high, min_rs, state]:
        ctrl.on_value_change(render)
    render()


def special_watchlist_page() -> None:
    section_header("Momentum Scanner", "Trend-template watchlist with bucket changes, top sector/industry focus, and TradingView copy.")
    with ui.row().classes("gap-3 items-end flex-wrap"):
        lookback = ui.select([1, 3, 5, 10, 20, 30], value=SPECIAL_SCREENER_DEFAULTS["lookback_days"], label="Lookback").classes("w-32")
        min_mcap = ui.number("Min MCap Cr", value=SPECIAL_SCREENER_DEFAULTS["min_market_cap_cr"]).classes("w-36")
        with ui.row().classes("items-center gap-1"):
            check_min_vol = ui.checkbox("Min Day Vol", value=False)
            min_volume = ui.number(value=SPECIAL_SCREENER_DEFAULTS["min_volume"]).classes("w-28")
        with ui.row().classes("items-center gap-1"):
            check_avg_vol = ui.checkbox("Min 20D Avg", value=True)
            min_avg_volume = ui.number(value=SPECIAL_SCREENER_DEFAULTS["min_avg_volume_20d"]).classes("w-28")
        max_52w = ui.number("Max 52W Away %", value=25).classes("w-40")
        min_52w_low = ui.number("Min Above 52W Low %", value=SPECIAL_SCREENER_DEFAULTS["min_52w_low_pct"]).classes("w-48")
        debug_symbol = ui.input("Debug Symbol", placeholder="e.g. RELIANCE (tests filter pass/fail)").classes("w-40").props("clearable dense")
        run_button = ui.button("Run Scanner").classes("mp-primary")
    with ui.row().classes("gap-3 items-center flex-wrap"):
        ui.label("Price vs EMA:").classes("text-xs text-[var(--mp-muted)]")
        cmp_gt_10 = ui.checkbox("CMP > 10 EMA", value=True)
        cmp_gt_200 = ui.checkbox("CMP > 200 EMA", value=True)
    with ui.row().classes("gap-3 items-center flex-wrap"):
        ui.label("OHLC vs EMA:").classes("text-xs text-[var(--mp-muted)]")
        ohlc_gt_10 = ui.checkbox("OHLC > 10 EMA", value=False)
        ohlc_gt_20 = ui.checkbox("OHLC > 20 EMA", value=False)
    with ui.row().classes("gap-3 items-center flex-wrap"):
        ui.label("EMA Stack (bullish):").classes("text-xs text-[var(--mp-muted)]")
        ema10_gt_20 = ui.checkbox("10 > 20", value=True)
        ema20_gt_50 = ui.checkbox("20 > 50", value=True)
        ema50_gt_100 = ui.checkbox("50 > 100", value=True)
        ema100_gt_200 = ui.checkbox("100 > 200", value=True)
    # Tighter summary using compact KPIs for density (consistent with new toolbar pattern)
    summary_row = ui.row().classes("gap-1 flex-wrap w-full")
    container = ui.column().classes("w-full")

    def safe_group_label(value: str) -> str:
        text = str(value or "Unknown").replace("&amp;", "&").replace("&", "And").strip()
        text = "".join(ch if ch.isalnum() else "_" for ch in text)
        while "__" in text:
            text = text.replace("__", "_")
        return text.strip("_") or "Unknown"

    def tradable_df(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        tradable = df.copy()
        if "is_avoid" in tradable.columns:
            tradable = tradable[~tradable["is_avoid"].fillna(False)]
        if "status" in tradable.columns:
            tradable = tradable[tradable["status"] != "Removed"]
        if {"close_price", "ema_200"}.issubset(tradable.columns):
            close = pd.to_numeric(tradable["close_price"], errors="coerce")
            ema_200 = pd.to_numeric(tradable["ema_200"], errors="coerce")
            tradable = tradable[ema_200.isna() | (close > ema_200)]
        if "market_cap_cr" in tradable.columns:
            tradable = tradable[pd.to_numeric(tradable["market_cap_cr"], errors="coerce").fillna(0) >= 1000]
        return tradable

    def bucket_copy_text(df: pd.DataFrame) -> str:
        df = tradable_df(df)
        parts = []
        for label, _, _ in WATCHLIST_BUCKETS:
            bucket = df[df["bucket"] == label]["symbol"].drop_duplicates().map(lambda s: f"NSE:{tradingview_symbol(s)}").tolist()
            if bucket:
                parts.append(f"###{label}," + ",".join(bucket))
        return ",".join(parts)

    def grouped_copy_text(df: pd.DataFrame, group_cols: list[str], restrict_values: set[str] | None = None) -> str:
        df = tradable_df(df)
        if restrict_values is not None and group_cols:
            df = df[df[group_cols[-1]].isin(restrict_values)]
        parts = []
        if df.empty:
            return ""
        grouped = df.groupby(group_cols, dropna=False)
        ordered = sorted(grouped, key=lambda item: item[1]["symbol"].nunique(), reverse=True)
        for keys, group in ordered:
            if not isinstance(keys, tuple):
                keys = (keys,)
            label = safe_group_label(keys[-1])
            symbols = group["symbol"].drop_duplicates().map(lambda s: f"NSE:{tradingview_symbol(s)}").tolist()
            if symbols:
                parts.append(f"###{label}," + ",".join(symbols))
        return ",".join(parts)

    def grouped_summary(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
        rows = []
        df = tradable_df(df)
        if df.empty:
            return pd.DataFrame(columns=[*group_cols, "stock_count", "avg_10ema_pct", "avg_rs_pct", "avg_20d_vol", "turnover_1d_cr", "turnover_1w_cr", "turnover_1m_cr", "deal_count", "symbols"])
        has_1w = "turnover_1w_cr" in df.columns
        has_1m = "turnover_1m_cr" in df.columns
        for keys, group in df.groupby(group_cols, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            row = {col: key for col, key in zip(group_cols, keys)}
            row["stock_count"] = int(group["symbol"].nunique())
            row["avg_10ema_pct"] = group["away_10ema_pct"].mean()
            row["avg_rs_pct"] = group["rs_percentile"].mean()
            row["avg_20d_vol"] = group["avg_volume_20d"].mean()
            row["turnover_1d_cr"] = group["turnover_cr"].sum() if "turnover_cr" in group else 0
            row["turnover_1w_cr"] = group["turnover_1w_cr"].sum() if has_1w else 0
            row["turnover_1m_cr"] = group["turnover_1m_cr"].sum() if has_1m else 0
            row["deal_count"] = int(group["has_deal"].eq("Yes").sum()) if "has_deal" in group else 0
            row["symbols"] = ",".join(group["symbol"].drop_duplicates().map(lambda s: f"NSE:{tradingview_symbol(s)}").tolist())
            rows.append(row)
        out = pd.DataFrame(rows)
        return out.sort_values(["stock_count", "avg_rs_pct"], ascending=[False, False]) if not out.empty else out

    def ema_filters(alias: str, strict: bool = True) -> list[str]:
        filters = []
        if cmp_gt_10.value:
            filters.append(f"({alias}.ema_10 IS NULL OR {alias}.close_price > {alias}.ema_10)")
        if cmp_gt_200.value:
            filters.append(f"({alias}.ema_200 IS NULL OR {alias}.close_price > {alias}.ema_200)")
        if not strict:
            return filters
        if ohlc_gt_10.value:
            filters.append(f"({alias}.ema_10 IS NOT NULL AND {alias}.open_price > {alias}.ema_10 AND {alias}.high_price > {alias}.ema_10 AND {alias}.low_price > {alias}.ema_10 AND {alias}.close_price > {alias}.ema_10)")
        if ohlc_gt_20.value:
            filters.append(f"({alias}.ema_20 IS NOT NULL AND {alias}.open_price > {alias}.ema_20 AND {alias}.high_price > {alias}.ema_20 AND {alias}.low_price > {alias}.ema_20 AND {alias}.close_price > {alias}.ema_20)")
        if ema10_gt_20.value:
            filters.append(f"({alias}.ema_10 IS NULL OR {alias}.ema_20 IS NULL OR {alias}.ema_10 > {alias}.ema_20)")
        if ema20_gt_50.value:
            filters.append(f"({alias}.ema_20 IS NULL OR {alias}.ema_50 IS NULL OR {alias}.ema_20 > {alias}.ema_50)")
        if ema50_gt_100.value:
            filters.append(f"({alias}.ema_50 IS NULL OR {alias}.ema_100 IS NULL OR {alias}.ema_50 > {alias}.ema_100)")
        if ema100_gt_200.value:
            filters.append(f"({alias}.ema_100 IS NULL OR {alias}.ema_200 IS NULL OR {alias}.ema_100 > {alias}.ema_200)")
        return filters

    def trigger_liquidity_sql() -> str:
        return "i.volume >= ?" if check_min_vol.value else "true"
        
    def trigger_liquidity_params() -> list[float]:
        return [float(min_volume.value or 0)] if check_min_vol.value else []

    def current_liquidity_sql() -> str:
        return "c.avg_volume_20d >= ?" if check_avg_vol.value else "true"

    def current_liquidity_params() -> list[float]:
        return [float(min_avg_volume.value or 0)] if check_avg_vol.value else []

    def scanner_for(as_of_date) -> pd.DataFrame:
        trigger_filters = ema_filters("i", strict=True)
        current_filters = ema_filters("c", strict=False)

        # EMA stack filters (if enabled) must also apply on the *current* day.
        # Previously they were only in strict (trigger) path. This was causing stocks that no longer
        # satisfy e.g. 10>20>50 on the latest day to still appear in the scanner list.
        stack_current = []
        if ema10_gt_20.value:
            stack_current.append("(c.ema_10 IS NULL OR c.ema_20 IS NULL OR c.ema_10 > c.ema_20)")
        if ema20_gt_50.value:
            stack_current.append("(c.ema_20 IS NULL OR c.ema_50 IS NULL OR c.ema_20 > c.ema_50)")
        if ema50_gt_100.value:
            stack_current.append("(c.ema_50 IS NULL OR c.ema_100 IS NULL OR c.ema_50 > c.ema_100)")
        if ema100_gt_200.value:
            stack_current.append("(c.ema_100 IS NULL OR c.ema_200 IS NULL OR c.ema_100 > c.ema_200)")
        if stack_current:
            current_filters.extend(stack_current)

        trigger_sql = " AND ".join(trigger_filters) if trigger_filters else "true"
        current_sql = " AND ".join(current_filters) if current_filters else "true"
        trigger_52w_low = indicator_expr("i", "away_52w_low_pct")
        current_52w_low = indicator_expr("c", "away_52w_low_pct")
        trigger_52w_low_filter = indicator_expr("i", "away_52w_low_pct", "999")
        current_52w_low_filter = indicator_expr("c", "away_52w_low_pct", "999")
        return df_query(
            f"""
            WITH dates AS (
                SELECT DISTINCT trade_date FROM indicators_daily
                WHERE trade_date <= CAST(? AS DATE)
                ORDER BY trade_date DESC LIMIT ?
            ),
            deal_summary AS (
                SELECT symbol,
                       sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_deal_cr,
                       sum(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) AS sell_deal_cr
                FROM deals
                WHERE trade_date >= CAST(? AS DATE) - INTERVAL 20 DAY
                GROUP BY symbol
            ),
            trigger_hits AS (
                SELECT i.symbol, max(i.trade_date) AS trigger_date
                FROM indicators_daily i
                JOIN stocks_master m USING(symbol)
                WHERE i.trade_date IN (SELECT trade_date FROM dates)
                  AND coalesce(m.market_cap_cr, 0) >= ?
                  AND {trigger_liquidity_sql()}
                  AND i.away_52w_high_pct >= ?
                  AND coalesce({trigger_52w_low_filter}, 999) >= ?
                  AND {trigger_sql}
                GROUP BY i.symbol
            )
            SELECT c.symbol, trigger_hits.trigger_date, c.trade_date, c.close_price, m.market_cap_cr, c.turnover_cr, c.delivery_pct,
                   c.volume, c.avg_volume_20d, c.ema_10, c.ema_20, c.ema_50, c.ema_100, c.ema_200,
                   c.away_10ema_pct, c.away_52w_high_pct, {current_52w_low} AS away_52w_low_pct, c.rvol, c.rs_percentile, m.band,
                   coalesce(m.sector, 'Unknown') AS sector, coalesce(m.industry, 'Unknown') AS industry,
                   coalesce(d.buy_deal_cr, 0) AS buy_deal_cr, coalesce(d.sell_deal_cr, 0) AS sell_deal_cr,
                   CASE
                     WHEN c.away_10ema_pct >= 0 AND c.away_10ema_pct <= 2 THEN '0_2%'
                     WHEN c.away_10ema_pct > 2 AND c.away_10ema_pct <= 5 THEN '2_5%'
                     WHEN c.away_10ema_pct > 5 AND c.away_10ema_pct <= 10 THEN '5_10%'
                     WHEN c.away_10ema_pct > 10 THEN '10%+'
                   END AS bucket,
                   CASE WHEN coalesce(m.band, 100) <= 5 THEN true ELSE false END AS is_avoid
            FROM indicators_daily c
            JOIN trigger_hits USING(symbol)
            JOIN stocks_master m USING(symbol)
            LEFT JOIN deal_summary d USING(symbol)
            WHERE c.trade_date = CAST(? AS DATE)
              AND coalesce(m.market_cap_cr, 0) >= ?
              AND {current_liquidity_sql()}
              AND c.away_52w_high_pct >= ?
              AND coalesce({current_52w_low_filter}, 999) >= ?
              AND c.away_10ema_pct >= 0
              AND {current_sql}
            ORDER BY bucket, away_10ema_pct
            """,
            [
                as_of_date,
                int(lookback.value),
                as_of_date,
                float(min_mcap.value or 0),
                *trigger_liquidity_params(),
                -abs(float(max_52w.value or 0)),
                float(min_52w_low.value or 0),
                as_of_date,
                float(min_mcap.value or 0),
                *current_liquidity_params(),
                -abs(float(max_52w.value or 0)),
                float(min_52w_low.value or 0),
            ],
        )

    def run_symbol_debug(symbol_str: str) -> None:
        symbol_str = symbol_str.upper().strip()
        date_rows = df_query("SELECT DISTINCT trade_date FROM indicators_daily ORDER BY trade_date DESC LIMIT ? + 1", [int(lookback.value)])
        if date_rows.empty:
            with container: ui.label("No data").classes("text-red-500")
            return
        current_date = date_rows.iloc[0]["trade_date"]
        df = df_query(
            """
            SELECT i.*, m.market_cap_cr 
            FROM indicators_daily i 
            JOIN stocks_master m USING(symbol) 
            WHERE i.symbol = ? AND i.trade_date >= ? AND i.trade_date <= ?
            ORDER BY i.trade_date DESC
            """, 
            [symbol_str, date_rows.iloc[-1]["trade_date"], current_date]
        )
        with container:
            if df.empty:
                ui.label(f"No data for {symbol_str} in lookback window.").classes("text-red-500")
                return
            
            c_row = df.iloc[0]
            c_fails = []
            if c_row["market_cap_cr"] < float(min_mcap.value or 0): c_fails.append(f"MCap < {min_mcap.value}")
            if check_avg_vol.value and c_row["avg_volume_20d"] < float(min_avg_volume.value or 0): c_fails.append(f"Avg Vol < {min_avg_volume.value}")
            if c_row["away_52w_high_pct"] < -abs(float(max_52w.value or 0)): c_fails.append(f"Away 52W High < -{max_52w.value}")
            if c_row.get("away_52w_low_pct", 999) < float(min_52w_low.value or 0): c_fails.append(f"Away 52W Low < {min_52w_low.value}")
            if c_row["away_10ema_pct"] < 0: c_fails.append(f"Close Below 10 EMA")
            if cmp_gt_10.value and (pd.notna(c_row["ema_10"]) and c_row["close_price"] <= c_row["ema_10"]): c_fails.append("Close <= 10 EMA")
            if cmp_gt_200.value and (pd.notna(c_row["ema_200"]) and c_row["close_price"] <= c_row["ema_200"]): c_fails.append("Close <= 200 EMA")
            # Current day must also respect enabled EMA stack (same as trigger logic)
            if ema10_gt_20.value and (pd.notna(c_row.get("ema_10")) and pd.notna(c_row.get("ema_20")) and c_row["ema_10"] <= c_row["ema_20"]): c_fails.append("Current 10<=20")
            if ema20_gt_50.value and (pd.notna(c_row.get("ema_20")) and pd.notna(c_row.get("ema_50")) and c_row["ema_20"] <= c_row["ema_50"]): c_fails.append("Current 20<=50")
            if ema50_gt_100.value and (pd.notna(c_row.get("ema_50")) and pd.notna(c_row.get("ema_100")) and c_row["ema_50"] <= c_row["ema_100"]): c_fails.append("Current 50<=100")
            if ema100_gt_200.value and (pd.notna(c_row.get("ema_100")) and pd.notna(c_row.get("ema_200")) and c_row["ema_100"] <= c_row["ema_200"]): c_fails.append("Current 100<=200")
            
            trigger_found = False
            t_fails = []
            for _, t_row in df.iterrows():
                fails = []
                if t_row["market_cap_cr"] < float(min_mcap.value or 0): fails.append("MCap")
                if check_min_vol.value and t_row["volume"] < float(min_volume.value or 0): fails.append("Day Vol")
                if t_row["away_52w_high_pct"] < -abs(float(max_52w.value or 0)): fails.append("52W High")
                if t_row.get("away_52w_low_pct", 999) < float(min_52w_low.value or 0): fails.append("52W Low")
                if cmp_gt_10.value and (pd.notna(t_row["ema_10"]) and t_row["close_price"] <= t_row["ema_10"]): fails.append("Close<=10EMA")
                if cmp_gt_200.value and (pd.notna(t_row["ema_200"]) and t_row["close_price"] <= t_row["ema_200"]): fails.append("Close<=200EMA")
                if ohlc_gt_10.value and (pd.isna(t_row["ema_10"]) or t_row["open_price"] <= t_row["ema_10"] or t_row["low_price"] <= t_row["ema_10"]): fails.append("OHLC<=10EMA")
                if ohlc_gt_20.value and (pd.isna(t_row["ema_20"]) or t_row["open_price"] <= t_row["ema_20"] or t_row["low_price"] <= t_row["ema_20"]): fails.append("OHLC<=20EMA")
                if ema10_gt_20.value and (pd.notna(t_row["ema_10"]) and pd.notna(t_row["ema_20"]) and t_row["ema_10"] <= t_row["ema_20"]): fails.append("10<=20")
                if ema20_gt_50.value and (pd.notna(t_row["ema_20"]) and pd.notna(t_row["ema_50"]) and t_row["ema_20"] <= t_row["ema_50"]): fails.append("20<=50")
                if ema50_gt_100.value and (pd.notna(t_row["ema_50"]) and pd.notna(t_row["ema_100"]) and t_row["ema_50"] <= t_row["ema_100"]): fails.append("50<=100")
                if ema100_gt_200.value and (pd.notna(t_row["ema_100"]) and pd.notna(t_row["ema_200"]) and t_row["ema_100"] <= t_row["ema_200"]): fails.append("100<=200")
                
                if not fails:
                    trigger_found = True
                    break
                else:
                    t_fails.append(f"{t_row['trade_date'].strftime('%Y-%m-%d')}: {','.join(fails)}")
                    
            with ui.card().classes("w-full mp-card p-4 mb-4"):
                ui.label(f"Debug Output: {symbol_str}").classes("text-lg font-bold mb-2")
                ui.label("Filters: Price>EMA | OHLC>EMA | EMA Stack | Liquidity | 52W | MCap").classes("text-xs text-[var(--mp-muted)] mb-1")
                if trigger_found and not c_fails:
                    ui.label("✅ Symbol PASSES all filters and should be in the scanner.").classes("text-green-600 font-bold")
                else:
                    ui.label("❌ Symbol FAILED filters:").classes("text-red-600 font-bold")
                    if c_fails:
                        ui.label(f"Failed Current Day Rules: {', '.join(c_fails)}").classes("ml-4 text-red-500 font-semibold")
                    if not trigger_found:
                        ui.label("Failed Trigger Rules (No valid trigger day found in lookback):").classes("ml-4 text-red-500 font-semibold mt-2")
                        for f in t_fails[:5]:
                            ui.label(f"- {f}").classes("ml-8 text-sm text-[var(--mp-muted)]")

    def render() -> None:
        container.clear()
        with container:
            ui.spinner()
            ui.label("Loading...").classes("text-xs text-[var(--mp-muted)]")
        summary_row.clear()
        date_rows = df_query("SELECT DISTINCT trade_date FROM indicators_daily ORDER BY trade_date DESC LIMIT 2")
        if date_rows.empty:
            with container:
                ui.label("No indicator dates found.").classes("text-[var(--mp-muted)]")
            return
            
        if debug_symbol.value:
            run_symbol_debug(debug_symbol.value)
            
        current_date = date_rows.iloc[0]["trade_date"]
        previous_date = date_rows.iloc[1]["trade_date"] if len(date_rows) > 1 else None
        current = scanner_for(current_date)
        previous = scanner_for(previous_date) if previous_date is not None else pd.DataFrame(columns=current.columns)
        for frame in [current, previous]:
            if not frame.empty:
                frame["has_deal"] = ((pd.to_numeric(frame["buy_deal_cr"], errors="coerce").fillna(0) + pd.to_numeric(frame["sell_deal_cr"], errors="coerce").fillna(0)) > 0).map({True: "Yes", False: "No"})
        prev_buckets = previous[["symbol", "bucket"]].rename(columns={"bucket": "prev_bucket"}) if not previous.empty else pd.DataFrame(columns=["symbol", "prev_bucket"])
        data = current.merge(prev_buckets, on="symbol", how="left") if not current.empty else current.copy()
        if not data.empty:
            data["status"] = data.apply(lambda r: "Added" if pd.isna(r.get("prev_bucket")) else ("Stayed" if r.get("prev_bucket") == r.get("bucket") else "Bucket Changed"), axis=1)
        removed = pd.DataFrame()
        if not previous.empty:
            removed = previous[~previous["symbol"].isin(current["symbol"] if not current.empty else [])].copy()
            if not removed.empty:
                removed["prev_bucket"] = removed["bucket"]
                removed["bucket"] = ""
                removed["status"] = "Removed"
        combined = pd.concat([data, removed], ignore_index=True, sort=False) if not removed.empty else data.copy()
        tradable = tradable_df(data)

        # Optimized recent turnover enrichment (was causing slowness with repeated huge IN (...) literal lists)
        # Query once for all relevant symbols (fast aggregate), then pandas merge.
        relevant_syms = set()
        for fr in [current, previous, data, combined]:
            if not fr.empty and "symbol" in fr.columns:
                relevant_syms.update([s for s in fr["symbol"].dropna().unique().tolist() if s])
        recent_turnover = pd.DataFrame(columns=["symbol", "turnover_1w_cr", "turnover_1m_cr"])
        if relevant_syms:
            sym_clause = ",".join([f"'{s}'" for s in relevant_syms])
            recent_turnover = df_query(f"""
                SELECT symbol,
                       SUM(turnover_cr) FILTER (WHERE trade_date >= (SELECT MAX(trade_date) FROM indicators_daily) - INTERVAL 5 DAY) AS turnover_1w_cr,
                       SUM(turnover_cr) FILTER (WHERE trade_date >= (SELECT MAX(trade_date) FROM indicators_daily) - INTERVAL 21 DAY) AS turnover_1m_cr
                FROM indicators_daily
                WHERE symbol IN ({sym_clause})
                GROUP BY symbol
            """)
            recent_turnover = recent_turnover.fillna(0)

        def _enrich_recent_turnover(dfin: pd.DataFrame) -> pd.DataFrame:
            if dfin.empty or "symbol" not in dfin.columns or recent_turnover.empty:
                if not dfin.empty:
                    dfin["turnover_1w_cr"] = dfin.get("turnover_1w_cr", 0.0)
                    dfin["turnover_1m_cr"] = dfin.get("turnover_1m_cr", 0.0)
                return dfin
            out = dfin.merge(recent_turnover[["symbol", "turnover_1w_cr", "turnover_1m_cr"]], on="symbol", how="left")
            out["turnover_1w_cr"] = out["turnover_1w_cr"].fillna(0)
            out["turnover_1m_cr"] = out["turnover_1m_cr"].fillna(0)
            return out

        tradable = _enrich_recent_turnover(tradable)
        data = _enrich_recent_turnover(data) if not data.empty else data
        combined = _enrich_recent_turnover(combined) if not combined.empty else combined

        top_sectors = set(tradable.groupby("sector")["symbol"].nunique().sort_values(ascending=False).head(3).index.tolist()) if not tradable.empty else set()
        top_industries = set(tradable.groupby("industry")["symbol"].nunique().sort_values(ascending=False).head(3).index.tolist()) if not tradable.empty else set()
        if not combined.empty:
            combined["is_top_sector"] = combined["sector"].isin(top_sectors)
            combined["is_top_industry"] = combined["industry"].isin(top_industries)
        sector_summary = grouped_summary(tradable, ["sector"])
        industry_summary = grouped_summary(tradable, ["sector", "industry"])
        bucket_copy = bucket_copy_text(data)
        sector_copy = grouped_copy_text(data, ["sector"])
        industry_copy = grouped_copy_text(data, ["sector", "industry"])
        top_sector_text = ", ".join(sector_summary.head(3)["sector"].tolist()) if not sector_summary.empty else "-"
        top_industry_text = ", ".join(industry_summary.head(3)["industry"].tolist()) if not industry_summary.empty else "-"
        with summary_row:
            compact_kpi("Current", len(tradable))
            compact_kpi("Added", int((combined.get("status") == "Added").sum()) if not combined.empty else 0)
            compact_kpi("Removed", int((combined.get("status") == "Removed").sum()) if not combined.empty else 0)
            compact_kpi("Bucket Chg", int((combined.get("status") == "Bucket Changed").sum()) if not combined.empty else 0)
            compact_kpi("5% Avoid", int(current["is_avoid"].sum()) if not current.empty else 0)
            # Top sectors/industries stay as compact text labels (still useful context)
            ui.label(f"Top Sectors: {top_sector_text}").classes("text-xs text-[var(--mp-muted)]")
            ui.label(f"Top Ind: {top_industry_text}").classes("text-xs text-[var(--mp-muted)]")
        # Updated columns per feedback: drop status/prev_bucket/bucket/has_deal; surface turnover (today + 1w/1m) + delivery %
        table_cols = ["symbol", "close_price", "market_cap_cr", "band", "volume", "avg_volume_20d", "turnover_cr", "turnover_1w_cr", "turnover_1m_cr", "delivery_pct", "away_10ema_pct", "away_52w_high_pct", "away_52w_low_pct", "rs_percentile", "buy_deal_cr", "sell_deal_cr", "sector", "industry", "ema_200", "is_avoid", "is_top_sector", "is_top_industry"]
        table_data = combined[[c for c in table_cols if c in combined.columns]].copy() if not combined.empty else combined
        if not table_data.empty and "is_avoid" in table_data.columns:
            table_data = table_data[~table_data["is_avoid"].fillna(False)]
        with container:
            ui.label("Liquidity Mode controls whether Day Volume, 20D Avg Volume, either, or both must pass. Optional OHLC filters are strict: if enabled, all OHLC prices must be above the selected EMA and the EMA must exist. Scanner also requires price within the selected distance from 52W high and at least the selected % above 52W low. 5% band stocks stay out of the scanner and copy text.").classes("mp-rule")
            with ui.row().classes("gap-2 flex-wrap"):
                ui.button("Copy Buckets", on_click=lambda c=bucket_copy: copy_text_to_clipboard("Buckets", c)).classes("mp-button")
                ui.button("Copy All Sectors", on_click=lambda c=sector_copy: copy_text_to_clipboard("Sectors", c)).classes("mp-button")
                ui.button("Copy All Industries", on_click=lambda c=industry_copy: copy_text_to_clipboard("Industries", c)).classes("mp-button")
                ui.button("Copy Top Sector Stocks", on_click=lambda: copy_text_to_clipboard("Top Sector Stocks", grouped_copy_text(data, ["sector"], top_sectors))).classes("mp-button")
                ui.button("Copy Top Industry Stocks", on_click=lambda: copy_text_to_clipboard("Top Industry Stocks", grouped_copy_text(data, ["industry"], top_industries))).classes("mp-button")
            table_from_df(table_data, "Momentum Scanner Changes", hidden_cols={"ema_200", "is_avoid", "is_top_sector", "is_top_industry"})

            # When output tables have less data (few groups), put side by side to avoid lots of vertical spacing and hard-to-read empty areas
            with ui.row().classes("w-full gap-4 items-start"):
                with ui.column().classes("flex-1"):
                    table_from_df(sector_summary, "Sector Output", copy_symbols=False)
                    ui.button("Copy All Sectors (TV format)", on_click=lambda: copy_text_to_clipboard("Sectors", sector_copy)).classes("mp-button text-xs mt-1")
                with ui.column().classes("flex-1"):
                    table_from_df(industry_summary, "Industry Output", copy_symbols=False)
                    ui.button("Copy All Industries (TV format)", on_click=lambda: copy_text_to_clipboard("Industries", industry_copy)).classes("mp-button text-xs mt-1")

    run_button.on_click(render)
    # Filters now update ONLY on explicit Run (no auto re-render on every checkbox tick/number change).
    # This eliminates the delay/lag the user reported when ticking/unticking or adjusting fields.
    # Adjust any combination of filters, then click "Run Scanner". Momentum core logic and results are 100% preserved.
    render()

def deals_page() -> None:
    section_header("Deals Intelligence", "Track institutions first, then drill into the stocks and raw bulk/block rows behind the flow.")
    with ui.row().classes("gap-3 items-end flex-wrap"):
        side = ui.select(["BOTH", "BUY", "SELL"], value="BOTH", label="Side").classes("w-40")
        min_value = ui.number("Min Activity Cr", value=0).classes("w-44")
        days_back = ui.number("Lookback Days", value=30, min=5, max=120).classes("w-32")
        selected_client = ui.select([""], value="", label="Institution / Client", with_input=True).classes("w-80")
        selected_symbol = ui.select([""], value="", label="Raw Rows For Symbol", with_input=True).classes("w-72")
        run_button = ui.button("Run Deals").classes("mp-primary")
    summary_row = ui.row().classes("gap-4 flex-wrap")
    flow_chart = ui.column().classes("w-full")
    container = ui.column().classes("w-full")

    def render() -> None:
        container.clear()
        summary_row.clear()
        flow_chart.clear()
        where = ["coalesce(m.market_cap_cr, 0) >= 1000"]
        params = []
        if side.value != "BOTH":
            where.append("d.side = ?")
            params.append(side.value)
        where_sql = " AND ".join(where)
        lookback = int(days_back.value or 30)
        client_data = df_query(
            f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
            filtered_deals AS (
                SELECT d.*, m.market_cap_cr, m.sector, m.industry
                FROM deals d
                JOIN stocks_master m USING(symbol)
                WHERE {where_sql} AND d.trade_date >= (SELECT d FROM latest) - INTERVAL {lookback} DAY
            ),
            client_history AS (
                SELECT client_name, min(trade_date) AS first_seen_date, max(trade_date) AS latest_seen_date
                FROM deals
                GROUP BY client_name
            ),
            client_symbols AS (
                SELECT client_name, symbol, max(trade_date) AS latest_symbol_date
                FROM filtered_deals
                GROUP BY client_name, symbol
            ),
            symbol_rollup AS (
                SELECT client_name,
                       string_agg('NSE:' || replace(upper(symbol), '-', '_'), ',' ORDER BY latest_symbol_date DESC, symbol) AS symbol_list
                FROM client_symbols
                GROUP BY client_name
            )
            SELECT f.client_name,
                   count(*) AS deal_rows,
                   count(DISTINCT f.symbol) AS symbols,
                   count(DISTINCT f.trade_date) AS active_days,
                   max(f.trade_date) AS latest_deal_date,
                   min(h.first_seen_date) AS first_seen_date,
                   CASE WHEN min(h.first_seen_date) >= (SELECT d FROM latest) - INTERVAL 5 DAY THEN 'Yes' ELSE 'No' END AS new_addition,
                   sum(CASE WHEN f.side='BUY' THEN f.deal_value_cr ELSE 0 END) AS buy_value_cr,
                   sum(CASE WHEN f.side='SELL' THEN f.deal_value_cr ELSE 0 END) AS sell_value_cr,
                   sum(CASE WHEN f.side='BUY' THEN f.deal_value_cr ELSE -f.deal_value_cr END) AS net_value_cr,
                   max(s.symbol_list) AS symbol_list
            FROM filtered_deals f
            LEFT JOIN client_history h USING(client_name)
            LEFT JOIN symbol_rollup s USING(client_name)
            GROUP BY f.client_name
            HAVING sum(f.deal_value_cr) >= ?
            ORDER BY latest_deal_date DESC, new_addition DESC, abs(net_value_cr) DESC, (buy_value_cr + sell_value_cr) DESC
            LIMIT 200
            """,
            [*params, float(min_value.value or 0)],
        )

        client_options = [""] + client_data["client_name"].dropna().astype(str).tolist()
        old_client = selected_client.value
        selected_client.options = client_options
        if old_client not in client_options:
            selected_client.value = ""

        client_filter = ""
        stock_params = [*params]
        if selected_client.value:
            client_filter = "AND d.client_name = ?"
            stock_params.append(selected_client.value)

        stock_data = df_query(
            f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
            latest_indicators AS (
                SELECT symbol, close_price, ema_200, rs_percentile, vcp_score, vcp_state, away_52w_high_pct
                FROM indicators_daily, latest
                WHERE trade_date = latest.d
            ),
            filtered_deals AS (
                SELECT d.*, m.market_cap_cr, m.broad_industry AS master_broad_industry
                FROM deals d
                JOIN stocks_master m USING(symbol)
                WHERE {where_sql} AND d.trade_date >= (SELECT d FROM latest) - INTERVAL {lookback} DAY
                  {client_filter}
            ),
            symbol_latest AS (
                SELECT symbol, max(trade_date) AS latest_deal_date
                FROM filtered_deals
                GROUP BY symbol
            )
            SELECT d.symbol,
                   sl.latest_deal_date,
                   sum(CASE WHEN d.trade_date = sl.latest_deal_date THEN d.deal_value_cr ELSE 0 END) AS latest_deal_value_cr,
                   sum(CASE WHEN d.side='BUY' THEN d.deal_value_cr ELSE 0 END) AS buy_value_cr,
                   sum(CASE WHEN d.side='SELL' THEN d.deal_value_cr ELSE 0 END) AS sell_value_cr,
                   sum(CASE WHEN d.side='BUY' THEN d.deal_value_cr ELSE -d.deal_value_cr END) AS net_value_cr,
                   count(DISTINCT d.trade_date) AS deal_days,
                   count(DISTINCT CASE WHEN d.side='BUY' THEN d.client_name END) AS buy_client_count,
                   count(DISTINCT CASE WHEN d.side='SELL' THEN d.client_name END) AS sell_client_count,
                   max(d.deal_price_vs_close_pct) AS deal_vs_close_pct,
                   max(d.deal_pct_volume) AS deal_volume_pct,
                   max(d.rs_percentile) AS rs_percentile,
                   max(d.away_52w_high_pct) AS away_52w_high_pct,
                   max(li.close_price) AS close_price,
                   max(li.ema_200) AS ema_200,
                   max(li.vcp_score) AS vcp_score,
                   max(li.vcp_state) AS vcp_state,
                   max(d.market_cap_cr) AS market_cap_cr,
                   max(d.master_broad_industry) AS broad_industry,
                   max(d.industry) AS industry,
                   string_agg(DISTINCT CASE WHEN d.side='BUY' THEN d.client_name END, ', ' ORDER BY CASE WHEN d.side='BUY' THEN d.client_name END) AS buy_clients,
                   string_agg(DISTINCT CASE WHEN d.side='SELL' THEN d.client_name END, ', ' ORDER BY CASE WHEN d.side='SELL' THEN d.client_name END) AS sell_clients
            FROM filtered_deals d
            JOIN symbol_latest sl USING(symbol)
            LEFT JOIN latest_indicators li USING(symbol)
            GROUP BY d.symbol, sl.latest_deal_date
            HAVING abs(sum(CASE WHEN d.side='BUY' THEN d.deal_value_cr ELSE -d.deal_value_cr END)) >= ?
            ORDER BY latest_deal_date DESC, latest_deal_value_cr DESC, abs(net_value_cr) DESC
            LIMIT 500
            """,
            [*stock_params, float(min_value.value or 0)],
        )
        # Deal flow over the lookback (for chart)
        flow = df_query(
            f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
            SELECT trade_date,
                   sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_cr,
                   sum(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) AS sell_cr
            FROM deals, latest
            WHERE trade_date >= (SELECT d FROM latest) - INTERVAL {lookback} DAY
              AND coalesce((SELECT market_cap_cr FROM stocks_master WHERE symbol=deals.symbol),0) >= 1000
            GROUP BY trade_date
            ORDER BY trade_date
            """
        )

        symbols = [""] + stock_data["symbol"].dropna().astype(str).tolist()
        old_symbol = selected_symbol.value
        selected_symbol.options = symbols
        if old_symbol not in symbols:
            selected_symbol.value = ""
        buy_total = client_data["buy_value_cr"].sum() if not client_data.empty else 0
        sell_total = client_data["sell_value_cr"].sum() if not client_data.empty else 0
        with summary_row:
            metric_card("BUY Cr (window)", f"{buy_total:,.0f}", "good")
            metric_card("SELL Cr (window)", f"{sell_total:,.0f}", "bad")
            metric_card("Institutions", len(client_data), "info")
            metric_card("Stocks w/ Deals", len(stock_data), "info")
            metric_card("Lookback", f"{lookback}d", "neutral")
            copy_button("Copy Visible Symbols", lambda: symbols_text(stock_data))
        if not stock_data.empty:
            stock_data["clients"] = stock_data["buy_client_count"].fillna(0).astype(int).astype(str) + " | " + stock_data["sell_client_count"].fillna(0).astype(int).astype(str)
        else:
            stock_data["clients"] = []
        if not client_data.empty:
            client_data["copy_symbols"] = "Copy"
        else:
            client_data["copy_symbols"] = []

        # Flow chart
        with flow_chart:
            if not flow.empty:
                x = pd.to_datetime(flow["trade_date"]).dt.strftime("%d-%b").tolist()
                ui.echart({
                    "title": {"text": f"Deal Flow Last {lookback} Days (MCap>=1000)", "left": 8, "textStyle": {"fontSize": 13, "fontWeight": 700, "color": "#e2e8f0"}},
                    "tooltip": {"trigger": "axis"},
                    "legend": {"top": 22, "textStyle": {"color": "#94a3b8"}},
                    "color": ["#22c55e", "#ef4444"],
                    "grid": {"left": 40, "right": 20, "top": 50, "bottom": 25},
                    "xAxis": {"type": "category", "data": x},
                    "yAxis": {"type": "value"},
                    "series": [
                        {"name": "Buy Cr", "type": "bar", "stack": "deal", "data": flow["buy_cr"].round(1).tolist()},
                        {"name": "Sell Cr", "type": "bar", "stack": "deal", "data": [ -v for v in flow["sell_cr"].round(1).tolist()]},
                    ],
                }).classes("w-full h-64 mp-chart")
            else:
                ui.label("No deal flow in window.").classes("text-[var(--mp-muted)]")

        with container:
            with ui.row().classes("items-center gap-3 mt-4"):
                copy_button("Copy All Institution Symbols", lambda: tv_symbol_list_text(client_data["symbol_list"] if "symbol_list" in client_data.columns else []))
            client_cols = [
                "client_name", "new_addition", "latest_deal_date", "first_seen_date",
                "buy_value_cr", "sell_value_cr", "net_value_cr",
                "symbols", "active_days", "deal_rows", "copy_symbols", "symbol_list"
            ]
            table_from_df(client_data[[c for c in client_cols if c in client_data.columns]], "Institution Flow Leaderboard", copy_symbols=False, pagination=20)

            if selected_client.value:
                client_rows = df_query(
                    f"""
                    WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
                    SELECT d.trade_date, d.symbol, d.side, d.deal_type, d.quantity, d.price, d.deal_value_cr,
                           d.deal_pct_volume, d.deal_price_vs_close_pct, d.repeated_client_count,
                           i.close_price, i.rs_percentile, i.vcp_score, i.vcp_state,
                           m.sector, m.industry, m.market_cap_cr
                    FROM deals d
                    LEFT JOIN indicators_daily i ON d.symbol = i.symbol AND d.trade_date = i.trade_date
                    LEFT JOIN stocks_master m ON d.symbol = m.symbol
                    WHERE d.client_name = ? AND d.trade_date >= (SELECT d FROM latest) - INTERVAL {lookback} DAY
                    ORDER BY d.trade_date DESC, d.deal_value_cr DESC
                    LIMIT 200
                    """,
                    [selected_client.value],
                )
                table_from_df(client_rows, f"Institution Detail - {selected_client.value}", pagination=25)

            deal_cols = [
                "symbol", "latest_deal_date", "latest_deal_value_cr", "buy_value_cr", "sell_value_cr", "net_value_cr",
                "deal_days", "clients", "deal_vs_close_pct", "deal_volume_pct",
                "close_price", "ema_200", "rs_percentile", "vcp_score", "vcp_state", "away_52w_high_pct",
                "market_cap_cr", "broad_industry", "industry",
                "buy_clients", "sell_clients"
            ]
            table_from_df(stock_data[[c for c in deal_cols if c in stock_data.columns]], "Stock-Level Deals (window)", pagination=30, hidden_cols={"buy_clients", "sell_clients"})
            if selected_symbol.value:
                raw = df_query(
                    """
                    SELECT deal_type, trade_date, symbol, side, client_name, quantity, price, deal_value_cr,
                           deal_pct_volume, deal_price_vs_close_pct, repeated_client_count, sector, industry
                    FROM deals
                    WHERE symbol = ?
                    ORDER BY trade_date DESC, deal_value_cr DESC
                    LIMIT 100
                    """,
                    [selected_symbol.value],
                )
                table_from_df(raw, f"Raw Deal Rows - {selected_symbol.value}", pagination=20, copy_symbols=False)

    for ctrl in [side, min_value, days_back, selected_client, selected_symbol]:
        ctrl.on_value_change(render)
    run_button.on_click(render)
    render()


def backtest_page() -> None:
    section_header("Backtest / Leader Study", "Find past leaders, then compare current stocks with pre-move setups.")
    with ui.row().classes("gap-3 items-end flex-wrap"):
        horizon = ui.select(["3M", "6M"], value="3M", label="Forward Window").classes("w-36")
        min_forward = ui.number("Min Forward %", value=30).classes("w-40")
        setup_offset = ui.select([5, 10, 20], value=10, label="Setup Days Before").classes("w-44")
        min_mcap = ui.number("Min MCap Cr", value=1000).classes("w-36")
        max_rows = ui.number("Rows", value=100, min=25, max=300).classes("w-28")
        run_button = ui.button("Run Study").classes("mp-primary")
        # Manual custom past leaders (user study/save for next time; not auto daily per-symbol actions).
        # Enter comma-separated; will override the auto 'Past Leaders Used For Profile' computation for your repeated study.
        # Store manually in Exports/custom_past_leaders.json or similar for persistence across sessions (preserved on rebuild).
        custom_leaders = ui.input("Custom Past Leaders (comma sep, e.g. MTARTECH,RELIANCE — study/save these; use for profile instead of auto)", value="").classes("w-full")
        info_icon("Past Leaders Profile")
    summary_row = ui.row().classes("gap-4 flex-wrap")
    container = ui.column().classes("w-full")

    def render() -> None:
        container.clear()
        summary_row.clear()
        forward_days = 63 if horizon.value == "3M" else 126
        data = df_query(
            f"""
            WITH sequenced AS (
                SELECT i.*, m.market_cap_cr, m.sector, m.industry,
                       lead(i.close_price, {forward_days}) OVER (PARTITION BY i.symbol ORDER BY i.trade_date) AS future_close,
                       lag(i.close_price, {int(setup_offset.value)}) OVER (PARTITION BY i.symbol ORDER BY i.trade_date) AS setup_close,
                       lag(i.away_10ema_pct, {int(setup_offset.value)}) OVER (PARTITION BY i.symbol ORDER BY i.trade_date) AS setup_10ema_pct,
                       lag(i.away_10wema_pct, {int(setup_offset.value)}) OVER (PARTITION BY i.symbol ORDER BY i.trade_date) AS setup_10wema_pct,
                       lag(i.away_10mema_pct, {int(setup_offset.value)}) OVER (PARTITION BY i.symbol ORDER BY i.trade_date) AS setup_10mema_pct,
                       lag(i.away_52w_high_pct, {int(setup_offset.value)}) OVER (PARTITION BY i.symbol ORDER BY i.trade_date) AS setup_52w_pct,
                       lag(i.rs_percentile, {int(setup_offset.value)}) OVER (PARTITION BY i.symbol ORDER BY i.trade_date) AS setup_rs_pct,
                       lag(i.rvol, {int(setup_offset.value)}) OVER (PARTITION BY i.symbol ORDER BY i.trade_date) AS setup_rvol,
                       lag(CASE WHEN i.ema_stack_bullish THEN 1 ELSE 0 END, {int(setup_offset.value)}) OVER (PARTITION BY i.symbol ORDER BY i.trade_date) AS setup_ema_stack
                FROM indicators_daily i
                JOIN stocks_master m USING(symbol)
                WHERE coalesce(m.market_cap_cr, 0) >= ?
            ),
            leaders AS (
                SELECT symbol, trade_date AS breakout_date, close_price AS breakout_close,
                       (future_close / nullif(close_price, 0) - 1) * 100 AS forward_return_pct,
                       setup_close, setup_10ema_pct, setup_10wema_pct, setup_10mema_pct,
                       setup_52w_pct, setup_rs_pct, setup_rvol, setup_ema_stack,
                       sector, industry
                FROM sequenced
                WHERE future_close IS NOT NULL
                  AND (future_close / nullif(close_price, 0) - 1) * 100 >= ?
                  AND setup_close IS NOT NULL
            ),
            leader_profile AS (
                SELECT median(setup_10ema_pct) AS p_10ema,
                       median(setup_10wema_pct) AS p_10wema,
                       median(setup_10mema_pct) AS p_10mema,
                       median(setup_52w_pct) AS p_52w,
                       median(setup_rs_pct) AS p_rs,
                       median(setup_rvol) AS p_rvol,
                       avg(setup_ema_stack) AS p_ema_stack
                FROM leaders
            ),
            latest AS (SELECT max(trade_date) d FROM indicators_daily),
            current_setups AS (
                SELECT i.symbol, i.trade_date, i.close_price, m.market_cap_cr, m.sector, m.industry,
                       i.away_10ema_pct, i.away_10wema_pct, i.away_10mema_pct, i.away_52w_high_pct,
                       i.rs_percentile, i.rvol, CASE WHEN i.ema_stack_bullish THEN 1 ELSE 0 END AS ema_stack
                FROM indicators_daily i JOIN stocks_master m USING(symbol), latest
                WHERE i.trade_date = latest.d AND coalesce(m.market_cap_cr, 0) >= ?
            ),
            scored AS (
                SELECT c.*,
                       (
                         greatest(0, 20 - abs(coalesce(c.away_10ema_pct, 0) - coalesce(p.p_10ema, 0))) * 1.0
                         + greatest(0, 15 - abs(coalesce(c.away_10wema_pct, 0) - coalesce(p.p_10wema, 0))) * 1.2
                         + greatest(0, 15 - abs(coalesce(c.away_52w_high_pct, 0) - coalesce(p.p_52w, 0))) * 1.2
                         + greatest(0, 30 - abs(coalesce(c.rs_percentile, 0) - coalesce(p.p_rs, 0))) * 0.8
                         + CASE WHEN c.ema_stack = round(coalesce(p.p_ema_stack, 0)) THEN 20 ELSE 0 END
                       ) AS similarity_score,
                       '10EMA ' || round(c.away_10ema_pct, 1) || '%, WEMA ' || round(c.away_10wema_pct, 1) ||
                       '%, 52W ' || round(c.away_52w_high_pct, 1) || '%, RS ' || round(c.rs_percentile, 1) AS current_setup,
                       'Leader median: 10EMA ' || round(p.p_10ema, 1) || '%, WEMA ' || round(p.p_10wema, 1) ||
                       '%, 52W ' || round(p.p_52w, 1) || '%, RS ' || round(p.p_rs, 1) AS what_matched
                FROM current_setups c CROSS JOIN leader_profile p
            )
            SELECT symbol, similarity_score, current_setup, what_matched,
                   close_price, market_cap_cr, away_10ema_pct, away_10wema_pct, away_10mema_pct,
                   away_52w_high_pct, rs_percentile, rvol, sector, industry
            FROM scored
            ORDER BY similarity_score DESC NULLS LAST
            LIMIT ?
            """,
            [float(min_mcap.value or 0), float(min_forward.value or 0), float(min_mcap.value or 0), int(max_rows.value or 100)],
        )
        leaders = df_query(
            f"""
            WITH sequenced AS (
                SELECT i.symbol, i.trade_date, i.close_price, m.market_cap_cr, m.sector, m.industry,
                       lead(i.close_price, {forward_days}) OVER (PARTITION BY i.symbol ORDER BY i.trade_date) AS future_close
                FROM indicators_daily i JOIN stocks_master m USING(symbol)
                WHERE coalesce(m.market_cap_cr, 0) >= ?
            )
            SELECT symbol, trade_date AS breakout_date, close_price AS breakout_close,
                   (future_close / nullif(close_price, 0) - 1) * 100 AS forward_return_pct,
                   sector, industry
            FROM sequenced
            WHERE future_close IS NOT NULL
              AND (future_close / nullif(close_price, 0) - 1) * 100 >= ?
            ORDER BY forward_return_pct DESC
            LIMIT ?
            """,
            [float(min_mcap.value or 0), float(min_forward.value or 0), int(max_rows.value or 100)],
        )
        with summary_row:
            metric_card("Past Leaders", len(leaders), "info")
            metric_card("Current Matches", len(data), "good" if len(data) else "warn")
            metric_card("Window", horizon.value, "neutral", f"{int(setup_offset.value)} days before")
            copy_button("Copy Current Matches", lambda: symbols_text(data))
        with container:
            ui.label("Prototype: similarity compares current stocks with median pre-move conditions of past leaders. It avoids future data in current setup columns.").classes("mp-rule")
            table_from_df(data, "Current Stocks Similar To Past Leaders", pagination=30)
            table_from_df(leaders, "Past Leaders Used For Profile", pagination=20)

    for ctrl in [horizon, min_forward, setup_offset, min_mcap, max_rows]:
        ctrl.on_value_change(render)
    run_button.on_click(render)
    render()



def journal_page() -> None:
    ensure_journal_table()
    section_header("Journal", "Local professional trade journal saved inside marketpulse.duckdb.")
    latest_date = df_query("SELECT max(trade_date) AS d FROM indicators_daily").iloc[0]["d"]
    symbols = df_query("SELECT symbol FROM stocks_master ORDER BY symbol")["symbol"].tolist()
    trade_types = ["Buy", "Sell", "Watch", "Avoid"]
    setups = ["Momentum Scanner", "EMA Cross", "Near WEMA", "Near MEMA", "Shakeout", "Near High", "Deal Based", "Sector Rotation", "Backtest Similarity", "Manual"]
    statuses = ["Open", "Closed", "Watchlist", "Avoided", "Cancelled"]
    exit_reasons = ["", "Target Hit", "Stop Hit", "Manual Exit", "Weak Close", "Sector Weakness", "Market Weakness", "Better Opportunity"]
    mistake_tags = ["", "Chased", "Early Entry", "Late Entry", "Ignored Stop", "Oversized", "No Setup", "Good Trade", "Other"]

    with ui.row().classes("gap-3 items-end flex-wrap"):
        selected_id = ui.select([""], value="", label="Edit ID (type or pick; IDs shown in table below)").classes("w-40").props("clearable use-input")
        trade_date_input = ui.input("Trade Date", value=str(latest_date)[:10] if pd.notna(latest_date) else str(date.today())).classes("w-36")
        symbol_input = ui.select(symbols, label="Symbol", with_input=True).classes("w-44")
        trade_type = ui.select(trade_types, value="Buy", label="Type").classes("w-28")
        setup_type = ui.select(setups, value="Manual", label="Setup").classes("w-48")
        status = ui.select(statuses, value="Open", label="Status").classes("w-36")
    with ui.row().classes("gap-3 items-end flex-wrap"):
        entry_price = ui.number("Entry", value=0).classes("w-28")
        quantity = ui.number("Qty", value=0).classes("w-28")
        stop_loss = ui.number("Stop", value=0).classes("w-28")
        target = ui.number("Target", value=0).classes("w-28")
        exit_date = ui.input("Exit Date", value="").classes("w-36")
        exit_price = ui.number("Exit", value=0).classes("w-28")
        exit_reason = ui.select(exit_reasons, value="", label="Exit Reason").classes("w-44")
        mistake_tag = ui.select(mistake_tags, value="", label="Mistake").classes("w-40")
    notes = ui.textarea("Notes").classes("w-full").props("autogrow")
    with ui.row().classes("gap-2 flex-wrap"):
        add_button = ui.button("Add Entry").classes("mp-primary")
        save_button = ui.button("Save Selected").classes("mp-button")
        close_button = ui.button("Close Selected").classes("mp-button")
    with ui.row().classes("gap-3 items-end flex-wrap"):
        view_filter = ui.select(["All", "Open", "Closed", "Watchlist", "Avoided", "Cancelled"], value="All", label="View").classes("w-40")
        setup_filter = ui.select(["All", *setups], value="All", label="Setup Filter").classes("w-52")
        sector_filter = ui.select(["All"], value="All", label="Sector").classes("w-52")
        run_button = ui.button("Refresh Journal").classes("mp-primary")
    summary_row = ui.row().classes("gap-4 flex-wrap")
    container = ui.column().classes("w-full")

    def calc_trade_values():
        entry = float(entry_price.value or 0)
        qty = float(quantity.value or 0)
        stop = float(stop_loss.value or 0)
        tgt = float(target.value or 0)
        pos = entry * qty
        risk_amt = abs(entry - stop) * qty if entry and stop and qty else 0
        risk_pct = (abs(entry - stop) / entry * 100) if entry and stop else 0
        reward_pct = ((tgt - entry) / entry * 100) if entry and tgt and trade_type.value == "Buy" else ((entry - tgt) / entry * 100 if entry and tgt else 0)
        r_target = (abs(tgt - entry) / abs(entry - stop)) if entry and stop and tgt and entry != stop else 0
        return pos, risk_amt, risk_pct, reward_pct, r_target

    def parse_date_or_none(value):
        text = str(value or "").strip()
        return text if text else None

    def add_entry() -> None:
        if not symbol_input.value:
            ui.notify("Select a symbol first", type="warning")
            return
        pos, risk_amt, risk_pct, reward_pct, r_target = calc_trade_values()
        row_id = int(pd.Timestamp.utcnow().value // 1_000_000)
        write_execute(
            """
            INSERT INTO trade_journal VALUES (?, now(), now(), CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS DATE), ?, ?, ?, ?)
            """,
            [row_id, trade_date_input.value, symbol_input.value, trade_type.value, setup_type.value,
             float(entry_price.value or 0), float(quantity.value or 0), float(stop_loss.value or 0), float(target.value or 0),
             pos, risk_amt, risk_pct, reward_pct, r_target, status.value, parse_date_or_none(exit_date.value),
             float(exit_price.value or 0) if exit_price.value else None, exit_reason.value or None, notes.value or "", mistake_tag.value or None],
        )
        ui.notify("Journal entry saved", type="positive")
        render()

    def save_selected(close_now: bool = False) -> None:
        if not selected_id.value:
            ui.notify("Select an entry ID first", type="warning")
            return
        pos, risk_amt, risk_pct, reward_pct, r_target = calc_trade_values()
        final_status = "Closed" if close_now else status.value
        write_execute(
            """
            UPDATE trade_journal
            SET updated_at = now(), trade_date = CAST(? AS DATE), symbol = ?, trade_type = ?, setup_type = ?,
                entry_price = ?, quantity = ?, stop_loss = ?, target = ?, position_size = ?, risk_amount = ?, risk_pct = ?,
                reward_pct = ?, r_multiple_target = ?, status = ?, exit_date = CAST(? AS DATE), exit_price = ?,
                exit_reason = ?, notes = ?, mistake_tag = ?
            WHERE id = ?
            """,
            [trade_date_input.value, symbol_input.value, trade_type.value, setup_type.value,
             float(entry_price.value or 0), float(quantity.value or 0), float(stop_loss.value or 0), float(target.value or 0),
             pos, risk_amt, risk_pct, reward_pct, r_target, final_status, parse_date_or_none(exit_date.value),
             float(exit_price.value or 0) if exit_price.value else None, exit_reason.value or None, notes.value or "", mistake_tag.value or None,
             int(selected_id.value)],
        )
        ui.notify("Journal entry updated", type="positive")
        render()

    def load_selected() -> None:
        if not selected_id.value:
            return
        row = df_query("SELECT * FROM trade_journal WHERE id = ?", [int(selected_id.value)])
        if row.empty:
            return
        r = row.iloc[0]
        trade_date_input.value = str(r["trade_date"])[:10]
        symbol_input.value = r["symbol"]
        trade_type.value = r["trade_type"] or "Buy"
        setup_type.value = r["setup_type"] or "Manual"
        entry_price.value = float(r["entry_price"] or 0)
        quantity.value = float(r["quantity"] or 0)
        stop_loss.value = float(r["stop_loss"] or 0)
        target.value = float(r["target"] or 0)
        status.value = r["status"] or "Open"
        exit_date.value = "" if pd.isna(r["exit_date"]) else str(r["exit_date"])[:10]
        exit_price.value = float(r["exit_price"] or 0)
        exit_reason.value = r["exit_reason"] or ""
        notes.value = r["notes"] or ""
        mistake_tag.value = r["mistake_tag"] or ""

    def enriched_journal() -> pd.DataFrame:
        where = ["true"]
        params = []
        if view_filter.value != "All":
            where.append("status = ?")
            params.append(view_filter.value)
        if setup_filter.value != "All":
            where.append("setup_type = ?")
            params.append(setup_filter.value)

        # Fetch ONLY the journal rows first with minimal query.
        # This completely avoids all the previous complex JOINs on "symbol"
        # (multiple USING(symbol) + historical tables) that were causing
        # DuckDB to mis-infer types and try to cast symbol strings to INT32.
        # We do the enrichment (current indicators + deals + historical regime)
        # in Python/pandas afterwards. This is safe, simple, and matches how 1.0
        # stayed stable. The "connect the dots" (entry-time breadth/sector state)
        # is still delivered.
        jdf = df_query(
            f"""
            SELECT * FROM trade_journal 
            WHERE {' AND '.join(where)}
            ORDER BY trade_date DESC, id DESC
            """,
            params,
        )

        if jdf.empty:
            return jdf

        # Apply sector filter later after enrichment

        symbols = jdf["symbol"].dropna().unique().tolist()
        if not symbols:
            return jdf

        sym_ph = ",".join(["?"] * len(symbols))

        # Latest data for these symbols (one clean join, no USING chains)
        latest_df = df_query(
            f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
            SELECT i.symbol, 
                   i.close_price AS current_close, 
                   i.away_10ema_pct, 
                   i.away_52w_high_pct,
                   i.rs_percentile, 
                   i.rvol, 
                   m.sector, 
                   m.industry, 
                   m.broad_industry
            FROM indicators_daily i 
            JOIN stocks_master m USING(symbol), latest
            WHERE i.trade_date = latest.d
              AND i.symbol IN ({sym_ph})
            """,
            symbols,
        )

        # Recent deals for these symbols
        deals_df = df_query(
            f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
            SELECT symbol,
                   sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_deal_cr,
                   sum(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) AS sell_deal_cr
            FROM deals, latest
            WHERE trade_date >= latest.d - INTERVAL 20 DAY
              AND symbol IN ({sym_ph})
            GROUP BY symbol
            """,
            symbols,
        )

        # Merge in pandas
        data = jdf.merge(latest_df, on="symbol", how="left")
        data = data.merge(deals_df, on="symbol", how="left")

        # Apply sector filter now that we have 'sector'
        if sector_filter.value != "All":
            data = data[data.get("sector") == sector_filter.value]

        # Enrich historical entry context (breadth + sector state at trade_date)
        # using small targeted queries + pandas merge. No complex SQL joins at all.
        unique_dates = data["trade_date"].dropna().unique().tolist()
        if unique_dates:
            date_ph = ",".join(["?"] * len(unique_dates))

            # Breadth at entry dates
            b_df = df_query(
                f"SELECT trade_date, breadth_state FROM breadth_daily WHERE trade_date IN ({date_ph})",
                unique_dates,
            )
            if not b_df.empty:
                b_df = b_df.rename(columns={"breadth_state": "entry_breadth_state"})
                data = data.merge(b_df, on="trade_date", how="left")

            # Sector rotation state at entry dates for the symbols' sectors
            unique_sectors = [
                s for s in data.get("sector", pd.Series(dtype=object)).dropna().unique().tolist() if s
            ]
            if unique_sectors:
                all_params = unique_dates + unique_sectors
                sec_ph = ",".join(["?"] * len(unique_sectors))
                sr_df = df_query(
                    f"""
                    SELECT trade_date, 
                           group_name as sector, 
                           rotation_state as entry_sector_state, 
                           rs_percentile as entry_sector_rs
                    FROM sector_rotation 
                    WHERE trade_date IN ({date_ph})
                      AND level = 'Sector'
                      AND group_name IN ({sec_ph})
                    """,
                    all_params,
                )
                if not sr_df.empty:
                    data = data.merge(sr_df, on=["trade_date", "sector"], how="left")

        return data

    def render() -> None:
        summary_row.clear()
        container.clear()
        data = enriched_journal()
        ids = [""] + data["id"].astype(str).tolist() if not data.empty else [""]
        old_id = selected_id.value
        selected_id.options = ids
        if old_id not in ids:
            selected_id.value = ""
        sectors = ["All"] + sorted([x for x in df_query("SELECT DISTINCT sector FROM stocks_master WHERE sector IS NOT NULL ORDER BY sector")["sector"].tolist() if x])
        old_sector = sector_filter.value
        sector_filter.options = sectors
        if old_sector not in sectors:
            sector_filter.value = "All"
        closed = data[data["status"] == "Closed"] if not data.empty else data
        wins = closed[pd.to_numeric(closed["pnl_pct"], errors="coerce") > 0] if not closed.empty else closed
        realized_pnl = pd.to_numeric(closed["pnl_amount"], errors="coerce").sum() if len(closed) else 0
        open_risk = pd.to_numeric(data.loc[data["status"] == "Open", "risk_amount"], errors="coerce").sum() if not data.empty else 0
        with summary_row:
            metric_card("Entries", len(data), "info")
            metric_card("Open", int((data["status"] == "Open").sum()) if not data.empty else 0, "good")
            metric_card("Win Rate", f"{(len(wins) / len(closed) * 100):.1f}%" if len(closed) else "-", "good" if len(wins) else "neutral")
            metric_card("Avg P/L", f"{pd.to_numeric(closed['pnl_pct'], errors='coerce').mean():.1f}%" if len(closed) else "-", "info")
            metric_card("Realized P/L", format_inr(realized_pnl, signed=True), "good" if realized_pnl >= 0 else "bad")
            metric_card("Avg R", f"{pd.to_numeric(closed['r_multiple'], errors='coerce').mean():.2f}" if len(closed) else "-", "info")
            metric_card("Open Risk", format_inr(open_risk), "warn")
            copy_button("Copy Journal Symbols", lambda: symbols_text(data))
        with container:
            journal_cols = [
                "id", "trade_date", "symbol", "status", "trade_type", "setup_type",
                "entry_price", "quantity", "stop_loss", "target", "current_close",
                "exit_price", "pnl_amount", "pnl_pct", "r_multiple", "risk_amount",
                "sector", "notes", "entry_breadth_state", "entry_sector_state", "entry_sector_rs",
            ]
            journal_view = data[[c for c in journal_cols if c in data.columns]].copy() if not data.empty else data
            table_from_df(journal_view, "Journal Entries", pagination=25)
            if not data.empty:
                by_setup = data.groupby("setup_type", dropna=False).agg(trades=("symbol", "count"), pnl_amount=("pnl_amount", "sum"), avg_pnl_pct=("pnl_pct", "mean"), avg_r=("r_multiple", "mean")).reset_index().sort_values("trades", ascending=False)
                by_sector = data.groupby(["sector", "industry"], dropna=False).agg(trades=("symbol", "count"), pnl_amount=("pnl_amount", "sum"), avg_pnl_pct=("pnl_pct", "mean"), open_risk=("risk_amount", "sum")).reset_index().sort_values("trades", ascending=False)
                mistakes = data.groupby("mistake_tag", dropna=False).agg(trades=("symbol", "count"), pnl_amount=("pnl_amount", "sum"), avg_pnl_pct=("pnl_pct", "mean"), avg_r=("r_multiple", "mean")).reset_index().sort_values("trades", ascending=False)
                table_from_df(by_setup, "By Setup", copy_symbols=False)
                table_from_df(by_sector, "By Sector / Industry", copy_symbols=False)
                table_from_df(mistakes, "Mistakes Review", copy_symbols=False)

    add_button.on_click(add_entry)
    save_button.on_click(lambda: save_selected(False))
    close_button.on_click(lambda: save_selected(True))
    selected_id.on_value_change(load_selected)
    for ctrl in [view_filter, setup_filter, sector_filter]:
        ctrl.on_value_change(render)
    run_button.on_click(render)
    render()

def stock_detail_page() -> None:
    section_header("Stock Detail", "Single-symbol setup context, deals, screener matches, and indicator history.")
    symbols = df_query("SELECT symbol FROM stocks_master ORDER BY symbol")["symbol"].tolist()
    selected = ui.select(symbols, label="Symbol", with_input=True).classes("w-80")
    container = ui.column().classes("w-full")

    def render() -> None:
        container.clear()
        if not selected.value:
            return
        latest = df_query(
            """
            SELECT i.symbol, i.trade_date, i.close_price,
                   i.away_10ema_pct, i.away_52w_high_pct, i.rs_percentile, i.rsi_14, i.rsi_14_w, i.rsi_14_m,
                   m.broad_sector, m.sector, m.industry, m.market_cap_cr, m.band
            FROM indicators_daily i JOIN stocks_master m USING(symbol)
            WHERE i.symbol = ?
            ORDER BY i.trade_date DESC LIMIT 1
            """,
            [selected.value],
        )
        history = df_query(
            """
            SELECT trade_date, close_price, volume, delivery_pct, ema_10, ema_50, ema_200,
                   away_10ema_pct, return_5d_pct, return_1m_pct, rvol, atr_pct, rs_percentile,
                   rsi_14, rsi_14_w, rsi_14_m
            FROM indicators_daily
            WHERE symbol = ?
            ORDER BY trade_date DESC LIMIT 120
            """,
            [selected.value],
        )
        deals = df_query(
            """
            SELECT deal_type, trade_date, side, client_name, quantity, price, deal_value_cr,
                   deal_pct_volume, deal_price_vs_close_pct, repeated_client_count
            FROM deals WHERE symbol = ? ORDER BY trade_date DESC, deal_value_cr DESC LIMIT 50
            """,
            [selected.value],
        )
        passed = df_query(
            """
            SELECT screener_name, rule_summary, close_price, rs_percentile, away_10ema_pct, away_52w_high_pct
            FROM screener_results WHERE symbol = ? ORDER BY screener_name
            """,
            [selected.value],
        )
        with container:
            ui.link(f"Open {selected.value} in TradingView", tradingview_url(selected.value), new_tab=True).classes("mp-symbol text-lg")
            if not latest.empty:
                r = latest.iloc[0]
                with ui.row().classes("gap-4 flex-wrap"):
                    metric_card("Close", f"{r['close_price']:.2f}", "info")
                    metric_card("RS", f"{r['rs_percentile']:.1f}", "good" if r["rs_percentile"] >= 80 else "info")
                    metric_card("RSI D", f"{r['rsi_14']:.1f}", "info")
                    metric_card("52W Dist", f"{r['away_52w_high_pct']:.1f}%", "good" if r["away_52w_high_pct"] >= -10 else "warn")
                    metric_card("Band", f"{r['band']}%", "warn" if float(r["band"] or 0) <= 5 else "neutral")
            table_from_df(passed, "Current Screener Matches", copy_symbols=False)
            table_from_df(deals, "Historical Deals", copy_symbols=False)
            table_from_df(history, "Recent Price / Indicator History", pagination=20, copy_symbols=False)

    selected.on_value_change(render)


def add_styles() -> None:
    ui.add_head_html(
        """
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
            height: 52px;
            padding: 0 24px;
            font-size: var(--mp-text-base);
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

          /* Tables */
          .mp-table, .q-table, .q-table__container {
            background: var(--mp-surface);
            color: var(--mp-text);
            border: 1px solid var(--mp-border);
            border-radius: var(--mp-radius-sm);
            font-size: var(--mp-text-sm);
          }
          .mp-table .q-table, .q-table {
            table-layout: fixed !important;
          }
          .mp-table th, .q-table th {
            font-weight: 700;
            background: var(--mp-surface-offset);
            color: var(--mp-text);
            text-transform: uppercase;
            font-size: var(--mp-text-xs);
            letter-spacing: 0.6px;
            padding: 6px 8px;
            border-bottom: 1px solid var(--mp-divider);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }
          .mp-table td, .mp-table .q-td, .q-table td, .q-table .q-td {
            color: var(--mp-text);
            padding: 5px 8px;
            border-bottom: 1px solid var(--mp-divider);
            font-weight: 500;
            font-variant-numeric: tabular-nums;
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
          .mp-table td.text-col, .mp-table .q-td.text-col,
          .q-table td.text-col, .q-table .q-td.text-col,
          .mp-table td.symbol-col, .mp-table .q-td.symbol-col,
          .q-table td.symbol-col, .q-table .q-td.symbol-col {
            text-align: left !important;
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
    )




def info_icon(key: str) -> None:
    """Render a small (i) icon with tooltip explanation from EXPLANATIONS dict. Call after section titles or in headers."""
    text = EXPLANATIONS.get(key, "No explanation available yet.")
    with ui.element("span").classes("ml-1 cursor-help text-xs text-sky-400 align-super"):
        ui.html("ⓘ").props("title='" + text.replace("'", "\\'") + "'")  # simple title for now; can upgrade to q-tooltip
        # For richer: ui.tooltip(text).props("anchor='top middle' self='bottom middle'") but title is lightweight and works everywhere.


def _regime_posture(state: str) -> tuple[str, str, str]:
    """Return (label, tone, guidance) for breadth_state."""
    s = (state or "Neutral").strip()
    if s in {"Improving", "Broad Participation"}:
        return "Aggressive", "good", "Breadth supports trend longs. Favour breakouts, VCP Near Pivot, and leaders in Leading groups."
    if s == "Weakening":
        return "Defensive", "bad", "Participation is deteriorating. Prefer selective names only: high RS + structure, avoid extended breakouts, size down."
    if s == "Diverging":
        return "Selective", "warn", "Price advances without breadth confirmation. Require multi-signal confluence and industry tailwind."
    return "Neutral", "info", "No strong breadth edge. Stick to highest-quality setups with clear invalidation."


def _build_why_risk(row: pd.Series) -> tuple[str, str]:
    why: list[str] = []
    risks: list[str] = []

    rs = float(row.get("rs_percentile") or 0)
    rs_1y = float(row.get("rs_1y_percentile") or 0) if pd.notna(row.get("rs_1y_percentile")) else None
    vcp = float(row.get("vcp_score") or 0)
    vcp_state = str(row.get("vcp_state") or "").strip()
    away_high = float(row.get("away_52w_high_pct") or 0) if pd.notna(row.get("away_52w_high_pct")) else None
    away_10 = float(row.get("away_10ema_pct") or 0) if pd.notna(row.get("away_10ema_pct")) else None
    buy_cr = float(row.get("buy_deal_cr") or 0)
    sell_cr = float(row.get("sell_deal_cr") or 0)
    ind_state = str(row.get("industry_state") or "")
    sec_state = str(row.get("sector_state") or "")
    band = float(row.get("band") or 0) if pd.notna(row.get("band")) else None
    delivery_spike = bool(row.get("delivery_spike")) if pd.notna(row.get("delivery_spike")) else False
    stack = bool(row.get("ema_stack_bullish")) if pd.notna(row.get("ema_stack_bullish")) else False
    reclaim = bool(row.get("fresh_200ema_reclaim")) if pd.notna(row.get("fresh_200ema_reclaim")) else False
    rvol = float(row.get("rvol") or 0) if pd.notna(row.get("rvol")) else None

    if rs >= 90:
        why.append(f"Elite RS {rs:.0f}")
    elif rs >= 80:
        why.append(f"Strong RS {rs:.0f}")
    elif rs >= 70:
        why.append(f"RS {rs:.0f}")
    if rs_1y is not None and rs_1y >= 80 and rs >= 70:
        why.append(f"Sustained 1Y RS {rs_1y:.0f}")
    if vcp_state in {"Near Pivot", "Building Base", "Breakout"}:
        why.append(f"VCP {vcp_state} ({vcp:.0f})")
    elif vcp >= 55:
        why.append(f"VCP score {vcp:.0f}")
    if stack:
        why.append("Bullish EMA stack")
    if reclaim:
        why.append("Fresh 200EMA reclaim")
    if away_high is not None and -10 <= away_high <= 2:
        why.append(f"Near 52W high ({away_high:.1f}%)")
    if buy_cr >= 5:
        why.append(f"Buy deals {buy_cr:.0f} Cr (20d)")
    elif buy_cr > 0:
        why.append(f"Buy flow {buy_cr:.1f} Cr")
    if ind_state in {"Leading", "Emerging", "Improving"}:
        why.append(f"Industry {ind_state}")
    elif sec_state in {"Leading", "Emerging", "Improving"}:
        why.append(f"Sector {sec_state}")
    if delivery_spike:
        why.append("Delivery spike")
    if rvol is not None and rvol >= 1.5:
        why.append(f"RVOL {rvol:.1f}x")

    if ind_state in {"Weakening", "Lagging"}:
        risks.append(f"Industry {ind_state}")
    if sec_state in {"Weakening", "Lagging"}:
        risks.append(f"Sector {sec_state}")
    if sell_cr > buy_cr and sell_cr >= 5:
        risks.append(f"Sell deals {sell_cr:.0f} Cr > buys")
    if band is not None and band > 0 and band <= 5:
        risks.append(f"{band:.0f}% price band")
    if away_10 is not None and away_10 > 8:
        risks.append(f"Extended +{away_10:.1f}% vs 10EMA")
    if away_high is not None and away_high < -20:
        risks.append(f"Far from high ({away_high:.1f}%)")
    if vcp_state == "Failed Breakout":
        risks.append("Failed breakout state")
    if rs < 60:
        risks.append(f"Soft RS {rs:.0f}")

    return (" · ".join(why) if why else "—", " · ".join(risks) if risks else "—")


def today_page() -> None:
    """Decision home: regime posture, leadership changes, ranked preparation list with evidence."""
    section_header("Today", "Decision desk — regime, what changed, and ranked prep candidates with evidence.")

    dates = df_query(
        """
        SELECT DISTINCT trade_date
        FROM indicators_daily
        ORDER BY trade_date DESC
        LIMIT 2
        """
    )
    if dates.empty:
        ui.label("No indicator data. Run Update_MarketPulse.bat.").classes("text-red-600")
        return

    latest_d = pd.to_datetime(dates.iloc[0]["trade_date"]).date()
    prev_d = pd.to_datetime(dates.iloc[1]["trade_date"]).date() if len(dates) > 1 else None

    breadth = df_query("SELECT * FROM breadth_daily ORDER BY trade_date DESC LIMIT 2")
    if breadth.empty:
        ui.label("No breadth data.").classes("text-red-600")
        return
    b0 = breadth.iloc[0]
    b1 = breadth.iloc[1] if len(breadth) > 1 else None
    posture, posture_tone, guidance = _regime_posture(str(b0.get("breadth_state", "Neutral")))

    # Regime banner
    with ui.card().classes("w-full mp-card mb-3"):
        with ui.row().classes("w-full items-start gap-4 flex-wrap"):
            with ui.column().classes("gap-1"):
                ui.label("MARKET POSTURE").classes("mp-card-label")
                ui.label(posture).classes(f"text-2xl font-bold mp-badge {TONE_CLASS.get(posture_tone, TONE_CLASS['info'])}")
                ui.label(str(b0.get("breadth_state", "—"))).classes("text-sm text-[var(--mp-muted)]")
            with ui.column().classes("gap-1 flex-1 min-w-[240px]"):
                ui.label(f"Session {latest_d}").classes("mp-card-label")
                ui.label(guidance).classes("text-sm")
                if b1 is not None:
                    d_adv = float(b0["advance_pct"]) - float(b1["advance_pct"])
                    d_50 = float(b0["above_50ema_pct"]) - float(b1["above_50ema_pct"])
                    ui.label(
                        f"vs prior: Advance {d_adv:+.1f}pp · Above 50EMA {d_50:+.1f}pp · "
                        f"VCP cands {int(b0.get('vcp_candidates') or 0)} · Near 52W {int(b0.get('near_52w_highs') or 0)}"
                    ).classes("text-xs text-[var(--mp-muted)]")
            with ui.row().classes("gap-3 flex-wrap"):
                metric_card("Advance %", f"{float(b0['advance_pct']):.1f}%", "good" if b0["advance_pct"] >= 55 else "bad" if b0["advance_pct"] <= 45 else "info")
                metric_card("Above 50", f"{float(b0['above_50ema_pct']):.1f}%", "good" if b0["above_50ema_pct"] >= 55 else "bad")
                metric_card("Above 200", f"{float(b0['above_200ema_pct']):.1f}%", "good" if b0["above_200ema_pct"] >= 45 else "bad")
                metric_card("Near 52W", int(b0.get("near_52w_highs") or 0), "info")

    # Leading / weakening industries
    rotation = df_query(
        """
        WITH latest AS (SELECT max(trade_date) d FROM sector_rotation)
        SELECT group_name, rotation_state, rotation_rank, score_change_5d, rank_change_5d,
               return_5d_pct, return_1m_pct, rs_percentile, turnover_1d_cr, stocks
        FROM sector_rotation, latest
        WHERE trade_date = latest.d AND level = 'Industry'
        """
    )
    leading = pd.DataFrame()
    weakening = pd.DataFrame()
    if not rotation.empty:
        leading = rotation[rotation["rotation_state"].isin(["Leading", "Emerging"])].sort_values(
            ["rotation_rank", "score_change_5d"], ascending=[True, False]
        ).head(8)
        weakening = rotation[rotation["rotation_state"].isin(["Weakening", "Lagging"])].sort_values(
            ["rank_change_5d", "score_change_5d"], ascending=[True, True]
        ).head(8)

    with ui.grid(columns=2).classes("w-full gap-3 mb-2"):
        with ui.column().classes("w-full"):
            ui.label("Leading / Emerging industries").classes("mp-section-title")
            if leading.empty:
                ui.label("No leading groups.").classes("text-[var(--mp-muted)] text-sm")
            else:
                table_from_df(
                    leading[["group_name", "rotation_state", "rotation_rank", "score_change_5d", "rank_change_5d", "return_1m_pct", "rs_percentile", "turnover_1d_cr"]],
                    "",
                    pagination=8,
                    copy_symbols=False,
                )
        with ui.column().classes("w-full"):
            ui.label("Weakening / Lagging industries").classes("mp-section-title")
            if weakening.empty:
                ui.label("No weak groups flagged.").classes("text-[var(--mp-muted)] text-sm")
            else:
                table_from_df(
                    weakening[["group_name", "rotation_state", "rotation_rank", "score_change_5d", "rank_change_5d", "return_1m_pct", "rs_percentile", "turnover_1d_cr"]],
                    "",
                    pagination=8,
                    copy_symbols=False,
                )

    # What changed since prior session
    ui.label("What changed").classes("mp-section-title mt-2")
    if prev_d is None:
        ui.label("Need at least two sessions for change detection.").classes("text-[var(--mp-muted)] text-sm")
    else:
        changes = df_query(
            """
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
            prev AS (
                SELECT max(trade_date) d FROM indicators_daily, latest
                WHERE trade_date < latest.d
            ),
            cur AS (
                SELECT i.symbol, i.vcp_state, i.vcp_score, i.ema_10_cross_200, i.fresh_200ema_reclaim,
                       i.is_vcp, i.rs_percentile, i.close_price, i.ema_200,
                       m.market_cap_cr, m.industry, m.sector
                FROM indicators_daily i
                JOIN stocks_master m USING(symbol), latest
                WHERE i.trade_date = latest.d AND coalesce(m.market_cap_cr, 0) >= 1000
            ),
            old AS (
                SELECT i.symbol, i.vcp_state, i.vcp_score, i.ema_10_cross_200, i.is_vcp
                FROM indicators_daily i, prev
                WHERE i.trade_date = prev.d
            ),
            deals_today AS (
                SELECT symbol,
                       sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_cr,
                       sum(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) AS sell_cr
                FROM deals, latest
                WHERE trade_date = latest.d
                GROUP BY symbol
            )
            SELECT c.symbol,
                   CASE
                     WHEN c.ema_10_cross_200 AND NOT coalesce(o.ema_10_cross_200, false) THEN 'New 10/200 cross'
                     WHEN c.fresh_200ema_reclaim THEN '200EMA reclaim'
                     WHEN c.vcp_state = 'Near Pivot' AND coalesce(o.vcp_state, '') <> 'Near Pivot' THEN 'New Near Pivot'
                     WHEN c.vcp_state = 'Breakout' AND coalesce(o.vcp_state, '') <> 'Breakout' THEN 'New Breakout'
                     WHEN c.is_vcp AND NOT coalesce(o.is_vcp, false) THEN 'Entered VCP'
                     WHEN coalesce(d.buy_cr, 0) >= 5 THEN 'Large buy deal'
                     WHEN coalesce(d.sell_cr, 0) >= 5 THEN 'Large sell deal'
                     ELSE 'Improved structure'
                   END AS change_type,
                   c.vcp_state, c.vcp_score, c.rs_percentile,
                   coalesce(d.buy_cr, 0) AS buy_deal_cr, coalesce(d.sell_cr, 0) AS sell_deal_cr,
                   c.industry, c.sector, c.close_price, c.market_cap_cr
            FROM cur c
            LEFT JOIN old o USING(symbol)
            LEFT JOIN deals_today d USING(symbol)
            WHERE (c.ema_10_cross_200 AND NOT coalesce(o.ema_10_cross_200, false))
               OR c.fresh_200ema_reclaim
               OR (c.vcp_state = 'Near Pivot' AND coalesce(o.vcp_state, '') <> 'Near Pivot')
               OR (c.vcp_state = 'Breakout' AND coalesce(o.vcp_state, '') <> 'Breakout')
               OR (c.is_vcp AND NOT coalesce(o.is_vcp, false) AND c.vcp_score >= 60)
               OR coalesce(d.buy_cr, 0) >= 5
               OR coalesce(d.sell_cr, 0) >= 5
            ORDER BY
                CASE
                  WHEN c.ema_10_cross_200 THEN 1
                  WHEN c.vcp_state = 'Near Pivot' THEN 2
                  WHEN c.fresh_200ema_reclaim THEN 3
                  WHEN coalesce(d.buy_cr, 0) >= 5 THEN 4
                  ELSE 5
                END,
                c.rs_percentile DESC NULLS LAST
            LIMIT 40
            """
        )
        if changes.empty:
            ui.label(f"No high-signal changes vs {prev_d} (or filters too tight).").classes("text-[var(--mp-muted)] text-sm")
        else:
            ui.label(f"vs prior session {prev_d} · MCap ≥ 1000 Cr").classes("mp-rule text-xs")
            table_from_df(
                changes[[
                    "symbol", "change_type", "vcp_state", "vcp_score", "rs_percentile",
                    "buy_deal_cr", "sell_deal_cr", "industry", "close_price", "market_cap_cr",
                ]],
                "Session changes",
                pagination=15,
            )

    # Ranked preparation list
    ui.label("Preparation list").classes("mp-section-title mt-3")
    ui.label(
        "Mixed confluence rank: RS + VCP structure + industry state + deal flow − risk penalties. "
        "Evidence in Why / Risks — not a black-box buy signal."
    ).classes("mp-rule text-xs mb-2")

    prep = df_query(
        """
        WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
        deal_sum AS (
            SELECT symbol,
                   sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_deal_cr,
                   sum(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) AS sell_deal_cr,
                   max(repeated_client_count) AS repeated_client_count
            FROM deals, latest
            WHERE trade_date >= latest.d - INTERVAL 20 DAY
            GROUP BY symbol
        ),
        latest_rows AS (
            SELECT i.symbol, i.close_price, i.ema_200, i.ema_10,
                   i.rs_percentile, i.rs_1y_percentile, i.rs_3m_percentile,
                   i.vcp_score, i.vcp_state, i.trend_score, i.contraction_score,
                   i.volume_dryup_score, i.pivot_proximity_score,
                   i.away_52w_high_pct, i.away_10ema_pct, i.rvol,
                   i.ema_stack_bullish, i.fresh_200ema_reclaim, i.delivery_spike,
                   i.return_5d_pct, i.return_1m_pct, i.avg_volume_20d, i.turnover_cr,
                   m.market_cap_cr, m.band, m.sector, m.industry, m.broad_industry, m.pe,
                   sr_i.rotation_state AS industry_state,
                   sr_s.rotation_state AS sector_state,
                   coalesce(d.buy_deal_cr, 0) AS buy_deal_cr,
                   coalesce(d.sell_deal_cr, 0) AS sell_deal_cr,
                   coalesce(d.repeated_client_count, 0) AS repeated_client_count,
                   (
                       coalesce(i.rs_percentile, 0) * 0.35
                       + coalesce(i.vcp_score, 0) * 0.25
                       + coalesce(i.return_1m_pct, 0) * 0.35
                       + CASE WHEN i.away_52w_high_pct BETWEEN -12 AND 3 THEN 10 ELSE 0 END
                       + CASE WHEN i.ema_stack_bullish THEN 8 ELSE 0 END
                       + CASE WHEN i.fresh_200ema_reclaim THEN 6 ELSE 0 END
                       + CASE WHEN i.vcp_state IN ('Near Pivot', 'Breakout') THEN 8
                              WHEN i.vcp_state = 'Building Base' THEN 4 ELSE 0 END
                       + least(coalesce(d.buy_deal_cr, 0), 30) * 0.7
                       + CASE WHEN coalesce(d.repeated_client_count, 0) >= 2 THEN 4 ELSE 0 END
                       + CASE sr_i.rotation_state
                           WHEN 'Leading' THEN 10 WHEN 'Emerging' THEN 8 WHEN 'Improving' THEN 5
                           WHEN 'Weakening' THEN -6 WHEN 'Lagging' THEN -10 ELSE 0 END
                       + CASE sr_s.rotation_state
                           WHEN 'Leading' THEN 4 WHEN 'Emerging' THEN 3 WHEN 'Improving' THEN 2
                           WHEN 'Weakening' THEN -3 WHEN 'Lagging' THEN -5 ELSE 0 END
                       - CASE WHEN coalesce(d.sell_deal_cr, 0) > coalesce(d.buy_deal_cr, 0)
                               AND coalesce(d.sell_deal_cr, 0) >= 5 THEN 8 ELSE 0 END
                       - CASE WHEN coalesce(m.band, 99) <= 5 THEN 12 ELSE 0 END
                       - CASE WHEN coalesce(i.away_10ema_pct, 0) > 10 THEN 6 ELSE 0 END
                       - CASE WHEN i.vcp_state = 'Failed Breakout' THEN 10 ELSE 0 END
                   ) AS prep_score
            FROM indicators_daily i
            JOIN stocks_master m USING(symbol)
            LEFT JOIN deal_sum d USING(symbol)
            LEFT JOIN sector_rotation sr_i
                ON sr_i.trade_date = (SELECT d FROM latest)
               AND sr_i.level = 'Industry' AND sr_i.group_name = m.industry
            LEFT JOIN sector_rotation sr_s
                ON sr_s.trade_date = (SELECT d FROM latest)
               AND sr_s.level = 'Sector' AND sr_s.group_name = m.sector, latest
            WHERE i.trade_date = latest.d
              AND coalesce(m.market_cap_cr, 0) >= 1000
              AND coalesce(i.avg_volume_20d, 0) >= 200000
              AND (i.ema_200 IS NULL OR i.close_price > i.ema_200)
              AND coalesce(i.rs_percentile, 0) >= 65
              AND (
                    i.vcp_score >= 50
                 OR i.ema_stack_bullish
                 OR i.fresh_200ema_reclaim
                 OR i.vcp_state IN ('Near Pivot', 'Building Base', 'Breakout')
                 OR coalesce(d.buy_deal_cr, 0) >= 3
                 OR i.away_52w_high_pct BETWEEN -10 AND 2
              )
        )
        SELECT * FROM latest_rows
        ORDER BY prep_score DESC NULLS LAST, rs_percentile DESC NULLS LAST
        LIMIT 40
        """
    )

    if prep.empty:
        ui.label("No prep candidates match filters (MCap≥1000, RS≥65, above 200EMA, setup confluence).").classes("text-[var(--mp-muted)]")
        return

    why_list = []
    risk_list = []
    for _, row in prep.iterrows():
        w, r = _build_why_risk(row)
        why_list.append(w)
        risk_list.append(r)
    prep = prep.copy()
    prep["why"] = why_list
    prep["risks"] = risk_list
    prep["setup"] = prep["vcp_state"].fillna("").replace("", "Structure")

    with ui.row().classes("gap-3 flex-wrap mb-2 items-center"):
        compact_kpi("Candidates", len(prep))
        compact_kpi("Top", str(prep.iloc[0]["symbol"]))
        compact_kpi("Top score", f"{float(prep.iloc[0]['prep_score']):.0f}")
        copy_button("Copy prep symbols", lambda: symbols_text(prep.head(25)))

    show_cols = [
        "symbol", "prep_score", "setup", "why", "risks",
        "rs_percentile", "rs_1y_percentile", "vcp_score",
        "industry_state", "sector_state",
        "buy_deal_cr", "sell_deal_cr",
        "away_52w_high_pct", "away_10ema_pct",
        "return_1m_pct", "close_price", "market_cap_cr",
        "industry", "sector",
    ]
    table_from_df(
        prep[[c for c in show_cols if c in prep.columns]],
        f"Ranked prep · session {latest_d}",
        pagination=20,
    )

    # High-value institutional buys with structure
    deals_hot = df_query(
        """
        WITH latest AS (SELECT max(trade_date) d FROM indicators_daily),
        deal_sum AS (
            SELECT symbol,
                   sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) AS buy_deal_cr,
                   sum(CASE WHEN side='SELL' THEN deal_value_cr ELSE 0 END) AS sell_deal_cr
            FROM deals, latest
            WHERE trade_date >= latest.d - INTERVAL 10 DAY
            GROUP BY symbol
            HAVING sum(CASE WHEN side='BUY' THEN deal_value_cr ELSE 0 END) >= 5
        )
        SELECT i.symbol, d.buy_deal_cr, d.sell_deal_cr, i.rs_percentile, i.vcp_score, i.vcp_state,
               i.away_52w_high_pct, m.industry, m.sector, m.market_cap_cr, i.close_price
        FROM deal_sum d
        JOIN indicators_daily i USING(symbol)
        JOIN stocks_master m USING(symbol), latest
        WHERE i.trade_date = latest.d
          AND coalesce(m.market_cap_cr, 0) >= 1000
          AND (i.ema_200 IS NULL OR i.close_price > i.ema_200)
        ORDER BY d.buy_deal_cr DESC, i.rs_percentile DESC
        LIMIT 15
        """
    )
    if not deals_hot.empty:
        ui.label("Institutional buy + tradable structure (10d)").classes("mp-section-title mt-3")
        table_from_df(deals_hot, "", pagination=10)


def _lazy_panel(build_fn, loaded: dict, key: str):
    """Build page content once when its tab is first shown."""
    host = ui.column().classes("w-full")

    def ensure():
        if loaded.get(key):
            return
        loaded[key] = True
        with host:
            build_fn()

    return ensure


def main() -> None:
    add_styles()
    if not DB_PATH.exists():
        ui.label(f"Database not found: {DB_PATH}. Run Update_MarketPulse.bat first.").classes("text-red-600 text-lg")
        ui.run(title="MarketPulse", reload=False, port=8080)
        return
    ensure_runtime_schema()
    app_header()

    loaded: dict[str, bool] = {}
    specialist_pages = {
        "Market Health": market_health_page,
        "Sector Rotation": sector_rotation_page,
        "Strong Groups": strong_groups_page,
        "Focus List": strong_rs_stocks_page,
        "Screeners": screener_page,
        "VCP Lab": vcp_lab_page,
        "Momentum Scanner": special_watchlist_page,
        "Deals": deals_page,
        "Stock Detail": stock_detail_page,
        "Sector Tree": sector_tree_page,
        "Leaders Study": backtest_page,
        "Journal": journal_page,
    }
    tab_specs = [
        ("Today", lambda: render_today(DB_PATH), "today", True),
        ("Watchlist", lambda: render_watchlist(DB_PATH), "watchlist", False),
        ("Research", lambda: render_research(specialist_pages), "research", False),
    ]

    with ui.tabs().classes("w-full bg-white text-[#28251d] shadow-sm border-b") as tabs:
        tab_els = {name: ui.tab(name) for name, _, _, _ in tab_specs}

    ensure_by_name: dict[str, callable] = {}
    with ui.tab_panels(tabs, value=tab_els["Today"]).classes("w-full p-4"):
        for name, build_fn, key, eager in tab_specs:
            with ui.tab_panel(tab_els[name]):
                ensure_by_name[name] = _lazy_panel(build_fn, loaded, key)
                if eager:
                    ensure_by_name[name]()

    def on_tab_change(e):
        val = getattr(e, "value", None)
        if val is None:
            val = tabs.value
        name = getattr(val, "text", None) or str(val)
        # NiceGUI sometimes returns the tab label string directly
        if name in ensure_by_name:
            ensure_by_name[name]()
            return
        # Match tab element identity
        for label, el in tab_els.items():
            if val is el or str(val) == label:
                ensure_by_name[label]()
                return

    tabs.on_value_change(on_tab_change)
    ui.run(title="MarketPulse", reload=False, port=8080)


if __name__ in {"__main__", "__mp_main__"}:
    main()
