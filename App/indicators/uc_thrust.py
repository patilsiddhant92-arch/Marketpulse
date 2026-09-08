"""
UC Thrust Radar: Empirical Pre-Circuit Detection Engine.

Decodes the statistical precursors of 10% and 20% Upper Circuit locks based on
an empirical study of 1,197 historical circuit events in DuckDB.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import duckdb
import numpy as np
import pandas as pd


def calculate_uc_thrust_candidates(
    db_path: Path | str,
    trade_date: str | None = None,
    limit: int = 40,
) -> pd.DataFrame:
    """
    Query and score all stocks meeting the empirical UC Thrust Radar criteria.
    Returns a sorted DataFrame of highest-probability circuit precursors.
    """
    db_file = Path(db_path)
    if not db_file.exists():
        return pd.DataFrame()

    with duckdb.connect(str(db_file), read_only=True) as con:
        if trade_date is None:
            max_d = con.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()
            if not max_d or not max_d[0]:
                return pd.DataFrame()
            target_date = max_d[0]
        else:
            target_date = trade_date

        deals_df = con.execute(
            """
            SELECT 
                symbol, 
                count(*) as n_deals, 
                sum(CASE WHEN is_institutional THEN 1 ELSE 0 END) as n_inst,
                round(sum(deal_value_cr), 1) as deal_cr
            FROM deals
            WHERE trade_date >= ? - INTERVAL 25 DAY
              AND coalesce(is_prop, false) = false
            GROUP BY symbol
            """,
            [target_date],
        ).fetchdf()

        rot_df = con.execute(
            """
            SELECT 
                group_name as sector, 
                rotation_state, 
                rotation_rank, 
                rank_change_5d
            FROM sector_rotation
            WHERE level = 'Sector'
              AND trade_date = (
                  SELECT max(trade_date) 
                  FROM sector_rotation 
                  WHERE trade_date <= ?
              )
            """,
            [target_date],
        ).fetchdf()

        raw_df = con.execute(
            """
            SELECT 
                i.symbol, 
                sm.security_name, 
                sm.sector, 
                sm.industry, 
                sm.market_cap_cr, 
                coalesce(sm.band, 20.0) as band,
                i.close_price as cmp, 
                round((i.close_price / nullif(i.prev_close, 0) - 1.0) * 100.0, 2) as day_pct,
                round(i.rvol, 2) as rvol, 
                round(i.rsi_14, 1) as rsi_14, 
                round(i.rs_percentile, 1) as rs_percentile, 
                round(i.away_10ema_pct, 2) as away_10ema_pct, 
                round(i.away_20ema_pct, 2) as away_20ema_pct, 
                round(i.away_52w_high_pct, 2) as away_52w_high_pct,
                round(i.delivery_pct, 1) as delivery_pct, 
                i.delivery_spike, 
                i.near_52w_high, 
                i.ema_stack_bullish,
                round(coalesce(i.avg_traded_value_cr_20d, i.turnover_cr), 1) as to_cr
            FROM indicators_daily i
            JOIN stocks_master sm USING (symbol)
            WHERE i.trade_date = ?
              AND coalesce(sm.market_cap_cr, 0) >= 1000.0
              AND coalesce(sm.band, 20.0) in (10.0, 20.0)
              AND coalesce(i.avg_traded_value_cr_20d, i.turnover_cr) >= 3.0
              AND (i.close_price / nullif(i.prev_close, 0) - 1.0) * 100.0 < 7.0
              AND i.away_10ema_pct BETWEEN -0.5 AND 6.0
              AND i.rvol BETWEEN 0.85 AND 4.0
              AND i.rsi_14 BETWEEN 45.0 AND 75.0
              AND i.symbol NOT LIKE '%-RE' AND i.symbol NOT LIKE '%_RE'
            """,
            [target_date],
        ).fetchdf()

    if raw_df.empty:
        return pd.DataFrame()

    if not deals_df.empty:
        df = raw_df.merge(deals_df, on="symbol", how="left")
    else:
        df = raw_df.copy()
        df["n_deals"] = 0
        df["n_inst"] = 0
        df["deal_cr"] = 0.0

    if not rot_df.empty:
        df = df.merge(rot_df, on="sector", how="left")
    else:
        df["rotation_state"] = "Neutral"
        df["rotation_rank"] = 99
        df["rank_change_5d"] = 0

    df["n_deals"] = df["n_deals"].fillna(0).astype(int)
    df["n_inst"] = df["n_inst"].fillna(0).astype(int)
    df["deal_cr"] = df["deal_cr"].fillna(0.0)
    df["rotation_state"] = df["rotation_state"].fillna("Neutral")
    df["rank_change_5d"] = df["rank_change_5d"].fillna(0)

    score = pd.Series(0.0, index=df.index)
    score += (df["delivery_spike"] == True).astype(float) * 3.0
    score += (df["near_52w_high"] == True).astype(float) * 2.0
    score += (df["rotation_state"].isin(["Leading", "Improving"])).astype(float) * 1.5
    score += (df["n_inst"] > 0).astype(float) * 1.5
    score += (df["ema_stack_bullish"] == True).astype(float) * 1.0
    score += (df["rs_percentile"].fillna(0) >= 60.0).astype(float) * 1.0
    score += (df["rank_change_5d"] > 0).astype(float) * 0.5
    score += (df["band"] == 10.0).astype(float) * 0.4
    df["uc_score"] = score.round(1)

    deal_flow_list = []
    for _, r in df.iterrows():
        n_inst = int(r["n_inst"])
        cr = float(r["deal_cr"])
        if n_inst > 0 and cr >= 5.0:
            deal_flow_list.append(f"🏛️ +₹{cr:,.0f}Cr ({n_inst} Inst)")
        elif n_inst > 0:
            deal_flow_list.append(f"🏛️ {n_inst} Inst Deals")
        elif int(r["n_deals"]) > 0:
            deal_flow_list.append(f"🏛️ {int(r['n_deals'])} Deals")
        else:
            deal_flow_list.append("—")
    df["deal_flow"] = deal_flow_list

    why_now_list = []
    for _, r in df.iterrows():
        parts = [f"⚡ UC Score {r['uc_score']:.1f}"]
        if r["delivery_spike"]:
            parts.append("Delivery Spike")
        if r["rotation_state"] in ("Leading", "Improving"):
            parts.append(f"{r['rotation_state']} {r['sector']}")
        if r["near_52w_high"]:
            parts.append("Near 52W High")
        if r["n_inst"] > 0:
            parts.append("Inst Deals")
        parts.append(f"Coiled {r['away_10ema_pct']:+.1f}% at 10 EMA (RVOL {r['rvol']:.1f}x)")
        why_now_list.append(" · ".join(parts))
    df["why_now"] = why_now_list

    df["trigger_price"] = (df["cmp"] * 1.005).round(2)
    df["stop_loss"] = (df["cmp"] * 0.965).round(2)
    df["risk_pct"] = ((df["cmp"] / df["stop_loss"] - 1.0) * 100.0).round(2)
    df["setup_type"] = "UC Thrust Radar"

    df = df.sort_values(["uc_score", "rs_percentile", "rvol"], ascending=[False, False, False])
    return df.head(limit).reset_index(drop=True)
