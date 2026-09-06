"""MarketPulse Terminal Bar: Market Ticker Ribbon, Global Search (Ctrl+K), and Session Replay."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd
from nicegui import ui

try:
    from App.ui.stock_drawer import open_stock_360_modal
except ModuleNotFoundError:
    from ui.stock_drawer import open_stock_360_modal  # type: ignore


_STOCKS_CACHE: list[dict[str, Any]] = []


def load_stocks_master_cache(db_path: Path) -> list[dict[str, Any]]:
    """Load stock symbol master for fast autocomplete."""
    global _STOCKS_CACHE
    if _STOCKS_CACHE:
        return _STOCKS_CACHE
    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            df = db.execute(
                """
                SELECT symbol, coalesce(security_name, symbol) AS name,
                       coalesce(sector, 'Other') AS sector,
                       coalesce(industry, '') AS industry,
                       latest_close AS cmp, market_cap_cr
                FROM stocks_master
                WHERE symbol IS NOT NULL
                ORDER BY coalesce(market_cap_cr, 0) DESC
                """
            ).fetchdf()
            _STOCKS_CACHE = df.to_dict(orient="records")
    except Exception:
        _STOCKS_CACHE = []
    return _STOCKS_CACHE


def fetch_market_indices(db_path: Path, trade_date: str | None = None) -> list[dict[str, Any]]:
    """Fetch benchmark index returns from index_daily."""
    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            if trade_date:
                df = db.execute(
                    """
                    SELECT index_name, close_price, return_1d_pct, previous_close, trade_date
                    FROM index_daily
                    WHERE trade_date = ?
                      AND index_name IN ('Nifty 50', 'Nifty Bank', 'NIFTY MIDCAP 100', 'NIFTY SMLCAP 100', 'India VIX')
                    ORDER BY CASE index_name
                        WHEN 'Nifty 50' THEN 1
                        WHEN 'Nifty Bank' THEN 2
                        WHEN 'NIFTY MIDCAP 100' THEN 3
                        WHEN 'NIFTY SMLCAP 100' THEN 4
                        WHEN 'India VIX' THEN 5
                        ELSE 6 END
                    """,
                    [trade_date],
                ).fetchdf()
            else:
                df = db.execute(
                    """
                    WITH latest AS (SELECT max(trade_date) AS max_d FROM index_daily)
                    SELECT index_name, close_price, return_1d_pct, previous_close, trade_date
                    FROM index_daily i JOIN latest l ON i.trade_date = l.max_d
                    WHERE index_name IN ('Nifty 50', 'Nifty Bank', 'NIFTY MIDCAP 100', 'NIFTY SMLCAP 100', 'India VIX')
                    ORDER BY CASE index_name
                        WHEN 'Nifty 50' THEN 1
                        WHEN 'Nifty Bank' THEN 2
                        WHEN 'NIFTY MIDCAP 100' THEN 3
                        WHEN 'NIFTY SMLCAP 100' THEN 4
                        WHEN 'India VIX' THEN 5
                        ELSE 6 END
                    """
                ).fetchdf()

            results = []
            for _, r in df.iterrows():
                raw_pct = float(r["return_1d_pct"] or 0)
                name = str(r["index_name"])
                if name == "NIFTY MIDCAP 100":
                    short_name = "MIDCAP 100"
                elif name == "NIFTY SMLCAP 100":
                    short_name = "SMLCAP 100"
                else:
                    short_name = name
                is_vix = "VIX" in name
                tone = "good" if (raw_pct < 0 if is_vix else raw_pct >= 0) else "bad"
                results.append(
                    {
                        "name": short_name,
                        "close": float(r["close_price"] or 0),
                        "return_pct": raw_pct,
                        "tone": tone,
                        "date": str(r["trade_date"])[:10],
                    }
                )
            return results
    except Exception:
        return []


def render_market_ticker_ribbon(db_path: Path, trade_date: str | None = None) -> None:
    """Render a dense horizontal benchmark ticker bar."""
    indices = fetch_market_indices(db_path, trade_date)
    if not indices:
        return

    with ui.row().classes("w-full items-center justify-between px-3 py-1 bg-[var(--mp-surface)] border-b border-[var(--mp-border)] text-xs"):
        with ui.row().classes("items-center gap-4 flex-wrap"):
            for idx in indices:
                is_positive = idx["return_pct"] >= 0
                sign = "+" if is_positive else ""
                color_class = "text-emerald-400" if is_positive else "text-rose-400"
                arrow = "▲" if is_positive else "▼"
                with ui.row().classes("items-center gap-1.5"):
                    ui.label(idx["name"]).classes("text-[var(--mp-muted)] font-semibold text-[11px] tracking-wide")
                    ui.label(f"{idx['close']:,.1f}").classes("text-[var(--mp-text)] font-mono font-medium text-[11px]")
                    ui.label(f"{arrow} {sign}{idx['return_pct']:.2f}%").classes(f"{color_class} font-mono font-semibold text-[11px]")


def render_global_search(db_path: Path, copy_text: Callable | None = None) -> None:
    """Render search bar with quick shortcut Ctrl+K and stock master autocomplete."""
    stocks = load_stocks_master_cache(db_path)
    options = {
        s["symbol"]: f"{s['symbol']} · {s['name'][:22]} ({s['sector']}) ₹{s['cmp']:,.0f}" if s.get("cmp") else f"{s['symbol']} · {s['name'][:22]}"
        for s in stocks
    }

    def on_stock_select(event):
        sym = str(event.value or "").strip()
        if sym and sym in options:
            open_stock_360_modal(db_path, sym, copy_text=copy_text)
            search_select.value = None

    search_select = ui.select(
        options=options,
        with_input=True,
        on_change=on_stock_select,
    ).props('dense outlined dark use-input hide-dropdown-icon input-debounce=150 placeholder="Quick Search (Ctrl+K)..."').classes("w-56 text-xs")

    # Bind Ctrl+K keyboard shortcut
    ui.keyboard(
        on_key=lambda e: search_select.run_method("focus") if (e.key == "k" and e.modifiers.ctrl) else None
    )
