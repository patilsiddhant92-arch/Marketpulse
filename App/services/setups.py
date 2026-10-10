"""Setups tab (HarkPro/06-tab2-setups.md, LOCKED 2026-10-09): one board, tags per screener.

Screener membership is read, never recomputed:
  * Darvas Squeeze / Darvas 10 EMA / VCP  -> `setup_daily` (strict gates, desk_contract.DARVAS)
  * Momentum                              -> `App.services.momentum._scan` (parity), with the SMA / EMA
                                             template switch and the day / 20D-avg volume gate.
Every row carries its Industry group's Pulse state (Favour / Neutral / Caution) with a numeric reason,
plus the decision columns (delivery streak, turnover multiples, group flow, base rate, room to run,
stock character, weekly check) and data-backed chips only. Results within N sessions highlights the row
when `security_events` holds a results date; locally it is empty, so the row carries a data gap instead.

Ported from HarkPro/tools/setups_mockup/extract.py; pure rules live in App/services/setups_logic.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from App.services import common, data_gaps, db, group_state, momentum
from App.services import setups_logic as L
from App.services.common import Result, no_session, unavailable

SOURCES = ["setup_daily", "indicators_daily", "stocks_master", "group_daily", "security_reference_daily", "deals"]
MIN_MCAP_CR = 1000.0
HISTORY_BARS = 260
BASE_HORIZON = 20
MIN_BASE_N = 30
RESULTS_N_DEFAULT = 10


@dataclass(frozen=True)
class BoardParams:
    template: str = "ema"          # momentum template: 'ema' (EMA stack, default) or 'sma' (SMA 50>150>200)
    volume_mode: str = "day"       # momentum volume gate: 'day' (parity default) or 'avg20d'
    min_volume: float = 1_000_000.0
    results_n: int = RESULTS_N_DEFAULT

    def momentum_params(self) -> momentum.Params:
        ema = self.template != "sma"
        sma = not ema
        vol = float(self.min_volume)
        return momentum.Params(
            min_volume=vol if self.volume_mode == "day" else 0.0,
            min_avg_volume_20d=vol if self.volume_mode == "avg20d" else 0.0,
            ema10_gt_20=ema, ema20_gt_50=ema, ema50_gt_100=ema, ema100_gt_200=ema,
            sma50_gt_150=sma, sma150_gt_200=sma, sma_cmp_gt_50=sma, sma_cmp_gt_150_200=sma, sma200_rising=sma,
        )


def _sql_list(syms: list[str]) -> str:
    return ",".join("'" + s.replace("'", "''") + "'" for s in syms) or "''"


def _sessions(con: Any, as_of: date, n: int) -> list[date]:
    return list(reversed(db.recent_sessions(con, as_of, n)))  # oldest -> newest


# --------------------------------------------------------------------------- group state (all dates)
def _group_frame(con: Any, as_of: date) -> pd.DataFrame:
    """Industry group state on every session (the one Pulse-owned source, App.services.group_state)."""
    gd = group_state.frame(con, as_of, "industry")
    if gd.empty:
        return gd
    gd = gd.copy()
    gd["rank"] = gd.groupby("d").x63.rank(ascending=False)
    return gd


def _groups(con: Any, as_of: date) -> pd.DataFrame:
    return db.cached("setups.groups", (as_of,), lambda: _group_frame(con, as_of))


# --------------------------------------------------------------------------- base rates
def _base_rates(con: Any, as_of: date, gd: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Hit rate + median 20D return of past NEW setups by screener x group state (point-in-time:
    the forward close must be on or before as_of)."""
    def compute() -> dict[str, dict[str, Any]]:
        hist = con.execute(f"""
            WITH cal AS (SELECT trade_date, row_number() OVER (ORDER BY trade_date) sidx
                         FROM (SELECT DISTINCT trade_date FROM indicators_daily WHERE trade_date <= ?)),
            px AS (SELECT i.symbol, cal.sidx, i.close_price c FROM indicators_daily i JOIN cal USING (trade_date)
                   WHERE i.series = 'EQ')
            SELECT s.queue, s.trade_date d, s.close_price c0, m.industry n, f.c c20
            FROM setup_daily s JOIN cal ON cal.trade_date = s.trade_date
            JOIN stocks_master m USING (symbol)
            JOIN px f ON f.symbol = s.symbol AND f.sidx = cal.sidx + {BASE_HORIZON}
            WHERE s.status = 'new' AND s.trade_date <= ?""", [as_of, as_of]).df()
        if hist.empty or gd.empty:
            return {}
        hist["d"] = pd.to_datetime(hist["d"])
        hist["f"] = hist.c20 / hist.c0 - 1
        hist = hist.merge(gd[["d", "n", "state"]], on=["d", "n"], how="left")
        hist["state"] = hist["state"].fillna(L.NEUTRAL)
        out: dict[str, dict[str, Any]] = {}
        for key, g in [*((f"{q}|{s}", g) for (q, s), g in hist.groupby(["queue", "state"])),
                       *((f"{q}|All", g) for q, g in hist.groupby("queue"))]:
            out[key] = {"n": int(len(g)), "win": L.fnum((g.f > 0).mean() * 100, 0), "median": L.fnum(g.f.median() * 100, 1)}
        return out

    return db.cached("setups.base", (as_of,), compute)


def _momentum_base(as_of: date) -> dict[str, dict[str, Any]]:
    """Momentum has no stored history in setup_daily; use the scanner's own bucket evidence (default
    settings, 20D horizon). Not split by group state."""
    try:
        res = momentum.evidence(as_of)
    except Exception:  # noqa: BLE001 - evidence is optional context
        return {}
    out = {}
    for r in res.rows:
        if r.get("hit_rate_20") is not None:
            out[r["bucket"]] = {"n": r.get("n_20"), "win": L.fnum(r["hit_rate_20"], 0), "median": L.fnum(r.get("median_20"), 1)}
    return out


# --------------------------------------------------------------------------- scan counts
def _counts(con: Any, as_of: date, mom_today: int) -> dict[str, dict[str, Any]]:
    cnt = con.execute("SELECT trade_date d, queue, count(*) n FROM setup_daily WHERE trade_date <= ? GROUP BY 1, 2 ORDER BY 1",
                      [as_of]).df()
    out: dict[str, dict[str, Any]] = {}
    for q in ("darvas_squeeze", "darvas_10ema", "vcp"):
        g = cnt[cnt.queue == q]
        series = [[pd.Timestamp(d).date().isoformat(), int(n)] for d, n in zip(g.d, g.n)]
        today = series[-1][1] if series and series[-1][0] == as_of.isoformat() else 0
        hist = [n for _, n in series]
        prior = hist[:-1] if series and series[-1][0] == as_of.isoformat() else hist
        out[q] = {"today": today, "median_20": L.median(prior[-20:]), "percentile": L.percentile_of(hist, today),
                  "series": series[-120:], "history_sessions": len(hist)}
    out["momentum"] = {"today": mom_today, "median_20": None, "percentile": None, "series": [], "history_sessions": 0,
                       "gap": "Momentum count history is not stored yet (needs a daily momentum count series)."}
    return out


# --------------------------------------------------------------------------- reference data / chips
def _band_frame(con: Any, as_of: date, syms: list[str]) -> pd.DataFrame:
    return con.execute(f"""
        SELECT symbol, price_band, band_remarks FROM security_reference_daily
        WHERE symbol IN ({_sql_list(syms)}) AND effective_date = (
            SELECT max(effective_date) FROM security_reference_daily WHERE effective_date <= ?)""", [as_of]).df() \
        .drop_duplicates("symbol").set_index("symbol")


def _future_sessions(as_of: date, n: int) -> date:
    """Calendar date of the n-th NSE session after as_of (weekdays minus holidays)."""
    hol = common.load_holidays()
    d, k = as_of, 0
    while k < n:
        d += timedelta(days=1)
        if common.is_trading_day(d, hol):
            k += 1
    return d


def _events(con: Any, as_of: date, syms: list[str], n: int) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Chips/highlights from event tables; returns (per symbol list, gaps). Empty tables -> named gaps."""
    gaps: list[str] = []
    out: dict[str, list[dict[str, Any]]] = {}
    horizon = _future_sessions(as_of, n)
    sl = _sql_list(syms)
    if db.table_has_rows(con, "security_events"):
        for s, d, t, h in con.execute(f"""
                SELECT symbol, event_date, event_type, headline FROM security_events
                WHERE symbol IN ({sl}) AND event_date > ? AND event_date <= ?
                  AND (lower(event_type) LIKE '%result%' OR lower(event_type) LIKE '%board%'
                       OR lower(coalesce(headline, '')) LIKE '%financial result%')
                ORDER BY event_date""", [as_of, horizon]).fetchall():
            out.setdefault(s, []).append({"kind": "results", "date": db.to_date(d), "label": f"Results {db.to_date(d)}",
                                          "title": db.text(h) or db.text(t)})
    else:
        gaps.append("Results dates: security_events is empty, so no row highlight is possible.")
    if db.table_has_rows(con, "corporate_actions"):
        for s, d, t in con.execute(f"""
                SELECT symbol, ex_date, action_type FROM corporate_actions
                WHERE symbol IN ({sl}) AND ex_date > ? AND ex_date <= ? ORDER BY ex_date""", [as_of, horizon]).fetchall():
            out.setdefault(s, []).append({"kind": "ex_date", "date": db.to_date(d), "label": f"Ex-date {db.to_date(d)}",
                                          "title": db.text(t)})
    else:
        gaps.append("Ex-dates: corporate_actions is empty.")
    if db.table_has_rows(con, "security_risk_daily"):
        for s, t, v in con.execute(f"""
                SELECT symbol, risk_type, new_value FROM security_risk_daily r
                WHERE symbol IN ({sl}) AND trade_date = (SELECT max(trade_date) FROM security_risk_daily WHERE trade_date <= ?)
                """, [as_of]).fetchall():
            kind = "pledge" if "pledge" in str(t).lower() else "risk"
            out.setdefault(s, []).append({"kind": kind, "date": None, "label": f"{t} {v or ''}".strip(), "title": db.text(t)})
    else:
        gaps.append("ASM / pledge: security_risk_daily is empty (GSM comes from band remarks only).")
    return out, gaps


# --------------------------------------------------------------------------- board
def _momentum_rows(con: Any, as_of: date, prev: date | None, p: BoardParams) -> tuple[dict[str, dict], set[str] | None]:
    mp = p.momentum_params()
    today = db.cached("setups.mom", (as_of, mp), lambda: momentum._scan(con, as_of, mp))
    prev_syms = None
    if prev:
        prev_syms = db.cached("setups.mom_syms", (prev, mp), lambda: {str(r["symbol"]) for r in momentum._scan(con, prev, mp)})
    return {str(r["symbol"]): r for r in today}, prev_syms


def _setup_frame(con: Any, d: date) -> pd.DataFrame:
    sd = con.execute("SELECT * FROM setup_daily WHERE trade_date = ?", [d]).df()
    sd["f"] = sd.features.apply(lambda s: json.loads(s) if isinstance(s, str) and s else {})
    return sd


def _gap_info(con: Any, as_of: date, syms: list[str]) -> dict[str, dict[str, Any]]:
    """Per symbol: active unexplained price gap -> warning text + the horizons it hides."""
    ev = data_gaps.events(con)
    if ev.empty:
        return {}
    ts = pd.Timestamp(as_of)
    ev = ev[ev.symbol.isin(syms) & (ev.gap_date <= ts) & (ev[f"end_{data_gaps.MAX_H}"] >= ts)]
    out: dict[str, dict[str, Any]] = {}
    for s, g in ev.groupby("symbol"):
        hidden = {h for h in data_gaps.HORIZONS if (g[f"end_{h}"] >= ts).any()}
        out[s] = {"warning": "; ".join(g.label), "hidden": hidden}
    return out


def board(as_of: date | None, p: BoardParams = BoardParams()) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        for t in ("setup_daily", "stocks_master", "indicators_daily"):
            if not db.table_exists(con, t):
                return unavailable(resolved, f"{t} missing", SOURCES)
        return db.cached("setups.board", (resolved, p), lambda: _board(con, resolved, p))


def _board(con: Any, as_of: date, p: BoardParams) -> Result:
    sessions = _sessions(con, as_of, HISTORY_BARS)
    prev = sessions[-2] if len(sessions) > 1 else None
    gap_days = (as_of - prev).days if prev else None
    sd = _setup_frame(con, as_of)
    momd, mom_prev = _momentum_rows(con, as_of, prev, p)

    # Execution check: 5% band stocks stay out (setup_daily's pool already does this; momentum needs it).
    syms_all = sorted(set(sd.symbol) | set(momd))
    bands = _band_frame(con, as_of, syms_all) if db.table_exists(con, "security_reference_daily") else pd.DataFrame()
    band_of = {s: L.fnum(v) for s, v in zip(bands.index, bands.get("price_band", []))} if not bands.empty else {}
    excluded_band = sorted(s for s in momd if band_of.get(s) is not None and band_of[s] <= 5)
    for s in excluded_band:
        momd.pop(s, None)
    syms = sorted(set(sd.symbol) | set(momd))
    if not syms:
        return unavailable(as_of, "no setups on this session", SOURCES)

    start = sessions[0]
    ind = con.execute(f"""
        SELECT symbol, trade_date d, open_price o, high_price h, low_price l, close_price c, volume v,
               ema_10 e10, ema_20 e20, ema_50 e50, delivery_pct dp, avg_delivery_pct_20d dp20, turnover_cr tov,
               away_52w_high_pct a52, away_10ema_pct a10, rs_vs_midsml400_21d rs21, rs_vs_midsml400_63d rs63,
               rs_percentile rsp, rs_rank_t5 rsp5, range_10d_pct r10, atr_pct atr, atr_pct_avg_50d atr50,
               volume_dryup_pct vdu, adr_20_pct adr, high_52w h52
        FROM indicators_daily WHERE symbol IN ({_sql_list(syms)}) AND trade_date BETWEEN ? AND ? AND series = 'EQ'
        ORDER BY symbol, d""", [start, as_of]).df()
    ind["d"] = pd.to_datetime(ind["d"])
    master = con.execute("SELECT symbol, security_name, sector, industry, market_cap_cr FROM stocks_master").df() \
        .drop_duplicates("symbol").set_index("symbol")

    gd = _groups(con, as_of)
    ts = pd.Timestamp(as_of)
    gtoday = gd[gd.d == ts].set_index("n") if not gd.empty else pd.DataFrame()
    win = gd[gd.d >= pd.Timestamp(sessions[-45])] if not gd.empty else gd
    gsh = {k: win.pivot_table(index="d", columns="n", values=c) for k, c in ((1, "sh"), (5, "sh5"), (20, "sh20"))} \
        if not win.empty else {}
    gr5 = gd[gd.d == pd.Timestamp(sessions[-6])].set_index("n")["rank"] if (not gd.empty and len(sessions) > 6) else pd.Series(dtype=float)

    def gshare_chg(n: str | None, k: int) -> float | None:
        t = gsh.get(k)
        if t is None or n not in t.columns:
            return None
        s = t[n].dropna()
        if len(s) <= k or not s.iloc[-1 - k]:
            return None
        return L.fnum((s.iloc[-1] / s.iloc[-1 - k] - 1) * 100, 1)

    base = _base_rates(con, as_of, gd)
    mbase = _momentum_base(as_of)
    deals = pd.DataFrame()
    if db.table_exists(con, "deals") and len(sessions) >= 10:
        deals = con.execute(f"""SELECT symbol, side, sum(deal_value_cr) val FROM deals WHERE symbol IN ({_sql_list(syms)})
                                AND trade_date BETWEEN ? AND ? GROUP BY 1, 2""", [sessions[-10], as_of]).df()
    events, event_gaps = _events(con, as_of, syms, p.results_n)
    gaps = _gap_info(con, as_of, syms)

    from Scripts.darvas_squeeze import calculate_darvas_box

    by_sym = {s: g.reset_index(drop=True) for s, g in ind.groupby("symbol")}
    tq = {s: g for s, g in sd.groupby("symbol")}
    rows: list[dict[str, Any]] = []
    for s in syms:
        g = by_sym.get(s)
        if g is None or len(g) < 30 or g.d.iloc[-1] != ts:
            continue
        last = g.iloc[-1]
        m = master.loc[s] if s in master.index else None
        mcap = L.fnum(m.market_cap_cr, 0) if m is not None else None
        tags: list[str] = []
        screeners: list[str] = []
        trig = stop = None
        status, age, sqz, vcp_fp, ten = "active", None, None, None, None
        sts: list[str] = []
        for _, r in (tq[s].iterrows() if s in tq else []):
            q = r.queue
            f = r.f
            tag = L.QUEUE_TAG.get(q, q)
            if q == "darvas_10ema":
                case, tag, tier = L.ten_ema_tag(f.get("flavor"), last.l, last.e10)
                ten = {"case": case, "tier": tier, "flavor": f.get("flavor")}
            if q == "darvas_squeeze":
                sqz = L.fnum(f.get("squeeze_pct"), 1)
            if q == "vcp":
                vcp_fp = f.get("footprint")
            tags.append(tag)
            screeners.append(q)
            trig = trig or L.fnum(r.trigger_price, 2)
            stop = stop or L.fnum(r.stop_price, 2)
            sts.append(str(r.status))
            age = max(age or 0, int(r.setup_age_sessions or 0))
            # Point-in-time market cap the setup pool used (stocks_master holds only the latest value).
            mcap = L.fnum(r.mcap_cr, 0) if L.fnum(r.mcap_cr) is not None else mcap
        mrow = momd.get(s)
        if mrow is not None:
            if mcap is not None and mcap < MIN_MCAP_CR:
                mrow = None
        if mrow is not None:
            bucket = str(mrow.get("bucket") or "")
            tags.append("MOM " + bucket.replace("_", "–"))
            screeners.append("momentum")
            sts.append("new" if (mom_prev is not None and s not in mom_prev) else "active")
        if not tags:
            continue
        status = "new" if "new" in sts else "returning" if "returning" in sts else "active"
        n = m.industry if m is not None else None
        gt = gtoday.loc[n] if (n is not None and not gtoday.empty and n in gtoday.index) else None
        if isinstance(gt, pd.DataFrame):
            gt = gt.iloc[0]
        gstate = gt.state if gt is not None else L.NEUTRAL
        tov = L.turnover_multiples(g.tov.tolist())
        t63 = g.tov.tail(63).mean()
        rk = L.risk_pct(trig, stop)
        room, blue = L.room_to_run(trig, last.h52)
        top, _bot = calculate_darvas_box(g.h.values, g.l.values, boxp=5)
        held, failed = L.box_character(top, g.c.values)
        wk = L.weekly_check(g.set_index("d").c.resample("W-FRI").last().dropna().tolist())
        # chips (data-backed only)
        chips: list[dict[str, Any]] = []
        br = str(bands.loc[s].band_remarks) if (not bands.empty and s in bands.index and bands.loc[s].band_remarks is not None) else ""
        if "GSM" in br or "ASM" in br:
            chips.append({"kind": "risk", "label": br.strip(), "title": "Surveillance remark (NSE band file)"})
        if band_of.get(s) == 10:
            chips.append({"kind": "band", "label": "10% band", "title": "Price band 10%"})
        if not deals.empty:
            dl = deals[deals.symbol == s]
            if len(dl):
                net = sum(v if str(sd_).upper().startswith("B") else -v for sd_, v in zip(dl.side, dl.val) if v == v)
                chips.append({"kind": "deal", "label": f"Deal {net:+.0f} Cr", "title": "Net bulk / block deals, last 10 sessions"})
        a52 = L.fnum(last.a52, 1)
        if a52 is not None and a52 >= -0.5:
            chips.append({"kind": "hi", "label": "52W high", "title": "Within 0.5% of the 52-week high"})
        ev = events.get(s, [])
        results = next((e for e in ev if e["kind"] == "results"), None)
        for e in ev:
            if e["kind"] != "results":
                chips.append({"kind": e["kind"], "label": e["label"], "title": e.get("title")})
        # base rate: first screener on the row (rows are ordered by screener confluence anyway)
        br_row: dict[str, Any] | None = None
        for q in screeners:
            if q == "momentum":
                b = mbase.get(str(mrow.get("bucket"))) if mrow is not None else None
                scope = "Momentum bucket, all groups"
            else:
                b = base.get(f"{q}|{gstate}")
                scope = f"{L.QUEUE_NAME[q]} in {gstate} groups"
            if b:
                br_row = {**b, "scope": scope, "horizon": BASE_HORIZON, "insufficient": (b.get("n") or 0) < MIN_BASE_N}
                break
        gi = gaps.get(s)
        hidden = gi["hidden"] if gi else set()
        rsp = L.fnum(last.rsp, 0)
        rsp_t5 = L.fnum(last.rsp5, 0)
        row = {
            "symbol": s, "name": m.security_name if m is not None else None,
            "sector": m.sector if m is not None else None, "industry": n, "market_cap_cr": mcap,
            "tags": tags, "screeners": screeners, "status": status, "age": age,
            "close": L.fnum(last.c, 2), "change_1d_pct": None if 1 in hidden else L.fnum((last.c / g.c.iloc[-2] - 1) * 100, 2),
            "trigger": trig, "stop": stop, "risk_pct": rk, "adr_pct": L.fnum(last.adr, 1),
            "risk_adr": L.fnum(rk / last.adr, 2) if rk and L.fnum(last.adr) else None,
            "away_52w_high_pct": None if 252 in hidden else a52, "away_10ema_pct": L.fnum(last.a10, 1),
            "away_50ema_pct": L.fnum((last.c / last.e50 - 1) * 100, 1) if L.fnum(last.e50) else None,
            "rs_21d": None if 21 in hidden else L.fnum(last.rs21, 1), "rs_63d": None if 63 in hidden else L.fnum(last.rs63, 1),
            "rs_percentile": None if 252 in hidden else rsp,
            "rs_delta_5d": None if (252 in hidden or rsp is None or rsp_t5 is None) else L.fnum(rsp - rsp_t5, 0),
            "range_10d_pct": L.fnum(last.r10, 1),
            "atr_x": L.fnum(last.atr / last.atr50, 2) if L.fnum(last.atr50) and L.fnum(last.atr) else None,
            "volume_dryup_pct": L.fnum(last.vdu, 0), "squeeze_pct": sqz, "vcp_footprint": vcp_fp, "ten_ema": ten,
            "delivery_pct": L.fnum(last.dp, 0), "delivery_avg_20d": L.fnum(last.dp20, 0),
            "delivery_streak": L.delivery_streak(g.dp.tolist(), g.dp20.tolist()),
            "delivery_5d": [L.fnum(x, 0) for x in g.dp.tail(5)],
            "turnover_cr": L.fnum(last.tov, 1), "turnover_1d_x": tov["1d"],
            "turnover_1w_x": tov["1w"], "turnover_1m_x": None if 21 in hidden else tov["1m"],
            "turnover_3m_avg_cr": L.fnum(t63, 1),
            "group_state": gstate, "group_reason": gt.why if gt is not None else "Group not mapped.",
            "group_share_chg_1d": gshare_chg(n, 1), "group_share_chg_1w": gshare_chg(n, 5),
            "group_share_chg_1m": gshare_chg(n, 20),
            "group_rank": L.fnum(gt["rank"], 0) if gt is not None else None, "group_rank_n": int(len(gtoday)),
            "group_rank_chg_5d": (L.fnum(gr5.get(n) - gt["rank"], 0) if gt is not None and n in gr5.index else None),
            "room_to_run_pct": room, "blue_sky": blue,
            "breakouts_held_6m": held, "breakouts_failed_6m": failed,
            "weekly_above_10w": wk["above_10w"], "weekly_tight": wk["tight"], "weekly_spread_3w_pct": wk["spread_3w_pct"],
            "chips": chips, "results_date": results["date"] if results else None,
            "results_soon": bool(results), "base_rate": br_row,
            "data_warning": gi["warning"] if gi else None, "peer_note": None,
        }
        rows.append(row)

    # Peer note: a board peer in the same industry with RS >= 10 points higher.
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["industry"] and r["rs_percentile"] is not None:
            b = best.get(r["industry"])
            if b is None or r["rs_percentile"] > b["rs_percentile"]:
                best[r["industry"]] = r
    for r in rows:
        b = best.get(r["industry"] or "")
        if b and b["symbol"] != r["symbol"] and r["rs_percentile"] is not None and b["rs_percentile"] - r["rs_percentile"] >= 10:
            r["peer_note"] = f"{b['symbol']} in the same industry has RS {b['rs_percentile']:.0f} vs {r['rs_percentile']:.0f}."

    rows.sort(key=L.sort_key)
    counts = _counts(con, as_of, sum(1 for r in rows if "momentum" in r["screeners"]))
    split = {k: sum(1 for r in rows if r["group_state"] == k) for k in (L.FAVOUR, L.NEUTRAL, L.CAUTION)}
    confluence = sum(1 for r in rows if len(r["screeners"]) >= 2)
    data_gap_notes = list(event_gaps)
    if gap_days and gap_days > 7:
        data_gap_notes.insert(0, f"Session gap: the previous session ({prev}) is {gap_days} days before {as_of}. "
                                 "1D moves, New tags and Why dropped compare across the gap.")
    if all(r["rs_63d"] is None for r in rows):
        data_gap_notes.append("RS vs MidSml400 63D is empty in this database.")
    return Result(
        as_of=as_of, rows=rows, sources=SOURCES,
        status=common.STATUS_PARTIAL if data_gap_notes else common.STATUS_OK,
        reason=data_gap_notes[0] if data_gap_notes else None,
        notes=["Screener calculations are unchanged: setup_daily (strict Squeeze, 10 EMA, VCP) and the momentum scanner.",
               "Lists show stocks with market cap ≥ ₹1,000 Cr. 5% price-band stocks are excluded.",
               f"Base rate = past new setups of the same screener in the same group state, {BASE_HORIZON}-session return."],
        extra={
            "previous_session": prev, "session_gap_days": gap_days,
            "params": {"template": p.template, "volume_mode": p.volume_mode, "min_volume": p.min_volume,
                       "results_n": p.results_n},
            "counts": counts, "group_split": split, "confluence": confluence,
            "groups": {"favour": int((gtoday.state == L.FAVOUR).sum()) if not gtoday.empty else 0,
                       "caution": int((gtoday.state == L.CAUTION).sum()) if not gtoday.empty else 0,
                       "total": int(len(gtoday))},
            "base_rates": base, "momentum_base": mbase,
            "readout": L.readout(counts=counts, split=split, total=len(rows), confluence=confluence, base=base,
                                 session_gap_days=gap_days, results_known=db.table_has_rows(con, "security_events")),
            "excluded_5pct_band": excluded_band,
            "data_gaps": data_gap_notes,
        },
    )


# --------------------------------------------------------------------------- near-miss
def near_miss(as_of: date | None, limit: int = 60) -> Result:
    from Scripts.darvas_squeeze import calculate_darvas_box
    from Scripts.desk_contract import DARVAS

    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)

        def compute() -> list[dict[str, Any]]:
            sessions = _sessions(con, resolved, 80)
            pool = con.execute("""
                SELECT i.symbol FROM indicators_daily i JOIN stocks_master m USING (symbol)
                LEFT JOIN (SELECT symbol, price_band, band_remarks FROM security_reference_daily WHERE effective_date =
                           (SELECT max(effective_date) FROM security_reference_daily WHERE effective_date <= ?)) r USING (symbol)
                WHERE i.trade_date = ? AND i.series = 'EQ' AND m.market_cap_cr >= ?
                  AND (i.ema_200 IS NULL OR i.close_price > i.ema_200)
                  AND coalesce(i.avg_traded_value_cr_20d, i.turnover_cr) >= 3
                  AND coalesce(r.price_band, 20) > 5
                  AND coalesce(r.band_remarks, m.band_remarks, '') NOT LIKE '%GSM%'""",
                               [resolved, resolved, MIN_MCAP_CR]).df().symbol.tolist()
            if not pool:
                return []
            pi = con.execute(f"""
                SELECT symbol, trade_date d, high_price h, low_price l, close_price c, ema_10 e10, ema_20 e20, rvol
                FROM indicators_daily WHERE symbol IN ({_sql_list(pool)}) AND series = 'EQ' AND trade_date BETWEEN ? AND ?
                ORDER BY 1, 2""", [sessions[0], resolved]).df()
            sq_today = set(con.execute("SELECT symbol FROM setup_daily WHERE trade_date = ? AND queue = 'darvas_squeeze'",
                                       [resolved]).df().symbol)
            master = con.execute("SELECT symbol, industry FROM stocks_master").df().drop_duplicates("symbol").set_index("symbol")
            out = []
            ts = pd.Timestamp(resolved)
            for s, g in pi.groupby("symbol"):
                if s in sq_today or len(g) < 30 or pd.Timestamp(g.d.iloc[-1]) != ts:
                    continue
                top, _ = calculate_darvas_box(g.h.values, g.l.values, boxp=5)
                last = g.iloc[-1]
                t = top[-1]
                if not (np.isfinite(t) and t > last.e10 and last.e10 * DARVAS["close_floor_tol"] <= last.c <= t * DARVAS["ceiling_tol"]):
                    continue
                fails = L.squeeze_gate_failures(
                    close=float(last.c), high=float(last.h), low=float(last.l), ema10=float(last.e10),
                    ema10_prev=L.fnum(g.e10.iloc[-2]), ema20=L.fnum(last.e20), top=float(t), rvol=L.fnum(last.rvol),
                    darvas=DARVAS)
                if len(fails) == 1:
                    out.append({"symbol": s, "industry": master.industry.get(s) if s in master.index else None,
                                "gate": fails[0], "squeeze_pct": L.fnum((t - last.e10) / t * 100, 1),
                                "close": L.fnum(last.c, 2), "box_top": L.fnum(t, 2), "ema_10": L.fnum(last.e10, 2),
                                "rvol": L.fnum(last.rvol, 2)})
            out.sort(key=lambda r: (r["squeeze_pct"] if r["squeeze_pct"] is not None else 99))
            return out

        rows = db.cached("setups.near", (resolved,), compute)
    return Result(as_of=resolved, rows=rows[:limit], sources=["indicators_daily", "setup_daily", "stocks_master"],
                  extra={"total_candidates": len(rows)},
                  notes=["Squeeze candidates with close in the zone (10 EMA to box top) that fail exactly one strict gate."])


# --------------------------------------------------------------------------- why dropped
def dropped(as_of: date | None, p: BoardParams = BoardParams()) -> Result:
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)

        def compute() -> tuple[list[dict[str, Any]], date | None]:
            sessions = _sessions(con, resolved, 2)
            if len(sessions) < 2:
                return [], None
            prev = sessions[0]
            sd = con.execute("SELECT queue, symbol, trade_date, trigger_price, stop_price FROM setup_daily WHERE trade_date IN (?, ?)",
                             [prev, resolved]).df()
            sd["trade_date"] = pd.to_datetime(sd.trade_date).dt.date
            today = sd[sd.trade_date == resolved]
            pv = sd[sd.trade_date == prev]
            last = con.execute("""SELECT symbol, close_price c, low_price l, ema_10 e10, ema_200 e200 FROM indicators_daily
                                  WHERE trade_date = ? AND series = 'EQ'""", [resolved]).df().drop_duplicates("symbol").set_index("symbol")
            master = con.execute("SELECT symbol, industry, market_cap_cr FROM stocks_master").df().drop_duplicates("symbol").set_index("symbol")
            out = []
            for q in ("darvas_squeeze", "darvas_10ema", "vcp"):
                tset = set(today[today.queue == q].symbol)
                pf = pv[pv.queue == q].drop_duplicates("symbol").set_index("symbol")
                for s in sorted(set(pf.index) - tset):
                    has = s in last.index
                    lr = last.loc[s] if has else None
                    mc = L.fnum(master.market_cap_cr.get(s)) if s in master.index else None
                    in_pool = bool(has and (mc or 0) >= MIN_MCAP_CR and (L.fnum(lr.e200) is None or lr.c > lr.e200))
                    code, why = L.drop_reason(has_bar=has, in_pool=in_pool, close=L.fnum(lr.c) if has else None,
                                              low=L.fnum(lr.l) if has else None, ema10=L.fnum(lr.e10) if has else None,
                                              trigger=L.fnum(pf.loc[s].trigger_price), stop=L.fnum(pf.loc[s].stop_price))
                    out.append({"screener": q, "screener_name": L.QUEUE_NAME[q], "symbol": s, "code": code, "why": why,
                                "industry": master.industry.get(s) if s in master.index else None,
                                "close": L.fnum(lr.c, 2) if has else None})
            momd, mom_prev = _momentum_rows(con, resolved, prev, p)
            for s in sorted((mom_prev or set()) - set(momd)):
                out.append({"screener": "momentum", "screener_name": "Momentum", "symbol": s, "code": "rule_failed",
                            "why": "Failed a current-day momentum rule.",
                            "industry": master.industry.get(s) if s in master.index else None,
                            "close": L.fnum(last.c.get(s), 2) if s in last.index else None})
            return out, prev

        rows, prev = db.cached("setups.dropped", (resolved, p), compute)
    return Result(as_of=resolved, rows=rows, sources=["setup_daily", "indicators_daily"],
                  extra={"previous_session": prev,
                         "session_gap_days": (resolved - prev).days if prev else None},
                  notes=["Stocks that left a screener since the previous session, with the rule that broke."])


# --------------------------------------------------------------------------- detail (facts + peers + markers)
def detail(symbol: str, as_of: date | None, p: BoardParams = BoardParams()) -> Result:
    res = board(as_of, p)
    if res.as_of is None:
        return res
    row = next((r for r in res.rows if r["symbol"] == symbol), None)
    with db.market_conn() as con:
        ind_row = con.execute("SELECT industry FROM stocks_master WHERE symbol = ? LIMIT 1", [symbol]).fetchone()
        if row is None and ind_row is None:
            raise KeyError(symbol)
        industry = row["industry"] if row else (ind_row[0] if ind_row else None)
        on_board = {r["symbol"]: r["tags"] for r in res.rows}
        peers = []
        if industry:
            for s, rsp, a52, a10 in con.execute("""
                    SELECT i.symbol, i.rs_percentile, i.away_52w_high_pct, i.away_10ema_pct
                    FROM indicators_daily i JOIN stocks_master m USING (symbol)
                    WHERE i.trade_date = ? AND i.series = 'EQ' AND m.industry = ? AND m.market_cap_cr >= ?
                    ORDER BY i.rs_percentile DESC NULLS LAST LIMIT 8""", [res.as_of, industry, MIN_MCAP_CR]).fetchall():
                peers.append({"symbol": s, "rs_percentile": L.fnum(rsp, 0), "away_52w_high_pct": L.fnum(a52, 1),
                              "away_10ema_pct": L.fnum(a10, 1), "tags": on_board.get(s, [])})
        start = res.as_of - timedelta(days=400)
        markers = []
        if db.table_exists(con, "deals"):
            for d, side, val in con.execute("""SELECT trade_date, side, sum(deal_value_cr) FROM deals WHERE symbol = ?
                                               AND trade_date BETWEEN ? AND ? GROUP BY 1, 2 ORDER BY 1""",
                                            [symbol, start, res.as_of]).fetchall():
                buy = str(side).upper().startswith("B")
                markers.append({"time": db.to_date(d), "kind": "deal_buy" if buy else "deal_sell",
                                "text": "D", "value_cr": L.fnum(val, 1)})
        divs = []
        typed = "rsi_divergence_type" in set(db.table_columns(con, "indicators_daily"))
        type_sql = "rsi_divergence_type" if typed else "NULL"
        cond = "(bullish_rsi_divergence OR bearish_rsi_divergence" + (" OR rsi_divergence_type IS NOT NULL)" if typed else ")")
        for d, b, s, t in con.execute(f"""SELECT trade_date, bullish_rsi_divergence, bearish_rsi_divergence, {type_sql}
                                      FROM indicators_daily
                                      WHERE symbol = ? AND trade_date BETWEEN ? AND ? AND series = 'EQ'
                                        AND {cond} ORDER BY 1""",
                                   [symbol, start, res.as_of]).fetchall():
            kind = "regular_bullish" if b else "regular_bearish" if s else "hidden_bullish" if "Hidden bull" in (t or "") else "hidden_bearish"
            divs.append({"time": db.to_date(d), "kind": kind, "type": db.text(t)})
    gaps = [] if typed else ["Hidden RSI divergences are not stored in this database yet (regular only; rebuild needed)."]
    return Result(as_of=res.as_of, rows=[row] if row else [], sources=SOURCES,
                  extra={"symbol": symbol, "industry": industry, "on_board": row is not None, "peers": peers,
                         "deal_markers": markers, "rsi_divergences": divs, "data_gaps": gaps})
