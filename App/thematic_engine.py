"""Thematic Intelligence Engine for MarketPulse.

Tracks the 44 Official NSE Thematic and Sectoral Indices from index_daily,
calculating:
- RSI (14-period Wilder)
- EMA Stack (10, 20, 50, 200 EMA status)
- 4-period RS Momentum Trail (e.g. 61 → 61 → 90 → 99)
- Distance to 20 EMA and rotation state
- Thematic-to-stock mapping linking official indices to stock catalysts
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

# The 44 Official NSE Indices (28 Thematic + 16 Sectoral)
CANONICAL_44_INDICES = {
    # Thematic (28)
    "Nifty IPO": {"category": "Thematic", "clean_name": "NIFTY IPO"},
    "Nifty Internet": {"category": "Thematic", "clean_name": "NIFTY INTERNET"},
    "Nifty Capital Mkt": {"category": "Thematic", "clean_name": "NIFTY CAPITAL MKT"},
    "Nifty MS IT Telcm": {"category": "Thematic", "clean_name": "NIFTY MS IT TELCM"},
    "Nifty MS Fin Serv": {"category": "Thematic", "clean_name": "NIFTY MS FIN SERV"},
    "Nifty Ind Defence": {"category": "Thematic", "clean_name": "NIFTY IND DEFENCE"},
    "Nifty CPSE": {"category": "Thematic", "clean_name": "NIFTY CPSE"},
    "Nifty Commodities": {"category": "Thematic", "clean_name": "NIFTY COMMODITIES"},
    "Nifty Chemicals": {"category": "Thematic", "clean_name": "NIFTY CHEMICALS"},
    "Nifty Energy": {"category": "Thematic", "clean_name": "NIFTY ENERGY"},
    "Nifty PSE": {"category": "Thematic", "clean_name": "NIFTY PSE"},
    "Nifty Housing": {"category": "Thematic", "clean_name": "NIFTY HOUSING"},
    "Nifty Infra": {"category": "Thematic", "clean_name": "NIFTY INFRA"},
    "Nifty Ind Tourism": {"category": "Thematic", "clean_name": "NIFTY IND TOURISM"},
    "Nifty CoreHousing": {"category": "Thematic", "clean_name": "NIFTY CORE HOUSING"},
    "Nifty Mobility": {"category": "Thematic", "clean_name": "NIFTY MOBILITY"},
    "Nifty RailwaysPSU": {"category": "Thematic", "clean_name": "NIFTY RAILWAYS PSU"},
    "Nifty Trans Logis": {"category": "Thematic", "clean_name": "NIFTY TRANS LOGIS"},
    "Nifty MNC": {"category": "Thematic", "clean_name": "NIFTY MNC"},
    "Nifty EV": {"category": "Thematic", "clean_name": "NIFTY EV"},
    "Nifty Rural": {"category": "Thematic", "clean_name": "NIFTY RURAL"},
    "Nifty Consumption": {"category": "Thematic", "clean_name": "NIFTY CONSUMPTION"},
    "Nifty New Consump": {"category": "Thematic", "clean_name": "NIFTY NEW CONSUMP"},
    "Nifty NonCyc Cons": {"category": "Thematic", "clean_name": "NIFTY NONCYC CONS"},
    "Nifty Tata 25 Cap": {"category": "Thematic", "clean_name": "NIFTY TATA 25 CAP"},
    "NiftyConglomerate": {"category": "Thematic", "clean_name": "NIFTY CONGLOMERATE"},
    "NIFTY IND DIGITAL": {"category": "Thematic", "clean_name": "NIFTY IND DIGITAL"},
    "NIFTY INDIA MFG": {"category": "Thematic", "clean_name": "NIFTY INDIA MFG"},
    # Sectoral (16)
    "Nifty Auto": {"category": "Sectoral", "clean_name": "NIFTY AUTO"},
    "Nifty Bank": {"category": "Sectoral", "clean_name": "NIFTY BANK"},
    "Nifty Fin Service": {"category": "Sectoral", "clean_name": "NIFTY FIN SERVICE"},
    "Nifty FinSerExBnk": {"category": "Sectoral", "clean_name": "NIFTY FINSER EX BANK"},
    "Nifty FinSrv25 50": {"category": "Sectoral", "clean_name": "NIFTY FINSRV 25 50"},
    "Nifty FMCG": {"category": "Sectoral", "clean_name": "NIFTY FMCG"},
    "Nifty IT": {"category": "Sectoral", "clean_name": "NIFTY IT"},
    "Nifty Media": {"category": "Sectoral", "clean_name": "NIFTY MEDIA"},
    "Nifty Metal": {"category": "Sectoral", "clean_name": "NIFTY METAL"},
    "Nifty Pharma": {"category": "Sectoral", "clean_name": "NIFTY PHARMA"},
    "Nifty PSU Bank": {"category": "Sectoral", "clean_name": "NIFTY PSU BANK"},
    "Nifty Pvt Bank": {"category": "Sectoral", "clean_name": "NIFTY PVT BANK"},
    "Nifty Realty": {"category": "Sectoral", "clean_name": "NIFTY REALTY"},
    "NIFTY HEALTHCARE": {"category": "Sectoral", "clean_name": "NIFTY HEALTHCARE"},
    "NIFTY OIL AND GAS": {"category": "Sectoral", "clean_name": "NIFTY OIL AND GAS"},
    "NIFTY CONSR DURBL": {"category": "Sectoral", "clean_name": "NIFTY CONSR DURBL"},
}

# Mapping of Index to Macro Investment Theme Tags & Sector Names
INDEX_THEMATIC_MAP: dict[str, dict[str, list[str]]] = {
    "Nifty Ind Defence": {"tags": ["Defence Indigenization"], "industries": ["Aerospace & Defense"]},
    "Nifty EV": {"tags": ["EV Supply Chain"], "sectors": []},
    "Nifty Capital Mkt": {"tags": ["Capital Markets"], "industries": ["Other Capital Market related Services", "Stockbroking & Allied"]},
    "Nifty Internet": {"tags": ["Digital India", "Data Center Boom"], "sectors": []},
    "NIFTY IND DIGITAL": {"tags": ["Digital India"], "sectors": ["Information Technology"]},
    "Nifty RailwaysPSU": {"tags": ["Railways"], "industries": ["Railway Wagons"]},
    "Nifty CPSE": {"tags": ["Energy Transition", "Defence Indigenization"], "sectors": []},
    "Nifty PSE": {"tags": ["Defence Indigenization"], "sectors": []},
    "Nifty Ind Tourism": {"tags": ["Hospitality Boom"], "industries": ["Hotels & Resorts", "Tour, Travel Related Services"]},
    "Nifty CoreHousing": {"tags": ["Real Estate Upcycle"], "sectors": ["Realty"]},
    "Nifty Housing": {"tags": ["Real Estate Upcycle"], "sectors": ["Realty"]},
    "Nifty Infra": {"tags": ["Infra Capex"], "sectors": ["Construction"]},
    "Nifty Mobility": {"tags": ["EV Supply Chain"], "sectors": ["Automobile and Auto Components"]},
    "Nifty Rural": {"tags": ["Rural Recovery", "Agri Value Chain"], "sectors": []},
    "Nifty Commodities": {"tags": ["Specialty Chemicals"], "sectors": ["Metals & Mining"]},
    "Nifty Chemicals": {"tags": ["Specialty Chemicals"], "sectors": ["Chemicals"]},
    "Nifty Energy": {"tags": ["Energy Transition"], "sectors": ["Oil, Gas & Consumable Fuels", "Power"]},
    "NIFTY INDIA MFG": {"tags": ["Make in India"], "sectors": ["Capital Goods"]},
    "Nifty Consumption": {"tags": ["Premiumization", "Retail Recovery"], "sectors": ["Consumer Durables"]},
    "Nifty New Consump": {"tags": ["Premiumization"], "sectors": ["Consumer Services"]},
    "Nifty NonCyc Cons": {"tags": ["Rural Recovery"], "sectors": ["Fast Moving Consumer Goods"]},
    "Nifty Trans Logis": {"tags": ["Infra Capex"], "industries": ["Logistics Solution Provider", "Transport Related Services"]},
    "Nifty MNC": {"tags": ["Premiumization"], "sectors": []},
    "Nifty Auto": {"tags": [], "sectors": ["Automobile and Auto Components"]},
    "Nifty Bank": {"tags": [], "industries": ["Private Sector Bank", "Public Sector Bank"]},
    "Nifty PSU Bank": {"tags": [], "industries": ["Public Sector Bank"]},
    "Nifty Pvt Bank": {"tags": [], "industries": ["Private Sector Bank"]},
    "Nifty Fin Service": {"tags": ["Banking Credit Growth"], "sectors": ["Financial Services"]},
    "Nifty FinSerExBnk": {"tags": ["Insurance Penetration", "Financial Inclusion"], "sectors": ["Financial Services"]},
    "Nifty IT": {"tags": [], "sectors": ["Information Technology"]},
    "Nifty Metal": {"tags": [], "sectors": ["Metals & Mining"]},
    "Nifty Pharma": {"tags": ["API/Pharma"], "sectors": ["Healthcare"]},
    "NIFTY HEALTHCARE": {"tags": ["API/Pharma"], "sectors": ["Healthcare"]},
    "Nifty Realty": {"tags": [], "sectors": ["Realty"]},
    "Nifty FMCG": {"tags": [], "sectors": ["Fast Moving Consumer Goods"]},
    "NIFTY OIL AND GAS": {"tags": [], "sectors": ["Oil, Gas & Consumable Fuels"]},
    "NIFTY CONSR DURBL": {"tags": [], "sectors": ["Consumer Durables"]},
    "Nifty Media": {"tags": [], "sectors": ["Media, Entertainment & Publication"]},
}


def _calc_wilder_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate standard Wilder RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


@functools.lru_cache(maxsize=4)
def get_stock_thematic_tags(user_db_path_str: str) -> dict[str, list[str]]:
    """Return map of symbol -> list of thematic tags from marketpulse_user.duckdb."""
    p = Path(user_db_path_str)
    if not p.exists():
        return {}
    try:
        with duckdb.connect(str(p), read_only=True) as con:
            rows = con.execute("SELECT symbol, tag FROM thematic_tags ORDER BY symbol, tag").fetchall()
            tag_map: dict[str, list[str]] = {}
            for sym, tag in rows:
                tag_map.setdefault(sym, []).append(tag)
            return tag_map
    except Exception:
        return {}


def build_thematic_leaderboard(db_path: Path) -> pd.DataFrame:
    """Build complete 44 Official NSE Thematic & Sectoral Indices leaderboard.

    Computes:
    - CMP, 1D %, 5D %, 20D %
    - RSI-14
    - EMA Stack (10, 20, 50, 200)
    - 4-session RS momentum trail (e.g. 61 -> 61 -> 90 -> 99)
    - Rotation state
    """
    with duckdb.connect(str(db_path), read_only=True) as con:
        # Get all distinct trade dates
        dates = [r[0] for r in con.execute("SELECT DISTINCT trade_date FROM index_daily ORDER BY trade_date ASC").fetchall()]
        if not dates:
            return pd.DataFrame()

        # Checkpoints for 4-period trail: T-15, T-10, T-5, T-0 (weekly Friday intervals)
        cp_indices = [-16, -11, -6, -1] if len(dates) >= 16 else [max(0, len(dates) - 4), max(0, len(dates) - 3), max(0, len(dates) - 2), len(dates) - 1]
        trail_dates = [dates[i] for i in cp_indices]

        # Fetch index daily records for the 44 indices
        names_list = list(CANONICAL_44_INDICES.keys())
        placeholders = ",".join(["?"] * len(names_list))
        df_all = con.execute(
            f"""
            SELECT trade_date, index_name, close_price, return_1d_pct, return_5d_pct, return_20d_pct,
                   ema_20, ema_50, ema_200, trend_state
            FROM index_daily
            WHERE index_name IN ({placeholders})
            ORDER BY index_name, trade_date ASC
            """,
            names_list,
        ).fetchdf()

    if df_all.empty:
        return pd.DataFrame()

    # Pre-calculate 20D return percentile ranks across all 44 indices for each of the 4 trail dates
    trail_ranks: dict[str, dict[str, int]] = {}
    for d in trail_dates:
        sub_d = df_all[df_all["trade_date"] == d].copy()
        if not sub_d.empty:
            sub_d["ret_rank"] = (sub_d["return_20d_pct"].rank(pct=True) * 100.0).round().astype(int)
            trail_ranks[str(d)[:10]] = dict(zip(sub_d["index_name"], sub_d["ret_rank"]))

    records = []
    for name, group in df_all.groupby("index_name"):
        group = group.sort_values("trade_date").reset_index(drop=True)
        if group.empty:
            continue

        meta = CANONICAL_44_INDICES.get(name, {"category": "Thematic", "clean_name": name})
        latest_row = group.iloc[-1]
        cp = float(latest_row["close_price"] or 0.0)

        # Calculate EMA 10 on the fly
        group["ema_10"] = group["close_price"].ewm(span=10, adjust=False).mean()
        ema_10 = float(group["ema_10"].iloc[-1])

        # Get or compute EMA 20, 50, 200
        ema_20 = float(latest_row["ema_20"] or group["close_price"].ewm(span=20, adjust=False).mean().iloc[-1])
        ema_50 = float(latest_row["ema_50"] or group["close_price"].ewm(span=50, adjust=False).mean().iloc[-1])
        ema_200 = float(latest_row["ema_200"] or group["close_price"].ewm(span=200, adjust=False).mean().iloc[-1])

        # EMA Stack flags
        above_10 = cp >= (ema_10 * 0.999)
        above_20 = cp >= (ema_20 * 0.999)
        above_50 = cp >= (ema_50 * 0.999)
        above_200 = cp >= (ema_200 * 0.999)
        stack_count = sum([above_10, above_20, above_50, above_200])

        # Distance to 20 EMA %
        dist_20 = ((cp - ema_20) / ema_20 * 100.0) if ema_20 > 0 else 0.0

        # RSI-14
        rsi_series = _calc_wilder_rsi(group["close_price"], period=14)
        rsi_val = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0

        # Build 4-session RS Trail
        trail_vals = []
        for d in trail_dates:
            d_str = str(d)[:10]
            val = trail_ranks.get(d_str, {}).get(name, int(round(rsi_val)))
            trail_vals.append(val)

        # Fallback if trail values not found
        if not trail_vals:
            trail_vals = [int(round(rsi_val))] * 4

        # Net trend momentum change across the 4 points
        net_momentum = trail_vals[-1] - trail_vals[0]

        # Trend State
        trend_state = str(latest_row["trend_state"] or "Neutral")
        if stack_count == 4 and rsi_val >= 55.0:
            trend_state = "Leading"
        elif stack_count >= 3 and rsi_val >= 50.0:
            trend_state = "Improving"
        elif stack_count <= 1 and rsi_val < 45.0:
            trend_state = "Lagging"
        elif stack_count <= 2:
            trend_state = "Weakening"

        records.append({
            "index_name": name,
            "clean_name": meta["clean_name"],
            "category": meta["category"],
            "close_price": cp,
            "return_1d_pct": float(latest_row["return_1d_pct"] or 0.0),
            "return_5d_pct": float(latest_row["return_5d_pct"] or 0.0),
            "return_20d_pct": float(latest_row["return_20d_pct"] or 0.0),
            "distance_ema_20_pct": dist_20,
            "rsi_14": rsi_val,
            "above_10": above_10,
            "above_20": above_20,
            "above_50": above_50,
            "above_200": above_200,
            "stack_count": stack_count,
            "trail_vals": trail_vals,
            "net_momentum": net_momentum,
            "trend_state": trend_state,
        })

    result_df = pd.DataFrame(records)
    if result_df.empty:
        return result_df

    # Sort by momentum: stack count DESC, RSI-14 DESC, return_1d_pct DESC
    result_df = result_df.sort_values(
        by=["return_20d_pct", "rsi_14", "return_1d_pct"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    result_df["rank"] = range(1, len(result_df) + 1)
    return result_df


def get_macro_pulse(db_path: Path) -> dict[str, Any]:
    """Return top 3 running and bottom 3 lagging macro themes today."""
    df = build_thematic_leaderboard(db_path)
    if df.empty:
        return {"top": [], "bottom": []}

    # Filter to thematic category for cleanest theme representation
    thematic_df = df[df["category"] == "Thematic"]
    if thematic_df.empty:
        thematic_df = df

    thematic_sorted = thematic_df.sort_values(by="return_1d_pct", ascending=False)
    top_3 = thematic_sorted.head(3).to_dict("records")
    bottom_3 = thematic_sorted.tail(3).sort_values(by="return_1d_pct", ascending=True).to_dict("records")

    return {
        "top": [
            {"name": r["clean_name"].replace("NIFTY ", ""), "return_1d": r["return_1d_pct"], "trend": r["trend_state"]}
            for r in top_3
        ],
        "bottom": [
            {"name": r["clean_name"].replace("NIFTY ", ""), "return_1d": r["return_1d_pct"], "trend": r["trend_state"]}
            for r in bottom_3
        ],
    }


def get_index_constituents(db_path: Path, user_db_path: Path, index_name: str) -> pd.DataFrame:
    """Fetch constituent stocks matching an official NSE index's macro theme and sector."""
    mapping = INDEX_THEMATIC_MAP.get(index_name, {})
    tags = mapping.get("tags", [])
    sectors = mapping.get("sectors", [])
    industries = mapping.get("industries", [])

    stock_tags = get_stock_thematic_tags(str(user_db_path))

    # Match stocks by tag
    matched_symbols = set()
    for sym, s_tags in stock_tags.items():
        if any(t in s_tags for t in tags):
            matched_symbols.add(sym)

    with duckdb.connect(str(db_path), read_only=True) as con:
        # Match by sector in stocks_master
        if sectors:
            sec_placeholders = ",".join(["?"] * len(sectors))
            sec_rows = con.execute(
                f"SELECT symbol FROM stocks_master WHERE sector IN ({sec_placeholders})",
                sectors,
            ).fetchall()
            for r in sec_rows:
                matched_symbols.add(r[0])

        # Match by industry in stocks_master
        if industries:
            ind_placeholders = ",".join(["?"] * len(industries))
            ind_rows = con.execute(
                f"SELECT symbol FROM stocks_master WHERE industry IN ({ind_placeholders})",
                industries,
            ).fetchall()
            for r in ind_rows:
                matched_symbols.add(r[0])

        if not matched_symbols:
            return pd.DataFrame()

        # Query latest performance for these matched stocks
        sym_placeholders = ",".join(["?"] * len(matched_symbols))
        sql = f"""
        WITH latest AS (SELECT max(trade_date) AS max_d FROM prices_daily)
        SELECT p.symbol, coalesce(m.security_name, p.symbol) AS company_name, m.sector, m.industry,
               p.close_price,
               round(((p.close_price - p.prev_close) / NULLIF(p.prev_close, 0)) * 100.0, 2) AS day_pct,
               p.turnover_cr,
               i.rs_percentile, i.ema_10, i.ema_20, i.ema_50, i.ema_200,
               r.market_cap_cr
        FROM prices_daily p
        JOIN latest l ON p.trade_date = l.max_d
        LEFT JOIN stocks_master m ON p.symbol = m.symbol
        LEFT JOIN indicators_daily i ON p.symbol = i.symbol AND p.trade_date = i.trade_date
        LEFT JOIN security_reference_daily r ON p.symbol = r.symbol AND p.trade_date = r.source_date
        WHERE p.symbol IN ({sym_placeholders})
        ORDER BY p.turnover_cr DESC
        """
        df = con.execute(sql, list(matched_symbols)).fetchdf()

    if df.empty:
        return df

    # Attach primary macro theme tag to each stock
    df["theme"] = df["symbol"].map(lambda s: stock_tags.get(s, ["—"])[0])
    return df
