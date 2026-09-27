"""Cross-tab context: what else the platform knows about a stock or a group (connect the dots).

One batched read per table so a table of up to MAX_SYMBOLS stocks never does N+1 requests.

Per stock (`stocks`)
  * group        its industry group at the ₹1,000 Cr floor: Health, zone, rank, RRG quadrant and the
                 quadrant note ("falling" = Leading/Improving vs peers while the group's own 21d return
                 is negative), absolute trend, Health over the last 21 sessions (group_daily or live)
  * deals        bulk/block net ₹ Cr over the last 10 sessions, PROP excluded, prints and last print date
  * setups       Desk queues the stock is in on as_of (setup_daily) with trigger / stop / distance / age
  * data_warning unexplained price gap inside a metric window (App/services/data_gaps.py)
  * events       next results / board meeting and next corporate action within 14 calendar days

Per group (`groups`): the same group block for every group of a level (one request per level).

`why` (Stock 360 "Why is this stock here?") builds plain-language bullets ONLY from those facts plus
the stock's own session numbers, and the evidence line for each queue in the current environment
(setup_outcomes via App/services/evidence.py, n shown; n < 30 says "too few").
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

import pandas as pd

from App.services import db, desk, groups, universe
from App.services.common import STATUS_PARTIAL, Result, no_session, unavailable

MAX_SYMBOLS = 200
DEAL_SESSIONS = 10
EVENT_DAYS = 14
SPARK_SESSIONS = 21
CONTEXT_LEVEL = "industry"
CONTEXT_FLOOR = "1000"
CORP_ACTIONS = ("bonus", "split", "rights_issue", "merger_demerger", "dividend", "consolidation", "demerger")
DEALS_LINK = "/deals?view=repeated&lb=10&floor=all&rdays=1&q={sym}"
QUEUE_LABEL = {k: v["label"] for k, v in desk.QUEUES.items()}


def _ph(symbols: Iterable[str]) -> tuple[str, list[str]]:
    syms = sorted({str(s) for s in symbols if s})
    return ",".join("?" * len(syms)), syms


# --------------------------------------------------------------------------
# Group block
# --------------------------------------------------------------------------
def _group_block(r: dict[str, Any], spark: list[float | None] | None, level_key: str) -> dict[str, Any]:
    health = db.num(r.get("health"), 1)
    stocks = db.integer(r.get("stocks"))
    return {
        "id": groups.group_id(level_key, str(r.get("group_name"))),
        "group_name": db.text(r.get("group_name")),
        "level": level_key,
        "stocks": stocks,
        "thin": bool(stocks is not None and stocks < groups.MIN_MEMBERS_RANK),
        "health": health,
        "health_zone": groups.health_zone(health),
        "health_rank": db.integer(r.get("health_rank")),
        "rrg_quadrant": db.text(r.get("rrg_quadrant")),
        "quadrant_note": db.text(r.get("quadrant_note")),
        "abs_trend": db.text(r.get("abs_trend")),
        "return_ew_21d": db.num(r.get("return_ew_21d"), 2),
        "health_spark_21": spark,
    }


def _group_map(con: Any, as_of: date, level_key: str, floor: str) -> tuple[dict[str, dict[str, Any]], str]:
    df, src = groups._frame(con, as_of, level_key, floor)
    if df is None or df.empty:
        return {}, src
    hist = df[df["trade_date"] <= pd.Timestamp(as_of)]
    last, _ = groups._last_rows(hist, as_of)
    out: dict[str, dict[str, Any]] = {}
    sparks: dict[str, list[float | None] | None] = {}
    if "health" in hist.columns:
        for name, g in hist.groupby("group_name", sort=False):
            h = pd.to_numeric(g["health"], errors="coerce").tail(SPARK_SESSIONS)
            sparks[str(name)] = [db.num(v, 1) for v in h] if h.notna().any() else None
    for r in last.to_dict("records"):
        name = str(r.get("group_name"))
        out[name] = _group_block(r, sparks.get(name), level_key)
    return out, src


def group_map(con: Any, as_of: date, level_key: str = CONTEXT_LEVEL, floor: str = CONTEXT_FLOOR) -> tuple[dict[str, dict[str, Any]], str]:
    return db.cached("context.groups", (as_of, level_key, floor), lambda: _group_map(con, as_of, level_key, floor))


def groups_context(as_of: date | None, level: str = CONTEXT_LEVEL, floor: str = CONTEXT_FLOOR) -> Result:
    level_key = universe.level_key(level)
    if level_key is None:
        raise ValueError(f"unknown level {level!r}")
    groups.floor_value(floor)
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        gm, src = group_map(con, resolved, level_key, floor)
    if not gm:
        return unavailable(resolved, "no group data on or before as_of", ["group_daily", "indicators_daily"])
    rows = sorted(gm.values(), key=lambda r: (r["health_rank"] is None, r["health_rank"] or 0, r["group_name"] or ""))
    return Result(as_of=resolved, rows=rows, status="ok" if src == "group_daily" else STATUS_PARTIAL,
                  reason=None if src == "group_daily" else "group_daily does not cover this level/floor; computed live",
                  sources=["group_daily"] if src == "group_daily" else ["indicators_daily"],
                  extra={"level": level_key, "floor": floor, "spark_sessions": SPARK_SESSIONS},
                  metric_keys=["group_health", "rrg_quadrant", "quadrant_note", "group_abs_trend"])


# --------------------------------------------------------------------------
# Per-stock facts
# --------------------------------------------------------------------------
def _deals(con: Any, syms: list[str], as_of: date) -> dict[str, dict[str, Any]]:
    if not syms or not db.table_exists(con, "deals"):
        return {}
    window = db.recent_sessions(con, as_of, DEAL_SESSIONS)
    if not window:
        return {}
    ph = ",".join("?" * len(syms))
    rows = db.records(con, f"""
        WITH p AS ({universe.collapsed_prints_sql("AND d.symbol IN (" + ph + ") AND d.trade_date BETWEEN ? AND ?")})
        SELECT symbol, count(*) AS prints, max(trade_date) AS last_date,
               sum(CASE WHEN side LIKE '%BUY%' THEN value_cr WHEN side LIKE '%SELL%' THEN -value_cr END) AS net_cr
        FROM p WHERE coalesce(upper(clientele), '') <> 'PROP' AND NOT is_prop GROUP BY symbol""",
        [*syms, window[-1], as_of])
    return {r["symbol"]: {"deal_net_10s_cr": db.num(r["net_cr"], 2), "deal_prints_10s": db.integer(r["prints"]),
                          "deal_last_date": db.to_date(r["last_date"])} for r in rows}


def _setups(con: Any, syms: list[str], as_of: date) -> dict[str, list[dict[str, Any]]]:
    if not syms or not db.table_exists(con, "setup_daily"):
        return {}
    have = set(db.table_columns(con, "setup_daily"))
    if not {"queue", "symbol", "trade_date"} <= have:
        return {}
    opt = [c for c in ("trigger_price", "stop_price", "distance_to_trigger_pct", "risk_pct", "setup_age_sessions",
                       "first_seen", "features") if c in have]
    ph = ",".join("?" * len(syms))
    recs = db.records(con, f"SELECT symbol, queue{''.join(', ' + c for c in opt)} FROM setup_daily "
                           f"WHERE trade_date = ? AND symbol IN ({ph}) ORDER BY queue", [as_of, *syms])
    out: dict[str, list[dict[str, Any]]] = {}
    for r in recs:
        feats = desk._parse_features(r.get("features"))
        out.setdefault(str(r["symbol"]), []).append({
            "queue": str(r["queue"]),
            "label": QUEUE_LABEL.get(str(r["queue"]), str(r["queue"])),
            "trigger_price": db.num(r.get("trigger_price"), 2),
            "stop_price": db.num(r.get("stop_price"), 2),
            "distance_to_trigger_pct": db.num(r.get("distance_to_trigger_pct"), 2),
            "risk_pct": db.num(r.get("risk_pct"), 2),
            "setup_age_sessions": db.integer(r.get("setup_age_sessions")),
            "first_seen": db.to_date(r.get("first_seen")),
            "flavor": db.text(feats.get("flavor")),
        })
    return out


def _corp_actions(con: Any, syms: list[str], as_of: date) -> dict[str, dict[str, Any]]:
    if not syms or not db.table_exists(con, "corporate_actions"):
        return {}
    have = set(db.table_columns(con, "corporate_actions"))
    if not {"symbol", "ex_date", "action_type"} <= have:
        return {}
    desc = "description" if "description" in have else "NULL"
    ph = ",".join("?" * len(syms))
    ph2 = ",".join("?" * len(CORP_ACTIONS))
    recs = db.records(con, f"""
        SELECT symbol, min(ex_date) AS ex_date, arg_min(action_type, ex_date) AS action_type,
               arg_min({desc}, ex_date) AS description
        FROM corporate_actions WHERE symbol IN ({ph}) AND ex_date > ? AND ex_date <= ? AND action_type IN ({ph2})
        GROUP BY symbol""", [*syms, as_of, as_of + timedelta(days=EVENT_DAYS), *CORP_ACTIONS])
    return {r["symbol"]: {"event_type": db.text(r["action_type"]), "event_date": db.to_date(r["ex_date"]),
                          "headline": (db.text(r.get("description")) or "")[:160] or None} for r in recs}


def _snapshot(con: Any, syms: list[str], as_of: date) -> dict[str, dict[str, Any]]:
    if not syms:
        return {}
    ph = ",".join("?" * len(syms))
    snap = universe.snapshot_sql(con, extra_where=f"AND i.symbol IN ({ph})")
    return {r["symbol"]: r for r in db.records(con, f"WITH s AS ({snap}) SELECT * FROM s", [as_of, *syms])}


def _stock_rows(con: Any, syms: list[str], as_of: date) -> tuple[list[dict[str, Any]], str]:
    snap = _snapshot(con, syms, as_of)
    gm, src = group_map(con, as_of)
    deals = _deals(con, syms, as_of)
    setups = _setups(con, syms, as_of)
    results = universe.upcoming_events(con, syms, as_of, EVENT_DAYS)
    actions = _corp_actions(con, syms, as_of)
    rows = []
    for s in syms:
        r = snap.get(s) or {}
        ind = db.text(r.get("industry"))
        d = deals.get(s, {})
        rows.append({
            "symbol": s,
            "security_name": db.text(r.get("security_name")),
            "in_session": bool(r),
            "industry": ind,
            "group": gm.get(ind) if ind else None,
            "deal_net_10s_cr": d.get("deal_net_10s_cr"),
            "deal_prints_10s": d.get("deal_prints_10s") or 0,
            "deal_last_date": d.get("deal_last_date"),
            "setups": setups.get(s, []),
            "data_warning": db.text(r.get("data_warning")),
            "next_results": results.get(s),
            "next_corp_action": actions.get(s),
        })
    return rows, src


def parse_symbols(raw: str | None) -> list[str]:
    syms: list[str] = []
    for part in str(raw or "").split(","):
        s = part.strip().upper()
        if s and s not in syms:
            syms.append(s)
    return syms


def stocks(as_of: date | None, symbols: list[str]) -> Result:
    if len(symbols) > MAX_SYMBOLS:
        raise ValueError(f"at most {MAX_SYMBOLS} symbols per request")
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if not symbols:
            return Result(as_of=resolved, rows=[], sources=[])
        rows, src = _stock_rows(con, symbols, resolved)
        have_setups = db.table_exists(con, "setup_daily")
    notes = [f"Group = the stock's industry at the ₹1,000 Cr floor ({src}). Deals = last {DEAL_SESSIONS} sessions, "
             "PROP excluded. Events = next results / corporate action within 14 days."]
    if not have_setups:
        notes.append("setup_daily not built: active setups unknown.")
    return Result(as_of=resolved, rows=rows, status="ok" if have_setups else STATUS_PARTIAL,
                  reason=None if have_setups else "setup_daily not built",
                  sources=["stocks_master", "group_daily" if src == "group_daily" else "indicators_daily", "deals",
                           "setup_daily", "security_events", "corporate_actions"],
                  extra={"deal_sessions": DEAL_SESSIONS, "event_days": EVENT_DAYS, "group_level": CONTEXT_LEVEL,
                         "group_floor": CONTEXT_FLOOR, "max_symbols": MAX_SYMBOLS},
                  notes=notes, metric_keys=["group_health", "rrg_quadrant", "deal_net_10s_cr"])


# --------------------------------------------------------------------------
# "Why is this stock here?"
# --------------------------------------------------------------------------
def _fmt_cr(v: float) -> str:
    return f"{'+' if v >= 0 else '−'}₹{abs(v):,.1f} Cr"


def _deliv_qty_x(con: Any, symbol: str, as_of: date) -> float | None:
    have = set(db.table_columns(con, "indicators_daily"))
    if not {"delivery_qty", "avg_delivery_qty_20d"} <= have:
        return None
    prev = db.session_back(con, as_of, 1)
    if prev is None:
        return None
    r = con.execute("""
        SELECT t.delivery_qty / nullif(p.avg_delivery_qty_20d, 0)
        FROM indicators_daily t JOIN indicators_daily p ON p.symbol = t.symbol AND p.trade_date = ?
        WHERE t.symbol = ? AND t.trade_date = ?""", [prev, symbol, as_of]).fetchone()
    return db.num(r[0], 2) if r else None


def _verdict(con: Any, as_of: date) -> str | None:
    if not db.table_exists(con, "regime_daily"):
        return None
    r = con.execute("SELECT verdict FROM regime_daily WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 1",
                    [as_of]).fetchone()
    return db.text(r[0]) if r else None


def _evidence_line(as_of: date, queue: str, verdict: str | None) -> dict[str, Any] | None:
    from App.services import evidence

    try:
        res = db.cached("context.evidence", (as_of, queue), lambda: evidence.evidence(as_of, queue, by="environment"))
    except KeyError:
        return None
    if not res.rows:
        return None
    pick = next((r for r in res.rows if verdict and r["bucket"] == verdict), None)
    base = next((r for r in res.rows if r["bucket"] == "all"), None)
    return {"bucket": pick["bucket"] if pick else "all", "row": pick or base, "all": base}


def bullets(ctx: dict[str, Any], snap: dict[str, Any], deliv_qty_x: float | None, verdict: str | None,
            evidence_lines: dict[str, dict[str, Any] | None]) -> list[dict[str, Any]]:
    """Plain-language bullets from facts only. Pure (unit-tested)."""
    out: list[dict[str, Any]] = []

    def add(kind: str, tone: str, text: str, link: str | None = None, **facts: Any) -> None:
        out.append({"kind": kind, "tone": tone, "text": text, "link": link, "facts": facts})

    for s in ctx.get("setups") or []:
        age = s.get("setup_age_sessions")
        bits = [f"In the {s['label']} queue"]
        if age is not None:
            bits.append(f"for {age} session{'s' if age != 1 else ''}")
        text = " ".join(bits)
        desc = (desk.QUEUES.get(s["queue"]) or {}).get("description")
        if s.get("flavor"):
            text += f" ({s['flavor']})"
        text += "."
        if desc:
            text += f" Rule: {desc}"
        add("setup", "accent", text, f"/desk?view=setups&queue={s['queue']}", queue=s["queue"], age=age, flavor=s.get("flavor"))
        trig, stop, dist, risk = s.get("trigger_price"), s.get("stop_price"), s.get("distance_to_trigger_pct"), s.get("risk_pct")
        if trig is not None:
            t = f"Trigger ₹{trig:,.2f}"
            if dist is not None:
                t += f" is {abs(dist):.1f}% {'above' if dist >= 0 else 'below'} the close"
            if stop is not None:
                t += f"; stop ₹{stop:,.2f}"
            if risk is not None:
                t += f" (risk {risk:.1f}%{', wide' if risk > 8 else ''})"
            add("trigger", "warn" if (risk or 0) > 8 else "neutral", t + ".", queue=s["queue"], trigger=trig,
                distance_pct=dist, stop=stop, risk_pct=risk)
        ev = evidence_lines.get(s["queue"])
        row = (ev or {}).get("row")
        if row:
            env = f"a {ev['bucket']} environment" if ev["bucket"] != "all" else "all environments"
            if row.get("insufficient_sample"):
                add("evidence", "neutral", f"Evidence: too few past {s['label']} setups in {env} to judge (n={row['n']}).",
                    "/research?rview=evidence", queue=s["queue"], bucket=ev["bucket"], n=row["n"])
            else:
                add("evidence", "info",
                    f"Evidence: past {s['label']} setups in {env} reached +2R {row['hit_rate_2r']:.0f}% of the time, "
                    f"average {row['avg_r']:+.2f}R (n={row['n']:,}).", "/research?rview=evidence",
                    queue=s["queue"], bucket=ev["bucket"], n=row["n"], hit_rate_2r=row["hit_rate_2r"], avg_r=row["avg_r"])

    g = ctx.get("group")
    if g and g.get("health") is not None:
        t = f"Group {g['group_name']}: Health {g['health']:.0f} ({g['health_zone']})"
        if g.get("health_rank"):
            t += f", #{g['health_rank']} of its level"
        if g.get("rrg_quadrant"):
            t += f"; {g['rrg_quadrant']} vs peers"
            note = g.get("quadrant_note") or ""
            short = ("falling in absolute terms" if "falling" in note else "on narrow breadth" if "narrow" in note
                     else "rising in absolute terms" if "rising" in note else note)
            if short:
                t += f" but {short}"
        spark = [v for v in (g.get("health_spark_21") or []) if v is not None]
        if len(spark) >= 2:
            d = spark[-1] - spark[0]
            t += f"; Health {'up' if d > 0 else 'down' if d < 0 else 'flat'} {abs(d):.0f} over {len(spark)} sessions"
        tone = {"Healthy": "positive", "Mixed": "neutral", "Weak": "negative"}.get(g["health_zone"] or "", "neutral")
        add("group", tone, t + ".", f"/groups?group={g['id']}", group_id=g["id"], health=g["health"],
            quadrant=g.get("rrg_quadrant"), note=g.get("quadrant_note"))
    elif not ctx.get("industry"):
        add("group", "neutral", "No sector / industry in stocks_master: group context unknown (Unclassified).")

    net, prints = ctx.get("deal_net_10s_cr"), ctx.get("deal_prints_10s") or 0
    if prints:
        tone = "positive" if (net or 0) > 0 else "negative" if (net or 0) < 0 else "neutral"
        t = f"Bulk/block deals, last {DEAL_SESSIONS} sessions: {prints} print{'s' if prints != 1 else ''}"
        if net is not None:
            t += f", net {_fmt_cr(net)} (PROP excluded)"
        add("deals", tone, t + ".", DEALS_LINK.format(sym=ctx["symbol"]), net_cr=net, prints=prints)

    rvol = db.num(snap.get("rvol"), 2)
    dpx = db.num(snap.get("deliv_pct_x"), 2)
    chg = db.num(snap.get("change_1d_pct"), 2)
    if rvol is not None or deliv_qty_x is not None:
        parts = []
        if chg is not None:
            parts.append(f"{chg:+.1f}% today")
        if rvol is not None:
            parts.append(f"RVOL {rvol:.2f}")
        if deliv_qty_x is not None:
            parts.append(f"delivered qty {deliv_qty_x:.2f}× its 20-day average")
        if dpx is not None:
            parts.append(f"delivery % {dpx:.2f}× its habit")
        real = rvol is not None and rvol >= 1.5 and deliv_qty_x is not None and deliv_qty_x >= 1.2
        churn = rvol is not None and rvol >= 1.5 and deliv_qty_x is not None and deliv_qty_x < 1.2
        verdict_txt = (" — real participation" if real else " — heavy volume without delivery (churn)" if churn
                       else " — light volume" if rvol is not None and rvol < 1 else "")
        tone = "positive" if real and (chg or 0) >= 0 else "negative" if real else "warn" if churn else "neutral"
        add("footprint", tone, "Footprint: " + ", ".join(parts) + verdict_txt + ".", rvol=rvol,
            deliv_qty_x=deliv_qty_x, deliv_pct_x=dpx, change_1d_pct=chg)

    for key, label in (("next_results", "Results"), ("next_corp_action", "Corporate action")):
        e = ctx.get(key)
        if e and e.get("event_date"):
            kind = (e.get("event_type") or "").replace("_", " ")
            add("event", "warn", f"{label} soon: {kind} on {e['event_date'].strftime('%d %b %Y')}.",
                event_type=e.get("event_type"), event_date=e["event_date"].isoformat())
    if ctx.get("data_warning"):
        add("data", "warn", f"Data check: {ctx['data_warning']} Multi-session numbers spanning it are hidden.")
    if verdict and not (ctx.get("setups") or []):
        add("environment", "neutral", f"Not in a Desk queue today; the environment is {verdict}.", verdict=verdict)
    return out


def why(as_of: date | None, symbol: str) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        rows, _ = _stock_rows(con, [symbol], resolved)
        snap = _snapshot(con, [symbol], resolved).get(symbol) or {}
        dqx = _deliv_qty_x(con, symbol, resolved)
        verdict = _verdict(con, resolved)
    ctx = rows[0]
    if not ctx["in_session"]:
        return unavailable(resolved, f"{symbol} has no row on this session", ["indicators_daily"], symbol=symbol)
    ev = {s["queue"]: _evidence_line(resolved, s["queue"], verdict) for s in ctx["setups"]}
    items = bullets(ctx, snap, dqx, verdict, ev)
    return Result(as_of=resolved, rows=items, sources=["setup_daily", "group_daily", "deals", "indicators_daily",
                                                      "setup_outcomes", "regime_daily"],
                  extra={"symbol": symbol, "verdict": verdict, "context": ctx},
                  notes=["Every bullet restates stored facts; nothing is predicted."])
