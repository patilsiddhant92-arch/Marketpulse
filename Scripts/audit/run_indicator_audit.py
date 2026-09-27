"""End-to-end indicator / screen / Desk-queue audit against the live DB (read-only).

    python Scripts/audit/run_indicator_audit.py --out <dir> [--sections stored,rs,pit,darvas,screens,queues]

Stored indicators_daily values are compared with the independent reference implementation in
Scripts/audit/indicator_reference.py on a fixed sample (~60 symbols, every session of their
history, highlighted on 8 dates) and, for RS / screens / queues, across the whole universe on the
audit dates. Results are written as JSON (one file per section) and summarised on stdout.
Memory: symbols are processed in chunks; DuckDB is capped at 512 MB.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Scripts"))

from Scripts.audit import indicator_reference as ref  # noqa: E402

LIVE_DB = Path(r"D:\Sid\MarketPulse2.0\Database\marketpulse.duckdb")
AUDIT_DATE = pd.Timestamp("2026-09-25")
TARGET_DATES = ["2021-03-15", "2021-11-10", "2022-06-20", "2023-02-14", "2023-10-05", "2024-08-06",
                "2025-07-15", "2026-09-25"]
SPECIAL = ["GOODLUCK", "HEGAM", "NAZARA", "BERGEPAINT", "ZYDUSWELL", "AARTECH", "SETFGOLD", "MBECL",
           "RSL", "BATLIBOI", "UPHOT", "ANNAPURNA", "LANCER", "ADFFOODS"]
TOL = 1e-6


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(LIVE_DB), read_only=True)
    con.execute("SET memory_limit='512MB'")
    con.execute("SET threads=2")
    return con


def sessions(con) -> pd.DatetimeIndex:
    d = con.execute("SELECT DISTINCT trade_date FROM prices_daily ORDER BY 1").fetchdf()["trade_date"]
    return pd.DatetimeIndex(pd.to_datetime(d))


def sample_dates(con) -> list[pd.Timestamp]:
    cal = sessions(con)
    return [cal[cal <= pd.Timestamp(d)][-1] for d in TARGET_DATES]


def sample_symbols(con) -> list[str]:
    q = """
        WITH m AS (
            SELECT i.symbol, COALESCE(s.market_cap_cr, 0) AS mcap
            FROM indicators_daily i LEFT JOIN stocks_master s USING (symbol)
            WHERE i.trade_date = ? AND i.series = 'EQ'
        )
        SELECT symbol, mcap FROM m
    """
    m = con.execute(q, [AUDIT_DATE]).fetchdf()
    # deterministic pseudo-random order (Python's hash() is salted per process)
    m["h"] = m["symbol"].map(lambda s: sum(ord(ch) * (i + 7) for i, ch in enumerate(s)) % 997)
    large = m[m.mcap >= 50_000].sort_values("h").head(15)
    mid = m[(m.mcap >= 3_000) & (m.mcap < 50_000)].sort_values("h").head(16)
    small = m[(m.mcap > 0) & (m.mcap < 3_000)].sort_values("h").head(15)
    syms = list(dict.fromkeys([*large.symbol, *mid.symbol, *small.symbol, *SPECIAL]))
    have = set(con.execute("SELECT DISTINCT symbol FROM prices_daily").fetchdf()["symbol"])
    return [s for s in syms if s in have]


# ------------------------------------------------------------------------------------------
# comparison helpers
# ------------------------------------------------------------------------------------------
def cmp_num(stored, refv, tol=TOL) -> dict:
    s = pd.to_numeric(pd.Series(stored), errors="coerce").to_numpy(dtype=float)
    r = pd.to_numeric(pd.Series(refv), errors="coerce").to_numpy(dtype=float)
    fs, fr = np.isfinite(s), np.isfinite(r)
    both = fs & fr
    err = np.abs(s[both] - r[both]) / np.maximum(np.abs(r[both]), 1.0)
    return {
        "n": int(len(s)), "n_both": int(both.sum()),
        "stored_only": int((fs & ~fr).sum()), "ref_only": int((~fs & fr).sum()),
        "max_err": float(err.max()) if len(err) else 0.0,
        "p99_err": float(np.quantile(err, 0.99)) if len(err) else 0.0,
        "median_err": float(np.median(err)) if len(err) else 0.0,
        "n_over_tol": int((err > tol).sum()),
    }


def cmp_bool(stored, refv) -> dict:
    s = pd.Series(stored).fillna(False).astype(bool).to_numpy()
    r = pd.Series(refv).fillna(False).astype(bool).to_numpy()
    return {"n": int(len(s)), "stored_true": int(s.sum()), "ref_true": int(r.sum()),
            "stored_not_ref": int((s & ~r).sum()), "ref_not_stored": int((~s & r).sum())}


# ------------------------------------------------------------------------------------------
# Section 1: stored per-symbol indicators vs reference (sample symbols, full history)
# ------------------------------------------------------------------------------------------
STORED_COLS = [
    "close_price", "prev_close", "ema_10", "ema_20", "ema_50", "ema_100", "ema_150", "ema_200", "sma_50", "sma_150",
    "sma_200", "sma_200_rising", "rsi_14", "true_range", "atr_14", "atr_14_wilder", "atr_pct", "adr_20_pct",
    "return_5d_pct", "return_1m_pct", "return_3m_pct", "return_6m_pct", "rvol", "avg_volume_20d",
    "avg_delivery_pct_20d", "avg_delivery_qty_20d", "delivery_spike", "price_up_delivery_up", "delivery_pct",
    "turnover_cr", "avg_traded_value_cr_20d", "high_252d", "low_252d", "high_20d", "new_20d_high",
    "high_52w", "low_52w", "away_52w_high_pct", "away_52w_low_pct", "distance_below_52w", "nr7", "inside_bar",
    "rsi_14_w", "away_10ema_pct", "rs_percentile", "trend_template_pass_n", "trend_template_pass", "price_factor",
]

EXACT_NUM = {
    # stored column -> (reference column, warm-up bars skipped)
    "ema_10": ("ema_10", 9), "ema_20": ("ema_20", 19), "ema_50": ("ema_50", 49), "ema_100": ("ema_100", 99),
    "ema_150": ("ema_150", 149), "ema_200": ("ema_200", 199),
    "sma_50": ("sma_50", 0), "sma_150": ("sma_150", 0), "sma_200": ("sma_200", 0),
    "rsi_14": ("rsi_14", 0), "true_range": ("true_range", 0), "atr_14": ("atr_14", 0),
    "atr_14_wilder": ("atr_14_wilder", 0), "atr_pct": ("atr_pct", 0), "adr_20_pct": ("adr_20_pct", 0),
    "return_5d_pct": ("return_5d_pct", 0), "return_1m_pct": ("return_1m_pct", 0),
    "return_3m_pct": ("return_3m_pct", 0), "return_6m_pct": ("return_6m_pct", 0), "rvol": ("rvol", 0),
    "avg_volume_20d": ("avg_volume_20d", 0), "avg_delivery_pct_20d": ("avg_delivery_pct_20d", 0),
    "avg_delivery_qty_20d": ("avg_delivery_qty_20d", 0), "avg_traded_value_cr_20d": ("avg_traded_value_cr_20d", 0),
    "high_252d": ("high_252d", 0), "low_252d": ("low_252d", 0), "high_20d": ("high_20d", 0),
    "rsi_14_w": ("rsi_14_w", 0), "away_10ema_pct": ("away_10ema_pct", 0),
    "change_1d_pct": ("change_1d_pct", 0), "turnover_cr": ("turnover_cr_from_lacs", 0),
}
EXACT_BOOL = {"sma_200_rising": "sma_200_rising", "nr7": "nr7", "inside_bar": "inside_bar",
              "new_20d_high": "new_20d_high", "delivery_spike": "delivery_spike",
              "price_up_delivery_up": "price_up_delivery_up"}


def load_stored(con, symbols, cols=STORED_COLS, dates=None) -> pd.DataFrame:
    con.register("_st_syms", pd.DataFrame({"symbol": sorted(set(symbols))}))
    try:
        where = "WHERE symbol IN (SELECT symbol FROM _st_syms)"
        params = []
        if dates is not None:
            con.register("_st_dates", pd.DataFrame({"d": pd.to_datetime(list(dates))}))
            where += " AND trade_date IN (SELECT d FROM _st_dates)"
        df = con.execute(f"SELECT symbol, trade_date, {', '.join(cols)} FROM indicators_daily {where} "
                         "ORDER BY symbol, trade_date", params).fetchdf()
    finally:
        con.unregister("_st_syms")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def section_stored(con, symbols, dates) -> dict:
    px = ref.load_adjusted(con, symbols)
    refs = pd.concat([ref.compute_symbol(g) for _, g in px.groupby("symbol", sort=False)], ignore_index=True)
    st = load_stored(con, symbols)
    st["change_1d_pct"] = (st["close_price"] / st["prev_close"] - 1) * 100
    m = st.merge(refs, on=["symbol", "trade_date"], how="inner", suffixes=("", "_ref"))
    m["pos"] = m.groupby("symbol").cumcount()
    out: dict = {"symbols": symbols, "rows": int(len(m)), "dates": [str(d.date()) for d in dates], "num": {}, "bool": {},
                 "on_dates": {}, "convention": {}}
    on_dates = m["trade_date"].isin(dates)
    for col, (rcol, warm) in EXACT_NUM.items():
        rc = rcol if rcol != col else f"{col}_ref" if f"{col}_ref" in m.columns else rcol
        sel = m["pos"] >= warm
        out["num"][col] = cmp_num(m.loc[sel, col], m.loc[sel, rc])
        out["on_dates"][col] = cmp_num(m.loc[sel & on_dates, col], m.loc[sel & on_dates, rc])
    for col, rcol in EXACT_BOOL.items():
        rc = f"{rcol}_ref" if f"{rcol}_ref" in m.columns else rcol
        out["bool"][col] = cmp_bool(m[col], m[rc])
    # conventions --------------------------------------------------------------------------
    conv = out["convention"]
    for span in (10, 20, 50, 200):
        for k in (3, 5):
            sel = m["pos"] == k * span
            conv[f"ema_{span}_first_vs_smaseed_at_{k}x"] = cmp_num(m.loc[sel, f"ema_{span}_ref"] if f"ema_{span}_ref" in m else m.loc[sel, f"ema_{span}"], m.loc[sel, f"ema_{span}_smaseed"])
        sel = on_dates & (m["pos"] >= span - 1)
        conv[f"ema_{span}_first_vs_smaseed_on_dates"] = cmp_num(m.loc[sel, f"ema_{span}"], m.loc[sel, f"ema_{span}_smaseed"])
    for k in (50, 100, 250):
        sel = m["pos"] == k
        conv[f"rsi_first_vs_textbook_at_bar_{k}"] = cmp_num(m.loc[sel, "rsi_14"], m.loc[sel, "rsi_14_textbook"])
    conv["rsi_first_vs_textbook_on_dates"] = cmp_num(m.loc[on_dates, "rsi_14"], m.loc[on_dates, "rsi_14_textbook"])
    conv["nr7_zero_range_vs_textbook"] = cmp_bool(m["nr7"], m["nr7_textbook"])
    # 52-week: NSE reported (x cumulative price_factor) vs rolling 252-session adjusted high/low
    for side, hcol, rcol in (("high", "high_52w", "high_252d_ref"), ("low", "low_52w", "low_252d_ref")):
        r252 = m[rcol] if rcol in m else m[f"{side}_252d"]
        d = (m[hcol] / r252 - 1) * 100
        sel = np.isfinite(d)
        conv[f"{side}_52w_vs_rolling252_pct_diff"] = {
            "n": int(sel.sum()), "exact_1e-6": int((d[sel].abs() <= 1e-4).sum()),
            "within_1pct": int((d[sel].abs() <= 1).sum()), "within_5pct": int((d[sel].abs() <= 5).sum()),
            "p01": float(np.quantile(d[sel], 0.01)), "median": float(np.median(d[sel])), "p99": float(np.quantile(d[sel], 0.99)),
            "worst": m.loc[sel].assign(d=d[sel]).reindex(d[sel].abs().sort_values(ascending=False).index)
            [["symbol", "trade_date", hcol, "d"]].head(8).astype(str).to_dict("records"),
        }
    # derived columns from stored 52w: away/distance identities
    out["num"]["away_52w_high_pct(identity)"] = cmp_num(m["away_52w_high_pct"], (m["close_price"] / m["high_52w"] - 1) * 100)
    out["num"]["away_52w_low_pct(identity)"] = cmp_num(m["away_52w_low_pct"], (m["close_price"] / m["low_52w"] - 1) * 100)
    out["num"]["distance_below_52w(identity)"] = cmp_num(
        m["distance_below_52w"], ((m["high_52w"] - m["close_price"]) / m["high_52w"] * 100).clip(lower=0))
    # trend template: reference SMAs + stored (NSE convention) 52w + stored RS
    n, allp = ref.trend_template(
        m["close"].to_numpy(), m["sma_50_ref"].to_numpy(), m["sma_150_ref"].to_numpy(), m["sma_200_ref"].to_numpy(),
        m["sma_200_rising_ref"].fillna(False).to_numpy(), m["away_52w_low_pct"].to_numpy(),
        m["distance_below_52w"].to_numpy(), m["rs_percentile"].to_numpy())
    out["num"]["trend_template_pass_n"] = cmp_num(m["trend_template_pass_n"], n)
    out["bool"]["trend_template_pass"] = cmp_bool(m["trend_template_pass"], allp)
    # worst offenders for any numeric FAIL
    worst = {}
    for col, (rcol, warm) in EXACT_NUM.items():
        rc = f"{col}_ref" if f"{col}_ref" in m.columns and rcol == col else rcol
        if out["num"][col]["n_over_tol"] or out["num"][col]["stored_only"] or out["num"][col]["ref_only"]:
            sel = m["pos"] >= warm
            e = (m.loc[sel, col] - m.loc[sel, rc]).abs() / np.maximum(m.loc[sel, rc].abs(), 1)
            mism = e.fillna(np.inf).where(m.loc[sel, col].isna() != m.loc[sel, rc].isna(), e.fillna(0))
            idx = mism.sort_values(ascending=False).head(5).index
            worst[col] = m.loc[idx, ["symbol", "trade_date", "pos", col, rc]].astype(str).to_dict("records")
    for col, rcol in EXACT_BOOL.items():
        rc = f"{rcol}_ref" if f"{rcol}_ref" in m.columns else rcol
        bad = m[m[col].fillna(False).astype(bool) != m[rc].fillna(False).astype(bool)]
        if len(bad):
            worst[col] = bad[["symbol", "trade_date", "pos", col, rc]].head(5).astype(str).to_dict("records")
    out["worst"] = worst
    return out


# ------------------------------------------------------------------------------------------
# Section 2: RS percentile, whole universe on the sample dates
# ------------------------------------------------------------------------------------------
def section_rs(con, dates) -> dict:
    r = ref.rs_percentile_for_dates(con, dates)
    con.register("_rs_d", pd.DataFrame({"d": pd.to_datetime(list(dates))}))
    st = con.execute("SELECT symbol, trade_date, rs_percentile, rs_rank_t5 FROM indicators_daily "
                     "WHERE trade_date IN (SELECT d FROM _rs_d)").fetchdf()
    con.unregister("_rs_d")
    st["trade_date"] = pd.to_datetime(st["trade_date"])
    m = st.merge(r, on=["symbol", "trade_date"], how="left")
    out = {"all": cmp_num(m["rs_percentile"], m["rs_percentile_ref"]), "by_date": {}}
    for d, g in m.groupby("trade_date"):
        out["by_date"][str(d.date())] = {**cmp_num(g["rs_percentile"], g["rs_percentile_ref"]), "ranked": int(g["rs_percentile_ref"].notna().sum())}
    # rs_rank_t5 == rs_percentile 5 of the symbol's own sessions earlier
    lag = con.execute("""
        WITH x AS (SELECT symbol, trade_date, rs_percentile, rs_rank_t5,
                          lag(rs_percentile, 5) OVER (PARTITION BY symbol ORDER BY trade_date) AS l5
                   FROM indicators_daily WHERE trade_date >= ? - INTERVAL 60 DAY)
        SELECT rs_rank_t5, l5 FROM x WHERE trade_date = ?""", [AUDIT_DATE, AUDIT_DATE]).fetchdf()
    out["rs_rank_t5_lag_identity"] = cmp_num(lag["rs_rank_t5"], lag["l5"])
    return out


# ------------------------------------------------------------------------------------------
# Section 3: point-in-time — production per-symbol pass on truncated vs full history
# ------------------------------------------------------------------------------------------
def section_pit(con, symbols, dates) -> dict:
    import build_database as bd  # production code, used ONLY to detect look-ahead

    cols = [c for c in con.execute("SELECT * FROM prices_daily LIMIT 0").fetchdf().columns]
    sel = []
    for c in cols:
        if c.startswith("adj_"):
            continue
        if f"adj_{c}" in cols:
            sel.append(f"CAST(adj_{c} AS DOUBLE) AS {c}")
        else:
            sel.append(c)
    out = {"checked": [], "leaky_columns": {}}
    for sym in symbols:
        full = con.execute(f"SELECT {', '.join(sel)} FROM prices_daily WHERE symbol = ? ORDER BY trade_date", [sym]).fetchdf()
        full["trade_date"] = pd.to_datetime(full["trade_date"])
        if len(full) < 300:
            continue
        f_ind = bd._calc_single_symbol_indicators(full)
        for d in dates:
            if d >= full["trade_date"].max() or d < full["trade_date"].iloc[260]:
                continue
            t_ind = bd._calc_single_symbol_indicators(full[full["trade_date"] <= d].copy())
            a = f_ind[f_ind["trade_date"] == d].iloc[0]
            b = t_ind[t_ind["trade_date"] == d].iloc[0]
            out["checked"].append(f"{sym}@{d.date()}")
            for c in f_ind.columns:
                va, vb = a[c], b[c]
                if isinstance(va, (float, np.floating)) and isinstance(vb, (float, np.floating)):
                    same = (np.isnan(va) and np.isnan(vb)) or abs(va - vb) <= 1e-9 * max(1.0, abs(va))
                else:
                    same = (pd.isna(va) and pd.isna(vb)) or va == vb
                if not same:
                    out["leaky_columns"].setdefault(c, []).append(f"{sym}@{d.date()}: full={va} truncated={vb}")
    return out


# ------------------------------------------------------------------------------------------
# Section 4: screener presets on AUDIT_DATE — reference values vs screener.run
# ------------------------------------------------------------------------------------------
def last_rows_reference(con, symbols, chunk=250) -> pd.DataFrame:
    parts = []
    syms = sorted(symbols)
    for k in range(0, len(syms), chunk):
        px = ref.load_adjusted(con, syms[k:k + chunk], until=AUDIT_DATE)
        for _, g in px.groupby("symbol", sort=False):
            if g["trade_date"].iloc[-1] != AUDIT_DATE:
                continue
            r = ref.compute_symbol(g)
            parts.append(r.tail(6))  # last 6 bars (squeeze persistence needs 5)
    return pd.concat(parts, ignore_index=True)


def preset_eval(df: pd.DataFrame, rules) -> pd.Series:
    ok = pd.Series(True, index=df.index)
    for r in rules:
        f = r["field"]
        x = df[f]
        if r["op"] == "is_true":
            ok &= x.fillna(False).astype(bool)
        elif r["op"] == "is_false":
            ok &= (x == False)  # noqa: E712 - NULL fails
        else:
            y = df[r["ref"]] if "ref" in r else r["value"]
            opf = {"gt": np.greater, "gte": np.greater_equal, "lt": np.less, "lte": np.less_equal, "eq": np.equal}[r["op"]]
            with np.errstate(invalid="ignore"):
                ok &= pd.Series(opf(pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")), index=df.index).fillna(False)
    return ok


def section_screens(con, out_dir: Path) -> dict:
    from App.services import screener, universe

    snap = universe.snapshot_sql(con, extra_cols=screener.EXTRA_COLS + ", i.away_52w_high_pct AS raw_away_h, "
                                 "i.away_52w_low_pct AS raw_away_l, i.rs_percentile AS raw_rs, "
                                 "i.trend_template_pass AS raw_tt, i.band_remarks AS ind_band_remarks, "
                                 "m.band_remarks AS master_band_remarks")
    s = con.execute(f"WITH s AS ({snap}) SELECT * FROM s", [AUDIT_DATE]).fetchdf()
    # every preset and the Desk pool need market cap >= 1,000 Cr (a non-indicator input): only
    # those symbols need reference values
    s = s[pd.to_numeric(s["market_cap_cr"], errors="coerce") >= 1000].reset_index(drop=True)
    universe_syms = s["symbol"].tolist()
    t0 = time.time()
    cache = out_dir / "reference_last_rows.pkl"
    if cache.exists():  # reference values are deterministic for a given DB; reuse between runs
        last = pd.read_pickle(cache)
    else:
        last = last_rows_reference(con, universe_syms)
        last.to_pickle(cache)
    print(f"  reference last rows for {last.symbol.nunique()} symbols in {time.time() - t0:.0f}s", flush=True)
    today = last[last["trade_date"] == AUDIT_DATE].set_index("symbol")
    rs = ref.rs_percentile_for_dates(con, [AUDIT_DATE]).set_index("symbol")["rs_percentile_ref"]
    d = s.set_index("symbol")
    R = pd.DataFrame(index=d.index)
    # floors / non-indicator fields from the production snapshot (market cap, taxonomy, guard)
    for c in ("market_cap_cr", "volume", "delivery_pct"):
        R[c] = d[c]
    R["close"] = today["close"].reindex(R.index)
    for c in ("ema_10", "ema_20", "ema_50", "ema_100", "ema_200", "sma_50", "sma_150", "sma_200", "rsi_14", "rsi_14_w",
              "rvol", "avg_volume_20d", "adr_20_pct", "return_1m_pct", "return_3m_pct", "return_6m_pct",
              "away_10ema_pct", "nr7", "inside_bar", "delivery_spike", "price_up_delivery_up", "sma_200_rising"):
        R[c] = today[c].reindex(R.index)
    R["high"] = today["high"].reindex(R.index)
    R["rs_percentile"] = rs.reindex(R.index)
    # 52W uses the stored NSE-reference high/low (documented convention; audited in section 1)
    R["away_52w_high_pct"] = (R["close"] / d["high_52w"] - 1) * 100
    R["away_52w_low_pct"] = (R["close"] / d["low_52w"] - 1) * 100
    dist = ((d["high_52w"] - R["close"]) / d["high_52w"] * 100).clip(lower=0)
    n, allp = ref.trend_template(R["close"].to_numpy(), R["sma_50"].to_numpy(), R["sma_150"].to_numpy(),
                                 R["sma_200"].to_numpy(), R["sma_200_rising"].fillna(False).to_numpy(),
                                 R["away_52w_low_pct"].to_numpy(), dist.to_numpy(), R["rs_percentile"].to_numpy())
    R["trend_template_pass_n"] = n
    R["trend_template_pass"] = allp.astype(float)  # 1/0, NaN-able for the gap guard
    R["nr7_or_inside"] = R["nr7"].fillna(False).astype(bool) | R["inside_bar"].fillna(False).astype(bool)
    R["new_52w_high"] = R["high"] >= d["high_52w"]
    e = R[["ema_10", "ema_20", "ema_50"]]
    R["ema_spread_10_50_pct"] = (e.max(axis=1) - e.min(axis=1)) / R["close"] * 100
    # data-gap guard: same NULLs as the served snapshot
    for col, raw in (("away_52w_high_pct", "raw_away_h"), ("away_52w_low_pct", "raw_away_l"), ("rs_percentile", "raw_rs"),
                     ("trend_template_pass", "raw_tt"), ("trend_template_pass_n", "raw_tt")):
        guarded = d[col if col != "trend_template_pass_n" else "trend_template_pass"].isna() & d[raw].notna()
        R.loc[guarded, col] = np.nan
    for col in ("return_1m_pct", "return_3m_pct", "return_6m_pct"):
        R.loc[d[col].isna(), col] = np.nan
    floor = (R["market_cap_cr"] >= 1000) & (R["close"] >= 15)
    res: dict = {"universe": int(len(R)), "presets": {}}
    for pid, p in screener.PRESETS.items():
        if p.kind != "rules":
            continue
        mine = set(R.index[floor & preset_eval(R, p.rules)])
        api = screener.run(AUDIT_DATE.date(), pid, None, screener.Params())
        theirs = {r["symbol"] for r in api.rows}
        only_ref, only_api = sorted(mine - theirs), sorted(theirs - mine)
        detail = {}
        for sym in (only_ref + only_api)[:12]:
            dbg = screener.debug(AUDIT_DATE.date(), sym, pid, None, screener.Params())
            failing = [f"{x['label']} (api actual={x['actual']}, ref={x.get('ref_actual')})" for x in dbg.rows if not x["passed"]]
            detail[sym] = {"api_failing": failing,
                           "ref_values": {r_["field"]: _jsonable(R.at[sym, r_["field"]]) for r_ in p.rules}}
        res["presets"][pid] = {"api": len(theirs), "ref": len(mine), "both": len(mine & theirs),
                               "only_ref": only_ref, "only_api": only_api, "detail": detail}
    return res


def _jsonable(v):
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    try:
        f = float(v)
        return None if not np.isfinite(f) else round(f, 6)
    except (TypeError, ValueError):
        return str(v)


# ------------------------------------------------------------------------------------------
# Section 5: Desk queues on AUDIT_DATE
# ------------------------------------------------------------------------------------------
DARVAS_SPEC = dict(max_squeeze_pct=5.0, max_range_pct=4.0, max_rvol=1.0, ceiling_tol=1.002, close_floor_tol=0.998,
                   ema_trend_tol=0.995, persist_sessions=5, persist_max_rvol=1.5, persist_max_range_pct=6.0)


def squeeze_bar(c, top, e10, e10_prev, e20, h, l, rv, S=DARVAS_SPEC) -> bool:
    if not (np.isfinite(top) and top > 0 and np.isfinite(e10) and e10 > 0 and np.isfinite(c) and c > 0):
        return False
    sq = (top - e10) / top * 100
    dist = (top - c) / top * 100
    rng = (h - l) / c * 100
    ok = 0 <= sq <= S["max_squeeze_pct"] and -0.2 <= dist <= S["max_squeeze_pct"]
    if np.isfinite(e20) and e20 > 0:
        ok = ok and e10 >= e20 * S["ema_trend_tol"]
    ok = ok and c >= e10 * S["close_floor_tol"] and c <= top * S["ceiling_tol"]
    ok = ok and (not np.isfinite(rng) or rng <= S["max_range_pct"])
    if np.isfinite(e10_prev):
        ok = ok and e10 > e10_prev
    if np.isfinite(rv):  # unknown RVOL passes (desk passes rvol=None)
        ok = ok and rv <= S["max_rvol"]
    return bool(ok)


def section_queues(con, out_dir: Path) -> dict:
    from App.services import desk, universe

    last = pd.read_pickle(out_dir / "reference_last_rows.pkl")
    snap = universe.snapshot_sql(con, extra_cols=", i.band_remarks AS ind_band_remarks, m.band_remarks AS master_band_remarks, "
                                 "i.high_52w, i.avg_traded_value_cr_20d AS st_adv, i.turnover_cr AS st_to")
    s = con.execute(f"WITH s AS ({snap}) SELECT * FROM s", [AUDIT_DATE]).fetchdf().set_index("symbol")
    today = last[last["trade_date"] == AUDIT_DATE].set_index("symbol")
    sd = con.execute("SELECT * FROM setup_daily WHERE trade_date = ?", [AUDIT_DATE]).fetchdf()
    sdm = sd.set_index(["queue", "symbol"])
    # pool (independent): mcap >= 1000 (served point-in-time mcap), ADV >= 3 Cr (reference 20D mean of turnover),
    # band > 5 (unknown passes), no GSM / STAGE 2 remark, no -RE, close > 200 EMA (unknown passes)
    con.register("_q_syms", pd.DataFrame({"symbol": today.index.tolist()}))
    px = con.execute("""SELECT symbol, trade_date, COALESCE(adj_high_price, high_price) AS h,
                               COALESCE(adj_low_price, low_price) AS l, turnover_cr AS to_cr
                        FROM prices_daily WHERE symbol IN (SELECT symbol FROM _q_syms)
                          AND trade_date BETWEEN ? AND ? ORDER BY symbol, trade_date""",
                     [AUDIT_DATE - pd.Timedelta(days=330), AUDIT_DATE]).fetchdf()  # >= 200 sessions: VCP 150, ADV 20
    con.unregister("_q_syms")
    px["trade_date"] = pd.to_datetime(px["trade_date"])
    pxg = {k: g.reset_index(drop=True) for k, g in px.groupby("symbol", sort=False)}
    adv = px.groupby("symbol")["to_cr"].apply(lambda x: ref.sma(x.to_numpy(dtype=float), 20, 5)[-1])
    remarks = s["ind_band_remarks"].where(s["ind_band_remarks"].notna(), s["master_band_remarks"]).fillna("").str.upper()
    P = pd.DataFrame(index=today.index)
    P["mcap"] = s["market_cap_cr"].reindex(P.index)
    P["adv"] = adv.reindex(P.index)
    P["band"] = s["circuit_band"].reindex(P.index)
    P["remarks"] = remarks.reindex(P.index).fillna("")
    P["close"], P["ema_200"] = today["close"], today["ema_200"]
    pool = ((P["mcap"] >= 1000) & (P["adv"] >= 3) & (P["band"].isna() | (P["band"] > 5))
            & ~P["remarks"].str.contains("GSM") & ~P["remarks"].str.contains("STAGE 2")
            & ~P.index.str.endswith("-RE") & ~P.index.str.endswith("_RE")
            & ((P["close"] > P["ema_200"]) | P["ema_200"].isna()))
    pool_syms = set(P.index[pool])
    out: dict = {"pool": int(pool.sum())}
    # ---- Darvas squeeze -------------------------------------------------------------------
    by = {k: g.reset_index(drop=True) for k, g in last.groupby("symbol")}
    mine_sq, sq_detail = set(), {}
    for sym in pool_syms:
        g = by[sym]
        if len(g) < 5:
            continue
        e10p = np.r_[np.nan, g["ema_10"].to_numpy()[:-1]]
        bars = [squeeze_bar(g.close[i], g.darvas_top[i], g.ema_10[i], e10p[i], g.ema_20[i], g.high[i], g.low[i], g.rvol[i])
                for i in range(len(g))]
        i = len(g) - 1
        rng = (g.high[i] - g.low[i]) / g.close[i] * 100
        still = (np.isfinite(g.darvas_top[i]) and g.darvas_top[i] > 0 and g.close[i] >= g.ema_10[i] * 0.998
                 and g.close[i] <= g.darvas_top[i] * 1.002)
        persist = any(bars[-5:]) and still and (not np.isfinite(rng) or rng <= 6.0) and (not np.isfinite(g.rvol[i]) or g.rvol[i] <= 1.5)
        if bars[-1] or persist:
            mine_sq.add(sym)
            sq_detail[sym] = {"top": _jsonable(g.darvas_top[i]), "stop": _jsonable(g.ema_10[i] * 0.985)}
    sd_sq = set(sd.loc[sd.queue == "darvas_squeeze", "symbol"])
    api_sq = {r["symbol"] for r in desk.queue_rows(AUDIT_DATE.date(), "darvas_squeeze", "D").rows}
    geo_err = []
    for sym in mine_sq & sd_sq:
        row = sdm.loc[("darvas_squeeze", sym)]
        if abs(row.trigger_price - sq_detail[sym]["top"]) > 1e-4 * row.trigger_price or abs(row.stop_price - sq_detail[sym]["stop"]) > 0.011:
            geo_err.append({"symbol": sym, "stored": [row.trigger_price, row.stop_price], "ref": [sq_detail[sym]["top"], sq_detail[sym]["stop"]]})
    out["darvas_squeeze"] = {"ref": len(mine_sq), "setup_daily": len(sd_sq), "api": len(api_sq),
                             "only_ref": sorted(mine_sq - sd_sq), "only_setup_daily": sorted(sd_sq - mine_sq),
                             "api_vs_setup_daily_diff": sorted(api_sq ^ sd_sq), "geometry_mismatch": geo_err,
                             "why": {sym: _why_squeeze(by.get(sym), P, sym, pool_syms) for sym in sorted(mine_sq ^ sd_sq)}}
    # ---- Darvas 10 EMA: geometry + necessary conditions -----------------------------------
    e10 = sd[sd.queue == "darvas_10ema"]
    api_e10 = {r["symbol"] for r in desk.queue_rows(AUDIT_DATE.date(), "darvas_10ema", "D").rows}
    geo, nec = [], []
    for _, r in e10.iterrows():
        g = pxg[r.symbol]
        t = g[g.trade_date == AUDIT_DATE]
        since = g[(g.trade_date >= pd.Timestamp(r.signal_date)) & (g.trade_date <= AUDIT_DATE)]
        feats = json.loads(r.features)
        want_trig = float(t.h.iloc[0])
        want_stop = None if feats.get("flavor") == "Catch-up" else float(since.l.min())
        ok_t = abs(r.trigger_price - want_trig) <= 1e-6 * want_trig
        ok_s = (want_stop is None and pd.isna(r.stop_price)) or (want_stop is not None and abs(r.stop_price - want_stop) <= 1e-6 * want_stop)
        if not (ok_t and ok_s):
            geo.append({"symbol": r.symbol, "stored": [r.trigger_price, r.stop_price], "ref": [want_trig, want_stop]})
        gg = by[r.symbol]
        i = len(gg) - 1
        cond = gg.ema_10[i] > gg.ema_10[i - 1] and gg.close[i] > gg.ema_10[i] and gg.high[i] >= gg.ema_10[i]
        if not cond or r.symbol not in pool_syms or r.symbol in sd_sq:
            nec.append({"symbol": r.symbol, "rising_close_above": bool(cond), "in_ref_pool": r.symbol in pool_syms,
                        "also_in_squeeze": r.symbol in sd_sq})
    out["darvas_10ema"] = {"setup_daily": int(len(e10)), "api": len(api_e10),
                           "api_vs_setup_daily_diff": sorted(api_e10 ^ set(e10.symbol)),
                           "geometry_checked": int(len(e10)), "geometry_mismatch": geo, "necessary_condition_violations": nec,
                           "flavors": e10["features"].map(lambda x: json.loads(x).get("flavor")).value_counts().to_dict()}
    # ---- VCP --------------------------------------------------------------------------------
    mine_vcp, vcp_geo = {}, []
    for sym in pool_syms:
        c = P.at[sym, "close"]
        away = s.at[sym, "away_52w_high_pct"] if sym in s.index else np.nan
        raw_away = (c / s.at[sym, "high_52w"] - 1) * 100 if sym in s.index else np.nan
        av = today.at[sym, "avg_volume_20d"]
        if not (c >= 30 and (np.isnan(raw_away) or raw_away >= -25) and (np.isnan(av) or av >= 100_000)):
            continue
        g = pxg[sym].tail(150)
        if len(g) < 30:
            continue
        depths, pivot, stop = ref.detect_contractions_ref(g.h.to_numpy(), g.l.to_numpy())
        if len(depths) >= 2 and pivot is not None and stop < c <= pivot:
            mine_vcp[sym] = (pivot, stop, depths)
    sd_v = sd[sd.queue == "vcp"].set_index("symbol")
    api_v = {r["symbol"] for r in desk.queue_rows(AUDIT_DATE.date(), "vcp", "D").rows}
    for sym in set(mine_vcp) & set(sd_v.index):
        p, st_, dep = mine_vcp[sym]
        f = json.loads(sd_v.at[sym, "features"])
        if abs(sd_v.at[sym, "trigger_price"] - p) > 1e-6 * p or abs(sd_v.at[sym, "stop_price"] - st_) > 1e-6 * st_ \
                or len(f["depths_pct"]) != len(dep) or max(abs(a - b) for a, b in zip(f["depths_pct"], dep)) > 0.006:
            vcp_geo.append({"symbol": sym, "stored": [sd_v.at[sym, "trigger_price"], sd_v.at[sym, "stop_price"], f["depths_pct"]],
                            "ref": [p, st_, [round(x, 2) for x in dep]]})
    sanity = []
    for sym, r in sd_v.iterrows():
        f = json.loads(r.features)
        dp = f["depths_pct"]
        ok = len(dp) >= 2 and all(a > b for a, b in zip(dp, dp[1:])) and min(dp) >= 3 and min(f["bars"]) >= 8 \
            and r.stop_price < r.close_price <= r.trigger_price
        if not ok:
            sanity.append({"symbol": sym, "depths": dp, "bars": f["bars"], "close": r.close_price, "pivot": r.trigger_price, "stop": r.stop_price})
    out["vcp"] = {"ref": len(mine_vcp), "setup_daily": int(len(sd_v)), "api": len(api_v),
                  "only_ref": sorted(set(mine_vcp) - set(sd_v.index)), "only_setup_daily": sorted(set(sd_v.index) - set(mine_vcp)),
                  "api_vs_setup_daily_diff": sorted(api_v ^ set(sd_v.index)), "geometry_mismatch": vcp_geo,
                  "sanity_violations": sanity}
    # desk live path (used by screener debug for VCP) vs setup_daily
    live = desk._compute_group(con, AUDIT_DATE.date(), "D")
    out["live_vs_setup_daily"] = {q: {"live": int(len(live.get(q, []))),
                                      "only_live": sorted(set(live[q]["symbol"]) - set(sd.loc[sd.queue == q, "symbol"])) if q in live and len(live[q]) else [],
                                      "only_setup_daily": sorted(set(sd.loc[sd.queue == q, "symbol"]) - (set(live[q]["symbol"]) if q in live and len(live[q]) else set()))}
                                  for q in ("darvas_squeeze", "darvas_10ema", "vcp")}
    return out


def _why_squeeze(g, P, sym, pool_syms) -> dict:
    if g is None:
        return {"note": "no reference rows"}
    i = len(g) - 1
    return {"in_ref_pool": sym in pool_syms, "mcap": _jsonable(P.at[sym, "mcap"]) if sym in P.index else None,
            "adv": _jsonable(P.at[sym, "adv"]) if sym in P.index else None,
            "top": _jsonable(g.darvas_top[i]), "ema10": _jsonable(g.ema_10[i]), "close": _jsonable(g.close[i]),
            "rvol": _jsonable(g.rvol[i]), "range_pct": _jsonable((g.high[i] - g.low[i]) / g.close[i] * 100)}


# ------------------------------------------------------------------------------------------
# Section 6: Darvas box — reference Pine transcription vs the production box (full history),
# and the production box's dependence on the window start (desk live uses the last 252 bars)
# ------------------------------------------------------------------------------------------
def section_darvas(con, symbols) -> dict:
    from Scripts.darvas_squeeze import calculate_darvas_box  # production, compared only

    px = ref.load_adjusted(con, symbols)
    n = mis = nwin = miswin = 0
    for _, g in px.groupby("symbol", sort=False):
        h, l = g["h"].to_numpy(), g["l"].to_numpy()
        t1, b1 = ref.darvas_box_pine(h, l)
        t2, b2 = calculate_darvas_box(h, l, 5)
        same = lambda a, b: np.isclose(a, b) | (np.isnan(a) & np.isnan(b))  # noqa: E731
        ok = same(t1, t2) & same(b1, b2)
        n += len(ok)
        mis += int((~ok).sum())
        for e in range(max(260, len(h) - 300), len(h)):
            tw, _ = calculate_darvas_box(h[e - 251:e + 1], l[e - 251:e + 1], 5)
            nwin += 1
            miswin += int(not same(np.array([tw[-1]]), np.array([t2[e]]))[0])
    return {"bars": n, "box_mismatch": mis, "window252_end_bars": nwin, "window252_top_differs": miswin}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--sections", default="stored,rs,pit,darvas,screens,queues")
    a = ap.parse_args()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MP_DB_PATH", str(LIVE_DB))
    con = connect()
    dates = sample_dates(con)
    symbols = sample_symbols(con)
    print(f"sample: {len(symbols)} symbols, dates {[str(d.date()) for d in dates]}", flush=True)
    for sec in a.sections.split(","):
        t0 = time.time()
        if sec == "stored":
            res = section_stored(con, symbols, dates)
        elif sec == "rs":
            res = section_rs(con, dates)
        elif sec == "pit":
            res = section_pit(con, symbols[::4] + ["GOODLUCK", "HEGAM"], [dates[2], dates[4], dates[6]])
        elif sec == "screens":
            res = section_screens(con, out_dir)
        elif sec == "queues":
            res = section_queues(con, out_dir)
        elif sec == "darvas":
            res = section_darvas(con, symbols)
        else:
            raise SystemExit(f"unknown section {sec}")
        (out_dir / f"{sec}.json").write_text(json.dumps(res, indent=1, default=str))
        print(f"[{sec}] done in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
