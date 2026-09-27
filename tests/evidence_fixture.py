"""Synthetic market data for evidence-engine tests (no live DB)."""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

N_SESSIONS = 330
SESSIONS = pd.bdate_range("2024-01-01", periods=N_SESSIONS)


def _symbol_frame(symbol: str, seed: int, jump_days: tuple[int, ...] = (), band: float = 10.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0008, 0.018, N_SESSIONS)
    for d in jump_days:
        ret[d] = band / 100 * 0.999 + 0.0005  # closes at the upper band
    close = 200 * np.exp(np.cumsum(ret))
    prev = np.r_[close[0] / (1 + ret[0]), close[:-1]]
    high = np.maximum(close, prev) * (1 + rng.uniform(0, 0.01, N_SESSIONS))
    for d in jump_days:
        high[d] = prev[d] * (1 + band / 100)
    low = np.minimum(close, prev) * (1 - rng.uniform(0, 0.015, N_SESSIONS))
    opn = prev * (1 + rng.normal(0, 0.004, N_SESSIONS))
    opn = np.clip(opn, low, high)
    vol = rng.uniform(2e5, 8e5, N_SESSIONS)
    df = pd.DataFrame({"symbol": symbol, "series": "EQ", "trade_date": SESSIONS, "prev_close": prev,
                       "open_price": opn, "high_price": high, "low_price": low, "close_price": close, "volume": vol})
    c, h, lo_ = df["close_price"], df["high_price"], df["low_price"]
    for span in (10, 20, 50, 200):
        df[f"ema_{span}"] = c.ewm(span=span, adjust=False).mean()
    v = df["volume"]
    df["avg_volume_10d"] = v.rolling(10, min_periods=1).mean()
    df["avg_volume_20d"] = v.rolling(20, min_periods=1).mean()
    df["avg_volume_50d"] = v.rolling(50, min_periods=1).mean()
    df["rvol"] = v / v.shift(1).rolling(20, min_periods=1).mean()
    df["turnover_cr"] = v * c / 1e7
    df["avg_traded_value_cr_20d"] = df["turnover_cr"].rolling(20, min_periods=1).mean()
    df["delivery_pct"] = rng.uniform(30, 70, N_SESSIONS)
    df["avg_delivery_pct_20d"] = df["delivery_pct"].rolling(20, min_periods=1).mean()
    df["delivery_spike"] = df["delivery_pct"] > 65
    tr = (h - lo_) / c * 100
    df["atr_pct"] = tr.rolling(14, min_periods=1).mean()
    df["atr_pct_avg_50d"] = df["atr_pct"].rolling(50, min_periods=1).mean()
    for w in (10, 20, 50):
        df[f"range_{w}d_pct"] = (h.rolling(w, min_periods=1).max() / lo_.rolling(w, min_periods=1).min() - 1) * 100
    df["high_20d"] = h.rolling(20, min_periods=1).max()
    df["low_10d"] = lo_.rolling(10, min_periods=1).min()
    df["high_252d"] = h.rolling(252, min_periods=1).max()
    df["low_252d"] = lo_.rolling(252, min_periods=1).min()
    df["away_52w_high_pct"] = (c / df["high_252d"] - 1) * 100
    df["rs_percentile"] = np.clip(50 + (c / c.shift(60) - 1).fillna(0) * 200, 1, 99)
    df["trend_template_pass"] = (c > df["ema_50"]) & (df["ema_50"] > df["ema_200"])
    df["return_1m_pct"] = (c / c.shift(21) - 1) * 100
    df["return_3m_pct"] = (c / c.shift(63) - 1) * 100
    return df


SYMBOLS = {  # symbol: (seed, jump days, industry, mcap at the end, band)
    "JUMPA": (1, (200, 201, 202), "Widgets", 5000.0, 10.0),
    "JUMPB": (2, (260,), "Widgets", 4000.0, 20.0),
    "TINY": (3, (220,), "Widgets", 300.0, 10.0),
    "PEERA": (4, (), "Widgets", 4500.0, 20.0),
    "PEERB": (5, (), "Widgets", 5200.0, 20.0),
    "PEERC": (6, (), "Widgets", 6000.0, 20.0),
    "OTHERA": (7, (), "Gadgets", 8000.0, 20.0),
    "OTHERB": (8, (), "Gadgets", 9000.0, 20.0),
}


def indicators() -> pd.DataFrame:
    return pd.concat([_symbol_frame(s, seed, jumps, band) for s, (seed, jumps, _i, _m, band) in SYMBOLS.items()],
                     ignore_index=True)


def master() -> pd.DataFrame:
    rows = []
    for s, (_seed, _j, ind, mcap, band) in SYMBOLS.items():
        rows.append({"symbol": s, "security_name": f"{s} LTD", "broad_sector": "Industrials", "sector": "Capital Goods",
                     "broad_industry": ind + " & Co", "industry": ind, "market_cap_cr": mcap,
                     "market_cap_date": SESSIONS[-1], "band": band, "band_remarks": None})
    return pd.DataFrame(rows)


def index_daily() -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-02", SESSIONS[-1])
    rng = np.random.default_rng(99)
    out = []
    for name, base, vol in (("NIFTY MIDSML 400", 15000, 0.01), ("Nifty 50", 22000, 0.008), ("India VIX", 14, 0.04)):
        close = base * np.exp(np.cumsum(rng.normal(0.0003, vol, len(dates))))
        out.append(pd.DataFrame({"trade_date": dates, "index_name": name, "close_price": close, "turnover_cr": 1e4}))
    return pd.concat(out, ignore_index=True)


def breadth(ind: pd.DataFrame) -> pd.DataFrame:
    g = ind.assign(a10=ind["close_price"] > ind["ema_10"], a50=ind["close_price"] > ind["ema_50"],
                   a200=ind["close_price"] > ind["ema_200"], adv=ind["close_price"] > ind["prev_close"]).groupby("trade_date")
    b = pd.DataFrame({"above_10ema_pct": g["a10"].mean() * 100, "above_50ema_pct": g["a50"].mean() * 100,
                      "above_200ema_pct": g["a200"].mean() * 100, "advance_pct": g["adv"].mean() * 100}).reset_index()
    b["advance_pct_5d_avg"] = b["advance_pct"].rolling(5, min_periods=1).mean()
    b["advance_pct_20d_avg"] = b["advance_pct"].rolling(20, min_periods=1).mean()
    b["breadth_state"] = np.where(b["above_50ema_pct"] > 60, "Improving", np.where(b["above_50ema_pct"] < 40, "Weakening", "Neutral"))
    return b


def regime(ind: pd.DataFrame) -> pd.DataFrame:
    b = breadth(ind)
    v = np.select([b["above_50ema_pct"] >= 75, b["above_50ema_pct"] >= 55, b["above_50ema_pct"] >= 40,
                   b["above_50ema_pct"] >= 25], ["Favourable", "Constructive", "Mixed", "Weak"], "Danger")
    return pd.DataFrame({"trade_date": b["trade_date"], "verdict": v})


def build_db(path: Path, with_regime: bool = True) -> Path:
    ind = indicators()
    con = duckdb.connect(str(path))
    try:
        for name, df in (("indicators_daily", ind), ("prices_daily", ind[["symbol", "series", "trade_date", "prev_close",
                                                                           "open_price", "high_price", "low_price",
                                                                           "close_price", "volume"]]),
                         ("stocks_master", master()), ("index_daily", index_daily()), ("breadth_daily", breadth(ind))):
            con.register("_df", df)
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM _df")
            con.unregister("_df")
        if with_regime:
            con.register("_df", regime(ind))
            con.execute("CREATE TABLE regime_daily AS SELECT * FROM _df")
            con.unregister("_df")
    finally:
        con.close()
    return path
