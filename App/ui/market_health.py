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

try:
    from Scripts.midsml_breadth import query_midsml_breadth
except ModuleNotFoundError:
    try:
        from midsml_breadth import query_midsml_breadth  # type: ignore
    except ModuleNotFoundError:
        query_midsml_breadth = None

# Action Desk exposure keys share this breadth_daily row (PR 4 / Key Decision 15).
BREADTH_EXPOSURE_MAP = {
    "adv_pct": "advance_pct",
    "ab20_pct": "above_20ema_pct",
    "ab50_pct": "above_50ema_pct",
    "ab200_pct": "above_200ema_pct",
}

_BREADTH_LATEST_SQL = """
SELECT *
FROM breadth_daily
ORDER BY trade_date DESC
LIMIT ?
"""


def query_latest_breadth_daily(con: Any, *, limit: int = 2) -> pd.DataFrame:
    """Latest breadth_daily rows — same query the health strip and exposure gate use."""
    try:
        return con.execute(_BREADTH_LATEST_SQL, [limit]).fetchdf()
    except Exception:
        return pd.DataFrame()


def _scalar(row: Any, key: str, default: Any = None) -> Any:
    try:
        val = row[key]
    except Exception:
        return default
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    return val


def _round_pct(val: Any) -> float | None:
    """Keep 0.0 as 0.0. SQL NULL / NaN stay None — never invent 50%."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return round(float(val), 1)
    except (TypeError, ValueError):
        return None


def _as_of_str(val: Any) -> str:
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        return str(pd.to_datetime(val).date())
    except (TypeError, ValueError):
        return str(val)


def _count_or_none(val: Any) -> int | None:
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def exposure_inputs_from_breadth_row(row: Any) -> dict[str, Any]:
    """Map one breadth_daily row onto Action Desk exposure keys."""
    as_of = _as_of_str(_scalar(row, "trade_date"))
    total_stocks = _count_or_none(_scalar(row, "stocks"))

    def pct(col: str) -> float | None:
        return _round_pct(_scalar(row, col))

    return {
        "adv_pct": pct(BREADTH_EXPOSURE_MAP["adv_pct"]),
        "ab20_pct": pct(BREADTH_EXPOSURE_MAP["ab20_pct"]),
        "ab50_pct": pct(BREADTH_EXPOSURE_MAP["ab50_pct"]),
        "ab200_pct": pct(BREADTH_EXPOSURE_MAP["ab200_pct"]),
        "total_stocks": total_stocks,
        "as_of": as_of,
        "source": "breadth_daily",
    }


_INDICATORS_FALLBACK_SQL = """
SELECT
    count(*) AS total_stocks,
    avg(CASE WHEN close_price > prev_close THEN 1.0 ELSE 0.0 END) * 100 AS advance_pct,
    avg(CASE WHEN close_price > ema_20 THEN 1.0 ELSE 0.0 END) * 100 AS above_20ema_pct,
    avg(CASE WHEN close_price > ema_50 THEN 1.0 ELSE 0.0 END) * 100 AS above_50ema_pct,
    avg(CASE WHEN close_price > ema_200 THEN 1.0 ELSE 0.0 END) * 100 AS above_200ema_pct
FROM indicators_daily
WHERE trade_date = ?
"""


def recompute_exposure_from_indicators(con: Any, trade_date: Any) -> dict[str, Any]:
    """indicators_daily fallback. NULL averages stay None; 0.0 stays 0.0."""
    as_of = _as_of_str(trade_date)
    try:
        row = con.execute(_INDICATORS_FALLBACK_SQL, [trade_date]).fetchone()
    except Exception:
        row = None
    if row is None:
        return {
            "adv_pct": None,
            "ab20_pct": None,
            "ab50_pct": None,
            "ab200_pct": None,
            "total_stocks": None,
            "as_of": as_of,
            "source": "indicators_daily",
        }
    return {
        "adv_pct": _round_pct(row[1]),
        "ab20_pct": _round_pct(row[2]),
        "ab50_pct": _round_pct(row[3]),
        "ab200_pct": _round_pct(row[4]),
        "total_stocks": _count_or_none(row[0]),
        "as_of": as_of,
        "source": "indicators_daily",
    }


def load_exposure_inputs(con: Any, *, trade_date: Any = None) -> dict[str, Any]:
    """Same latest breadth_daily row as the health strip; indicators recompute only if missing."""
    b_df = query_latest_breadth_daily(con, limit=1)
    if not b_df.empty:
        return exposure_inputs_from_breadth_row(b_df.iloc[0])
    return recompute_exposure_from_indicators(con, trade_date)



def resolve_india_vix(con: Any, trade_date: Any) -> tuple[float | None, float]:
    """Load India VIX for the session. Missing row is (None, 0.0) — never a silent default."""
    try:
        vix_res = con.execute(
            """
            SELECT close_price,
                   coalesce(
                       return_1d_pct,
                       (close_price / nullif(previous_close, 0) - 1.0) * 100
                   ) AS vix_1d_pct
            FROM index_daily
            WHERE trade_date = ? AND index_name = 'India VIX'
            """,
            [trade_date],
        ).fetchone()
        if vix_res and vix_res[0] is not None:
            return round(float(vix_res[0]), 2), round(float(vix_res[1] or 0.0), 1)
    except Exception:
        pass
    return None, 0.0


def count_52w_extremes(con: Any, trade_date: Any) -> tuple[int, int]:
    """Near-52W highs / near-52W lows counts used by the Action Desk exposure gate."""
    try:
        row = con.execute(
            """
            SELECT
                count(CASE WHEN away_52w_high_pct >= -2.0 THEN 1 END) AS count_52w_highs,
                count(CASE WHEN (close_price / nullif(low_52w, 0) - 1.0) <= 0.02 THEN 1 END) AS count_52w_lows
            FROM indicators_daily
            WHERE trade_date = ?
            """,
            [trade_date],
        ).fetchone()
        if row:
            return int(row[0] or 0), int(row[1] or 0)
    except Exception:
        pass
    return 0, 0


def load_exposure_gate_args(con: Any, *, trade_date: Any = None) -> dict[str, Any]:
    """Full match_exposure args: breadth_daily + India VIX + 52W extremes.

    Overview/Brief and Action Desk MUST share this so missing VIX cannot drop Overview
    to risk_off while Action Desk shows Selective.
    """
    exp = load_exposure_inputs(con, trade_date=trade_date)
    td = trade_date
    if td is None:
        try:
            row = con.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()
            td = row[0] if row else None
        except Exception:
            td = None
        if td is None and exp.get("as_of"):
            td = exp["as_of"]
    vix, vix_1d = resolve_india_vix(con, td)
    highs, lows = count_52w_extremes(con, td)
    return {
        "adv_pct": exp.get("adv_pct"),
        "ab20_pct": exp.get("ab20_pct"),
        "ab50_pct": exp.get("ab50_pct"),
        "ab200_pct": exp.get("ab200_pct"),
        "total_stocks": exp.get("total_stocks"),
        "as_of": exp.get("as_of"),
        "source": exp.get("source"),
        "trade_date": td,
        "vix": vix,
        "vix_1d_pct": vix_1d,
        "vix_spike": bool(vix is not None and vix_1d >= 10.0),
        "count_52w_highs": highs,
        "count_52w_lows": lows,
        "net_lows_expanding": lows > highs,
    }



def query_market_health_summary(db_path: Path) -> dict[str, Any]:
    """Fetch current 7-card market health metrics and 1-session changes."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {}

    with duckdb.connect(str(db_path), read_only=True) as db:
        # 1. Fetch latest 2 rows from breadth_daily for day-over-day delta
        b_df = query_latest_breadth_daily(db, limit=2)

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

        a50_5d_raw = today.get("above_50ema_5d_change")
        a200_20d_raw = today.get("above_200ema_20d_change")
        a50_5d_val = float(a50_5d_raw) if a50_5d_raw is not None and not pd.isna(a50_5d_raw) else None
        a200_20d_val = float(a200_20d_raw) if a200_20d_raw is not None and not pd.isna(a200_20d_raw) else None

        near_52_pct = (float(today.get("near_52w_highs") or 0) / tot_stocks * 100.0) if tot_stocks > 0 else 0.0
        vcp_pct = (float(today.get("vcp_candidates") or 0) / tot_stocks * 100.0) if tot_stocks > 0 else 0.0
        exp_inputs = exposure_inputs_from_breadth_row(today)

        midsml_data = {}
        if query_midsml_breadth is not None:
            try:
                midsml_data = query_midsml_breadth(con=db, trade_date=str(today["trade_date"]))
            except Exception:
                midsml_data = {}

        exchange_macro = {}
        try:
            from Scripts.index_history import parse_market_macro
            from Scripts.config import DAILY_DIR, ARCHIVE_DIR
            t_str = pd.to_datetime(today["trade_date"]).strftime("%d%m%y")
            ma_file = Path(DAILY_DIR) / f"MA{t_str}.csv"
            if not ma_file.exists():
                ma_file = Path(ARCHIVE_DIR) / f"MA{t_str}.csv"
            if not ma_file.exists():
                import glob
                cands = glob.glob(str(Path(DAILY_DIR) / "MA*.csv")) + glob.glob(str(Path(ARCHIVE_DIR) / "MA*.csv"))
                if cands:
                    ma_file = Path(cands[-1])
            if ma_file.exists():
                exchange_macro = parse_market_macro(ma_file, today["trade_date"])
        except Exception:
            exchange_macro = {}

        cards = [
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
                "change": f"{a20_chg:+.1f} (5D: {a50_5d_val:+.1f})" if a50_5d_val is not None else f"{a20_chg:+.1f} pts",
                "change_5d": f"{a50_5d_val:+.1f} pts" if a50_5d_val is not None else None,
                "tone": "good" if float(today.get("above_20ema_pct") or 0) >= 50 else "bad",
                "context": f"5D: {a50_5d_val:+.1f} pts (50 EMA) · Short-term" if a50_5d_val is not None else "Short-term trend breadth",
                "column_series": "above_20ema_pct",
            },
            {
                "key": "above_200",
                "title": "Above 200 EMA",
                "value": f"{float(today.get('above_200ema_pct') or 0):.1f}%",
                "change": f"{a200_chg:+.1f} (20D: {a200_20d_val:+.1f})" if a200_20d_val is not None else f"{a200_chg:+.1f} pts",
                "change_20d": f"{a200_20d_val:+.1f} pts" if a200_20d_val is not None else None,
                "tone": "good" if float(today.get("above_200ema_pct") or 0) >= 50 else "bad",
                "context": f"20D: {a200_20d_val:+.1f} pts · Bull/bear regime" if a200_20d_val is not None else "Long-term bull/bear regime",
                "column_series": "above_200ema_pct",
            },
            {
                "key": "rsi_60",
                "title": "RSI above 60",
                "value": f"{rsi_60_pct:.1f}%",
                "change": "—",
                "tone": "good" if rsi_60_pct >= 25 else "neutral",
                "context": "High-momentum participation",
                "column_series": "rsi_60_pct",
            },
            {
                "key": "pivot",
                "title": "Above daily pivot",
                "value": f"{pivot_pct:.1f}%",
                "change": "—",
                "tone": "good" if pivot_pct >= 50 else "neutral",
                "context": "Short-term price location",
                "column_series": "pivot_pct",
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
                "title": "VCP heuristic",
                "value": f"{vcp_pct:.1f}%",
                "change": f"{vcp_chg:+.0f} names",
                "tone": "good" if vcp_pct >= 15 else "neutral",
                "context": f"{int(today.get('vcp_candidates') or 0)} heuristic names",
                "column_series": "vcp_candidates",
            },
        ]

        return {
            "as_of": str(pd.to_datetime(today["trade_date"]).date()),
            "total_stocks": int(tot_stocks),
            "breadth_state": str(today.get("breadth_state") or "Unclassified"),
            "midsml": midsml_data,
            "exchange_macro": exchange_macro,
            "adv_pct": exp_inputs["adv_pct"],
            "ab20_pct": exp_inputs["ab20_pct"],
            "ab50_pct": exp_inputs["ab50_pct"],
            "ab200_pct": exp_inputs["ab200_pct"],
            "cards": cards,
        }


def open_breadth_history_modal(db_path: Path, title: str, column_series: str | None = None) -> None:
    """Open interactive modal with 90-session history for the clicked breadth metric."""
    if not column_series:
        return

    db_path = Path(db_path)
    df = pd.DataFrame()
    active_col: str | None = None
    with duckdb.connect(str(db_path), read_only=True) as db:
        if column_series in ("rsi_60", "rsi_60_pct"):
            try:
                df = db.execute(
                    """
                    SELECT trade_date,
                           count(CASE WHEN rsi_14 >= 60 THEN 1 END) * 100.0 / nullif(count(*), 0) AS rsi_60_pct
                    FROM indicators_daily
                    WHERE trade_date >= (SELECT min(trade_date) FROM (SELECT DISTINCT trade_date FROM indicators_daily ORDER BY trade_date DESC LIMIT 90))
                    GROUP BY trade_date
                    ORDER BY trade_date ASC
                    """
                ).fetchdf()
                active_col = "rsi_60_pct"
            except Exception:
                df = pd.DataFrame()
        elif column_series in ("pivot", "pivot_pct"):
            try:
                df = db.execute(
                    """
                    SELECT trade_date,
                           count(CASE WHEN close_price >= (high_price + low_price + close_price) / 3.0 THEN 1 END) * 100.0 / nullif(count(*), 0) AS pivot_pct
                    FROM indicators_daily
                    WHERE trade_date >= (SELECT min(trade_date) FROM (SELECT DISTINCT trade_date FROM indicators_daily ORDER BY trade_date DESC LIMIT 90))
                    GROUP BY trade_date
                    ORDER BY trade_date ASC
                    """
                ).fetchdf()
                active_col = "pivot_pct"
            except Exception:
                df = pd.DataFrame()
        else:
            try:
                b_cols = {r[1] for r in db.execute("PRAGMA table_info(breadth_daily)").fetchall()}
                if column_series in b_cols:
                    df = db.execute(
                        """
                        SELECT *
                        FROM (
                            SELECT *
                            FROM breadth_daily
                            ORDER BY trade_date DESC
                            LIMIT 90
                        )
                        ORDER BY trade_date ASC
                        """
                    ).fetchdf()
                    active_col = column_series
            except Exception:
                df = pd.DataFrame()

    if active_col is None or df.empty or active_col not in df.columns:
        ui.notify(f"No historical trend series available for {title}.", type="info")
        return

    dialog = ui.dialog().classes("mp-dialog")
    with dialog, ui.card().classes("mp-card p-6 w-[780px] max-w-full"):
        with ui.row().classes("w-full items-center justify-between pb-3 border-b border-[var(--mp-border)]"):
            with ui.column().classes("gap-0"):
                ui.label(f"Market Breadth History · {title}").classes("text-lg font-bold text-[var(--mp-text)]")
                ui.label("Historical trend across the active universe (latest 90 sessions)").classes("text-xs text-[var(--mp-muted)]")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense").classes("text-[var(--mp-muted)]")

        line_chart(
            df,
            date_col="trade_date",
            series={title: active_col},
            series_tones={title: "good" if ("advance" in active_col or "high" in active_col or "rsi" in active_col or "pivot" in active_col) else "info"},
            area=True,
        )

        with ui.row().classes("w-full justify-end mt-4"):
            ui.button("Close", on_click=dialog.close).props("outline dense").classes("mp-button")

    dialog.open()


def render_market_health_strip(db_path: Path, *, expanded: bool = True) -> None:
    """Render the collapsible 7-card market health strip at the top of a page.

    expanded=False starts collapsed (Lab pages like Momentum); Action Desk keeps True.
    """
    data = query_market_health_summary(db_path)
    if not data:
        return

    cards = data.get("cards", [])
    as_of = data.get("as_of", "—")
    stocks_n = data.get("total_stocks", 0)
    posture = data.get("breadth_state", "Neutral")
    midsml = data.get("midsml", {})
    m_regime = midsml.get("regime", "")
    m_stance = midsml.get("stance", "")
    m_icon = midsml.get("regime_icon", "🧭")
    m_metrics = midsml.get("metrics", {})

    container = ui.element("section").classes("mp-market-health-strip w-full mb-3")
    with container:
        with ui.row().classes("w-full items-center justify-between gap-2 px-1 py-1 mp-health-header"):
            with ui.row().classes("items-center gap-2"):
                ui.label("Market Health").classes("text-xs font-bold uppercase tracking-wider text-[var(--mp-text-subtle)]")
                ui.label(f"{as_of} · {stocks_n:,} stocks").classes("text-xs text-[var(--mp-muted)]")
                state_tone = "mp-good" if "improv" in posture.lower() or "broad" in posture.lower() else "mp-bad" if "weak" in posture.lower() else "mp-neutral"
                ui.label(posture).classes(f"mp-badge {state_tone} text-[10px]")
                if m_regime:
                    m_badge_tone = "mp-bad" if ("WASHOUT" in m_regime or "CORRECTION" in m_regime) else "mp-neutral" if "WARNING" in m_regime else "mp-good"
                    ui.label(f"MidSml400: {m_regime}").classes(f"mp-badge {m_badge_tone} text-[10px] font-bold")

                macro = data.get("exchange_macro", {})
                if macro and macro.get("traded_value_cr"):
                    ui.label(f"Cash Vol: ₹{macro['traded_value_cr']:,.0f}Cr").classes("mp-badge mp-info text-[10px] font-semibold")
                if macro and macro.get("total_market_cap_cr"):
                    ui.label(f"India MCap: ₹{macro['total_market_cap_cr']/100000:.1f}L Cr").classes("mp-badge mp-neutral text-[10px] font-mono")

            toggle_btn = ui.button("Hide market health").props("flat dense").classes("text-[11px] text-[var(--mp-muted)]")

        if m_regime:
            banner_bg = "bg-rose-950/30 border-rose-800/40 text-rose-300" if ("WASHOUT" in m_regime or "CORRECTION" in m_regime) else "bg-amber-950/30 border-amber-800/40 text-amber-300" if "WARNING" in m_regime else "bg-emerald-950/30 border-emerald-800/40 text-emerald-300"
            with ui.row().classes(f"w-full items-center justify-between px-3 py-1.5 rounded border {banner_bg} mt-1 text-xs"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"{m_icon} NIFTY MIDSML 400 REGIME:").classes("font-bold")
                    ui.label(m_regime).classes("font-extrabold underline")
                    if m_metrics:
                        ui.label(f"({m_metrics.get('adv_pct', 0):.1f}% Adv | >10 EMA: {m_metrics.get('abv_10ema', 0):.1f}% | >50 EMA: {m_metrics.get('abv_50ema', 0):.1f}%)").classes("opacity-90")
                if m_stance:
                    ui.label(m_stance).classes("font-medium")

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
        is_expanded = [bool(expanded)]
        if not is_expanded[0]:
            cards_row.set_visibility(False)
            toggle_btn.set_text("Show market health")

        def _toggle():
            is_expanded[0] = not is_expanded[0]
            if is_expanded[0]:
                cards_row.set_visibility(True)
                toggle_btn.set_text("Hide market health")
            else:
                cards_row.set_visibility(False)
                toggle_btn.set_text("Show market health")

        toggle_btn.on_click(_toggle)
