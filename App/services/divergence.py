"""RSI divergence services (HarkPro/12-sprint2-plan.md "Divergence API contract").

* chart_divergences: every divergence of one stock on D / W / M bars up to as_of, with its
  status as of that date - what the chart draws.
* scan: the divergences confirmed in the last `window` bars across the >= Rs 1,000 Cr universe
  - the Setups "Divergences" view.

The rules live in the shared engine (Scripts/rsi_divergence.py, re-exported by
App/indicators/rsi_divergence.py); the EOD pipeline flags indicators_daily with the same code.
Bars are the adjusted daily prices (adj_* when present) resampled to W-FRI / calendar month;
a W/M bar that is still forming on as_of is left out, so a W/M divergence is only confirmed
by completed bars. Status walks the DAILY closes after the 2nd pivot's bar up to as_of.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

import numpy as np
import pandas as pd

from App.indicators import rsi_divergence as rd
from App.services import db
from App.services.common import Result, is_trading_day, load_holidays, no_session, unavailable

SOURCES = ["prices_daily", "stocks_master", "group_daily"]
MIN_MCAP_CR = 1000.0
TFS = ("D", "W", "M")
WINDOW_DEFAULT = 5
RULES = {
    "pivot": f"{rd.PIVOT_K}-bar pivot on low (bull) / high (bear), confirmed {rd.PIVOT_K} bars later",
    "gap_bars": [rd.MIN_GAP, rd.MAX_GAP],
    "equal_price_atr": rd.PRICE_TOL_ATR,
    "equal_rsi_points": rd.RSI_TOL,
    "regular_zone": "bull: an RSI pivot < 40 and RSI never > 60 between; bear: an RSI pivot > 60 and RSI never < 40 between",
    "hidden_trend": "bull: close > EMA50 and RSI < 50 at the 2nd low; bear: close < EMA50 and RSI > 50 at the 2nd high",
    "trigger": "bull: highest high between the lows; bear: lowest low between the highs",
    "stop": "bull: the 2nd low; bear: the 2nd high",
    "status": "first daily close beyond the trigger = triggered, beyond the stop = failed (terminal); else watching",
}


def _check_tf(tf: str) -> str:
    tf = str(tf or "D").upper()
    if tf not in TFS:
        raise ValueError("tf must be D, W or M")
    return tf


def _price_exprs(con: Any) -> dict[str, str]:
    cols = set(db.table_columns(con, "prices_daily"))
    return {c: (f"COALESCE(adj_{c}, {c})" if f"adj_{c}" in cols else c) for c in ("high_price", "low_price", "close_price")}


def _load_daily(con: Any, as_of: date, symbols: list[str] | None) -> pd.DataFrame:
    ex = _price_exprs(con)
    where = "trade_date <= ?"
    params: list[Any] = [as_of]
    if symbols is not None:
        con.register("_div_syms", pd.DataFrame({"symbol": symbols}))
        where += " AND symbol IN (SELECT symbol FROM _div_syms)"
    try:
        frame = con.execute(
            f"""SELECT symbol, CAST(trade_date AS DATE) AS d, {ex['high_price']} AS h, {ex['low_price']} AS l,
                       {ex['close_price']} AS c
                FROM prices_daily WHERE {where} ORDER BY symbol, d""", params).df()
    finally:
        if symbols is not None:
            con.unregister("_div_syms")
    frame["d"] = pd.to_datetime(frame["d"])
    return frame.dropna(subset=["h", "l", "c"])


def _period_complete(label: pd.Timestamp, as_of: date, holidays: set[date]) -> bool:
    """A W/M bar labelled `label` (its Friday / month-end) is complete on as_of when no NSE session
    lies in (as_of, label]."""
    end = label.date()
    d = as_of + timedelta(days=1)
    while d <= end:
        if is_trading_day(d, holidays):
            return False
        d += timedelta(days=1)
    return True


def bars_for(daily: pd.DataFrame, tf: str, as_of: date, holidays: set[date] | None = None) -> pd.DataFrame:
    """D: the daily rows. W/M: W-FRI / month-end bars dated by their last session, completed only."""
    if tf == "D" or daily.empty:
        return daily[["d", "h", "l", "c"]].reset_index(drop=True)
    rule = "W-FRI" if tf == "W" else "ME"
    g = daily.assign(last=daily["d"]).set_index("d").resample(rule)
    out = pd.DataFrame({"h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(), "d": g["last"].max()}).dropna(subset=["c"])
    if not out.empty:
        hol = holidays if holidays is not None else load_holidays()
        if not _period_complete(out.index[-1], as_of, hol):
            out = out.iloc[:-1]
    return out.reset_index(drop=True)[["d", "h", "l", "c"]]


def _detect_rows(daily: pd.DataFrame, tf: str, as_of: date, holidays: set[date] | None = None) -> tuple[list[dict[str, Any]], pd.DataFrame, np.ndarray]:
    bars = bars_for(daily, tf, as_of, holidays)
    if bars.empty:
        return [], bars, np.array([])
    rsi, atr, trend = rd.indicator_inputs(bars.h, bars.l, bars.c)
    divs = rd.detect(bars.h.to_numpy(), bars.l.to_numpy(), bars.c.to_numpy(), rsi=rsi, atr=atr, trend=trend)
    if not divs:
        return [], bars, rsi
    rows = rd.to_rows(divs, list(bars.d.dt.date), status_closes=daily.c.to_numpy(), status_dates=list(daily.d.dt.date))
    for r, d in zip(rows, divs):
        r["confirm_index"] = d.confirm
    return rows, bars, rsi


def chart_divergences(as_of: date | None, symbol: str, tf: str = "D") -> Result:
    tf = _check_tf(tf)
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        daily = _load_daily(con, resolved, [symbol])
    if daily.empty:
        return unavailable(resolved, f"no bars for {symbol} on or before {resolved.isoformat()}", ["prices_daily"])
    rows, bars, _ = _detect_rows(daily, tf, resolved)
    for r in rows:
        r.pop("confirm_index", None)
        r["tf"] = tf
    notes = ["A divergence exists from its confirm_date (2nd pivot + 3 bars); nothing is drawn before it is known."]
    if tf != "D":
        notes.append("W/M bars are resampled from adjusted daily prices; a bar still forming on as_of is not used.")
    return Result(as_of=resolved, rows=rows, sources=["prices_daily"],
                  extra={"symbol": symbol, "timeframe": tf, "bars": int(len(bars)), "rules": RULES}, notes=notes)


# ------------------------------------------------------------------------------------- universe scan
def _universe(con: Any) -> pd.DataFrame:
    if not db.table_exists(con, "stocks_master"):
        return pd.DataFrame(columns=["symbol", "security_name", "sector", "industry", "market_cap_cr"])
    m = con.execute("SELECT symbol, security_name, sector, industry, market_cap_cr FROM stocks_master "
                    "WHERE market_cap_cr >= ?", [MIN_MCAP_CR]).df()
    return m.drop_duplicates("symbol").set_index("symbol")


def _group_states(con: Any, as_of: date) -> dict[str, tuple[str, str]]:
    """Industry -> (state, why) on as_of from the Setups group-state model (Pulse group state)."""
    try:
        from App.services import setups
        if not db.table_exists(con, "group_daily"):
            return {}
        gd = setups._groups(con, as_of)
    except Exception:  # noqa: BLE001 - group state is optional context, never fatal
        return {}
    if gd is None or gd.empty:
        return {}
    last = gd[gd.d == gd.d.max()]
    return {str(n): (str(s), str(w)) for n, s, w in zip(last.n, last.state, last.why)}


def _scan_all(as_of: date, tf: str, window: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with db.market_conn() as con:
        uni = _universe(con)
        syms = sorted(uni.index)
        daily = _load_daily(con, as_of, syms) if syms else pd.DataFrame(columns=["symbol", "d", "h", "l", "c"])
        groups = _group_states(con, as_of)
    holidays = load_holidays()
    out: list[dict[str, Any]] = []
    for sym, g in daily.groupby("symbol", sort=True):
        g = g.reset_index(drop=True)
        if g.d.iloc[-1].date() != as_of:  # not trading on as_of (suspended / delisted)
            continue
        rows, bars, rsi = _detect_rows(g, tf, as_of, holidays)
        n = len(bars)
        if not rows or n == 0:
            continue
        close = float(g.c.iloc[-1])
        m = uni.loc[sym]
        ind = db.text(m.industry)
        gs = groups.get(ind or "")
        for r in rows:
            since = n - 1 - r.pop("confirm_index")
            if since >= window:
                continue
            trig = r["trigger_price"]
            out.append({
                "symbol": sym, "name": db.text(m.security_name), "sector": db.text(m.sector), "industry": ind,
                "group": ind, "market_cap_cr": db.num(m.market_cap_cr, 0),
                "tf": tf, **r, "bars_since_confirm": int(since),
                "close": round(close, 2),
                "distance_to_trigger_pct": db.num((trig / close - 1) * 100, 2) if close else None,
                "risk_pct": db.num(abs(close / r["stop_price"] - 1) * 100, 2) if r["stop_price"] else None,
                "rsi": db.num(rsi[-1], 1),
                "group_state": gs[0] if gs else None, "group_reason": gs[1] if gs else None,
            })
    out.sort(key=lambda r: (r["bars_since_confirm"], rd.TYPES.index(r["type"]), abs(r["distance_to_trigger_pct"] or 0)))
    ctx = {"universe": int(len(uni)), "group_state_available": bool(groups)}
    return out, ctx


def scan(as_of: date | None, tf: str = "D", side: str | None = None, types: Iterable[str] | None = None,
         window: int = WINDOW_DEFAULT, status: Iterable[str] | None = None) -> Result:
    tf = _check_tf(tf)
    window = max(1, min(int(window), 60))
    side = (side or "").lower() or None
    if side not in (None, "bull", "bear"):
        raise ValueError("side must be bull or bear")
    tset = {t.strip().capitalize() for t in (types or []) if t and t.strip()}
    bad = tset - set(rd.TYPES)
    if bad:
        raise ValueError(f"unknown type(s): {', '.join(sorted(bad))}; use {', '.join(rd.TYPES)}")
    sset = {s.strip().lower() for s in (status or []) if s and s.strip()}
    if sset - set(rd.STATUSES):
        raise ValueError(f"status must be among {', '.join(rd.STATUSES)}")
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
    if resolved is None:
        return no_session(as_of)
    # One cached pass per (session, tf) over the widest window; narrower windows filter it.
    rows, ctx = db.cached("divergence.scan", (resolved, tf), lambda: _scan_all(resolved, tf, 60))
    rows = [r for r in rows if r["bars_since_confirm"] < window]
    counts = {f"{s}:{t}": 0 for s in rd.SIDES for t in rd.TYPES}
    for r in rows:
        counts[f"{r['side']}:{r['type']}"] += 1
    picked = [r for r in rows if (side is None or r["side"] == side) and (not tset or r["type"] in tset)
              and (not sset or r["status"] in sset)]
    notes = [f"Divergences confirmed in the last {window} {tf} bar(s) up to as_of, stocks >= Rs 1,000 Cr market cap.",
             "Market cap is today's stocks_master value (no as-of market cap yet)."]
    if not ctx.get("group_state_available"):
        notes.append("Group state unavailable (group_daily missing).")
    return Result(as_of=resolved, rows=picked, sources=SOURCES, notes=notes,
                  extra={**ctx, "timeframe": tf, "window": window, "counts": counts, "rules": RULES})
