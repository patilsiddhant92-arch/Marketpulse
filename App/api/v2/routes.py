"""API v2 routes (spec §8). Thin: validate → call a service → wrap in the envelope."""
from __future__ import annotations

import os
import re
import subprocess
from datetime import date
from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from App.api.v2 import models as m
from App.services import common, db, deals, desk, evidence, groups, market, metrics, research, screener, stock, user
from App.services.common import Result

API_VERSION = "2.0.0"
SYMBOL_RE = re.compile(r"^[A-Z0-9&\-_.]{1,20}$")
MAX_LIMIT = 5000


class V2Route(APIRoute):
    """Maps service exceptions to HTTP: DB lock/missing → 503 + Retry-After."""

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except db.DBUnavailable as exc:
                return JSONResponse(status_code=503, content={"detail": exc.reason},
                                    headers={"Retry-After": str(exc.retry_after)})

        return handler


router = APIRouter(prefix="/api/v2", route_class=V2Route)


def _build() -> str:
    env = os.environ.get("MP_BUILD", "").strip()
    if env:
        return env
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(db.ROOT_DIR), capture_output=True,
                             text=True, timeout=3)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


BUILD = _build()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def symbol_param(raw: str) -> str:
    sym = str(raw or "").strip().upper()
    if not SYMBOL_RE.fullmatch(sym):
        raise HTTPException(status_code=422, detail=f"invalid symbol {raw!r}")
    return sym


AsOf = Query(None, description="Time travel: all data bounded to sessions on or before this date (YYYY-MM-DD)")
Offset = Query(0, ge=0)
Limit = Query(500, ge=1, le=MAX_LIMIT)


def _freshness(as_of: date | None, strict: bool = True) -> dict[str, Any]:
    try:
        with db.market_conn() as con:
            return common.freshness(con, as_of)
    except db.DBUnavailable:
        if strict:
            raise
        return {"status": "unavailable", "history_mode": False, "reason": "market database unavailable"}


def envelope(result: Result, offset: int = 0, limit: int = MAX_LIMIT, strict: bool = True) -> dict[str, Any]:
    rows = result.rows or []
    page = rows[offset: offset + limit]
    return {
        "as_of": result.as_of,
        "freshness": _freshness(result.as_of, strict),
        "total": len(rows),
        "returned": len(page),
        "rows": page,
        "meta": {
            "status": result.status,
            "reason": result.reason,
            "sources": result.sources,
            "notes": result.notes,
            "offset": offset,
            "limit": limit,
            "metric_keys": result.metric_keys,
            "context": result.extra,
        },
    }


def _call(fn: Callable[..., Result], *args: Any, **kwargs: Any) -> Result:
    try:
        return fn(*args, **kwargs)
    except screener.RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown: {exc.args[0] if exc.args else ''}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
@router.get("/health", response_model=m.HealthResponse, responses={503: {"model": m.HealthResponse}})
def health(response: Response) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    try:
        with db.market_conn() as con:
            fr = common.freshness(con, None)
            checks.append({"name": "market_db", "ok": True, "detail": "opened read-only"})
            for table in ("indicators_daily", "prices_daily", "breadth_daily", "regime_daily", "group_daily",
                          "setup_daily", "deal_session_net"):
                ok = db.table_exists(con, table)
                checks.append({"name": f"table:{table}", "ok": ok, "detail": None if ok else "missing"})
    except db.DBUnavailable as exc:
        fr = {"status": "unavailable", "history_mode": False, "reason": exc.reason}
        checks.append({"name": "market_db", "ok": False, "detail": exc.reason})
        response.headers["Retry-After"] = str(exc.retry_after)
    checks.append({"name": "freshness", "ok": fr["status"] == "fresh",
                   "detail": f"latest {fr.get('latest_session')} expected {fr.get('expected_session')}"})
    checks.append({"name": "metric_dictionary", "ok": bool(metrics.load()), "detail": str(len(metrics.load())) + " entries"})
    status = {"fresh": "healthy", "stale": "stale", "degraded": "degraded"}.get(fr["status"], "unavailable")
    if status != "healthy":
        response.status_code = 503
    return {"status": status, "version": API_VERSION, "build": BUILD, "freshness": fr, "checks": checks}


# --------------------------------------------------------------------------
# Market
# --------------------------------------------------------------------------
@router.get("/market/regime", response_model=m.Envelope[m.RegimeRow])
def market_regime(as_of: Optional[date] = AsOf, days: int = Query(126, ge=1, le=2000),
                  offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(market.regime, as_of, days), offset, limit)


@router.get("/market/health", response_model=m.Envelope[m.MarketHealthRow])
def market_health(as_of: Optional[date] = AsOf, days: int = Query(250, ge=1, le=2000),
                  offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(market.health, as_of, days), offset, limit)


# --------------------------------------------------------------------------
# Desk
# --------------------------------------------------------------------------
QueueName = Literal["darvas_squeeze", "darvas_10ema", "vcp"]
QueueSort = Literal["rs_percentile", "distance_to_trigger_pct", "risk_pct", "setup_age_sessions", "rvol",
                    "change_1d_pct", "squeeze_pct", "excess_vs_midsml400_63d", "symbol"]


@router.get("/desk/queues", response_model=m.Envelope[m.QueueSummaryRow])
def desk_queues(as_of: Optional[date] = AsOf,
                all_timeframes: bool = Query(False, description="Also count W/M (slow until setup_daily exists)")) -> dict[str, Any]:
    return envelope(_call(desk.queues_summary, as_of, all_timeframes))


@router.get("/desk/queue/{name}", response_model=m.Envelope[m.QueueRow])
def desk_queue(name: QueueName, as_of: Optional[date] = AsOf, tf: Literal["D", "W", "M"] = "D",
               sort: Optional[QueueSort] = None, desc: bool = False,
               offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    res = _call(desk.queue_rows, as_of, name, tf)
    if sort:
        res.rows = screener.sort_rows(res.rows, sort, desc)
    return envelope(res, offset, limit)


@router.get("/desk/watchlist", response_model=m.Envelope[m.DeskWatchRow])
def desk_watchlist(as_of: Optional[date] = AsOf,
                   symbols: str = Query("", max_length=25000, description="Comma-separated symbols, in display order"),
                   offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    syms = [symbol_param(s) for s in symbols.split(",") if s.strip()]
    if len(syms) > 1000:
        raise HTTPException(status_code=422, detail="at most 1000 symbols")
    return envelope(_call(desk.watchlist_rows, as_of, syms), offset, limit)


@router.get("/desk/diff", response_model=m.Envelope[m.DiffRow])
def desk_diff(as_of: Optional[date] = AsOf, queue: Optional[QueueName] = None, tf: Literal["D", "W", "M"] = "D",
              offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(desk.diff, as_of, queue, tf), offset, limit)


# --------------------------------------------------------------------------
# Screener
# --------------------------------------------------------------------------
ScreenerSort = Literal["rs_percentile", "change_1d_pct", "rvol", "delivery_pct", "market_cap_cr", "away_52w_high_pct",
                       "return_1m_pct", "return_3m_pct", "return_6m_pct", "excess_vs_midsml400_63d", "symbol",
                       "rs_delta_5"]


def _params(min_mcap_cr: float, min_price: Optional[float], min_day_volume: Optional[float],
            min_avg_volume_20d: Optional[float], lookback_days: int, include_ipos: bool,
            level: Optional[str], group: Optional[str]) -> screener.Params:
    return screener.Params(min_mcap_cr=min_mcap_cr, min_price=min_price, min_day_volume=min_day_volume,
                           min_avg_volume_20d=min_avg_volume_20d, lookback_days=lookback_days,
                           include_ipos=include_ipos, level=level, group=group)


@router.get("/screener/presets", response_model=m.Envelope[m.PresetRow])
def screener_presets() -> dict[str, Any]:
    return envelope(screener.presets(), strict=False)


@router.get("/screener/run", response_model=m.Envelope[m.ScreenerRow])
def screener_run(
    as_of: Optional[date] = AsOf,
    preset: Optional[str] = Query(None, max_length=40),
    rules: Optional[str] = Query(None, max_length=8000, description="JSON array of rules; replaces the preset's rules"),
    min_mcap_cr: float = Query(1000.0, ge=0, description="Market-cap floor, ₹ Cr (point-in-time where available)"),
    min_price: Optional[float] = Query(15.0, ge=0),
    min_day_volume: Optional[float] = Query(None, ge=0, description="Session volume floor (shares)"),
    min_avg_volume_20d: Optional[float] = Query(None, ge=0, description="20-day average volume floor (shares)"),
    lookback_days: int = Query(1, ge=1, le=60, description="Rules may have held on any session in this window"),
    include_ipos: bool = Query(False, description="Use rs_percentile_ipo when rs_percentile is NULL (badged)"),
    level: Optional[str] = Query(None, max_length=40),
    group: Optional[str] = Query(None, max_length=120),
    sort: ScreenerSort = "rs_percentile",
    desc: bool = True,
    offset: int = Offset,
    limit: int = Limit,
) -> dict[str, Any]:
    try:
        parsed = screener.parse_rules(rules)
    except screener.RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    p = _params(min_mcap_cr, min_price, min_day_volume, min_avg_volume_20d, lookback_days, include_ipos, level, group)
    return envelope(_call(screener.run, as_of, preset, parsed, p, sort, desc), offset, limit)


@router.get("/screener/debug", response_model=m.Envelope[m.DebugRow])
def screener_debug(
    symbol: str = Query(..., max_length=20),
    as_of: Optional[date] = AsOf,
    preset: Optional[str] = Query(None, max_length=40),
    rules: Optional[str] = Query(None, max_length=8000),
    min_mcap_cr: float = Query(1000.0, ge=0),
    min_price: Optional[float] = Query(15.0, ge=0),
    min_day_volume: Optional[float] = Query(None, ge=0),
    min_avg_volume_20d: Optional[float] = Query(None, ge=0),
    include_ipos: bool = False,
    level: Optional[str] = Query(None, max_length=40),
    group: Optional[str] = Query(None, max_length=120),
) -> dict[str, Any]:
    sym = symbol_param(symbol)
    try:
        parsed = screener.parse_rules(rules)
    except screener.RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    p = _params(min_mcap_cr, min_price, min_day_volume, min_avg_volume_20d, 1, include_ipos, level, group)
    return envelope(_call(screener.debug, as_of, sym, preset, parsed, p))


# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------
Level = Literal["broad_sector", "sector", "broad_industry", "industry"]
Floor = Literal["1000", "all", "watch"]
MemberSort = Literal["rs_percentile", "change_1d_pct", "rvol", "delivery_pct", "market_cap_cr", "rs_delta_5",
                     "rs_vs_sector_index_63d", "trend_template_pass_n", "delivery_accumulation_days", "symbol"]


@router.get("/groups/board", response_model=m.Envelope[m.GroupRow])
def groups_board(as_of: Optional[date] = AsOf, level: Level = "industry", floor: Floor = "1000",
                 offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(groups.board, as_of, level, floor), offset, limit)


@router.get("/groups/rrg", response_model=m.Envelope[m.RrgRow])
def groups_rrg(as_of: Optional[date] = AsOf, level: Level = "industry", floor: Floor = "1000",
               tail_weeks: int = Query(6, ge=1, le=12), offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(groups.rrg, as_of, level, floor, tail_weeks), offset, limit)


@router.get("/groups/{group_id:path}/members", response_model=m.Envelope[m.MemberRow],
            description="Group members at as_of — also a Charts source. group_id = '<level>:<name>'.")
def groups_members(group_id: str = Path(..., max_length=160), as_of: Optional[date] = AsOf, floor: Floor = "1000",
                   sort: MemberSort = "rs_percentile", desc: bool = True,
                   offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(groups.members, as_of, group_id, floor, sort, desc), offset, limit)


@router.get("/groups/{group_id:path}", response_model=m.Envelope[m.GroupRow],
            description="Group drill-down history (newest first). group_id = '<level>:<name>'.")
def groups_detail(group_id: str = Path(..., max_length=160), as_of: Optional[date] = AsOf, floor: Floor = "1000",
                  days: int = Query(60, ge=5, le=600), offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(groups.detail, as_of, group_id, floor, days), offset, limit)


# --------------------------------------------------------------------------
# Deals
# --------------------------------------------------------------------------
@router.get("/deals/session", response_model=m.Envelope[m.DealSessionRow])
def deals_session(as_of: Optional[date] = AsOf, min_mcap_cr: float = Query(1000.0, ge=0),
                  offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals.session, as_of, min_mcap_cr), offset, limit)


@router.get("/deals/houses", response_model=m.Envelope[m.HouseRow],
            description="Every deal client with its print summary and next-open track record.")
def deals_houses(as_of: Optional[date] = AsOf, session_only: bool = False,
                 offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals.houses, as_of, session_only), offset, limit)


@router.get("/deals/house/{house_id}", response_model=m.Envelope[m.HousePrintRow])
def deals_house(house_id: str = Path(..., max_length=200), as_of: Optional[date] = AsOf,
                offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals.house, as_of, house_id), offset, limit)


Lookback = Query(20, ge=2, le=60, description="Deal sessions in the window (old desk: 10 / 20 / 30)")


@router.get("/deals/prints", response_model=m.Envelope[m.DealPrintRow])
def deals_prints(as_of: Optional[date] = AsOf, min_mcap_cr: float = Query(0.0, ge=0),
                 offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals.prints, as_of, min_mcap_cr), offset, limit)


@router.get("/deals/window", response_model=m.Envelope[m.DealWindowRow])
def deals_window(as_of: Optional[date] = AsOf, lookback: int = Lookback, min_mcap_cr: float = Query(1000.0, ge=0),
                 setup: Literal["ALL", "ABOVE_200", "TURNAROUND"] = "ALL",
                 offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals.window, as_of, lookback, min_mcap_cr, setup), offset, limit)


@router.get("/deals/leaderboard", response_model=m.Envelope[m.DealLeaderRow])
def deals_leaderboard(as_of: Optional[date] = AsOf, lookback: int = Lookback, include_individuals: bool = False,
                      ranked_only: bool = False, min_bets: int = Query(5, ge=3, le=50),
                      offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals.leaderboard, as_of, lookback, include_individuals, ranked_only, min_bets), offset, limit)


@router.get("/deals/star-radar", response_model=m.Envelope[m.DealStarRow])
def deals_star_radar(as_of: Optional[date] = AsOf, lookback: int = Lookback, include_individuals: bool = False,
                     stars_from: Literal["strong", "steady"] = "strong", min_bets: int = Query(5, ge=3, le=50),
                     offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(deals.star_radar, as_of, lookback, include_individuals, stars_from, min_bets), offset, limit)


@router.get("/deals/followthrough", response_model=m.Envelope[m.FollowThroughRow])
def deals_followthrough(as_of: Optional[date] = AsOf, min_mcap_cr: float = Query(1000.0, ge=0)) -> dict[str, Any]:
    return envelope(_call(deals.followthrough, as_of, min_mcap_cr))


# --------------------------------------------------------------------------
# Stock
# --------------------------------------------------------------------------
@router.get("/stock/{sym}", response_model=m.Envelope[m.StockHeaderRow])
def stock_header(sym: str, as_of: Optional[date] = AsOf) -> dict[str, Any]:
    return envelope(_call(stock.header, as_of, symbol_param(sym)))


@router.get("/stock/{sym}/bars", response_model=m.Envelope[m.BarRow])
def stock_bars(sym: str, as_of: Optional[date] = AsOf, tf: Literal["D", "W", "M"] = "D",
               limit: int = Query(400, ge=1, le=MAX_LIMIT)) -> dict[str, Any]:
    return envelope(_call(stock.bars, as_of, symbol_param(sym), tf, limit), 0, limit)


@router.get("/stock/{sym}/rs", response_model=m.Envelope[m.RsRow])
def stock_rs(sym: str, as_of: Optional[date] = AsOf, limit: int = Query(400, ge=20, le=MAX_LIMIT)) -> dict[str, Any]:
    return envelope(_call(stock.rs_line, as_of, symbol_param(sym), limit), 0, limit)


@router.get("/stock/{sym}/events", response_model=m.Envelope[m.EventRow])
def stock_events(sym: str, as_of: Optional[date] = AsOf, days_ahead: int = Query(14, ge=0, le=60),
                 offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(stock.events, as_of, symbol_param(sym), days_ahead), offset, limit)


@router.get("/stock/{sym}/deals", response_model=m.Envelope[m.StockDealRow])
def stock_deals(sym: str, as_of: Optional[date] = AsOf, offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(stock.stock_deals, as_of, symbol_param(sym)), offset, limit)


@router.get("/stock/{sym}/analogs", response_model=m.Envelope[m.StockAnalogRow])
def stock_analogs(sym: str, as_of: Optional[date] = AsOf) -> dict[str, Any]:
    return envelope(_call(stock.analogs, as_of, symbol_param(sym)))


# --------------------------------------------------------------------------
# Evidence / research
# --------------------------------------------------------------------------
@router.get("/evidence/{setup}", response_model=m.Envelope[m.EvidenceRow])
def evidence_setup(setup: str = Path(..., max_length=40), as_of: Optional[date] = AsOf,
                   by: Literal["environment", "quadrant", "all"] = "environment") -> dict[str, Any]:
    return envelope(_call(evidence.evidence, as_of, setup, by))


@router.get("/research/analogs", response_model=m.Envelope[m.MarketAnalogRow])
def research_analogs(as_of: Optional[date] = AsOf) -> dict[str, Any]:
    return envelope(_call(research.analogs, as_of))


@router.get("/research/big-moves", response_model=m.Envelope[m.BigMoveRow])
def research_big_moves(as_of: Optional[date] = AsOf, min_mcap_cr: float = Query(1000.0, ge=0),
                       offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(research.big_moves, as_of, min_mcap_cr), offset, limit)


@router.get("/research/big-moves/{event_id}", response_model=m.Envelope[m.BigMoveRow])
def research_big_move(event_id: str = Path(..., max_length=80), as_of: Optional[date] = AsOf) -> dict[str, Any]:
    return envelope(_call(research.big_move, as_of, event_id))


@router.get("/research/pre-move", response_model=m.Envelope[m.PreMoveRow])
def research_pre_move(as_of: Optional[date] = AsOf, offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(research.pre_move, as_of), offset, limit)


@router.get("/research/group-studies", response_model=m.Envelope[m.GroupStudyRow])
def research_group_studies(as_of: Optional[date] = AsOf,
                           level: Literal["broad_sector", "sector", "broad_industry", "industry"] = "industry",
                           offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    return envelope(_call(research.group_studies, as_of, level), offset, limit)


# --------------------------------------------------------------------------
# Metric dictionary
# --------------------------------------------------------------------------
@router.get("/metrics/dictionary", response_model=m.Envelope[m.MetricEntry])
def metrics_dictionary(keys: Optional[str] = Query(None, max_length=4000, description="Comma-separated keys"),
                       offset: int = Offset, limit: int = Limit) -> dict[str, Any]:
    wanted = [k.strip() for k in keys.split(",") if k.strip()] if keys else None
    entries = metrics.entries(wanted)
    res = Result(as_of=None, rows=entries, sources=["Scripts/data/metric_dictionary.yaml"],
                 status="ok" if entries or wanted else "unavailable",
                 reason=None if entries or wanted else "metric dictionary missing or empty")
    return envelope(res, offset, limit, strict=False)


# --------------------------------------------------------------------------
# User data (user DB)
# --------------------------------------------------------------------------
def _user_call(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return fn(*args)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/watchlist", response_model=m.Envelope[m.WatchlistItem])
def watchlist_get() -> dict[str, Any]:
    return envelope(Result(as_of=None, rows=_user_call(user.get_watchlist), sources=["v2_watchlist"]), strict=False)


@router.put("/watchlist", response_model=m.Envelope[m.WatchlistItem])
def watchlist_put(body: m.WatchlistPut) -> dict[str, Any]:
    symbols = [symbol_param(s) for s in body.symbols]
    return envelope(Result(as_of=None, rows=_user_call(user.put_watchlist, symbols), sources=["v2_watchlist"]),
                    strict=False)


@router.get("/notes/{sym}", response_model=m.Envelope[m.Note])
def note_get(sym: str) -> dict[str, Any]:
    note = _user_call(user.get_note, symbol_param(sym))
    return envelope(Result(as_of=None, rows=[note] if note else [], sources=["v2_notes"]), strict=False)


@router.put("/notes/{sym}", response_model=m.Envelope[m.Note])
def note_put(sym: str, body: m.NotePut) -> dict[str, Any]:
    note = _user_call(user.put_note, symbol_param(sym), body.body)
    return envelope(Result(as_of=None, rows=[note] if note else [], sources=["v2_notes"]), strict=False)
