"""Stock 360 services: header, bars (D/W/M), RS line, events, deals, analogs (spec §7.7).

Prices use the adjusted columns (`adj_*`) when `prices_daily` carries them,
falling back to raw columns (today's live DB). Everything is bounded to as_of.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from App.services import data_gaps, db, deals, desk, universe
from App.services.common import Result, is_trading_day, load_holidays, no_session, unavailable

SYMBOL_RE = re.compile(r"^[A-Z0-9&\-_.]{1,20}$")
EMA_SPANS = (10, 20, 50, 200)
MAX_BARS = 5000
STOCK_METRICS = [
    "rs_percentile", "rs_delta_5", "excess_vs_midsml400_63d", "excess_vs_nifty50_63d", "rs_vs_sector_index_63d",
    "trend_template_pass_n", "away_52w_high_pct", "adr_20_pct", "rvol", "delivery_pct", "market_cap_cr",
    "circuit_band", "change_1d_pct",
]


def validate_symbol(raw: str) -> str:
    sym = str(raw or "").strip().upper()
    if not SYMBOL_RE.fullmatch(sym):
        raise ValueError(f"invalid symbol {raw!r}")
    return sym


def _adj_exprs(con: Any) -> tuple[dict[str, str], bool]:
    cols = set(db.table_columns(con, "prices_daily"))
    out = {}
    adjusted = False
    for c in ("open_price", "high_price", "low_price", "close_price", "volume", "delivery_qty"):
        if f"adj_{c}" in cols:
            out[c] = f"COALESCE(p.adj_{c}, p.{c})"
            adjusted = True
        else:
            out[c] = f"p.{c}"
    return out, adjusted


def _adjustments(con: Any, symbol: str, as_of: date) -> list[dict[str, Any]]:
    if not db.table_exists(con, "price_adjustments"):
        return []
    cols = set(db.table_columns(con, "price_adjustments"))
    if not {"symbol", "ex_date"} <= cols:
        return []
    sel = ", ".join(c if c in cols else f"NULL AS {c}" for c in ("factor", "kind", "source", "confidence", "description"))
    raws = db.records(
        con,
        f"SELECT ex_date, {sel} FROM price_adjustments WHERE CAST(symbol AS VARCHAR) = ? AND ex_date <= ? ORDER BY ex_date",
        [symbol, as_of],
    )
    return [{
        "ex_date": db.to_date(r["ex_date"]),
        "kind": db.text(r["kind"]),
        "factor": db.num(r["factor"], 6),
        "source": db.text(r["source"]),
        "confidence": db.text(r["confidence"]),
        "description": db.text(r["description"]),
    } for r in raws]


def header(as_of: date | None, symbol: str) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        snap = universe.snapshot_sql(
            con, extra_where="AND i.symbol = ?",
            extra_cols=", i.high_52w, i.low_52w, i.band_remarks AS band_remarks_i, "
                       f"{data_gaps.guard('i.rs_vs_sector_index_21d', 'rs_vs_sector_index_21d')} AS rs_vs_sector_index_21d, "
                       "m.band_remarks, m.listing_date, m.isin",
        )
        recs = db.records(con, f"WITH s AS ({snap}) SELECT * FROM s", [resolved, symbol])
        if not recs:
            last = con.execute("SELECT max(trade_date) FROM indicators_daily WHERE symbol = ? AND trade_date <= ?",
                               [symbol, resolved]).fetchone()[0]
            if last is None:
                return unavailable(resolved, f"{symbol} has no data on or before {resolved.isoformat()}", ["indicators_daily"])
            recs = db.records(con, f"WITH s AS ({snap}) SELECT * FROM s", [db.to_date(last), symbol])
        r = recs[0]
        row_date = db.to_date(r.get("trade_date"))
        events = universe.upcoming_events(con, [symbol], resolved)
        adjustments = _adjustments(con, symbol, resolved)
        spark = con.execute(
            """
            SELECT list(delivery_pct ORDER BY trade_date) FROM (
                SELECT trade_date, delivery_pct FROM indicators_daily WHERE symbol = ? AND trade_date <= ?
                ORDER BY trade_date DESC LIMIT 60)
            """,
            [symbol, resolved],
        ).fetchone()[0]
        setups = desk.stock_setups(con, resolved, symbol)
        _, adjusted = _adj_exprs(con)
    base = universe.shape_stock(r)
    row = {
        **base,
        "trade_date": row_date,
        "stale_vs_as_of": row_date is not None and row_date < resolved,
        "isin": db.text(r.get("isin")),
        "series": db.text(r.get("series")),
        "prev_close": db.num(r.get("prev_close"), 2),
        "high_52w": db.num(r.get("high_52w"), 2),
        "low_52w": db.num(r.get("low_52w"), 2),
        "away_52w_high_pct": db.num(r.get("away_52w_high_pct"), 2),
        "away_52w_low_pct": db.num(r.get("away_52w_low_pct"), 2),
        "circuit_band": db.num(r.get("circuit_band"), 1),
        "band_remarks": db.text(r.get("band_remarks")),
        "mcap_point_in_time": db.boolean(r.get("mcap_point_in_time")),
        "excess_vs_midsml400_21d": db.num(r.get("excess_vs_midsml400_21d"), 2),
        "excess_vs_nifty50_21d": db.num(r.get("excess_vs_nifty50_21d"), 2),
        "excess_vs_nifty50_63d": db.num(r.get("excess_vs_nifty50_63d"), 2),
        "rs_vs_sector_index_63d": db.num(r.get("rs_vs_sector_index_63d"), 2),
        "sector_index_name": db.text(r.get("sector_index_name")),
        "rs_rank_t5": db.num(r.get("rs_rank_t5"), 1),
        "rs_rank_t15": db.num(r.get("rs_rank_t15"), 1),
        "rs_rank_t30": db.num(r.get("rs_rank_t30"), 1),
        "rs_percentile_ipo": db.num(r.get("rs_percentile_ipo"), 1),
        "trend_template_pass_n": db.integer(r.get("trend_template_pass_n")),
        "trend_template_pass": db.boolean(r.get("trend_template_pass")),
        "adr_20_pct": db.num(r.get("adr_20_pct"), 2),
        "atr_pct": db.num(r.get("atr_pct"), 2),
        "ema_10": db.num(r.get("ema_10"), 2),
        "ema_20": db.num(r.get("ema_20"), 2),
        "ema_50": db.num(r.get("ema_50"), 2),
        "ema_200": db.num(r.get("ema_200"), 2),
        "return_1m_pct": db.num(r.get("return_1m_pct"), 2),
        "return_3m_pct": db.num(r.get("return_3m_pct"), 2),
        "return_6m_pct": db.num(r.get("return_6m_pct"), 2),
        "taxonomy": [
            {"level": k, "name": base[k], "id": f"{k}:{base[k]}" if base[k] else None}
            for k in ("broad_sector", "sector", "broad_industry", "industry")
        ],
        "adjustments": adjustments,
        "prices_adjusted": adjusted,
        "next_event": events.get(symbol),
        "delivery_spark_60": [db.num(v, 1) for v in (spark or [])],
        "setups": setups,
    }
    return Result(as_of=resolved, rows=[row], sources=["indicators_daily", "stocks_master", "security_reference_daily",
                                                       "security_events", "price_adjustments"],
                  metric_keys=STOCK_METRICS)


def _resample(daily: pd.DataFrame, tf: str, as_of: date) -> pd.DataFrame:
    frame = daily.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    rule = "W-FRI" if tf == "W" else "ME"
    g = frame.set_index("trade_date").resample(rule)
    out = pd.DataFrame({
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
        "volume": g["volume"].sum(min_count=1),
        "delivery_qty": g["delivery_qty"].sum(min_count=1),
        "last_session": g["session"].last(),
    }).dropna(subset=["close"])
    out["delivery_pct"] = out["delivery_qty"] / out["volume"].where(out["volume"] > 0) * 100.0
    out["partial"] = out.index.map(lambda d: d.date() > as_of)
    out = out.reset_index().rename(columns={"trade_date": "period_end"})
    out["trade_date"] = out["last_session"]
    return out


def bars(as_of: date | None, symbol: str, tf: str = "D", limit: int = 400) -> Result:
    tf = tf.upper()
    if tf not in ("D", "W", "M"):
        raise ValueError("tf must be D, W or M")
    limit = max(1, min(int(limit), MAX_BARS))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        ex, adjusted = _adj_exprs(con)
        daily = con.execute(
            f"""
            SELECT p.trade_date AS session, p.trade_date,
                   {ex['open_price']} AS open, {ex['high_price']} AS high, {ex['low_price']} AS low,
                   {ex['close_price']} AS close, p.close_price AS raw_close,
                   {ex['volume']} AS volume, {ex['delivery_qty']} AS delivery_qty, p.delivery_pct,
                   i.ema_10, i.ema_20, i.ema_50, i.ema_200
            FROM prices_daily p
            LEFT JOIN indicators_daily i ON i.symbol = p.symbol AND i.trade_date = p.trade_date
            WHERE p.symbol = ? AND p.trade_date <= ?
            ORDER BY p.trade_date
            """,
            [symbol, resolved],
        ).fetchdf()
        adjustments = _adjustments(con, symbol, resolved)
    if daily.empty:
        return unavailable(resolved, f"no bars for {symbol} on or before {resolved.isoformat()}", ["prices_daily"])
    if tf == "D":
        frame = daily.tail(limit)
        rows = [{
            "trade_date": db.to_date(r["trade_date"]),
            "open": db.num(r["open"], 2), "high": db.num(r["high"], 2), "low": db.num(r["low"], 2),
            "close": db.num(r["close"], 2), "raw_close": db.num(r["raw_close"], 2),
            "volume": db.integer(r["volume"]), "delivery_pct": db.num(r["delivery_pct"], 2),
            "ema_10": db.num(r["ema_10"], 2), "ema_20": db.num(r["ema_20"], 2),
            "ema_50": db.num(r["ema_50"], 2), "ema_200": db.num(r["ema_200"], 2),
            "partial": False,
        } for r in frame.to_dict("records")]
    else:
        agg = _resample(daily, tf, resolved)
        for span in EMA_SPANS:
            ema = agg["close"].ewm(span=span, adjust=False, min_periods=span).mean()
            agg[f"ema_{span}"] = ema
        frame = agg.tail(limit)
        rows = [{
            "trade_date": db.to_date(r["trade_date"]),
            "open": db.num(r["open"], 2), "high": db.num(r["high"], 2), "low": db.num(r["low"], 2),
            "close": db.num(r["close"], 2), "raw_close": None,
            "volume": db.integer(r["volume"]), "delivery_pct": db.num(r["delivery_pct"], 2),
            "ema_10": db.num(r["ema_10"], 2), "ema_20": db.num(r["ema_20"], 2),
            "ema_50": db.num(r["ema_50"], 2), "ema_200": db.num(r["ema_200"], 2),
            "partial": bool(r["partial"]),
        } for r in frame.to_dict("records")]
    first = rows[0]["trade_date"] if rows else None
    markers = [
        {"trade_date": a["ex_date"], "kind": a["kind"] or "adjustment", "factor": a["factor"], "text": a["description"]}
        for a in adjustments if first is None or (a["ex_date"] and a["ex_date"] >= first)
    ]
    return Result(
        as_of=resolved, rows=rows, sources=["prices_daily", "indicators_daily", "price_adjustments"],
        extra={"symbol": symbol, "timeframe": tf, "prices_adjusted": adjusted, "markers": markers,
               "total_history_bars": int(len(daily)) if tf == "D" else None},
        notes=([] if adjusted else ["prices_daily has no adj_* columns yet; bars are raw (unadjusted) prices."])
        + (["W/M EMAs are computed on the resampled closes; the last bar may be partial."] if tf != "D" else []),
    )


PROJECTION_BARS = 5


def future_periods(last: date, tf: str, holidays: set[date], n: int = PROJECTION_BARS) -> list[date]:
    """The next `n` bar dates after `last` on the NSE calendar (weekends + holidays skipped).

    D = next sessions; W / M = the last session of each following week / month
    (the date a W/M bar carries, as `weekly_ohlc` / `monthly_ohlc` stamp it).
    """
    out: list[date] = []
    d = last
    if tf == "D":
        while len(out) < n:
            d += timedelta(days=1)
            if is_trading_day(d, holidays):
                out.append(d)
        return out

    def period(x: date) -> tuple[int, int]:
        return tuple(x.isocalendar()[:2]) if tf == "W" else (x.year, x.month)  # type: ignore[return-value]

    cur = period(last)
    best: date | None = None
    for _ in range(3000):
        if len(out) >= n:
            break
        d += timedelta(days=1)
        p = period(d)
        if p != cur:
            if best is not None:
                out.append(best)
            cur, best = p, None
        if is_trading_day(d, holidays):
            best = d
    return out[:n]


def ema_projection(ema: Any, n: int = PROJECTION_BARS) -> list[float] | None:
    """Pine: slope = ema10 - ema10[1]; the dotted line runs to ema10 + slope * n. Returns ema_last + slope * k, k=1..n."""
    vals = [float(v) for v in pd.Series(ema, dtype=float).tolist()]
    if len(vals) < 2 or not all(np.isfinite(vals[-2:])):
        return None
    last, slope = vals[-1], vals[-1] - vals[-2]
    return [last + slope * k for k in range(1, n + 1)]


def darvas(as_of: date | None, symbol: str, tf: str = "D", limit: int = 400) -> Result:
    """Per-bar Darvas TopBox / BottomBox (the user's Pine "SUCCESS" indicator) + 5-bar projections.

    Rows are the bars of `tf` (D sessions; W / M = the bars /bars serves, stamped
    with the period's last session). `top` / `bottom` are exactly
    `Scripts.darvas_squeeze.calculate_darvas_box` (Pine valuewhen, boxp 5) over the
    whole adjusted history (COALESCE(adj_*, raw)), bounded to as_of; NULL before
    the first box. W boxes use completed weeks only (as the queues do), so a
    partial week has no box value. No restarts at data gaps (Pine has none).
    Then `PROJECTION_BARS` rows with `projected` = true at the next calendar
    periods: `top_extension` = the last TopBox (Pine top box extension) and
    `ema_10_projection` = ema10 + slope * k (Pine EMA 10 projection); the last
    real bar carries both lines' starting values.
    """
    try:
        from Scripts.darvas_squeeze import calculate_darvas_box, monthly_ohlc, weekly_ohlc
    except ModuleNotFoundError:  # pragma: no cover - script-style import
        from darvas_squeeze import calculate_darvas_box, monthly_ohlc, weekly_ohlc  # type: ignore

    tf = tf.upper()
    if tf not in ("D", "W", "M"):
        raise ValueError("tf must be D, W or M")
    limit = max(1, min(int(limit), MAX_BARS))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        ex, adjusted = _adj_exprs(con)
        daily = con.execute(
            f"""
            SELECT p.symbol, p.trade_date AS session, p.trade_date,
                   {ex['open_price']} AS open_price, {ex['high_price']} AS high_price,
                   {ex['low_price']} AS low_price, {ex['close_price']} AS close_price,
                   {ex['volume']} AS volume, {ex['delivery_qty']} AS delivery_qty
            FROM prices_daily p
            WHERE p.symbol = ? AND p.trade_date <= ?
            ORDER BY p.trade_date
            """,
            [symbol, resolved],
        ).fetchdf()
    sources = ["prices_daily", "price_adjustments", "nse_holidays"]
    daily = daily.dropna(subset=["high_price", "low_price", "close_price"]).reset_index(drop=True)
    if daily.empty:
        return unavailable(resolved, f"no bars for {symbol} on or before {resolved.isoformat()}", sources)

    # Bar spine = the bars the chart shows for tf (same bars as /bars).
    if tf == "D":
        dates = [db.to_date(d) for d in daily["trade_date"]]
        closes = daily["close_price"].astype(float)
    else:
        agg = _resample(daily.rename(columns={
            "open_price": "open", "high_price": "high", "low_price": "low", "close_price": "close"}), tf, resolved)
        dates = [db.to_date(d) for d in agg["trade_date"]]
        closes = agg["close"].astype(float).reset_index(drop=True)

    # Box series on the queue's bars for tf, mapped onto the spine by bar date.
    frame = daily
    if tf == "W":
        frame = weekly_ohlc(daily, as_of=resolved)
    elif tf == "M":
        frame = monthly_ohlc(daily, as_of=resolved)
    top, bottom = calculate_darvas_box(frame["high_price"].astype(float).values, frame["low_price"].astype(float).values, boxp=5)
    box_by_date = {db.to_date(d): (float(t), float(b)) for d, t, b in zip(frame["trade_date"], top, bottom)}

    ema10 = closes.ewm(span=10, adjust=False, min_periods=10).mean()
    first_i = max(0, len(dates) - limit)
    rows: list[dict[str, Any]] = []
    last_top: float | None = None
    for i, d in enumerate(dates):
        t, b = box_by_date.get(d, (np.nan, np.nan))
        if np.isfinite(t):
            last_top = t
        if i < first_i:
            continue
        rows.append({
            "trade_date": d,
            "top": db.num(t, 2) if np.isfinite(t) else None,
            "bottom": db.num(b, 2) if np.isfinite(b) else None,
            "projected": False, "top_extension": None, "ema_10_projection": None,
        })
    proj = ema_projection(ema10)
    future = future_periods(dates[-1], tf, load_holidays()) if dates and dates[-1] else []
    ext = db.num(last_top, 2) if last_top is not None else None
    if rows:
        rows[-1]["top_extension"] = ext
        rows[-1]["ema_10_projection"] = db.num(float(ema10.iloc[-1]), 2) if proj else None
    for k, d in enumerate(future):
        rows.append({
            "trade_date": d, "top": None, "bottom": None, "projected": True,
            "top_extension": ext, "ema_10_projection": db.num(proj[k], 2) if proj else None,
        })
    return Result(
        as_of=resolved, rows=rows, sources=sources,
        extra={"symbol": symbol, "timeframe": tf, "prices_adjusted": adjusted, "box_period": 5,
               "last_bar_date": dates[-1] if dates else None, "projection_bars": PROJECTION_BARS,
               "future_dates": future},
        notes=["top / bottom = Pine TopBox / BottomBox (boxp 5), the same series as the Darvas Squeeze / 10-EMA queues. "
               f"projected rows = the next {PROJECTION_BARS} {'sessions' if tf == 'D' else 'periods'} on the NSE calendar "
               "(no candles): top_extension = last TopBox, ema_10_projection = EMA10 + slope * k (slope = last EMA10 change)."]
        + (["W boxes use completed weeks only (as the queue does); a partial week has no box value."] if tf == "W" else [])
        + ([] if adjusted else ["prices_daily has no adj_* columns yet; boxes use raw prices."]),
    )


def rs_line(as_of: date | None, symbol: str, limit: int = 400) -> Result:
    limit = max(20, min(int(limit), MAX_BARS))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        ex, adjusted = _adj_exprs(con)
        frame = con.execute(
            f"""
            WITH ix AS (
                SELECT trade_date,
                       max(close_price) FILTER (WHERE index_name = 'NIFTY MIDSML 400') AS midsml400,
                       max(close_price) FILTER (WHERE index_name = 'Nifty 50') AS nifty50
                FROM index_daily WHERE trade_date <= ? AND index_name IN ('NIFTY MIDSML 400', 'Nifty 50')
                GROUP BY trade_date
            )
            SELECT p.trade_date, {ex['close_price']} AS close, ix.midsml400, ix.nifty50
            FROM prices_daily p LEFT JOIN ix ON ix.trade_date = p.trade_date
            WHERE p.symbol = ? AND p.trade_date <= ?
            ORDER BY p.trade_date
            """,
            [resolved, symbol, resolved],
        ).fetchdf()
    if frame.empty:
        return unavailable(resolved, f"no prices for {symbol}", ["prices_daily"])
    for bm in ("midsml400", "nifty50"):
        ratio = frame["close"] / frame[bm]
        frame[f"rs_{bm}"] = ratio
        prior_max = ratio.shift(1).rolling(252, min_periods=60).max()
        frame[f"rs_{bm}_new_high"] = [
            (bool(r > m) if pd.notna(r) and pd.notna(m) else None) for r, m in zip(ratio, prior_max)
        ]
    frame = frame.tail(limit)
    rows = [{
        "trade_date": db.to_date(r["trade_date"]),
        "close": db.num(r["close"], 2),
        "midsml400_close": db.num(r["midsml400"], 2),
        "nifty50_close": db.num(r["nifty50"], 2),
        "rs_midsml400": db.num(r["rs_midsml400"], 6),
        "rs_nifty50": db.num(r["rs_nifty50"], 6),
        "rs_midsml400_new_high": r["rs_midsml400_new_high"],
        "rs_nifty50_new_high": r["rs_nifty50_new_high"],
    } for r in frame.to_dict("records")]
    return Result(as_of=resolved, rows=rows, sources=["prices_daily", "index_daily"],
                  extra={"symbol": symbol, "prices_adjusted": adjusted},
                  notes=["RS line = stock close / benchmark close; new_high = above the prior 252-session RS high."])


def events(as_of: date | None, symbol: str, days_ahead: int = 14) -> Result:
    days_ahead = max(0, min(int(days_ahead), 60))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        horizon = resolved + timedelta(days=days_ahead)
        rows: list[dict[str, Any]] = []
        if db.table_exists(con, "security_events"):
            for r in db.records(
                con,
                "SELECT event_date, event_type, headline FROM security_events WHERE symbol = ? AND event_date <= ? "
                "ORDER BY event_date DESC",
                [symbol, horizon],
            ):
                d = db.to_date(r["event_date"])
                rows.append({"event_date": d, "event_type": db.text(r["event_type"]), "headline": db.text(r["headline"]),
                             "source": "security_events", "upcoming": bool(d and d > resolved)})
        if db.table_exists(con, "corporate_actions"):
            for r in db.records(
                con,
                "SELECT ex_date, action_type, description FROM corporate_actions WHERE symbol = ? AND ex_date <= ? "
                "ORDER BY ex_date DESC",
                [symbol, horizon],
            ):
                d = db.to_date(r["ex_date"])
                rows.append({"event_date": d, "event_type": db.text(r["action_type"]), "headline": db.text(r["description"]),
                             "source": "corporate_actions", "upcoming": bool(d and d > resolved)})
        for a in _adjustments(con, symbol, resolved):
            rows.append({"event_date": a["ex_date"], "event_type": f"adjustment:{a['kind'] or 'unknown'}",
                         "headline": a["description"], "source": "price_adjustments", "upcoming": False})
    rows.sort(key=lambda r: r["event_date"] or date.min, reverse=True)
    return Result(as_of=resolved, rows=rows, sources=["security_events", "corporate_actions", "price_adjustments"],
                  extra={"symbol": symbol, "days_ahead": days_ahead},
                  notes=["corporate_actions ratios are not exposed (known-bad 1.0/1.0 in the warehouse)."])


def stock_deals(as_of: date | None, symbol: str) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not db.table_exists(con, "deals"):
            return unavailable(resolved, "no deals table", ["deals"])
        rows = deals.stock_prints(con, symbol, resolved)
    return Result(as_of=resolved, rows=rows, sources=["deals"], extra={"symbol": symbol},
                  notes=["Bulk ∩ block duplicate prints are collapsed to one row (deal_types lists both)."],
                  metric_keys=["deal_net_cr"])


def analogs(as_of: date | None, symbol: str) -> Result:
    from App.services import evidence  # evidence engine owns stock analogs (setup_outcomes, spec §5)

    return evidence.stock_analogs(as_of, symbol)
