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

try:
    from App.cache_manager import get_cached, set_cached, cache_key
except ModuleNotFoundError:
    try:
        from cache_manager import get_cached, set_cached, cache_key  # type: ignore
    except ModuleNotFoundError:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from cache_manager import get_cached, set_cached, cache_key  # type: ignore

try:
    from Scripts.price_views import ohlcv_columns
except ModuleNotFoundError:
    from price_views import ohlcv_columns  # type: ignore


CHECKS = (
    ("price_gt_150_200", "Price > 150 SMA and 200 SMA"),
    ("sma_150_gt_200", "150 SMA > 200 SMA"),
    ("sma_200_rising", "200 SMA up ≥ 1 month"),
    ("sma_50_gt_150", "50 SMA > 150 SMA"),
    ("sma_50_gt_200", "50 SMA > 200 SMA"),
    ("price_gt_50", "Price > 50 SMA"),
    ("rs_70", "RS ≥ 70"),
)


def query_stage2_universe_trend(db_path: Path) -> dict[str, Any]:
    """Query macro historical expansion/contraction of Stage 2 passing stocks across all sessions."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"dates": [], "pass_count": [], "total_stocks": [], "pass_pct": []}
    ckey = cache_key(db_path, "latest", "stage2_universe_trend")
    cached = get_cached(ckey)
    if cached is not None:
        return cached

    with duckdb.connect(str(db_path), read_only=True) as db:
        cols = {row[1] for row in db.execute("PRAGMA table_info(indicators_daily)").fetchall()}
        if not cols:
            res = {"dates": [], "pass_count": [], "total_stocks": [], "pass_pct": []}
            set_cached(ckey, res)
            return res

        if "trend_template_pass" in cols:
            pass_expr = "count(CASE WHEN trend_template_pass THEN 1 END)"
        elif "close_price" in cols and "sma_200" in cols:
            pass_expr = "count(CASE WHEN close_price > sma_200 THEN 1 END)"
        else:
            pass_expr = "0"

        df = db.execute(
            f"""
            SELECT trade_date,
                   {pass_expr} AS pass_count,
                   count(*) AS total_stocks,
                   round({pass_expr} * 100.0 / NULLIF(count(*), 0), 1) AS pass_pct
            FROM indicators_daily
            GROUP BY trade_date
            ORDER BY trade_date ASC
            """
        ).fetchdf()

    if df.empty:
        res = {"dates": [], "pass_count": [], "total_stocks": [], "pass_pct": []}
        set_cached(ckey, res)
        return res

    dates = [str(pd.to_datetime(d).strftime("%Y-%m-%d")) for d in df["trade_date"]]
    pass_cnt = [int(x) if pd.notna(x) else 0 for x in df["pass_count"]]
    tot_cnt = [int(x) if pd.notna(x) else 0 for x in df["total_stocks"]]
    pct = [round(float(x), 1) if pd.notna(x) else 0.0 for x in df["pass_pct"]]

    res = {
        "dates": dates,
        "pass_count": pass_cnt,
        "total_stocks": tot_cnt,
        "pass_pct": pct,
    }
    set_cached(ckey, res)
    return res


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
        price_cols = ohlcv_columns(db)
        adj_close = price_cols["close_price"]
        return db.execute(
            f"""
            WITH latest AS (
                SELECT max(trade_date) d FROM indicators_daily
            ),
            p_win1 AS (
                SELECT symbol, trade_date,
                       avg({adj_close}) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS sma_50,
                       avg({adj_close}) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 149 PRECEDING AND CURRENT ROW) AS sma_150,
                       avg({adj_close}) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma_200
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

    # Market-Wide Stage 2 Universe Trend (Macro Breadth Expansion / Contraction)
    s2_trend = query_stage2_universe_trend(db_path)
    if s2_trend and s2_trend.get("dates"):
        dates = s2_trend["dates"]
        pass_counts = s2_trend["pass_count"]
        pass_pcts = s2_trend["pass_pct"]
        total_stocks = s2_trend["total_stocks"]
        n_sessions = len(dates)

        latest_pass = pass_counts[-1] if pass_counts else 0
        latest_pct = pass_pcts[-1] if pass_pcts else 0.0
        latest_tot = total_stocks[-1] if total_stocks else 0

        prev_5d_pass = pass_counts[-6] if n_sessions >= 6 else (pass_counts[0] if pass_counts else 0)
        prev_5d_pct = pass_pcts[-6] if n_sessions >= 6 else (pass_pcts[0] if pass_pcts else 0.0)
        chg_5d_stocks = latest_pass - prev_5d_pass
        chg_5d_pct = round(latest_pct - prev_5d_pct, 1)

        prev_20d_pass = pass_counts[-21] if n_sessions >= 21 else (pass_counts[0] if pass_counts else 0)
        prev_20d_pct = pass_pcts[-21] if n_sessions >= 21 else (pass_pcts[0] if pass_pcts else 0.0)
        chg_20d_stocks = latest_pass - prev_20d_pass
        chg_20d_pct = round(latest_pct - prev_20d_pct, 1)

        chg_5d_tone = "text-emerald-400" if chg_5d_stocks >= 0 else "text-rose-400"
        chg_20d_tone = "text-emerald-400" if chg_20d_stocks >= 0 else "text-rose-400"

        with ui.card().classes("w-full mp-card p-3 mb-4 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
            with ui.row().classes("w-full items-center justify-between pb-2 border-b border-[var(--mp-border)] flex-wrap gap-2"):
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    ui.label("🌐 Market-Wide Stage 2 Universe Trend").classes("text-xs font-bold tracking-wider text-[var(--mp-primary)] uppercase")
                    ui.label(f"{latest_pass} of {latest_tot} stocks ({latest_pct}%) in Stage 2").classes("mp-badge mp-good text-xs font-semibold")
                with ui.row().classes("items-center gap-3 text-xs font-mono"):
                    ui.label(f"5D: {chg_5d_stocks:+d} ({chg_5d_pct:+.1f}%)").classes(f"font-semibold {chg_5d_tone}")
                    ui.label(f"20D: {chg_20d_stocks:+d} ({chg_20d_pct:+.1f}%)").classes(f"font-semibold {chg_20d_tone}")
                    ui.label(f"{n_sessions} Sessions").classes("text-[var(--mp-muted)]")

            z_start = max(0, int(((n_sessions - 126) / max(1, n_sessions)) * 100))
            chart_opt = {
                "backgroundColor": "transparent",
                "animation": False,
                "tooltip": {
                    "trigger": "axis",
                    "axisPointer": {"type": "cross"},
                    "backgroundColor": "rgba(15, 23, 42, 0.95)",
                    "borderColor": "#334155",
                    "borderWidth": 1,
                    "textStyle": {"color": "#f8fafc", "fontSize": 11, "fontFamily": "IBM Plex Mono"},
                    "confine": True,
                },
                "legend": {
                    "data": ["Stage 2 Stocks", "Stage 2 %"],
                    "textStyle": {"color": "#94a3b8", "fontSize": 10},
                    "top": 0,
                    "right": 10,
                },
                "grid": {"left": "5%", "right": "5%", "top": "14%", "bottom": "22%"},
                "xAxis": {
                    "type": "category",
                    "data": dates,
                    "boundaryGap": False,
                    "axisLine": {"lineStyle": {"color": "#334155"}},
                    "axisLabel": {"color": "#94a3b8", "fontSize": 9},
                },
                "yAxis": [
                    {
                        "type": "value",
                        "name": "Stage 2 Count",
                        "splitLine": {"lineStyle": {"color": "#1e293b"}},
                        "axisLabel": {"color": "#94a3b8", "fontSize": 9},
                    },
                    {
                        "type": "value",
                        "name": "Stage 2 %",
                        "min": 0,
                        "max": 100,
                        "splitLine": {"show": False},
                        "axisLabel": {"color": "#fbbf24", "fontSize": 9, "formatter": "{value}%"},
                    },
                ],
                "dataZoom": [
                    {"type": "inside", "xAxisIndex": 0, "start": z_start, "end": 100},
                    {
                        "type": "slider",
                        "xAxisIndex": 0,
                        "start": z_start,
                        "end": 100,
                        "height": 18,
                        "bottom": 2,
                        "borderColor": "#334155",
                        "fillerColor": "rgba(16, 185, 129, 0.18)",
                        "handleStyle": {"color": "#10b981", "borderColor": "#059669"},
                        "moveHandleStyle": {"color": "#10b981"},
                        "dataBackground": {
                            "lineStyle": {"color": "#64748b"},
                            "areaStyle": {"color": "rgba(100, 116, 139, 0.2)"},
                        },
                    },
                ],
                "series": [
                    {
                        "name": "Stage 2 Stocks",
                        "type": "line",
                        "yAxisIndex": 0,
                        "smooth": True,
                        "data": pass_counts,
                        "lineStyle": {"color": "#10b981", "width": 2},
                        "areaStyle": {
                            "color": {
                                "type": "linear",
                                "x": 0, "y": 0, "x2": 0, "y2": 1,
                                "colorStops": [
                                    {"offset": 0, "color": "rgba(16, 185, 129, 0.35)"},
                                    {"offset": 1, "color": "rgba(16, 185, 129, 0.0)"},
                                ],
                            }
                        },
                        "showSymbol": False,
                    },
                    {
                        "name": "Stage 2 %",
                        "type": "line",
                        "yAxisIndex": 1,
                        "smooth": True,
                        "data": pass_pcts,
                        "lineStyle": {"color": "#fbbf24", "width": 1.5, "type": "dashed"},
                        "showSymbol": False,
                    },
                ],
            }
            macro_chart = ui.echart(chart_opt).classes("w-full h-[220px]")
            with ui.row().classes("w-full items-center justify-end gap-1.5 text-[10px] font-mono"):
                ui.label("Zoom:").classes("text-[var(--mp-muted)]")
                z3m = max(0, int(((n_sessions - 63) / max(1, n_sessions)) * 100))
                z6m = max(0, int(((n_sessions - 126) / max(1, n_sessions)) * 100))
                z1y = max(0, int(((n_sessions - 252) / max(1, n_sessions)) * 100))
                ui.button("3M", on_click=lambda: macro_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'start': z3m, 'end': 100})).props("dense outline size=xs").classes("mp-button px-1.5 py-0")
                ui.button("6M", on_click=lambda: macro_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'start': z6m, 'end': 100})).props("dense outline size=xs").classes("mp-button px-1.5 py-0")
                ui.button("1Y", on_click=lambda: macro_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'start': z1y, 'end': 100})).props("dense outline size=xs").classes("mp-button px-1.5 py-0")
                ui.button("All", on_click=lambda: macro_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'start': 0, 'end': 100})).props("dense outline size=xs").classes("mp-button px-1.5 py-0")
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
