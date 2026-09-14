"""Stock-vs-mapped-index and index-vs-bench excess RS."""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from true_rs import (
    BENCH_MIDSML400,
    BENCH_NIFTY50,
    excess_vs_index,
    index_closes,
)
from index_constituents import (
    SECTOR_INDEX_COLUMNS,
    load_membership_csv,
    map_symbols_to_indices,
)

try:
    from thematic_engine import CANONICAL_44_INDICES
except ImportError:  # pragma: no cover
    from App.thematic_engine import CANONICAL_44_INDICES  # type: ignore

INDEX_BENCH_RS_COLUMNS = (
    "rs_vs_nifty50_21d",
    "rs_vs_nifty50_63d",
    "rs_vs_midsml400_21d",
    "rs_vs_midsml400_63d",
)


def attach_sector_index_rs(
    indicators: pd.DataFrame,
    index_daily: pd.DataFrame,
    membership: pd.DataFrame | None = None,
    master: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Add sector_index_name + rs_vs_sector_index_21d/63d."""
    out = indicators.copy()
    for col in SECTOR_INDEX_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan if col != "sector_index_name" else None

    mem = membership if membership is not None else load_membership_csv()
    out["sector_index_name"] = map_symbols_to_indices(out["symbol"], mem, master)

    # Compute excess per mapped index group
    out["rs_vs_sector_index_21d"] = np.nan
    out["rs_vs_sector_index_63d"] = np.nan

    stock = out[["symbol", "trade_date", "close_price", "sector_index_name"]].copy()
    for index_name, grp_idx in stock.groupby("sector_index_name", dropna=True).groups.items():
        if index_name is None or (isinstance(index_name, float) and np.isnan(index_name)):
            continue
        idx = index_closes(index_daily, str(index_name))
        if idx.empty:
            continue
        sub = stock.loc[grp_idx, ["symbol", "trade_date", "close_price"]]
        for sessions, col in ((21, "rs_vs_sector_index_21d"), (63, "rs_vs_sector_index_63d")):
            excess = excess_vs_index(sub, idx, sessions)
            out.loc[grp_idx, col] = excess.to_numpy()
    return out


def compute_index_bench_rs(
    index_daily: pd.DataFrame,
    *,
    index_names: Iterable[str] | None = None,
    sessions: Iterable[int] = (21, 63),
) -> pd.DataFrame:
    """Excess of each canonical index vs Nifty50 and MidSml400 for every trade_date."""
    names = list(index_names or CANONICAL_44_INDICES.keys())
    nifty = index_closes(index_daily, BENCH_NIFTY50)
    midsml = index_closes(index_daily, BENCH_MIDSML400)
    frames = []
    for name in names:
        leg = index_daily.loc[index_daily["index_name"] == name, ["trade_date", "close_price"]].copy()
        if leg.empty:
            continue
        leg = leg.sort_values("trade_date").drop_duplicates("trade_date")
        # treat as single-symbol series for excess_vs_index
        stockish = leg.assign(symbol=name)
        row = {"mp_index_name": name, "trade_date": leg["trade_date"].to_numpy()}
        base = pd.DataFrame({"trade_date": leg["trade_date"]})
        base["mp_index_name"] = name
        for sessions_n in sessions:
            if not nifty.empty:
                base[f"rs_vs_nifty50_{sessions_n}d"] = excess_vs_index(
                    stockish[["symbol", "trade_date", "close_price"]], nifty, sessions_n
                ).to_numpy()
            else:
                base[f"rs_vs_nifty50_{sessions_n}d"] = np.nan
            if not midsml.empty:
                base[f"rs_vs_midsml400_{sessions_n}d"] = excess_vs_index(
                    stockish[["symbol", "trade_date", "close_price"]], midsml, sessions_n
                ).to_numpy()
            else:
                base[f"rs_vs_midsml400_{sessions_n}d"] = np.nan
        frames.append(base)
    if not frames:
        cols = ["mp_index_name", "trade_date", *INDEX_BENCH_RS_COLUMNS]
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True)
