"""MarketPulse Watchlist Hub: Dedicated management for WL1, WL2, and WL3 with TradingView export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd
from nicegui import ui

try:
    from App.ui.stock_drawer import open_stock_360_modal, toggle_watchlist_symbol
except ModuleNotFoundError:
    from ui.stock_drawer import open_stock_360_modal, toggle_watchlist_symbol  # type: ignore


def load_watchlist_symbols(user_db: Path, wl_num: int) -> list[str]:
    """Retrieve list of symbols in watchlist 1, 2, or 3."""
    key = f"watchlist_{wl_num}"
    try:
        with duckdb.connect(str(user_db), read_only=True) as db:
            r = db.execute("SELECT setting_value FROM portfolio_settings WHERE setting_key = ?", [key]).fetchone()
            if r and r[0]:
                data = json.loads(r[0])
                return sorted(list(data)) if isinstance(data, list) else []
            return []
    except Exception:
        return []


def clear_watchlist_symbols(user_db: Path, wl_num: int) -> None:
    """Clear all symbols from watchlist."""
    key = f"watchlist_{wl_num}"
    try:
        with duckdb.connect(str(user_db)) as db:
            db.execute(
                """
                INSERT INTO portfolio_settings (setting_key, setting_value, updated_at)
                VALUES (?, '[]', now())
                ON CONFLICT (setting_key) DO UPDATE SET
                    setting_value = '[]',
                    updated_at = now()
                """,
                [key],
            )
    except Exception:
        pass


def fetch_watchlist_table_data(db_path: Path, symbols: list[str]) -> pd.DataFrame:
    """Query live technical metrics for symbols in watchlist."""
    if not symbols:
        return pd.DataFrame()
    clause = ", ".join([f"'{s}'" for s in symbols])
    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            df = db.execute(
                f"""
                WITH latest AS (SELECT max(trade_date) AS max_d FROM indicators_daily)
                SELECT i.symbol,
                       coalesce(m.security_name, i.symbol) AS security_name,
                       coalesce(m.sector, 'Other') AS sector,
                       round(i.close_price, 2) AS cmp,
                       round(coalesce(i.return_5d_pct, 0), 1) AS return_5d_pct,
                       round(coalesce(i.rs_percentile, 50), 1) AS rs_percentile,
                       round(coalesce(i.away_10ema_pct, 0), 1) AS away_10ema_pct,
                       round(coalesce(i.away_52w_high_pct, 0), 1) AS away_52w_high_pct,
                       round(coalesce(i.turnover_cr, 0), 1) AS turnover_cr,
                       round(coalesce(i.rvol, 1), 1) AS rvol,
                       CASE WHEN coalesce(i.away_10ema_pct, 0) >= 0 AND coalesce(i.ema_stack_bullish, false) THEN 'Bullish' ELSE 'Neutral' END AS trend_state
                FROM indicators_daily i
                JOIN latest l ON i.trade_date = l.max_d
                LEFT JOIN stocks_master m ON i.symbol = m.symbol
                WHERE i.symbol IN ({clause})
                ORDER BY i.rs_percentile DESC
                """
            ).fetchdf()
            return df
    except Exception:
        return pd.DataFrame()


def build_watchlist_page(
    db_path: Path,
    user_db_path: Path,
    *,
    copy_text: Callable[[str, str], None],
    table_from_df: Callable[..., Any],
) -> None:
    """Render the Dedicated Watchlists Hub workspace."""
    active_wl = {"num": 1}
    table_container = ui.column().classes("w-full")

    with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap mb-3"):
        with ui.column().classes("gap-0"):
            ui.label("Custom Watchlists").classes("mp-page-title")
            ui.label("Personal curated watchlists synced across the stock drawer and terminal.").classes("mp-page-subtitle")

        with ui.row().classes("items-center gap-2"):
            tv_btn = ui.button("Copy for TradingView").props("outline dense").classes("mp-button text-xs")
            clear_btn = ui.button("Clear Watchlist").props("flat dense").classes("text-xs text-rose-400 hover:bg-rose-950/30")

    def format_tv_symbols(syms: list[str]) -> str:
        return ", ".join([f"NSE:{s.replace('-', '_')}" for s in syms])

    def render_content() -> None:
        table_container.clear()
        symbols = load_watchlist_symbols(user_db_path, active_wl["num"])

        with table_container:
            with ui.row().classes("items-center gap-3 mb-2 flex-wrap"):
                ui.label(f"WL{active_wl['num']} ({len(symbols)} stocks)").classes("text-sm font-semibold text-[var(--mp-text)]")

                # Quick add input
                def _add_sym(e):
                    val = str(add_input.value or "").strip().upper()
                    if val:
                        toggle_watchlist_symbol(user_db_path, active_wl["num"], val)
                        add_input.value = ""
                        render_content()

                add_input = ui.input(placeholder="Add symbol e.g. TRENT").props("dense outlined dark clearable").classes("w-44 text-xs")
                add_input.on("keydown.enter", _add_sym)

            if not symbols:
                ui.label(f"No symbols in Watchlist {active_wl['num']}. Tag stocks using WL{active_wl['num']} in the Stock 360 Drawer or add above.").classes("text-sm text-[var(--mp-muted)] py-8 text-center w-full")
                return

            df = fetch_watchlist_table_data(db_path, symbols)
            if not df.empty:
                table_from_df(df, "", pagination=25)

    def on_tab_change(num: int) -> None:
        active_wl["num"] = num
        render_content()

    with ui.row().classes("gap-1 mb-3"):
        for num, label in ((1, "WL1 · Swing Focus"), (2, "WL2 · Breakout Radar"), (3, "WL3 · Core Ideas")):
            ui.button(label, on_click=lambda n=num: on_tab_change(n)).props("dense outline").classes("mp-button text-xs")

    def _copy_tv():
        syms = load_watchlist_symbols(user_db_path, active_wl["num"])
        if syms:
            copy_text("TradingView Watchlist", format_tv_symbols(syms))
            ui.notify(f"Copied {len(syms)} symbols for TradingView", type="positive")
        else:
            ui.notify("Watchlist is empty", type="warning")

    def _clear_wl():
        clear_watchlist_symbols(user_db_path, active_wl["num"])
        ui.notify(f"Cleared WL{active_wl['num']}", type="info")
        render_content()

    tv_btn.on_click(_copy_tv)
    clear_btn.on_click(_clear_wl)

    render_content()
