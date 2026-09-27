"""Groups: board, RRG, drill-down and members (spec §7.4).

Source of truth is `group_daily` (data layer §4.5, built by Scripts/derived/group_daily.py).
Until that table exists — or for a floor it does not carry (group_daily builds all / 1000cr / watch) — the
board, RRG and drill-down are **computed live** from `indicators_daily` with the
same rules as the builder (status "partial", reason says so):

  * members  = stocks meeting the market-cap floor on as_of (current taxonomy mapping)
  * ret_ew_h = equal-weight mean of member returns over h sessions (each member's own sessions)
  * excess   = ret_ew − MidSml400 (or Nifty 50) return over the same horizon, points
  * rs_ratio_self = 100 × EMA10(RS) / EMA50(RS), RS = equal-weight group index / MidSml400;
    rs_momentum_self = 100 × rs_ratio_self / rs_ratio_self 10 sessions ago (each group vs its own history)
  * RS-Ratio / RS-Mom = 100 + 10 × cross-sectional z-score of rs_ratio_self / rs_momentum_self across the
    groups (≥ 3 members) of the same level, floor and session — peer-relative, so "Leading" = strong vs peers;
    quadrant from both vs 100. abs_trend, quadrant_note and Health (0–100) as in
    Scripts.derived.group_daily.add_health_columns (shared code, identical numbers). When the stored
    group_daily predates these columns they are computed on the fly from its rs_ratio / rs_momentum history.
  * rank     = by mean(excess_21d, excess_63d) vs MidSml400 among groups with ≥ 3 members, 1 = best;
               rank change = rank h sessions ago − rank now (positive = climbed)
  * money flow = group share of floor-universe turnover, 5-session avg − 20-session avg
  * deal net = collapsed bulk/block prints, PROP excluded, last 10 sessions

A 1-day move ≤ −35 % or ≥ +100 % is treated as an unadjusted corporate action: that
member's returns over any window containing it are excluded (never filled).

Group id format: ``<level>:<name>`` e.g. ``industry:2/3 Wheelers``.
"""
from __future__ import annotations

import threading
from collections import Counter
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from App.services import db, universe
from App.services.common import STATUS_PARTIAL, Result, no_session, unavailable
# Floor bands and the corporate-action guard are shared with the nightly group_daily builder.
from Scripts.derived.group_daily import FLOORS as _GD_FLOORS, SPLIT_DOWN, SPLIT_UP, add_health_columns

GROUP_METRICS = [
    "group_health", "group_abs_trend", "quadrant_note", "rs_ratio_self", "rs_ratio", "rs_momentum", "rrg_quadrant", "group_rank", "group_rank_delta_5", "group_rank_delta_20",
    "group_excess_21d", "group_excess_63d", "group_breadth_50", "group_breadth_200", "group_trend_template_pct",
    "turnover_share_5d", "turnover_share_delta_20d", "deal_net_10s_cr", "group_top1_turnover_share",
    "group_delivery_accumulation", "group_flow_up_days", "group_return_ew_21d",
]
MEMBER_METRICS = ["rs_percentile", "rs_delta_5", "rs_vs_sector_index_63d", "trend_template_pass_n",
                  "delivery_accumulation_days", "change_1d_pct", "rvol", "delivery_pct", "market_cap_cr"]

MIDSML400, NIFTY50 = "NIFTY MIDSML 400", "Nifty 50"
LIVE_WINDOW = 260          # sessions of history for the live computation (EMA50 warm-up + 63d rank change)
HISTORY_SESSIONS = 70      # sessions read from group_daily for sparks / tails
RS_FAST, RS_SLOW, RS_MOM_LAG = 10, 50, 10
MIN_MEMBERS_RANK = 3
CONCENTRATION_TOP1 = 50.0
DEAL_WINDOW = 10
LEVEL_ORDER = ["broad_sector", "sector", "broad_industry", "industry"]
_LIVE_LOCK = threading.Lock()

# Response field -> group_daily column candidates (first present wins). Names from
# Scripts/derived/SCHEMA.md first, then spec §4.5 names.
_GD_FIELDS: dict[str, tuple[str, ...]] = {
    "group_name": ("group_name", "name", "group"),
    "stocks": ("members", "stock_count", "stocks", "n_members"),
    "rrg_quadrant": ("rrg_quadrant", "quadrant"),
    "days_in_quadrant": ("days_in_quadrant",),
    "rs_ratio": ("rs_ratio", "jdk_rs_ratio"),
    "rs_momentum": ("rs_momentum", "jdk_rs_momentum"),
    "rs_ratio_self": ("rs_ratio_self",),
    "rs_momentum_self": ("rs_momentum_self",),
    "health": ("health",),
    "health_rank": ("health_rank",),
    "abs_trend": ("abs_trend",),
    "quadrant_note": ("quadrant_note",),
    "ew_index": ("ew_index",),
    "ew_index_ema50": ("ew_index_ema50",),
    "ew_index_ema200": ("ew_index_ema200",),
    "turnover_cr": ("turnover_cr",),
    "rank": ("rank", "group_rank", "rank_vs_benchmark"),
    "rank_n": ("rank_n",),
    "rank_score": ("rank_score",),
    "rank_delta_5": ("rank_chg_5d", "rank_delta_5", "rank_change_5d"),
    "rank_delta_20": ("rank_chg_20d", "rank_delta_20", "rank_change_20d"),
    "rank_delta_63": ("rank_chg_63d", "rank_delta_63", "rank_change_63d"),
    "return_ew_1d": ("ret_ew_1d", "return_ew_1d"),
    "return_ew_5d": ("ret_ew_5d", "return_ew_5d"),
    "return_ew_21d": ("ret_ew_21d", "return_ew_21d", "ew_return_21d"),
    "return_ew_63d": ("ret_ew_63d", "return_ew_63d"),
    "return_cw_21d": ("ret_cw_21d", "return_cw_21d", "cw_return_21d"),
    "excess_vs_midsml400_21d": ("excess_midsml_21d", "excess_vs_midsml400_21d"),
    "excess_vs_midsml400_63d": ("excess_midsml_63d", "excess_vs_midsml400_63d"),
    "excess_vs_nifty50_21d": ("excess_nifty_21d", "excess_vs_nifty50_21d", "excess_vs_nifty_21d"),
    "excess_vs_nifty50_63d": ("excess_nifty_63d", "excess_vs_nifty50_63d", "excess_vs_nifty_63d"),
    "breadth_50": ("pct_above_50ema", "breadth_50"),
    "breadth_200": ("pct_above_200ema", "breadth_200"),
    "trend_template_pct": ("pct_trend_template", "trend_template_pct"),
    "new_highs": ("new_highs_52w", "new_highs", "official_new_highs"),
    "pct_new_highs": ("pct_new_highs_52w",),
    "turnover_share_pct": ("turnover_share_pct",),
    "turnover_share_5d": ("turnover_share_5d_avg", "turnover_share_5d"),
    "turnover_share_20d": ("turnover_share_20d_avg", "turnover_share_20d"),
    "turnover_share_delta": ("turnover_share_delta", "turnover_share_delta_20d"),
    "top1_turnover_share_pct": ("top1_turnover_share_pct",),
    "concentration_flag": ("concentration_flag",),
    "delivery_accumulation": ("deliv_acc_10d_pct", "delivery_accumulation", "delivery_weighted_accumulation"),
    "acc_day_members_pct": ("acc_day_members_pct",),
    "deal_net_10s_cr": ("deal_net_10s_cr", "deal_net_10_cr"),
}
_TEXT = {"group_name", "rrg_quadrant", "abs_trend", "quadrant_note"}
_INT = {"stocks", "days_in_quadrant", "rank", "health_rank", "rank_n", "rank_delta_5", "rank_delta_20", "rank_delta_63", "new_highs"}
_BOOL = {"concentration_flag"}
FIELDS = list(_GD_FIELDS)
_HEALTH_FIELDS = ("rs_ratio", "rs_momentum", "rrg_quadrant", "days_in_quadrant", "rs_ratio_self", "rs_momentum_self",
                  "health", "health_rank", "abs_trend", "quadrant_note", "ew_index", "ew_index_ema50", "ew_index_ema200")


def parse_group_id(group_id: str) -> tuple[str, str]:
    raw = str(group_id or "")
    if ":" not in raw:
        raise ValueError("group id must look like '<level>:<name>'")
    lvl, name = raw.split(":", 1)
    key = universe.level_key(lvl)
    name = name.strip()
    if key is None or not name or len(name) > 120:
        raise ValueError(f"invalid group id {group_id!r}")
    return key, name


def group_id(level_key: str, name: str) -> str:
    return f"{level_key}:{name}"


def floor_value(floor: str) -> float:
    key = str(floor or "1000").strip().lower()
    if key not in universe.FLOORS:
        raise ValueError(f"floor must be one of {sorted(universe.FLOORS)}")
    return universe.FLOORS[key]


def floor_label(floor: str) -> str:
    return {"1000": "members with market cap ≥ ₹1,000 Cr", "all": "all listed members",
            "watch": "watch band: market cap ₹300–1,000 Cr"}[str(floor).lower()]


_GD_FLOOR_LABEL = {"1000": "1000cr", "all": "all", "watch": "watch"}  # API floor -> group_daily.floor


def _floor_mask(mcap: pd.Series, floor: str) -> pd.Series:
    lo, hi = _GD_FLOORS[_GD_FLOOR_LABEL.get(str(floor).lower(), "1000cr")]
    mask = pd.Series(True, index=mcap.index)
    if lo is not None:
        mask &= mcap >= lo
    if hi is not None:
        mask &= mcap < hi
    return mask


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def _index_closes(con: Any, as_of: date) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    if not db.table_exists(con, "index_daily"):
        return out
    df = con.execute(
        "SELECT index_name, trade_date, close_price FROM index_daily WHERE index_name IN (?, ?) AND trade_date <= ? "
        "ORDER BY trade_date", [MIDSML400, NIFTY50, as_of]).df()
    for name, g in df.groupby("index_name"):
        s = pd.Series(pd.to_numeric(g["close_price"], errors="coerce").to_numpy(), index=pd.to_datetime(g["trade_date"]))
        out[str(name)] = s[~s.index.duplicated(keep="last")]
    return out


def _grp_roll(df: pd.DataFrame, col: str, w: int, how: str = "mean") -> pd.Series:
    r = getattr(df.groupby("group_name", sort=False)[col].rolling(w, min_periods=w), how)()
    return r.reset_index(level=0, drop=True).reindex(df.index)


def _members_snapshot(con: Any, as_of: date, floor: str) -> pd.DataFrame:
    snap = universe.snapshot_sql(con)
    m = con.execute(f"WITH s AS ({snap}) SELECT * FROM s", [as_of]).df()
    if m.empty:
        return m
    m["market_cap_cr"] = pd.to_numeric(m["market_cap_cr"], errors="coerce")
    return m[_floor_mask(m["market_cap_cr"], floor).to_numpy(dtype=bool)].reset_index(drop=True)


# --------------------------------------------------------------------------
# Live computation (mirrors Scripts/derived/group_daily.py)
# --------------------------------------------------------------------------
_PANEL_COLS = ("close_price", "prev_close", "high_price", "turnover_cr", "ema_50", "ema_200", "trend_template_pass",
               "delivery_qty", "delivery_pct", "avg_delivery_pct_20d", "high_52w")


def _live_frames(con: Any, as_of: date, floor: str) -> dict[str, pd.DataFrame]:
    sessions = db.recent_sessions(con, as_of, LIVE_WINDOW)
    members = _members_snapshot(con, as_of, floor)
    if not sessions or members.empty:
        return {k: pd.DataFrame() for k in LEVEL_ORDER}
    start = sessions[-1]
    have = set(db.table_columns(con, "indicators_daily"))
    sel = ", ".join(f"i.{c}" if c in have else f"NULL AS {c}" for c in _PANEL_COLS)
    tax = members[["symbol", *LEVEL_ORDER, "market_cap_cr", "close"]].rename(columns={"close": "close_asof"}).copy()
    for lvl in LEVEL_ORDER:
        s = tax[lvl].astype("string").str.strip()
        tax[lvl] = s.where(s != "").astype("category")
    con.register("grp_members", tax[["symbol"]])
    try:
        p = con.execute(
            f"SELECT i.symbol, i.trade_date, {sel} FROM indicators_daily i JOIN grp_members USING (symbol) "
            "WHERE i.trade_date BETWEEN ? AND ? ORDER BY i.symbol, i.trade_date", [start, as_of]).df()
    finally:
        con.unregister("grp_members")
    if p.empty:
        return {k: pd.DataFrame() for k in LEVEL_ORDER}
    p["trade_date"] = pd.to_datetime(p["trade_date"])
    for c in _PANEL_COLS:
        if c != "trend_template_pass":
            p[c] = pd.to_numeric(p[c], errors="coerce").astype(float)
    p = p.merge(tax, on="symbol", how="left")
    sid = pd.Series(pd.factorize(p["symbol"])[0], index=p.index)
    g = p.groupby(sid, sort=False)
    c = p["close_price"]
    prev = g["close_price"].shift(1).fillna(p["prev_close"])
    r1 = c / prev.where(prev > 0) - 1.0
    bad = ((r1 <= SPLIT_DOWN) | (r1 >= SPLIT_UP)).fillna(False)
    lr = np.log1p(r1.where(~bad).fillna(0.0).clip(lower=-0.99))
    cl = lr.groupby(sid, sort=False).cumsum()
    cb = bad.astype(int).groupby(sid, sort=False).cumsum()
    p["r_1"] = r1.where(~bad)
    for h in (5, 21, 63):
        cl_h = cl.groupby(sid, sort=False).shift(h)
        cb_h = cb.groupby(sid, sort=False).shift(h)
        p[f"r_{h}"] = (np.exp(cl - cl_h) - 1.0).where(cl_h.notna() & (cb - cb_h == 0))
    # Cap weight at window start ≈ mcap(as_of) × close(t−21)/close(as_of) (constant share count).
    c21 = g["close_price"].shift(21)
    w21 = (p["market_cap_cr"] * c21 / p["close_asof"]).where(p["r_21"].notna())
    p["cwd21"] = w21
    p["cwn21"] = w21 * p["r_21"]
    p["a50"] = (c > p["ema_50"]).astype(float).where(c.notna() & p["ema_50"].notna())
    p["a200"] = (c > p["ema_200"]).astype(float).where(c.notna() & p["ema_200"].notna())
    p["tt"] = pd.array(p["trend_template_pass"], dtype="boolean").astype("Float64").to_numpy(dtype=float, na_value=np.nan)
    prev_h52 = g["high_52w"].shift(1)
    p["nh"] = (p["high_price"] > prev_h52).astype(float).where(prev_h52.notna() & p["high_price"].notna())
    dv = p["delivery_qty"] * c / 1e7
    p["dv"] = dv
    p["dvs"] = dv * np.sign(p["r_1"])
    acc_known = p["r_1"].notna() & p["delivery_pct"].notna() & p["avg_delivery_pct_20d"].notna()
    p["acc"] = ((p["r_1"] > 0) & (p["delivery_pct"] > p["avg_delivery_pct_20d"])).astype(float).where(acc_known)

    # Deals (collapsed prints, PROP excluded) per symbol-day.
    deal_start = None
    p["deal"] = 0.0
    if db.table_exists(con, "deals"):
        deal_start = db.to_date(con.execute("SELECT min(trade_date) FROM deals").fetchone()[0])
        dn = con.execute(
            f"""WITH q AS ({universe.collapsed_prints_sql("AND d.trade_date BETWEEN ? AND ?")})
                SELECT symbol, trade_date,
                       sum(CASE WHEN side LIKE '%BUY%' THEN value_cr WHEN side LIKE '%SELL%' THEN -value_cr END) AS net
                FROM q WHERE coalesce(upper(clientele), '') <> 'PROP' AND NOT is_prop GROUP BY 1, 2""", [start, as_of]).df()
        if not dn.empty:
            dn["trade_date"] = pd.to_datetime(dn["trade_date"])
            p = p.merge(dn, on=["symbol", "trade_date"], how="left")
            p["deal"] = pd.to_numeric(p["net"], errors="coerce").fillna(0.0)
            p = p.drop(columns=["net"])

    idx = _index_closes(con, as_of)
    out: dict[str, pd.DataFrame] = {}
    for lvl in LEVEL_ORDER:
        q = p[p[lvl].notna()]
        a = q.groupby([lvl, "trade_date"], sort=True, observed=True).agg(
            stocks=("symbol", "size"), return_ew_1d=("r_1", "mean"), return_ew_5d=("r_5", "mean"),
            return_ew_21d=("r_21", "mean"), return_ew_63d=("r_63", "mean"), cwn21=("cwn21", "sum"),
            cwd21=("cwd21", "sum"), breadth_50=("a50", "mean"), breadth_200=("a200", "mean"),
            trend_template_pct=("tt", "mean"), nh=("nh", "sum"), nh_k=("nh", "count"), turnover=("turnover_cr", "sum"),
            tmax=("turnover_cr", "max"), dv=("dv", "sum"), dvs=("dvs", "sum"), acc_day_members_pct=("acc", "mean"),
            deal=("deal", "sum"),
        ).reset_index().rename(columns={lvl: "group_name"})
        a["group_name"] = a["group_name"].astype(str)
        out[lvl] = _finish_live(a, idx, deal_start)
    return out


def _finish_live(a: pd.DataFrame, idx: dict[str, pd.Series], deal_start: date | None) -> pd.DataFrame:
    if a.empty:
        return a
    a = a.sort_values(["group_name", "trade_date"], kind="mergesort").reset_index(drop=True)
    for h in (1, 5, 21, 63):
        a[f"return_ew_{h}d"] = a[f"return_ew_{h}d"] * 100.0
    a["return_cw_21d"] = (a["cwn21"] / a["cwd21"].where(a["cwd21"] > 0)) * 100.0
    for col in ("breadth_50", "breadth_200", "trend_template_pct", "acc_day_members_pct"):
        a[col] = a[col] * 100.0
    valid_nh = a["nh_k"] >= 0.5 * a["stocks"]
    a["new_highs"] = a["nh"].where(valid_nh)
    a["pct_new_highs"] = (a["nh"] / a["nh_k"].where(a["nh_k"] > 0) * 100.0).where(valid_nh)
    for name, key in ((MIDSML400, "midsml400"), (NIFTY50, "nifty50")):
        s = idx.get(name)
        for h in (21, 63):
            br = (s / s.shift(h) - 1.0) * 100.0 if s is not None else None
            a[f"excess_vs_{key}_{h}d"] = a[f"return_ew_{h}d"] - (a["trade_date"].map(br) if br is not None else np.nan)
    gb = a.groupby("group_name", sort=False)
    a["_idx"] = np.exp(np.log1p((a["return_ew_1d"] / 100.0).fillna(0.0).clip(lower=-0.99)).groupby(a["group_name"], sort=False).cumsum())
    bench = idx.get(MIDSML400)
    a["_rs"] = a["_idx"] / (a["trade_date"].map(bench) if bench is not None else np.nan)
    fast = gb["_rs"].transform(lambda s: s.ewm(span=RS_FAST, adjust=False, min_periods=RS_FAST).mean())
    slow = gb["_rs"].transform(lambda s: s.ewm(span=RS_SLOW, adjust=False, min_periods=RS_SLOW).mean())
    a["rs_ratio_self"] = 100.0 * fast / slow
    a["rs_momentum_self"] = 100.0 * a["rs_ratio_self"] / a.groupby("group_name", sort=False)["rs_ratio_self"].shift(RS_MOM_LAG)
    add_health_columns(a, "group_name", ["trade_date"], members="stocks", ret1="return_ew_1d", ret21="return_ew_21d",
                       b50="breadth_50", b200="breadth_200")
    score = (a["excess_vs_midsml400_21d"] + a["excess_vs_midsml400_63d"]) / 2.0
    a["rank_score"] = score
    elig = score.where((a["stocks"] >= MIN_MEMBERS_RANK) & score.notna())
    a["rank"] = elig.groupby(a["trade_date"]).rank(ascending=False, method="min")
    a["rank_n"] = elig.groupby(a["trade_date"]).transform("count")
    for h in (5, 20, 63):
        a[f"rank_delta_{h}"] = a.groupby("group_name", sort=False)["rank"].shift(h) - a["rank"]
    a["turnover_cr"] = a["turnover"]
    tot = a.groupby("trade_date")["turnover"].transform("sum")
    a["turnover_share_pct"] = a["turnover"] / tot.where(tot > 0) * 100.0
    a["turnover_share_5d"] = _grp_roll(a, "turnover_share_pct", 5)
    a["turnover_share_20d"] = _grp_roll(a, "turnover_share_pct", 20)
    a["turnover_share_delta"] = a["turnover_share_5d"] - a["turnover_share_20d"]
    a["_up"] = (a["turnover_share_delta"] > 0).astype(float).where(a["turnover_share_delta"].notna())
    a["top1_turnover_share_pct"] = a["tmax"] / a["turnover"].where(a["turnover"] > 0) * 100.0
    a["concentration_flag"] = (a["top1_turnover_share_pct"] >= CONCENTRATION_TOP1) & (a["stocks"] >= MIN_MEMBERS_RANK)
    dvs10, dv10 = _grp_roll(a, "dvs", 10, "sum"), _grp_roll(a, "dv", 10, "sum")
    a["delivery_accumulation"] = (dvs10 / dv10.where(dv10 > 0)) * 100.0
    if deal_start is None:
        a["deal_net_10s_cr"] = np.nan
    else:
        d10 = _grp_roll(a, "deal", DEAL_WINDOW, "sum")
        wstart = a.groupby("group_name", sort=False)["trade_date"].shift(DEAL_WINDOW - 1)
        a["deal_net_10s_cr"] = d10.where(wstart >= pd.Timestamp(deal_start))
    return a


# --------------------------------------------------------------------------
# group_daily reader
# --------------------------------------------------------------------------
def _gd_floor_values(floor: str) -> list[str]:
    f = str(floor).lower()
    return {"1000": ["1000cr", "1000", "default"], "all": ["all"], "watch": ["watch", "300cr"]}[f]


def _gd_frame(con: Any, as_of: date, level_key: str, floor: str) -> pd.DataFrame | None:
    """History frame from group_daily for (level, floor), or None when it has no rows for them."""
    cols = set(db.table_columns(con, "group_daily"))
    fmap = {k: next((c for c in names if c in cols), "") for k, names in _GD_FIELDS.items()}
    if not fmap["group_name"] or "trade_date" not in cols or "level" not in cols:
        return None
    label = universe.LEVELS[level_key][1]
    where = "lower(replace(CAST(level AS VARCHAR), '_', ' ')) = lower(?)"
    params: list[Any] = [label]
    if "floor" in cols:
        vals = _gd_floor_values(floor)
        where += f" AND lower(CAST(floor AS VARCHAR)) IN ({','.join('?' * len(vals))})"
        params += vals
    elif str(floor).lower() != "1000":
        return None
    dates = [r[0] for r in con.execute(
        f"SELECT DISTINCT trade_date FROM group_daily WHERE trade_date <= ? AND {where} ORDER BY trade_date DESC LIMIT ?",
        [as_of, *params, HISTORY_SESSIONS]).fetchall()]
    if not dates:
        return None
    raw = con.execute(f"SELECT * FROM group_daily WHERE trade_date >= ? AND trade_date <= ? AND {where}",
                      [dates[-1], as_of, *params]).df()
    out = pd.DataFrame({"trade_date": pd.to_datetime(raw["trade_date"])})
    for field, col in fmap.items():
        out[field] = raw[col] if col else None
    out = out[out["group_name"].notna() & (out["group_name"].astype(str).str.upper() != "TOTAL")]
    out = out.sort_values(["group_name", "trade_date"], kind="mergesort").reset_index(drop=True)
    if "health" not in cols:  # built before the peer-relative RRG / Health columns: compute them on the fly
        long = _long(con, as_of, level_key, floor)
        if long is not None:
            out = out.drop(columns=list(_HEALTH_FIELDS)).merge(long, on=["trade_date", "group_name"], how="left")
    delta = pd.to_numeric(out["turnover_share_delta"], errors="coerce")
    out["_up"] = (delta > 0).astype(float).where(delta.notna())
    if fmap["return_ew_1d"]:
        idx = _index_closes(con, as_of).get(MIDSML400)
        r1 = pd.to_numeric(out["return_ew_1d"], errors="coerce") / 100.0
        out["_idx"] = np.exp(np.log1p(r1.fillna(0.0).clip(lower=-0.99)).groupby(out["group_name"], sort=False).cumsum())
        out["_rs"] = out["_idx"] / (out["trade_date"].map(idx) if idx is not None else np.nan)
    else:
        out["_rs"] = np.nan
    return out


def _gd_where(con: Any, level_key: str, floor: str) -> tuple[str, list[Any]] | None:
    cols = set(db.table_columns(con, "group_daily"))
    label = universe.LEVELS[level_key][1]
    where = "lower(replace(CAST(level AS VARCHAR), '_', ' ')) = lower(?)"
    params: list[Any] = [label]
    if "floor" in cols:
        vals = _gd_floor_values(floor)
        where += f" AND lower(CAST(floor AS VARCHAR)) IN ({','.join('?' * len(vals))})"
        params += vals
    elif str(floor).lower() != "1000":
        return None
    return where, params


def _gd_long(con: Any, as_of: date, level_key: str, floor: str) -> pd.DataFrame | None:
    """Full group_daily history (≤ as_of) of the Health / peer-RRG / EW-index columns for (level, floor).

    Read as stored when the table has them; otherwise computed here with the builder's shared
    add_health_columns from the stored self-normalised rs_ratio / rs_momentum (tables built before
    2026-09-27 hold the self-normalised values in those columns)."""
    cols = set(db.table_columns(con, "group_daily"))
    wp = _gd_where(con, level_key, floor)
    if wp is None or not {"group_name", "trade_date", "level"} <= cols:
        return None
    where, params = wp
    if {"health", "ew_index", "rs_ratio_self"} <= cols:
        sel = ", ".join(c for c in ("trade_date", "group_name", *_HEALTH_FIELDS) if c in cols)
        df = con.execute(f"SELECT {sel} FROM group_daily WHERE trade_date <= ? AND {where}", [as_of, *params]).df()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df.sort_values(["group_name", "trade_date"], kind="mergesort").reset_index(drop=True)
    need = {"members", "ret_ew_1d", "rs_ratio", "rs_momentum"}
    if not need <= cols:
        return None
    opt = [c for c in ("ret_ew_21d", "pct_above_50ema", "pct_above_200ema") if c in cols]
    sel = ", ".join(["trade_date", "group_name", "members", "ret_ew_1d", "rs_ratio AS rs_ratio_self",
                     "rs_momentum AS rs_momentum_self", *opt])
    df = con.execute(f"SELECT {sel} FROM group_daily WHERE trade_date <= ? AND {where} "
                     "AND upper(CAST(group_name AS VARCHAR)) <> 'TOTAL'", [as_of, *params]).df()
    if df.empty:
        return None
    for c in ("ret_ew_21d", "pct_above_50ema", "pct_above_200ema"):
        if c not in df.columns:
            df[c] = np.nan
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values(["group_name", "trade_date"], kind="mergesort").reset_index(drop=True)
    add_health_columns(df, "group_name", ["trade_date"])
    return df[["trade_date", "group_name", *_HEALTH_FIELDS]]


def _long(con: Any, as_of: date, level_key: str, floor: str) -> pd.DataFrame | None:
    return db.cached("groups.gd_long", (as_of, level_key, floor), lambda: _gd_long(con, as_of, level_key, floor))


def _frame(con: Any, as_of: date, level_key: str, floor: str) -> tuple[pd.DataFrame, str]:
    """(history frame, source) — group_daily when it covers (level, floor), else live."""
    if db.table_exists(con, "group_daily"):
        gd = db.cached("groups.gd", (as_of, level_key, floor), lambda: _gd_frame(con, as_of, level_key, floor))
        if gd is not None and not gd.empty:
            return gd, "group_daily"
    with _LIVE_LOCK:  # one live computation at a time; concurrent requests wait and hit the cache
        live = db.cached("groups.live", (as_of, floor), lambda: _live_frames(con, as_of, floor))
    return live.get(level_key, pd.DataFrame()), "live"


def _live_reason(has_gd: bool, floor: str) -> str:
    why = (f"group_daily has no rows for floor '{floor}'" if has_gd else "group_daily not built yet")
    return (f"{why}; computed live from indicators_daily with the group_daily rules (equal-weight members at as_of, "
            "RS-Ratio = EMA10/EMA50 of group index vs MidSml400). Official new highs use the high_52w snapshot.")


# --------------------------------------------------------------------------
# Row shaping
# --------------------------------------------------------------------------
def _clean(v: Any, field: str) -> Any:
    if field in _TEXT:
        return db.text(v)
    if field in _BOOL:
        return db.boolean(v)
    if field in _INT:
        return db.integer(v)
    return db.num(v, 4)


def _row(r: dict[str, Any], level_key: str) -> dict[str, Any]:
    row: dict[str, Any] = {"level": level_key}
    for f in FIELDS:
        row[f] = _clean(r.get(f), f)
    row["id"] = group_id(level_key, row["group_name"] or "")
    row["trade_date"] = db.to_date(r.get("trade_date"))
    return row


def _last_rows(df: pd.DataFrame, as_of: date) -> tuple[pd.DataFrame, date | None]:
    if df.empty:
        return df, None
    d = df.loc[df["trade_date"] <= pd.Timestamp(as_of), "trade_date"].max()
    if pd.isna(d):
        return df.iloc[0:0], None
    return df[df["trade_date"] == d], db.to_date(d)


def _spark(values: pd.Series, n: int = 60, digits: int = 2) -> list[float | None] | None:
    v = values.tail(n)
    if v.notna().sum() == 0:
        return None
    return [db.num(x, digits) for x in v]


def _leaders(members: pd.DataFrame, level_key: str) -> dict[str, list[str]]:
    if members.empty:
        return {}
    m = members[members[level_key].notna()].copy()
    m["rs_percentile"] = pd.to_numeric(m["rs_percentile"], errors="coerce")
    m = m.sort_values("rs_percentile", ascending=False, na_position="last")
    return {str(k): [str(s) for s in g["symbol"].head(3)] for k, g in m.groupby(level_key, sort=False)}


HEALTH_ZONES = ((65.0, "Healthy"), (45.0, "Mixed"), (-1.0, "Weak"))  # metric_dictionary.yaml group_health


def health_zone(v: float | None) -> str | None:
    if v is None:
        return None
    return next(label for lo, label in HEALTH_ZONES if v >= lo)


def _desk_verdict(con: Any, as_of: date) -> str | None:
    """The Desk's environment verdict (regime_daily) on or before as_of, for the Groups context line."""
    if not db.table_exists(con, "regime_daily"):
        return None
    from App.services.market import shape_regime_row

    recs = db.records(con, "SELECT * FROM regime_daily WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 1", [as_of])
    return shape_regime_row(recs[0]).get("verdict") if recs else None


def _bench_return(s: pd.Series | None, d: date, h: int) -> float | None:
    if s is None or s.empty:
        return None
    s = s[s.index <= pd.Timestamp(d)]
    if len(s) <= h:
        return None
    return db.num((s.iloc[-1] / s.iloc[-1 - h] - 1.0) * 100.0, 2)


def _market_line(rows: list[dict[str, Any]], bench: dict[str, pd.Series], d: date, verdict: str | None) -> dict[str, Any]:
    """Absolute context for the board header: Desk verdict, benchmark 21d returns, how many 'Leading' groups fall."""
    ranked = [r for r in rows if (r.get("stocks") or 0) >= MIN_MEMBERS_RANK]
    quads = Counter(r.get("rrg_quadrant") for r in ranked if r.get("rrg_quadrant"))
    lead = [r for r in ranked if r.get("rrg_quadrant") == "Leading"]
    healths = [r["health"] for r in ranked if r.get("health") is not None]
    zones = Counter(health_zone(h) for h in healths)
    return {
        "verdict": verdict,
        "midsml400_ret_21d": _bench_return(bench.get(MIDSML400), d, 21),
        "nifty50_ret_21d": _bench_return(bench.get(NIFTY50), d, 21),
        "groups": len(ranked),
        "quadrants": {q: int(quads.get(q, 0)) for q in ("Leading", "Improving", "Weakening", "Lagging")},
        "leading_falling": sum(1 for r in lead if (r.get("return_ew_21d") or 0) < 0),
        "leading_narrow": sum(1 for r in lead if r.get("breadth_50") is not None and r["breadth_50"] < 50),
        "falling_21d": sum(1 for r in ranked if (r.get("return_ew_21d") or 0) < 0),
        "trend": {t: sum(1 for r in ranked if r.get("abs_trend") == t) for t in ("Up", "Flat", "Down")},
        "health_median": db.num(float(np.median(healths)), 1) if healths else None,
        "health_zones": {z: int(zones.get(z, 0)) for z in ("Healthy", "Mixed", "Weak")},
    }


def board(as_of: date | None, level: str, floor: str = "1000") -> Result:
    level_key = universe.level_key(level)
    if level_key is None:
        raise ValueError(f"unknown level {level!r}")
    floor_value(floor)
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        has_gd = db.table_exists(con, "group_daily")
        df, src = _frame(con, resolved, level_key, floor)
        members = db.cached("groups.members_snap", (resolved, floor), lambda: _members_snapshot(con, resolved, floor))
        bench = _index_closes(con, resolved)
        verdict = _desk_verdict(con, resolved)
    if df.empty:
        return unavailable(resolved, "no group data on or before as_of", ["group_daily", "indicators_daily"])
    last, d = _last_rows(df, resolved)
    leaders = _leaders(members, level_key)
    hist = df[df["trade_date"] <= pd.Timestamp(resolved)]
    rows = []
    for name, g in hist.groupby("group_name", sort=False):
        cur = last[last["group_name"] == name]
        if cur.empty:
            continue
        row = _row(cur.iloc[0].to_dict(), level_key)
        rank = pd.to_numeric(g["rank"], errors="coerce")
        row["rank_spark_60"] = [db.integer(x) for x in rank.tail(60)] if rank.notna().any() else None
        rs = pd.to_numeric(g["_rs"], errors="coerce").tail(60)
        base = rs.dropna().iloc[0] if rs.notna().any() else None
        row["rs_line_60"] = _spark(rs / base * 100.0) if base else None
        up = pd.to_numeric(g["_up"], errors="coerce").tail(10)
        row["flow_up_days_10"] = int(up.sum()) if up.notna().sum() == 10 else None
        row["leader_symbols"] = leaders.get(str(name)) or None
        rows.append(row)
    market_line = _market_line(rows, bench, d or resolved, verdict)
    # Default order: Health (relative + absolute trend + breadth), healthiest first; unranked last.
    rows.sort(key=lambda r: (r.get("health_rank") is None, r.get("health_rank") or 0, -(r.get("health") or -1e9),
                             r.get("rank") or 1e9))
    status, reason = ("ok", None) if src == "group_daily" else (STATUS_PARTIAL, _live_reason(has_gd, floor))
    ranked = sum(1 for r in rows if r["rank"] is not None)
    return Result(
        as_of=d or resolved, rows=rows, status=status, reason=reason,
        sources=["group_daily"] if src == "group_daily" else ["indicators_daily", "index_daily", "deals", "stocks_master"],
        extra={"level": level_key, "floor": floor, "floor_label": floor_label(floor), "floor_applied": True,
               "source": src, "ranked": ranked, "benchmark": MIDSML400,
               "market": market_line,
               "rank_rule": f"rank by mean of 21d and 63d excess return vs {MIDSML400}; groups with < {MIN_MEMBERS_RANK} "
                            "members are listed but not ranked",
               "health_rule": "Health 0-100 = 0.40 relative (peer RS-Ratio / RS-Momentum) + 0.35 absolute (EW index vs "
                              "its 50/200 EMA and slope, 21d return) + 0.25 breadth (% above 50/200 EMA); default sort",
               "rrg_rule": "RS-Ratio / RS-Momentum = 100 + 10 x z-score across this level's groups (peer-relative): "
                           "'Leading' = strongest vs peers, not necessarily rising"},
        notes=["Taxonomy is today's mapping (documented limitation).",
               "Members are fixed at as_of for the live computation; group_daily applies the floor each session."],
        metric_keys=GROUP_METRICS)


def rrg(as_of: date | None, level: str, floor: str = "1000", tail_weeks: int = 6) -> Result:
    level_key = universe.level_key(level)
    if level_key is None:
        raise ValueError(f"unknown level {level!r}")
    floor_value(floor)
    tail_weeks = max(1, min(int(tail_weeks), 12))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        has_gd = db.table_exists(con, "group_daily")
        df, src = _frame(con, resolved, level_key, floor)
    if df.empty:
        return unavailable(resolved, "no group data on or before as_of", ["group_daily"])
    df = df[df["trade_date"] <= pd.Timestamp(resolved)]
    dates = sorted(df["trade_date"].unique(), reverse=True)[: tail_weeks * 5 + 1]
    weekly = set(dates[::5])
    pts = df[df["trade_date"].isin(weekly)]
    rows = []
    for name, g in pts.groupby("group_name", sort=True):
        g = g.sort_values("trade_date")
        last = g.iloc[-1]
        if db.num(last["rs_ratio"]) is None or db.num(last["rs_momentum"]) is None or last["trade_date"] != dates[0]:
            continue
        rows.append({
            "id": group_id(level_key, str(name)), "group_name": str(name), "level": level_key,
            "rs_ratio": db.num(last["rs_ratio"], 3), "rs_momentum": db.num(last["rs_momentum"], 3),
            "rrg_quadrant": db.text(last["rrg_quadrant"]), "days_in_quadrant": db.integer(last["days_in_quadrant"]),
            "stocks": db.integer(last["stocks"]), "rank": db.integer(last["rank"]),
            "health": db.num(last.get("health"), 1), "health_rank": db.integer(last.get("health_rank")),
            "abs_trend": db.text(last.get("abs_trend")), "quadrant_note": db.text(last.get("quadrant_note")),
            "return_ew_21d": db.num(last.get("return_ew_21d"), 2),
            "tail": [{"trade_date": db.to_date(p["trade_date"]), "rs_ratio": db.num(p["rs_ratio"], 3),
                      "rs_momentum": db.num(p["rs_momentum"], 3)} for _, p in g.iterrows()
                     if db.num(p["rs_ratio"]) is not None and db.num(p["rs_momentum"]) is not None],
        })
    if not rows:
        return unavailable(resolved, f"not enough history for RS-Ratio (needs ≥ {RS_SLOW + RS_MOM_LAG} sessions)",
                           ["group_daily" if src == "group_daily" else "indicators_daily"])
    status, reason = ("ok", None) if src == "group_daily" else (STATUS_PARTIAL, _live_reason(has_gd, floor))
    return Result(as_of=db.to_date(dates[0]), rows=rows, status=status, reason=reason,
                  sources=["group_daily"] if src == "group_daily" else ["indicators_daily", "index_daily"],
                  extra={"level": level_key, "floor": floor, "floor_label": floor_label(floor), "tail_weeks": tail_weeks,
                         "source": src, "tail_step_sessions": 5, "benchmark": MIDSML400,
                         "axes": "peer-relative: 100 + 10 x z-score across this level's groups (>= 3 members)"},
                  metric_keys=["rs_ratio", "rs_momentum", "rrg_quadrant", "group_health", "quadrant_note"])


def _breadcrumb(con: Any, level_key: str, name: str) -> list[dict[str, Any]]:
    col = universe.LEVELS[level_key][0]
    parents = LEVEL_ORDER[: LEVEL_ORDER.index(level_key)]
    if not parents:
        return [{"level": level_key, "name": name, "id": group_id(level_key, name)}]
    cols = ", ".join(universe.LEVELS[p][0] for p in parents)
    recs = con.execute(f"SELECT {cols} FROM stocks_master WHERE {col} = ? AND upper(symbol) <> 'TOTAL'", [name]).fetchall()
    crumb = []
    for i, p in enumerate(parents):
        vals = Counter(r[i] for r in recs if r[i])
        pname = vals.most_common(1)[0][0] if vals else None
        crumb.append({"level": p, "name": pname, "id": group_id(p, pname) if pname else None})
    crumb.append({"level": level_key, "name": name, "id": group_id(level_key, name)})
    return crumb


def _children(con: Any, level_key: str, name: str) -> list[dict[str, Any]]:
    if level_key == "industry":
        return []
    child = LEVEL_ORDER[LEVEL_ORDER.index(level_key) + 1]
    col, ccol = universe.LEVELS[level_key][0], universe.LEVELS[child][0]
    recs = con.execute(f"SELECT DISTINCT {ccol} FROM stocks_master WHERE {col} = ? AND {ccol} IS NOT NULL "
                       f"AND upper(symbol) <> 'TOTAL' ORDER BY 1", [name]).fetchall()
    return [{"level": child, "name": r[0], "id": group_id(child, r[0])} for r in recs]


def detail(as_of: date | None, gid: str, floor: str = "1000", days: int = 60) -> Result:
    level_key, name = parse_group_id(gid)
    floor_value(floor)
    days = max(5, min(int(days), 600))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        crumb = _breadcrumb(con, level_key, name)
        children = _children(con, level_key, name)
        has_gd = db.table_exists(con, "group_daily")
        df, src = _frame(con, resolved, level_key, floor)
    g = df[(df["group_name"] == name) & (df["trade_date"] <= pd.Timestamp(resolved))] if not df.empty else df
    if g.empty:
        return unavailable(resolved, f"no history for group {gid!r} at this floor", [src], breadcrumb=crumb,
                           children=children)
    g = g.sort_values("trade_date", ascending=False).head(days)
    rows = [_row(r, level_key) for r in g.to_dict("records")]
    status, reason = ("ok", None) if src == "group_daily" else (STATUS_PARTIAL, _live_reason(has_gd, floor))
    return Result(as_of=rows[0].get("trade_date") or resolved, rows=rows, status=status, reason=reason,
                  sources=["group_daily"] if src == "group_daily" else ["indicators_daily", "index_daily"],
                  extra={"group": {"id": gid, "level": level_key, "name": name}, "breadcrumb": crumb,
                         "children": children, "floor": floor, "floor_label": floor_label(floor), "source": src,
                         "members_endpoint": f"/api/v2/groups/{gid}/members"},
                  notes=["Group evidence ('when this group turned Leading…') arrives with the evidence engine."],
                  metric_keys=GROUP_METRICS)


def members(as_of: date | None, gid: str, floor: str = "1000", sort: str = "rs_percentile", descending: bool = True) -> Result:
    level_key, name = parse_group_id(gid)
    floor_value(floor)
    col = universe.LEVELS[level_key][0]
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        snap = universe.snapshot_sql(con, extra_where=f"AND m.{col} = ?")
        f = str(floor).lower()
        where = {"1000": "WHERE s.market_cap_cr >= 1000", "watch": "WHERE s.market_cap_cr >= 300 AND s.market_cap_cr < 1000",
                 "all": ""}[f]
        recs = db.records(con, f"WITH s AS ({snap}) SELECT * FROM s {where}", [resolved, name])
        syms = [r["symbol"] for r in recs]
        acc: dict[str, int] = {}
        setups: dict[str, list[str]] = {}
        deal_net = universe.deal_net_recent(con, syms, resolved, DEAL_WINDOW, exclude_prop=True) if syms else {}
        has_setups = db.table_exists(con, "setup_daily")
        if syms:
            window = db.recent_sessions(con, resolved, 10)
            con.register("grp_syms", pd.DataFrame({"symbol": syms}))
            try:
                acc = {r[0]: int(r[1]) for r in con.execute(
                    """
                    SELECT i.symbol, count(*) FILTER (WHERE i.close_price > i.prev_close
                                                       AND i.delivery_pct > i.avg_delivery_pct_20d)
                    FROM indicators_daily i JOIN grp_syms USING (symbol)
                    WHERE i.trade_date BETWEEN ? AND ? GROUP BY 1
                    """,
                    [window[-1], resolved],
                ).fetchall()}
                if has_setups and {"queue", "symbol", "trade_date"} <= set(db.table_columns(con, "setup_daily")):
                    for s, q in con.execute(
                        "SELECT symbol, queue FROM setup_daily JOIN grp_syms USING (symbol) WHERE trade_date = ? "
                        "ORDER BY queue", [resolved]).fetchall():
                        setups.setdefault(str(s), []).append(str(q))
            finally:
                con.unregister("grp_syms")
    rows = []
    for r in recs:
        base = universe.shape_stock(r)
        sym = base["symbol"] or ""
        rows.append({
            **base,
            "rs_vs_sector_index_63d": db.num(r.get("rs_vs_sector_index_63d"), 2),
            "sector_index_name": db.text(r.get("sector_index_name")),
            "rs_rank_t5": db.num(r.get("rs_rank_t5"), 1),
            "rs_rank_t15": db.num(r.get("rs_rank_t15"), 1),
            "rs_rank_t30": db.num(r.get("rs_rank_t30"), 1),
            "trend_template_pass_n": db.integer(r.get("trend_template_pass_n")),
            "trend_template_pass": db.boolean(r.get("trend_template_pass")),
            "return_1m_pct": db.num(r.get("return_1m_pct"), 2),
            "return_3m_pct": db.num(r.get("return_3m_pct"), 2),
            "excess_vs_midsml400_21d": db.num(r.get("excess_vs_midsml400_21d"), 2),
            "away_52w_high_pct": db.num(r.get("away_52w_high_pct"), 2),
            "delivery_accumulation_days": acc.get(sym),
            "deal_net_10s_cr": deal_net.get(sym),
            "active_setups": setups.get(sym, []) if has_setups else None,
        })
    present = [r for r in rows if r.get(sort) is not None]
    missing = [r for r in rows if r.get(sort) is None]
    present.sort(key=lambda r: r[sort], reverse=descending)
    return Result(
        as_of=resolved, rows=present + missing, sources=["indicators_daily", "stocks_master", "deals"],
        extra={"group": {"id": gid, "level": level_key, "name": name}, "floor": floor, "floor_label": floor_label(floor)},
        notes=[] if has_setups else ["Active setups need setup_daily (not built yet); use the Desk queues meanwhile."],
        metric_keys=MEMBER_METRICS,
    )


def index_history(as_of: date | None, gid: str, floor: str = "1000", days: int = 500) -> Result:
    """The group's own equal-weight index (rebased to 100 at the start of history) with its 50/200 EMA."""
    level_key, name = parse_group_id(gid)
    floor_value(floor)
    days = max(20, min(int(days), 2000))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        long = _long(con, resolved, level_key, floor) if db.table_exists(con, "group_daily") else None
        src = "group_daily"
        if long is None or long.empty or not (long["group_name"] == name).any():
            with _LIVE_LOCK:
                live = db.cached("groups.live", (resolved, floor), lambda: _live_frames(con, resolved, floor))
            long, src = live.get(level_key, pd.DataFrame()), "live"
    g = long[long["group_name"] == name] if not long.empty else long
    if g.empty or "ew_index" not in g.columns:
        return unavailable(resolved, f"no index history for group {gid!r} at this floor", [src])
    g = g[g["trade_date"] <= pd.Timestamp(resolved)].sort_values("trade_date").tail(days)
    rows = [{"trade_date": db.to_date(r["trade_date"]), "ew_index": db.num(r["ew_index"], 3),
             "ema_50": db.num(r.get("ew_index_ema50"), 3), "ema_200": db.num(r.get("ew_index_ema200"), 3),
             "abs_trend": db.text(r.get("abs_trend")), "health": db.num(r.get("health"), 1)}
            for r in g.to_dict("records")]
    status, reason = ("ok", None) if src == "group_daily" else (
        STATUS_PARTIAL, "computed live from indicators_daily (group_daily does not cover this floor); ~260 sessions")
    return Result(as_of=rows[-1]["trade_date"] or resolved, rows=rows, status=status, reason=reason,
                  sources=["group_daily"] if src == "group_daily" else ["indicators_daily"],
                  extra={"group": {"id": gid, "level": level_key, "name": name}, "floor": floor, "source": src,
                         "index_rule": "equal-weight members, cumulative product of (1 + mean member return), start = 100"},
                  metric_keys=["group_abs_trend", "group_health"])


def _parents(con: Any) -> dict[str, dict[str, str]]:
    """Most common parent of every taxonomy group, per child level (current stocks_master mapping)."""
    cols = [universe.LEVELS[k][0] for k in LEVEL_ORDER]
    recs = con.execute(f"SELECT {', '.join(cols)}, count(*) FROM stocks_master WHERE upper(symbol) <> 'TOTAL' "
                       f"GROUP BY ALL").fetchall()
    out: dict[str, dict[str, str]] = {}
    for i in range(1, len(LEVEL_ORDER)):
        votes: dict[str, Counter] = {}
        for r in recs:
            child, parent = r[i], r[i - 1]
            if child and parent:
                votes.setdefault(str(child).strip(), Counter())[str(parent).strip()] += int(r[-1])
        out[LEVEL_ORDER[i]] = {c: v.most_common(1)[0][0] for c, v in votes.items()}
    return out


def treemap(as_of: date | None, floor: str = "1000") -> Result:
    """Every group of every level at as_of with its parent, Health, 21d return and 20-session average turnover
    (tile size) — the Groups taxonomy heatmap."""
    floor_value(floor)
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        parents = db.cached("groups.parents", (), lambda: _parents(con))
        frames = {lvl: _frame(con, resolved, lvl, floor) for lvl in LEVEL_ORDER}
    rows: list[dict[str, Any]] = []
    srcs = set()
    d_out = None
    for lvl, (df, src) in frames.items():
        if df.empty:
            continue
        srcs.add(src)
        hist = df[df["trade_date"] <= pd.Timestamp(resolved)]
        last, d = _last_rows(hist, resolved)
        d_out = d_out or d
        to20 = (pd.to_numeric(hist["turnover_cr"], errors="coerce").groupby(hist["group_name"]).apply(lambda s: s.tail(20).mean())
                if "turnover_cr" in hist.columns else pd.Series(dtype=float))
        for r in last.to_dict("records"):
            name = str(r["group_name"])
            parent = parents.get(lvl, {}).get(name) if lvl != "broad_sector" else None
            prev = LEVEL_ORDER[LEVEL_ORDER.index(lvl) - 1] if lvl != "broad_sector" else None
            rows.append({
                "id": group_id(lvl, name), "level": lvl, "group_name": name,
                "parent_id": group_id(prev, parent) if prev and parent else None,
                "stocks": db.integer(r.get("stocks")), "turnover_20d_cr": db.num(to20.get(name), 2),
                "health": db.num(r.get("health"), 1), "return_ew_21d": db.num(r.get("return_ew_21d"), 2),
                "rrg_quadrant": db.text(r.get("rrg_quadrant")), "quadrant_note": db.text(r.get("quadrant_note")),
                "abs_trend": db.text(r.get("abs_trend")),
            })
    if not rows:
        return unavailable(resolved, "no group data on or before as_of", ["group_daily", "indicators_daily"])
    live = "live" in srcs
    return Result(as_of=d_out or resolved, rows=rows, status=STATUS_PARTIAL if live else "ok",
                  reason=_live_reason(True, floor) if live else None,
                  sources=sorted({"group_daily" if s == "group_daily" else "indicators_daily" for s in srcs} | {"stocks_master"}),
                  extra={"floor": floor, "floor_label": floor_label(floor),
                         "size": "average daily turnover over the last 20 sessions, ₹ Cr",
                         "parents": "most common parent in today's stocks_master mapping"},
                  metric_keys=["group_health", "group_return_ew_21d"])
