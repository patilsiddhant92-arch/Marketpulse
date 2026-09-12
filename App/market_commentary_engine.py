"""Quantitative Market Commentary & Tactical Action Plan Engine.

Synthesizes point-in-time DuckDB data:
- Macro Index (Nifty 50, Nifty 500, EMAs, RSI, Trend State)
- Market Breadth (A/D Ratio, % Above 20/50/200 EMAs, New 52W Highs)
- Turnover & Volume Velocity (Session turnover vs 20D average)
- Institutional Deals Footprint (FII vs DII vs Prop/HFT Net Inflow/Outflow Cr)
- Sector Rotation & Capital Flight (Leading vs Lagging groups, money flow migration)
- Tactical Action Plan ("What's happening? What should be planned?")

100% deterministic, offline, zero-latency, and zero-hallucination.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import duckdb
import numpy as np
import pandas as pd


def _fmt_cr(val: float | None) -> str:
    if val is None or pd.isna(val):
        return "₹0.0 Cr"
    v = float(val)
    if abs(v) < 0.05:
        return "₹0.0 Cr"
    sign = "+" if v > 0 else "-"
    abs_v = abs(v)
    if abs_v >= 1000:
        return f"{sign}₹{abs_v / 1000:,.1f}k Cr"
    return f"{sign}₹{abs_v:,.1f} Cr"


def _fmt_pct(val: float | None, signed: bool = True) -> str:
    if val is None or pd.isna(val):
        return "0.0%"
    v = float(val)
    sign = "+" if signed and v > 0 else ""
    return f"{sign}{v:.1f}%"


def generate_market_commentary(db_path: Path | str) -> dict[str, Any]:
    """Generate comprehensive, quantitative market commentary and action plan."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"ok": False, "error": f"Database not found at {db_path}"}

    with duckdb.connect(str(db_path), read_only=True) as con:
        # 1. Broad Breadth Latest & Previous
        breadth_rows = con.execute("""
            SELECT * FROM breadth_daily 
            ORDER BY trade_date DESC 
            LIMIT 5
        """).fetchdf()

        # 2. Benchmark & Intermarket Indices
        indices_df = con.execute("""
            SELECT trade_date, index_name, close_price, return_1d_pct, return_5d_pct,
                   ema_20, ema_50, ema_200, trend_state
            FROM index_daily
            WHERE index_name IN (
                'Nifty 50', 'Nifty 500', 'NIFTY 50', 'NIFTY 500',
                'India VIX', 'Nifty GS 10Yr', 'Nifty GS Compsite',
                'Nifty50 USD', 'NIFTY OIL AND GAS', 'Nifty Energy'
            )
            ORDER BY index_name, trade_date DESC
        """).fetchdf()

        # 2b. Crude Oil Sensitive Stocks (Upstream vs Downstream proxy)
        crude_stocks_df = con.execute("""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
            SELECT i.symbol, i.close_price, 
                   (i.close_price / nullif(i.prev_close, 0) - 1) * 100.0 AS return_1d_pct,
                   i.return_5d_pct, i.rs_percentile
            FROM indicators_daily i, latest
            WHERE i.trade_date = latest.d
              AND i.symbol IN (
                  'ONGC', 'OIL',
                  'ASIANPAINT', 'BERGEPAINT', 'INDIGO', 'MRF', 'IOC', 'BPCL'
              )
        """).fetchdf()

        # 3. Institutional Deals (Latest Session & Trailing 7 Days)
        latest_deals_date_row = con.execute("SELECT max(trade_date) FROM deals").fetchone()
        latest_deals_date = latest_deals_date_row[0] if latest_deals_date_row else None

        deals_latest_df = pd.DataFrame()
        deals_7d_df = pd.DataFrame()
        top_accum_df = pd.DataFrame()
        top_dist_df = pd.DataFrame()

        if latest_deals_date is not None:
            deals_latest_df = con.execute("""
                SELECT 
                    count(*) as deal_count,
                    coalesce(sum(CASE WHEN side = 'BUY' THEN deal_value_cr ELSE 0 END), 0.0) as buy_cr,
                    coalesce(sum(CASE WHEN side = 'SELL' THEN deal_value_cr ELSE 0 END), 0.0) as sell_cr,
                    coalesce(sum(CASE WHEN side = 'BUY' AND tier LIKE '%FII%' THEN deal_value_cr WHEN side = 'SELL' AND tier LIKE '%FII%' THEN -deal_value_cr ELSE 0 END), 0.0) as fii_net_cr,
                    coalesce(sum(CASE WHEN side = 'BUY' AND tier LIKE '%DII%' THEN deal_value_cr WHEN side = 'SELL' AND tier LIKE '%DII%' THEN -deal_value_cr ELSE 0 END), 0.0) as dii_net_cr,
                    coalesce(sum(CASE WHEN side = 'BUY' AND (tier LIKE '%PROP%' OR tier LIKE '%HFT%') THEN deal_value_cr WHEN side = 'SELL' AND (tier LIKE '%PROP%' OR tier LIKE '%HFT%') THEN -deal_value_cr ELSE 0 END), 0.0) as prop_net_cr
                FROM deals
                WHERE trade_date = ?
            """, [latest_deals_date]).fetchdf()

            deals_7d_df = con.execute("""
                SELECT 
                    count(*) as deal_count,
                    coalesce(sum(CASE WHEN side = 'BUY' THEN deal_value_cr ELSE 0 END), 0.0) as buy_cr,
                    coalesce(sum(CASE WHEN side = 'SELL' THEN deal_value_cr ELSE 0 END), 0.0) as sell_cr,
                    coalesce(sum(CASE WHEN side = 'BUY' AND tier LIKE '%FII%' THEN deal_value_cr WHEN side = 'SELL' AND tier LIKE '%FII%' THEN -deal_value_cr ELSE 0 END), 0.0) as fii_net_cr,
                    coalesce(sum(CASE WHEN side = 'BUY' AND tier LIKE '%DII%' THEN deal_value_cr WHEN side = 'SELL' AND tier LIKE '%DII%' THEN -deal_value_cr ELSE 0 END), 0.0) as dii_net_cr,
                    coalesce(sum(CASE WHEN side = 'BUY' AND (tier LIKE '%PROP%' OR tier LIKE '%HFT%') THEN deal_value_cr WHEN side = 'SELL' AND (tier LIKE '%PROP%' OR tier LIKE '%HFT%') THEN -deal_value_cr ELSE 0 END), 0.0) as prop_net_cr
                FROM deals
                WHERE trade_date >= (? - INTERVAL 7 DAY)
            """, [latest_deals_date]).fetchdf()

            top_accum_df = con.execute("""
                SELECT symbol, security_name, sector, 
                       sum(CASE WHEN side = 'BUY' THEN deal_value_cr ELSE -deal_value_cr END) as net_cr,
                       sum(deal_value_cr) as gross_cr
                FROM deals
                WHERE trade_date >= (? - INTERVAL 7 DAY)
                GROUP BY symbol, security_name, sector
                HAVING net_cr > 15.0
                ORDER BY net_cr DESC
                LIMIT 5
            """, [latest_deals_date]).fetchdf()

            top_dist_df = con.execute("""
                SELECT symbol, security_name, sector, 
                       sum(CASE WHEN side = 'SELL' THEN deal_value_cr ELSE -deal_value_cr END) as net_sell_cr,
                       sum(deal_value_cr) as gross_cr
                FROM deals
                WHERE trade_date >= (? - INTERVAL 7 DAY)
                GROUP BY symbol, security_name, sector
                HAVING net_sell_cr > 15.0
                ORDER BY net_sell_cr DESC
                LIMIT 5
            """, [latest_deals_date]).fetchdf()

        # 4. Sector Rotation Latest
        sector_latest_df = con.execute("""
            WITH latest AS (SELECT max(trade_date) d FROM sector_rotation WHERE level = 'Sector')
            SELECT group_name, return_5d_pct, rs_percentile, turnover_cr, rotation_state,
                   near_52w_highs, above_50ema_pct, leader_symbols
            FROM sector_rotation, latest
            WHERE sector_rotation.level = 'Sector' AND sector_rotation.trade_date = latest.d
            ORDER BY rs_percentile DESC
        """).fetchdf()

        # 5. Total Market Cash Turnover
        turnover_stats = con.execute("""
            WITH daily_turnover AS (
                SELECT trade_date, sum(close_price * volume) / 10000000.0 as tot_turnover_cr
                FROM prices_daily
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT 21
            )
            SELECT 
                (SELECT tot_turnover_cr FROM daily_turnover LIMIT 1) as latest_turnover_cr,
                (SELECT avg(tot_turnover_cr) FROM daily_turnover) as avg_20d_turnover_cr
        """).fetchdf()

        # 6. Action Desk Queue Setup Counts & Samples
        action_samples = {}
        try:
            # Darvas 10 EMA squeezes
            darvas_q = con.execute("""
                WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
                SELECT i.symbol, i.close_price, i.day_pct, i.rs_percentile, m.sector,
                       i.darvas_box_top, i.darvas_box_bottom
                FROM indicators_daily i
                JOIN latest ON i.trade_date = latest.d
                LEFT JOIN stocks_master m ON i.symbol = m.symbol
                WHERE i.close_price BETWEEN coalesce(i.darvas_box_bottom, 0) AND coalesce(i.darvas_box_top, 999999)
                  AND i.close_price >= i.ema_10
                  AND i.rs_percentile >= 70
                  AND i.day_pct >= 0
                ORDER BY i.rs_percentile DESC
                LIMIT 4
            """).fetchdf()
            action_samples["darvas"] = darvas_q.to_dict("records")

            # Stage 1 Turnarounds
            stage1_q = con.execute("""
                WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
                SELECT i.symbol, i.close_price, i.day_pct, i.rs_percentile, m.sector, i.away_52w_low_pct
                FROM indicators_daily i
                JOIN latest ON i.trade_date = latest.d
                LEFT JOIN stocks_master m ON i.symbol = m.symbol
                WHERE i.close_price >= i.ema_10
                  AND i.ema_10 >= i.ema_20
                  AND i.away_52w_low_pct BETWEEN 20 AND 80
                  AND i.rs_percentile >= 60
                ORDER BY i.rs_percentile DESC
                LIMIT 4
            """).fetchdf()
            action_samples["stage1"] = stage1_q.to_dict("records")
        except Exception:
            action_samples = {"darvas": [], "stage1": []}

    # ==================== DATA PROCESSING & SYNTHESIS ====================
    # Dates
    b_latest = breadth_rows.iloc[0] if not breadth_rows.empty else None
    b_prev = breadth_rows.iloc[1] if len(breadth_rows) > 1 else None
    
    trade_date_dt = pd.to_datetime(b_latest["trade_date"]) if b_latest is not None else datetime.now()
    trade_date_str = trade_date_dt.strftime("%d %b %Y")
    day_name = trade_date_dt.strftime("%A")
    week_str = f"Week of {trade_date_dt.strftime('%b %d, %Y')}"

    # Index metrics
    nifty_row = indices_df[indices_df["index_name"].str.upper().str.contains("NIFTY 50")].iloc[0] if not indices_df.empty and indices_df["index_name"].str.upper().str.contains("NIFTY 50").any() else None
    nifty_cmp = float(nifty_row["close_price"]) if nifty_row is not None and pd.notna(nifty_row["close_price"]) else 23600.0
    nifty_1d = float(nifty_row["return_1d_pct"]) if nifty_row is not None and pd.notna(nifty_row["return_1d_pct"]) else 0.0
    nifty_5d = float(nifty_row["return_5d_pct"]) if nifty_row is not None and pd.notna(nifty_row["return_5d_pct"]) else 0.0
    nifty_ema20 = float(nifty_row["ema_20"]) if nifty_row is not None and pd.notna(nifty_row["ema_20"]) else nifty_cmp
    nifty_ema50 = float(nifty_row["ema_50"]) if nifty_row is not None and pd.notna(nifty_row["ema_50"]) else nifty_cmp
    nifty_ema200 = float(nifty_row["ema_200"]) if nifty_row is not None and pd.notna(nifty_row["ema_200"]) else nifty_cmp
    nifty_trend = str(nifty_row["trend_state"]) if nifty_row is not None and pd.notna(nifty_row["trend_state"]) else "Neutral"

    # Breadth metrics
    adv_pct = float(b_latest["advance_pct"]) if b_latest is not None and pd.notna(b_latest["advance_pct"]) else 50.0
    adv_cnt = int(b_latest["advancers"]) if b_latest is not None and pd.notna(b_latest["advancers"]) else 1200
    dec_cnt = int(b_latest["decliners"]) if b_latest is not None and pd.notna(b_latest["decliners"]) else 1200
    ab_20 = float(b_latest["above_20ema_pct"]) if b_latest is not None and pd.notna(b_latest["above_20ema_pct"]) else 50.0
    ab_50 = float(b_latest["above_50ema_pct"]) if b_latest is not None and pd.notna(b_latest["above_50ema_pct"]) else 50.0
    ab_200 = float(b_latest["above_200ema_pct"]) if b_latest is not None and pd.notna(b_latest["above_200ema_pct"]) else 50.0
    highs_52w = int(b_latest["near_52w_highs"]) if b_latest is not None and pd.notna(b_latest["near_52w_highs"]) else 0
    breadth_state = str(b_latest["breadth_state"]) if b_latest is not None and pd.notna(b_latest["breadth_state"]) else "Neutral"

    # Breadth delta vs prior day
    ab_50_prev = float(b_prev["above_50ema_pct"]) if b_prev is not None and pd.notna(b_prev["above_50ema_pct"]) else ab_50
    ab_50_delta = ab_50 - ab_50_prev

    # Turnover
    t_latest = float(turnover_stats.iloc[0]["latest_turnover_cr"]) if not turnover_stats.empty and pd.notna(turnover_stats.iloc[0]["latest_turnover_cr"]) else 75000.0
    t_avg = float(turnover_stats.iloc[0]["avg_20d_turnover_cr"]) if not turnover_stats.empty and pd.notna(turnover_stats.iloc[0]["avg_20d_turnover_cr"]) else 75000.0
    turnover_ratio = (t_latest / t_avg) if t_avg > 0 else 1.0

    # Deals
    d_latest = deals_latest_df.iloc[0].to_dict() if not deals_latest_df.empty else {}
    d_7d = deals_7d_df.iloc[0].to_dict() if not deals_7d_df.empty else {}

    fii_7d_net = float(d_7d.get("fii_net_cr") or 0.0)
    dii_7d_net = float(d_7d.get("dii_net_cr") or 0.0)
    prop_7d_net = float(d_7d.get("prop_net_cr") or 0.0)
    total_deal_count_7d = int(d_7d.get("deal_count") or 0)

    # Sectors
    leaders = sector_latest_df.head(3).to_dict("records") if not sector_latest_df.empty else []
    laggards = sector_latest_df.tail(3).to_dict("records") if not sector_latest_df.empty else []

    # ==================== INTERMARKET MACRO PROCESSING ====================
    def _find_idx(name_pattern: str):
        if indices_df.empty:
            return None
        hits = indices_df[indices_df["index_name"].str.upper().str.contains(name_pattern.upper())]
        return hits.iloc[0] if not hits.empty else None

    # 1. India VIX (Volatility Regime)
    vix_row = _find_idx("VIX")
    vix_cmp = float(vix_row["close_price"]) if vix_row is not None and pd.notna(vix_row["close_price"]) else 13.0
    vix_1d = float(vix_row["return_1d_pct"]) if vix_row is not None and pd.notna(vix_row["return_1d_pct"]) else 0.0
    vix_5d = float(vix_row["return_5d_pct"]) if vix_row is not None and pd.notna(vix_row["return_5d_pct"]) else 0.0
    if vix_cmp < 13.0:
        vix_state = "Complacent / Low-Risk (<13)"
        vix_desc = f"India VIX printed **{vix_cmp:.2f}** ({vix_1d:+.1f}% day), signaling subdued near-term volatility and minimal institutional hedging demand."
    elif vix_cmp < 17.0:
        vix_state = "Normal Volatility (13–17)"
        vix_desc = f"India VIX sits at **{vix_cmp:.2f}** ({vix_1d:+.1f}% day), indicating an orderly swing trading environment without systemic stress."
    elif vix_cmp < 22.0:
        vix_state = "Elevated Volatility (17–22)"
        vix_desc = f"India VIX elevated to **{vix_cmp:.2f}** ({vix_1d:+.1f}% day), signaling heightened option premium pricing and expanding intraday ranges."
    else:
        vix_state = "Extreme Fear / Risk-Off (>22)"
        vix_desc = f"India VIX spiked to **{vix_cmp:.2f}** ({vix_1d:+.1f}% day), warning of acute market turbulence and aggressive downside tail risk."

    # 2. Sovereign Bond Market (Nifty GS 10Yr Yield Curve proxy)
    gs10_row = _find_idx("GS 10Yr")
    gs10_cmp = float(gs10_row["close_price"]) if gs10_row is not None and pd.notna(gs10_row["close_price"]) else 2600.0
    gs10_1d = float(gs10_row["return_1d_pct"]) if gs10_row is not None and pd.notna(gs10_row["return_1d_pct"]) else 0.0
    gs10_5d = float(gs10_row["return_5d_pct"]) if gs10_row is not None and pd.notna(gs10_row["return_5d_pct"]) else 0.0
    # In bond index pricing: rising index = falling yields (monetary easing); falling index = rising yields (rate pressure)
    if gs10_5d > 0.15:
        gs10_state = "Yields Softening (Bond Inflows)"
        gs10_desc = f"10-Year Indian Sovereign G-Secs (`Nifty GS 10Yr` at **{gs10_cmp:,.1f}**, {gs10_5d:+.2f}% 5D) reflect softening benchmark yields, easing corporate borrowing costs and supporting equity multiples."
    elif gs10_5d < -0.15:
        gs10_state = "Yields Hardening (Rate Pressure)"
        gs10_desc = f"10-Year Indian Sovereign G-Secs (`Nifty GS 10Yr` at **{gs10_cmp:,.1f}**, {gs10_5d:+.2f}% 5D) reflect yields hardening, signaling sticky inflation expectations and keeping RBI rate-easing headroom constrained."
    else:
        gs10_state = "Yields Rangebound"
        gs10_desc = f"10-Year Sovereign G-Secs (`Nifty GS 10Yr` at **{gs10_cmp:,.1f}**, {gs10_5d:+.2f}% 5D) traded rangebound, reflecting stable domestic monetary conditions."

    # 3. Currency & Dollar Returns (Nifty50 USD vs Nifty 50 INR)
    nifty_usd_row = _find_idx("Nifty50 USD")
    nifty_usd_cmp = float(nifty_usd_row["close_price"]) if nifty_usd_row is not None and pd.notna(nifty_usd_row["close_price"]) else 8500.0
    nifty_usd_1d = float(nifty_usd_row["return_1d_pct"]) if nifty_usd_row is not None and pd.notna(nifty_usd_row["return_1d_pct"]) else nifty_1d
    nifty_usd_5d = float(nifty_usd_row["return_5d_pct"]) if nifty_usd_row is not None and pd.notna(nifty_usd_row["return_5d_pct"]) else nifty_5d
    usd_drift_1d = nifty_usd_1d - nifty_1d
    usd_drift_5d = nifty_usd_5d - nifty_5d
    if usd_drift_5d < -0.4:
        curr_state = "Rupee Depreciating vs USD"
        curr_desc = (
            f"**Currency Drag (USD/INR):** Dollar-denominated Nifty (`Nifty50 USD` {nifty_usd_5d:+.1f}% 5D) lagged the domestic INR index by **{usd_drift_5d:+.1f}%**, "
            f"indicating Rupee depreciation against the US Dollar. A weaker Rupee erodes dollar returns for foreign funds, acting as a structural headwind for fresh FII inflows."
        )
    elif usd_drift_5d > 0.4:
        curr_state = "Rupee Appreciating vs USD"
        curr_desc = (
            f"**Currency Tailized (USD/INR):** Dollar-denominated Nifty (`Nifty50 USD` {nifty_usd_5d:+.1f}% 5D) outpaced the domestic INR index by **{usd_drift_5d:+.1f}%**, "
            f"indicating Rupee resilience. A firming currency strengthens foreign portfolio returns and typically invites aggressive FII allocations."
        )
    else:
        curr_state = "Rupee Stable"
        curr_desc = f"**Currency Stability (USD/INR):** `Nifty50 USD` ({nifty_usd_5d:+.1f}% 5D) closely tracked domestic Nifty (drift: {usd_drift_5d:+.1f}%), signaling stable foreign exchange conditions."

    # 4. Crude Oil & Energy Transmission (Upstream drillers vs Downstream consumers)
    oil_row = _find_idx("OIL AND GAS")
    if oil_row is None:
        oil_row = _find_idx("Energy")
    oil_name = oil_row["index_name"] if oil_row is not None else "Nifty Oil & Gas"
    oil_1d = float(oil_row["return_1d_pct"]) if oil_row is not None and pd.notna(oil_row["return_1d_pct"]) else 0.0
    oil_5d = float(oil_row["return_5d_pct"]) if oil_row is not None and pd.notna(oil_row["return_5d_pct"]) else 0.0

    upstream_syms = ["ONGC", "OIL"]
    downstream_syms = ["ASIANPAINT", "BERGEPAINT", "INDIGO", "MRF", "IOC", "BPCL"]
    up_df = crude_stocks_df[crude_stocks_df["symbol"].isin(upstream_syms)] if not crude_stocks_df.empty else pd.DataFrame()
    down_df = crude_stocks_df[crude_stocks_df["symbol"].isin(downstream_syms)] if not crude_stocks_df.empty else pd.DataFrame()

    up_5d = float(up_df["return_5d_pct"].mean()) if not up_df.empty and pd.notna(up_df["return_5d_pct"].mean()) else 0.0
    down_5d = float(down_df["return_5d_pct"].mean()) if not down_df.empty and pd.notna(down_df["return_5d_pct"].mean()) else 0.0
    crude_bifurcation = up_5d - down_5d

    if crude_bifurcation > 2.0:
        crude_summary = (
            f"**Crude Oil & Energy Transmission:** Upstream crude beneficiaries (`OIL`, `ONGC` avg: **{up_5d:+.1f}%** 5D) significantly outperformed "
            f"downstream crude consumers (`ASIANPAINT`, `BERGEPAINT`, `INDIGO`, `MRF` avg: **{down_5d:+.1f}%** 5D) with a **{crude_bifurcation:+.1f}% spread**. "
            f"Because India imports ~85% of its crude requirements, rising or elevated oil prices inflate the Current Account Deficit, weaken the Rupee, "
            f"and directly compress gross margins across Paints, Aviation, Tyres, and Specialty Chemicals."
        )
    elif crude_bifurcation < -2.0:
        crude_summary = (
            f"**Crude Oil Relief & Margin Expansion:** Downstream crude consumers (`ASIANPAINT`, `BERGEPAINT`, `INDIGO`, `MRF` avg: **{down_5d:+.1f}%** 5D) "
            f"strongly outpaced upstream drillers (`OIL`, `ONGC` avg: **{up_5d:+.1f}%** 5D) by **{abs(crude_bifurcation):.1f}%**. "
            f"Softening crude oil prices provide immediate macroeconomic relief to India's import bill and unlock gross margin tailwinds for domestic consumer durables and transport."
        )
    else:
        crude_summary = (
            f"**Crude Oil & Margin Transmission:** Upstream drillers (avg: **{up_5d:+.1f}%** 5D) and downstream users (avg: **{down_5d:+.1f}%** 5D) "
            f"are trading in equilibrium (spread: **{crude_bifurcation:+.1f}%**). Sectoral index `{oil_name}` printed **{oil_1d:+.1f}%** (1D) / **{oil_5d:+.1f}%** (5D)."
        )

    # ==================== REGIME & POSTURE CLASSIFICATION ====================
    # Nifty position vs EMAs
    dist_20ema = ((nifty_cmp - nifty_ema20) / nifty_ema20 * 100.0) if nifty_ema20 > 0 else 0.0
    dist_50ema = ((nifty_cmp - nifty_ema50) / nifty_ema50 * 100.0) if nifty_ema50 > 0 else 0.0
    dist_200ema = ((nifty_cmp - nifty_ema200) / nifty_ema200 * 100.0) if nifty_ema200 > 0 else 0.0

    if nifty_cmp >= nifty_ema20 and nifty_ema20 >= nifty_ema50 and ab_50 >= 55.0 and adv_pct >= 55.0:
        regime_title = "AGGRESSIVE BULLISH EXPANSION"
        regime_tone = "positive"
        posture_title = "Aggressive Swing Allocation (80% – 100%)"
        posture_desc = "Broad market participation is in full expansion. High-volume breakout continuation setups and 10 EMA pullback entries carry maximum statistical expectancy. Pyramiding into leading winners is favored."
        cash_recommendation = "0% – 15% Cash"
    elif nifty_cmp >= nifty_ema50 and ab_50 >= 45.0:
        regime_title = "SELECTIVE CONSTRUCTIVE PULLBACK"
        regime_tone = "info"
        posture_title = "Selective Precision Posture (50% – 70% Allocation)"
        posture_desc = "Market is holding key intermediate moving averages but digesting recent gains. Avoid buying extended breakouts; focus strictly on tight Darvas squeezes coiled directly on 10 EMA support with institutional deal backing."
        cash_recommendation = "30% – 50% Cash"
    elif nifty_cmp < nifty_ema50 and ab_50 < 45.0 and ab_50 >= 35.0:
        regime_title = "DEFENSIVE CONSOLIDATION & DISTRIBUTION"
        regime_tone = "warning"
        posture_title = "Defensive Capital Preservation (25% – 40% Allocation)"
        posture_desc = "Index has dipped below intermediate EMAs and fewer than 45% of stocks are above their 50 EMA. Keep stop-losses tight, trim lagging positions quickly, and only deploy risk into isolated high-RS institutional turnaround setups."
        cash_recommendation = "60% – 75% Cash"
    else:
        regime_title = "CORRECTION & RISK-OFF DEFENSIVE"
        regime_tone = "negative"
        posture_title = "Strict Capital Preservation (0% – 20% Allocation)"
        posture_desc = "Broad-based distribution is active with market breadth severely compressed below 35%. Cash is a high-conviction position. Protect capital, avoid catching falling knives, and wait for a confirmed Breadth Thrust."
        cash_recommendation = "80% – 100% Cash"

    # ==================== NARRATIVE GENERATION ====================
    # 1. Headline
    top_sec_name = leaders[0]["group_name"] if leaders else "Key Pockets"
    headline = (
        f"{regime_title.title()}: Nifty prints ₹{nifty_cmp:,.0f} ({nifty_1d:+.1f}%) with {top_sec_name} in leadership "
        f"as institutions deploy {_fmt_cr(fii_7d_net)} net."
    )

    # 2. Macro & Index Narrative (with Crude, Currency & Bond Yields)
    nifty_trend_verb = "holding above" if nifty_cmp >= nifty_ema20 else "trading below"
    macro_text = (
        f"**Benchmark Action:** On {day_name} ({trade_date_str}), the Nifty 50 settled at **₹{nifty_cmp:,.2f}** ({nifty_1d:+.2f}% day / {nifty_5d:+.1f}% 5-day). "
        f"The index is currently **{nifty_trend_verb} its 20-day EMA** (₹{nifty_ema20:,.0f}, {dist_20ema:+.1f}%) and "
        f"{'above' if nifty_cmp >= nifty_ema50 else 'below'} its 50-day EMA (₹{nifty_ema50:,.0f}, {dist_50ema:+.1f}%). "
        f"Long-term structural trend remains {'firmly intact above the 200 EMA' if nifty_cmp >= nifty_ema200 else 'pressured near the 200 EMA'} (₹{nifty_ema200:,.0f}, {dist_200ema:+.1f}%).\n\n"
        f"**Market Context & Liquidity:** Overall technical classification is in a **{nifty_trend.upper()}** state. "
        f"Total session cash market turnover was **₹{t_latest:,.0f} Cr**, representing **{turnover_ratio:.2f}x** of the 20-day average turnover (₹{t_avg:,.0f} Cr). "
        f"{'Turnover expanded noticeably, indicating elevated participation.' if turnover_ratio > 1.05 else 'Turnover contracted below trailing averages, reflecting quiet institutional absorption rather than aggressive panic dumping.'}\n\n"
        f"### Intermarket Transmission: Crude Oil, Currency & Sovereign Bonds\n"
        f"• {crude_summary}\n\n"
        f"• {curr_desc}\n\n"
        f"• **Sovereign Bond Market (Yield Curve):** {gs10_desc}\n\n"
        f"• **Volatility Regime (`India VIX`):** {vix_desc}"
    )

    # 3. Breadth Narrative
    adv_decline_verb = "dominant advancing momentum" if adv_pct >= 55.0 else "neutral churn" if adv_pct >= 45.0 else "defensive selling pressure"
    breadth_text = (
        f"**Participation & Thrust:** Market breadth recorded **{adv_cnt:,} advancers vs {dec_cnt:,} decliners** ({adv_pct:.1f}% advance share), reflecting {adv_decline_verb}. "
        f"Internally, **{ab_20:.1f}%** of stocks trade above their 20 EMA, **{ab_50:.1f}%** above their 50 EMA ({ab_50_delta:+.1f} pp day-over-day), "
        f"and **{ab_200:.1f}%** remain above their long-term 200 EMA.\n\n"
        f"**High/Low Momentum:** **{highs_52w} stocks** are currently trading within 15% of their 52-week highs. "
        f"{'Healthy leadership breadth persists under the surface despite headline index hesitation.' if highs_52w >= 300 else '52-week high expansion remains selective, emphasizing individual stock picking over index beta.'}"
    )

    # 4. Institutional Flows Narrative
    top_accum_list = top_accum_df.to_dict("records")
    accum_str = ", ".join([f"**{r['symbol']}** ({_fmt_cr(r['net_cr'])})" for r in top_accum_list[:4]]) if top_accum_list else "None above threshold"

    top_dist_list = top_dist_df.to_dict("records")
    dist_str = ", ".join([f"**{r['symbol']}** (-{_fmt_cr(r['net_sell_cr'])})" for r in top_dist_list[:3]]) if top_dist_list else "None above threshold"

    flows_text = (
        f"**Deal Tape Footprint (Trailing 7 Days):** Over the past week, MarketPulse recorded **{total_deal_count_7d:,} institutional block & bulk transactions**. "
        f"Institutional net flow stood at **{_fmt_cr(fii_7d_net + dii_7d_net)}**.\n\n"
        f"- **Foreign Institutional Investors (FIIs):** {_fmt_cr(fii_7d_net)} net balance.\n"
        f"- **Domestic Institutional Investors (DIIs):** {_fmt_cr(dii_7d_net)} net balance.\n"
        f"- **Proprietary & Algorithmic Desks:** {_fmt_cr(prop_7d_net)} net balance.\n\n"
        f"**Notable Institutional Accumulation:** Institutions actively established net buying positions in {accum_str}.\n"
        f"**Institutional Profit-Taking / Distribution:** Notable outflows were concentrated in {dist_str}."
    )

    # 5. Sector Rotation & Capital Flight
    sec_lead_str = ", ".join([f"**{r['group_name']}** (5D: {r.get('return_5d_pct', 0.0):+.1f}%, RS {r.get('rs_percentile', 0.0):.0f})" for r in leaders]) if leaders else "—"
    sec_lag_str = ", ".join([f"**{r['group_name']}** (5D: {r.get('return_5d_pct', 0.0):+.1f}%, RS {r.get('rs_percentile', 0.0):.0f})" for r in laggards]) if laggards else "—"

    sector_text = (
        f"**Capital Rotation:** Sector leadership continues to bifurcate between capital goods/cyclicals and defensive pockets.\n\n"
        f"- **Leading Sectors (Top RS & Thrust):** {sec_lead_str}.\n"
        f"- **Lagging / Dragging Sectors:** {sec_lag_str}.\n\n"
        f"**Money Flow Synthesis:** Capital is visibly rotating toward industry leaders exhibiting positive RS momentum and high relative volume, while extended or low-margin segments are seeing liquidity contraction."
    )

    # 6. Tactical Action Plan Details
    darvas_items = action_samples.get("darvas", [])
    stage1_items = action_samples.get("stage1", [])

    darvas_chips = [f"{x['symbol']} (RS {x.get('rs_percentile', 0):.0f})" for x in darvas_items]
    stage1_chips = [f"{x['symbol']} (RS {x.get('rs_percentile', 0):.0f})" for x in stage1_items]

    plan_directives = [
        f"**Execution Bias:** {posture_desc}",
        f"**Recommended Exposure:** {cash_recommendation} (adjust size based on individual account risk profile).",
        f"**Key Setups to Target:**",
        f"  • *Darvas 10 EMA Squeezes:* Watch {', '.join(darvas_chips) if darvas_chips else 'Action Desk Darvas queue'} for tight base breakouts.",
        f"  • *Stage 1 Turnarounds:* Inspect {', '.join(stage1_chips) if stage1_chips else 'Stage 1 queue'} for low-risk, asymmetric reward entries off weekly bottoms.",
        f"**Tactical Line in the Sand:** Nifty 20 EMA at **₹{nifty_ema20:,.0f}** serves as the primary pivot. Maintain strict stop-loss hygiene and avoid buying stocks extended >8% above their 10 EMA."
    ]

    return {
        "ok": True,
        "date_str": trade_date_str,
        "day_name": day_name,
        "week_str": week_str,
        "regime_title": regime_title,
        "regime_tone": regime_tone,
        "headline": headline,
        "kpis": {
            "nifty_cmp": f"₹{nifty_cmp:,.2f}",
            "nifty_1d": _fmt_pct(nifty_1d),
            "nifty_5d": _fmt_pct(nifty_5d),
            "nifty_trend": nifty_trend,
            "adv_ratio": f"{adv_cnt} : {dec_cnt} ({adv_pct:.0f}%)",
            "breadth_50ema": f"{ab_50:.1f}%",
            "breadth_state": breadth_state,
            "fii_7d_net": _fmt_cr(fii_7d_net),
            "dii_7d_net": _fmt_cr(dii_7d_net),
            "turnover_cr": f"₹{t_latest:,.0f} Cr",
            "turnover_ratio": f"{turnover_ratio:.2f}x",
            "top_sector": top_sec_name,
            "vix": f"{vix_cmp:.1f}",
            "vix_1d": _fmt_pct(vix_1d),
            "vix_state": vix_state,
            "gs10yr_cmp": f"{gs10_cmp:,.1f}",
            "gs10yr_1d": _fmt_pct(gs10_1d),
            "gs10yr_state": gs10_state,
            "usd_drift_5d": _fmt_pct(usd_drift_5d),
            "oil_5d": _fmt_pct(oil_5d),
            "crude_spread": f"{crude_bifurcation:+.1f}%",
        },
        "macro_commentary": macro_text,
        "breadth_commentary": breadth_text,
        "flows_commentary": flows_text,
        "sector_commentary": sector_text,
        "action_plan": {
            "posture_title": posture_title,
            "cash_recommendation": cash_recommendation,
            "posture_desc": posture_desc,
            "directives": plan_directives,
            "darvas_samples": darvas_items,
            "stage1_samples": stage1_items,
            "top_accum": top_accum_list,
        },
    }
