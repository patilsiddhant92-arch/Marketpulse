"""Sector board: turnover, trend, RS. Not a taxonomy tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd
from nicegui import ui

try:
    from App.market_status import load_market_status, non_actionable_message
    from App.market_summary import group_tape, group_trend, movers
    from App.ui.stock_drawer import open_stock_360_modal
    from App.ui.widgets import grouped_line_chart, return_heatmap
except ModuleNotFoundError:
    from market_status import load_market_status, non_actionable_message  # type: ignore
    from market_summary import group_tape, group_trend, movers  # type: ignore
    from ui.stock_drawer import open_stock_360_modal  # type: ignore
    from ui.widgets import grouped_line_chart, return_heatmap  # type: ignore


def build_sector_board_page(
    db_path: Path,
    *,
    copy_text: Callable[[str, str], None] | None = None,
    table_from_df: Callable[..., Any] | None = None,
) -> None:
    db_path = Path(db_path)
    with ui.column().classes("w-full mp-sector-page"):
        ui.label("Sectors").classes("mp-page-title")
        ui.label("Who took the rupees. Day / week / month trend. Not a classification tree.").classes("mp-page-subtitle")
        st = load_market_status(db_path, db_path.parent / "status.json")
        if not st.actionable:
            ui.label(non_actionable_message(st)).classes("mp-badge mp-bad w-full mt-2")

        level = ui.toggle(["sector", "industry"], value="sector").props("dense")
        host = ui.column().classes("w-full")

        def paint() -> None:
            host.clear()
            g = group_tape(db_path, level.value)
            cols = [c for c in ["grp", "n", "day_pct", "week_pct", "month_pct", "advance_pct", "above_50", "rs", "rs_rank", "t_o_today", "t_o_1w", "vs_20d"] if c in g.columns]
            with host:
                if g.empty:
                    ui.label("No group tape.").classes("text-sm text-[var(--mp-muted)]")
                    return
                ui.label("Return trend — top groups by turnover").classes("mp-section-title")
                trend = group_trend(db_path, str(level.value), top_n=6, days=21)
                grouped_line_chart(trend, date_col="trade_date", group_col="grp", value_col="day_pct")
                ui.label("Heatmap — day return").classes("mp-section-title mt-3")
                return_heatmap(g, name_col="grp", value_col="day_pct")
                if table_from_df:
                    table_from_df(g[cols], f"{level.value.title()} by turnover", pagination=30, copy_symbols=False)
                else:
                    ui.table(
                        columns=[{"name": c, "label": c, "field": c} for c in cols],
                        rows=g[cols].fillna("—").to_dict("records"),
                        pagination=20,
                    ).classes("w-full mp-table")
                names = [str(x) for x in g["grp"].head(8).tolist()] if "grp" in g.columns else []
                if names:
                    ui.label("Names in the top group").classes("mp-section-title mt-3")
                    mv = movers(db_path)
                    col = "sector" if level.value == "sector" else "industry"
                    top = names[0]
                    if col in mv.columns:
                        sub = mv[mv[col].astype(str) == top].sort_values("t_o_today", ascending=False).head(20)
                        show = [c for c in ["symbol", "day_pct", "week_pct", "month_pct", "t_o_today", "rvol", "rs_percentile", "industry", "market_cap_cr"] if c in sub.columns]
                        if table_from_df and not sub.empty:
                            table_from_df(sub[show], top, pagination=20)
                        elif not sub.empty:
                            for _, row in sub.head(8).iterrows():
                                ui.button(
                                    str(row["symbol"]),
                                    on_click=lambda s=str(row["symbol"]): open_stock_360_modal(db_path, s),
                                ).props("dense flat")

        level.on_value_change(lambda _: paint())
        paint()
