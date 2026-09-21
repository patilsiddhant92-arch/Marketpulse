"""
Action Desk: Executive Swing Trading Command Center.
Provides a 3-step actionable workflow:
1. Market Exposure Gate (Recommended Exposure % and Stop Discipline)
2. Leading Sector Themes (Institutional Money Flow)
3. Primary setups only: Darvas Squeeze + Darvas 10 EMA + VCP (retired queues deleted)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import duckdb
import numpy as np
import pandas as pd
from nicegui import ui

from App.cache_manager import get_cached, set_cached, cache_key
try:
    from App.sector_read_model import leading_themes_from_board, query_rotation_board
    from App.indicators.uc_thrust import uc_flag_label, uc_score_map
except ModuleNotFoundError:
    from sector_read_model import leading_themes_from_board, query_rotation_board  # type: ignore
    from indicators.uc_thrust import uc_flag_label, uc_score_map  # type: ignore
from App.indicators.darvas import (
    DARVAS,
    WEEKLY_LOOKBACK_SESSIONS,
    apply_display_window,
    calculate_darvas_box,
    darvas_v2_enabled,
    darvas_weekly_enabled,
    is_darvas_10ema_squeeze,
    is_darvas_10ema_squeeze_legacy,
    squeeze_frame,
    classify_darvas_10ema_frame,
)
try:
    from App.thematic_engine import get_macro_pulse, get_stock_thematic_tags
except ModuleNotFoundError:
    from thematic_engine import get_macro_pulse, get_stock_thematic_tags  # type: ignore
try:
    from Scripts.telegram_deals import to_tv_list
except ModuleNotFoundError:
    from telegram_deals import to_tv_list  # type: ignore

try:
    from App.ui.stock_drawer import open_stock_360_modal, query_stock_candlestick_data, render_stock_inspector_panel
    from App.ui.table import _table_event_symbol
except ModuleNotFoundError:
    from ui.stock_drawer import open_stock_360_modal, query_stock_candlestick_data, render_stock_inspector_panel  # type: ignore
    from ui.table import _table_event_symbol  # type: ignore

try:
    from App.ui.vcp_chart import render_vcp_ohlc
except ModuleNotFoundError:
    from ui.vcp_chart import render_vcp_ohlc  # type: ignore

try:
    from App.ui.playbook_guide import open_playbook_modal, render_inline_field_guide_banner
except ModuleNotFoundError:
    from ui.playbook_guide import open_playbook_modal, render_inline_field_guide_banner  # type: ignore

try:
    from Scripts.desk_contract import DARVAS, MORE_QUEUES, POOL, PRIMARY_QUEUES, QUEUE_DISPLAY_CAPS, QUEUE_META, match_exposure
except ModuleNotFoundError:
    from desk_contract import DARVAS, MORE_QUEUES, POOL, PRIMARY_QUEUES, QUEUE_DISPLAY_CAPS, QUEUE_META, match_exposure  # type: ignore

try:
    from Scripts.vcp import VCP, classify_vcp_frame
except ModuleNotFoundError:
    from vcp import VCP, classify_vcp_frame  # type: ignore


try:
    from App.ui.market_health import load_exposure_gate_args, load_exposure_inputs, render_market_health_strip, resolve_india_vix as _mh_resolve_india_vix
    from App.ui.desk_chrome import peer_chip_label, rotation_badge_class, signed_pct_class
except ModuleNotFoundError:
    from ui.market_health import load_exposure_gate_args, load_exposure_inputs, render_market_health_strip, resolve_india_vix as _mh_resolve_india_vix  # type: ignore
    from ui.desk_chrome import peer_chip_label, rotation_badge_class, signed_pct_class  # type: ignore


def _fmt_exp_pct(val: Any) -> str:
    if val is None:
        return "n/a"
    try:
        return f"{float(val):.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _exp_pct_tone(val: Any, threshold: float) -> str:
    if val is None:
        return "text-amber-400"
    try:
        return "text-emerald-400" if float(val) >= threshold else "text-rose-400"
    except (TypeError, ValueError):
        return "text-amber-400"


def resolve_india_vix(con: duckdb.DuckDBPyConnection, trade_date: Any) -> tuple[float | None, float]:
    """Delegate to market_health — single VIX source for the exposure gate."""
    return _mh_resolve_india_vix(con, trade_date)




def compute_exposure_gate(
    *,
    adv_pct: float,
    ab20_pct: float,
    ab200_pct: float,
    vix: float | None,
    vix_1d_pct: float,
    net_lows_expanding: bool,
    count_52w_highs: int,
    count_52w_lows: int,
) -> dict[str, Any]:
    """Canonical exposure gate via desk_contract. VIX n/a skips every vix-threshold branch."""
    vix_spike = bool(vix is not None and vix_1d_pct >= 10.0)
    gate = match_exposure(
        {
            "adv_pct": adv_pct,
            "ab20_pct": ab20_pct,
            "ab200_pct": ab200_pct,
            "vix": vix,
            "vix_spike": vix_spike,
            "net_lows_expanding": net_lows_expanding,
            "count_52w_lows": count_52w_lows,
            "count_52w_highs": count_52w_highs,
            "vix_1d_pct": vix_1d_pct,
        }
    )
    vix_available = not gate["vix_na"]
    gate["vix"] = vix
    gate["vix_1d_pct"] = vix_1d_pct
    gate["vix_available"] = vix_available
    gate["vix_label"] = "VIX n/a" if not vix_available else f"{vix}"
    gate["vix_spike"] = vix_spike
    return gate


def _rs_trail_5d(con: Any, symbols: list[str], trade_date: Any = None) -> pd.DataFrame:
    """Last 5 session RS percentiles per symbol with step-by-step colored transitions and 5D trend badge."""
    if not symbols:
        return pd.DataFrame(columns=["symbol", "rs_5d_trail", "rs_5d_trail_html"])
    clause = ", ".join([f"'{str(s).strip().upper()}'" for s in symbols])
    try:
        if trade_date:
            date_filter = "WHERE trade_date <= ?"
            params = [trade_date]
        else:
            date_filter = ""
            params = []
        hist = con.execute(
            f"""
            WITH dates AS (
                SELECT DISTINCT trade_date
                FROM indicators_daily
                {date_filter}
                ORDER BY trade_date DESC
                LIMIT 5
            ),
            recent AS (
                SELECT symbol, trade_date, rs_percentile
                FROM indicators_daily
                WHERE symbol IN ({clause})
                  AND trade_date IN (SELECT trade_date FROM dates)
            )
            SELECT symbol, trade_date, rs_percentile
            FROM recent
            ORDER BY symbol, trade_date ASC
            """,
            params,
        ).fetchdf()
    except Exception:
        return pd.DataFrame(columns=["symbol", "rs_5d_trail", "rs_5d_trail_html"])

    if hist.empty:
        return pd.DataFrame(columns=["symbol", "rs_5d_trail", "rs_5d_trail_html"])

    rows = []
    for sym, g in hist.groupby("symbol", sort=False):
        vals = [int(round(float(v))) for v in g["rs_percentile"].dropna().tolist()]
        if not vals:
            rows.append({"symbol": sym, "rs_5d_trail": "—", "rs_5d_trail_html": "—"})
            continue
        plain_trail = " → ".join(str(v) for v in vals)

        html_parts = []
        for i, val in enumerate(vals):
            if i == 0:
                color_class = "text-zinc-400 font-medium"
                arrow = ""
            else:
                prev = vals[i - 1]
                if val > prev:
                    color_class = "mp-up font-bold text-emerald-400"
                    arrow = '<span class="text-zinc-600 mx-0.5 text-[10px]">→</span>'
                elif val < prev:
                    color_class = "mp-down font-bold text-rose-400"
                    arrow = '<span class="text-zinc-600 mx-0.5 text-[10px]">→</span>'
                else:
                    color_class = "text-zinc-400 font-medium"
                    arrow = '<span class="text-zinc-600 mx-0.5 text-[10px]">→</span>'
            html_parts.append(f'{arrow}<span class="{color_class}">{val}</span>')

        if len(vals) > 1:
            delta = vals[-1] - vals[0]
            if delta > 0:
                trend_badge = f'<span class="ml-1 text-[10px] text-emerald-400 font-bold" title="5D Net: +{delta}">▲+{delta}</span>'
                plain_trail += f" ▲+{delta}"
            elif delta < 0:
                trend_badge = f'<span class="ml-1 text-[10px] text-rose-400 font-bold" title="5D Net: {delta}">▼{delta}</span>'
                plain_trail += f" ▼{delta}"
            else:
                trend_badge = '<span class="ml-1 text-[10px] text-zinc-500 font-bold" title="5D Net: 0">▬</span>'
                plain_trail += " ▬"
            html_parts.append(trend_badge)

        rows.append({"symbol": sym, "rs_5d_trail": plain_trail, "rs_5d_trail_html": "".join(html_parts)})
    return pd.DataFrame(rows)


def fetch_action_desk_data(db_path: Path | str) -> dict[str, Any]:
    """
    Query and assemble all datasets required for the Action Desk.
    Results are cached in memory for sub-millisecond response on subsequent tab visits.
    """
    use_v2 = darvas_v2_enabled()
    use_weekly = darvas_weekly_enabled()
    key = cache_key(
        db_path,
        None,
        "action_desk_v12_peer_on_symbol",
        "darvas_v2" if use_v2 else "darvas_v1",
        "weekly" if use_weekly else "daily",
    )
    cached = get_cached(key)
    if cached is not None:
        return cached

    with duckdb.connect(str(db_path), read_only=True) as con:
        # 1. Latest trade date
        max_d_res = con.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()
        if not max_d_res or not max_d_res[0]:
            return {"ready": False, "reason": "No data in indicators_daily"}
        trade_date = max_d_res[0]
        trade_date_str = str(pd.to_datetime(trade_date).date())

        # 2. Market Breadth & Exposure Gate — same breadth_daily row as the health strip.
        exp_inputs = load_exposure_gate_args(con, trade_date=trade_date)
        total_stocks = exp_inputs["total_stocks"]
        adv_pct = exp_inputs["adv_pct"]
        ab20_pct = exp_inputs["ab20_pct"]
        ab50_pct = exp_inputs["ab50_pct"]
        ab200_pct = exp_inputs["ab200_pct"]
        breadth_source = exp_inputs["source"]
        breadth_as_of = exp_inputs["as_of"]

        vix_val = exp_inputs["vix"]
        vix_1d_pct = float(exp_inputs["vix_1d_pct"] or 0.0)
        count_52w_highs = int(exp_inputs["count_52w_highs"] or 0)
        count_52w_lows = int(exp_inputs["count_52w_lows"] or 0)
        net_highs = count_52w_highs - count_52w_lows
        net_lows_expanding = bool(exp_inputs["net_lows_expanding"])

        gate = compute_exposure_gate(
            adv_pct=adv_pct,
            ab20_pct=ab20_pct,
            ab200_pct=ab200_pct,
            vix=vix_val,
            vix_1d_pct=vix_1d_pct,
            net_lows_expanding=net_lows_expanding,
            count_52w_highs=count_52w_highs,
            count_52w_lows=count_52w_lows,
        )
        exposure_pct = gate["pct"]
        exposure_state = gate["state"]
        exposure_badge = gate["badge"]
        exposure_guidance = gate["guidance"]

        # 3. Top Leading Themes — shared contract with Sector Intel money board
        # (Leading/Emerging + positive Δ SHARE 5D only; never Lagging wearing Leading)
        board = query_rotation_board(Path(db_path), level="Broad Industry")
        top_sectors = leading_themes_from_board(board, limit=4)
        if not top_sectors.empty:
            top_sectors["sector"] = top_sectors["group_name"]
            top_sectors["leaders"] = top_sectors["leader_symbols"] if "leader_symbols" in top_sectors.columns else ""
            top_sectors["total_to_cr"] = top_sectors["turnover_1d_cr"] if "turnover_1d_cr" in top_sectors.columns else 0.0
            top_sectors["avg_5d_pct"] = top_sectors["return_5d_pct"] if "return_5d_pct" in top_sectors.columns else 0.0
            top_sectors["avg_rs"] = top_sectors["rs_percentile"] if "rs_percentile" in top_sectors.columns else 0.0
            top_sectors["above_50_pct"] = top_sectors["above_50ema_pct"] if "above_50ema_pct" in top_sectors.columns else 0.0

        # 4. Strict Quality Filtered Pool for Setups (Without RS gate, so Darvas & Pre-Move queues can find unextended gems)
        setup_pool = con.execute(
            """
            WITH dates AS (
                SELECT DISTINCT trade_date 
                FROM indicators_daily 
                ORDER BY trade_date DESC 
                LIMIT 7
            ),
            hist AS (
                SELECT symbol,
                       ARRAY_AGG(round(rvol, 2) ORDER BY trade_date ASC) as rvol_arr,
                       ARRAY_AGG(round(delivery_pct, 1) ORDER BY trade_date ASC) as deliv_arr,
                       ARRAY_AGG(round((close_price / prev_close - 1.0)*100, 2) ORDER BY trade_date ASC) as day_pct_arr
                FROM indicators_daily
                WHERE trade_date IN (SELECT trade_date FROM dates)
                GROUP BY symbol
            ),
            pool AS (
                SELECT 
                    i.trade_date,
                    i.symbol,
                    m.security_name,
                    m.sector,
                    m.industry,
                    m.market_cap_cr,
                    COALESCE(m.band, 20.0) AS band,
                    m.pe,
                    i.close_price AS cmp,
                    (i.close_price / nullif(i.prev_close, 0) - 1.0) * 100 AS day_pct,
                    i.return_5d_pct,
                    i.return_1m_pct,
                    i.away_52w_high_pct,
                    i.rs_percentile,
                    i.rvol,
                    i.delivery_pct,
                    i.high_20d,
                    i.low_10d,
                    i.low_price,
                    i.high_price,
                    i.open_price,
                    i.ema_10,
                    i.ema_20,
                    i.ema_50,
                    i.ema_200,
                    i.away_10ema_pct,
                    i.away_20ema_pct,
                    i.low_volatility_near_high,
                    COALESCE(i.avg_traded_value_cr_20d, i.turnover_cr) AS to_cr,
                    round(i.avg_trade_size / nullif(i.avg_trade_size_20d, 0), 2) AS ticket_ratio,
                    COALESCE(i.delivery_spike, false) AS delivery_spike,
                    COALESCE(i.price_up_delivery_up, false) AS price_up_delivery_up,
                    COALESCE(i.nr7, false) AS nr7,
                    round(i.rs_vs_midsml400_21d, 1) AS rs_vs_midsml400_21d,
                    h.rvol_arr,
                    h.deliv_arr,
                    h.day_pct_arr
                FROM indicators_daily i
                JOIN stocks_master m ON m.symbol = i.symbol
                JOIN hist h ON h.symbol = i.symbol
                WHERE i.trade_date = ?
                  AND m.market_cap_cr >= ?
                  AND COALESCE(m.band, 20.0) > ?
                  AND i.symbol NOT LIKE '%-RE' AND i.symbol NOT LIKE '%_RE'
                  AND COALESCE(i.avg_traded_value_cr_20d, i.turnover_cr) >= ?
                  AND COALESCE(m.band_remarks, '') NOT LIKE '%GSM%'
                  AND COALESCE(m.band_remarks, '') NOT LIKE '%STAGE 2%'
            )
            SELECT * FROM pool
            """,
            [trade_date, POOL["min_mcap"], POOL["min_band"], POOL["min_adv_cr"]],
        ).fetchdf()

        # Build readable RVOL Trail and institutional flow strings
        if not setup_pool.empty:
            def _build_inst_badges(row):
                badges = []
                tr = row.get("ticket_ratio")
                if tr is not None and not (pd.isna(tr) or np.isnan(float(tr))) and float(tr) >= 1.25:
                    badges.append(f"{float(tr):.1f}x Whale 🏛️")
                if bool(row.get("delivery_spike")):
                    badges.append("Deliv Surge 📦")
                elif bool(row.get("price_up_delivery_up")):
                    badges.append("Acc Vol 📈")
                if bool(row.get("nr7")):
                    badges.append("NR7 ⚡")
                midsml_rs = row.get("rs_vs_midsml400_21d")
                if midsml_rs is not None and not pd.isna(midsml_rs) and float(midsml_rs) >= 5.0:
                    badges.append("MidSml RS 💪")
                return " · ".join(badges) if badges else "—"

            setup_pool["inst_footprint"] = setup_pool.apply(_build_inst_badges, axis=1)
            setup_pool["rvol_trail"] = setup_pool["rvol_arr"].apply(
                lambda arr: " -> ".join([f"{x:.1f}x" for x in arr]) if arr is not None and len(arr) > 0 else "—"
            )
            setup_pool["ticket_flow"] = setup_pool["ticket_ratio"].apply(
                lambda tr: f"{float(tr):.1f}x 🏛️" if tr is not None and not (pd.isna(tr) or np.isnan(float(tr))) and float(tr) >= 1.20 else (f"{float(tr):.1f}x" if tr is not None and not (pd.isna(tr) or np.isnan(float(tr))) else "—")
            )
            setup_pool["band_fmt"] = setup_pool["band"].apply(
                lambda b: "10% ⚡" if b is not None and not pd.isna(b) and float(b) == 10.0 else (f"{int(b)}%" if b is not None and not pd.isna(b) else "20%")
            )
            setup_pool["away_10ema"] = setup_pool["away_10ema_pct"].apply(
                lambda a: f"{float(a):+.1f}%" if a is not None and not pd.isna(a) else "—"
            )
            setup_pool["away_20ema"] = setup_pool["away_20ema_pct"].apply(
                lambda a: f"{float(a):+.1f}%" if a is not None and not pd.isna(a) else "—"
            )

            # Wire 5-day RS Velocity Trail
            pool_symbols = setup_pool["symbol"].tolist()
            trail_df = _rs_trail_5d(con, pool_symbols, trade_date=trade_date)
            if not trail_df.empty:
                setup_pool = setup_pool.merge(trail_df, on="symbol", how="left")
            if "rs_5d_trail" not in setup_pool.columns:
                setup_pool["rs_5d_trail"] = "—"
            if "rs_5d_trail_html" not in setup_pool.columns:
                setup_pool["rs_5d_trail_html"] = "—"

            # Setup tenure / age from signal_ledger
            try:
                ledger_df = con.execute(
                    """
                    WITH latest AS (
                        SELECT COALESCE(?::DATE, (SELECT max(trade_date) FROM indicators_daily)) AS max_d
                    ),
                    sessions AS (
                        SELECT trade_date, dense_rank() OVER (ORDER BY trade_date ASC) as session_idx
                        FROM (SELECT DISTINCT trade_date FROM indicators_daily)
                    ),
                    ledger AS (
                        SELECT symbol, first_seen_date
                        FROM (
                            SELECT symbol, first_seen_date,
                                   row_number() OVER (
                                       PARTITION BY symbol
                                       ORDER BY
                                           CASE WHEN status IN ('prepare', 'observe') THEN 0 ELSE 1 END,
                                           last_seen_date DESC,
                                           first_seen_date DESC
                                   ) as rn
                            FROM signal_ledger
                            CROSS JOIN latest
                            WHERE first_seen_date <= latest.max_d
                        )
                        WHERE rn = 1
                    )
                    SELECT l.symbol, l.first_seen_date,
                           (s_max.session_idx - s_first.session_idx + 1) AS session_age
                    FROM ledger l
                    CROSS JOIN latest
                    LEFT JOIN sessions s_max ON s_max.trade_date = latest.max_d
                    LEFT JOIN sessions s_first ON s_first.trade_date = l.first_seen_date
                    """,
                    [trade_date],
                ).fetchdf()
                age_map = {}
                for r in ledger_df.itertuples(index=False):
                    age = int(r.session_age) if (r.session_age is not None and not pd.isna(r.session_age)) else 1
                    age_map[str(r.symbol).strip().upper()] = age
            except Exception:
                age_map = {}

            def _format_setup_age(sym: str) -> str:
                age = age_map.get(str(sym).strip().upper(), 1)
                if age <= 2:
                    return f"Fresh (D{age})"
                elif age <= 7:
                    return f"Coiling (D{age})"
                else:
                    return f"Extended (D{age})"

            setup_pool["setup_age"] = setup_pool["symbol"].apply(_format_setup_age)
        else:
            setup_pool["inst_footprint"] = pd.Series(dtype=str)
            setup_pool["rvol_trail"] = pd.Series(dtype=str)
            setup_pool["ticket_flow"] = pd.Series(dtype=str)
            setup_pool["band_fmt"] = pd.Series(dtype=str)
            setup_pool["away_10ema"] = pd.Series(dtype=str)
            setup_pool["away_20ema"] = pd.Series(dtype=str)
            setup_pool["rs_5d_trail"] = pd.Series(dtype=str)
            setup_pool["rs_5d_trail_html"] = pd.Series(dtype=str)
            setup_pool["setup_age"] = pd.Series(dtype=str)

        # Attach macro theme tags to setup pool
        user_db_path = Path(db_path).parent / "marketpulse_user.duckdb"
        stock_tags = get_stock_thematic_tags(str(user_db_path))
        if not setup_pool.empty:
            setup_pool["theme"] = setup_pool["symbol"].map(lambda s: stock_tags.get(s, ["—"])[0])
            # Compact peer chip: industry abbrev + stock RS rank within industry
            # (same owner as Stock 360 peer list — NOT sector_rotation.rotation_rank)
            try:
                peer_ranks = con.execute(
                    """
                    WITH latest AS (SELECT max(trade_date) AS d FROM indicators_daily)
                    SELECT m.symbol,
                           m.industry,
                           m.sector,
                           rank() OVER (
                               PARTITION BY m.industry
                               ORDER BY i.rs_percentile DESC NULLS LAST, i.close_price DESC
                           ) AS ind_rs_rank
                    FROM indicators_daily i
                    JOIN stocks_master m ON m.symbol = i.symbol
                    JOIN latest ON i.trade_date = latest.d
                    WHERE m.industry IS NOT NULL AND m.industry <> ''
                    """
                ).fetchdf()
                rank_by_sym = {
                    str(r.symbol): (str(r.industry), int(r.ind_rs_rank))
                    for r in peer_ranks.itertuples(index=False)
                } if not peer_ranks.empty else {}
            except Exception:
                rank_by_sym = {}

            def _peer_chip(row):
                sym = str(row.get("symbol") or "").strip().upper()
                industry = str(row.get("industry") or "").strip()
                sector = str(row.get("sector") or "").strip()
                hit = rank_by_sym.get(sym)
                if hit:
                    return peer_chip_label(hit[0], hit[1])
                return peer_chip_label(industry or sector, None)

            setup_pool["peer"] = setup_pool.apply(_peer_chip, axis=1)
            try:
                _uc_map = uc_score_map(db_path, limit=200)
            except Exception:
                _uc_map = {}
            setup_pool["uc_flag"] = setup_pool["symbol"].map(
                lambda s: uc_flag_label(_uc_map.get(str(s).strip().upper()))
            )
            setup_pool["uc_score"] = setup_pool["symbol"].map(
                lambda s: _uc_map.get(str(s).strip().upper())
            )

        else:
            setup_pool["theme"] = pd.Series(dtype=str)
            setup_pool['peer'] = pd.Series(dtype=str)
            setup_pool['uc_flag'] = pd.Series(dtype=str)
            setup_pool['uc_score'] = pd.Series(dtype=float)

        # Attach institutional deal accumulation tags to setup pool (25-day lookback)
        deals_agg = con.execute(
            """
            SELECT 
                symbol,
                count(*) as deals_cnt,
                round(sum(CASE WHEN side = 'BUY' THEN COALESCE(deal_value_cr, quantity * price / 10000000.0) ELSE 0 END), 1) as buy_cr,
                round(sum(CASE WHEN side = 'SELL' THEN COALESCE(deal_value_cr, quantity * price / 10000000.0) ELSE 0 END), 1) as sell_cr
            FROM deals
            WHERE trade_date >= (SELECT max(trade_date) - INTERVAL 25 DAY FROM deals)
            GROUP BY symbol
            """
        ).fetchdf()
        deal_badge_map = {}
        if not deals_agg.empty:
            for _, r in deals_agg.iterrows():
                b_cr = float(r["buy_cr"] or 0)
                if b_cr >= 10.0:
                    deal_badge_map[r["symbol"]] = f"🏛️ +₹{b_cr:,.0f}Cr"
                elif r["deals_cnt"] > 0:
                    deal_badge_map[r["symbol"]] = f"🏛️ {int(r['deals_cnt'])} Deals"
        if not setup_pool.empty:
            setup_pool["deal_flow"] = setup_pool["symbol"].map(deal_badge_map).fillna("—")
        else:
            setup_pool["deal_flow"] = pd.Series(dtype=str)

        # Trailing bars for Darvas Box calculation across setup pool.
        # Weekly flag may fetch 400 sessions for resampling; daily queue still uses 252 / 45.
        darvas_hist = pd.DataFrame()
        daily_lookback = int(DARVAS["box_lookback_sessions"]) if use_v2 else 45
        fetch_lookback = max(daily_lookback, int(WEEKLY_LOOKBACK_SESSIONS))
        if not setup_pool.empty:
            pool_symbols = setup_pool["symbol"].tolist()
            con.register("pool_syms_tbl", pd.DataFrame({"symbol": pool_symbols}))
            darvas_hist = con.execute(
                f"""
                WITH dates AS (
                    SELECT DISTINCT trade_date 
                    FROM indicators_daily 
                    ORDER BY trade_date DESC 
                    LIMIT {int(fetch_lookback)}
                )
                SELECT i.symbol, i.trade_date, i.open_price, i.high_price, i.low_price, i.close_price, i.ema_10, i.ema_20, i.rvol, i.volume, i.ema_shakeout, i.close_location_pct, i.avg_volume_20d
                FROM indicators_daily i
                JOIN pool_syms_tbl p ON i.symbol = p.symbol
                JOIN dates d ON i.trade_date = d.trade_date
                ORDER BY i.symbol, i.trade_date ASC
                """
            ).fetchdf()

    # Classify the Setup Queues (No stop loss filter in screeners)
    # -------------------------------------------------------------
    # Queue 5: Darvas Box & 10/20 EMA Squeeze (Decoupled from RS)
    # Squeeze into top box and 10 EMA / 20 EMA. No stop-loss filter.
    # Weekly & Monthly paths available via screener timeframe toggle.
    # -------------------------------------------------------------
    def _hist_last_sessions(hist: pd.DataFrame, n: int) -> pd.DataFrame:
        if hist is None or hist.empty:
            return hist
        sessions = pd.to_datetime(hist["trade_date"]).drop_duplicates().sort_values()
        keep = set(sessions.tail(int(n)))
        return hist.loc[pd.to_datetime(hist["trade_date"]).isin(keep)].copy()

    darvas_hist_daily = _hist_last_sessions(darvas_hist, daily_lookback)

    def _assemble_darvas_queue(
        cand_df: pd.DataFrame, *, v2: bool, weekly: bool = False
    ) -> tuple[pd.DataFrame, int]:
        if cand_df is None or cand_df.empty or setup_pool.empty:
            return pd.DataFrame(), 0
        out = setup_pool.merge(cand_df, on="symbol", how="inner")
        if out.empty:
            return pd.DataFrame(), 0
        # Invariant: Darvas Squeeze must only show stocks trading ABOVE 200 EMA.
        # Stocks below 200 EMA are consolidating in a downtrend — not valid squeeze candidates.
        if v2 and "ema_200" in out.columns:
            ema200 = pd.to_numeric(out["ema_200"], errors="coerce")
            cmp = pd.to_numeric(out["cmp"], errors="coerce")
            out = out.loc[(cmp > ema200) | ema200.isna()].copy()
        if out.empty:
            return pd.DataFrame(), 0
        out["trigger_price"] = out["darvas_top"]
        if weekly and "ema_floor" in out.columns:
            stop_base = pd.to_numeric(out["ema_floor"], errors="coerce")
        else:
            stop_base = out["ema_10"]
        out["stop_loss"] = (stop_base * 0.985).round(2)
        out["risk_pct"] = ((out["trigger_price"] / out["stop_loss"] - 1.0) * 100.0).round(2)
        out["setup_type"] = "Darvas Squeeze"
        if v2:
            out["why_now"] = [
                f"Close inside, wick ≤1.5% under stacked 10/20 floor · Squeezed {sq:.1f}% (Range {cr:.1f}%) into Green Line ₹{top:,.1f}"
                + (f" · {fp}" if fp and fp != "—" else "")
                for sq, cr, top, fp in zip(
                    out["squeeze_pct"],
                    out["candle_range_pct"],
                    out["darvas_top"],
                    out["inst_footprint"] if "inst_footprint" in out.columns else [""] * len(out),
                )
            ]
            return apply_display_window(out)
        out["why_now"] = [
            f"OHLC inside box · Squeezed {sq:.1f}% (Range {cr:.1f}%) into Green Line ₹{top:,.1f}"
            + (f" · {fp}" if fp and fp != "—" else "")
            for sq, cr, top, fp in zip(
                out["squeeze_pct"],
                out["candle_range_pct"],
                out["darvas_top"],
                out["inst_footprint"] if "inst_footprint" in out.columns else [""] * len(out),
            )
        ]
        out = out.sort_values(["squeeze_pct", "candle_range_pct"], ascending=[True, True]).head(150)
        return out, int(len(out))

    darvas_cand_df = pd.DataFrame()
    if not darvas_hist_daily.empty:
        if use_v2:
            sq_frame = squeeze_frame(darvas_hist_daily, timeframe="D")
            if not sq_frame.empty:
                darvas_cand_df = sq_frame.loc[sq_frame["qualifies"]].copy()
        else:
            rows = []
            for sym, group in darvas_hist_daily.groupby("symbol"):
                if len(group) < 10:
                    continue
                top_box, bottom_box = calculate_darvas_box(
                    group["high_price"].values, group["low_price"].values, boxp=5
                )
                last_o = float(group["open_price"].iloc[-1])
                last_h = float(group["high_price"].iloc[-1])
                last_l = float(group["low_price"].iloc[-1])
                last_c = float(group["close_price"].iloc[-1])
                last_top = float(top_box[-1])
                last_btm = float(bottom_box[-1])
                last_ema10 = float(group["ema_10"].iloc[-1])
                last_ema20 = (
                    float(group["ema_20"].iloc[-1])
                    if "ema_20" in group.columns and pd.notna(group["ema_20"].iloc[-1])
                    else None
                )
                if last_ema20 is not None and last_ema10 < last_ema20:
                    continue
                if is_darvas_10ema_squeeze_legacy(
                    last_c,
                    last_top,
                    last_btm,
                    last_ema10,
                    high=last_h,
                    low=last_l,
                    open_price=last_o,
                    max_squeeze_pct=5.0,
                    max_candle_range_pct=4.0,
                    require_ohlc_inside=True,
                    ema20=last_ema20,
                ):
                    sq_pct = round(((last_top - last_ema10) / last_top) * 100.0, 2)
                    sq_pct = max(0.0, min(sq_pct, 5.0))
                    cr_pct = round(((last_h - last_l) / last_c) * 100.0, 2) if last_c > 0 else 0.0
                    rows.append({
                        "symbol": sym,
                        "darvas_top": round(last_top, 2),
                        "darvas_bottom": round(last_btm, 2),
                        "squeeze_pct": sq_pct,
                        "candle_range_pct": cr_pct,
                    })
            darvas_cand_df = pd.DataFrame(rows)

    darvas_df, darvas_count = _assemble_darvas_queue(darvas_cand_df, v2=use_v2)

    def _assemble_darvas_10ema_queue(
        flav: pd.DataFrame, exclude_syms: set | None = None, is_resampled: bool = False
    ) -> pd.DataFrame:
        if flav is None or flav.empty or setup_pool.empty:
            return pd.DataFrame()
        if exclude_syms:
            flav = flav[~flav["symbol"].isin(exclude_syms)].copy()
        if flav.empty:
            return pd.DataFrame()
        rename_dict = {
            "rvol": "flavor_rvol",
            "away_10ema_pct": "flavor_away_10ema_pct",
        }
        cols_to_keep = ["symbol", "flavor", "thrust_pct", "away_10ema_pct", "rvol"]
        if is_resampled and "ema_10" in flav.columns:
            rename_dict["ema_10"] = "flavor_ema_10"
            cols_to_keep.append("ema_10")
        flav_slim = flav[[c for c in cols_to_keep if c in flav.columns]].rename(
            columns=rename_dict
        )
        out = setup_pool.merge(flav_slim, on="symbol", how="inner")
        # Invariant: Darvas 10 EMA setups must also trade ABOVE 200 EMA.
        if not out.empty and "ema_200" in out.columns:
            ema200 = pd.to_numeric(out["ema_200"], errors="coerce")
            cmp = pd.to_numeric(out["cmp"], errors="coerce")
            out = out.loc[(cmp > ema200) | ema200.isna()].copy()
        if not out.empty:
            base_ema = out["flavor_ema_10"] if (is_resampled and "flavor_ema_10" in out.columns) else out["ema_10"]
            out["trigger_price"] = base_ema.round(2)
            out["stop_loss"] = (base_ema * 0.985).round(2)
            out["risk_pct"] = (
                (out["trigger_price"] / out["stop_loss"] - 1.0) * 100.0
            ).round(2)
            out["setup_type"] = "Darvas 10 EMA"
            out["why_now"] = [
                f"{fl} after thrust {tp:.1f}% · dry rvol {rv:.2f} · away 10EMA {aw:+.1f}%"
                + (f" · {fp}" if fp and fp != "—" else "")
                for fl, tp, rv, aw, fp in zip(
                    out["flavor"],
                    out["thrust_pct"],
                    out["flavor_rvol"],
                    out["flavor_away_10ema_pct"],
                    out["inst_footprint"] if "inst_footprint" in out.columns else [""] * len(out),
                )
            ]
            out = out.sort_values(
                ["flavor", "flavor_away_10ema_pct"], ascending=[True, True]
            ).head(QUEUE_DISPLAY_CAPS.get("darvas_10ema", 40))
        return out

    darvas_10ema_df = pd.DataFrame()
    if not darvas_hist_daily.empty and not setup_pool.empty:
        flav = classify_darvas_10ema_frame(darvas_hist_daily)
        exclude_darvas = set(darvas_df["symbol"].astype(str)) if not darvas_df.empty and "symbol" in darvas_df.columns else None
        darvas_10ema_df = _assemble_darvas_10ema_queue(flav, exclude_syms=exclude_darvas, is_resampled=False)



    # -------------------------------------------------------------
    # Queue: VCP (Manas Arora Progressive Contractions + VDU)
    # -------------------------------------------------------------
    vcp_df = pd.DataFrame()
    if not darvas_hist_daily.empty and not setup_pool.empty:
        vcp_hist = darvas_hist_daily
        # Prefer full lookback for purple/3M (darvas_hist already 252 when v2)
        if not darvas_hist.empty and len(darvas_hist) >= len(darvas_hist_daily):
            vcp_hist = darvas_hist
        flav = classify_vcp_frame(vcp_hist)
        if not flav.empty:
            vcp_cols_to_merge = [
                "symbol",
                "vcp_stage",
                "contractions_depth",
                "vdu_active",
                "vdu_ratio",
                "pivot_price",
                "stop_price",
                "pivot_distance_pct",
                "vcp_score",
                "purple_n",
                "ret_3m_pct",
                "close_location_pct",
                "ema_rising",
                "avg_volume_20d",
            ]
            vcp_slim = flav[[c for c in vcp_cols_to_merge if c in flav.columns]].copy()
            vcp_df = setup_pool.merge(vcp_slim, on="symbol", how="inner")
            if not vcp_df.empty:
                # Invariant: VCP must trade ABOVE 200 EMA (Stage 2 template)
                if "ema_200" in vcp_df.columns:
                    ema200 = pd.to_numeric(vcp_df["ema_200"], errors="coerce")
                    cmp = pd.to_numeric(vcp_df["cmp"], errors="coerce")
                    vcp_df = vcp_df.loc[(cmp > ema200) | ema200.isna()].copy()
                # Liquidity reinforce: avg_volume_20d >= 100k when column present
                if "avg_volume_20d" in vcp_df.columns:
                    vcp_df = vcp_df[
                        vcp_df["avg_volume_20d"].isna()
                        | (vcp_df["avg_volume_20d"] >= float(VCP.get("min_avg_volume_20d", 100_000)))
                    ].copy()
                if "cmp" in vcp_df.columns:
                    vcp_df = vcp_df[vcp_df["cmp"] >= float(VCP.get("min_close_price", 30.0))].copy()
                if not vcp_df.empty:
                    # Trigger price: pivot resistance breakout (or CMP * 1.005 if already above pivot)
                    triggers = []
                    for _, r in vcp_df.iterrows():
                        pp = r.get("pivot_price")
                        cmp_val = float(r["cmp"])
                        if pd.notna(pp) and float(pp) > cmp_val:
                            triggers.append(round(float(pp), 2))
                        else:
                            triggers.append(round(cmp_val * 1.005, 2))
                    vcp_df["trigger_price"] = triggers

                    # Stop loss: low of final contraction wave (stop_price) or EMA20/EMA10 floor
                    stop_losses = []
                    for _, r in vcp_df.iterrows():
                        sp = r.get("stop_price")
                        cmp_val = float(r["cmp"])
                        if pd.notna(sp) and float(sp) > 0 and float(sp) < cmp_val:
                            sl = round(float(sp) * 0.995, 2)
                        elif "ema_20" in r and pd.notna(r["ema_20"]) and float(r["ema_20"]) < cmp_val:
                            sl = round(float(r["ema_20"]) * 0.985, 2)
                        elif "ema_10" in r and pd.notna(r["ema_10"]) and float(r["ema_10"]) < cmp_val:
                            sl = round(float(r["ema_10"]) * 0.985, 2)
                        else:
                            sl = round(cmp_val * 0.95, 2)
                        stop_losses.append(sl)
                    vcp_df["stop_loss"] = stop_losses
                    vcp_df["risk_pct"] = (
                        (vcp_df["trigger_price"] / vcp_df["stop_loss"] - 1.0) * 100.0
                    ).round(2)
                    vcp_df["setup_type"] = "VCP"

                    # Explainable Manas Arora rationale
                    why_now_list = []
                    for _, r in vcp_df.iterrows():
                        stage = str(r.get("vcp_stage") or "VCP")
                        depths = str(r.get("contractions_depth") or "—")
                        vdu_str = "VDU ✓" if r.get("vdu_active") else f"Vol {float(r.get('vdu_ratio') or 1.0):.2f}x"
                        p_dist = float(r.get("pivot_distance_pct") or 0.0)
                        pn = int(r.get("purple_n") or 0)
                        r3 = float(r.get("ret_3m_pct") or 0.0)
                        rk = float(r.get("risk_pct") or 0.0)
                        score = float(r.get("vcp_score") or 0.0)
                        fp = str(r.get("inst_footprint") or "—")
                        fp_suffix = f" · {fp}" if fp and fp != "—" else ""
                        why_now_list.append(
                            f"{stage} ({depths}) · {vdu_str} · Pivot {p_dist:+.1f}% · Risk {rk:.1f}% · Score {score:.0f}{fp_suffix}"
                        )
                    vcp_df["why_now"] = why_now_list
                    # Rank: highest VCP score first, then tightest pivot distance, then rising EMA
                    sort_cols = ["vcp_score", "pivot_distance_pct", "ema_rising"]
                    ascending = [False, False, False]
                    if "away_52w_high_pct" in vcp_df.columns:
                        sort_cols.append("away_52w_high_pct")
                        ascending.append(False)
                    vcp_df = vcp_df.sort_values(sort_cols, ascending=ascending).head(
                        QUEUE_DISPLAY_CAPS.get("vcp", 40)
                    )

    darvas_weekly_df = pd.DataFrame()
    darvas_count_weekly = 0
    darvas_monthly_df = pd.DataFrame()
    darvas_count_monthly = 0
    darvas_10ema_weekly_df = pd.DataFrame()
    darvas_count_10ema_weekly = 0
    darvas_10ema_monthly_df = pd.DataFrame()
    darvas_count_10ema_monthly = 0
    if not darvas_hist.empty:
        sq_weekly = squeeze_frame(darvas_hist, timeframe="W", as_of=trade_date)
        cand_w = sq_weekly.loc[sq_weekly["qualifies"]].copy() if not sq_weekly.empty else pd.DataFrame()
        darvas_weekly_df, darvas_count_weekly = _assemble_darvas_queue(cand_w, v2=True, weekly=True)

        sq_monthly = squeeze_frame(darvas_hist, timeframe="M", as_of=trade_date)
        cand_m = sq_monthly.loc[sq_monthly["qualifies"]].copy() if not sq_monthly.empty else pd.DataFrame()
        darvas_monthly_df, darvas_count_monthly = _assemble_darvas_queue(cand_m, v2=True, weekly=True)

        flav_w = classify_darvas_10ema_frame(darvas_hist, timeframe="W", as_of=trade_date)
        exclude_w = set(darvas_weekly_df["symbol"].astype(str)) if not darvas_weekly_df.empty and "symbol" in darvas_weekly_df.columns else None
        darvas_10ema_weekly_df = _assemble_darvas_10ema_queue(flav_w, exclude_syms=exclude_w, is_resampled=True)
        darvas_count_10ema_weekly = len(darvas_10ema_weekly_df)

        flav_m = classify_darvas_10ema_frame(darvas_hist, timeframe="M", as_of=trade_date)
        exclude_m = set(darvas_monthly_df["symbol"].astype(str)) if not darvas_monthly_df.empty and "symbol" in darvas_monthly_df.columns else None
        darvas_10ema_monthly_df = _assemble_darvas_10ema_queue(flav_m, exclude_syms=exclude_m, is_resampled=True)
        darvas_count_10ema_monthly = len(darvas_10ema_monthly_df)

    def _is_num(v: Any) -> bool:
        if v is None or v is np.ma.masked:
            return False
        try:
            f = float(v)
            return not (np.isnan(f) or np.isinf(f))
        except Exception:
            return False

    try:
        from App.thematic_engine import get_macro_pulse
        macro_pulse = get_macro_pulse(Path(db_path))
    except Exception:
        try:
            from thematic_engine import get_macro_pulse
            macro_pulse = get_macro_pulse(Path(db_path))
        except Exception:
            macro_pulse = {"top": [], "bottom": []}
    data = {
        "ready": True,
        "trade_date": trade_date_str,
        "macro_pulse": macro_pulse,
        "exposure": {
            "pct": exposure_pct,
            "state": exposure_state,
            "badge": exposure_badge,
            "guidance": exposure_guidance,
            "adv_pct": adv_pct,
            "ab20_pct": ab20_pct,
            "ab50_pct": ab50_pct,
            "ab200_pct": ab200_pct,
            "breadth_source": breadth_source,
            "as_of": breadth_as_of,
            "vix": vix_val,
            "vix_1d_pct": vix_1d_pct,
            "vix_available": gate["vix_available"],
            "vix_na": gate["vix_na"],
            "vix_label": gate["vix_label"],
            "count_52w_highs": count_52w_highs,
            "count_52w_lows": count_52w_lows,
            "net_highs": net_highs,
            "total_stocks": total_stocks,
        },
        "themes": top_sectors,
        "darvas_count": darvas_count,
        "darvas_count_weekly": darvas_count_weekly,
        "darvas_count_monthly": darvas_count_monthly,
        "darvas_10ema_count": len(darvas_10ema_df),
        "darvas_10ema_count_weekly": darvas_count_10ema_weekly,
        "darvas_10ema_count_monthly": darvas_count_10ema_monthly,
        "darvas_weekly_enabled": True,
        "queues": {
            "darvas": darvas_df,
            "darvas_10ema": darvas_10ema_df,
            "vcp": vcp_df,
            "darvas_weekly": darvas_weekly_df,
            "darvas_monthly": darvas_monthly_df,
            "darvas_10ema_weekly": darvas_10ema_weekly_df,
            "darvas_10ema_monthly": darvas_10ema_monthly_df,
        },
        "tv_lists": {
            "darvas": to_tv_list(darvas_df["symbol"].tolist()) if not darvas_df.empty else "",
            "darvas_10ema": to_tv_list(darvas_10ema_df["symbol"].tolist()) if not darvas_10ema_df.empty else "",
            "vcp": to_tv_list(vcp_df["symbol"].tolist()) if not vcp_df.empty else "",
            "darvas_weekly": to_tv_list(darvas_weekly_df["symbol"].tolist()) if not darvas_weekly_df.empty else "",
            "darvas_monthly": to_tv_list(darvas_monthly_df["symbol"].tolist()) if not darvas_monthly_df.empty else "",
            "darvas_10ema_weekly": to_tv_list(darvas_10ema_weekly_df["symbol"].tolist()) if not darvas_10ema_weekly_df.empty else "",
            "darvas_10ema_monthly": to_tv_list(darvas_10ema_monthly_df["symbol"].tolist()) if not darvas_10ema_monthly_df.empty else "",
            "all_focus": to_tv_list(
                list(dict.fromkeys(
                    (darvas_df["symbol"].tolist() if not darvas_df.empty else [])
                    + (darvas_10ema_df["symbol"].tolist() if not darvas_10ema_df.empty else [])
                    + (vcp_df["symbol"].tolist() if not vcp_df.empty else [])
                ))
            ),
        },

    }

    set_cached(key, data)
    return data


def render_inline_candlestick_chart(db_path: Path | str, symbol: str, is_darvas: bool = False) -> None:
    cdata = query_stock_candlestick_data(Path(db_path), symbol, limit=90)
    if not cdata:
        ui.label(f"No historical candlestick data available for {symbol}.").classes("text-sm text-[var(--mp-muted)] p-4")
        return

    if is_darvas and cdata.get("is_darvas_squeeze"):
        with ui.row().classes("w-full items-center justify-between px-3 py-1.5 rounded bg-emerald-950/40 border border-emerald-500/50 text-emerald-300 text-xs font-mono mb-2"):
            ui.label("🎯 DARVAS 10 EMA SQUEEZE (OHLC INSIDE BOX)").classes("font-bold text-emerald-400 tracking-wide")
            cr = f" · Candle Range: {cdata['candle_range_pct']:.1f}%" if cdata.get('candle_range_pct') is not None else ""
            top_txt = f" · Green Line: ₹{cdata['latest_darvas_top']:,.1f}" if cdata.get('latest_darvas_top') else ""
            ema_txt = f" · 10 EMA: ₹{cdata['ema10'][-1]:,.1f}" if cdata.get('ema10') and cdata['ema10'][-1] else ""
            ui.label(f"Spread: {cdata['darvas_squeeze_pct']:.1f}%{cr}{top_txt}{ema_txt}").classes("font-semibold")

    # Squeeze corridor highlight markArea
    squeeze_mark_area = None
    if is_darvas and cdata.get("latest_darvas_top"):
        top_val = cdata["latest_darvas_top"]
        ema_val = cdata["ema10"][-1] if cdata.get("ema10") and cdata["ema10"][-1] else None
        bot_val = cdata.get("latest_darvas_bottom")
        lower_bound = ema_val if ema_val is not None else bot_val
        if lower_bound:
            recent_idx = max(0, len(cdata["dates"]) - 15)
            start_d = cdata["dates"][recent_idx]
            end_d = cdata["dates"][-1]
            squeeze_mark_area = {
                "silent": True,
                "itemStyle": {
                    "color": "rgba(16, 185, 129, 0.09)",
                    "borderColor": "rgba(16, 185, 129, 0.45)",
                    "borderWidth": 1.5,
                    "borderType": "dashed",
                },
                "data": [
                    [
                        {
                            "name": "🎯 Squeeze Zone",
                            "coord": [start_d, top_val],
                            "label": {
                                "show": True,
                                "color": "#34d399",
                                "fontSize": 10,
                                "position": "insideTopRight",
                                "formatter": f"🎯 Darvas Squeeze ({cdata.get('darvas_squeeze_pct', 0):.1f}%)" if cdata.get("darvas_squeeze_pct") else "🎯 Darvas Squeeze",
                            },
                        },
                        {"coord": [end_d, min(top_val, lower_bound)]},
                    ]
                ],
            }

    legend_items = ["Price", "10 EMA", "20 EMA", "50 EMA", "200 EMA"]
    series = [
        {
            "name": "Price",
            "type": "candlestick",
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "data": cdata["ohlc"],
            "itemStyle": {
                "color": "#10b981",
                "color0": "#ef4444",
                "borderColor": "#10b981",
                "borderColor0": "#ef4444"
            },
            "markArea": squeeze_mark_area,
        },
    ]

    if is_darvas:
        legend_items.insert(1, "Darvas Top")
        legend_items.insert(2, "Darvas Bottom")
        series.extend([
            {
                "name": "Darvas Top",
                "type": "line",
                "step": "end",
                "xAxisIndex": 0,
                "yAxisIndex": 0,
                "data": cdata.get("darvas_top", []),
                "lineStyle": {"color": "#22c55e", "width": 2.5},
                "showSymbol": False,
            },
            {
                "name": "Darvas Bottom",
                "type": "line",
                "step": "end",
                "xAxisIndex": 0,
                "yAxisIndex": 0,
                "data": cdata.get("darvas_bottom", []),
                "lineStyle": {"color": "#ef4444", "width": 1.5},
                "showSymbol": False,
            },
        ])

    series.extend([
        {"name": "10 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema10"], "smooth": True, "lineStyle": {"color": "#ffffff", "width": 2.0}, "showSymbol": False},
        {"name": "20 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema20"], "smooth": True, "lineStyle": {"color": "#fbbf24", "width": 1.5}, "showSymbol": False},
        {"name": "50 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema50"], "smooth": True, "lineStyle": {"color": "#f97316", "width": 1.5}, "showSymbol": False},
        {"name": "200 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema200"], "smooth": True, "lineStyle": {"color": "#ec4899", "width": 1.5}, "showSymbol": False},
        {
            "name": "Volume",
            "type": "bar",
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "data": cdata["volume"],
            "itemStyle": {"color": "#475569"}
        },
        {
            "name": "RSI(14)",
            "type": "line",
            "xAxisIndex": 2,
            "yAxisIndex": 2,
            "data": cdata["rsi"],
            "lineStyle": {"color": "#a855f7", "width": 1.5},
            "showSymbol": False
        }
    ])

    total_bars = len(cdata["dates"])
    zoom_20d_pct = max(0.0, round(((total_bars - 22) / max(total_bars, 1)) * 100.0, 1))
    zoom_45d_pct = max(0.0, round(((total_bars - 45) / max(total_bars, 1)) * 100.0, 1))
    zoom_start_pct = zoom_20d_pct

    echart_opt = {
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
            "data": legend_items,
            "textStyle": {"color": "#94a3b8", "fontSize": 10},
            "top": 0
        },
        "grid": [
            {"left": "5%", "right": "3%", "top": "7%", "height": "60%"},
            {"left": "5%", "right": "3%", "top": "70%", "height": "12%"},
            {"left": "5%", "right": "3%", "top": "84%", "height": "10%"},
        ],
        "xAxis": [
            {"type": "category", "gridIndex": 0, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"onZero": False, "lineStyle": {"color": "#334155"}}, "axisLabel": {"show": False}},
            {"type": "category", "gridIndex": 1, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"onZero": False, "lineStyle": {"color": "#334155"}}, "axisLabel": {"show": False}},
            {"type": "category", "gridIndex": 2, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"onZero": False, "lineStyle": {"color": "#334155"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 9}},
        ],
        "yAxis": [
            {"scale": True, "gridIndex": 0, "splitLine": {"lineStyle": {"color": "#1e293b"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 10}},
            {"scale": True, "gridIndex": 1, "splitLine": {"show": False}, "axisLabel": {"show": False}},
            {"scale": True, "gridIndex": 2, "min": 0, "max": 100, "splitLine": {"lineStyle": {"color": "#1e293b"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 9}},
        ],
        "dataZoom": [
            {
                "type": "inside",
                "xAxisIndex": [0, 1, 2],
                "start": zoom_start_pct,
                "end": 100,
                "minValueSpan": 10,
                "zoomOnMouseWheel": True,
                "moveOnMouseMove": True,
            },
            {
                "type": "slider",
                "xAxisIndex": [0, 1, 2],
                "start": zoom_start_pct,
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
                "selectedDataBackground": {
                    "lineStyle": {"color": "#10b981"},
                    "areaStyle": {"color": "rgba(16, 185, 129, 0.3)"},
                },
                "textStyle": {"color": "#94a3b8", "fontSize": 10},
            },
        ],
        "series": series
    }
    chart_elem = ui.echart(echart_opt).classes("w-full h-[500px]")

    with ui.row().classes("w-full items-center justify-end gap-2 my-1 text-xs"):
        ui.label("Zoom Focus:").classes("text-[var(--mp-muted)] font-mono")
        ui.button("🎯 20D (Squeeze Focus)", on_click=lambda: chart_elem.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': zoom_20d_pct, 'end': 100})).props("dense outline size=xs").classes("mp-button")
        ui.button("⏳ 45D (Base)", on_click=lambda: chart_elem.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': zoom_45d_pct, 'end': 100})).props("dense outline size=xs").classes("mp-button")
        ui.button("📊 90D (All)", on_click=lambda: chart_elem.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': 0, 'end': 100})).props("dense outline size=xs").classes("mp-button")


def build_action_desk_page(
    db_path: Path | str,
    section_header: Callable,
    table_from_df: Callable,
    copy_text: Callable | None = None,
) -> None:
    """Build the Action Desk view inside NiceGUI (3-Column Master-Detail Cockpit)."""
    render_market_health_strip(Path(db_path))
    data = fetch_action_desk_data(db_path)
    if not data.get("ready"):
        ui.label(data.get("reason", "Action Desk initializing...")).classes("text-sm text-[var(--mp-muted)] p-4")
        return

    exp = data["exposure"]
    themes = data["themes"]
    queues = data["queues"]
    tv = data["tv_lists"]

    # =========================================================================
    # Playbook access (macro pulse strip retired)
    with ui.row().classes("w-full items-center justify-end mb-3"):
        ui.button("Trading Playbook & Field Guide", on_click=open_playbook_modal).classes(
            "mp-button text-xs bg-emerald-500 text-slate-950 font-bold hover:bg-emerald-400"
        ).props("dense unelevated")

    queue_meta = dict(QUEUE_META)
    if darvas_v2_enabled():
        darvas_meta = dict(queue_meta["darvas"])
        darvas_meta["desc"] = (
            "Close inside, wick ≤1.5% under stacked 10/20 floor, squeezed into Green Line (TopBox)."
        )
        queue_meta["darvas"] = darvas_meta

    # Initial selection
    initial_queue = "darvas"
    initial_sym = ""
    for q_key in list(PRIMARY_QUEUES):
        q_df = queues.get(q_key, pd.DataFrame())
        if not q_df.empty and "symbol" in q_df.columns:
            if not initial_sym:
                initial_queue = q_key
                initial_sym = str(q_df["symbol"].iloc[0])
                break

    state = {
        "active_queue": initial_queue,
        "selected_symbol": initial_sym,
        "real_inst_flow_only": False,
        "darvas_tf": "Daily",
        "darvas_10ema_tf": "Daily",
        "matrix_rows_per_page": 25,
        "matrix_page": 1,
    }

    # Display columns for the matrix
    display_cols = [
        "symbol", "setup_age", "rs_5d_trail", "flavor", "purple_n", "ret_3m_pct", "close_location_pct", "peer", "uc_flag", "inst_footprint", "ticket_flow", "band_fmt", "away_10ema", "deal_flow", "rvol_trail", "theme", "cmp", "trigger_price", "stop_loss",
        "day_pct", "rvol", "delivery_pct", "rs_percentile", "pe", "sector"
    ]

    # Cockpit 3-column split-pane layout
    with ui.element("div").classes("mp-cockpit-container w-full"):

        # =====================================================================
        # COLUMN 1: FUNNEL & QUEUES (Left Column - 250px)
        # =====================================================================
        with ui.column().classes("mp-funnel-col"):

            # Card 1: Market Exposure Gate
            with ui.card().classes("w-full mp-card p-3 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("STEP 1: EXPOSURE GATE").classes("text-[11px] font-bold tracking-wider text-[var(--mp-primary)] uppercase")
                    ui.label(str(data["trade_date"])).classes("text-[10px] text-[var(--mp-muted)] font-mono")

                with ui.row().classes("w-full items-center justify-between mt-2"):
                    ui.label("EXPOSURE:").classes("text-xs text-[var(--mp-muted)] font-semibold")
                    ui.label(exp["pct"]).classes(f"text-sm font-black px-2 py-0.5 rounded {exp['badge']}")

                ui.label(exp["state"]).classes("text-xs font-semibold text-[var(--mp-text)] mt-1")
                ui.label(exp["guidance"]).classes("text-[11px] text-[var(--mp-muted)] mt-1 leading-snug font-mono")

                src = exp.get("breadth_source") or ""
                src_label = "indicators_daily fallback" if src == "indicators_daily" else (src or "breadth")
                as_of = exp.get("as_of") or data["trade_date"]
                ui.label(f"{as_of} · {src_label}").classes("text-[10px] text-[var(--mp-muted)] font-mono mt-1")

                if copy_text and tv.get("all_focus"):
                    ui.button(
                        "📋 Copy All Focus (TV)",
                        on_click=lambda: copy_text("All Focus (TV)", tv["all_focus"]),
                    ).classes("mp-button w-full text-[11px] mt-2").props("dense outline")

            # Card 2: Leading Sector Themes
            with ui.card().classes("w-full mp-card p-3 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                with ui.row().classes("w-full items-center justify-between mb-1.5"):
                    ui.label("STEP 2: LEADING THEMES").classes("text-[11px] font-bold tracking-wider text-[var(--mp-primary)] uppercase")
                    ui.label("Δ 5D Share").classes("text-[9px] text-[var(--mp-muted)] font-mono")

                with ui.column().classes("w-full gap-1.5"):
                    if themes.empty:
                        ui.label("No Leading/Emerging + ΔSHARE>0 themes today.").classes("text-[11px] text-[var(--mp-muted)]")
                    for idx, (_, sec) in enumerate(themes.head(3).iterrows(), 1):
                        grp_name = str(sec.get("group_name") or sec.get("sector") or "—")
                        delta = float(sec.get("turnover_share_delta_5d") or 0.0)
                        leaders_raw = str(sec.get("leader_symbols") or sec.get("leaders") or "")
                        state_lbl = str(sec.get("rotation_state") or sec.get("state") or "").strip()
                        with ui.row().classes("w-full items-center justify-between p-1.5 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                            with ui.column().classes("gap-0 max-w-[150px]"):
                                ui.label(f"#{idx} {grp_name[:16]}").classes("font-bold text-xs text-[var(--mp-text)] truncate")
                                with ui.row().classes("items-center gap-1"):
                                    if state_lbl:
                                        ui.label(state_lbl).classes(rotation_badge_class(state_lbl) + " text-[9px]")
                                    if leaders_raw:
                                        top_sym = leaders_raw.split(",")[0].strip()
                                        ui.button(f"★ {top_sym}", on_click=lambda s=top_sym: select_symbol(s)).props("dense flat size=xs").classes("font-mono text-[9px] text-sky-400 p-0 hover:underline")
                            ui.label(f"Δ {delta:+.1f}pp").classes("text-xs font-mono " + signed_pct_class(delta))

            # Card 3: Setup Queues Navigation
            queue_nav_card = ui.card().classes("w-full mp-card p-3 border border-[var(--mp-border)] bg-[var(--mp-surface)]")

        # =====================================================================
        # COLUMN 2: CANDIDATE MATRIX (Center Column - 52% / flex-1)
        # =====================================================================
        matrix_host = ui.column().classes("mp-matrix-col")

        # =====================================================================
        # COLUMN 3: EMBEDDED STOCK INSPECTOR (Right Column - 440px)
        # =====================================================================
        inspector_host = ui.column().classes("mp-inspector-col")

    # Reactive interaction functions
    def select_symbol(sym: str) -> None:
        sym = str(sym or "").strip().upper()
        if not sym:
            return
        state["selected_symbol"] = sym
        # Do not rebuild the matrix here — Quasar pagination resets to page 1 on remount.
        render_inspector()

    def _darvas_is_weekly() -> bool:
        return state.get("darvas_tf") == "Weekly"

    def _darvas_is_monthly() -> bool:
        return state.get("darvas_tf") == "Monthly"

    def _queue_frame(q_key: str) -> pd.DataFrame:
        if q_key == "darvas":
            tf = state.get("darvas_tf", "Daily")
            if tf == "Weekly":
                return queues.get("darvas_weekly", pd.DataFrame())
            elif tf == "Monthly":
                return queues.get("darvas_monthly", pd.DataFrame())
        elif q_key == "darvas_10ema":
            tf = state.get("darvas_10ema_tf", "Daily")
            if tf == "Weekly":
                return queues.get("darvas_10ema_weekly", pd.DataFrame())
            elif tf == "Monthly":
                return queues.get("darvas_10ema_monthly", pd.DataFrame())
        return queues.get(q_key, pd.DataFrame())

    def set_queue(q_key: str) -> None:
        state["active_queue"] = q_key
        state["matrix_page"] = 1  # new queue → start at page 1; keep rows-per-page choice
        q_df = _queue_frame(q_key)
        if not q_df.empty and "symbol" in q_df.columns:
            state["selected_symbol"] = str(q_df["symbol"].iloc[0])
        render_queue_nav()
        render_matrix()
        render_inspector()

    def render_queue_nav() -> None:
        with queue_nav_card:
            queue_nav_card.clear()
            ui.label("STEP 3: SETUP QUEUES").classes("text-[11px] font-bold tracking-wider text-[var(--mp-primary)] uppercase mb-2")
            with ui.column().classes("w-full gap-1.5"):
                def _queue_btn(q_key: str) -> None:
                    q_info = queue_meta[q_key]
                    count = len(_queue_frame(q_key))
                    is_active = state["active_queue"] == q_key
                    with ui.button(
                        on_click=lambda k=q_key: set_queue(k)
                    ).classes(
                        "w-full justify-between text-left text-xs font-semibold px-2 py-1.5 rounded " +
                        ("bg-emerald-600/20 text-emerald-300 border border-emerald-500/40" if is_active else "bg-[var(--mp-surface-raised)] text-[var(--mp-text)] border border-[var(--mp-border)] hover:bg-[var(--mp-surface-2)]")
                    ).props("dense flat no-caps"):
                        ui.label(q_info["short_title"]).classes("truncate")
                        ui.label(str(count)).classes(
                            "text-[10px] font-mono px-1.5 py-0.2 rounded font-bold " +
                            ("bg-emerald-500 text-slate-950" if is_active and count > 0 else "bg-slate-800 text-slate-300")
                        )

                ui.label("PRIMARY").classes("text-[9px] font-bold tracking-wider text-emerald-400/80 mt-1")
                for q_key in PRIMARY_QUEUES:
                    if q_key in queue_meta:
                        _queue_btn(q_key)
    def render_matrix() -> None:
        with matrix_host:
            matrix_host.clear()

            q_key = state["active_queue"]
            q_info = queue_meta.get(q_key, queue_meta["darvas"])
            q_df = _queue_frame(q_key)
            if state.get("real_inst_flow_only") and not q_df.empty:
                has_deal = q_df["deal_flow"].astype(str).str.strip().ne("—") if "deal_flow" in q_df.columns else pd.Series(False, index=q_df.index)
                has_fp = q_df["inst_footprint"].astype(str).str.strip().ne("—") if "inst_footprint" in q_df.columns else pd.Series(False, index=q_df.index)
                q_df = q_df[has_deal | has_fp]
            if q_key == "darvas" and not q_df.empty and "squeeze_pct" in q_df.columns:
                q_df = q_df.sort_values(["squeeze_pct", "candle_range_pct"], ascending=[True, True])
            if not q_df.empty and "symbol" in q_df.columns:
                tv_text = to_tv_list(q_df["symbol"].tolist())
            else:
                tv_text = ""

            # Header Banner
            with ui.card().classes("w-full mp-card p-3 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                with ui.row().classes("w-full items-center justify-between flex-wrap gap-2"):
                    with ui.column().classes("gap-0.5"):
                        ui.label(q_info["title"]).classes("text-sm font-bold text-[var(--mp-text)]")
                        ui.label(q_info["desc"]).classes("text-xs text-[var(--mp-muted)]")
                    with ui.row().classes("items-center gap-2"):
                        if q_key in ("darvas", "darvas_10ema"):
                            tf_state_key = "darvas_tf" if q_key == "darvas" else "darvas_10ema_tf"
                            def _on_tf(e, k=q_key, sk=tf_state_key):
                                state[sk] = e.value
                                q_new = _queue_frame(k)
                                if not q_new.empty and "symbol" in q_new.columns:
                                    state["selected_symbol"] = str(q_new["symbol"].iloc[0])
                                render_queue_nav()
                                render_matrix()
                                render_inspector()
                            # Active multi-timeframe toggle: ["Daily", "Weekly"] extended to ["Daily", "Weekly", "Monthly"]
                            tf_toggle = ui.toggle(
                                ["Daily", "Weekly", "Monthly"],
                                value=state.get(tf_state_key, "Daily"),
                            ).props("dense unelevated").classes("mp-toggle text-xs")
                            tf_toggle.on_value_change(_on_tf)
                        if copy_text and tv_text:
                            btn_label = f"📋 Copy {q_info['short_title']} (TV)"
                            if q_key == "darvas":
                                tf = state.get("darvas_tf", "Daily")
                                btn_label = f"📋 Copy Darvas Squeeze ({tf}) (TV)"
                            elif q_key == "darvas_10ema":
                                tf = state.get("darvas_10ema_tf", "Daily")
                                btn_label = f"📋 Copy Darvas 10 EMA ({tf}) (TV)"
                            ui.button(
                                btn_label,
                                on_click=lambda *_, t=tv_text, lbl=btn_label: copy_text(lbl, t),
                            ).classes("mp-button text-xs font-bold").props("dense outline")

                # Quality Filter Strip
                is_classic_rs = False  # classic RS queues retired
                rules_txt = (
                    "Rules: MCap > ₹1000Cr · Circuit > 5% · Stage 2 Uptrend · Within 25% 52W · RS >= 70"
                    if is_classic_rs else
                    "Evidence-Based Rules: MCap > ₹1000Cr · 10/20 EMA Support · VDU & High Deliv · Institutional Footprint · No Stop-Loss Cutoff"
                )
                with ui.row().classes("w-full items-center justify-between text-[11px] text-[var(--mp-muted)] font-mono mt-2 pt-2 border-t border-[var(--mp-border)] flex-wrap gap-2"):
                    ui.label(rules_txt).classes("truncate")
                    with ui.row().classes("items-center gap-3"):
                        ui.label("Stop Loss: Off (No filter)").classes("font-bold text-emerald-400 font-mono")
                        ui.button(
                            "🏛️ Real Inst Flow Only",
                            on_click=lambda: (
                                state.update({"real_inst_flow_only": not state.get("real_inst_flow_only", False)}),
                                render_matrix(),
                            ),
                        ).props("dense size=xs").classes(
                            "font-mono font-bold px-2 py-0.5 rounded transition-all " +
                            ("bg-emerald-600 text-white shadow" if state.get("real_inst_flow_only") else "bg-slate-800 text-slate-400 border border-slate-700 hover:bg-slate-700")
                        )

                render_inline_field_guide_banner(q_key)

            # Candidate Quick Selector Chips
            if not q_df.empty and "symbol" in q_df.columns:
                symbols = [str(s) for s in q_df["symbol"].dropna().tolist()]
                with ui.row().classes("w-full items-center gap-1.5 flex-wrap p-2 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                    ui.label("INSPECT:").classes("text-[10px] font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                    for sym in symbols:
                        is_sel = (sym == state["selected_symbol"])
                        deal_str = ""
                        if "deal_flow" in q_df.columns:
                            match_row = q_df[q_df["symbol"] == sym]
                            if not match_row.empty:
                                deal_val = str(match_row["deal_flow"].iloc[0])
                                if deal_val and deal_val != "—":
                                    deal_str = f" {deal_val}"
                        ui.button(
                            f"{sym}{deal_str}",
                            on_click=lambda s=sym: select_symbol(s),
                        ).props("dense unelevated size=sm").classes(
                            "font-mono font-bold text-xs px-2 py-0.5 rounded transition-all " +
                            ("bg-emerald-600 text-white shadow" if is_sel else "bg-slate-800 text-slate-300 hover:bg-slate-700")
                        )

            # Candidates Table
            if q_df.empty:
                with ui.card().classes("w-full mp-card p-8 text-center border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
                    ui.label(f"No {q_info['short_title']} setups currently active in this session.").classes("text-sm text-[var(--mp-muted)]")
            else:
                matrix_cols = display_cols
                if q_key == "darvas":
                    squeeze_cols = [
                        "squeeze_pct", "candle_range_pct", "darvas_top",
                        "tightening", "squeeze_age", "failed_low",
                    ]
                    matrix_cols = ["symbol"] + squeeze_cols + [c for c in display_cols if c != "symbol"]
                table_cols = [c for c in matrix_cols if c in q_df.columns]
                rows_per = int(state.get("matrix_rows_per_page") or 25)
                page_now = int(state.get("matrix_page") or 1)
                pagination_dict = {"rowsPerPage": rows_per, "page": page_now}
                if q_key == "darvas":
                    pagination_dict["sortBy"] = "squeeze_pct"
                    pagination_dict["descending"] = False
                tbl = table_from_df(
                    q_df[table_cols],
                    "",
                    pagination=pagination_dict,
                )
                if tbl is not None:
                    def on_table_click(e):
                        try:
                            args = e.args
                            row = args[1] if isinstance(args, (list, tuple)) and len(args) > 1 else (args if isinstance(args, dict) else {})
                            s = row.get("symbol")
                            if s:
                                select_symbol(str(s))
                        except Exception:
                            pass

                    def on_pagination(e):
                        try:
                            pag = e.args if isinstance(e.args, dict) else {}
                            if not isinstance(pag, dict) and hasattr(e, "sender"):
                                pag = getattr(e.sender, "pagination", {}) or {}
                            if isinstance(pag, dict):
                                if "rowsPerPage" in pag and pag["rowsPerPage"]:
                                    state["matrix_rows_per_page"] = int(pag["rowsPerPage"])
                                if "page" in pag and pag["page"]:
                                    state["matrix_page"] = int(pag["page"])
                        except Exception:
                            pass

                    def on_stock_open(e):
                        sym = _table_event_symbol(e)
                        if sym:
                            select_symbol(sym)
                            open_stock_360_modal(Path(db_path), sym, copy_text=copy_text)

                    tbl.on("rowClick", on_table_click)
                    tbl.on("row-click", on_table_click)
                    tbl.on("open_stock", on_stock_open)
                    tbl.on("update:pagination", on_pagination)

    def render_inspector() -> None:
        with inspector_host:
            inspector_host.clear()
            sym = state["selected_symbol"]
            render_stock_inspector_panel(
                Path(db_path),
                sym,
                copy_text=copy_text,
                on_select_symbol=select_symbol,
            )

    # Initial render
    render_queue_nav()
    render_matrix()
    render_inspector()

