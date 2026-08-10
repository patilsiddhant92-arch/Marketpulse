from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pytest


def _command(**overrides):
    from App.user_data_service import PositionCommand

    values = {
        "symbol": "ACME",
        "quantity": 10,
        "entry_price": 100,
        "buy_date": date(2026, 8, 1),
        "stop_price": 95,
        "target_price": 115,
        "thesis": "breakout",
    }
    values.update(overrides)
    return PositionCommand(**values)


def test_position_validation_rejects_bad_geometry_and_future_date():
    from App.user_data_service import MarketSnapshot, validate_position

    snapshot = MarketSnapshot(symbol="ACME", close_price=101)
    bad = validate_position(_command(stop_price=100), snapshot, today=date(2026, 8, 10))
    future = validate_position(_command(buy_date=date(2026, 8, 11)), snapshot, today=date(2026, 8, 10))

    assert bad.valid is False
    assert "stop price must be below entry price" in bad.errors
    assert future.valid is False
    assert "buy date cannot be in the future" in future.errors


def test_portfolio_commands_write_event_history_and_require_delete_confirmation(tmp_path):
    from App.user_data_service import ExitCommand, MarketSnapshot, delete_position, mark_sold, upsert_position

    user = tmp_path / "marketpulse_user.duckdb"
    position = upsert_position(user, _command(), MarketSnapshot(symbol="ACME", close_price=101))
    assert position.symbol == "ACME"
    with pytest.raises(ValueError, match="confirmed"):
        delete_position(user, "ACME", confirmed=False)

    sold = mark_sold(user, ExitCommand("ACME", 110, date(2026, 8, 9), "target reached"))
    assert sold.status == "SOLD"
    delete_position(user, "ACME", confirmed=True)
    with duckdb.connect(str(user), read_only=True) as db:
        assert db.execute("SELECT count(*) FROM portfolio_positions").fetchone()[0] == 0
        events = db.execute("SELECT event_type FROM portfolio_events ORDER BY id").fetchall()
    assert [row[0] for row in events] == ["CREATE", "SELL", "DELETE"]
