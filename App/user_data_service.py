"""Validated portfolio commands backed only by the isolated user database."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

import duckdb

try:
    from Scripts.user_data import initialize_user_db
except ModuleNotFoundError:  # App/app.py adds Scripts/ directly when run as a script.
    from user_data import initialize_user_db


ENTRY_DEVIATION_LIMIT = 0.20
DEFAULT_ACCOUNT_EQUITY = 100_000.0
DEFAULT_MAX_RISK_PCT = 1.0


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    close_price: float | None = None
    ema_20: float | None = None
    ema_50: float | None = None
    rs_percentile: float | None = None
    sector: str = ""
    industry: str = ""
    event_risk: str = "none"
    corporate_action_warning: str = ""


@dataclass(frozen=True)
class PositionCommand:
    symbol: str
    quantity: float
    entry_price: float
    buy_date: date
    stop_price: float
    target_price: float
    thesis: str = ""
    setup_type: str = ""
    invalidation_note: str = ""
    notes: str = ""
    tags: str = ""
    planned_risk_inr: float | None = None
    max_risk_pct: float | None = None
    confirm_entry_deviation: bool = False
    confirm_corporate_action: bool = False


@dataclass(frozen=True)
class ExitCommand:
    symbol: str
    sell_price: float
    sell_date: date
    notes: str = ""


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    requires_confirmation: bool = False


@dataclass(frozen=True)
class Position:
    symbol: str
    status: str
    quantity: float
    entry_price: float
    buy_date: date
    stop_price: float
    target_price: float
    sell_date: date | None = None
    sell_price: float | None = None
    thesis: str = ""
    setup_type: str = ""
    invalidation_note: str = ""
    planned_risk_inr: float | None = None
    max_risk_pct: float | None = None
    notes: str = ""
    tags: str = ""


@dataclass(frozen=True)
class PositionRisk:
    initial_risk_inr: float
    initial_risk_pct: float
    current_open_risk_inr: float
    current_open_risk_pct: float
    r_multiple: float
    portfolio_weight_pct: float
    stop_distance_pct: float
    target_distance_pct: float
    unrealized_pnl_inr: float
    action_state: str = "Monitor"


@dataclass(frozen=True)
class PortfolioReadModel:
    open_positions: list[dict[str, Any]]
    sold_positions: list[dict[str, Any]]
    total_open_risk_inr: float
    total_open_risk_pct: float
    total_weight_pct: float
    account_equity: float
    max_risk_pct: float
    as_of: date | None = None
    warnings: list[str] | None = None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _snapshot(value: MarketSnapshot | Mapping[str, Any]) -> MarketSnapshot:
    if isinstance(value, MarketSnapshot):
        return value
    allowed = {field.name for field in fields(MarketSnapshot)}
    data = {key: value.get(key) for key in allowed if key in value}
    data.setdefault("symbol", str(value.get("symbol") or ""))
    return MarketSnapshot(**data)


def validate_position(command: PositionCommand, latest: MarketSnapshot | Mapping[str, Any], *, today: date | None = None) -> ValidationResult:
    snapshot = _snapshot(latest)
    errors: list[str] = []
    warnings: list[str] = []
    requires_confirmation = False
    symbol = str(command.symbol or "").strip().upper()
    if not symbol:
        errors.append("symbol is required")
    elif symbol != str(snapshot.symbol or "").strip().upper():
        errors.append(f"unknown symbol: {symbol}")
    quantity = _finite(command.quantity)
    entry = _finite(command.entry_price)
    stop = _finite(command.stop_price)
    target = _finite(command.target_price)
    if quantity is None or quantity <= 0:
        errors.append("quantity must be greater than zero")
    if entry is None or entry <= 0:
        errors.append("entry price must be greater than zero")
    if stop is None or stop <= 0:
        errors.append("stop price must be greater than zero")
    if target is None or target <= 0:
        errors.append("target price must be greater than zero")
    if entry is not None and stop is not None and stop >= entry:
        errors.append("stop price must be below entry price")
    if entry is not None and target is not None and target <= entry:
        errors.append("target price must be above entry price")
    buy_date = _as_date(command.buy_date)
    reference_day = today or date.today()
    if buy_date is None:
        errors.append("buy date is required")
    elif buy_date > reference_day:
        errors.append("buy date cannot be in the future")
    close = _finite(snapshot.close_price)
    if entry is not None and close and close > 0 and abs(entry - close) / close > ENTRY_DEVIATION_LIMIT:
        warnings.append("entry price differs materially from the latest market price")
        requires_confirmation = not command.confirm_entry_deviation
    if snapshot.corporate_action_warning:
        warnings.append(f"corporate-action reconciliation: {snapshot.corporate_action_warning}")
        requires_confirmation = requires_confirmation or not command.confirm_corporate_action
    return ValidationResult(not errors and not requires_confirmation, tuple(errors), tuple(warnings), requires_confirmation)


def _position_from_row(row: Mapping[str, Any]) -> Position:
    return Position(
        symbol=str(row.get("symbol") or ""),
        status=str(row.get("status") or "OPEN"),
        quantity=float(row.get("qty") or 0),
        entry_price=float(row.get("avg_buy_price") or 0),
        buy_date=_as_date(row.get("buy_date")) or date.today(),
        stop_price=float(row.get("stop_price") or 0),
        target_price=float(row.get("target_price") or 0),
        sell_date=_as_date(row.get("sell_date")),
        sell_price=_finite(row.get("sell_price")),
        thesis=str(row.get("thesis") or ""),
        setup_type=str(row.get("setup_type") or ""),
        invalidation_note=str(row.get("invalidation_note") or ""),
        planned_risk_inr=_finite(row.get("planned_risk_inr")),
        max_risk_pct=_finite(row.get("max_risk_pct")),
        notes=str(row.get("notes") or ""),
        tags=str(row.get("tags") or ""),
    )


def _write_event(db: duckdb.DuckDBPyConnection, symbol: str, event_type: str, event_date: date, qty: float | None, price: float | None, notes: str = "") -> None:
    event_id = int(db.execute("SELECT coalesce(max(id), 0) + 1 FROM portfolio_events").fetchone()[0])
    db.execute("INSERT INTO portfolio_events (id, symbol, event_type, event_date, qty, price, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, current_timestamp)", [event_id, symbol, event_type, event_date, qty, price, notes])


def upsert_position(user_db: Path, command: PositionCommand, latest: MarketSnapshot | Mapping[str, Any] | None = None) -> Position:
    if latest is not None:
        result = validate_position(command, latest)
        if not result.valid:
            raise ValueError("; ".join(result.errors or result.warnings or ("position is not valid",)))
    symbol = str(command.symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    initialize_user_db(user_db)
    with duckdb.connect(str(user_db)) as db:
        existing = int(db.execute("SELECT count(*) FROM portfolio_positions WHERE symbol = ?", [symbol]).fetchone()[0])
        event_type = "EDIT" if existing else "CREATE"
        values = [command.quantity, command.entry_price, command.buy_date, command.notes, command.tags, command.setup_type, command.stop_price, command.target_price, command.thesis, command.invalidation_note, command.planned_risk_inr, command.max_risk_pct, symbol]
        if existing:
            db.execute("UPDATE portfolio_positions SET status='OPEN', qty=?, avg_buy_price=?, buy_date=?, sell_date=NULL, sell_price=NULL, notes=?, tags=?, setup_type=?, stop_price=?, target_price=?, thesis=?, invalidation_note=?, planned_risk_inr=?, max_risk_pct=?, updated_at=current_timestamp WHERE symbol=?", values)
        else:
            db.execute("INSERT INTO portfolio_positions (symbol, status, qty, avg_buy_price, buy_date, sell_date, sell_price, notes, tags, setup_type, stop_price, target_price, thesis, invalidation_note, planned_risk_inr, max_risk_pct, created_at, updated_at) VALUES (?, 'OPEN', ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp, current_timestamp)", [symbol, *values[:-1]])
        _write_event(db, symbol, event_type, command.buy_date, command.quantity, command.entry_price, command.thesis)
        row = db.execute("SELECT * FROM portfolio_positions WHERE symbol = ?", [symbol]).fetchone()
        columns = [item[0] for item in db.description]
    return _position_from_row(dict(zip(columns, row)))


def mark_sold(user_db: Path, command: ExitCommand) -> Position:
    symbol = str(command.symbol or "").strip().upper()
    price = _finite(command.sell_price)
    sell_date = _as_date(command.sell_date)
    if not symbol:
        raise ValueError("selected symbol is required")
    if price is None or price <= 0:
        raise ValueError("sell price must be greater than zero")
    if sell_date is None or sell_date > date.today():
        raise ValueError("sell date cannot be in the future")
    initialize_user_db(user_db)
    with duckdb.connect(str(user_db)) as db:
        row = db.execute("SELECT * FROM portfolio_positions WHERE symbol = ?", [symbol]).fetchone()
        if row is None:
            raise ValueError(f"unknown position: {symbol}")
        db.execute("UPDATE portfolio_positions SET status='SOLD', sell_date=?, sell_price=?, updated_at=current_timestamp WHERE symbol=?", [sell_date, price, symbol])
        _write_event(db, symbol, "SELL", sell_date, row[2], price, command.notes)
        current = db.execute("SELECT * FROM portfolio_positions WHERE symbol = ?", [symbol]).fetchone()
        columns = [item[0] for item in db.description]
    return _position_from_row(dict(zip(columns, current)))


def reopen_position(user_db: Path, selected_symbol: str) -> Position:
    symbol = str(selected_symbol or "").strip().upper()
    if not symbol:
        raise ValueError("selected symbol is required")
    initialize_user_db(user_db)
    with duckdb.connect(str(user_db)) as db:
        row = db.execute("SELECT * FROM portfolio_positions WHERE symbol = ?", [symbol]).fetchone()
        if row is None:
            raise ValueError(f"unknown position: {symbol}")
        db.execute(
            "UPDATE portfolio_positions SET status='OPEN', sell_date=NULL, sell_price=NULL, updated_at=current_timestamp WHERE symbol=?",
            [symbol],
        )
        _write_event(db, symbol, "STATUS", date.today(), row[2], row[3], "position reopened")
        current = db.execute("SELECT * FROM portfolio_positions WHERE symbol = ?", [symbol]).fetchone()
        columns = [item[0] for item in db.description]
    return _position_from_row(dict(zip(columns, current)))


def delete_position(user_db: Path, selected_symbol: str | None, *, confirmed: bool = False) -> None:
    symbol = str(selected_symbol or "").strip().upper()
    if not symbol:
        raise ValueError("selected symbol is required")
    if not confirmed:
        raise ValueError("delete must be confirmed")
    initialize_user_db(user_db)
    with duckdb.connect(str(user_db)) as db:
        row = db.execute("SELECT qty, avg_buy_price, buy_date FROM portfolio_positions WHERE symbol = ?", [symbol]).fetchone()
        if row is None:
            raise ValueError(f"unknown position: {symbol}")
        _write_event(db, symbol, "DELETE", _as_date(row[2]) or date.today(), row[0], row[1], "position deleted by user")
        db.execute("DELETE FROM portfolio_positions WHERE symbol = ?", [symbol])


def calculate_position_risk(position: Position | PositionCommand, cmp: float, account_equity: float = DEFAULT_ACCOUNT_EQUITY) -> PositionRisk:
    qty = max(0.0, _finite(getattr(position, "quantity")) or 0.0)
    entry = max(0.0, _finite(getattr(position, "entry_price")) or 0.0)
    stop = max(0.0, _finite(getattr(position, "stop_price")) or 0.0)
    target = max(0.0, _finite(getattr(position, "target_price")) or 0.0)
    current = max(0.0, _finite(cmp) or 0.0)
    equity = max(1.0, _finite(account_equity) or DEFAULT_ACCOUNT_EQUITY)
    geometry = entry > stop > 0 and target > entry
    initial = max(0.0, (entry - stop) * qty) if geometry else 0.0
    open_risk = max(0.0, (current - stop) * qty) if geometry else 0.0
    return PositionRisk(initial, initial / equity * 100, open_risk, open_risk / equity * 100, (current - entry) / (entry - stop) if geometry else 0.0, (entry * qty) / equity * 100, (current - stop) / current * 100 if current and geometry else 0.0, (target - current) / current * 100 if current and geometry else 0.0, (current - entry) * qty, "Protect" if geometry and current <= stop else "Monitor")


__all__ = ["ExitCommand", "MarketSnapshot", "PortfolioReadModel", "Position", "PositionCommand", "PositionRisk", "ValidationResult", "calculate_position_risk", "delete_position", "mark_sold", "reopen_position", "upsert_position", "validate_position"]
