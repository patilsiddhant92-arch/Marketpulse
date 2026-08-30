"""Deterministic, point-in-time sector and industry metrics."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


LEVEL_COLUMNS = {
    "Broad Sector": "broad_sector",
    "Sector": "sector",
    "Broad Industry": "broad_industry",
    "Industry": "industry",
}


def _as_of_market_cap(indicators: pd.DataFrame, reference: pd.DataFrame) -> pd.Series:
    if reference is None or reference.empty or "market_cap_cr" not in reference.columns:
        return pd.Series(np.nan, index=indicators.index, dtype=float)

    left = indicators[["symbol", "trade_date"]].copy()
    left["trade_date"] = pd.to_datetime(left["trade_date"])
    left["_row"] = np.arange(len(left))
    right = reference[["symbol", "effective_date", "market_cap_cr"]].copy()
    right["effective_date"] = pd.to_datetime(right["effective_date"])
    right["market_cap_cr"] = pd.to_numeric(right["market_cap_cr"], errors="coerce")
    left = left.sort_values(["trade_date", "symbol"])
    right = right.sort_values(["effective_date", "symbol"])
    merged = pd.merge_asof(
        left,
        right,
        left_on="trade_date",
        right_on="effective_date",
        by="symbol",
        direction="backward",
    ).sort_values("_row")
    return merged["market_cap_cr"].set_axis(indicators.index)


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    values = pd.to_numeric(values, errors="coerce")
    weights = pd.to_numeric(weights, errors="coerce").fillna(0)
    valid = values.notna()
    if not valid.any():
        return float("nan")
    values = values[valid]
    weights = weights[valid]
    if weights.sum() <= 0:
        return float(values.mean())
    return float((values * weights).sum() / weights.sum())


def _benchmark_returns(index_daily: pd.DataFrame, dates: Iterable[pd.Timestamp]) -> pd.DataFrame:
    if index_daily is None or index_daily.empty:
        return pd.DataFrame(columns=["trade_date", "bench_21d", "bench_63d"])
    frame = index_daily.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    names = frame.get("index_name", pd.Series("", index=frame.index)).astype(str).str.upper()
    nifty = frame[names.str.contains("NIFTY 50", na=False)].copy()
    if nifty.empty:
        return pd.DataFrame(columns=["trade_date", "bench_21d", "bench_63d"])
    for days, column in ((21, "bench_21d"), (63, "bench_63d")):
        source = f"return_{days}d_pct"
        if source in nifty.columns:
            nifty[column] = pd.to_numeric(nifty[source], errors="coerce")
        elif "close_price" in nifty.columns:
            close = pd.to_numeric(nifty["close_price"], errors="coerce")
            nifty[column] = (close / close.shift(days) - 1) * 100
        else:
            nifty[column] = np.nan
    return nifty[["trade_date", "bench_21d", "bench_63d"]].drop_duplicates("trade_date")


def _prepare_deal_metrics(
    deals: pd.DataFrame | None,
    as_of_dates: Iterable[pd.Timestamp | str],
) -> pd.DataFrame:
    """Precompute 30-day deal totals once per symbol and target date.

    The previous implementation copied and regrouped the entire deal table
    inside every taxonomy/date group.  That made a full rebuild effectively
    quadratic in the number of sector groups.  This cache performs the same
    ``(as_of - 30 days, as_of]`` window once per target session, after which
    the main taxonomy loop only does a cheap merge.
    """

    columns = ["trade_date", "symbol", "deal_net_30d_cr", "deal_prop_30d_cr"]
    targets = pd.Series(pd.to_datetime(list(as_of_dates), errors="coerce"), dtype="datetime64[ns]")
    targets = targets.dropna().dt.normalize().drop_duplicates().sort_values()
    if targets.empty or deals is None or deals.empty:
        return pd.DataFrame(columns=columns)

    required = {"trade_date", "symbol", "side", "deal_value_cr"}
    if not required.issubset(deals.columns):
        return pd.DataFrame(columns=columns)

    frame = deals[["trade_date", "symbol", "side", "deal_value_cr", *(["clientele"] if "clientele" in deals.columns else [])]].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["side"] = frame["side"].astype(str).str.upper()
    frame["deal_value_cr"] = pd.to_numeric(frame["deal_value_cr"], errors="coerce").fillna(0.0)
    frame = frame[frame["trade_date"].notna() & frame["symbol"].ne("")].copy()
    if frame.empty:
        return pd.DataFrame(columns=columns)
    clientele = frame["clientele"].astype(str).str.upper() if "clientele" in frame.columns else pd.Series("", index=frame.index)
    frame["deal_net_30d_cr"] = np.where(frame["side"].eq("BUY"), frame["deal_value_cr"], -frame["deal_value_cr"])
    frame["deal_prop_30d_cr"] = np.where(clientele.eq("PROP") & frame["side"].eq("BUY"), frame["deal_value_cr"], 0.0)

    rows: list[pd.DataFrame] = []
    for as_of in targets.tolist():
        window = frame[(frame["trade_date"] <= as_of) & (frame["trade_date"] > as_of - pd.Timedelta(days=30))]
        if window.empty:
            continue
        grouped = (
            window.groupby("symbol", as_index=False)[["deal_net_30d_cr", "deal_prop_30d_cr"]]
            .sum()
        )
        grouped.insert(0, "trade_date", as_of)
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True)[columns] if rows else pd.DataFrame(columns=columns)


def compute_sector_metrics(
    indicators: pd.DataFrame,
    master: pd.DataFrame,
    reference: pd.DataFrame | None = None,
    index_daily: pd.DataFrame | None = None,
    deals: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build cap-weighted taxonomy metrics without sector-index assumptions."""
    if indicators is None or indicators.empty or master is None or master.empty:
        return pd.DataFrame()

    frame = indicators.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    taxonomy = ["symbol", *LEVEL_COLUMNS.values()]
    frame = frame.merge(master[[c for c in taxonomy if c in master.columns]], on="symbol", how="left")
    frame["market_cap_cr"] = _as_of_market_cap(frame, reference if reference is not None else pd.DataFrame())
    if "market_cap_cr" not in frame.columns:
        frame["market_cap_cr"] = np.nan
    frame["market_cap_cr"] = pd.to_numeric(frame["market_cap_cr"], errors="coerce")
    benchmark = _benchmark_returns(index_daily if index_daily is not None else pd.DataFrame(), frame["trade_date"].unique())
    frame = frame.merge(benchmark, on="trade_date", how="left")

    if "return_21d_pct" not in frame.columns:
        frame["return_21d_pct"] = frame.groupby("symbol", sort=False)["close_price"].transform(lambda s: (s / s.shift(21) - 1) * 100)
    if "return_63d_pct" not in frame.columns:
        frame["return_63d_pct"] = frame.groupby("symbol", sort=False)["close_price"].transform(lambda s: (s / s.shift(63) - 1) * 100)

    deal_metrics = _prepare_deal_metrics(deals, frame["trade_date"].unique())
    if deal_metrics.empty:
        frame["deal_net_30d_cr"] = 0.0
        frame["deal_prop_30d_cr"] = 0.0
    else:
        frame = frame.merge(deal_metrics, on=["trade_date", "symbol"], how="left")
        frame["deal_net_30d_cr"] = pd.to_numeric(frame["deal_net_30d_cr"], errors="coerce").fillna(0.0)
        frame["deal_prop_30d_cr"] = pd.to_numeric(frame["deal_prop_30d_cr"], errors="coerce").fillna(0.0)

    # Materialise the per-row primitives once.  The old implementation
    # calculated these values in a Python loop for every (date, taxonomy)
    # group, which created hundreds of thousands of temporary Series objects.
    def numeric(name: str, default: float = np.nan) -> pd.Series:
        if name in frame.columns:
            return pd.to_numeric(frame[name], errors="coerce")
        return pd.Series(default, index=frame.index, dtype=float)

    close = numeric("close_price")
    ema_50 = numeric("ema_50")
    ema_200 = numeric("ema_200")
    frame["_above_50"] = (close > ema_50).astype(float)
    frame["_above_200"] = (close > ema_200).astype(float)
    frame["_return_21"] = numeric("return_21d_pct")
    frame["_return_63"] = numeric("return_63d_pct")
    frame["_market_cap_weight"] = numeric("market_cap_cr").fillna(0.0)
    frame["_return_21_weight"] = np.where(frame["_return_21"].notna(), frame["_market_cap_weight"], 0.0)
    frame["_return_63_weight"] = np.where(frame["_return_63"].notna(), frame["_market_cap_weight"], 0.0)
    frame["_return_21_num"] = frame["_return_21"].fillna(0.0) * frame["_return_21_weight"]
    frame["_return_63_num"] = frame["_return_63"].fillna(0.0) * frame["_return_63_weight"]
    if "avg_traded_value_cr_20d" in frame.columns:
        frame["_adv"] = numeric("avg_traded_value_cr_20d").fillna(0.0)
    elif "turnover_cr" in frame.columns:
        frame["_adv"] = numeric("turnover_cr").fillna(0.0)
    else:
        frame["_adv"] = 0.0
    distance = numeric("distance_below_52w")
    if distance.isna().all() and "away_52w_high_pct" in frame.columns:
        distance = (-numeric("away_52w_high_pct")).clip(lower=0)
    frame["_near_52"] = (distance <= 5).astype(float)
    frame["_near_52_valid"] = distance.notna().astype(float)
    setup = frame.get("setup_class", pd.Series("", index=frame.index)).astype(str).str.upper()
    tech_gate = frame.get("tech_gate", pd.Series("", index=frame.index)).astype(str).str.upper()
    funda_gate = frame.get("funda_gate", pd.Series("", index=frame.index)).astype(str).str.upper()
    frame["_tech_pass"] = (tech_gate.eq("PASS") | setup.isin(["BASE", "PIVOT", "BREAKOUT"])).astype(float)
    frame["_funda_pass"] = funda_gate.isin(["PROXY", "PASS"]).astype(float)

    result_frames: list[pd.DataFrame] = []
    for level, column in LEVEL_COLUMNS.items():
        if column not in frame.columns:
            continue
        scoped = frame.loc[
            frame[column].fillna("").astype(str).str.strip() != "",
            [
                "trade_date", "symbol", column, "_return_21", "_return_63",
                "_return_21_weight", "_return_63_weight", "_return_21_num", "_return_63_num",
                "_above_50", "_above_200", "_adv", "_near_52", "_near_52_valid",
                "_tech_pass", "_funda_pass", "deal_net_30d_cr", "deal_prop_30d_cr",
                "bench_21d", "bench_63d",
            ],
        ]
        if scoped.empty:
            continue
        keys = ["trade_date", column]
        summary = (
            scoped.groupby(keys, dropna=False, sort=False)
            .agg(
                stock_count=("symbol", "nunique"),
                row_count=("symbol", "size"),
                return_21_num=("_return_21_num", "sum"),
                return_21_weight=("_return_21_weight", "sum"),
                return_21_sum=("_return_21", "sum"),
                return_21_count=("_return_21", "count"),
                return_63_num=("_return_63_num", "sum"),
                return_63_weight=("_return_63_weight", "sum"),
                return_63_sum=("_return_63", "sum"),
                return_63_count=("_return_63", "count"),
                breadth_50_sum=("_above_50", "sum"),
                breadth_200_sum=("_above_200", "sum"),
                adv_total_cr=("_adv", "sum"),
                near_52_sum=("_near_52", "sum"),
                near_52_valid=("_near_52_valid", "sum"),
                tech_pass_n=("_tech_pass", "sum"),
                funda_pass_n=("_funda_pass", "sum"),
                deal_net_10s_cr=("deal_net_30d_cr", "sum"),
                deal_prop_10s_cr=("deal_prop_30d_cr", "sum"),
                bench_21d=("bench_21d", "first"),
                bench_63d=("bench_63d", "first"),
            )
            .reset_index()
        )
        top3 = (
            scoped.sort_values(keys + ["_adv"], ascending=[True, True, False], kind="mergesort")
            .groupby(keys, dropna=False, sort=False)
            .head(3)
            .groupby(keys, dropna=False, sort=False, as_index=False)["_adv"]
            .sum()
            .rename(columns={"_adv": "top3_adv"})
        )
        summary = summary.merge(top3, on=keys, how="left")
        return_21 = np.where(
            summary["return_21_weight"].gt(0),
            summary["return_21_num"] / summary["return_21_weight"],
            summary["return_21_sum"] / summary["return_21_count"].replace(0, np.nan),
        )
        return_63 = np.where(
            summary["return_63_weight"].gt(0),
            summary["return_63_num"] / summary["return_63_weight"],
            summary["return_63_sum"] / summary["return_63_count"].replace(0, np.nan),
        )
        summary["trade_date"] = pd.to_datetime(summary["trade_date"]).dt.normalize()
        summary["level"] = level
        summary["group_name"] = summary[column].astype(str)
        summary["rs_vs_nifty_21d"] = return_21 - pd.to_numeric(summary["bench_21d"], errors="coerce")
        summary["rs_vs_nifty_63d"] = return_63 - pd.to_numeric(summary["bench_63d"], errors="coerce")
        summary["breadth_50"] = summary["breadth_50_sum"] / summary["row_count"] * 100
        summary["breadth_200"] = summary["breadth_200_sum"] / summary["row_count"] * 100
        summary["adv_concentration_top3"] = np.where(
            summary["adv_total_cr"].gt(0), summary["top3_adv"] / summary["adv_total_cr"] * 100, np.nan
        )
        summary["near_52w_pct"] = np.where(
            summary["near_52_valid"].gt(0), summary["near_52_sum"] / summary["row_count"] * 100, np.nan
        )
        summary["rotation_state"] = ""
        result_frames.append(
            summary[
                [
                    "trade_date", "level", "group_name", "stock_count", "rs_vs_nifty_21d", "rs_vs_nifty_63d",
                    "breadth_50", "breadth_200", "adv_concentration_top3", "near_52w_pct", "adv_total_cr",
                    "tech_pass_n", "funda_pass_n", "deal_net_10s_cr", "deal_prop_10s_cr", "rotation_state",
                ]
            ]
        )
    return pd.concat(result_frames, ignore_index=True) if result_frames else pd.DataFrame()


__all__ = ["compute_sector_metrics"]
