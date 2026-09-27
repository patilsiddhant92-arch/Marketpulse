"""group_daily — taxonomy-group strength, rotation and money flow per session (spec §4.5, §7.4).

One row per (trade_date, level, floor, group_name):
  level  ∈ Broad Sector · Sector · Broad Industry · Industry (stocks_master columns
           broad_sector, sector, broad_industry, industry — current mapping, documented limitation)
  floor  ∈ 'all' · '1000cr' (member market cap >= ₹1,000 Cr on that session) ·
           'watch' (₹300 Cr <= market cap < ₹1,000 Cr — the API's watch band, App/services/groups.py)

Market cap on session t (point-in-time):
  1. security_reference_daily.market_cap_cr as-of t (effective_date <= t, at most 10 calendar days
     old) when a `reference` frame is passed;
  2. otherwise stocks_master.market_cap_cr scaled by close_t / close on the master's
     market_cap_date ("price-scaled current": exact for constant share count, and exact across
     splits/bonuses once prices are adjusted). Column mcap_basis says which one a row used.

Unadjusted corporate actions: a 1-day move <= -35 % or >= +100 % (SPLIT_DOWN / SPLIT_UP) is treated as an
unadjusted split/bonus; that member's returns over any window containing it are excluded (never filled).
Same rule and constants as the live API fallback (App/services/groups.py imports them from here).

Everything is vectorised: per-stock features via groupby-shift, group stats via one
groupby-sum per (level, floor), time-series stats via groupby rolling/ewm on an integer group id.

JdK RS-Ratio / RS-Momentum, PEER-RELATIVE (deterministic re-implementation, not the proprietary formula):
  G_t   = equal-weight group index (ew_index), cumulative product of (1 + ret_ew_1d)
  RS_t  = G_t / MidSml400_close_t
  rs_ratio_self_t    = 100 * EMA10(RS)_t / EMA50(RS)_t         (the group's smoothed RS trend vs its OWN history)
  rs_momentum_self_t = 100 * rs_ratio_self_t / rs_ratio_self_{t-10 group sessions}   (its 10-session rate of change)
  Cross-sectional normalisation per (trade_date, level, floor) over groups with >= 3 members (JdK practice):
  RS-Ratio_t    = 100 + 10 * z(rs_ratio_self_t)      z = (x - peer mean) / peer std
  RS-Momentum_t = 100 + 10 * z(rs_momentum_self_t)
  so about half the groups sit above 100 on each axis by construction and "Leading" means strong vs PEERS,
  not vs a falling benchmark. NULL when fewer than 4 eligible peers or zero dispersion.
  Quadrant: Leading (ratio>=100, mom>=100) · Weakening (>=100, <100) · Lagging (<100, <100) · Improving (<100, >=100)
Absolute context and Health (see add_health_columns): abs_trend (ew_index vs its EMA50/EMA200 and EMA50 slope),
  quadrant_note ("Leading but falling" ...), health 0-100 = 0.40 relative + 0.35 absolute + 0.25 breadth, health_rank.
Rank: groups with >= 3 members ranked within (date, level, floor) by rank_score =
  mean(excess_midsml_21d, excess_midsml_63d) of the equal-weight return; 1 = strongest.
  rank_chg_h = rank h group-sessions ago - rank today (positive = moved up).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import (
    MIDSML400,
    NIFTY50,
    boolcol,
    clean_symbols,
    index_series,
    new_high_low_flags,
    normalise_dates,
    num,
    point_in_time_mcap,
    prep_indicators,
)
from .deal_session_net import normalise_deals

LEVELS = {"Broad Sector": "broad_sector", "Sector": "sector", "Broad Industry": "broad_industry", "Industry": "industry"}
# floor label -> (min mcap inclusive, max mcap exclusive); None = unbounded. Same bands as App/services/groups.py.
FLOORS: dict[str, tuple[float | None, float | None]] = {"all": (None, None), "1000cr": (1000.0, None),
                                                        "watch": (300.0, 1000.0)}
HORIZONS = (1, 5, 21, 63)
MIN_MEMBERS_RANK = 3
RS_FAST, RS_SLOW, RS_MOM_LAG = 10, 50, 10
CONCENTRATION_TOP1_SHARE = 50.0
DEAL_WINDOW = 10
SPLIT_DOWN, SPLIT_UP = -0.35, 1.0  # 1-day move treated as an unadjusted corporate action

INDICATOR_COLUMNS = (
    "close_price", "prev_close", "turnover_cr", "ema_50", "ema_200", "trend_template_pass", "delivery_qty",
    "delivery_pct", "avg_delivery_pct_20d", "high_price", "low_price", "high_52w", "low_52w", "high_52w_date",
)

OUTPUT_COLUMNS = [
    "trade_date", "level", "floor", "group_name", "members", "mcap_total_cr", "mcap_basis",
    *[f"ret_ew_{h}d" for h in HORIZONS], *[f"ret_cw_{h}d" for h in HORIZONS],
    "excess_nifty_21d", "excess_nifty_63d", "excess_midsml_21d", "excess_midsml_63d",
    "excess_cw_midsml_21d", "excess_cw_midsml_63d",
    "rs_ratio", "rs_momentum", "rrg_quadrant", "days_in_quadrant", "rs_ratio_self", "rs_momentum_self",
    "ew_index", "ew_index_ema50", "ew_index_ema200", "abs_trend", "quadrant_note", "health", "health_rank",
    "rank_score", "rank", "rank_n", "rank_chg_5d", "rank_chg_20d", "rank_chg_63d",
    "pct_above_50ema", "pct_above_200ema", "pct_trend_template", "new_highs_52w", "pct_new_highs_52w",
    "turnover_cr", "turnover_share_pct", "turnover_share_5d_avg", "turnover_share_20d_avg",
    "turnover_share_delta", "turnover_share_5d_chg_5d", "top1_turnover_share_pct", "concentration_flag",
    "delivery_value_cr", "deliv_acc_1d_pct", "deliv_acc_10d_pct", "acc_day_members_pct",
    "deal_net_10s_cr",
]


PEER_MIN = 4                 # eligible peers needed for a cross-sectional z-score
TREND_SLOPE_LAG = 10         # EMA50 slope = EMA50_t / EMA50_{t-10} - 1
HEALTH_WEIGHTS = {"relative": 0.40, "absolute": 0.35, "breadth": 0.25}
QUADRANTS = ("Leading", "Weakening", "Lagging", "Improving")


def _quadrant(rr: pd.Series, mm: pd.Series) -> np.ndarray:
    return np.select([(rr >= 100) & (mm >= 100), (rr >= 100) & (mm < 100), (rr < 100) & (mm < 100), (rr < 100) & (mm >= 100)],
                     list(QUADRANTS), default=None)


def _streak(values: np.ndarray, gid: pd.Series) -> np.ndarray:
    """1-based run length of equal values per group (rows sorted by gid, date); NaN where value is NULL."""
    key = pd.Series(values, index=gid.index).fillna("__NULL__")
    new = (key != key.shift()) | (gid != gid.shift())
    run = new.cumsum()
    return np.where(pd.isna(values), np.nan, (run.groupby(run).cumcount() + 1).to_numpy(dtype=float))


def add_health_columns(df: pd.DataFrame, gid: str, part: list[str], *, members: str = "members",
                       ret1: str = "ret_ew_1d", ret21: str = "ret_ew_21d", b50: str = "pct_above_50ema",
                       b200: str = "pct_above_200ema", ratio_self: str = "rs_ratio_self",
                       mom_self: str = "rs_momentum_self") -> pd.DataFrame:
    """Peer-relative RRG, absolute trend, quadrant note and Health, in place on a frame sorted by (gid, date).

    Shared by the nightly builder and the API (App/services/groups.py) so both give identical numbers.
    Input: one row per (group, session) with the named columns (returns / breadth in percent units);
    `part` = columns that define a cross-section (e.g. trade_date, level, floor).
    Adds: ew_index, ew_index_ema50, ew_index_ema200, rs_ratio, rs_momentum, rrg_quadrant, days_in_quadrant,
    abs_trend, quadrant_note, health, health_rank.

      RS-Ratio    = 100 + 10 * z(rs_ratio_self)    z across groups with >= 3 members in the same cross-section
      RS-Momentum = 100 + 10 * z(rs_momentum_self)
      abs_trend   = Up   if ew_index > EMA50, EMA50 rising over 10 sessions and (EMA200 unknown or EMA50 > EMA200)
                    Down if ew_index < EMA50 and EMA50 falling over 10 sessions;  Flat otherwise
      quadrant_note = "<Q> but falling"    Leading/Improving with 21d EW return < 0
                      "<Q>, narrow breadth" Leading/Improving with < 50 % of members above their 50 EMA
                      "<Q> but rising"      Weakening/Lagging with 21d return > 0 and >= 50 % above 50 EMA
      health = 0.40 relative + 0.35 absolute + 0.25 breadth (each 0-100):
        relative = clip(50 + 2.5 (RS-Ratio - 100) + 1.5 (RS-Momentum - 100), 0, 100)
        absolute = 0.7 trend_points + 0.3 clip(50 + 5 ret_ew_21d, 0, 100)
                   trend_points = 100 x share of [idx > EMA50, EMA50 > EMA200, EMA50 rising] that hold (known ones)
                   (the 21d-return leg alone until EMA50 has formed)
        breadth  = 0.7 % above 50 EMA + 0.3 % above 200 EMA (whichever is known)
      health_rank = rank by health (1 = healthiest) among groups with >= 3 members in the cross-section.
    """
    g = df[gid]
    r1 = (pd.to_numeric(df[ret1], errors="coerce") / 100.0).fillna(0.0).clip(lower=-0.99)
    idx = np.exp(np.log1p(r1).groupby(g, sort=False).cumsum())
    df["ew_index"] = idx * 100.0
    gb = df.groupby(g, sort=False)["ew_index"]
    e50 = gb.ewm(span=50, adjust=False, min_periods=50).mean().reset_index(level=0, drop=True).sort_index()
    e200 = gb.ewm(span=200, adjust=False, min_periods=200).mean().reset_index(level=0, drop=True).sort_index()
    df["ew_index_ema50"], df["ew_index_ema200"] = e50, e200
    slope = e50 / e50.groupby(g, sort=False).shift(TREND_SLOPE_LAG) - 1.0
    lvl = df["ew_index"]
    up = (lvl > e50) & (slope > 0) & (e200.isna() | (e50 > e200))
    down = (lvl < e50) & (slope < 0)
    df["abs_trend"] = np.where(e50.isna() | slope.isna(), None, np.where(up, "Up", np.where(down, "Down", "Flat")))

    n_mem = pd.to_numeric(df[members], errors="coerce")
    elig = n_mem >= MIN_MEMBERS_RANK
    keys = [df[c] for c in part]
    for src, dst in ((ratio_self, "rs_ratio"), (mom_self, "rs_momentum")):
        x = pd.to_numeric(df[src], errors="coerce")
        grp = x.where(elig).groupby(keys, sort=False)
        mu, sd, n = grp.transform("mean"), grp.transform("std"), grp.transform("count")
        ok = (n >= PEER_MIN) & (sd > 1e-12)
        df[dst] = (100.0 + 10.0 * (x - mu) / sd.where(ok)).where(ok & x.notna())
    rr, mm = df["rs_ratio"], df["rs_momentum"]
    quad = _quadrant(rr, mm)
    df["rrg_quadrant"] = quad
    df["days_in_quadrant"] = _streak(quad, g)

    ret = pd.to_numeric(df[ret21], errors="coerce")
    br50 = pd.to_numeric(df[b50], errors="coerce")
    br200 = pd.to_numeric(df[b200], errors="coerce") if b200 in df.columns else pd.Series(np.nan, index=df.index)
    q = pd.Series(quad, index=df.index, dtype=object)
    pos = q.isin(["Leading", "Improving"]).to_numpy()
    neg = q.isin(["Weakening", "Lagging"]).to_numpy()
    qs = q.fillna("").astype(str)
    note = np.where(pos & (ret < 0).to_numpy(), qs + " but falling",
                    np.where(pos & (br50 < 50).to_numpy(), qs + ", narrow breadth",
                             np.where(neg & (ret > 0).to_numpy() & (br50 >= 50).to_numpy(), qs + " but rising", None)))
    df["quadrant_note"] = note

    rel = (50.0 + 2.5 * (rr - 100.0) + 1.5 * (mm - 100.0)).clip(0.0, 100.0)
    conds = [(lvl > e50).astype(float).where(e50.notna()),
             (e50 > e200).astype(float).where(e50.notna() & e200.notna()),
             (slope > 0).astype(float).where(slope.notna())]
    known = sum(c.notna().astype(float) for c in conds)
    hits = sum(c.fillna(0.0) for c in conds)
    trend_pts = 100.0 * hits / known.where(known > 0)
    ret_pts = (50.0 + 5.0 * ret).clip(0.0, 100.0)
    absolute = (0.7 * trend_pts + 0.3 * ret_pts).where(trend_pts.notna(), ret_pts)  # EMAs not formed yet: return leg
    breadth = (0.7 * br50 + 0.3 * br200).where(br200.notna(), br50)
    w = HEALTH_WEIGHTS
    df["health"] = (w["relative"] * rel + w["absolute"] * absolute + w["breadth"] * breadth).round(1)
    hs = df["health"].where(elig)
    df["health_rank"] = hs.groupby(keys, sort=False).rank(ascending=False, method="min")
    return df


def _taxonomy(master: pd.DataFrame) -> pd.DataFrame:
    m = clean_symbols(master.copy())
    keep = ["symbol", *LEVELS.values(), "market_cap_cr", "market_cap_date"]
    for c in keep:
        if c not in m.columns:
            m[c] = np.nan
    m = m[keep].drop_duplicates("symbol", keep="last")
    for c in LEVELS.values():
        s = m[c].astype("string").str.strip()
        m[c] = s.where(s != "")
    m["market_cap_cr"] = pd.to_numeric(m["market_cap_cr"], errors="coerce")
    m["market_cap_date"] = normalise_dates(m["market_cap_date"])
    return m


def _stock_frame(indicators, master, reference, deals) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    ind = prep_indicators(indicators, INDICATOR_COLUMNS)
    tax = _taxonomy(master)
    ind = ind.merge(tax, on="symbol", how="inner")
    ind = ind.sort_values(["symbol", "trade_date"], kind="mergesort").reset_index(drop=True)
    sym = ind["symbol"]
    c = num(ind, "close_price")
    gc = c.groupby(sym, sort=False)

    f = pd.DataFrame({"trade_date": ind["trade_date"], "symbol": sym})
    for lvl_col in LEVELS.values():
        f[lvl_col] = ind[lvl_col].astype("category")

    # Market cap: reference as-of, else price-scaled current (shared helper).
    mcap, basis = point_in_time_mcap(ind, tax, reference)
    f["mcap"] = mcap.to_numpy()
    f["mcap_ref"] = (basis == "reference_asof").to_numpy(dtype=float)
    f["mcap_known"] = mcap.notna().to_numpy(dtype=float)

    f["n"] = 1.0
    prev = gc.shift(1)
    if "prev_close" in ind.columns:  # first stored row: the exchange's previous close
        prev = prev.fillna(num(ind, "prev_close"))
    r1_raw = c / prev.where(prev > 0) - 1.0
    bad = ((r1_raw <= SPLIT_DOWN) | (r1_raw >= SPLIT_UP)).fillna(False)
    n_bad = bad.astype(int).groupby(sym, sort=False).cumsum()
    for h in HORIZONS:
        ch = gc.shift(h)
        clean = (n_bad - n_bad.groupby(sym, sort=False).shift(h)) == 0
        r_h = (c / ch - 1.0).where(clean)
        known = r_h.notna()
        f[f"rs_{h}"] = r_h.fillna(0.0).to_numpy()
        f[f"rc_{h}"] = known.astype(float).to_numpy()
        w = (mcap * ch / c).where(known & mcap.notna())
        f[f"cwd_{h}"] = w.fillna(0.0).to_numpy()
        f[f"cwn_{h}"] = (w * r_h).fillna(0.0).to_numpy()
    f["r1"] = (c / gc.shift(1) - 1.0).where(~bad).to_numpy()

    def add_ratio(name: str, s: pd.Series) -> None:
        f[name] = s.fillna(0.0).to_numpy()
        f[name + "_k"] = s.notna().astype(float).to_numpy()

    for col, name in (("ema_50", "a50"), ("ema_200", "a200")):
        ref = num(ind, col)
        add_ratio(name, (c > ref).astype(float).where(c.notna() & ref.notna()))
    add_ratio("tt", boolcol(ind, "trend_template_pass"))
    flags = new_high_low_flags(ind)
    add_ratio("nh", flags["new_high"])
    to = num(ind, "turnover_cr")
    f["turnover"] = to.fillna(0.0).to_numpy()
    f["turnover_max"] = to.to_numpy()
    dv = num(ind, "delivery_qty") * c / 1e7
    r1 = f["r1"]
    f["dv"] = dv.fillna(0.0).to_numpy()
    f["dv_signed"] = (dv * np.sign(r1)).fillna(0.0).to_numpy()
    acc = ((r1 > 0) & (num(ind, "delivery_pct") > num(ind, "avg_delivery_pct_20d"))).astype(float)
    acc_known = r1.notna() & num(ind, "delivery_pct").notna() & num(ind, "avg_delivery_pct_20d").notna()
    add_ratio("acc", acc.where(acc_known))

    deal_start = None
    f["deal_net"] = 0.0
    if deals is not None:
        p = normalise_deals(deals)
        if not p.empty:
            deal_start = p["trade_date"].min()
            p = p[p["clientele"] != "PROP"]
            p["net"] = np.where(p["side"] == "BUY", p["value_cr"], -p["value_cr"])
            net = p.groupby(["symbol", "trade_date"])["net"].sum().rename("deal_net_sym").reset_index()
            f = f.merge(net, on=["symbol", "trade_date"], how="left")
            f["deal_net"] = f["deal_net_sym"].fillna(0.0)
            f = f.drop(columns=["deal_net_sym"])
    return f, deal_start


def _aggregate(f: pd.DataFrame, level: str, col: str, floor: str, bounds: tuple[float | None, float | None],
               dates: pd.DatetimeIndex, dcode: np.ndarray) -> pd.DataFrame:
    """Sum every feature column per (date, group) with one np.bincount per column."""
    cat = f[col].cat
    codes = cat.codes.to_numpy()
    n_groups = len(cat.categories)
    mask = codes >= 0
    lo, hi = bounds
    if lo is not None:
        mask &= (f["mcap"].to_numpy() >= lo)
    if hi is not None:
        mask &= (f["mcap"].to_numpy() < hi)
    key = dcode[mask].astype(np.int64) * n_groups + codes[mask]
    size = len(dates) * n_groups
    counts = np.bincount(key, minlength=size)
    present = np.flatnonzero(counts)
    sums = [c for c in f.columns if c not in ("trade_date", "symbol", "turnover_max", "r1", *LEVELS.values())]
    data = {c: np.bincount(key, weights=np.nan_to_num(f[c].to_numpy(dtype=float)[mask]), minlength=size)[present]
            for c in sums}
    tmax = pd.Series(f["turnover_max"].to_numpy(dtype=float)[mask]).groupby(key).max()
    agg = pd.DataFrame(data)
    agg["turnover_max"] = tmax.reindex(present).to_numpy()
    agg.insert(0, "trade_date", dates[present // n_groups])
    agg.insert(1, "level", level)
    agg.insert(2, "floor", floor)
    agg.insert(3, "group_name", np.asarray(cat.categories.astype(str), dtype=object)[present % n_groups])
    return agg


def _index_returns(index_daily: pd.DataFrame | None, name: str) -> pd.DataFrame:
    s = index_series(index_daily, name)
    out = pd.DataFrame(index=s.index)
    out["close"] = s["close_price"]
    for h in (1, 21, 63):
        out[f"ret_{h}"] = s["close_price"] / s["close_price"].shift(h) - 1.0
    return out


def build_group_daily(
    indicators: pd.DataFrame,
    master: pd.DataFrame,
    index_daily: pd.DataFrame,
    deals: pd.DataFrame | None = None,
    reference: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if indicators is None or indicators.empty or master is None or master.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    f, deal_start = _stock_frame(indicators, master, reference, deals)
    if f.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    dcode, dates_u = pd.factorize(f["trade_date"], sort=True)
    dates_u = pd.DatetimeIndex(dates_u)
    parts = [_aggregate(f, lvl, col, fl, mn, dates_u, dcode) for lvl, col in LEVELS.items() for fl, mn in FLOORS.items()]
    del f
    G = pd.concat(parts, ignore_index=True)
    del parts

    out = pd.DataFrame({"trade_date": G["trade_date"], "level": G["level"], "floor": G["floor"],
                        "group_name": G["group_name"], "members": G["n"].astype(int)})
    out["mcap_total_cr"] = G["mcap"].where(G["mcap_known"] > 0)
    out["mcap_basis"] = np.where(G["mcap_ref"] >= 0.5 * G["n"], "reference_asof", "price_scaled_current")
    for h in HORIZONS:
        out[f"ret_ew_{h}d"] = (G[f"rs_{h}"] / G[f"rc_{h}"].where(G[f"rc_{h}"] > 0)) * 100.0
        out[f"ret_cw_{h}d"] = (G[f"cwn_{h}"] / G[f"cwd_{h}"].where(G[f"cwd_{h}"] > 0)) * 100.0

    ms = _index_returns(index_daily, MIDSML400)
    nf = _index_returns(index_daily, NIFTY50)
    dates = out["trade_date"]
    for h in (21, 63):
        ms_r = dates.map(ms[f"ret_{h}"]) * 100.0 if not ms.empty else np.nan
        nf_r = dates.map(nf[f"ret_{h}"]) * 100.0 if not nf.empty else np.nan
        out[f"excess_nifty_{h}d"] = out[f"ret_ew_{h}d"] - nf_r
        out[f"excess_midsml_{h}d"] = out[f"ret_ew_{h}d"] - ms_r
        out[f"excess_cw_midsml_{h}d"] = out[f"ret_cw_{h}d"] - ms_r

    def ratio(num_col: str) -> pd.Series:
        return G[num_col] / G[num_col + "_k"].where(G[num_col + "_k"] > 0) * 100.0

    out["pct_above_50ema"] = ratio("a50")
    out["pct_above_200ema"] = ratio("a200")
    out["pct_trend_template"] = ratio("tt")
    out["new_highs_52w"] = G["nh"].where(G["nh_k"] >= 0.5 * G["n"])
    out["pct_new_highs_52w"] = (G["nh"] / G["nh_k"] * 100.0).where(G["nh_k"] >= 0.5 * G["n"])
    out["turnover_cr"] = G["turnover"]
    tot = out.groupby(["trade_date", "level", "floor"], sort=False)["turnover_cr"].transform("sum")
    out["turnover_share_pct"] = (out["turnover_cr"] / tot.where(tot > 0)) * 100.0
    out["top1_turnover_share_pct"] = (G["turnover_max"] / G["turnover"].where(G["turnover"] > 0)) * 100.0
    out["concentration_flag"] = (out["top1_turnover_share_pct"] >= CONCENTRATION_TOP1_SHARE) & (out["members"] >= MIN_MEMBERS_RANK)
    out["delivery_value_cr"] = G["dv"].where(G["dv"] > 0)
    out["deliv_acc_1d_pct"] = (G["dv_signed"] / G["dv"].where(G["dv"] > 0)) * 100.0
    out["acc_day_members_pct"] = ratio("acc")
    out["_deal"] = G["deal_net"].to_numpy()
    del G

    # ---- time series per group (integer id; rows sorted by id, date) ----
    out = out.sort_values(["level", "floor", "group_name", "trade_date"], kind="mergesort").reset_index(drop=True)
    gid = out.groupby(["level", "floor", "group_name"], sort=False).ngroup()
    out["_gid"] = gid.to_numpy()
    gb = out.groupby("_gid", sort=False)

    def roll(col: str, w: int, how: str = "mean") -> np.ndarray:
        r = getattr(gb[col].rolling(w, min_periods=w), how)()
        return r.reset_index(level=0, drop=True).sort_index().to_numpy()

    out["turnover_share_5d_avg"] = roll("turnover_share_pct", 5)
    out["turnover_share_20d_avg"] = roll("turnover_share_pct", 20)
    out["turnover_share_delta"] = out["turnover_share_5d_avg"] - out["turnover_share_20d_avg"]
    gb = out.groupby("_gid", sort=False)
    out["turnover_share_5d_chg_5d"] = out["turnover_share_5d_avg"] - gb["turnover_share_5d_avg"].shift(5)

    out["_dvs"] = (out["deliv_acc_1d_pct"] / 100.0 * out["delivery_value_cr"]).fillna(0.0)
    out["_dv"] = out["delivery_value_cr"].fillna(0.0)
    gb = out.groupby("_gid", sort=False)
    dvs10 = roll("_dvs", 10, "sum")
    dv10 = roll("_dv", 10, "sum")
    out["deliv_acc_10d_pct"] = np.where(dv10 > 0, dvs10 / np.where(dv10 > 0, dv10, 1.0) * 100.0, np.nan)

    # RRG: self-normalised RS trend per group, then peer-relative (cross-sectional) axes + Health.
    bench = out["trade_date"].map(ms["close"]) if not ms.empty else pd.Series(np.nan, index=out.index)
    r1 = (out["ret_ew_1d"] / 100.0).fillna(0.0)
    lvl = np.exp(np.log1p(r1.clip(lower=-0.99)).groupby(out["_gid"], sort=False).cumsum())
    out["_rs"] = lvl / bench
    gb = out.groupby("_gid", sort=False)
    fast = gb["_rs"].ewm(span=RS_FAST, adjust=False, min_periods=RS_FAST).mean().reset_index(level=0, drop=True).sort_index()
    slow = gb["_rs"].ewm(span=RS_SLOW, adjust=False, min_periods=RS_SLOW).mean().reset_index(level=0, drop=True).sort_index()
    out["rs_ratio_self"] = 100.0 * fast / slow
    out["rs_momentum_self"] = 100.0 * out["rs_ratio_self"] / out.groupby("_gid", sort=False)["rs_ratio_self"].shift(RS_MOM_LAG)
    add_health_columns(out, "_gid", ["trade_date", "level", "floor"])

    # Rank vs benchmark
    score = (out["excess_midsml_21d"] + out["excess_midsml_63d"]) / 2.0
    eligible = (out["members"] >= MIN_MEMBERS_RANK) & score.notna()
    out["rank_score"] = score
    out["_score_rank"] = score.where(eligible)
    out["rank"] = out.groupby(["trade_date", "level", "floor"], sort=False)["_score_rank"].rank(ascending=False, method="min")
    out["rank_n"] = out.groupby(["trade_date", "level", "floor"], sort=False)["_score_rank"].transform("count")
    gb = out.groupby("_gid", sort=False)
    for h in (5, 20, 63):
        out[f"rank_chg_{h}d"] = gb["rank"].shift(h) - out["rank"]

    # Deals: 10-session net (ex-PROP), NULL until deal history covers the whole window.
    if deal_start is None:
        out["deal_net_10s_cr"] = np.nan
    else:
        d10 = roll("_deal", DEAL_WINDOW, "sum")
        window_start = gb["trade_date"].shift(DEAL_WINDOW - 1)
        covered = (window_start >= deal_start).to_numpy(dtype=bool)
        out["deal_net_10s_cr"] = np.where(covered, d10, np.nan)
    out = out.drop(columns=[c for c in out.columns if c.startswith("_")])
    return out[OUTPUT_COLUMNS]
