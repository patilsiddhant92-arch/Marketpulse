"""SMA Trend Template scanner — own tab, Momentum-style checkboxes + TV copy.

SMAs are computed live from prices_daily. This DB does not persist sma_50/150/200
on indicators_daily, so reading those columns always yielded an empty list.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from nicegui import ui

try:
    from App.market_flags import annotate
    from App.ui.shell import page_shell
except ModuleNotFoundError:
    from market_flags import annotate  # type: ignore
    from ui.shell import page_shell  # type: ignore

try:
    from App.ui.stock_drawer import open_stock_360_modal
except ModuleNotFoundError:
    from ui.stock_drawer import open_stock_360_modal  # type: ignore

try:
    from App.ui.vcp_chart import render_vcp_ohlc
except ModuleNotFoundError:
    from ui.vcp_chart import render_vcp_ohlc  # type: ignore


CHECKS = (
    ("price_gt_150_200", "Price > 150 SMA and 200 SMA"),
    ("sma_150_gt_200", "150 SMA > 200 SMA"),
    ("sma_200_rising", "200 SMA up ≥ 1 month"),
    ("sma_50_gt_150", "50 SMA > 150 SMA"),
    ("sma_50_gt_200", "50 SMA > 200 SMA"),
    ("price_gt_50", "Price > 50 SMA"),
    ("rs_70", "RS ≥ 70"),
)


def scan_template(db_path: Path, min_mcap: float, min_avg_vol: float = 0.0) -> pd.DataFrame:
    """Latest session using pre-computed SMA 50/150/200 from indicators_daily, with prices_daily fallback."""
    db_path = Path(db_path)
    with duckdb.connect(str(db_path), read_only=True) as db:
        cols = {row[1] for row in db.execute("PRAGMA table_info(indicators_daily)").fetchall()}
        low_pct = "i.away_52w_low_pct" if "away_52w_low_pct" in cols else "NULL"
        avg_vol = "i.avg_volume_20d" if "avg_volume_20d" in cols else "NULL"

        if "sma_50" in cols and "sma_150" in cols and "sma_200" in cols:
            rising_col = "i.sma_200_rising" if "sma_200_rising" in cols else "(i.sma_200 > lag(i.sma_200, 20) over (partition by i.symbol order by i.trade_date))"
            return db.execute(
                f"""
                WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
                SELECT m.symbol, i.close_price, i.rs_percentile, i.away_52w_high_pct, {low_pct} AS away_52w_low_pct,
                       i.sma_50, i.sma_150, i.sma_200, {rising_col} AS sma_200_rising,
                       i.turnover_cr, i.rvol, i.delivery_pct, {avg_vol} AS avg_volume_20d,
                       m.market_cap_cr, m.sector, m.industry, m.band
                FROM indicators_daily i
                JOIN stocks_master m USING(symbol), latest
                WHERE i.trade_date = latest.d
                  AND coalesce(m.market_cap_cr, 0) >= ?
                  AND coalesce({avg_vol}, 0) >= ?
                """,
                [min_mcap, min_avg_vol],
            ).fetchdf()

        # Fallback for databases or test fixtures without pre-computed SMAs
        return db.execute(
            f"""
            WITH latest AS (
                SELECT max(trade_date) d FROM indicators_daily
            ),
            p_win1 AS (
                SELECT symbol, trade_date, close_price,
                       avg(close_price) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS sma_50,
                       avg(close_price) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 149 PRECEDING AND CURRENT ROW) AS sma_150,
                       avg(close_price) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma_200
                FROM prices_daily
            ),
            p_win2 AS (
                SELECT symbol, trade_date, sma_50, sma_150, sma_200,
                       lag(sma_200, 20) OVER (PARTITION BY symbol ORDER BY trade_date) AS sma_200_20d_ago
                FROM p_win1
            )
            SELECT m.symbol, i.close_price, i.rs_percentile, i.away_52w_high_pct, {low_pct} AS away_52w_low_pct,
                   p.sma_50, p.sma_150, p.sma_200, (p.sma_200 > p.sma_200_20d_ago) AS sma_200_rising,
                   i.turnover_cr, i.rvol, i.delivery_pct, {avg_vol} AS avg_volume_20d,
                   m.market_cap_cr, m.sector, m.industry, m.band
            FROM indicators_daily i
            JOIN stocks_master m USING(symbol)
            JOIN latest ON i.trade_date = latest.d
            LEFT JOIN p_win2 p ON p.symbol = i.symbol AND p.trade_date = latest.d
            WHERE coalesce(m.market_cap_cr, 0) >= ?
              AND coalesce({avg_vol}, 0) >= ?
            """,
            [min_mcap, min_avg_vol],
        ).fetchdf()


def pass_mask(
    frame: pd.DataFrame,
    enabled: dict[str, bool],
    min_rs: float,
    *,
    min_low_pct: float = 30.0,
    max_high_away: float = 25.0,
) -> pd.Series:
    close = pd.to_numeric(frame.get("close_price"), errors="coerce")
    s50 = pd.to_numeric(frame.get("sma_50"), errors="coerce")
    s150 = pd.to_numeric(frame.get("sma_150"), errors="coerce")
    s200 = pd.to_numeric(frame.get("sma_200"), errors="coerce")
    rs = pd.to_numeric(frame.get("rs_percentile"), errors="coerce")
    away_high = pd.to_numeric(frame.get("away_52w_high_pct"), errors="coerce")
    away_low = pd.to_numeric(frame.get("away_52w_low_pct"), errors="coerce")
    rising = frame.get("sma_200_rising")
    rise = rising.fillna(False).astype(bool) if rising is not None else pd.Series(False, index=frame.index)
    tests = {
        "price_gt_150_200": close.gt(s150) & close.gt(s200),
        "sma_150_gt_200": s150.gt(s200),
        "sma_200_rising": rise,
        "sma_50_gt_150": s50.gt(s150),
        "sma_50_gt_200": s50.gt(s200),
        "price_gt_50": close.gt(s50),
        "rs_70": rs.ge(min_rs),
    }
    mask = away_low.ge(min_low_pct).fillna(False) & away_high.ge(-abs(max_high_away)).fillna(False)
    for key, on in enabled.items():
        if on and key in tests:
            mask = mask & tests[key].fillna(False)
    return mask


def gate_counts(frame: pd.DataFrame, min_rs: float, min_low_pct: float, max_high_away: float) -> dict[str, int]:
    if frame.empty:
        return {key: 0 for key, _ in CHECKS}
    return {
        key: int(pass_mask(frame, {key: True}, min_rs, min_low_pct=min_low_pct, max_high_away=max_high_away).sum())
        for key, _ in CHECKS
    }


def build_sma_template_page(
    db_path: Path,
    *,
    table_from_df: Callable[..., Any],
    copy_text: Callable[[str, str], None],
) -> None:
    db_path = Path(db_path)
    page_shell(
        "SMA Trend Template",
        "SMA 50 / 150 / 200 computed from EOD prices. Tick gates, Run, copy to TradingView.",
        eyebrow="Scanner · Minervini SMA",
    )
    boxes: dict[str, Any] = {}
    with ui.row().classes("gap-3 items-center flex-wrap"):
        for key, label in CHECKS:
            boxes[key] = ui.checkbox(label, value=True)
    with ui.row().classes("gap-3 items-end flex-wrap mt-2"):
        min_mcap = ui.number("Min MCap Cr", value=1000).classes("w-36")
        min_avg_vol = ui.number("Min 20D Avg Vol", value=1_000_000).classes("w-40")
        min_low = ui.number("Min 52W Low %", value=30).classes("w-36")
        max_high = ui.number("Max 52W High %", value=25).classes("w-36")
        min_rs = ui.number("Min RS", value=70).classes("w-28")
        run_btn = ui.button("Run template").classes("mp-primary")
        copy_btn = ui.button("Copy TV").classes("mp-button")
    ui.label("52W Low % = minimum distance above the low (default 30). 52W High % = maximum distance below the high (default 25).").classes(
        "text-sm text-[var(--mp-muted)] mt-1"
    )
    host = ui.column().classes("w-full")
    tv_state = {"text": ""}

    def run() -> None:
        host.clear()
        enabled = {key: bool(box.value) for key, box in boxes.items()}
        try:
            frame = scan_template(
                db_path,
                float(min_mcap.value or 0),
                float(min_avg_vol.value or 0),
            )
        except Exception as exc:
            with host:
                ui.label(f"Cannot scan template: {exc}").classes("text-sm")
            ui.notify(f"Template scan failed: {exc}", type="negative")
            return
        if frame.empty:
            with host:
                ui.label("No names in the MCap / 20D vol universe, or prices_daily is empty.").classes("text-sm")
            tv_state["text"] = ""
            ui.notify("No names in universe", type="warning")
            return
        min_rs_v = float(min_rs.value or 70)
        min_low_v = float(min_low.value or 0)
        max_high_v = abs(float(max_high.value or 0))
        counts = gate_counts(frame, min_rs_v, min_low_v, max_high_v)
        hits = frame.loc[
            pass_mask(frame, enabled, min_rs_v, min_low_pct=min_low_v, max_high_away=max_high_v)
        ].copy()
        hits = annotate(hits, db_path)
        n90 = int((pd.to_numeric(hits.get("rs_percentile"), errors="coerce") >= 90).sum()) if not hits.empty else 0
        symbols = hits["symbol"].dropna().astype(str).str.upper().drop_duplicates().tolist() if not hits.empty else []
        tv_state["text"] = ",".join(f"NSE:{s.replace('-', '_')}" for s in symbols)
        sma_ready = int(pd.to_numeric(frame.get("sma_200"), errors="coerce").notna().sum())
        show = [
            c
            for c in [
                "symbol",
                "close_price",
                "rs_percentile",
                "away_52w_high_pct",
                "away_52w_low_pct",
                "sma_50",
                "sma_150",
                "sma_200",
                "avg_volume_20d",
                "turnover_cr",
                "deal_when",
                "sector",
                "industry",
                "market_cap_cr",
            ]
            if c in hits.columns
        ]
        with host:
            ui.label(
                f"{len(hits)} passed  ·  universe {len(frame)}  ·  200 SMA ready {sma_ready}  ·  RS ≥ 90: {n90}"
            ).classes("text-sm mt-2 font-semibold")
            with ui.row().classes("gap-3 flex-wrap mt-1"):
                for key, label in CHECKS:
                    ui.label(f"{label}: {counts.get(key, 0)}").classes("text-sm text-[var(--mp-text)]")
            if hits.empty:
                ui.label("No names passed the ticked gates. Untick a gate or lower Min RS.").classes("text-sm mt-2")
            else:
                table_from_df(
                    hits[show],
                    "SMA template",
                    pagination=25,
                    hidden_cols={
                        "is_top_sector",
                        "is_top_industry",
                        "is_improving_sector",
                        "is_improving_industry",
                        "has_deal",
                    },
                )
                sym_list = hits["symbol"].dropna().astype(str).tolist()
                if sym_list:
                    default_sym = sym_list[0]
                    with ui.card().classes("w-full mp-card p-3 mt-4 border border-[var(--mp-border)] bg-[var(--mp-surface-raised)]"):
                        with ui.row().classes("w-full items-center justify-between pb-2 border-b border-[var(--mp-border)] flex-wrap gap-2"):
                            with ui.row().classes("items-center gap-2"):
                                ui.label("📈 SMA Trend Template Chart Preview (OHLC + SMA 50/150/200 + RS)").classes("text-xs font-bold tracking-wider text-[var(--mp-primary)] uppercase")
                                sel = ui.select(sym_list, value=default_sym, label="Candidate").classes("w-44").props("dense outlined")
                            with ui.row().classes("items-center gap-2"):
                                ui.button("Open Stock 360 ↗", on_click=lambda: open_stock_360_modal(Path(db_path), str(sel.value), copy_text=copy_text)).classes("mp-button text-xs").props("dense outline")

                        chart_host = ui.column().classes("w-full mt-2")

                        def update_chart():
                            chart_host.clear()
                            sym = str(sel.value or "").strip().upper()
                            if not sym:
                                return
                            with chart_host:
                                render_vcp_ohlc(Path(db_path), sym)

                        sel.on_value_change(lambda _: update_chart())
                        update_chart()
        ui.notify(f"{len(hits)} names passed", type="positive" if len(hits) else "warning")

    def copy() -> None:
        if not tv_state["text"]:
            ui.notify("Run the template first", type="warning")
            return
        copy_text("SMA template TV", tv_state["text"])
        ui.notify("Copied TradingView list", type="positive")

    run_btn.on_click(run)
    copy_btn.on_click(copy)
    run()
