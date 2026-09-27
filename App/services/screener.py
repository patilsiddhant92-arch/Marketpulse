"""Screener presets, rule engine and rule debugger (spec §7.3).

Rules are data: ``{"field": "rs_percentile", "op": "gte", "value": 70}`` or
``{"field": "close", "op": "gt", "ref": "ema_200"}``. Fields and operators are
whitelisted and values are bound parameters — no request text ever reaches SQL.
Fail-closed: a NULL input fails its rule (SQL three-valued logic), unlike the
old endpoint's ``ema IS NULL OR ...`` pass-through.

Presets are server-side, returned with their rules as editable chips, and
replace (never stack). Darvas / VCP presets delegate to the Desk queues so the
screener and the desk share one source of truth.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from App.services import db, desk, universe
from App.services.common import STATUS_PARTIAL, Result, no_session, unavailable


class RuleError(ValueError):
    """Invalid rule / preset / parameter (maps to 422)."""


# field -> (SQL expression over the snapshot CTE alias `s`, kind)
FIELDS: dict[str, tuple[str, str]] = {
    "close": ("s.close", "num"),
    "open": ("s.open_price", "num"),
    "high": ("s.high_price", "num"),
    "low": ("s.low_price", "num"),
    "change_1d_pct": ("s.change_1d_pct", "num"),
    "volume": ("s.volume", "num"),
    "avg_volume_20d": ("s.avg_volume_20d", "num"),
    "rvol": ("s.rvol", "num"),
    "delivery_pct": ("s.delivery_pct", "num"),
    "delivery_vs_20d": ("s.delivery_vs_20d", "num"),
    "rs_percentile": ("s.rs_percentile", "num"),
    "rs_delta_5": ("s.rs_delta_5", "num"),
    "excess_vs_midsml400_63d": ("s.excess_vs_midsml400_63d", "num"),
    "excess_vs_nifty50_63d": ("s.excess_vs_nifty50_63d", "num"),
    "market_cap_cr": ("s.market_cap_cr", "num"),
    "adv_cr_20d": ("s.adv_cr_20d", "num"),
    "away_52w_high_pct": ("s.away_52w_high_pct", "num"),
    "away_52w_low_pct": ("s.away_52w_low_pct", "num"),
    "away_10ema_pct": ("s.away_10ema_pct", "num"),
    "adr_20_pct": ("s.adr_20_pct", "num"),
    "trend_template_pass_n": ("s.trend_template_pass_n", "num"),
    "return_1m_pct": ("s.return_1m_pct", "num"),
    "return_3m_pct": ("s.return_3m_pct", "num"),
    "return_6m_pct": ("s.return_6m_pct", "num"),
    "ema_10": ("s.ema_10", "num"),
    "ema_20": ("s.ema_20", "num"),
    "ema_50": ("s.ema_50", "num"),
    "ema_100": ("s.ema_100", "num"),
    "ema_200": ("s.ema_200", "num"),
    "sma_50": ("s.sma_50", "num"),
    "sma_150": ("s.sma_150", "num"),
    "sma_200": ("s.sma_200", "num"),
    "rsi_14": ("s.rsi_14", "num"),
    "rsi_14_w": ("s.rsi_14_w", "num"),
    "ema_spread_10_50_pct": ("s.ema_spread_10_50_pct", "num"),
    "trend_template_pass": ("s.trend_template_pass", "bool"),
    "sma_200_rising": ("s.sma_200_rising", "bool"),
    "nr7": ("s.nr7", "bool"),
    "inside_bar": ("s.inside_bar", "bool"),
    "nr7_or_inside": ("(s.nr7 OR s.inside_bar)", "bool"),
    "delivery_spike": ("s.delivery_spike", "bool"),
    "price_up_delivery_up": ("s.price_up_delivery_up", "bool"),
    "new_52w_high": ("(s.high_price >= s.high_52w)", "bool"),
}
OPS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "="}
BOOL_OPS = {"is_true", "is_false"}
FIELD_LABELS = {
    "close": "Close", "open": "Open", "high": "High", "low": "Low", "change_1d_pct": "1D %",
    "volume": "Day volume", "avg_volume_20d": "20D avg volume", "rvol": "RVOL",
    "delivery_pct": "Delivery %", "delivery_vs_20d": "Delivery vs 20D", "rs_percentile": "Strength rank",
    "rs_delta_5": "Strength rank Δ5", "excess_vs_midsml400_63d": "Excess vs MidSml400 63D",
    "excess_vs_nifty50_63d": "Excess vs Nifty 63D", "market_cap_cr": "Market cap (₹ Cr)",
    "adv_cr_20d": "20D avg traded value (₹ Cr)", "away_52w_high_pct": "% from 52W high",
    "away_52w_low_pct": "% above 52W low", "away_10ema_pct": "% from 10 EMA", "adr_20_pct": "ADR 20 %",
    "trend_template_pass_n": "Trend template checks", "return_1m_pct": "1M %", "return_3m_pct": "3M %",
    "return_6m_pct": "6M %", "ema_10": "10 EMA", "ema_20": "20 EMA", "ema_50": "50 EMA", "ema_100": "100 EMA",
    "ema_200": "200 EMA", "sma_50": "50 SMA", "sma_150": "150 SMA", "sma_200": "200 SMA",
    "rsi_14": "RSI 14", "rsi_14_w": "Weekly RSI", "ema_spread_10_50_pct": "10/20/50 EMA spread %",
    "trend_template_pass": "Trend template 8/8", "sma_200_rising": "200 SMA rising", "nr7": "NR7",
    "inside_bar": "Inside bar", "nr7_or_inside": "NR7 or inside bar", "delivery_spike": "Delivery spike",
    "price_up_delivery_up": "Price up on rising delivery", "new_52w_high": "New 52W high today",
}
# Rule field -> metric-dictionary key (tooltips in the custom-rule builder).
FIELD_METRIC = {k: k for k in (
    "change_1d_pct", "rvol", "delivery_pct", "delivery_vs_20d", "rs_percentile", "rs_delta_5",
    "excess_vs_midsml400_63d", "excess_vs_nifty50_63d", "market_cap_cr", "adv_cr_20d", "away_52w_high_pct",
    "away_52w_low_pct", "away_10ema_pct", "adr_20_pct", "trend_template_pass_n",
)}
SORTABLE = {"rs_percentile", "change_1d_pct", "rvol", "delivery_pct", "market_cap_cr", "away_52w_high_pct",
            "return_1m_pct", "return_3m_pct", "return_6m_pct", "excess_vs_midsml400_63d", "symbol", "rs_delta_5"}
SCREENER_METRICS = ["rs_percentile", "rs_delta_5", "change_1d_pct", "rvol", "delivery_pct", "away_52w_high_pct",
                    "excess_vs_midsml400_63d", "trend_template_pass_n", "market_cap_cr", "adv_cr_20d"]


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    description: str
    rules: tuple[dict[str, Any], ...] = ()
    kind: str = "rules"  # rules | queue | lab
    queue: str | None = None


def _r(field: str, op: str, value: Any = None, ref: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"field": field, "op": op}
    if ref is not None:
        out["ref"] = ref
    elif value is not None:
        out["value"] = value
    return out


EMA_STACK = (
    _r("ema_10", "gt", ref="ema_20"), _r("ema_20", "gt", ref="ema_50"),
    _r("ema_50", "gt", ref="ema_100"), _r("ema_100", "gt", ref="ema_200"),
)

PRESETS: dict[str, Preset] = {p.id: p for p in (
    Preset("minervini_8of8", "Minervini 8/8", "All eight trend-template checks pass and strength rank ≥ 70.",
           (_r("trend_template_pass", "is_true"), _r("rs_percentile", "gte", 70))),
    Preset("stage2_leader", "Stage 2 leader", "Above rising EMA stack, within 25% of the 52W high, ≥ 50% off the low.",
           (_r("close", "gt", ref="ema_200"), _r("away_10ema_pct", "gte", 0), _r("away_52w_high_pct", "gte", -25),
            _r("away_52w_low_pct", "gte", 50), *EMA_STACK)),
    Preset("ema_stack", "EMA stack", "10 > 20 > 50 > 100 > 200 EMA with price above the 10 EMA.",
           (*EMA_STACK, _r("away_10ema_pct", "gte", 0))),
    Preset("emas_converge", "EMAs converge", "10/20/50 EMAs within 3% of each other above the 200 EMA (coil).",
           (_r("ema_spread_10_50_pct", "lte", 3), _r("close", "gt", ref="ema_200"))),
    Preset("near_52w_high", "Near 52W high", "Within 5% of the 52W high, above the 10 and 200 EMA.",
           (_r("away_52w_high_pct", "gte", -5), _r("away_52w_low_pct", "gte", 50),
            _r("away_10ema_pct", "gte", 0), _r("close", "gt", ref="ema_200"))),
    Preset("fresh_52w_high", "Fresh 52W high", "Session high reached the 52-week high.",
           (_r("new_52w_high", "is_true"), _r("close", "gt", ref="ema_200"))),
    Preset("sma_template", "SMA template", "Minervini SMA structure (50 > 150 > 200, 200 rising) without the RS check.",
           (_r("close", "gt", ref="sma_150"), _r("close", "gt", ref="sma_200"), _r("sma_150", "gt", ref="sma_200"),
            _r("sma_50", "gt", ref="sma_150"), _r("close", "gt", ref="sma_50"), _r("sma_200_rising", "is_true"),
            _r("away_52w_high_pct", "gte", -25), _r("away_52w_low_pct", "gte", 50))),
    Preset("delivery_thrust", "Delivery thrust", "Delivery spike with price up on rising delivery, above 20/200 EMA.",
           (_r("delivery_spike", "is_true"), _r("price_up_delivery_up", "is_true"),
            _r("close", "gt", ref="ema_20"), _r("close", "gt", ref="ema_200"))),
    Preset("nr7_inside", "NR7 / Inside bar", "Narrowest range in 7 sessions or inside bar, within 15% of the high.",
           (_r("nr7_or_inside", "is_true"), _r("away_52w_high_pct", "gte", -15), _r("away_52w_low_pct", "gte", 50))),
    Preset("weekly_rsi_60", "Weekly RSI ≥ 60", "Weekly RSI at least 60 with price above the 10 and 200 EMA.",
           (_r("rsi_14_w", "gte", 60), _r("away_10ema_pct", "gte", 0), _r("close", "gt", ref="ema_200"))),
    Preset("darvas", "Darvas", "Desk Darvas Squeeze queue (same predicate as the Desk).", kind="queue", queue="darvas_squeeze"),
    Preset("vcp", "VCP", "Desk VCP queue (same predicate as the Desk).", kind="queue", queue="vcp"),
    Preset("uc_thrust", "UC thrust (lab)", "Upper-circuit thrust research preset.", kind="lab"),
)}


PRESET_CATEGORY = {
    "minervini_8of8": "Trend", "stage2_leader": "Trend", "ema_stack": "Trend", "sma_template": "Trend",
    "near_52w_high": "Highs", "fresh_52w_high": "Highs", "emas_converge": "Coil", "nr7_inside": "Coil",
    "delivery_thrust": "Momentum", "weekly_rsi_60": "Momentum", "darvas": "Setups", "vcp": "Setups",
    "uc_thrust": "Lab",
}
# Desk pool the Darvas / VCP queue presets use instead of the screener floors.
QUEUE_POOL_NOTE = ("Darvas / VCP presets use the Desk pool (≥ ₹1,000 Cr, 20D traded value ≥ ₹3 Cr, band > 5%, "
                   "no GSM / ASM stage 2) — screener floors other than the group filter do not apply.")


def field_catalog() -> list[dict[str, Any]]:
    """Rule fields for the custom-rule builder: id, label, kind (num|bool), metric-dictionary key."""
    return [{"field": f, "label": FIELD_LABELS.get(f, f), "kind": kind, "metric_key": FIELD_METRIC.get(f)}
            for f, (_, kind) in FIELDS.items()]


def presets() -> Result:
    rows = []
    for p in PRESETS.values():
        rows.append({
            "id": p.id,
            "label": p.label,
            "description": p.description,
            "kind": p.kind,
            "queue": p.queue,
            "category": PRESET_CATEGORY.get(p.id),
            "rules": [dict(r, label=rule_label(r)) for r in p.rules],
            "available": p.kind != "lab",
        })
    return Result(as_of=None, rows=rows, sources=["App/services/screener.py:PRESETS"],
                  notes=["uc_thrust is a research preset not yet ported to v2 (available=false).", QUEUE_POOL_NOTE],
                  extra={"fields": field_catalog(), "ops": sorted(OPS), "bool_ops": sorted(BOOL_OPS)})


def rule_label(rule: dict[str, Any]) -> str:
    field = FIELD_LABELS.get(rule["field"], rule["field"])
    op = rule["op"]
    if op in BOOL_OPS:
        return f"{field}" if op == "is_true" else f"not {field}"
    rhs = FIELD_LABELS.get(rule.get("ref", ""), rule.get("ref")) if rule.get("ref") else rule.get("value")
    return f"{field} {OPS[op]} {rhs}"


def parse_rules(raw: str | None) -> list[dict[str, Any]] | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise RuleError("rules must be a JSON array") from exc
    if not isinstance(data, list) or len(data) > 40:
        raise RuleError("rules must be a JSON array of at most 40 rules")
    return [validate_rule(r) for r in data]


def validate_rule(rule: Any) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise RuleError("each rule must be an object")
    field = rule.get("field")
    op = rule.get("op")
    if field not in FIELDS:
        raise RuleError(f"unknown field: {field!r}")
    kind = FIELDS[field][1]
    if kind == "bool":
        if op not in BOOL_OPS:
            raise RuleError(f"{field} is boolean; op must be is_true/is_false")
        return {"field": field, "op": op}
    if op not in OPS:
        raise RuleError(f"unknown op: {op!r}")
    if "ref" in rule and rule["ref"] is not None:
        ref = rule["ref"]
        if ref not in FIELDS or FIELDS[ref][1] != "num":
            raise RuleError(f"unknown ref field: {ref!r}")
        return {"field": field, "op": op, "ref": ref}
    value = rule.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuleError(f"rule on {field} needs a numeric value or a ref field")
    return {"field": field, "op": op, "value": float(value)}


def rule_sql(rule: dict[str, Any], rs_expr: str) -> tuple[str, list[Any]]:
    expr = FIELDS[rule["field"]][0]
    if rule["field"] == "rs_percentile":
        expr = rs_expr
    if rule["op"] == "is_true":
        return f"({expr}) IS TRUE", []
    if rule["op"] == "is_false":
        return f"({expr}) IS FALSE", []
    if "ref" in rule:
        return f"({expr} {OPS[rule['op']]} {FIELDS[rule['ref']][0]})", []
    return f"({expr} {OPS[rule['op']]} ?)", [rule["value"]]


EXTRA_COLS = """,
       i.open_price, i.high_price, i.low_price, i.high_52w, i.low_52w,
       i.ema_100, i.sma_50, i.sma_150, i.sma_200, i.sma_200_rising, i.rsi_14, i.rsi_14_w,
       i.nr7, i.inside_bar, i.delivery_spike, i.price_up_delivery_up,
       (greatest(i.ema_10, i.ema_20, i.ema_50) - least(i.ema_10, i.ema_20, i.ema_50))
           / nullif(i.close_price, 0) * 100 AS ema_spread_10_50_pct"""


@dataclass
class Params:
    min_mcap_cr: float = 1000.0
    min_price: float | None = 15.0
    min_day_volume: float | None = None
    min_avg_volume_20d: float | None = None
    lookback_days: int = 1
    include_ipos: bool = False
    level: str | None = None
    group: str | None = None


def _floors(p: Params, alias: str = "s") -> tuple[list[str], list[Any]]:
    where, params = [], []
    if p.min_mcap_cr and p.min_mcap_cr > 0:
        where.append(f"{alias}.market_cap_cr >= ?")
        params.append(float(p.min_mcap_cr))
    if p.min_price is not None:
        where.append(f"{alias}.close >= ?")
        params.append(float(p.min_price))
    if p.min_day_volume is not None:
        where.append(f"{alias}.volume >= ?")
        params.append(float(p.min_day_volume))
    if p.min_avg_volume_20d is not None:
        where.append(f"{alias}.avg_volume_20d >= ?")
        params.append(float(p.min_avg_volume_20d))
    if p.level:
        key = universe.level_key(p.level)
        if key is None:
            raise RuleError(f"unknown taxonomy level: {p.level!r}")
        if p.group:
            where.append(f"{alias}.{universe.LEVELS[key][0]} = ?")
            params.append(p.group)
    return where, params


def _rs_expr(p: Params) -> str:
    return "COALESCE(s.rs_percentile, s.rs_percentile_ipo)" if p.include_ipos else "s.rs_percentile"


def _match(con: Any, as_of: date, rules: list[dict[str, Any]], p: Params) -> list[dict[str, Any]]:
    """Rows passing floors on as_of and all rules on as_of (or any session in the lookback)."""
    rs_expr = _rs_expr(p)
    rule_parts = [rule_sql(r, rs_expr) for r in rules]
    rule_where = " AND ".join(sql for sql, _ in rule_parts) or "TRUE"
    rule_params = [v for _, vals in rule_parts for v in vals]
    floor_where, floor_params = _floors(p)
    snap = universe.snapshot_sql(con, extra_cols=EXTRA_COLS)
    lookback = max(1, min(int(p.lookback_days), 60))
    if lookback == 1:
        sql = f"""
            WITH s AS ({snap})
            SELECT s.*, s.trade_date AS last_pass_date FROM s
            WHERE {' AND '.join(floor_where) or 'TRUE'} AND {rule_where}
        """
        return db.records(con, sql, [as_of, *floor_params, *rule_params])
    sessions = db.recent_sessions(con, as_of, lookback)
    hits_sql = universe.snapshot_sql(con, extra_cols=EXTRA_COLS).replace(
        "WHERE i.trade_date = ?", "WHERE i.trade_date BETWEEN ? AND ?"
    )
    sql = f"""
        WITH s AS ({snap}),
        hits AS (
            SELECT h.symbol, max(h.trade_date) AS last_pass_date
            FROM ({hits_sql}) AS h
            WHERE {rule_where.replace('s.', 'h.')}
            GROUP BY h.symbol
        )
        SELECT s.*, hits.last_pass_date FROM s JOIN hits USING (symbol)
        WHERE {' AND '.join(floor_where) or 'TRUE'}
    """
    return db.records(con, sql, [as_of, sessions[-1], as_of, *rule_params, *floor_params])


def _history_cols(con: Any, as_of: date, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    sessions = db.recent_sessions(con, as_of, 252)
    start = sessions[-1]
    t20 = sessions[20] if len(sessions) > 20 else None
    con.register("scr_syms", pd.DataFrame({"symbol": symbols}))
    try:
        rows = db.records(
            con,
            """
            WITH h AS (
                SELECT i.symbol, i.trade_date, i.rs_percentile,
                       (i.close_price > i.ema_200 AND i.ema_50 > i.ema_200) AS stage2
                FROM indicators_daily i JOIN scr_syms USING (symbol)
                WHERE i.trade_date BETWEEN ? AND ?
            ),
            breaks AS (
                SELECT symbol, max(trade_date) FILTER (WHERE stage2 IS NOT TRUE) AS last_break,
                       min(trade_date) AS first_d,
                       max(rs_percentile) FILTER (WHERE trade_date = ?) AS rs_t20
                FROM h GROUP BY symbol
            )
            SELECT b.symbol, b.rs_t20,
                   (SELECT count(*) FROM h WHERE h.symbol = b.symbol
                        AND h.trade_date > COALESCE(b.last_break, b.first_d - INTERVAL 1 DAY)
                        AND h.stage2 IS TRUE) AS days_in_stage2,
                   b.last_break IS NULL AS stage2_full_window
            FROM breaks b
            """,
            [start, as_of, t20],
        )
    finally:
        con.unregister("scr_syms")
    return {r["symbol"]: r for r in rows}


def _shape(rec: dict[str, Any], hist: dict[str, Any], as_of: date, prev_syms: set[str] | None, p: Params) -> dict[str, Any]:
    base = universe.shape_stock(rec)
    rs = db.num(rec.get("rs_percentile"), 1)
    ipo_rs = rs is None and db.num(rec.get("rs_percentile_ipo")) is not None
    if p.include_ipos and ipo_rs:
        base["rs_percentile"] = db.num(rec.get("rs_percentile_ipo"), 1)
    h = hist.get(base["symbol"] or "", {})
    rs_t20 = db.num(h.get("rs_t20"))
    high_d = db.to_date(rec.get("high_52w_date"))
    return {
        **base,
        "rs_is_ipo_rank": bool(p.include_ipos and ipo_rs),
        "rs_delta_20": round(rs - rs_t20, 1) if rs is not None and rs_t20 is not None else None,
        "rs_rank_t5": db.num(rec.get("rs_rank_t5"), 1),
        "rs_rank_t15": db.num(rec.get("rs_rank_t15"), 1),
        "rs_rank_t30": db.num(rec.get("rs_rank_t30"), 1),
        "trend_template_pass_n": db.integer(rec.get("trend_template_pass_n")),
        "away_52w_high_pct": db.num(rec.get("away_52w_high_pct"), 2),
        "days_since_52w_high": (as_of - high_d).days if high_d and high_d <= as_of else None,
        "days_in_stage2": db.integer(h.get("days_in_stage2")),
        "days_in_stage2_capped": bool(h.get("stage2_full_window")) if h else None,
        "return_1m_pct": db.num(rec.get("return_1m_pct"), 2),
        "return_3m_pct": db.num(rec.get("return_3m_pct"), 2),
        "return_6m_pct": db.num(rec.get("return_6m_pct"), 2),
        "last_pass_date": db.to_date(rec.get("last_pass_date")),
        "is_new": (base["symbol"] not in prev_syms) if prev_syms is not None else None,
    }


def resolve_rules(preset_id: str | None, rules: list[dict[str, Any]] | None) -> tuple[Preset | None, list[dict[str, Any]]]:
    preset = None
    if preset_id:
        preset = PRESETS.get(preset_id)
        if preset is None:
            raise RuleError(f"unknown preset: {preset_id!r}")
    if rules is not None:
        return preset, rules
    return preset, [dict(r) for r in preset.rules] if preset else []


def run(as_of: date | None, preset_id: str | None, rules: list[dict[str, Any]] | None, p: Params,
        sort: str = "rs_percentile", descending: bool = True) -> Result:
    preset, applied = resolve_rules(preset_id, rules)
    if sort not in SORTABLE:
        raise RuleError(f"cannot sort by {sort!r}")
    if preset is not None and preset.kind == "lab" and rules is None:
        return unavailable(None, f"{preset.label} is a research preset not yet ported to v2", [], preset=preset.id)
    if preset is not None and preset.kind == "queue" and rules is None:
        return _run_queue(as_of, preset, p, sort, descending)
    _floors(p)  # validate level early
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        key = (resolved, json.dumps(applied, sort_keys=True), repr(p))

        def compute() -> tuple[list[dict[str, Any]], list[dict[str, Any]], date | None]:
            matched = _match(con, resolved, applied, p)
            prev = db.session_back(con, resolved, 1)
            prev_recs = _match(con, prev, applied, p) if prev else None
            prev_syms = {r["symbol"] for r in prev_recs} if prev_recs is not None else None
            hist = _history_cols(con, resolved, [r["symbol"] for r in matched])
            shaped = [_shape(r, hist, resolved, prev_syms, p) for r in matched]
            today = {r["symbol"] for r in shaped}
            dropped = [_dropped_row(r) for r in (prev_recs or []) if r["symbol"] not in today]
            return shaped, dropped, prev

        rows, dropped, prev_session = db.cached("screener.run", key, compute)
    rows = sort_rows(rows, sort, descending)
    return Result(
        as_of=resolved,
        rows=rows,
        sources=["indicators_daily", "stocks_master", "security_reference_daily"],
        extra={
            "preset": preset.id if preset else None,
            "applied_rules": [dict(r, label=rule_label(r)) for r in applied],
            "previous_session": prev_session,
            "new_count": sum(1 for r in rows if r.get("is_new")),
            "dropped": sorted(dropped, key=lambda r: r["symbol"] or ""),
            "floors": {
                "min_mcap_cr": p.min_mcap_cr, "min_price": p.min_price, "min_day_volume": p.min_day_volume,
                "min_avg_volume_20d": p.min_avg_volume_20d, "lookback_days": p.lookback_days,
                "include_ipos": p.include_ipos, "level": p.level, "group": p.group,
            },
        },
        notes=["Rules fail closed: a missing input fails the rule.",
               "lookback_days > 1: all rules held together on at least one session in the window; floors apply on as_of."],
        metric_keys=SCREENER_METRICS,
    )


def _dropped_row(rec: dict[str, Any]) -> dict[str, Any]:
    """A stock that matched on the previous session but not on as_of (shown as it was then)."""
    base = universe.shape_stock(rec)
    return {"symbol": base["symbol"], "close": base["close"], "rs_percentile": base["rs_percentile"],
            "industry": base["industry"]}


def _run_queue(as_of: date | None, preset: Preset, p: Params, sort: str, descending: bool) -> Result:
    """Darvas / VCP presets: the Desk queue itself (one predicate), optionally narrowed to a taxonomy group."""
    queue = preset.queue or ""
    res = desk.queue_rows(as_of, queue, "D")
    rows = list(res.rows)
    if p.level:
        key = universe.level_key(p.level)
        if key is None:
            raise RuleError(f"unknown taxonomy level: {p.level!r}")
        if p.group:
            rows = [r for r in rows if r.get(key) == p.group]
    rows = sort_rows(rows, sort, descending)
    dropped: list[dict[str, Any]] = []
    prev_session = None
    if res.as_of is not None and res.status != "unavailable":
        diff = desk.diff(res.as_of, queue, "D")
        prev_session = diff.extra.get("previous_session")
        for r in diff.rows:
            if r["change"] != "dropped":
                continue
            dropped.append({"symbol": r["symbol"], "close": r["close"], "rs_percentile": r["rs_percentile"],
                            "industry": r["industry"]})
    res = Result(
        as_of=res.as_of, rows=rows, status=res.status, reason=res.reason, sources=res.sources,
        notes=[*res.notes, QUEUE_POOL_NOTE], metric_keys=res.metric_keys,
        extra={**res.extra, "preset": preset.id, "applied_rules": [], "delegated_to": f"desk/queue/{queue}",
               "previous_session": prev_session, "new_count": sum(1 for r in rows if r.get("is_new")),
               "dropped": dropped, "floors": {"level": p.level, "group": p.group}},
    )
    return res


def sort_rows(rows: list[dict[str, Any]], key: str, descending: bool) -> list[dict[str, Any]]:
    """Sort by `key`, NULLs always last."""
    present = [r for r in rows if r.get(key) is not None]
    missing = [r for r in rows if r.get(key) is None]
    present.sort(key=lambda r: r[key], reverse=descending)
    return present + missing


def debug(as_of: date | None, symbol: str, preset_id: str | None, rules: list[dict[str, Any]] | None, p: Params) -> Result:
    preset, applied = resolve_rules(preset_id, rules)
    if preset is not None and preset.kind == "queue" and rules is None:
        return _debug_queue(as_of, symbol, preset, p)
    if preset is not None and preset.kind != "rules" and rules is None:
        return unavailable(None, f"{preset.label} is not a rule preset; use desk/queue for its predicate", [])
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        snap = universe.snapshot_sql(con, extra_where="AND i.symbol = ?", extra_cols=EXTRA_COLS)
        recs = db.records(con, f"WITH s AS ({snap}) SELECT * FROM s", [resolved, symbol])
        if not recs:
            return unavailable(resolved, f"{symbol} has no row on {resolved.isoformat()}", ["indicators_daily"])
        rec = recs[0]
        rows = []
        floor_where, floor_params = _floors(p)
        for clause, label in zip(floor_where, _floor_labels(p)):
            n_params = clause.count("?")
            vals, floor_params = floor_params[:n_params], floor_params[n_params:]
            passed = con.execute(f"WITH s AS ({snap}) SELECT ({clause}) IS TRUE FROM s",
                                 [resolved, symbol, *vals]).fetchone()[0]
            rows.append({"kind": "floor", "label": label, "field": label.split(" ")[0], "op": None,
                         "value": vals[0] if vals else None, "ref": None, "actual": None,
                         "ref_actual": None, "passed": bool(passed)})
        rs_expr = _rs_expr(p)
        for r in applied:
            clause, vals = rule_sql(r, rs_expr)
            passed = con.execute(f"WITH s AS ({snap}) SELECT {clause} FROM s", [resolved, symbol, *vals]).fetchone()[0]
            actual_expr = rs_expr if r["field"] == "rs_percentile" else FIELDS[r["field"]][0]
            actual = con.execute(f"WITH s AS ({snap}) SELECT {actual_expr} FROM s", [resolved, symbol]).fetchone()[0]
            ref_actual = None
            if "ref" in r:
                ref_actual = con.execute(f"WITH s AS ({snap}) SELECT {FIELDS[r['ref']][0]} FROM s",
                                         [resolved, symbol]).fetchone()[0]
            rows.append({
                "kind": "rule", "label": rule_label(r), "field": r["field"], "op": r["op"],
                "value": r.get("value"), "ref": r.get("ref"),
                "actual": db.num(actual, 4) if not isinstance(actual, bool) else actual,
                "ref_actual": db.num(ref_actual, 4),
                "passed": bool(passed),
                "missing_input": actual is None,
            })
    return Result(
        as_of=resolved,
        rows=rows,
        sources=["indicators_daily"],
        extra={"symbol": symbol, "preset": preset.id if preset else None,
               "passes_all": all(r["passed"] for r in rows)},
    )


def _check(label: str, passed: bool, *, field: str | None = None, value: Any = None, actual: Any = None,
           ref_actual: Any = None, detail: str | None = None, kind: str = "check") -> dict[str, Any]:
    return {"kind": kind, "label": label, "field": field, "op": None,
            "value": db.num(value, 4), "ref": None,
            "actual": actual if isinstance(actual, (bool, str)) or actual is None else db.num(actual, 4),
            "ref_actual": db.num(ref_actual, 4), "passed": bool(passed),
            "missing_input": actual is None and field is not None, "detail": detail}


def _debug_queue(as_of: date | None, symbol: str, preset: Preset, p: Params) -> Result:
    """Why is `symbol` (not) in a Desk queue: the Desk pool gates, then the queue's own predicate.

    Uses the same functions as the queue (desk pool gates, squeeze_frame, detect_contractions);
    the final row is the authoritative membership test from desk.queue_rows.
    """
    queue = preset.queue or ""
    with db.market_conn() as con:
        resolved = db.resolve_as_of(con, as_of)
        if resolved is None:
            return no_session(as_of)
        snap = universe.snapshot_sql(
            con, extra_where="AND i.symbol = ?",
            extra_cols=", COALESCE(i.avg_traded_value_cr_20d, i.turnover_cr) AS pool_adv_cr, m.band_remarks",
        )
        recs = db.records(con, f"WITH s AS ({snap}) SELECT * FROM s", [resolved, symbol])
        if not recs:
            return unavailable(resolved, f"{symbol} has no row on {resolved.isoformat()}", ["indicators_daily"])
        rec = recs[0]
        rows: list[dict[str, Any]] = []
        pool = desk.POOL
        mcap = db.num(rec.get("market_cap_cr"))
        adv = db.num(rec.get("pool_adv_cr"))
        band = db.num(rec.get("circuit_band"))
        remarks = str(rec.get("band_remarks") or "")
        rows.append(_check(f"Market cap >= {pool['min_mcap']:,.0f} Cr", mcap is not None and mcap >= pool["min_mcap"],
                           field="market_cap_cr", value=pool["min_mcap"], actual=mcap, kind="floor"))
        rows.append(_check(f"20D traded value >= {pool['min_adv_cr']:g} Cr",
                           adv is not None and adv >= pool["min_adv_cr"],
                           field="adv_cr_20d", value=pool["min_adv_cr"], actual=adv, kind="floor"))
        rows.append(_check(f"Circuit band > {pool['min_band']:g}% (unknown passes)",
                           band is None or band > pool["min_band"],
                           field="circuit_band", value=pool["min_band"], actual=band, kind="floor"))
        surveil = "GSM" in remarks or "STAGE 2" in remarks
        rows.append(_check("Not in GSM / ASM stage 2", not surveil, detail=remarks or None, kind="floor"))
        if symbol.endswith("-RE") or symbol.endswith("_RE"):
            rows.append(_check("Not a rights entitlement", False, detail="rights-entitlement symbols are excluded",
                               kind="floor"))
        close = db.num(rec.get("close"))
        ema200 = db.num(rec.get("ema_200"))
        rows.append(_check("Close > 200 EMA (unknown 200 EMA passes - Desk rule)",
                           ema200 is None or (close is not None and close > ema200),
                           field="close", actual=close, ref_actual=ema200))
        if p.level and p.group:
            key = universe.level_key(p.level)
            if key is None:
                raise RuleError(f"unknown taxonomy level: {p.level!r}")
            rows.append(_check(f"{universe.LEVELS[key][1]} = {p.group}", rec.get(key) == p.group,
                               detail=db.text(rec.get(key)), kind="floor"))
        try:
            rows.extend(_queue_predicate_checks(con, resolved, symbol, queue, rec))
        except Exception as exc:  # noqa: BLE001 - diagnostics are best-effort; membership below is authoritative
            rows.append(_check("Queue geometry", False, detail=f"could not evaluate: {exc}"))
    res = desk.queue_rows(resolved, queue, "D")
    member = any(r.get("symbol") == symbol for r in res.rows)
    rows.append(_check(f"In the {desk.QUEUES[queue]['label']} queue on {resolved.isoformat()}", member,
                       detail="authoritative: same predicate as the Desk queue", kind="result"))
    return Result(
        as_of=resolved,
        rows=rows,
        status=res.status if res.status != "unavailable" else "partial",
        reason=res.reason,
        sources=["indicators_daily", "prices_daily", "stocks_master"],
        extra={"symbol": symbol, "preset": preset.id, "queue": queue, "passes_all": member},
        notes=[QUEUE_POOL_NOTE],
    )


def _queue_predicate_checks(con: Any, as_of: date, symbol: str, queue: str, rec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if queue == "darvas_squeeze":
        n = int(desk.DARVAS["box_lookback_sessions"])
        hist = desk._history(con, as_of, [symbol], n)
        if hist.empty:
            return [_check("Price history available", False, detail="no bars in the Darvas lookback")]
        frame = desk.squeeze_frame(desk._last_sessions(hist, n), timeframe="D")
        if frame.empty:
            return [_check("Enough bars for a Darvas box", False, detail="fewer than 5 sessions")]
        row = frame.iloc[0].to_dict()
        max_sq = float(desk.DARVAS["max_squeeze_pct"])
        sq = db.num(row.get("squeeze_pct"))
        out.append(_check(f"Squeeze: 10 EMA within {max_sq:g}% under the box top",
                          sq is not None and 0 <= sq <= max_sq, field="squeeze_pct", value=max_sq, actual=sq))
        top = db.num(row.get("darvas_top"))
        close = db.num(rec.get("close"))
        near = top is not None and close is not None and top > 0 and -0.2 <= (top - close) / top * 100 <= max_sq
        out.append(_check("Close at or just under the box top", near, field="darvas_box_top",
                          actual=close, ref_actual=top))
        out.append(_check("All squeeze conditions (range, EMA order, inside box, persistence)",
                          bool(row.get("qualifies")), field="candle_range_pct",
                          actual=db.num(row.get("candle_range_pct")),
                          detail="squeeze_frame.qualifies - the Desk predicate"))
    elif queue == "vcp":
        hist = desk._history(con, as_of, [symbol], 252)
        vol = db.num(rec.get("avg_volume_20d"))
        close = db.num(rec.get("close"))
        out.append(_check(f"20D avg volume >= {desk.VCP_MIN_AVG_VOLUME_20D:,} (unknown passes)",
                          vol is None or vol >= desk.VCP_MIN_AVG_VOLUME_20D, field="avg_volume_20d",
                          value=desk.VCP_MIN_AVG_VOLUME_20D, actual=vol))
        out.append(_check(f"Close >= {desk.VCP_MIN_CLOSE:g}", close is not None and close >= desk.VCP_MIN_CLOSE,
                          field="close", value=desk.VCP_MIN_CLOSE, actual=close))
        if hist.empty or len(hist) < 60:
            out.append(_check(">= 60 sessions of history", False, actual=int(len(hist))))
            return out
        g = hist.tail(252).reset_index(drop=True)
        seq = desk.detect_contractions(
            g[["trade_date", "open_price", "high_price", "low_price", "close_price", "volume"]])
        n = len(seq.contractions)
        depths = ", ".join(f"{c.label} {c.depth_pct:.1f}%" for c in seq.contractions) or None
        out.append(_check(f">= {desk.VCP_MIN_CONTRACTIONS} strictly shrinking contractions",
                          n >= desk.VCP_MIN_CONTRACTIONS, field="vcp_contractions",
                          value=desk.VCP_MIN_CONTRACTIONS, actual=n, detail=depths))
        last_close = float(g["close_price"].iloc[-1])
        has_geo = seq.pivot is not None and seq.stop is not None
        inside = has_geo and seq.stop < last_close <= seq.pivot * desk.VCP_MAX_ABOVE_PIVOT
        out.append(_check(f"Close inside the base (stop < close <= pivot x {desk.VCP_MAX_ABOVE_PIVOT:g})", inside,
                          field="trigger_price", actual=last_close, ref_actual=seq.pivot,
                          detail=(f"pivot {seq.pivot:.2f}, stop {seq.stop:.2f}" if has_geo
                                  else "no pivot / stop found")))
    return out


def _floor_labels(p: Params) -> list[str]:
    out = []
    if p.min_mcap_cr and p.min_mcap_cr > 0:
        out.append(f"market_cap_cr >= {p.min_mcap_cr:g}")
    if p.min_price is not None:
        out.append(f"close >= {p.min_price:g}")
    if p.min_day_volume is not None:
        out.append(f"volume >= {p.min_day_volume:g}")
    if p.min_avg_volume_20d is not None:
        out.append(f"avg_volume_20d >= {p.min_avg_volume_20d:g}")
    if p.level and p.group:
        out.append(f"{universe.level_key(p.level)} = {p.group}")
    return out
