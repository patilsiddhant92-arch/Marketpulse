"""Research: the live signal log + setup scorecard ("log and grade", 10-tab-research.md §7).

Write side (Scripts/research_lab.py, i.e. the pipeline; never the API):
- ``research_signal_log`` lives in the research sidecar DB (research_lab.duckdb), NOT in the shared market DB.
  Unlike the other research_* tables it is never rebuilt whole: a signal is inserted once and its signal
  fields are never rewritten, so the log keeps what the Desk showed that day even if setup_daily is rebuilt
  later. Only the grade columns are refreshed on each run.
- A signal = a setup's first day in a Desk queue (setup_daily rows with trade_date = first_seen, i.e.
  status "new"): Darvas squeeze, 10 EMA (Pullback / Trace-back / Catch-up) and VCP. Identity = setup_id.
- ``logged`` = "live" when the run that inserted it saw it on the latest session, else "backfill" (rows
  added from setup_daily history on the first run, or after missed runs).

Grading (5 / 10 / 20 sessions of the stock's own bars after the signal day; no look-ahead):
- entry = the signal-day close (the price the Desk showed that evening).
- ret_h = close_h / entry - 1; excess_h = ret_h minus the equal-weight >= Rs 1,000 Cr market over the same
  sessions (research_regime_daily.ew_index); NULL where the EW market is not known (gap tail).
- R multiple vs the setup stop: risk = entry - stop (needs stop < entry). Walking sessions 1..h, a low <= stop
  exits at min(open, stop) (gap-downs fill at the open) -> stopped; else R_h = (close_h - entry) / risk.
- triggered_h = a high >= the trigger price within the h sessions.
- A window that spans a calendar gap of > 20 days (the local Aug-Oct hole) is not graded (grade_note "gap").

Read side (the API): rows with trade_date <= as_of; a horizon's grade is shown only when its date <= as_of.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from App.services import db
from App.services import research_lab as lab
from App.services.common import Result, no_session, unavailable

TABLE = "research_signal_log"
HORIZONS = (5, 10, 20)
QUEUE_LABEL = {"darvas_squeeze": "Darvas squeeze", "darvas_10ema": "10 EMA", "vcp": "VCP"}
NOT_WORKING_MONTHS = 3
MIN_MONTH_GRADED = 5

SIGNAL_COLS = ["setup_id", "trade_date", "queue", "flavor", "symbol", "signal_close", "trigger_price", "stop_price", "risk_pct",
               "rs_percentile", "adv_cr", "mcap_cr", "logged", "logged_at"]
GRADE_COLS = [f"{k}_{h}" for h in HORIZONS for k in ("date", "ret", "excess", "r", "stopped", "triggered")] + \
    ["grade_note", "graded_at"]


def setup_key(queue: str, flavor: str | None) -> str:
    return f"{queue}:{flavor}" if queue == "darvas_10ema" and flavor else queue


def setup_label(queue: str, flavor: str | None) -> str:
    base = QUEUE_LABEL.get(queue, queue)
    return f"{base} · {flavor}" if queue == "darvas_10ema" and flavor else base


# --------------------------------------------------------------------------
# Write side (pipeline)
# --------------------------------------------------------------------------
def ensure(con: Any) -> None:
    hz = ",\n".join(f"date_{h} DATE, ret_{h} DOUBLE, excess_{h} DOUBLE, r_{h} DOUBLE, stopped_{h} BOOLEAN, "
                    f"triggered_{h} BOOLEAN" for h in HORIZONS)
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            setup_id VARCHAR PRIMARY KEY, trade_date DATE, queue VARCHAR, flavor VARCHAR, symbol VARCHAR,
            signal_close DOUBLE, trigger_price DOUBLE, stop_price DOUBLE, risk_pct DOUBLE, rs_percentile DOUBLE,
            adv_cr DOUBLE, mcap_cr DOUBLE, logged VARCHAR, logged_at TIMESTAMP,
            {hz},
            grade_note VARCHAR, graded_at TIMESTAMP
        )""")


def _flavor(features: Any) -> str | None:
    if not isinstance(features, str) or not features:
        return None
    try:
        v = json.loads(features).get("flavor")
    except (ValueError, AttributeError):
        return None
    return str(v) if v else None


def log_signals(market_con: Any, out_con: Any, end: date | None = None) -> int:
    """Insert the setup_daily signals not yet logged (signal fields are written once). Returns rows added."""
    ensure(out_con)
    if not db.table_exists(market_con, "setup_daily"):
        return 0
    latest = db.latest_session(market_con)
    where, params = ["CAST(trade_date AS DATE) = CAST(first_seen AS DATE)"], []
    if end is not None:
        where.append("CAST(trade_date AS DATE) <= ?")
        params.append(end)
    s = market_con.execute(f"""
        SELECT setup_id, CAST(trade_date AS DATE) trade_date, queue, symbol, close_price signal_close, trigger_price,
               stop_price, risk_pct, rs_percentile, adv_cr, mcap_cr, features
        FROM setup_daily WHERE {' AND '.join(where)}""", params).df()
    if s.empty:
        return 0
    have = {r[0] for r in out_con.execute(f"SELECT setup_id FROM {TABLE}").fetchall()}
    s = s[~s.setup_id.isin(have)].drop_duplicates("setup_id").copy()
    if s.empty:
        return 0
    s["flavor"] = [_flavor(f) for f in s.features]
    s["trade_date"] = pd.to_datetime(s.trade_date).dt.date
    s["logged"] = np.where(s.trade_date == latest, "live", "backfill")
    s["logged_at"] = datetime.now().replace(microsecond=0)
    s = s[SIGNAL_COLS]
    out_con.register("_sig", s)
    try:
        out_con.execute(f"INSERT INTO {TABLE} ({', '.join(SIGNAL_COLS)}) SELECT {', '.join(SIGNAL_COLS)} FROM _sig "
                        "ON CONFLICT (setup_id) DO NOTHING")
    finally:
        out_con.unregister("_sig")
    return int(len(s))


def grade_frame(sig: pd.DataFrame, bars: pd.DataFrame, ew: pd.Series | None) -> pd.DataFrame:
    """Grades for `sig` (setup_id, symbol, trade_date, signal_close, trigger_price, stop_price) from `bars`
    (symbol, trade_date, open/high/low/close_price) and the EW index (date -> level). Pure."""
    ew_map = {pd.Timestamp(k): float(v) for k, v in (ew.dropna().items() if ew is not None else [])}
    by_sym = {k: g.sort_values("trade_date").reset_index(drop=True) for k, g in bars.groupby("symbol", sort=False)}
    arrays: dict[str, tuple[np.ndarray, ...]] = {}
    out = []
    for r in sig.itertuples(index=False):
        row: dict[str, Any] = {"setup_id": r.setup_id, "grade_note": None}
        g = by_sym.get(r.symbol)
        t0 = pd.Timestamp(r.trade_date)
        if g is None:
            row["grade_note"] = "no bars"
            out.append(row)
            continue
        if r.symbol not in arrays:
            dts = g.trade_date.to_numpy(dtype="datetime64[ns]")
            arrays[r.symbol] = (dts, *(g[c].to_numpy(dtype=float) for c in ("open_price", "high_price", "low_price", "close_price")),
                                np.r_[0, np.diff(dts).astype("timedelta64[D]").astype(int)])
        dates, op, hi, lo, cl, gap_days = arrays[r.symbol]
        i0 = int(np.searchsorted(dates, np.datetime64(t0), side="right")) - 1
        if i0 < 0 or pd.Timestamp(dates[i0]) != t0:
            row["grade_note"] = "no bar on the signal day"
            out.append(row)
            continue
        entry = float(r.signal_close) if r.signal_close is not None and not pd.isna(r.signal_close) else float(cl[i0])
        stop = None if r.stop_price is None or pd.isna(r.stop_price) else float(r.stop_price)
        trig = None if r.trigger_price is None or pd.isna(r.trigger_price) else float(r.trigger_price)
        risk = entry - stop if stop is not None and stop < entry else None
        ew0 = ew_map.get(t0)
        for h in HORIZONS:
            j = i0 + h
            if j >= len(dates):
                continue
            if (gap_days[i0 + 1:j + 1] > lab.GAP_DAYS).any():
                row["grade_note"] = "gap"
                continue
            dh = pd.Timestamp(dates[j])
            ret = cl[j] / entry - 1 if entry > 0 else np.nan
            ewh = ew_map.get(dh)
            row[f"date_{h}"] = dh.date()
            row[f"ret_{h}"] = ret * 100
            row[f"excess_{h}"] = (ret - (ewh / ew0 - 1)) * 100 if ew0 and ewh else None
            row[f"triggered_{h}"] = bool(trig is not None and np.nanmax(hi[i0 + 1:j + 1]) >= trig) if trig is not None else None
            if risk:
                rr, stopped = None, False
                for k in range(i0 + 1, j + 1):
                    if lo[k] <= stop:
                        rr, stopped = (min(op[k], stop) - entry) / risk, True
                        break
                row[f"r_{h}"] = rr if stopped else (cl[j] - entry) / risk
                row[f"stopped_{h}"] = stopped
        out.append(row)
    df = pd.DataFrame(out)
    for c in GRADE_COLS:
        if c not in df.columns:
            df[c] = None
    return df


def grade(market_con: Any, out_con: Any, ew: pd.Series | None) -> int:
    """Refresh the grade columns of every logged signal whose 20-session grade is not final. Returns rows graded."""
    ensure(out_con)
    sig = out_con.execute(f"""SELECT setup_id, symbol, trade_date, signal_close, trigger_price, stop_price FROM {TABLE}
                              WHERE date_20 IS NULL AND coalesce(grade_note, '') NOT IN ('gap', 'no bars')""").df()
    if sig.empty:
        return 0
    lo = pd.Timestamp(sig.trade_date.min()).date()
    bars = market_con.execute("""SELECT symbol, CAST(trade_date AS DATE) trade_date, open_price, high_price, low_price, close_price
                                 FROM indicators_daily WHERE trade_date >= ? AND symbol IN (SELECT unnest(?))""",
                              [lo, sorted(set(sig.symbol))]).df()
    bars["trade_date"] = pd.to_datetime(bars.trade_date)
    g = grade_frame(sig, bars, ew)
    g["graded_at"] = datetime.now().replace(microsecond=0)
    for h in HORIZONS:
        for c in (f"ret_{h}", f"excess_{h}", f"r_{h}"):
            g[c] = pd.to_numeric(g[c], errors="coerce")
        for c in (f"stopped_{h}", f"triggered_{h}"):
            g[c] = g[c].astype("boolean")
        g[f"date_{h}"] = pd.to_datetime(g[f"date_{h}"])
    out_con.register("_g", g[["setup_id", *GRADE_COLS]])
    try:
        sets = ", ".join(f"{c} = _g.{c}" for c in GRADE_COLS)
        out_con.execute(f"UPDATE {TABLE} SET {sets} FROM _g WHERE {TABLE}.setup_id = _g.setup_id")
    finally:
        out_con.unregister("_g")
    return int(len(g))


def update(market_con: Any, out_con: Any, ew: pd.Series | None, end: date | None = None) -> dict[str, int]:
    """Pipeline step: log today's (and any missed) signals, then grade what can be graded."""
    added = log_signals(market_con, out_con, end)
    graded = grade(market_con, out_con, ew)
    total = int(out_con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0])
    return {"added": added, "graded": graded, "total": total}


# --------------------------------------------------------------------------
# Read side (API)
# --------------------------------------------------------------------------
def _load(as_of: date) -> pd.DataFrame | None:
    with lab._sidecar() as side:
        if side is None or not db.table_exists(side, TABLE):
            return None
        df = side.execute(f"SELECT * FROM {TABLE} WHERE trade_date <= ? ORDER BY trade_date DESC, symbol", [as_of]).df()
    ts = pd.Timestamp(as_of)
    for h in HORIZONS:
        dh = pd.to_datetime(df[f"date_{h}"])
        hide = dh.isna() | (dh > ts)
        for c in (f"ret_{h}", f"excess_{h}", f"r_{h}", f"stopped_{h}", f"triggered_{h}"):
            df[c] = df[c].astype(object).where(~hide, None)
        df[f"date_{h}"] = dh.where(~hide)
    df["setup"] = [setup_key(q, f) for q, f in zip(df.queue, df.flavor)]
    df["setup_label"] = [setup_label(q, f) for q, f in zip(df.queue, df.flavor)]
    return df


def _cached_load(as_of: date) -> pd.DataFrame | None:
    side = lab.sidecar_path()
    try:
        st = side.stat()
        skey = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        skey = "none"
    return db.cached("research_signal_log", (as_of, skey), lambda: _load(as_of))


def _resolve(as_of: date | None) -> date | None:
    with db.market_conn() as con:
        return db.resolve_as_of(con, as_of)


MISSING = ("The signal log is empty. It is written by the daily pipeline (Scripts/research_lab.py). "
           "Run it once to backfill it from setup_daily history.")


def signal_log(as_of: date | None, setup: str | None = None, days: int = 30) -> Result:
    resolved = _resolve(as_of)
    if resolved is None:
        return no_session(as_of)
    df = _cached_load(resolved)
    if df is None or df.empty:
        return unavailable(resolved, MISSING, [TABLE], caveat=lab.CAVEAT)
    if setup:
        df = df[(df.setup == setup) | (df.queue == setup)]
    since = pd.Timestamp(resolved) - pd.Timedelta(days=int(days))
    df = df[pd.to_datetime(df.trade_date) > since]
    cols = ["setup_id", "trade_date", "setup", "setup_label", "queue", "flavor", "symbol", "signal_close", "trigger_price",
            "stop_price", "risk_pct", "rs_percentile", "logged",
            *[f"{k}_{h}" for h in HORIZONS for k in ("ret", "excess", "r", "stopped", "triggered")], "grade_note"]
    rows = lab.records(df[cols], 2)
    live = int((df.logged == "live").sum())
    ctx = {"caveat": lab.CAVEAT, "days": days, "setup": setup, "live": live, "backfill": int(len(df) - live),
           "definition": DEFINITION}
    return Result(as_of=resolved, rows=rows, sources=[TABLE, "setup_daily", "indicators_daily"], extra=ctx)


DEFINITION = ("A signal is a setup's first day in a Desk queue. It is graded 5, 10 and 20 sessions later from that "
              "day's close: return, return vs the equal-weight market (>= Rs 1,000 Cr), and R = gain / (entry - stop), "
              "with the stop hit at min(open, stop). Triggered = the high reached the trigger.")


def _agg(x: pd.DataFrame) -> dict[str, Any]:
    def mean(c: str) -> float | None:
        v = pd.to_numeric(x[c], errors="coerce").dropna()
        return lab.rnd(v.mean(), 2) if len(v) else None

    def share(c: str) -> float | None:
        v = x[c].dropna()
        return lab.rnd(v.astype(bool).mean() * 100, 1) if len(v) else None
    ex20 = pd.to_numeric(x.excess_20, errors="coerce").dropna()
    return {"signals": int(len(x)), "graded_20": int(len(ex20)),
            "hit_20_pct": lab.rnd((ex20 > 0).mean() * 100, 1) if len(ex20) else None,
            "avg_excess_5": mean("excess_5"), "avg_excess_10": mean("excess_10"), "avg_excess_20": mean("excess_20"),
            "avg_ret_20": mean("ret_20"), "avg_r_20": mean("r_20"), "stopped_20_pct": share("stopped_20"),
            "triggered_20_pct": share("triggered_20")}


def signal_scorecard(as_of: date | None) -> Result:
    resolved = _resolve(as_of)
    if resolved is None:
        return no_session(as_of)
    df = _cached_load(resolved)
    if df is None or df.empty:
        return unavailable(resolved, MISSING, [TABLE], caveat=lab.CAVEAT)
    df = df.copy()
    df["month"] = pd.to_datetime(df.trade_date).dt.strftime("%Y-%m")
    rows, monthly = [], []
    order = {"darvas_squeeze": 0, "darvas_10ema": 1, "vcp": 2}
    for key, x in sorted(df.groupby("setup"), key=lambda kv: (order.get(kv[1].queue.iat[0], 9), kv[0])):
        a = _agg(x)
        months = []
        for m, y in sorted(x.groupby("month")):
            b = _agg(y)
            months.append({"setup": key, "setup_label": x.setup_label.iat[0], "month": m, **b})
        graded = [mm for mm in months if mm["graded_20"] >= MIN_MONTH_GRADED]
        last = graded[-NOT_WORKING_MONTHS:]
        not_working = len(last) == NOT_WORKING_MONTHS and all((mm["avg_excess_20"] or 0) < 0 for mm in last)
        recent = x[x.month.isin([mm["month"] for mm in last])]
        ra = _agg(recent) if len(recent) else {}
        rows.append({"setup": key, "setup_label": x.setup_label.iat[0], "queue": x.queue.iat[0], **a,
                     "live": int((x.logged == "live").sum()),
                     "first_signal": lab.clean(pd.Timestamp(x.trade_date.min())),
                     "last_signal": lab.clean(pd.Timestamp(x.trade_date.max())),
                     "recent_months": [mm["month"] for mm in last],
                     "recent_hit_20_pct": ra.get("hit_20_pct"), "recent_avg_excess_20": ra.get("avg_excess_20"),
                     "not_working": bool(not_working)})
        monthly += months
    allx = _agg(df)
    summary = [f"{allx['signals']:,} Desk signals logged to {resolved:%d %b %Y}; {allx['graded_20']:,} have a 20-session grade."]
    graded_rows = [r for r in rows if r["graded_20"] >= 20 and r["avg_excess_20"] is not None]
    if graded_rows:
        best = max(graded_rows, key=lambda r: r["avg_excess_20"])
        worst = min(graded_rows, key=lambda r: r["avg_excess_20"])
        summary.append(f"Best so far: {best['setup_label']}, {best['avg_excess_20']:+.1f}% vs the market over 20 sessions "
                       f"({best['hit_20_pct']:.0f}% beat it, n = {best['graded_20']}).")
        if worst["setup"] != best["setup"]:
            summary.append(f"Weakest: {worst['setup_label']}, {worst['avg_excess_20']:+.1f}% (n = {worst['graded_20']}).")
    nw = [r["setup_label"] for r in rows if r["not_working"]]
    if nw:
        summary.append(f"Not working now (lagged the market {NOT_WORKING_MONTHS} graded months in a row): {', '.join(nw)}.")
    live = int((df.logged == "live").sum())
    summary.append(f"{live:,} signals were logged live by the pipeline; the rest were backfilled from setup_daily, which "
                   "can be rebuilt later. Live rows are the honest record.")
    ctx = {"caveat": lab.CAVEAT, "monthly": monthly, "overall": allx, "summary": summary, "definition": DEFINITION,
           "not_working_rule": (f"A setup that lagged the equal-weight market (average 20-session excess < 0) in each of "
                                f"its last {NOT_WORKING_MONTHS} graded months (>= {MIN_MONTH_GRADED} graded signals each) "
                                "is flagged 'not working now'."),
           "horizons": list(HORIZONS)}
    return Result(as_of=resolved, rows=lab.deep_clean(rows), sources=[TABLE, "setup_daily", "indicators_daily"], extra=ctx)
