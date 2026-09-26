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

try:
    from Scripts.price_views import ohlcv_columns
except ModuleNotFoundError:
    from price_views import ohlcv_columns  # type: ignore

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
    # Tidy multiple spaces and trailing punctuation left by suffix strips
    n = re.sub(r"\s+", " ", n).strip(" .")
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

    with duckdb.connect(str(target_db), read_only=True) as con:
        cols = ohlcv_columns(con, alias="p.")
        # Forward returns are measured against the deal price, which was struck
        # on the historical (raw) price scale. Rescale it onto the adjusted
        # scale using the cumulative price_factor as of the deal date, so a
        # split/bonus between the deal and today doesn't show up as a fake
        # return.
        query = f"""
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
                {cols['open_price']} AS open_price,
                {cols['high_price']} AS high_price,
                {cols['low_price']} AS low_price,
                {cols['close_price']} AS close_price,
                {cols['price_factor']} AS price_factor,
                row_number() OVER (PARTITION BY b.symbol, b.deal_date, b.client_name, b.deal_price ORDER BY p.trade_date) - 1 as sess_idx
            FROM buy_deals b
            JOIN prices_daily p ON p.symbol = b.symbol AND p.trade_date >= b.deal_date
        ),
        deal_base AS (
            SELECT
                deal_date,
                symbol,
                client_name,
                deal_price,
                deal_value_cr,
                clientele,
                clientele_sub,
                max(sess_idx) as holding_days,
                max(CASE WHEN sess_idx = 0 THEN price_factor END) as factor_on_deal_date,
                -- close at key forward horizons
                max(CASE WHEN sess_idx = 5 THEN close_price END) as close_5d,
                max(CASE WHEN sess_idx = 10 THEN close_price END) as close_10d,
                max(CASE WHEN sess_idx = 20 THEN close_price END) as close_20d,
                max(CASE WHEN sess_idx = 60 THEN close_price END) as close_60d,
                -- latest close / CMP
                arg_max(close_price, sess_idx) as cmp,
                -- max peak runup within 60 sessions
                max(CASE WHEN sess_idx <= 60 THEN high_price END) as peak_60d,
                min(CASE WHEN sess_idx <= 60 THEN low_price END) as trough_60d,
                -- days taken to hit peak high
                arg_max(sess_idx, CASE WHEN sess_idx <= 60 THEN high_price END) as days_to_peak
            FROM daily_series
            GROUP BY deal_date, symbol, client_name, deal_price, deal_value_cr, clientele, clientele_sub
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
                holding_days,
                -- returns at key forward horizons (deal_price rescaled onto the adjusted basis)
                (close_5d / (deal_price * coalesce(factor_on_deal_date, 1.0)) - 1) * 100 as ret_5d,
                (close_10d / (deal_price * coalesce(factor_on_deal_date, 1.0)) - 1) * 100 as ret_10d,
                (close_20d / (deal_price * coalesce(factor_on_deal_date, 1.0)) - 1) * 100 as ret_20d,
                (close_60d / (deal_price * coalesce(factor_on_deal_date, 1.0)) - 1) * 100 as ret_60d,
                cmp,
                round((cmp / (deal_price * coalesce(factor_on_deal_date, 1.0)) - 1) * 100, 1) as ret_current,
                round((peak_60d / (deal_price * coalesce(factor_on_deal_date, 1.0)) - 1) * 100, 1) as max_runup_pct,
                round((trough_60d / (deal_price * coalesce(factor_on_deal_date, 1.0)) - 1) * 100, 1) as max_drawdown_pct,
                days_to_peak
            FROM deal_base
        )
        SELECT * FROM deal_summary ORDER BY deal_date DESC
        """

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
    g["bets_count"] = g["total_bets"].astype(int)
    g["names_count"] = g["unique_stocks"].astype(int)
    return g


def fetch_fund_holdings_book(
    db_path: Path | None = None,
    lookback_days: int = 20,
    min_deal_cr: float = 5.0,
    min_mcap_cr: float = 1000.0,
) -> dict[str, list[dict[str, Any]]]:
    """Net prints per fund house × symbol in the lookback window.

    NSE bulk/block is not a 13F book. This is the print tape: names they bought
    vs sold in the window, with net ₹ Cr. A positive net is treated as still-on.
    """
    target_db = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    if not target_db.exists():
        return {}
    with duckdb.connect(str(target_db), read_only=True) as con:
        dates = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT trade_date FROM deals ORDER BY trade_date DESC LIMIT ?",
                [int(lookback_days)],
            ).fetchall()
        ]
        if not dates:
            return {}
        placeholders = ",".join(["?"] * len(dates))
        raw = con.execute(
            f"""
            SELECT
                d.trade_date, d.symbol, d.client_name, d.side, d.price,
                d.deal_value_cr, d.clientele, d.is_prop, d.is_hft,
                coalesce(d.market_cap_cr, m.market_cap_cr, 0) AS market_cap_cr,
                coalesce(d.sector, m.sector, '') AS sector,
                i.close_price AS cmp
            FROM deals d
            LEFT JOIN stocks_master m ON m.symbol = d.symbol
            LEFT JOIN indicators_daily i
              ON i.symbol = d.symbol
             AND i.trade_date = (SELECT max(trade_date) FROM indicators_daily)
            WHERE d.trade_date IN ({placeholders})
              AND coalesce(d.deal_value_cr, 0) >= ?
              AND coalesce(d.market_cap_cr, m.market_cap_cr, 0) >= ?
              AND (d.is_prop = False OR d.is_prop IS NULL)
              AND (d.is_hft = False OR d.is_hft IS NULL)
              AND d.symbol NOT LIKE '%-RE'
              AND d.symbol NOT LIKE '%_RE'
              AND upper(d.symbol) <> 'TOTAL'
            """,
            [*dates, float(min_deal_cr), float(min_mcap_cr)],
        ).fetchdf()
    if raw.empty:
        return {}
    raw["fund_house"] = raw["client_name"].map(clean_fund_name)
    raw = raw[raw["fund_house"].astype(str).str.len() > 0]
    if raw.empty:
        return {}
    raw["is_buy"] = raw["side"].astype(str).str.upper().str.contains("BUY")
    book: dict[str, list[dict[str, Any]]] = {}
    grouped = raw.groupby(["fund_house", "symbol"], sort=False)
    rows = []
    for (house, symbol), g in grouped:
        buy_cr = float(g.loc[g["is_buy"], "deal_value_cr"].sum())
        sell_cr = float(g.loc[~g["is_buy"], "deal_value_cr"].sum())
        last = g.sort_values("trade_date").iloc[-1]
        cmp = float(last["cmp"]) if pd.notna(last.get("cmp")) else None
        deal_px = float(last["price"]) if pd.notna(last.get("price")) else None
        ret = None
        if cmp and deal_px and deal_px > 0:
            ret = round((cmp / deal_px - 1.0) * 100.0, 1)
        rows.append(
            {
                "fund_house": str(house),
                "symbol": str(symbol),
                "buy_cr": round(buy_cr, 1),
                "sell_cr": round(sell_cr, 1),
                "net_cr": round(buy_cr - sell_cr, 1),
                "prints": int(len(g)),
                "last_date": str(pd.Timestamp(last["trade_date"]).date()),
                "last_side": "BUY" if bool(last["is_buy"]) else "SELL",
                "last_price": round(deal_px, 2) if deal_px else None,
                "cmp": round(cmp, 2) if cmp else None,
                "ret_pct": ret,
                "mcap_cr": round(float(last["market_cap_cr"]), 0) if pd.notna(last.get("market_cap_cr")) else None,
                "sector": str(last.get("sector") or ""),
            }
        )
    for rec in rows:
        book.setdefault(rec["fund_house"], []).append(rec)
    for house, items in book.items():
        items.sort(key=lambda x: (abs(x["net_cr"]), x["prints"]), reverse=True)
    return book


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
        return {"deals": [], "symbols": [], "tv_list": "", "as_of": None, "leaderboard": pd.DataFrame(), "holdings": {}}

    leaderboard = build_fund_leaderboard(attr_df, min_bets=2)
    if leaderboard.empty:
        return {"deals": [], "symbols": [], "tv_list": "", "as_of": None, "leaderboard": pd.DataFrame(), "holdings": {}}

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

    holdings = fetch_fund_holdings_book(db_path, lookback_days=lookback_days, min_deal_cr=min_deal_cr)

    if recent_star_deals.empty:
        return {
            "deals": [],
            "symbols": [],
            "tv_list": "",
            "as_of": as_of,
            "leaderboard": leaderboard,
            "holdings": holdings,
        }

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
        "holdings": holdings,
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
