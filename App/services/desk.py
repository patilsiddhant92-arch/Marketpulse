"""Desk queues: Darvas Squeeze, Darvas 10 EMA, VCP (spec §7.2).

Source of truth, in order:
1. `setup_daily` (data layer §4.5) when it exists — rows are read, not recomputed.
2. Otherwise the queues are computed in-process with the same predicate
   functions the old Action Desk used (`Scripts.darvas_squeeze.squeeze_frame`,
   `classify_darvas_10ema_frame`) plus `Scripts.minervini_geometry.detect_contractions`
   for VCP (spec §7.2), bounded to `as_of`. Moved out of the NiceGUI page
   (`App/pages/action_desk.fetch_action_desk_data`) without its fabricated
   fallbacks: no CMP×k pivots/stops, no default VDU, no display caps.

Geometry:
- Darvas Squeeze: trigger = Darvas box top; stop = 10 EMA − 1.5% (weekly/monthly:
  EMA floor − 1.5%) — the existing desk rule.
- Darvas 10 EMA (spec §14.1, accepted): trigger = high of the latest completed
  session (the session before the entry day); stop = lowest low since the
  10 EMA touch (signal_date).
- VCP: ≥ 2 strictly shrinking contractions; pivot = last-T high, stop = last-T low;
  close must still be inside the base (stop < close ≤ pivot × 1.03).
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from App.services import db, universe
from App.services.common import STATUS_OK, STATUS_PARTIAL, Result, no_session, unavailable

try:
    from Scripts.darvas_squeeze import DARVAS, WEEKLY_LOOKBACK_SESSIONS, classify_darvas_10ema_frame, squeeze_frame
    from Scripts.desk_contract import POOL
    from Scripts.minervini_geometry import detect_contractions
except ModuleNotFoundError:  # pragma: no cover - script-style import
    from darvas_squeeze import DARVAS, WEEKLY_LOOKBACK_SESSIONS, classify_darvas_10ema_frame, squeeze_frame  # type: ignore
    from desk_contract import POOL  # type: ignore
    from minervini_geometry import detect_contractions  # type: ignore

QUEUES: dict[str, dict[str, Any]] = {
    "darvas_squeeze": {
        "label": "Darvas Squeeze",
        "timeframes": ["D", "W", "M"],
        "description": "Price coiled just under the Darvas box top with the rising 10/20 EMA squeezing up into it.",
    },
    "darvas_10ema": {
        "label": "Darvas 10 EMA",
        "timeframes": ["D", "W", "M"],
        "description": "Strong stock pulling back to / tagging a rising 10 EMA (Pullback, Trace-back, Catch-up).",
    },
    "vcp": {
        "label": "VCP",
        "timeframes": ["D"],
        "description": "Volatility contraction: two or more successively shallower pullbacks, pivot at the last T high.",
    },
}
QUEUE_METRICS = [
    "change_1d_pct", "trigger_price", "stop_price", "distance_to_trigger_pct", "risk_pct", "rvol",
    "delivery_pct", "delivery_vs_20d", "rs_percentile", "rs_delta_5", "excess_vs_midsml400_63d",
    "setup_age_sessions", "squeeze_pct", "candle_range_pct", "darvas_box_top", "darvas_box_bottom",
    "darvas_10ema_flavor", "vcp_contractions", "vcp_depth_pct", "vdu_ratio", "deal_net_10s_cr", "rrg_quadrant",
]
# Same VCP rule as the served queue (Scripts/derived/setup_daily.py): 150-session window, close at or
# below the pivot, Stage-2 gates from Scripts.vcp.VCP (close >= 30, within 25% of the 52W high, 20d
# volume >= 100k) - so "why / why not" answers match queue membership.
VCP_MIN_CONTRACTIONS = 2
VCP_WINDOW = 150
VCP_MAX_ABOVE_PIVOT = 1.0
VCP_MIN_AVG_VOLUME_20D = 100_000
VCP_MIN_CLOSE = 30.0
VCP_MAX_AWAY_52W_HIGH_PCT = -25.0
STOP_BUFFER = 0.985


def validate_queue(name: str) -> str:
    key = str(name or "").strip().lower()
    if key not in QUEUES:
        raise KeyError(key)
    return key


# --------------------------------------------------------------------------
# Live computation (fallback when setup_daily is absent)
# --------------------------------------------------------------------------
def _pool(con: Any, as_of: date, symbol: str | None = None) -> pd.DataFrame:
    sql = universe.snapshot_sql(
        con,
        extra_where=("AND i.symbol = ?" if symbol else "") + """
          AND i.symbol NOT LIKE '%-RE' AND i.symbol NOT LIKE '%\\_RE' ESCAPE '\\'
          AND COALESCE(i.avg_traded_value_cr_20d, i.turnover_cr) >= ?
          AND COALESCE(m.band_remarks, '') NOT LIKE '%GSM%'
          AND COALESCE(m.band_remarks, '') NOT LIKE '%STAGE 2%'
        """,
        extra_cols=", i.high_price, i.low_price, i.open_price, i.avg_delivery_pct_20d",
    )
    params: list[Any] = [as_of] + ([symbol] if symbol else []) + [float(POOL["min_adv_cr"])]
    frame = con.execute(sql, params).fetchdf()
    if frame.empty:
        return frame
    mcap = pd.to_numeric(frame["market_cap_cr"], errors="coerce")
    band = pd.to_numeric(frame["circuit_band"], errors="coerce")
    keep = (mcap >= float(POOL["min_mcap"])) & (band.isna() | (band > float(POOL["min_band"])))
    return frame.loc[keep].reset_index(drop=True)


def _history(con: Any, as_of: date, symbols: list[str], sessions: int) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    window = db.recent_sessions(con, as_of, sessions)
    if not window:
        return pd.DataFrame()
    start = window[-1]
    cols = set(db.table_columns(con, "prices_daily")) if db.table_exists(con, "prices_daily") else set()
    adj = {c: f"COALESCE(p.adj_{c}, i.{c})" if f"adj_{c}" in cols else f"i.{c}"
           for c in ("open_price", "high_price", "low_price", "close_price")}
    vol = "COALESCE(p.adj_volume, i.volume)" if "adj_volume" in cols else "i.volume"
    join = "LEFT JOIN prices_daily p ON p.symbol = i.symbol AND p.trade_date = i.trade_date" if any(
        c.startswith("adj_") for c in cols) else ""
    tbl = pd.DataFrame({"symbol": symbols})
    con.register("desk_pool_syms", tbl)
    try:
        return con.execute(
            f"""
            SELECT i.symbol, i.trade_date,
                   {adj['open_price']} AS open_price, {adj['high_price']} AS high_price,
                   {adj['low_price']} AS low_price, {adj['close_price']} AS close_price,
                   {vol} AS volume,
                   i.ema_10, i.ema_20, i.rvol, i.ema_shakeout, i.close_location_pct, i.avg_volume_20d
            FROM indicators_daily i
            JOIN desk_pool_syms s ON s.symbol = i.symbol
            {join}
            WHERE i.trade_date BETWEEN ? AND ?
            ORDER BY i.symbol, i.trade_date
            """,
            [start, as_of],
        ).fetchdf()
    finally:
        con.unregister("desk_pool_syms")


def _last_sessions(hist: pd.DataFrame, n: int) -> pd.DataFrame:
    if hist.empty:
        return hist
    dates = pd.Series(pd.to_datetime(hist["trade_date"]).unique()).sort_values()
    keep = set(dates.tail(int(n)))
    return hist.loc[pd.to_datetime(hist["trade_date"]).isin(keep)].copy()


def _above_200(frame: pd.DataFrame) -> pd.DataFrame:
    ema200 = pd.to_numeric(frame["ema_200"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    return frame.loc[(close > ema200) | ema200.isna()].copy()


def _vdu_ratio(g: pd.DataFrame) -> float | None:
    vol = pd.to_numeric(g["volume"], errors="coerce").dropna()
    if len(vol) < 20:
        return None
    v20 = float(vol.tail(20).mean())
    if not np.isfinite(v20) or v20 <= 0:
        return None
    return round(float(vol.tail(3).mean()) / v20, 2)


def _darvas_squeeze(pool: pd.DataFrame, hist: pd.DataFrame, tf: str, as_of: date) -> pd.DataFrame:
    if tf == "D":
        frame = squeeze_frame(_last_sessions(hist, int(DARVAS["box_lookback_sessions"])), timeframe="D")
    else:
        frame = squeeze_frame(hist, timeframe=tf, as_of=as_of)
    if frame.empty:
        return pd.DataFrame()
    cand = frame.loc[frame["qualifies"].astype(bool)]
    out = _above_200(pool.merge(cand, on="symbol", how="inner"))
    if out.empty:
        return out
    stop_base = pd.to_numeric(out["ema_floor"], errors="coerce") if tf != "D" else pd.to_numeric(out["ema_10"], errors="coerce")
    out["trigger_price"] = pd.to_numeric(out["darvas_top"], errors="coerce")
    out["stop_price"] = stop_base * STOP_BUFFER
    return out.sort_values(["squeeze_pct", "candle_range_pct"], na_position="last")


def _darvas_10ema(pool: pd.DataFrame, hist: pd.DataFrame, tf: str, as_of: date, exclude: set[str]) -> pd.DataFrame:
    if tf == "D":
        daily = _last_sessions(hist, int(DARVAS["box_lookback_sessions"]))
        flav = classify_darvas_10ema_frame(daily)
    else:
        daily = hist
        flav = classify_darvas_10ema_frame(hist, timeframe=tf, as_of=as_of)
    if flav is None or flav.empty:
        return pd.DataFrame()
    flav = flav.loc[~flav["symbol"].isin(exclude)]
    keep = [c for c in ("symbol", "flavor", "thrust_pct", "away_10ema_pct", "signal_date") if c in flav.columns]
    flav = flav[keep].rename(columns={"away_10ema_pct": "flavor_away_10ema_pct"})
    out = _above_200(pool.merge(flav, on="symbol", how="inner"))
    if out.empty:
        return out
    triggers, stops = [], []
    by_sym = {s: g for s, g in hist.groupby("symbol")} if tf == "D" else {}
    for rec in out.to_dict("records"):
        trig = stop = None
        g = by_sym.get(rec["symbol"])
        sig = db.to_date(rec.get("signal_date"))
        if g is not None and sig is not None:
            d = pd.to_datetime(g["trade_date"]).dt.date
            last = g.loc[d == as_of]
            since = g.loc[(d >= sig) & (d <= as_of)]
            if not last.empty:
                trig = db.num(last["high_price"].iloc[-1])
            if not since.empty:
                stop = db.num(pd.to_numeric(since["low_price"], errors="coerce").min())
        triggers.append(trig)
        stops.append(stop)
    out["trigger_price"] = triggers
    out["stop_price"] = stops
    rank = {"Pullback": 0, "Trace-back": 1, "Catch-up": 2}
    out["_r"] = out["flavor"].map(rank).fillna(9)
    return out.sort_values(["_r", "flavor_away_10ema_pct"], na_position="last").drop(columns=["_r"])


def _vcp(pool: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    base = _above_200(pool)
    if base.empty or hist.empty:
        return pd.DataFrame()
    avg_vol = pd.to_numeric(base["avg_volume_20d"], errors="coerce")
    close = pd.to_numeric(base["close"], errors="coerce")
    away = pd.to_numeric(base["away_52w_high_pct"], errors="coerce") if "away_52w_high_pct" in base else pd.Series(np.nan, index=base.index)
    base = base.loc[(avg_vol.isna() | (avg_vol >= VCP_MIN_AVG_VOLUME_20D)) & (close >= VCP_MIN_CLOSE)
                    & (away.isna() | (away >= VCP_MAX_AWAY_52W_HIGH_PCT))]
    wanted = set(base["symbol"])
    rows = []
    for sym, g in hist.groupby("symbol"):
        if sym not in wanted or len(g) < 60:
            continue
        g = g.tail(VCP_WINDOW).reset_index(drop=True)
        seq = detect_contractions(g[["trade_date", "open_price", "high_price", "low_price", "close_price", "volume"]])
        if len(seq.contractions) < VCP_MIN_CONTRACTIONS or seq.pivot is None or seq.stop is None:
            continue
        last_close = float(g["close_price"].iloc[-1])
        if not (seq.stop < last_close <= seq.pivot * VCP_MAX_ABOVE_PIVOT):
            continue
        rows.append({
            "symbol": sym,
            "trigger_price": float(seq.pivot),
            "stop_price": float(seq.stop),
            "vcp_contractions": [
                {
                    "label": c.label,
                    "start_date": db.to_date(c.start_date),
                    "trough_date": db.to_date(c.trough_date),
                    "end_date": db.to_date(c.end_date),
                    "peak": round(float(c.peak), 2),
                    "trough": round(float(c.trough), 2),
                    "depth_pct": round(float(c.depth_pct), 2),
                    "bars": int(c.bars),
                    "volume_ratio": db.num(c.volume_ratio, 2),
                }
                for c in seq.contractions
            ],
            "vcp_weeks": seq.weeks,
            "vdu_ratio": _vdu_ratio(g),
        })
    if not rows:
        return pd.DataFrame()
    out = base.merge(pd.DataFrame(rows), on="symbol", how="inner")
    out["_dist"] = (pd.to_numeric(out["trigger_price"]) / pd.to_numeric(out["close"]) - 1.0).abs()
    return out.sort_values("_dist").drop(columns=["_dist"])


def _compute_group(con: Any, as_of: date, tf: str, symbol: str | None = None) -> dict[str, pd.DataFrame]:
    """All live queues for one timeframe (they share the pool, history and exclusions)."""
    pool = _pool(con, as_of, symbol)
    out: dict[str, pd.DataFrame] = {}
    if pool.empty:
        return out
    lookback = int(DARVAS["box_lookback_sessions"]) if tf == "D" else int(WEEKLY_LOOKBACK_SESSIONS)
    hist = _history(con, as_of, pool["symbol"].tolist(), lookback)
    if hist.empty:
        return out
    sq = _darvas_squeeze(pool, hist, tf, as_of)
    out["darvas_squeeze"] = sq
    out["darvas_10ema"] = _darvas_10ema(pool, hist, tf, as_of, set(sq["symbol"]) if not sq.empty else set())
    if tf == "D":
        out["vcp"] = _vcp(pool, hist)
    return out


def _live_queues(con: Any, as_of: date, tf: str) -> dict[str, pd.DataFrame]:
    return db.cached("desk.live", (as_of, tf), lambda: _compute_group(con, as_of, tf))


def stock_setups(con: Any, as_of: date, symbol: str) -> dict[str, Any]:
    """Which Desk queues (daily) the symbol is in on as_of — same predicates as the queues."""
    out: dict[str, Any] = {}
    for q in QUEUES:
        frame = _setup_daily_rows(con, as_of, q, "D")
        if frame is not None and not frame.empty:
            hit = frame.loc[frame["symbol"] == symbol]
            out[q] = _shape(hit, q, "D", as_of, con, None)[0] if not hit.empty else None
    if len(out) == len(QUEUES):
        return out
    live = db.cached("desk.stock_setups", (as_of, symbol), lambda: _compute_group(con, as_of, "D", symbol))
    for q in QUEUES:
        if q in out:
            continue
        frame = live.get(q, pd.DataFrame())
        out[q] = _shape(frame, q, "D", as_of, con, None)[0] if frame is not None and not frame.empty else None
    return out


# --------------------------------------------------------------------------
# setup_daily reader
# --------------------------------------------------------------------------
_SETUP_COL_ALIASES = {
    "queue": ("queue", "queue_name", "setup_type"),
    "trigger_price": ("trigger_price", "trigger"),
    "stop_price": ("stop_price", "stop", "stop_loss"),
    "risk_pct": ("risk_pct",),
    "distance_to_trigger_pct": ("distance_to_trigger_pct", "distance_pct", "distance"),
    "first_seen": ("first_seen", "first_seen_date"),
    "status": ("status",),
    "timeframe": ("timeframe", "tf"),
    "features": ("features", "features_snapshot", "feature_snapshot"),
}


def _setup_cols(con: Any) -> dict[str, str]:
    cols = set(db.table_columns(con, "setup_daily"))
    return {k: next((c for c in names if c in cols), "") for k, names in _SETUP_COL_ALIASES.items()}


def _setup_daily_rows(con: Any, as_of: date, queue: str, tf: str) -> pd.DataFrame | None:
    """Rows from setup_daily, or None when the table does not carry this queue/session."""
    if not db.table_exists(con, "setup_daily"):
        return None
    c = _setup_cols(con)
    if not c["queue"]:
        return None
    where = [f"s.{db.quote_ident(c['queue'])} = ?", "s.trade_date = ?"]
    params: list[Any] = [queue, as_of]
    if c["timeframe"]:
        where.append(f"COALESCE(CAST(s.{db.quote_ident(c['timeframe'])} AS VARCHAR), 'D') = ?")
        params.append(tf)
    elif tf != "D":
        return None
    sel = [f"s.{db.quote_ident(v)} AS {k}" for k, v in c.items() if v and k not in ("queue", "timeframe")]
    snap = universe.snapshot_sql(con)
    frame = con.execute(
        f"""
        WITH snap AS ({snap})
        SELECT snap.*, {', '.join(sel) if sel else 'NULL AS _none'}
        FROM setup_daily s
        JOIN snap ON snap.symbol = s.symbol
        WHERE {' AND '.join(where)}
        """,
        [as_of, *params],
    ).fetchdf()
    return frame


# --------------------------------------------------------------------------
# Shaping
# --------------------------------------------------------------------------
def _parse_features(val: Any) -> dict[str, Any]:
    if isinstance(val, dict):
        return val
    if isinstance(val, str) and val.strip().startswith("{"):
        try:
            return json.loads(val)
        except ValueError:
            return {}
    return {}


def _shape(frame: pd.DataFrame, queue: str, tf: str, as_of: date, con: Any, prev_syms: set[str] | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    syms = frame["symbol"].astype(str).tolist()
    events = universe.upcoming_events(con, syms, as_of)
    has_events = db.table_exists(con, "security_events")
    deals = universe.deal_net_recent(con, syms, as_of)
    quads = universe.industry_quadrants(con, as_of)
    rows = []
    for rec in frame.to_dict("records"):
        feats = _parse_features(rec.get("features"))
        base = universe.shape_stock(rec)
        close = base["close"]
        trig = db.num(rec.get("trigger_price"), 2)
        stop = db.num(rec.get("stop_price"), 2)
        dist = db.num(rec.get("distance_to_trigger_pct"), 2)
        if dist is None and trig is not None and close:
            dist = round((trig / close - 1.0) * 100.0, 2)
        risk = db.num(rec.get("risk_pct"), 2)
        if risk is None and trig is not None and stop is not None and stop > 0 and trig > stop:
            risk = round((trig / stop - 1.0) * 100.0, 2)
        sym = base["symbol"]
        ev = events.get(sym)
        vcp_list = rec.get("vcp_contractions") if isinstance(rec.get("vcp_contractions"), list) else feats.get("contractions")
        row = {
            **base,
            "queue": queue,
            "timeframe": tf,
            "trigger_price": trig,
            "stop_price": stop,
            "distance_to_trigger_pct": dist,
            "risk_pct": risk,
            "risk_flag": bool(risk is not None and risk > 8.0),
            "first_seen": db.to_date(rec.get("first_seen")),
            "setup_age_sessions": db.integer(rec.get("setup_age_sessions", feats.get("setup_age_sessions"))),
            "is_new": (sym not in prev_syms) if prev_syms is not None else None,
            "industry_quadrant": (quads.get(base["industry"] or "") or {}).get("quadrant"),
            "results_within_10": bool(ev) if has_events else None,
            "next_event": ev,
            "deal_net_10s_cr": deals.get(sym),
            "squeeze_pct": db.num(rec.get("squeeze_pct", feats.get("squeeze_pct")), 2),
            "candle_range_pct": db.num(rec.get("candle_range_pct", feats.get("candle_range_pct")), 2),
            "darvas_box_top": db.num(rec.get("darvas_top", feats.get("darvas_top")), 2),
            "darvas_box_bottom": db.num(rec.get("darvas_bottom", feats.get("darvas_bottom")), 2),
            "darvas_10ema_flavor": db.text(rec.get("flavor", feats.get("flavor"))),
            "signal_date": db.to_date(rec.get("signal_date", feats.get("signal_date"))),
            "vcp_contractions": vcp_list if isinstance(vcp_list, list) else None,
            "vcp_depth_pct": (vcp_list[-1].get("depth_pct") if isinstance(vcp_list, list) and vcp_list else None),
            "vdu_ratio": db.num(rec.get("vdu_ratio", feats.get("vdu_ratio")), 2),
            "status": db.text(rec.get("status")),
        }
        rows.append(row)
    return rows


def _queue_frame(con: Any, as_of: date, queue: str, tf: str) -> tuple[pd.DataFrame, str]:
    frame = _setup_daily_rows(con, as_of, queue, tf)
    if frame is not None and not frame.empty:
        return frame, "setup_daily"
    live = _live_queues(con, as_of, tf)
    return live.get(queue, pd.DataFrame()), "live"


def queue_rows(as_of: date | None, queue: str, tf: str = "D") -> Result:
    queue = validate_queue(queue)
    tf = tf.upper()
    if tf not in QUEUES[queue]["timeframes"]:
        return unavailable(None, f"timeframe {tf} is not offered for {queue}", [])
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)

        def compute() -> tuple[list[dict[str, Any]], str]:
            frame, source = _queue_frame(con, resolved, queue, tf)
            prev = db.session_back(con, resolved, 1)
            prev_syms = None
            if prev is not None:
                pframe, _ = _queue_frame(con, prev, queue, tf)
                prev_syms = set(pframe["symbol"].astype(str)) if not pframe.empty else set()
            return _shape(frame, queue, tf, resolved, con, prev_syms), source

        rows, source = db.cached("desk.queue", (resolved, queue, tf), compute)
    notes = [
        "Darvas 10 EMA: trigger = latest session high, stop = lowest low since the 10 EMA touch.",
        "Darvas Squeeze: trigger = box top, stop = 10 EMA (weekly/monthly: EMA floor) less 1.5%.",
        "VCP: pivot = last contraction high, stop = last contraction low (detect_contractions).",
    ]
    status = STATUS_OK
    reason = None
    if source == "live":
        status = STATUS_PARTIAL
        reason = "setup_daily not built yet; queue computed live — setup age / first-seen unavailable"
    return Result(
        as_of=resolved,
        rows=rows,
        status=status,
        reason=reason,
        sources=["setup_daily"] if source == "setup_daily" else ["indicators_daily", "prices_daily", "stocks_master"],
        notes=notes,
        extra={"queue": queue, "timeframe": tf, "label": QUEUES[queue]["label"]},
        metric_keys=QUEUE_METRICS,
    )


def queues_summary(as_of: date | None, all_timeframes: bool = False) -> Result:
    """Queue list with counts. Weekly/monthly counts are only computed when asked (slow live path)."""
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        rows = []
        sources: set[str] = set()
        for name, meta in QUEUES.items():
            counts = {}
            for tf in meta["timeframes"]:
                if tf != "D" and not all_timeframes:
                    counts[tf] = None
                    continue
                frame, source = _queue_frame(con, resolved, name, tf)
                counts[tf] = int(len(frame))
                sources.add(source)
            rows.append({
                "name": name,
                "label": meta["label"],
                "description": meta["description"],
                "timeframes": meta["timeframes"],
                "counts": counts,
                "count": counts.get("D", 0),
            })
    live = "live" in sources
    return Result(
        as_of=resolved,
        rows=rows,
        status=STATUS_PARTIAL if live else STATUS_OK,
        reason="setup_daily not built yet; queues computed live" if live else None,
        sources=sorted({"setup_daily"} if not live else {"indicators_daily", "prices_daily"}),
    )


def diff(as_of: date | None, queue: str | None = None, tf: str = "D") -> Result:
    names = [validate_queue(queue)] if queue else list(QUEUES)
    tf = tf.upper()
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        prev = db.session_back(con, resolved, 1)
        if prev is None:
            return unavailable(resolved, "no previous session to compare against", ["indicators_daily"])
        rows = []
        for name in names:
            if tf not in QUEUES[name]["timeframes"]:
                continue
            today, _ = _queue_frame(con, resolved, name, tf)
            yday, _ = _queue_frame(con, prev, name, tf)
            t_syms = set(today["symbol"].astype(str)) if not today.empty else set()
            y_syms = set(yday["symbol"].astype(str)) if not yday.empty else set()
            for change, syms, frame in (("new", t_syms - y_syms, today), ("dropped", y_syms - t_syms, yday)):
                if not syms:
                    continue
                sub = frame.loc[frame["symbol"].isin(syms)]
                for rec in sub.to_dict("records"):
                    base = universe.shape_stock(rec)
                    rows.append({
                        "queue": name,
                        "timeframe": tf,
                        "change": change,
                        "symbol": base["symbol"],
                        "session": resolved if change == "new" else prev,
                        "close": base["close"],
                        "rs_percentile": base["rs_percentile"],
                        "industry": base["industry"],
                    })
    rows.sort(key=lambda r: (r["queue"], r["change"], r["symbol"] or ""))
    return Result(
        as_of=resolved,
        rows=rows,
        sources=["indicators_daily"],
        extra={"previous_session": prev},
        notes=["'dropped' rows show the stock as it was on the previous session."],
    )


# --------------------------------------------------------------------------
# Watchlist snapshot (Desk watchlist panel)
# --------------------------------------------------------------------------
WATCH_QUEUE_ORDER = ("vcp", "darvas_squeeze", "darvas_10ema")


def watchlist_rows(as_of: date | None, symbols: list[str]) -> Result:
    """Snapshot of the given symbols on as_of plus which daily Desk queues each one is in.

    Order is the caller's (watchlist order). A symbol without a row on or before as_of is
    returned with NULL fields (never dropped, never filled). Queue membership comes from the
    same queue frames the Desk shows (setup_daily or the live predicates).
    """
    seen: list[str] = []
    for s in symbols:
        if s and s not in seen:
            seen.append(s)
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        snaps: dict[str, dict[str, Any]] = {}
        if seen:
            ph = ",".join(["?"] * len(seen))
            sql = universe.snapshot_sql(con, extra_where=f"AND i.symbol IN ({ph})")
            for rec in db.records(con, sql, [resolved, *seen]):
                snaps[str(rec["symbol"])] = rec
        frames: dict[str, pd.DataFrame] = {}
        sources: set[str] = set()
        if seen:
            for q in QUEUES:
                frame, source = _queue_frame(con, resolved, q, "D")
                frames[q] = frame
                sources.add(source)
        has_events = db.table_exists(con, "security_events")
        events = universe.upcoming_events(con, seen, resolved) if seen else {}
    rows = []
    for sym in seen:
        rec = snaps.get(sym)
        base = universe.shape_stock(rec) if rec else {**universe.shape_stock({}), "symbol": sym}
        queues: list[str] = []
        best: dict[str, Any] | None = None
        for q in WATCH_QUEUE_ORDER:
            frame = frames.get(q)
            if frame is None or frame.empty:
                continue
            hit = frame.loc[frame["symbol"].astype(str) == sym]
            if hit.empty:
                continue
            queues.append(q)
            if best is None:
                best = hit.iloc[0].to_dict()
        trig = db.num(best.get("trigger_price"), 2) if best else None
        stop = db.num(best.get("stop_price"), 2) if best else None
        close = base["close"]
        dist = round((trig / close - 1.0) * 100.0, 2) if trig is not None and close else None
        risk = round((trig / stop - 1.0) * 100.0, 2) if trig is not None and stop and trig > stop else None
        rows.append({
            **base,
            "trade_date": db.to_date(rec.get("trade_date")) if rec else None,
            "has_data": rec is not None,
            "queues": queues,
            "primary_queue": queues[0] if queues else None,
            "trigger_price": trig,
            "stop_price": stop,
            "distance_to_trigger_pct": dist,
            "risk_pct": risk,
            "away_52w_high_pct": db.num(rec.get("away_52w_high_pct"), 2) if rec else None,
            "results_within_10": (sym in events) if has_events else None,
            "next_event": events.get(sym),
        })
    live = "live" in sources
    return Result(
        as_of=resolved,
        rows=rows,
        status=STATUS_PARTIAL if live else STATUS_OK,
        reason="setup_daily not built yet; queue membership computed live" if live else None,
        sources=["indicators_daily", "stocks_master"] + (["setup_daily"] if "setup_daily" in sources else []),
        notes=["Trigger/stop come from the first queue the stock is in (VCP, then Darvas Squeeze, then Darvas 10 EMA)."],
        metric_keys=["change_1d_pct", "rs_percentile", "rs_delta_5", "distance_to_trigger_pct", "risk_pct",
                     "away_52w_high_pct", "rvol", "delivery_vs_20d"],
    )
