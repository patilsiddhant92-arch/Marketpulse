"""Groups: board, RRG, drill-down and members (spec §7.4).

`group_daily` (data layer §4.5) is the source of truth. Until it exists the
board and drill-down fall back to the legacy `sector_rotation` +
`sector_metrics_daily` tables (status "partial": no RS-Ratio/Momentum, no
floor dimension, legacy rotation labels). RRG needs `group_daily` and is
"unavailable" without it. Members are always computed from indicators_daily
at `as_of` with the requested market-cap floor.

Group id format: ``<level>:<name>`` e.g. ``industry:2/3 Wheelers``.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

import pandas as pd

from App.services import db, universe
from App.services.common import STATUS_PARTIAL, Result, no_session, unavailable

GROUP_METRICS = [
    "rs_ratio", "rs_momentum", "rrg_quadrant", "group_rank", "group_rank_delta_5", "group_rank_delta_20",
    "group_excess_21d", "group_excess_63d", "group_breadth_50", "group_breadth_200", "group_trend_template_pct",
    "turnover_share_5d", "turnover_share_delta_20d", "delivery_accumulation_days", "deal_net_10s_cr",
    "concentration_top3",
]
MEMBER_METRICS = ["rs_percentile", "rs_delta_5", "rs_vs_sector_index_63d", "trend_template_pass_n",
                  "delivery_accumulation_days", "change_1d_pct", "rvol", "delivery_pct", "market_cap_cr"]

# group_daily column -> response field (first present wins)
_GD_FIELDS: dict[str, tuple[str, ...]] = {
    "group_name": ("group_name", "name", "group"),
    "stocks": ("stock_count", "stocks", "n_members", "members"),
    "rrg_quadrant": ("rrg_quadrant", "quadrant"),
    "days_in_quadrant": ("days_in_quadrant",),
    "rs_ratio": ("rs_ratio", "jdk_rs_ratio"),
    "rs_momentum": ("rs_momentum", "jdk_rs_momentum"),
    "rank": ("rank", "group_rank", "rank_vs_benchmark"),
    "rank_delta_5": ("rank_delta_5", "rank_change_5d"),
    "rank_delta_20": ("rank_delta_20", "rank_change_20d"),
    "rank_delta_63": ("rank_delta_63", "rank_change_63d"),
    "return_ew_21d": ("return_ew_21d", "ew_return_21d"),
    "return_cw_21d": ("return_cw_21d", "cw_return_21d"),
    "excess_vs_midsml400_21d": ("excess_vs_midsml400_21d",),
    "excess_vs_midsml400_63d": ("excess_vs_midsml400_63d",),
    "excess_vs_nifty50_21d": ("excess_vs_nifty50_21d", "excess_vs_nifty_21d"),
    "excess_vs_nifty50_63d": ("excess_vs_nifty50_63d", "excess_vs_nifty_63d"),
    "breadth_50": ("breadth_50", "pct_above_50ema"),
    "breadth_200": ("breadth_200", "pct_above_200ema"),
    "trend_template_pct": ("trend_template_pct",),
    "new_highs": ("new_highs", "official_new_highs"),
    "turnover_share_5d": ("turnover_share_5d",),
    "turnover_share_20d": ("turnover_share_20d",),
    "turnover_share_delta": ("turnover_share_delta", "turnover_share_delta_20d"),
    "delivery_accumulation": ("delivery_accumulation", "delivery_weighted_accumulation"),
    "deal_net_10s_cr": ("deal_net_10s_cr", "deal_net_10_cr"),
    "concentration_top3": ("concentration_top3", "adv_concentration_top3"),
}


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


# --------------------------------------------------------------------------
# group_daily readers
# --------------------------------------------------------------------------
def _gd_map(con: Any) -> dict[str, str]:
    cols = set(db.table_columns(con, "group_daily"))
    return {k: next((c for c in names if c in cols), "") for k, names in _GD_FIELDS.items()}


def _gd_where(con: Any, level_key: str, floor: str) -> tuple[str, list[Any]]:
    cols = set(db.table_columns(con, "group_daily"))
    label = universe.LEVELS[level_key][1]
    where = "lower(replace(CAST(level AS VARCHAR), '_', ' ')) = lower(?)"
    params: list[Any] = [label]
    if "floor" in cols:
        where += " AND lower(CAST(floor AS VARCHAR)) = ?"
        params.append(str(floor).lower())
    return where, params


def _shape_gd(raw: dict[str, Any], fmap: dict[str, str], level_key: str) -> dict[str, Any]:
    row: dict[str, Any] = {"level": level_key}
    for field, col in fmap.items():
        val = raw.get(col) if col else None
        row[field] = db.text(val) if field in ("group_name", "rrg_quadrant") else db.num(val, 4)
    for f in ("stocks", "days_in_quadrant", "rank", "rank_delta_5", "rank_delta_20", "rank_delta_63", "new_highs"):
        row[f] = db.integer(row[f])
    row["id"] = group_id(level_key, row["group_name"] or "")
    row["trade_date"] = db.to_date(raw.get("trade_date"))
    return row


def _board_group_daily(con: Any, as_of: date, level_key: str, floor: str) -> tuple[list[dict[str, Any]], date | None]:
    where, params = _gd_where(con, level_key, floor)
    fmap = _gd_map(con)
    d = con.execute(f"SELECT max(trade_date) FROM group_daily WHERE trade_date <= ? AND {where}", [as_of, *params]).fetchone()[0]
    if d is None:
        return [], None
    raws = db.records(con, f"SELECT * FROM group_daily WHERE trade_date = ? AND {where}", [d, *params])
    rows = [_shape_gd(r, fmap, level_key) for r in raws]
    if fmap["rank"]:
        spark = db.records(
            con,
            f"""
            SELECT {db.quote_ident(fmap['group_name'])} AS g, list({db.quote_ident(fmap['rank'])} ORDER BY trade_date) AS s
            FROM (SELECT * FROM group_daily WHERE trade_date <= ? AND {where}
                  AND trade_date IN (SELECT DISTINCT trade_date FROM group_daily WHERE trade_date <= ?
                                     ORDER BY trade_date DESC LIMIT 60))
            GROUP BY 1
            """,
            [d, *params, d],
        )
        sp = {r["g"]: [db.integer(v) for v in (r["s"] or [])] for r in spark}
        for row in rows:
            row["rank_spark_60"] = sp.get(row["group_name"])
    return rows, db.to_date(d)


# --------------------------------------------------------------------------
# Legacy fallback (sector_rotation + sector_metrics_daily)
# --------------------------------------------------------------------------
def _board_legacy(con: Any, as_of: date, level_key: str) -> tuple[list[dict[str, Any]], date | None]:
    label = universe.LEVELS[level_key][1]
    d = con.execute("SELECT max(trade_date) FROM sector_rotation WHERE trade_date <= ? AND level = ?", [as_of, label]).fetchone()[0]
    if d is None:
        return [], None
    has_sm = db.table_exists(con, "sector_metrics_daily")
    sm_join = ("LEFT JOIN sector_metrics_daily sm ON sm.trade_date = r.trade_date AND sm.level = r.level "
               "AND sm.group_name = r.group_name") if has_sm else ""
    sm_cols = ("sm.rs_vs_nifty_21d, sm.rs_vs_nifty_63d, sm.deal_net_10s_cr, sm.adv_concentration_top3, sm.stock_count"
               if has_sm else "NULL AS rs_vs_nifty_21d, NULL AS rs_vs_nifty_63d, NULL AS deal_net_10s_cr, "
                              "NULL AS adv_concentration_top3, NULL AS stock_count")
    raws = db.records(
        con,
        f"""
        SELECT r.*, {sm_cols}
        FROM sector_rotation r {sm_join}
        WHERE r.trade_date = ? AND r.level = ? AND upper(r.group_name) <> 'TOTAL'
        """,
        [d, label],
    )
    spark = db.records(
        con,
        """
        SELECT group_name AS g, list(rotation_rank ORDER BY trade_date) AS s
        FROM sector_rotation
        WHERE level = ? AND trade_date <= ?
          AND trade_date IN (SELECT DISTINCT trade_date FROM sector_rotation WHERE trade_date <= ? AND level = ?
                             ORDER BY trade_date DESC LIMIT 60)
        GROUP BY 1
        """,
        [label, d, d, label],
    )
    sp = {r["g"]: [db.integer(v) for v in (r["s"] or [])] for r in spark}
    rows = []
    for r in raws:
        name = db.text(r.get("group_name"))
        rows.append({
            "id": group_id(level_key, name or ""),
            "level": level_key,
            "group_name": name,
            "trade_date": db.to_date(r.get("trade_date")),
            "stocks": db.integer(r.get("stock_count") if r.get("stock_count") is not None else r.get("stocks")),
            "rrg_quadrant": None,
            "days_in_quadrant": None,
            "rs_ratio": None,
            "rs_momentum": None,
            "rank": db.integer(r.get("rotation_rank")),
            "rank_delta_5": db.integer(r.get("rank_change_5d")),
            "rank_delta_20": db.integer(r.get("rank_change_20d")),
            "rank_delta_63": None,
            "return_ew_21d": db.num(r.get("return_1m_pct"), 4),
            "return_cw_21d": None,
            "excess_vs_midsml400_21d": None,
            "excess_vs_midsml400_63d": None,
            "excess_vs_nifty50_21d": db.num(r.get("rs_vs_nifty_21d"), 4),
            "excess_vs_nifty50_63d": db.num(r.get("rs_vs_nifty_63d"), 4),
            "breadth_50": db.num(r.get("above_50ema_pct"), 4),
            "breadth_200": db.num(r.get("above_200ema_pct"), 4),
            "trend_template_pct": None,
            "new_highs": None,
            "turnover_share_5d": None,
            "turnover_share_20d": None,
            "turnover_share_delta": db.num(r.get("turnover_share_delta_5d"), 4),
            "delivery_accumulation": None,
            "deal_net_10s_cr": db.num(r.get("deal_net_10s_cr"), 2),
            "concentration_top3": db.num(r.get("adv_concentration_top3"), 4),
            "legacy_rotation_state": db.text(r.get("rotation_state")),
            "legacy_median_rs_percentile": db.num(r.get("rs_percentile"), 1),
            "turnover_share_pct": db.num(r.get("turnover_share_pct"), 4),
            "leader_symbols": [s.strip() for s in str(r.get("leader_symbols") or "").split(",") if s.strip()] or None,
            "rank_spark_60": sp.get(name),
        })
    return rows, db.to_date(d)


def board(as_of: date | None, level: str, floor: str = "1000") -> Result:
    level_key = universe.level_key(level)
    if level_key is None:
        raise ValueError(f"unknown level {level!r}")
    floor_value(floor)
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        if db.table_exists(con, "group_daily"):
            rows, d = _board_group_daily(con, resolved, level_key, floor)
            src, status, reason = ["group_daily"], "ok", None
        elif db.table_exists(con, "sector_rotation"):
            rows, d = _board_legacy(con, resolved, level_key)
            src, status = ["sector_rotation", "sector_metrics_daily"], STATUS_PARTIAL
            reason = ("group_daily not built yet; legacy sector_rotation fields shown — RS-Ratio/Momentum, quadrant "
                      "and floor are unavailable")
        else:
            return unavailable(resolved, "no group tables (group_daily / sector_rotation)", ["group_daily"])
    rows.sort(key=lambda r: (r.get("rank") is None, r.get("rank") or 0))
    return Result(as_of=d or resolved, rows=rows, status=status, reason=reason, sources=src,
                  extra={"level": level_key, "floor": floor, "floor_applied": "group_daily" in src},
                  metric_keys=GROUP_METRICS)


def rrg(as_of: date | None, level: str, floor: str = "1000", tail_weeks: int = 6) -> Result:
    level_key = universe.level_key(level)
    if level_key is None:
        raise ValueError(f"unknown level {level!r}")
    floor_value(floor)
    tail_weeks = max(1, min(int(tail_weeks), 12))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if not db.table_exists(con, "group_daily"):
            return unavailable(resolved, "group_daily not built yet (RS-Ratio / RS-Momentum come from it)", ["group_daily"])
        if resolved is None:
            return no_session(as_of)
        fmap = _gd_map(con)
        if not (fmap["rs_ratio"] and fmap["rs_momentum"] and fmap["group_name"]):
            return unavailable(resolved, "group_daily lacks rs_ratio / rs_momentum columns", ["group_daily"])
        where, params = _gd_where(con, level_key, floor)
        dates = [db.to_date(r[0]) for r in con.execute(
            f"SELECT DISTINCT trade_date FROM group_daily WHERE trade_date <= ? AND {where} ORDER BY trade_date DESC LIMIT ?",
            [resolved, *params, tail_weeks * 5 + 1],
        ).fetchall()]
        if not dates:
            return unavailable(resolved, "group_daily has no rows on or before as_of", ["group_daily"])
        weekly = dates[::5]
        ph = ",".join(["?"] * len(weekly))
        raws = db.records(
            con,
            f"SELECT * FROM group_daily WHERE trade_date IN ({ph}) AND {where} ORDER BY trade_date",
            [*weekly, *params],
        )
    by_group: dict[str, list[dict[str, Any]]] = {}
    for r in raws:
        row = _shape_gd(r, fmap, level_key)
        by_group.setdefault(row["group_name"] or "", []).append(row)
    rows = []
    for name, pts in by_group.items():
        last = pts[-1]
        rows.append({
            "id": group_id(level_key, name),
            "group_name": name,
            "level": level_key,
            "rs_ratio": last["rs_ratio"],
            "rs_momentum": last["rs_momentum"],
            "rrg_quadrant": last["rrg_quadrant"],
            "days_in_quadrant": last["days_in_quadrant"],
            "tail": [{"trade_date": p["trade_date"], "rs_ratio": p["rs_ratio"], "rs_momentum": p["rs_momentum"]} for p in pts],
        })
    rows.sort(key=lambda r: r["group_name"])
    return Result(as_of=weekly[0], rows=rows, sources=["group_daily"],
                  extra={"level": level_key, "floor": floor, "tail_weeks": tail_weeks}, metric_keys=GROUP_METRICS[:3])


def _breadcrumb(con: Any, level_key: str, name: str) -> list[dict[str, Any]]:
    order = ["broad_sector", "sector", "broad_industry", "industry"]
    col = universe.LEVELS[level_key][0]
    parents = order[: order.index(level_key)]
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


def detail(as_of: date | None, gid: str, floor: str = "1000", days: int = 60) -> Result:
    level_key, name = parse_group_id(gid)
    floor_value(floor)
    days = max(5, min(int(days), 600))
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        crumb = _breadcrumb(con, level_key, name)
        if db.table_exists(con, "group_daily"):
            fmap = _gd_map(con)
            where, params = _gd_where(con, level_key, floor)
            raws = db.records(
                con,
                f"SELECT * FROM group_daily WHERE trade_date <= ? AND {where} AND {db.quote_ident(fmap['group_name'])} = ? "
                f"ORDER BY trade_date DESC LIMIT ?",
                [resolved, *params, name, days],
            )
            rows = [_shape_gd(r, fmap, level_key) for r in raws]
            src, status, reason = ["group_daily"], "ok", None
        elif db.table_exists(con, "sector_rotation"):
            label = universe.LEVELS[level_key][1]
            raws = db.records(
                con,
                """
                SELECT trade_date, rotation_rank, rank_change_5d, rank_change_20d, return_5d_pct, return_1m_pct,
                       return_3m_pct, above_50ema_pct, above_200ema_pct, turnover_share_pct, turnover_share_delta_5d,
                       rotation_state, stocks
                FROM sector_rotation WHERE level = ? AND group_name = ? AND trade_date <= ?
                ORDER BY trade_date DESC LIMIT ?
                """,
                [label, name, resolved, days],
            )
            rows = [{
                "id": gid, "level": level_key, "group_name": name,
                "trade_date": db.to_date(r["trade_date"]),
                "stocks": db.integer(r["stocks"]),
                "rank": db.integer(r["rotation_rank"]),
                "rank_delta_5": db.integer(r["rank_change_5d"]),
                "rank_delta_20": db.integer(r["rank_change_20d"]),
                "return_ew_21d": db.num(r["return_1m_pct"], 4),
                "breadth_50": db.num(r["above_50ema_pct"], 4),
                "breadth_200": db.num(r["above_200ema_pct"], 4),
                "turnover_share_pct": db.num(r["turnover_share_pct"], 4),
                "turnover_share_delta": db.num(r["turnover_share_delta_5d"], 4),
                "legacy_rotation_state": db.text(r["rotation_state"]),
                "rrg_quadrant": None, "rs_ratio": None, "rs_momentum": None,
            } for r in raws]
            src, status = ["sector_rotation"], STATUS_PARTIAL
            reason = "group_daily not built yet; legacy sector_rotation history shown"
        else:
            return unavailable(resolved, "no group tables", ["group_daily"], breadcrumb=crumb)
    if not rows:
        return unavailable(resolved, f"no history for group {gid!r}", src, breadcrumb=crumb)
    return Result(as_of=rows[0].get("trade_date") or resolved, rows=rows, status=status, reason=reason, sources=src,
                  extra={"group": {"id": gid, "level": level_key, "name": name}, "breadcrumb": crumb, "floor": floor,
                         "members_endpoint": f"/api/v2/groups/{gid}/members"},
                  notes=["Group evidence ('when this group turned Leading…') arrives with the evidence engine."],
                  metric_keys=GROUP_METRICS)


def members(as_of: date | None, gid: str, floor: str = "1000", sort: str = "rs_percentile", descending: bool = True) -> Result:
    level_key, name = parse_group_id(gid)
    min_mcap = floor_value(floor)
    col = universe.LEVELS[level_key][0]
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        snap = universe.snapshot_sql(con, extra_where=f"AND m.{col} = ?")
        where = "WHERE s.market_cap_cr >= ?" if min_mcap > 0 else ""
        params: list[Any] = [resolved, name] + ([min_mcap] if min_mcap > 0 else [])
        if str(floor).lower() == "watch":
            where = "WHERE s.market_cap_cr >= ? AND s.market_cap_cr < 1000"
        recs = db.records(con, f"WITH s AS ({snap}) SELECT * FROM s {where}", params)
        syms = [r["symbol"] for r in recs]
        acc: dict[str, int] = {}
        if syms:
            window = db.recent_sessions(con, resolved, 10)
            con.register("grp_syms", pd.DataFrame({"symbol": syms}))
            try:
                acc = {r[0]: int(r[1]) for r in con.execute(
                    """
                    SELECT i.symbol, count(*) FILTER (WHERE i.price_up_delivery_up IS TRUE)
                    FROM indicators_daily i JOIN grp_syms USING (symbol)
                    WHERE i.trade_date BETWEEN ? AND ? GROUP BY 1
                    """,
                    [window[-1], resolved],
                ).fetchall()}
            finally:
                con.unregister("grp_syms")
        has_setups = db.table_exists(con, "setup_daily")
    rows = []
    for r in recs:
        base = universe.shape_stock(r)
        rows.append({
            **base,
            "rs_vs_sector_index_63d": db.num(r.get("rs_vs_sector_index_63d"), 2),
            "sector_index_name": db.text(r.get("sector_index_name")),
            "rs_rank_t5": db.num(r.get("rs_rank_t5"), 1),
            "rs_rank_t15": db.num(r.get("rs_rank_t15"), 1),
            "rs_rank_t30": db.num(r.get("rs_rank_t30"), 1),
            "trend_template_pass_n": db.integer(r.get("trend_template_pass_n")),
            "delivery_accumulation_days": acc.get(base["symbol"] or ""),
            "active_setups": None,
        })
    present = [r for r in rows if r.get(sort) is not None]
    missing = [r for r in rows if r.get(sort) is None]
    present.sort(key=lambda r: r[sort], reverse=descending)
    return Result(
        as_of=resolved, rows=present + missing, sources=["indicators_daily", "stocks_master"],
        extra={"group": {"id": gid, "level": level_key, "name": name}, "floor": floor},
        notes=[] if has_setups else ["active_setups needs setup_daily; use desk/queue/{name} meanwhile."],
        metric_keys=MEMBER_METRICS,
    )
