"""Institutional Performance & Fund Attribution Engine.

Quantifies the price trajectory and alpha generated following institutional additions.
Identifies 'Star Catalyst' funds (who made stocks run faster, whose stock selection is superior),
computes forward win rates (T+5d, T+20d, T+60d, peak runup), and flags live Smart Radar alerts
when top-tier funds add new stocks.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
import duckdb
import numpy as np
import pandas as pd

# Default DB Path
DEFAULT_DB_PATH = Path("Database/marketpulse.duckdb")


def clean_fund_name(name: str) -> str:
    """Normalizes fund entity names by stripping technical suffixes (-FPI, -ODI, PVT LTD)."""
    if not name or not isinstance(name, str):
        return ""
    n = name.strip()
    # Remove trailing -ODI, -FPI, etc.
    n = re.sub(r"\s*[-/]\s*(FPI|ODI|EQUITY|DEBT|A/C|SUB-ACCOUNT).*$", "", n, flags=re.IGNORECASE)
    # Remove corporate suffixes if mutual fund / bank is already clear
    n = re.sub(r"\s+(PRIVATE LIMITED|PVT LTD|PVT\. LTD\.|LLP|LTD\.|LIMITED|CO\.? LTD\.?)\s*$", "", n, flags=re.IGNORECASE)
    # Tidy multiple spaces
    n = re.sub(r"\s+", " ", n).strip()
    return n


def to_tv_symbols_list(symbols: list[str], prefix: str = "NSE:") -> str:
    """Formats a list of symbols for TradingView watchlist import."""
    clean_syms = []
    seen = set()
    for s in symbols:
        if not s or not isinstance(s, str):
            continue
        sym = s.strip().upper()
        if sym and sym not in seen and not sym.endswith(("-RE", "_RE")):
            seen.add(sym)
            clean_syms.append(f"{prefix}{sym}")
    return ",".join(clean_syms)


def fetch_deal_attribution_df(db_path: Path | None = None, min_deal_cr: float = 5.0) -> pd.DataFrame:
    """Calculates forward returns, peak runups, and drawdowns for all institutional BUY deals.

    Excludes pure algorithmic prop desks (is_prop=True) and HFT scalpers (is_hft=True).
    """
    target_db = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    if not target_db.exists():
        return pd.DataFrame()

    query = """
    WITH buy_deals AS (
        SELECT 
            d.trade_date as deal_date,
            d.symbol,
            d.client_name,
            d.price as deal_price,
            d.deal_value_cr,
            d.clientele,
            d.clientele_sub
        FROM deals d
        WHERE d.side = 'BUY' 
          AND (d.is_prop = False OR d.is_prop IS NULL)
          AND (d.is_hft = False OR d.is_hft IS NULL)
          AND d.deal_value_cr >= ?
          AND d.symbol NOT LIKE '%-RE'
          AND d.symbol NOT LIKE '%_RE'
    ),
    daily_series AS (
        SELECT 
            b.deal_date,
            b.symbol,
            b.client_name,
            b.deal_price,
            b.deal_value_cr,
            b.clientele,
            b.clientele_sub,
            p.trade_date,
            p.open_price,
            p.high_price,
            p.low_price,
            p.close_price,
            row_number() OVER (PARTITION BY b.symbol, b.deal_date, b.client_name, b.deal_price ORDER BY p.trade_date) - 1 as sess_idx
        FROM buy_deals b
        JOIN prices_daily p ON p.symbol = b.symbol AND p.trade_date >= b.deal_date
    ),
    deal_summary AS (
        SELECT 
            deal_date,
            symbol,
            client_name,
            deal_price,
            deal_value_cr,
            clientele,
            clientele_sub,
            max(sess_idx) as holding_days,
            -- returns at key forward horizons
            max(CASE WHEN sess_idx = 5 THEN (close_price / deal_price - 1) * 100 END) as ret_5d,
            max(CASE WHEN sess_idx = 10 THEN (close_price / deal_price - 1) * 100 END) as ret_10d,
            max(CASE WHEN sess_idx = 20 THEN (close_price / deal_price - 1) * 100 END) as ret_20d,
            max(CASE WHEN sess_idx = 60 THEN (close_price / deal_price - 1) * 100 END) as ret_60d,
            -- latest close / CMP
            arg_max(close_price, sess_idx) as cmp,
            round((arg_max(close_price, sess_idx) / deal_price - 1) * 100, 1) as ret_current,
            -- max peak runup within 60 sessions
            round((max(CASE WHEN sess_idx <= 60 THEN high_price END) / deal_price - 1) * 100, 1) as max_runup_pct,
            round((min(CASE WHEN sess_idx <= 60 THEN low_price END) / deal_price - 1) * 100, 1) as max_drawdown_pct,
            -- days taken to hit peak high
            arg_max(sess_idx, CASE WHEN sess_idx <= 60 THEN high_price END) as days_to_peak
        FROM daily_series
        GROUP BY deal_date, symbol, client_name, deal_price, deal_value_cr, clientele, clientele_sub
    )
    SELECT * FROM deal_summary ORDER BY deal_date DESC
    """

    with duckdb.connect(str(target_db), read_only=True) as con:
        df = con.execute(query, [float(min_deal_cr)]).fetchdf()

    if df.empty:
        return df

    df["fund_house"] = df["client_name"].map(clean_fund_name)
    df["deal_date"] = pd.to_datetime(df["deal_date"]).dt.date
    return df


def build_fund_leaderboard(attribution_df: pd.DataFrame, min_bets: int = 3) -> pd.DataFrame:
    """Ranks institutional funds by win rate, forward returns, and velocity (speed of run-up)."""
    if attribution_df.empty:
        return pd.DataFrame()

    # Aggregate by normalized fund house
    g = attribution_df.groupby("fund_house").agg(
        total_bets=("symbol", "count"),
        unique_stocks=("symbol", "nunique"),
        total_cr=("deal_value_cr", "sum"),
        avg_runup=("max_runup_pct", "mean"),
        avg_20d=("ret_20d", "mean"),
        avg_60d=("ret_60d", "mean"),
        avg_current=("ret_current", "mean"),
        avg_drawdown=("max_drawdown_pct", "mean"),
        avg_days_to_peak=("days_to_peak", "mean"),
        # 20d Win Count: either reached 20d with >= +5% OR if recent, current return >= +5%
        win_count_20d=("ret_20d", lambda s: (s >= 5.0).sum()),
        eligible_20d=("ret_20d", lambda s: s.notna().sum()),
        # Big winners (peak gain >= 25%)
        baggers=("max_runup_pct", lambda s: (s >= 25.0).sum()),
        best_gain=("max_runup_pct", "max"),
        latest_buy_date=("deal_date", "max"),
    ).reset_index()

    # Win rate % at 20-day horizon
    g["win_rate_20d"] = np.where(g["eligible_20d"] > 0, (g["win_count_20d"] / g["eligible_20d"]) * 100, np.nan)

    # Filter minimum bets
    g = g[g["total_bets"] >= int(min_bets)].copy()
    if g.empty:
        return g

    # Composite Catalyst Score (0-100):
    # 40% Win Rate, 30% Avg Peak Run-up (scaled), 15% Avg 20d Return, 15% Velocity (quick peak)
    win_score = g["win_rate_20d"].fillna(50).clip(0, 100)
    runup_score = (g["avg_runup"].clip(0, 50) / 50.0) * 100
    ret20_score = ((g["avg_20d"].fillna(0) + 10).clip(0, 30) / 30.0) * 100
    # Velocity: Faster peak (lower days_to_peak) gives higher score
    velocity_score = (100 - g["avg_days_to_peak"].clip(5, 45) * 2).clip(20, 100)

    g["catalyst_score"] = np.round(
        win_score * 0.40 + runup_score * 0.30 + ret20_score * 0.15 + velocity_score * 0.15, 1
    )

    # Classification Tier (ASCII-safe for Windows console compatibility)
    def assign_tier(row):
        score = row["catalyst_score"]
        wr = row.get("win_rate_20d", 0)
        runup = row.get("avg_runup", 0)
        if (wr >= 75.0 or score >= 75.0) and runup >= 15.0:
            return "Star Catalyst"
        elif (wr >= 60.0 or score >= 60.0) and runup >= 10.0:
            return "Strong Accumulator"
        elif wr >= 45.0 or score >= 45.0:
            return "Steady Value"
        else:
            return "Low Alpha / Laggard"

    g["fund_tier"] = g.apply(assign_tier, axis=1)

    # Sort by Catalyst Score desc, then Total Value desc
    g = g.sort_values(["catalyst_score", "total_cr"], ascending=[False, False]).reset_index(drop=True)
    return g


def fetch_star_fund_radar(
    db_path: Path | None = None,
    lookback_days: int = 15,
    min_deal_cr: float = 5.0,
    min_catalyst_score: float = 65.0,
) -> dict[str, Any]:
    """Screens recent trading sessions for stocks added by high-conviction Star Funds.

    Returns structured radar cards, table rows, and TradingView copy-paste string.
    """
    attr_df = fetch_deal_attribution_df(db_path, min_deal_cr=min_deal_cr)
    if attr_df.empty:
        return {"deals": [], "symbols": [], "tv_list": "", "as_of": None, "leaderboard": pd.DataFrame()}

    leaderboard = build_fund_leaderboard(attr_df, min_bets=2)
    if leaderboard.empty:
        return {"deals": [], "symbols": [], "tv_list": "", "as_of": None, "leaderboard": pd.DataFrame()}

    star_funds = set(leaderboard[leaderboard["catalyst_score"] >= float(min_catalyst_score)]["fund_house"])
    # Map fund stats for quick lookup
    fund_stats = leaderboard.set_index("fund_house").to_dict("index")

    # Filter to recent deals within lookback_days
    all_dates = sorted(attr_df["deal_date"].unique(), reverse=True)
    recent_dates = set(all_dates[:int(lookback_days)])
    as_of = str(all_dates[0]) if all_dates else None

    recent_star_deals = attr_df[
        attr_df["deal_date"].isin(recent_dates) & attr_df["fund_house"].isin(star_funds)
    ].copy()

    if recent_star_deals.empty:
        return {"deals": [], "symbols": [], "tv_list": "", "as_of": as_of, "leaderboard": leaderboard}

    # Enrich with latest technical state if available in indicators_daily
    target_db = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    try:
        with duckdb.connect(str(target_db), read_only=True) as con:
            tech_df = con.execute("""
                SELECT symbol, rs_percentile, ema_stack_bullish, away_10ema_pct, away_52w_high_pct, is_vcp
                FROM indicators_daily
                WHERE trade_date = (SELECT max(trade_date) FROM indicators_daily)
            """).fetchdf()
        recent_star_deals = recent_star_deals.merge(tech_df, on="symbol", how="left")
    except Exception:
        pass

    recent_star_deals = recent_star_deals.sort_values(["deal_date", "deal_value_cr"], ascending=[False, False])

    radar_deals = []
    unique_symbols = []
    for _, r in recent_star_deals.iterrows():
        fh = r["fund_house"]
        f_info = fund_stats.get(fh, {})
        sym = r["symbol"]
        if sym not in unique_symbols:
            unique_symbols.append(sym)

        radar_deals.append({
            "deal_date": str(r["deal_date"]),
            "symbol": sym,
            "fund_house": fh,
            "deal_price": float(r["deal_price"]),
            "deal_value_cr": float(r["deal_value_cr"]),
            "cmp": float(r["cmp"]) if pd.notna(r["cmp"]) else float(r["deal_price"]),
            "ret_current": float(r["ret_current"]) if pd.notna(r["ret_current"]) else 0.0,
            "max_runup_pct": float(r["max_runup_pct"]) if pd.notna(r["max_runup_pct"]) else 0.0,
            "holding_days": int(r["holding_days"]) if pd.notna(r["holding_days"]) else 0,
            "fund_win_rate": float(f_info.get("win_rate_20d", 0)) if pd.notna(f_info.get("win_rate_20d")) else None,
            "fund_catalyst_score": float(f_info.get("catalyst_score", 0)),
            "fund_tier": str(f_info.get("fund_tier", "")),
            "rs_percentile": float(r.get("rs_percentile", 0)) if pd.notna(r.get("rs_percentile")) else None,
            "away_52w_high_pct": float(r.get("away_52w_high_pct", 0)) if pd.notna(r.get("away_52w_high_pct")) else None,
        })

    tv_list = to_tv_symbols_list(unique_symbols)
    return {
        "deals": radar_deals,
        "symbols": unique_symbols,
        "tv_list": tv_list,
        "as_of": as_of,
        "leaderboard": leaderboard,
    }


def fetch_stock_fund_attribution(db_path: Path | None = None, symbol: str = "") -> list[dict[str, Any]]:
    """Returns historical institutional entries and forward returns for a specific stock."""
    if not symbol:
        return []
    sym = symbol.strip().upper()
    attr_df = fetch_deal_attribution_df(db_path, min_deal_cr=1.0)
    if attr_df.empty:
        return []

    stock_deals = attr_df[attr_df["symbol"].str.upper() == sym].copy()
    if stock_deals.empty:
        return []

    leaderboard = build_fund_leaderboard(attr_df, min_bets=2)
    fund_stats = leaderboard.set_index("fund_house").to_dict("index") if not leaderboard.empty else {}

    results = []
    for _, r in stock_deals.sort_values("deal_date", ascending=False).iterrows():
        fh = r["fund_house"]
        f_info = fund_stats.get(fh, {})
        results.append({
            "deal_date": str(r["deal_date"]),
            "symbol": sym,
            "client_name": r["client_name"],
            "fund_house": fh,
            "deal_price": float(r["deal_price"]),
            "deal_value_cr": float(r["deal_value_cr"]),
            "cmp": float(r["cmp"]) if pd.notna(r["cmp"]) else float(r["deal_price"]),
            "ret_current": float(r["ret_current"]) if pd.notna(r["ret_current"]) else 0.0,
            "max_runup_pct": float(r["max_runup_pct"]) if pd.notna(r["max_runup_pct"]) else 0.0,
            "days_to_peak": int(r["days_to_peak"]) if pd.notna(r["days_to_peak"]) else 0,
            "ret_20d": float(r["ret_20d"]) if pd.notna(r["ret_20d"]) else None,
            "fund_win_rate": float(f_info.get("win_rate_20d", 0)) if f_info and pd.notna(f_info.get("win_rate_20d")) else None,
            "fund_catalyst_score": float(f_info.get("catalyst_score", 0)) if f_info else None,
            "fund_tier": str(f_info.get("fund_tier", "")),
        })
    return results
