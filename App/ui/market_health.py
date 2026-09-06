"""Market Health Regime Strip & Breadth History Drill-down.

Inspired by Screening Mantis's 7-card regime strip with 90-session historical modal.
Provides immediate market context before opening screener or research tables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import duckdb
import pandas as pd
from nicegui import ui

try:
    from App.ui.widgets import chart_panel, line_chart
except ModuleNotFoundError:
    from ui.widgets import chart_panel, line_chart  # type: ignore


def query_market_health_summary(db_path: Path) -> dict[str, Any]:
    """Fetch current 7-card market health metrics and 1-session changes."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {}

    with duckdb.connect(str(db_path), read_only=True) as db:
        # 1. Fetch latest 2 rows from breadth_daily for day-over-day delta
        try:
            b_df = db.execute(
                """
                SELECT trade_date, stocks, advancers, decliners, unchanged,
                       advance_pct, above_20ema_pct, above_50ema_pct, above_200ema_pct,
                       near_52w_highs, vcp_candidates, breadth_state
                FROM breadth_daily
                ORDER BY trade_date DESC
                LIMIT 2
                """
            ).fetchdf()
        except Exception:
            b_df = pd.DataFrame()

        if b_df.empty:
            return {}

        today = b_df.iloc[0]
        yest = b_df.iloc[1] if len(b_df) > 1 else None

        tot_stocks = float(today.get("stocks") or 1)
        adv = float(today.get("advancers") or 0)
        dec = float(today.get("decliners") or 0)
        ad_net = ((adv - dec) / tot_stocks) * 100.0 if tot_stocks > 0 else 0.0

        if yest is not None:
            y_tot = float(yest.get("stocks") or 1)
            y_adv = float(yest.get("advancers") or 0)
            y_dec = float(yest.get("decliners") or 0)
            y_ad_net = ((y_adv - y_dec) / y_tot) * 100.0 if y_tot > 0 else 0.0
            ad_net_chg = ad_net - y_ad_net
            a20_chg = float(today.get("above_20ema_pct") or 0) - float(yest.get("above_20ema_pct") or 0)
            a200_chg = float(today.get("above_200ema_pct") or 0) - float(yest.get("above_200ema_pct") or 0)
            near52_chg = float(today.get("near_52w_highs") or 0) - float(yest.get("near_52w_highs") or 0)
            vcp_chg = float(today.get("vcp_candidates") or 0) - float(yest.get("vcp_candidates") or 0)
        else:
            ad_net_chg = 0.0
            a20_chg = 0.0
            a200_chg = 0.0
            near52_chg = 0.0
            vcp_chg = 0.0

        # 2. Query RSI>60 and Above Pivot from latest indicators_daily
        try:
            latest_d = today["trade_date"]
            ind_stat = db.execute(
                """
                SELECT
                    count(CASE WHEN rsi_14 >= 60 THEN 1 END) AS rsi_60_n,
                    count(CASE WHEN close_price >= (high_price + low_price + close_price) / 3.0 THEN 1 END) AS above_pivot_n
                FROM indicators_daily
                WHERE trade_date = ?
                """,
                [latest_d],
            ).fetchone()
            rsi_60_pct = (ind_stat[0] / tot_stocks * 100.0) if ind_stat and tot_stocks > 0 else 0.0
            pivot_pct = (ind_stat[1] / tot_stocks * 100.0) if ind_stat and tot_stocks > 0 else 0.0
        except Exception:
            rsi_60_pct = 0.0
            pivot_pct = 0.0

        near_52_pct = (float(today.get("near_52w_highs") or 0) / tot_stocks * 100.0) if tot_stocks > 0 else 0.0
        vcp_pct = (float(today.get("vcp_candidates") or 0) / tot_stocks * 100.0) if tot_stocks > 0 else 0.0

        return {
            "as_of": str(pd.to_datetime(today["trade_date"]).date()),
            "total_stocks": int(tot_stocks),
            "breadth_state": str(today.get("breadth_state") or "Unclassified"),
            "cards": [
                {
                    "key": "ad_net",
                    "title": "Advance / decline",
                    "value": f"{ad_net:+.1f}%",
                    "change": f"{ad_net_chg:+.1f} pts",
                    "tone": "good" if ad_net > 0 else "bad",
                    "context": f"{int(adv)} up · {int(dec)} down",
                    "column_series": "advance_pct",
                },
                {
                    "key": "above_20",
                    "title": "Above 20 EMA",
                    "value": f"{float(today.get('above_20ema_pct') or 0):.1f}%",
                    "change": f"{a20_chg:+.1f} pts",
                    "tone": "good" if float(today.get("above_20ema_pct") or 0) >= 50 else "bad",
                    "context": "Short-term trend breadth",
                    "column_series": "above_20ema_pct",
                },
                {
                    "key": "above_200",
                    "title": "Above 200 EMA",
                    "value": f"{float(today.get('above_200ema_pct') or 0):.1f}%",
                    "change": f"{a200_chg:+.1f} pts",
                    "tone": "good" if float(today.get("above_200ema_pct") or 0) >= 50 else "bad",
                    "context": "Long-term bull/bear regime",
                    "column_series": "above_200ema_pct",
                },
                {
                    "key": "rsi_60",
                    "title": "RSI above 60",
                    "value": f"{rsi_60_pct:.1f}%",
                    "change": "—",
                    "tone": "good" if rsi_60_pct >= 25 else "neutral",
                    "context": "High-momentum participation",
                    "column_series": None,
                },
                {
                    "key": "pivot",
                    "title": "Above daily pivot",
                    "value": f"{pivot_pct:.1f}%",
                    "change": "—",
                    "tone": "good" if pivot_pct >= 50 else "neutral",
                    "context": "Short-term price location",
                    "column_series": None,
                },
                {
                    "key": "near_52w",
                    "title": "Near 52W high",
                    "value": f"{near_52_pct:.1f}%",
                    "change": f"{near52_chg:+.0f} names",
                    "tone": "good" if near_52_pct >= 20 else "neutral",
                    "context": f"{int(today.get('near_52w_highs') or 0)} stocks within 10%",
                    "column_series": "near_52w_highs",
                },
                {
                    "key": "breakout",
                    "title": "Recent breakout",
                    "value": f"{vcp_pct:.1f}%",
                    "change": f"{vcp_chg:+.0f} names",
                    "tone": "good" if vcp_pct >= 15 else "neutral",
                    "context": f"{int(today.get('vcp_candidates') or 0)} VCP setups",
                    "column_series": "vcp_candidates",
                },
            ],
        }


def open_breadth_history_modal(db_path: Path, title: str, column_series: str | None = None) -> None:
    """Open interactive modal with 90-session history for the clicked breadth metric."""
    db_path = Path(db_path)
    with duckdb.connect(str(db_path), read_only=True) as db:
        df = db.execute(
            """
            SELECT trade_date, advance_pct, above_10ema_pct, above_20ema_pct,
                   above_50ema_pct, above_200ema_pct, new_20d_highs, near_52w_highs,
                   vcp_candidates, breadth_state
            FROM breadth_daily
            ORDER BY trade_date ASC
            """
        ).fetchdf()

    dialog = ui.dialog().classes("mp-dialog")
    with dialog, ui.card().classes("mp-card p-6 w-[780px] max-w-full"):
        with ui.row().classes("w-full items-center justify-between pb-3 border-b border-[var(--mp-border)]"):
            with ui.column().classes("gap-0"):
                ui.label(f"Market Breadth History · {title}").classes("text-lg font-bold text-[var(--mp-text)]")
                ui.label("Historical trend across the active universe (latest 90 sessions)").classes("text-xs text-[var(--mp-muted)]")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense").classes("text-[var(--mp-muted)]")

        if df.empty:
            ui.label("No breadth history found.").classes("text-sm text-[var(--mp-muted)] py-4")
        else:
            active_col = column_series if (column_series and column_series in df.columns) else "advance_pct"
            line_chart(
                df,
                date_col="trade_date",
                series={title: active_col},
                series_tones={title: "good" if "advance" in active_col or "high" in active_col else "info"},
                area=True,
            )

        with ui.row().classes("w-full justify-end mt-4"):
            ui.button("Close", on_click=dialog.close).props("outline dense").classes("mp-button")

    dialog.open()


def render_market_health_strip(db_path: Path) -> None:
    """Render the collapsible 7-card market health strip at the top of a page."""
    data = query_market_health_summary(db_path)
    if not data:
        return

    cards = data.get("cards", [])
    as_of = data.get("as_of", "—")
    stocks_n = data.get("total_stocks", 0)
    posture = data.get("breadth_state", "Neutral")

    container = ui.element("section").classes("mp-market-health-strip w-full mb-3")
    with container:
        with ui.row().classes("w-full items-center justify-between gap-2 px-1 py-1 mp-health-header"):
            with ui.row().classes("items-center gap-2"):
                ui.label("Market Health").classes("text-xs font-bold uppercase tracking-wider text-[var(--mp-text-subtle)]")
                ui.label(f"{as_of} · {stocks_n:,} stocks").classes("text-xs text-[var(--mp-muted)]")
                state_tone = "mp-good" if "improv" in posture.lower() or "broad" in posture.lower() else "mp-bad" if "weak" in posture.lower() else "mp-neutral"
                ui.label(posture).classes(f"mp-badge {state_tone} text-[10px]")

            toggle_btn = ui.button("Hide market health").props("flat dense").classes("text-[11px] text-[var(--mp-muted)]")

        cards_row = ui.element("div").classes("grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 w-full mt-1 mp-health-grid")
        with cards_row:
            for c in cards:
                tone = c.get("tone", "neutral")
                tone_border = "border-emerald-500/30" if tone == "good" else "border-rose-500/30" if tone == "bad" else "border-slate-700/50"
                tone_text = "text-emerald-400" if tone == "good" else "text-rose-400" if tone == "bad" else "text-slate-300"
                
                with ui.card().classes(
                    f"p-2.5 rounded-md bg-[var(--mp-surface-raised)] border {tone_border} hover:border-[var(--mp-primary)] transition-all cursor-pointer select-none flex flex-col justify-between min-h-[76px]"
                ).on("click", lambda _, card=c: open_breadth_history_modal(db_path, card["title"], card["column_series"])):
                    with ui.row().classes("w-full items-center justify-between gap-1"):
                        ui.label(c["title"]).classes("text-[11px] font-medium text-[var(--mp-text-muted)] truncate")
                        ui.label(c["change"]).classes("text-[10px] text-[var(--mp-muted)]")
                    ui.label(c["value"]).classes(f"text-base font-bold {tone_text} my-0.5")
                    ui.label(c["context"]).classes("text-[10px] text-[var(--mp-text-subtle)] truncate")

        # Collapse / Expand toggle
        is_expanded = [True]

        def _toggle():
            is_expanded[0] = not is_expanded[0]
            if is_expanded[0]:
                cards_row.set_visibility(True)
                toggle_btn.set_text("Hide market health")
            else:
                cards_row.set_visibility(False)
                toggle_btn.set_text("Show market health")

        toggle_btn.on_click(_toggle)
