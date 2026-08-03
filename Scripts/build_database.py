import argparse
import re
import shutil
import warnings
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning

from config import (
    ARCHIVE_DIR,
    DAILY_DIR,
    DATABASE_DIR,
    DB_PATH,
    EMA_WINDOWS,
    EQUITY_LIST_FILE,
    EXPORTS_DIR,
    LOGS_DIR,
    ROOT_DIR,
    RETURN_WINDOWS,
    SECTOR_FILE,
    WATCHLIST_BUCKETS,
)
from reference_history import asof_reference, load_reference_history

warnings.simplefilter("ignore", PerformanceWarning)


def ensure_folders() -> None:
    for folder in [DATABASE_DIR, EXPORTS_DIR, LOGS_DIR]:
        folder.mkdir(parents=True, exist_ok=True)


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]
    return df


def to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.strip().replace({"": np.nan, "-": np.nan}),
        errors="coerce",
    )


def parse_file_date(path: Path) -> pd.Timestamp | None:
    match = re.search(r"(\d{8})", path.name)
    if not match:
        return None
    try:
        return pd.to_datetime(match.group(1), format="%d%m%Y")
    except ValueError:
        return None


def latest_file(folder: Path, pattern: str) -> Path | None:
    files = sorted(folder.glob(pattern), key=lambda p: (parse_file_date(p) or pd.Timestamp.min, p.stat().st_mtime))
    return files[-1] if files else None


def read_equity_symbols() -> pd.DataFrame:
    df = pd.read_csv(EQUITY_LIST_FILE, usecols=[0], dtype=str)
    df.columns = ["symbol"]
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df = df[(df["symbol"] != "") & (df["symbol"].str.lower() != "nan")]
    return df.drop_duplicates("symbol")


def read_sector() -> pd.DataFrame:
    df = pd.read_csv(
        SECTOR_FILE,
        header=None,
        names=["symbol", "broad_sector", "sector", "broad_industry", "industry"],
        dtype=str,
    )
    for col in df.columns:
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["symbol"] = df["symbol"].str.upper()
    df = df[(df["symbol"] != "") & (df["symbol"] != "0")]
    return df.drop_duplicates("symbol", keep="last")


def read_bhavcopy(path: Path, universe: set[str]) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, skipinitialspace=True)
    df = clean_columns(df)
    rename = {
        "date1": "trade_date",
        "open_price": "open_price",
        "high_price": "high_price",
        "low_price": "low_price",
        "close_price": "close_price",
        "ttl_trd_qnty": "volume",
        "turnover_lacs": "turnover_lacs",
        "no_of_trades": "trades",
        "deliv_qty": "delivery_qty",
        "deliv_per": "delivery_pct",
    }
    df = df.rename(columns=rename)
    needed = [
        "symbol",
        "series",
        "trade_date",
        "prev_close",
        "open_price",
        "high_price",
        "low_price",
        "last_price",
        "close_price",
        "avg_price",
        "volume",
        "turnover_lacs",
        "trades",
        "delivery_qty",
        "delivery_pct",
    ]
    df = df[[col for col in needed if col in df.columns]].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["series"] = df["series"].astype(str).str.strip().str.upper()
    df = df[df["symbol"].isin(universe)]
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str).str.strip(), format="%d-%b-%Y", errors="coerce")
    for col in ["prev_close", "open_price", "high_price", "low_price", "last_price", "close_price", "avg_price", "volume", "turnover_lacs", "trades", "delivery_qty", "delivery_pct"]:
        if col in df.columns:
            df[col] = to_number(df[col])
    df["turnover_cr"] = df["turnover_lacs"] / 100.0
    df["series_priority"] = np.where(df["series"] == "EQ", 0, 1)
    df = df.sort_values(["symbol", "trade_date", "series_priority"]).drop_duplicates(["symbol", "trade_date"], keep="first")
    return df.drop(columns=["series_priority"], errors="ignore")


def build_prices(universe: set[str]) -> pd.DataFrame:
    files = sorted(set(ARCHIVE_DIR.glob("sec_bhavdata_full_*.csv")) | set(DAILY_DIR.glob("sec_bhavdata_full_*.csv")))
    frames = []
    for path in files:
        try:
            frame = read_bhavcopy(path, universe)
            if not frame.empty:
                frames.append(frame)
        except Exception as exc:
            print(f"Skipped {path.name}: {exc}")
    if not frames:
        raise RuntimeError("No bhavcopy files could be loaded.")
    prices = pd.concat(frames, ignore_index=True)
    prices = prices.dropna(subset=["symbol", "trade_date", "close_price"])
    prices = prices.sort_values(["symbol", "trade_date"]).drop_duplicates(["symbol", "trade_date"], keep="last")
    return prices


def read_market_cap() -> pd.DataFrame:
    path = latest_file(DAILY_DIR, "mcap*.csv")
    if not path:
        return pd.DataFrame(columns=["symbol", "security_name", "market_cap_cr", "market_cap_date"])
    df = clean_columns(pd.read_csv(path, dtype=str, skipinitialspace=True))
    market_cap_col = next((c for c in df.columns if c.startswith("market_cap")), None)
    if not market_cap_col:
        return pd.DataFrame(columns=["symbol", "security_name", "market_cap_cr", "market_cap_date"])
    out = pd.DataFrame()
    out["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    out["security_name"] = df.get("security_name", "").astype(str).str.strip()
    out["market_cap_cr"] = to_number(df[market_cap_col]) / 10_000_000
    out["market_cap_date"] = pd.to_datetime(df.get("trade_date", ""), format="%d %b %Y", errors="coerce")
    return out.drop_duplicates("symbol", keep="last")


def read_price_band() -> pd.DataFrame:
    path = latest_file(DAILY_DIR, "sec_list_*.csv")
    if not path:
        return pd.DataFrame(columns=["symbol", "band", "band_remarks"])
    df = clean_columns(pd.read_csv(path, dtype=str))
    return pd.DataFrame(
        {
            "symbol": df["symbol"].astype(str).str.strip().str.upper(),
            "band": to_number(df.get("band", pd.Series(dtype=str))),
            "band_remarks": df.get("remarks", "").astype(str).str.strip(),
        }
    ).drop_duplicates("symbol", keep="last")


def read_pe() -> pd.DataFrame:
    path = latest_file(DAILY_DIR, "PE_*.csv")
    if not path:
        return pd.DataFrame(columns=["symbol", "pe", "adjusted_pe"])
    df = clean_columns(pd.read_csv(path, dtype=str))
    return pd.DataFrame(
        {
            "symbol": df["symbol"].astype(str).str.strip().str.upper(),
            "pe": to_number(df.get("symbol_p/e", pd.Series(dtype=str))),
            "adjusted_pe": to_number(df.get("adjusted_p/e", pd.Series(dtype=str))),
        }
    ).drop_duplicates("symbol", keep="last")


def read_52_week() -> pd.DataFrame:
    path = latest_file(DAILY_DIR, "CM_52_wk_High_low_*.csv")
    if not path:
        return pd.DataFrame(columns=["symbol", "high_52w", "low_52w"])
    df = clean_columns(pd.read_csv(path, dtype=str, skiprows=2))
    return pd.DataFrame(
        {
            "symbol": df["symbol"].astype(str).str.strip().str.upper(),
            "series": df["series"].astype(str).str.strip().str.upper(),
            "high_52w": to_number(df.get("adjusted_52_week_high", pd.Series(dtype=str))),
            "high_52w_date": pd.to_datetime(df.get("52_week_high_date", ""), format="%d-%b-%Y", errors="coerce"),
            "low_52w": to_number(df.get("adjusted_52_week_low", pd.Series(dtype=str))),
            "low_52w_date": pd.to_datetime(df.get("52_week_low_dt", ""), format="%d-%b-%Y", errors="coerce"),
        }
    ).drop_duplicates("symbol", keep="last")


def _empty_deals_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["deal_type", "trade_date", "symbol", "security_name", "client_name", "side", "quantity", "price", "source_file"]
    )


def _series_col(df: pd.DataFrame, *candidates: str) -> pd.Series:
    """Return the first matching column as a Series; never a bare default string."""
    for name in candidates:
        if name in df.columns:
            return df[name]
    return pd.Series([pd.NA] * len(df), index=df.index, dtype="object")


def read_deals(path: Path, deal_type: str) -> pd.DataFrame:
    """Parse NSE bulk/block CSV (daily archive format or historical range export)."""
    if not path.exists():
        return _empty_deals_frame()
    try:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", skipinitialspace=True)
    except Exception:
        try:
            df = pd.read_csv(path, dtype=str, encoding="cp1252", skipinitialspace=True)
        except Exception as exc:
            print(f"Skipped deals file {path.name}: {exc}")
            return _empty_deals_frame()
    df = clean_columns(df)
    if df.empty:
        return _empty_deals_frame()
    # Historical exports clean to buy_/_sell; daily files clean to buy/sell.
    date_s = _series_col(df, "date", "bd_dt_date", "timestamp")
    if date_s.astype(str).str.strip().str.upper().eq("NO RECORDS").any() and len(df) <= 2:
        return _empty_deals_frame()
    first_date = str(date_s.iloc[0]).strip().upper() if len(date_s) else ""
    if first_date in {"NO RECORDS", "NAN", ""}:
        # Single NO RECORDS row, or unusable file
        non_empty = date_s.astype(str).str.strip().str.upper().replace({"NAN": "", "NONE": ""})
        if non_empty.eq("").all() or non_empty.eq("NO RECORDS").all():
            return _empty_deals_frame()

    side_s = _series_col(df, "buy/sell", "buy_/_sell", "buy_sell", "bd_buy_sell")
    qty_s = _series_col(df, "quantity_traded", "quantity", "bd_qty_trd")
    price_s = _series_col(
        df,
        "trade_price_/_wght._avg._price",
        "trade_price_/_wght_avg_price",
        "trade_price",
        "bd_tp_watp",
        "price",
    )
    symbol_s = _series_col(df, "symbol", "bd_symbol")
    security_s = _series_col(df, "security_name", "bd_scrip_name")
    client_s = _series_col(df, "client_name", "bd_client_name")

    trade_date = pd.to_datetime(date_s.astype(str).str.strip(), format="%d-%b-%Y", errors="coerce")
    if trade_date.isna().all():
        trade_date = pd.to_datetime(date_s.astype(str).str.strip(), dayfirst=True, errors="coerce")

    out = pd.DataFrame(
        {
            "deal_type": deal_type,
            "trade_date": trade_date,
            "symbol": symbol_s.astype(str).str.strip().str.upper(),
            "security_name": security_s.astype(str).str.strip(),
            "client_name": client_s.astype(str).str.strip(),
            "side": side_s.astype(str).str.strip().str.upper().str.replace(r"\s+", "", regex=True),
            "quantity": to_number(qty_s),
            "price": to_number(price_s),
            "source_file": path.name,
        }
    )
    # Drop junk rows (NO RECORDS, blank symbols)
    out = out[~out["symbol"].isin({"", "NAN", "NONE", "NO RECORDS", "SYMBOL"})]
    out = out[out["side"].isin({"BUY", "SELL"})]
    return out.reset_index(drop=True)


def _deal_file_sort_key(path: Path) -> tuple:
    """Process single-day files first; multi-day range exports last so they win on dedupe."""
    name = path.name.lower()
    is_range = ("-to-" in name) or name.startswith("bulk-deals") or name.startswith("block-deals")
    return (1 if is_range else 0, name)


def _iter_deal_paths(folder: Path, kind: str) -> list[Path]:
    """kind is 'bulk' or 'block'. Collect daily and historical range filenames."""
    if not folder.exists():
        return []
    patterns = (
        f"{kind}*.csv",
        f"{kind.capitalize()}*.csv",
        f"{kind.capitalize()}-Deals*.csv",
        f"{kind.upper()}-Deals*.csv",
    )
    found: dict[str, Path] = {}
    for pattern in patterns:
        for path in folder.glob(pattern):
            # Avoid treating non-deal CSVs; require name stem to start with bulk/block
            stem = path.name.lower()
            if not stem.startswith(kind):
                continue
            found[str(path.resolve()).lower()] = path
    return sorted(found.values(), key=_deal_file_sort_key)


def read_all_deals() -> pd.DataFrame:
    frames = []
    for folder in [ARCHIVE_DIR, DAILY_DIR]:
        for path in _iter_deal_paths(folder, "bulk"):
            frames.append(read_deals(path, "Bulk"))
        for path in _iter_deal_paths(folder, "block"):
            frames.append(read_deals(path, "Block"))
    if not frames:
        return _empty_deals_frame()
    deals = pd.concat(frames, ignore_index=True)
    if deals.empty:
        return _empty_deals_frame()
    deals["trade_date"] = pd.to_datetime(deals["trade_date"], errors="coerce")
    deals = deals.dropna(subset=["trade_date", "symbol", "side", "quantity", "price"])
    deals["symbol"] = deals["symbol"].astype(str).str.strip().str.upper()
    deals["client_name"] = deals["client_name"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    deals["side"] = deals["side"].astype(str).str.strip().str.upper()
    # Range files sorted last → keep="last" prefers the historical export on conflicts.
    deals = deals.drop_duplicates(
        ["deal_type", "trade_date", "symbol", "client_name", "side", "quantity", "price"],
        keep="last",
    )
    deals["deal_value_cr"] = deals["quantity"] * deals["price"] / 10_000_000
    return deals.sort_values(["trade_date", "deal_type", "symbol", "side", "client_name"]).reset_index(drop=True)


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def rsi_divergence_flags(price: pd.Series, rsi: pd.Series) -> tuple[pd.Series, pd.Series]:
    swing_low = (price < price.shift(1)) & (price <= price.shift(-1))
    swing_high = (price > price.shift(1)) & (price >= price.shift(-1))
    low_price = price.where(swing_low)
    low_rsi = rsi.where(swing_low)
    high_price = price.where(swing_high)
    high_rsi = rsi.where(swing_high)
    prev_low_price = low_price.ffill().shift(1)
    prev_low_rsi = low_rsi.ffill().shift(1)
    prev_high_price = high_price.ffill().shift(1)
    prev_high_rsi = high_rsi.ffill().shift(1)
    bullish = swing_low & (price < prev_low_price) & (rsi > prev_low_rsi)
    bearish = swing_high & (price > prev_high_price) & (rsi < prev_high_rsi)
    return bullish.fillna(False), bearish.fillna(False)


def candle_features(bars: pd.DataFrame) -> pd.DataFrame:
    bars = bars.copy()
    day_range = (bars["high_price"] - bars["low_price"]).replace(0, np.nan)
    bars["body_pct"] = (bars["close_price"] - bars["open_price"]).abs() / day_range * 100
    bars["upper_wick_pct"] = (bars["high_price"] - pd.concat([bars["close_price"], bars["open_price"]], axis=1).max(axis=1)) / day_range * 100
    bars["lower_wick_pct"] = (pd.concat([bars["close_price"], bars["open_price"]], axis=1).min(axis=1) - bars["low_price"]) / day_range * 100
    bars["close_location_pct"] = (bars["close_price"] - bars["low_price"]) / day_range * 100
    small_body = bars["body_pct"] <= 35
    bars["confirmed_morning_star"] = (
        (bars["close_price"].shift(2) < bars["open_price"].shift(2))
        & small_body.shift(1)
        & (bars["close_price"] > bars["open_price"])
        & (bars["close_price"] > ((bars["open_price"].shift(2) + bars["close_price"].shift(2)) / 2))
        & (bars["close_price"].shift(2) < bars["close_price"].shift(7))
        & (bars["close_location_pct"] >= 60)
    )
    bars["confirmed_shooting_star"] = (
        (bars["upper_wick_pct"] >= 50)
        & (bars["lower_wick_pct"] <= 20)
        & (bars["close_location_pct"] <= 40)
        & (bars["close_price"] > bars["close_price"].shift(10))
    )
    return bars


def resampled_timeframe_features(g: pd.DataFrame, rule: str) -> pd.DataFrame:
    bars = (
        g.set_index("trade_date")
        .resample(rule)
        .agg(
            open_price=("open_price", "first"),
            high_price=("high_price", "max"),
            low_price=("low_price", "min"),
            close_price=("close_price", "last"),
            volume=("volume", "sum"),
        )
        .dropna(subset=["open_price", "high_price", "low_price", "close_price"])
    )
    if bars.empty:
        return bars
    bars = candle_features(bars)
    bars["rsi_14"] = calc_rsi(bars["close_price"])
    bars["bullish_rsi_divergence"], bars["bearish_rsi_divergence"] = rsi_divergence_flags(bars["close_price"], bars["rsi_14"])
    return bars


def calc_indicators(prices: pd.DataFrame, enrichment: pd.DataFrame) -> pd.DataFrame:
    df = prices.sort_values(["symbol", "trade_date"]).copy()
    parts = []
    for _, group in df.groupby("symbol", sort=False):
        g = group.copy().sort_values("trade_date")
        close = g["close_price"]
        high = g["high_price"]
        low = g["low_price"]
        prev_close = close.shift(1)
        for window in EMA_WINDOWS:
            g[f"ema_{window}"] = close.ewm(span=window, adjust=False, min_periods=window).mean()
        for name, window in RETURN_WINDOWS.items():
            g[name] = (close / close.shift(window) - 1) * 100
        g["rsi_14"] = calc_rsi(close)
        g["bullish_rsi_divergence"], g["bearish_rsi_divergence"] = rsi_divergence_flags(close, g["rsi_14"])
        g["avg_volume_5d"] = g["volume"].rolling(5, min_periods=3).mean()
        g["avg_volume_10d"] = g["volume"].rolling(10, min_periods=3).mean()
        g["avg_volume_20d"] = g["volume"].rolling(20, min_periods=5).mean()
        g["avg_volume_50d"] = g["volume"].rolling(50, min_periods=10).mean()
        g["avg_traded_value_cr_20d"] = g["turnover_cr"].rolling(20, min_periods=5).mean()
        g["avg_traded_value_cr_50d"] = g["turnover_cr"].rolling(50, min_periods=10).mean()
        g["rvol"] = g["volume"] / g["avg_volume_20d"]
        g["avg_delivery_qty_20d"] = g["delivery_qty"].rolling(20, min_periods=5).mean()
        g["avg_delivery_pct_20d"] = g["delivery_pct"].rolling(20, min_periods=5).mean()
        g["delivery_spike"] = g["delivery_qty"] > (2 * g["avg_delivery_qty_20d"])
        true_range = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        g["true_range"] = true_range
        g["atr_14"] = true_range.rolling(14, min_periods=5).mean()
        g["atr_pct"] = g["atr_14"] / close * 100
        g["atr_pct_avg_5d"] = g["atr_pct"].rolling(5, min_periods=3).mean()
        g["atr_pct_avg_20d"] = g["atr_pct"].rolling(20, min_periods=5).mean()
        g["atr_pct_avg_50d"] = g["atr_pct"].rolling(50, min_periods=10).mean()
        day_range = (high - low).replace(0, np.nan)
        g["body_pct"] = (close - g["open_price"]).abs() / day_range * 100
        g["upper_wick_pct"] = (high - pd.concat([close, g["open_price"]], axis=1).max(axis=1)) / day_range * 100
        g["lower_wick_pct"] = (pd.concat([close, g["open_price"]], axis=1).min(axis=1) - low) / day_range * 100
        g["close_location_pct"] = (close - low) / day_range * 100
        for window in [5, 10, 20, 50, 100, 252]:
            g[f"high_{window}d"] = high.rolling(window, min_periods=3).max()
            g[f"low_{window}d"] = low.rolling(window, min_periods=3).min()
            g[f"range_{window}d_pct"] = (g[f"high_{window}d"] - g[f"low_{window}d"]) / close * 100
        g["database_high"] = high.cummax()
        g["ema_200_rising"] = g["ema_200"] > g["ema_200"].shift(20)
        g["away_10ema_pct"] = (close / g["ema_10"] - 1) * 100
        g["away_20ema_pct"] = (close / g["ema_20"] - 1) * 100
        g["away_50ema_pct"] = (close / g["ema_50"] - 1) * 100
        g["away_database_high_pct"] = (close / g["database_high"] - 1) * 100
        g["price_up_delivery_up"] = (close > prev_close) & (g["delivery_qty"] > g["avg_delivery_qty_20d"])
        g["fresh_200ema_reclaim"] = (prev_close <= g["ema_200"].shift(1)) & (close > g["ema_200"])
        g["ema_10_cross_200"] = (g["ema_10"] > g["ema_200"]) & (g["ema_10"].shift(1) <= g["ema_200"].shift(1))
        g["ema_stack_bullish"] = (g["ema_10"] > g["ema_20"]) & (g["ema_20"] > g["ema_50"]) & (g["ema_50"] > g["ema_100"]) & (g["ema_100"] > g["ema_200"])
        g["new_20d_high"] = close >= g["high_20d"].shift(1)
        g["new_50d_high"] = close >= g["high_50d"].shift(1)
        g["new_100d_high"] = close >= g["high_100d"].shift(1)
        g["ema_shakeout"] = ((low < g["ema_10"]) | (low < g["ema_20"])) & (close > g["ema_10"]) & (g["close_location_pct"] >= 60)
        g["shakeout"] = (low < g["low_10d"].shift(1)) & (close > g["low_10d"].shift(1)) & (g["close_location_pct"] >= 60)
        g["hammer"] = (g["lower_wick_pct"] >= 50) & (g["upper_wick_pct"] <= 20) & (g["close_location_pct"] >= 60)
        g["shooting_star"] = (g["upper_wick_pct"] >= 50) & (g["lower_wick_pct"] <= 20) & (g["close_location_pct"] <= 40) & (close > close.shift(10))
        g["bullish_engulfing"] = (close > g["open_price"]) & (prev_close < g["open_price"].shift(1)) & (close >= g["open_price"].shift(1)) & (g["open_price"] <= prev_close)
        g["inside_bar"] = (high < high.shift(1)) & (low > low.shift(1))
        g["nr7"] = day_range == day_range.rolling(7, min_periods=7).min()
        small_body = g["body_pct"] <= 35
        g["morning_star"] = (
            (close.shift(2) < g["open_price"].shift(2))
            & small_body.shift(1)
            & (close > g["open_price"])
            & (close > ((g["open_price"].shift(2) + close.shift(2)) / 2))
        )
        g["confirmed_morning_star"] = g["morning_star"] & (close.shift(2) < close.shift(7)) & (g["close_location_pct"] >= 60)
        g["confirmed_hammer"] = g["hammer"] & (close < close.shift(5)) & (g["close_location_pct"] >= 60)
        g["confirmed_bullish_engulfing"] = g["bullish_engulfing"] & (close.shift(1) < close.shift(6))
        g["confirmed_shooting_star"] = g["shooting_star"] & (close > close.shift(10)) & (g["away_database_high_pct"] >= -15)
        weekly_features = resampled_timeframe_features(g, "W-FRI")
        monthly_features = resampled_timeframe_features(g, "ME")
        if not weekly_features.empty:
            weekly = weekly_features["close_price"]
            weekly_ema = weekly.ewm(span=10, adjust=False, min_periods=10).mean()
            weekly_ema_200 = weekly.ewm(span=200, adjust=False, min_periods=10).mean()
            weekly_ma30 = weekly.rolling(30, min_periods=10).mean()
            weekly_10_cross_200 = (weekly_ema > weekly_ema_200) & (weekly_ema.shift(1) <= weekly_ema_200.shift(1))
            g["wema_10"] = weekly_ema.reindex(g["trade_date"], method="ffill").to_numpy()
            g["wema_200"] = weekly_ema_200.reindex(g["trade_date"], method="ffill").to_numpy()
            g["wema_10_cross_200"] = weekly_10_cross_200.reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
            g["wma_30"] = weekly_ma30.reindex(g["trade_date"], method="ffill").to_numpy()
            g["rsi_14_w"] = weekly_features["rsi_14"].reindex(g["trade_date"], method="ffill").to_numpy()
            g["confirmed_morning_star_w"] = weekly_features["confirmed_morning_star"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
            g["confirmed_shooting_star_w"] = weekly_features["confirmed_shooting_star"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
            g["bullish_rsi_divergence_w"] = weekly_features["bullish_rsi_divergence"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
            g["bearish_rsi_divergence_w"] = weekly_features["bearish_rsi_divergence"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
        else:
            g["wema_10"] = np.nan
            g["wema_200"] = np.nan
            g["wema_10_cross_200"] = False
            g["wma_30"] = np.nan
            g["rsi_14_w"] = np.nan
            g["confirmed_morning_star_w"] = False
            g["confirmed_shooting_star_w"] = False
            g["bullish_rsi_divergence_w"] = False
            g["bearish_rsi_divergence_w"] = False
        if not monthly_features.empty:
            monthly = monthly_features["close_price"]
            monthly_ema = monthly.ewm(span=10, adjust=False, min_periods=10).mean()
            monthly_ema_200 = monthly.ewm(span=200, adjust=False, min_periods=10).mean()
            monthly_10_cross_200 = (monthly_ema > monthly_ema_200) & (monthly_ema.shift(1) <= monthly_ema_200.shift(1))
            g["mema_10"] = monthly_ema.reindex(g["trade_date"], method="ffill").to_numpy()
            g["mema_200"] = monthly_ema_200.reindex(g["trade_date"], method="ffill").to_numpy()
            g["mema_10_cross_200"] = monthly_10_cross_200.reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
            g["rsi_14_m"] = monthly_features["rsi_14"].reindex(g["trade_date"], method="ffill").to_numpy()
            g["confirmed_morning_star_m"] = monthly_features["confirmed_morning_star"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
            g["confirmed_shooting_star_m"] = monthly_features["confirmed_shooting_star"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
            g["bullish_rsi_divergence_m"] = monthly_features["bullish_rsi_divergence"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
            g["bearish_rsi_divergence_m"] = monthly_features["bearish_rsi_divergence"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
        else:
            g["mema_10"] = np.nan
            g["mema_200"] = np.nan
            g["mema_10_cross_200"] = False
            g["rsi_14_m"] = np.nan
            g["confirmed_morning_star_m"] = False
            g["confirmed_shooting_star_m"] = False
            g["bullish_rsi_divergence_m"] = False
            g["bearish_rsi_divergence_m"] = False
        g["away_10wema_pct"] = (close / g["wema_10"] - 1) * 100
        g["away_10mema_pct"] = (close / g["mema_10"] - 1) * 100
        parts.append(g)
    indicators = pd.concat(parts, ignore_index=True)
    if "effective_date" in enrichment.columns:
        reference_rows = asof_reference(enrichment, indicators[["symbol", "trade_date"]])
        indicators["high_52w"] = reference_rows.get("high_52w", pd.Series(index=indicators.index, dtype=float)).to_numpy()
        indicators["low_52w"] = reference_rows.get("low_52w", pd.Series(index=indicators.index, dtype=float)).to_numpy()
    else:
        high52 = enrichment[["symbol", "high_52w"]].dropna().drop_duplicates("symbol", keep="last")
        indicators = indicators.merge(high52, on="symbol", how="left")
    indicators["away_52w_high_pct"] = (indicators["close_price"] / indicators["high_52w"] - 1) * 100
    if "effective_date" not in enrichment.columns:
        low52 = enrichment[["symbol", "low_52w"]].dropna().drop_duplicates("symbol", keep="last")
        indicators = indicators.merge(low52, on="symbol", how="left")
    indicators["away_52w_low_pct"] = (indicators["close_price"] / indicators["low_52w"] - 1) * 100
    close_by_symbol = indicators.groupby("symbol", sort=False)["close_price"]
    rs_latest_q = (indicators["close_price"] / close_by_symbol.shift(63) - 1) * 100
    rs_prior_q2 = (close_by_symbol.shift(63) / close_by_symbol.shift(126) - 1) * 100
    rs_prior_q3 = (close_by_symbol.shift(126) / close_by_symbol.shift(189) - 1) * 100
    rs_prior_q4 = (close_by_symbol.shift(189) / close_by_symbol.shift(252) - 1) * 100
    rs_score = (
        rs_latest_q.fillna(0) * 0.40
        + rs_prior_q2.fillna(0) * 0.20
        + rs_prior_q3.fillna(0) * 0.20
        + rs_prior_q4.fillna(0) * 0.20
    )
    indicators["rs_percentile"] = rs_score.groupby(indicators["trade_date"]).rank(pct=True) * 100

    # Alternative RS views (additive, primary rs_percentile unchanged for compatibility).
    # These help validate / compare. The current method is a weighted multi-quarter momentum rank vs peers on the day.
    # rs_1y_percentile = pure 252-day return rank percentile (classic 1-year relative strength).
    rs_1y = (indicators["close_price"] / close_by_symbol.shift(252) - 1) * 100
    indicators["rs_1y_percentile"] = rs_1y.groupby(indicators["trade_date"]).rank(pct=True) * 100

    # Simple recent strength (63d) percentile for quick views.
    rs_3m = (indicators["close_price"] / close_by_symbol.shift(63) - 1) * 100
    indicators["rs_3m_percentile"] = rs_3m.groupby(indicators["trade_date"]).rank(pct=True) * 100

    # NOTE on RS: All are cross-sectional daily ranks (0-100). Higher = stronger relative performance vs other stocks that day.
    # Primary rs_percentile uses the 40/20/20/20 quarterly decay. Use the alternatives in UI/queries for comparison or when you suspect the weighting.
    indicators["distance_to_high_pct"] = indicators[["away_database_high_pct", "away_52w_high_pct"]].abs().min(axis=1)
    indicators["trend_score"] = (
        (indicators["close_price"] > indicators["ema_50"]).astype(float) * 20
        + (indicators["close_price"] > indicators["ema_150"]).astype(float) * 20
        + (indicators["close_price"] > indicators["ema_200"]).astype(float) * 20
        + indicators["ema_200_rising"].fillna(False).astype(float) * 20
        + (indicators["rs_percentile"] >= 70).astype(float) * 20
    )
    indicators["contraction_score"] = (
        (indicators["range_5d_pct"] < indicators["range_10d_pct"]).astype(float) * 25
        + (indicators["range_10d_pct"] < indicators["range_20d_pct"]).astype(float) * 25
        + (indicators["atr_pct_avg_5d"] < indicators["atr_pct_avg_20d"]).astype(float) * 25
        + (indicators["atr_pct_avg_20d"] < indicators["atr_pct_avg_50d"]).astype(float) * 25
    )
    indicators["volume_dryup_pct"] = (1 - (indicators["avg_volume_5d"] / indicators["avg_volume_50d"])) * 100
    indicators["volume_dryup_score"] = (
        (indicators["avg_volume_5d"] < indicators["avg_volume_20d"]).astype(float) * 25
        + (indicators["avg_volume_5d"] < indicators["avg_volume_50d"]).astype(float) * 25
        + (indicators["rvol"] < 1).astype(float) * 25
        + (indicators["volume_dryup_pct"] > 20).astype(float) * 25
    )
    indicators["pivot_proximity_score"] = (100 - indicators["distance_to_high_pct"].clip(lower=0, upper=20) * 5).clip(lower=0, upper=100)
    indicators["vcp_score"] = (
        indicators["trend_score"] * 0.30
        + indicators["contraction_score"] * 0.30
        + indicators["volume_dryup_score"] * 0.25
        + indicators["pivot_proximity_score"] * 0.15
    )
    indicators["vcp_state"] = np.select(
        [
            indicators["close_price"] < indicators["ema_50"],
            (indicators["new_20d_high"]) & (indicators["rvol"] >= 1.5) & (indicators["trend_score"] >= 70),
            (indicators["vcp_score"] >= 70) & (indicators["distance_to_high_pct"] <= 5),
            indicators["vcp_score"] >= 55,
        ],
        ["Failed Breakout", "Breakout", "Near Pivot", "Building Base"],
        default="",
    )
    indicators["is_vcp"] = indicators["vcp_state"].isin(["Building Base", "Near Pivot", "Breakout"]) & (indicators["trend_score"] >= 60)
    indicators["near_52w_high"] = indicators["away_52w_high_pct"].between(-10, 0, inclusive="both")
    indicators["near_database_high"] = indicators["away_database_high_pct"].between(-10, 0, inclusive="both")
    indicators["near_high_tight"] = indicators["distance_to_high_pct"].le(5) & indicators["range_10d_pct"].le(indicators["range_50d_pct"] * 0.65)
    indicators["low_volatility_near_high"] = indicators["distance_to_high_pct"].le(10) & (indicators["atr_pct_avg_5d"] < indicators["atr_pct_avg_50d"])
    return indicators


def build_master(equity: pd.DataFrame, sector: pd.DataFrame, prices: pd.DataFrame, mcap: pd.DataFrame, bands: pd.DataFrame, pe: pd.DataFrame) -> pd.DataFrame:
    latest_price = prices.sort_values("trade_date").drop_duplicates("symbol", keep="last")
    master = equity.merge(sector, on="symbol", how="left")
    master = master.merge(latest_price[["symbol", "series", "trade_date", "close_price"]], on="symbol", how="left")
    master = master.rename(columns={"series": "latest_series", "trade_date": "latest_price_date", "close_price": "latest_close"})
    master = master.merge(mcap, on="symbol", how="left")
    master = master.merge(bands, on="symbol", how="left")
    master = master.merge(pe, on="symbol", how="left")
    return master


def build_enrichment(mcap: pd.DataFrame, bands: pd.DataFrame, pe: pd.DataFrame, high52: pd.DataFrame, bulk: pd.DataFrame, block: pd.DataFrame) -> pd.DataFrame:
    symbols = set(mcap.get("symbol", [])) | set(bands.get("symbol", [])) | set(pe.get("symbol", [])) | set(high52.get("symbol", []))
    enrichment = pd.DataFrame({"symbol": sorted(symbols)})
    for frame in [mcap, bands, pe, high52]:
        enrichment = enrichment.merge(frame, on="symbol", how="left")
    deal_flags = pd.concat([bulk, block], ignore_index=True)
    if not deal_flags.empty:
        flags = deal_flags.assign(has_deal=True).groupby("symbol", as_index=False)["has_deal"].max()
        enrichment = enrichment.merge(flags, on="symbol", how="left")
    if "has_deal" not in enrichment.columns:
        enrichment["has_deal"] = False
    else:
        enrichment["has_deal"] = enrichment["has_deal"].fillna(False)
    return enrichment


def enrich_deals(deals: pd.DataFrame, prices: pd.DataFrame, indicators: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    if deals.empty:
        return deals
    price_cols = ["symbol", "trade_date", "close_price", "volume", "turnover_cr"]
    indicator_cols = ["symbol", "trade_date", "rs_percentile", "vcp_score", "vcp_state", "is_vcp", "near_52w_high", "near_database_high", "ema_stack_bullish", "away_10ema_pct", "away_52w_high_pct"]
    master_cols = ["symbol", "broad_sector", "sector", "broad_industry", "industry", "market_cap_cr", "band"]
    out = deals.merge(prices[price_cols], on=["symbol", "trade_date"], how="left")
    out = out.merge(indicators[indicator_cols], on=["symbol", "trade_date"], how="left")
    out = out.merge(master[master_cols], on="symbol", how="left")
    out["deal_pct_volume"] = out["quantity"] / out["volume"] * 100
    out["deal_price_vs_close_pct"] = (out["price"] / out["close_price"] - 1) * 100
    out["client_symbol_key"] = out["deal_type"].astype(str) + "|" + out["symbol"].astype(str) + "|" + out["client_name"].astype(str) + "|" + out["side"].astype(str)
    out["repeated_client_count"] = out.groupby("client_symbol_key")["trade_date"].transform("nunique")
    out = out.drop(columns=["client_symbol_key"])
    return out


def build_breadth_daily(indicators: pd.DataFrame) -> pd.DataFrame:
    df = indicators.copy()
    df["adv_volume"] = np.where(df["close_price"] > df["prev_close"], df["volume"], 0)
    df["decl_volume"] = np.where(df["close_price"] < df["prev_close"], df["volume"], 0)
    grouped = df.groupby("trade_date").apply(
        lambda g: pd.Series(
            {
                "stocks": g["symbol"].nunique(),
                "advancers": (g["close_price"] > g["prev_close"]).sum(),
                "decliners": (g["close_price"] < g["prev_close"]).sum(),
                "unchanged": (g["close_price"] == g["prev_close"]).sum(),
                "advance_pct": (g["close_price"] > g["prev_close"]).mean() * 100,
                "advance_volume_pct": g["adv_volume"].sum() / max((g["adv_volume"].sum() + g["decl_volume"].sum()), 1) * 100,
                "above_10ema_pct": (g["close_price"] > g["ema_10"]).mean() * 100,
                "above_20ema_pct": (g["close_price"] > g["ema_20"]).mean() * 100,
                "above_50ema_pct": (g["close_price"] > g["ema_50"]).mean() * 100,
                "above_100ema_pct": (g["close_price"] > g["ema_100"]).mean() * 100,
                "above_200ema_pct": (g["close_price"] > g["ema_200"]).mean() * 100,
                "new_20d_highs": g["new_20d_high"].sum(),
                "new_50d_highs": g["new_50d_high"].sum(),
                "new_100d_highs": g["new_100d_high"].sum(),
                "near_52w_highs": g["near_52w_high"].sum(),
                "vcp_candidates": g["is_vcp"].sum(),
            }
        ),
        include_groups=False,
    ).reset_index()
    grouped = grouped.sort_values("trade_date")
    grouped["advance_pct_5d_avg"] = grouped["advance_pct"].rolling(5, min_periods=3).mean()
    grouped["advance_pct_20d_avg"] = grouped["advance_pct"].rolling(20, min_periods=5).mean()
    grouped["above_50ema_5d_change"] = grouped["above_50ema_pct"] - grouped["above_50ema_pct"].shift(5)
    grouped["above_200ema_20d_change"] = grouped["above_200ema_pct"] - grouped["above_200ema_pct"].shift(20)
    grouped["breadth_state"] = np.select(
        [
            (grouped["advance_pct_5d_avg"] >= 55) & (grouped["above_50ema_5d_change"] > 3),
            (grouped["advance_pct_5d_avg"] <= 45) & (grouped["above_50ema_5d_change"] < -3),
            (grouped["above_50ema_pct"] >= 60) & (grouped["above_200ema_pct"] >= 45),
            (grouped["advance_pct"] > 55) & (grouped["above_50ema_5d_change"] < 0),
        ],
        ["Improving", "Weakening", "Broad Participation", "Diverging"],
        default="Neutral",
    )
    return grouped


def build_sector_rotation(indicators: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    base = indicators.merge(
        master[["symbol", "broad_sector", "sector", "broad_industry", "industry"]],
        on="symbol",
        how="left",
    )
    frames = []
    levels = {
        "Broad Sector": "broad_sector",
        "Sector": "sector",
        "Broad Industry": "broad_industry",
        "Industry": "industry",
    }
    for level_name, col in levels.items():
        d = base.dropna(subset=[col]).copy()
        d = d[d[col].astype(str).str.strip() != ""]
        if d.empty:
            continue
        grouped = d.groupby(["trade_date", col]).apply(
            lambda g: pd.Series(
                {
                    "stocks": g["symbol"].nunique(),
                    "return_5d_pct": g["return_5d_pct"].mean(),
                    "return_1m_pct": g["return_1m_pct"].mean(),
                    "return_3m_pct": g["return_3m_pct"].mean(),
                    "rs_percentile": g["rs_percentile"].mean(),
                    "above_10ema_pct": (g["close_price"] > g["ema_10"]).mean() * 100,
                    "above_50ema_pct": (g["close_price"] > g["ema_50"]).mean() * 100,
                    "above_200ema_pct": (g["close_price"] > g["ema_200"]).mean() * 100,
                    "near_52w_highs": g["near_52w_high"].sum(),
                    "vcp_candidates": g["is_vcp"].sum(),
                    "turnover_cr": g["turnover_cr"].sum(),
                }
            ),
            include_groups=False,
        ).reset_index().rename(columns={col: "group_name"})
        grouped["level"] = level_name
        grouped["rotation_score"] = (
            grouped["rs_percentile"].fillna(0) * 0.40
            + grouped["above_50ema_pct"].fillna(0) * 0.25
            + grouped["above_200ema_pct"].fillna(0) * 0.20
            + grouped["return_1m_pct"].fillna(0).clip(-20, 20) * 0.75
        )
        grouped["rotation_rank"] = grouped.groupby("trade_date")["rotation_score"].rank(ascending=False, method="min")
        grouped = grouped.sort_values(["group_name", "trade_date"])
        grouped["rank_change_5d"] = grouped.groupby("group_name")["rotation_rank"].shift(5) - grouped["rotation_rank"]
        grouped["rank_change_20d"] = grouped.groupby("group_name")["rotation_rank"].shift(20) - grouped["rotation_rank"]
        grouped["score_change_5d"] = grouped.groupby("group_name")["rotation_score"].diff(5)
        grouped["turnover_1d_cr"] = grouped["turnover_cr"]
        grouped["turnover_5d_cr"] = grouped.groupby("group_name")["turnover_cr"].transform(lambda s: s.rolling(5, min_periods=1).sum())
        grouped["turnover_20d_cr"] = grouped.groupby("group_name")["turnover_cr"].transform(lambda s: s.rolling(20, min_periods=1).sum())
        grouped["rotation_state"] = np.select(
            [
                (grouped["rotation_rank"] <= 5) & (grouped["score_change_5d"] >= 0),
                (grouped["rank_change_5d"] >= 5) & (grouped["score_change_5d"] > 0),
                (grouped["rank_change_5d"] >= 2) & (grouped["score_change_5d"] > 0),
                (grouped["rotation_rank"] <= 8) & (grouped["score_change_5d"] < 0),
                (grouped["rotation_rank"] > 8) & (grouped["score_change_5d"] <= 0),
            ],
            ["Leading", "Emerging", "Improving", "Weakening", "Lagging"],
            default="Neutral",
        )
        frames.append(grouped)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def make_screener_results(indicators: pd.DataFrame, master: pd.DataFrame, deals: pd.DataFrame | None = None, sector_rotation: pd.DataFrame | None = None) -> pd.DataFrame:
    latest_date = indicators["trade_date"].max()
    latest = indicators[indicators["trade_date"] == latest_date].merge(
        master[["symbol", "market_cap_cr", "band", "broad_sector", "sector", "broad_industry", "industry"]],
        on="symbol",
        how="left",
    )
    latest_deals = pd.DataFrame(columns=["symbol", "latest_buy_deal_value_cr", "latest_sell_deal_value_cr", "latest_deal_date"])
    if deals is not None and not deals.empty:
        latest_deals = deals[deals["trade_date"] >= latest_date - pd.Timedelta(days=20)].groupby("symbol").apply(
            lambda g: pd.Series(
                {
                    "latest_buy_deal_value_cr": g.loc[g["side"] == "BUY", "deal_value_cr"].sum(),
                    "latest_sell_deal_value_cr": g.loc[g["side"] == "SELL", "deal_value_cr"].sum(),
                    "latest_deal_date": g["trade_date"].max(),
                    "repeated_client_count": g["repeated_client_count"].max() if "repeated_client_count" in g.columns else 1,
                }
            ),
            include_groups=False,
        ).reset_index()
    latest = latest.merge(latest_deals, on="symbol", how="left")
    for col in ["latest_buy_deal_value_cr", "latest_sell_deal_value_cr", "repeated_client_count"]:
        latest[col] = latest[col].fillna(0)
    rows = []
    definitions = {
        "Near 10 EMA": ("% Away from 10 EMA between 0% and 2%", latest["away_10ema_pct"].between(0, 2, inclusive="both")),
        "Near 10 WEMA": ("OHLC above 10 WEMA and close 0%-5% above 10 WEMA", (latest["low_price"] >= latest["wema_10"]) & latest["away_10wema_pct"].between(0, 5, inclusive="both")),
        "Near 10 MEMA": ("OHLC above 10 MEMA and close 0%-5% above 10 MEMA", (latest["low_price"] >= latest["mema_10"]) & latest["away_10mema_pct"].between(0, 5, inclusive="both")),
        "Near 52W High": ("Within 10% of adjusted 52W high", latest["near_52w_high"].fillna(False)),
        "Near Database High": ("Within 10% of highest price in loaded database", latest["near_database_high"].fillna(False)),
        "Near High + Low Volatility": ("Within 10% of high and short ATR below long ATR", latest["low_volatility_near_high"].fillna(False)),
        "Fresh 200 EMA Reclaim": ("Previous close below 200 EMA and latest close above 200 EMA", latest["fresh_200ema_reclaim"].fillna(False)),
        "EMA Stack Bullish": ("10 EMA > 20 EMA > 50 EMA > 100 EMA > 200 EMA", latest["ema_stack_bullish"].fillna(False)),
        "New 20D High": ("Close at or above prior 20D high", latest["new_20d_high"].fillna(False)),
        "New 50D High": ("Close at or above prior 50D high", latest["new_50d_high"].fillna(False)),
        "New 100D High": ("Close at or above prior 100D high", latest["new_100d_high"].fillna(False)),
        "10 EMA Cross 200 EMA - Today": ("10 EMA crossed above 200 EMA on the latest trading day", latest["ema_10_cross_200"].fillna(False)),
        "10 WEMA Cross 200 WEMA - Today": ("10 WEMA crossed above 200 WEMA on the latest weekly update", latest["wema_10_cross_200"].fillna(False)),
        "10 MEMA Cross 200 MEMA - Today": ("10 MEMA crossed above 200 MEMA on the latest monthly update", latest["mema_10_cross_200"].fillna(False)),
        "Shakeout": ("Low breaks 10D support but closes back strong", latest["shakeout"].fillna(False)),
        "EMA Shakeout": ("Low dips below 10/20 EMA and closes back above 10 EMA", latest["ema_shakeout"].fillna(False)),
        "Morning Star D": ("Confirmed daily morning-star style reversal after weakness", latest["confirmed_morning_star"].fillna(False)),
        "Morning Star W": ("Confirmed weekly morning-star style reversal after weakness", latest["confirmed_morning_star_w"].fillna(False)),
        "Morning Star M": ("Confirmed monthly morning-star style reversal; lower confidence with short history", latest["confirmed_morning_star_m"].fillna(False)),
        "Shooting Star D": ("Daily long upper wick after uptrend", latest["confirmed_shooting_star"].fillna(False)),
        "Shooting Star W": ("Weekly long upper wick after uptrend", latest["confirmed_shooting_star_w"].fillna(False)),
        "Shooting Star M": ("Monthly long upper wick after uptrend; lower confidence with short history", latest["confirmed_shooting_star_m"].fillna(False)),
        "Bull RSI Div D": ("Daily price lower low with RSI higher low candidate", latest["bullish_rsi_divergence"].fillna(False)),
        "Bear RSI Div D": ("Daily price higher high with RSI lower high candidate", latest["bearish_rsi_divergence"].fillna(False)),
        "Bull RSI Div W": ("Weekly price lower low with RSI higher low candidate", latest["bullish_rsi_divergence_w"].fillna(False)),
        "Bear RSI Div W": ("Weekly price higher high with RSI lower high candidate", latest["bearish_rsi_divergence_w"].fillna(False)),
        "Bull RSI Div M": ("Monthly price lower low with RSI higher low candidate", latest["bullish_rsi_divergence_m"].fillna(False)),
        "Bear RSI Div M": ("Monthly price higher high with RSI lower high candidate", latest["bearish_rsi_divergence_m"].fillna(False)),
        "Hammer": ("Confirmed hammer after pullback", latest["confirmed_hammer"].fillna(False)),
        "Bullish Engulfing": ("Bullish engulfing after short weakness", latest["confirmed_bullish_engulfing"].fillna(False)),
        "Inside Bar": ("Inside bar compression", latest["inside_bar"].fillna(False)),
        "NR7": ("Narrowest range in 7 sessions", latest["nr7"].fillna(False)),
        "RVOL Spike": ("RVOL >= 2", latest["rvol"] >= 2),
        "Delivery Spike": ("Delivery quantity > 2x 20D average", latest["delivery_spike"].fillna(False)),
        "Price Up + Delivery Up": ("Price up with delivery quantity above 20D average", latest["price_up_delivery_up"].fillna(False)),
        "Top RS Stocks": ("RS percentile >= 90", latest["rs_percentile"] >= 90),
        "Strong Sector + Strong Stock": ("RS percentile >= 85 and bullish EMA stack", (latest["rs_percentile"] >= 85) & latest["ema_stack_bullish"].fillna(False)),
        "BUY Deal + Near High": ("Recent BUY deal and near 52W/database high", (latest["latest_buy_deal_value_cr"] > 0) & (latest["near_52w_high"].fillna(False) | latest["near_database_high"].fillna(False))),
        "SELL Deal + Weak Setup": ("Recent SELL deal while below 50 EMA or RS < 40", (latest["latest_sell_deal_value_cr"] > 0) & ((latest["close_price"] < latest["ema_50"]) | (latest["rs_percentile"] < 40))),
        "Repeated Buyer + Accumulation": ("Repeated buyer plus price/delivery accumulation", (latest["repeated_client_count"] >= 2) & (latest["latest_buy_deal_value_cr"] > 0) & latest["price_up_delivery_up"].fillna(False)),
    }
    cols = [
        "symbol", "trade_date", "close_price", "volume", "turnover_cr", "market_cap_cr", "band",
        "avg_volume_20d", "ema_10_cross_200", "rsi_14", "rsi_14_w", "rsi_14_m",
        "away_10ema_pct", "away_10wema_pct", "away_10mema_pct", "away_52w_high_pct",
        "away_52w_low_pct", "away_database_high_pct", "distance_to_high_pct", "rvol", "rs_percentile",
        "vcp_score", "trend_score", "contraction_score", "volume_dryup_score",
        "pivot_proximity_score", "vcp_state", "latest_buy_deal_value_cr", "latest_sell_deal_value_cr",
        "broad_sector", "sector", "broad_industry", "industry",
    ]
    for name, (rule_summary, mask) in definitions.items():
        frame = latest.loc[mask, cols].copy()
        frame.insert(0, "screener_name", name)
        frame.insert(1, "rule_summary", rule_summary)
        rows.append(frame)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["screener_name", *cols])


def write_database(
    prices: pd.DataFrame,
    master: pd.DataFrame,
    enrichment: pd.DataFrame,
    indicators: pd.DataFrame,
    deals: pd.DataFrame,
    breadth_daily: pd.DataFrame,
    sector_rotation: pd.DataFrame,
    screener_results: pd.DataFrame,
) -> None:
    temp_db = DB_PATH.with_suffix(".tmp.duckdb")
    if temp_db.exists():
        temp_db.unlink()
    con = duckdb.connect(str(temp_db))
    for name, frame in {
        "prices_daily": prices,
        "stocks_master": master,
        "daily_enrichment": enrichment,
        "indicators_daily": indicators,
        "deals": deals,
        "breadth_daily": breadth_daily,
        "sector_rotation": sector_rotation,
        "screener_results": screener_results,
    }.items():
        con.register(f"{name}_df", frame)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM {name}_df")
    con.execute("CREATE INDEX idx_prices_symbol_date ON prices_daily(symbol, trade_date)")
    con.execute("CREATE INDEX idx_indicators_symbol_date ON indicators_daily(symbol, trade_date)")
    con.execute("CREATE INDEX idx_deals_symbol_date ON deals(symbol, trade_date)")
    con.execute("CREATE INDEX idx_breadth_date ON breadth_daily(trade_date)")
    con.execute("CREATE INDEX idx_sector_rotation ON sector_rotation(level, group_name, trade_date)")
    con.execute("CREATE INDEX idx_screener_name ON screener_results(screener_name)")
    if DB_PATH.exists():
        try:
            old_con = duckdb.connect(str(DB_PATH), read_only=True)
            for user_table in ("trade_journal", "watchlist_candidates"):
                exists = old_con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [user_table]).fetchone()[0]
                if exists:
                    user_rows = old_con.execute(f"SELECT * FROM {user_table}").fetchdf()
                    con.register(f"{user_table}_df", user_rows)
                    con.execute(f"CREATE TABLE {user_table} AS SELECT * FROM {user_table}_df")
            old_con.close()
        except Exception as exc:
            print(f"Warning: could not preserve trade_journal: {exc}")
    con.close()
    if DB_PATH.exists():
        backup = DB_PATH.with_suffix(".backup.duckdb")
        shutil.copy2(DB_PATH, backup)
        DB_PATH.unlink()
    temp_db.rename(DB_PATH)
    # Decision tables are explicit runtime migrations and materialized only after
    # the accepted replacement database has been atomically installed.
    try:
        from materialize_decision_tables import materialize_decision_tables

        materialize_decision_tables(DB_PATH)
    except Exception as exc:
        print(f"Warning: decision tables were not materialized: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the MarketPulse DuckDB database. This ALWAYS performs a FULL rebuild from ALL available price history (archive + daily). Use this directly for catch-up after missed daily uploads: drop any missed bhavcopy / deal / reference files into Input/daily/ (even older dated ones) then run this script. The normal daily_update.bat is stricter for day-to-day use.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if not args.quiet:
        print("Starting full database rebuild. This may take 5-10 minutes depending on archive size.")
    ensure_folders()
    if not args.quiet:
        print("1/8: Loading equity universe and sector mapping...")
    equity = read_equity_symbols()
    universe = set(equity["symbol"])
    sector = read_sector()
    if not args.quiet:
        print("2/8: Reading historical price files (archive + daily)...")
    prices = build_prices(universe)
    if not args.quiet:
        print("3/8: Reading market cap, price band, PE, and 52-week reference files...")
    mcap = read_market_cap()
    bands = read_price_band()
    pe = read_pe()
    high52 = read_52_week()
    if not args.quiet:
        print("4/8: Building enrichment tables and stock master list...")
    enrichment = build_enrichment(mcap, bands, pe, high52, pd.DataFrame(), pd.DataFrame())
    master = build_master(equity, sector, prices, mcap, bands, pe)
    if not args.quiet:
        print("5/8: Calculating indicators...")
    reference_history = load_reference_history(ROOT_DIR)
    indicators = calc_indicators(prices, reference_history if not reference_history.empty else enrichment)
    if not args.quiet:
        print("6/8: Reading and enriching deal flow...")
    deals_raw = read_all_deals()
    deals = enrich_deals(deals_raw, prices, indicators, master)
    latest_deals = deals[deals["trade_date"] == deals["trade_date"].max()] if not deals.empty else deals
    if not args.quiet:
        print("7/8: Building breadth and sector rotation metrics...")
    enrichment = build_enrichment(mcap, bands, pe, high52, latest_deals, pd.DataFrame())
    breadth_daily = build_breadth_daily(indicators)
    sector_rotation = build_sector_rotation(indicators, master)
    screener_results = make_screener_results(indicators, master, deals, sector_rotation)
    if not args.quiet:
        print("8/8: Writing database file...")
    write_database(prices, master, enrichment, indicators, deals, breadth_daily, sector_rotation, screener_results)
    if not args.quiet:
        print("MarketPulse database built successfully (FULL history rebuild).")
        print(f"Database: {DB_PATH}")
        print(f"Stocks in master list: {len(master):,}")
        print(f"Price rows: {len(prices):,}")
        print(f"Deal rows: {len(deals):,}")
        print(f"Date range: {prices['trade_date'].min().date()} to {prices['trade_date'].max().date()}")
        print("Tip: For normal daily use prefer Update_MarketPulse.bat. For catch-up after missed uploads, place missed files in Input/daily/ and run this script (or python -m Scripts.build_database).")

if __name__ == "__main__":
    main()
