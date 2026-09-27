"""signal_ledger.price_scale_factor: signals written while prices are already adjusted
(backfill_decisions over history) must not be rescaled a second time by outcomes."""
from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from test_outcomes import _split_prices


def test_raw_scale_row_without_stamp_is_rescaled():
    """Old rows (NULL price_scale_factor) keep the historical behaviour: ledger on the raw
    scale of last_seen_date, multiplied by that date's price_factor (0.5)."""
    from Scripts.outcomes import _ledger_price_scale

    rows = _split_prices()
    aaa = rows[rows["symbol"] == "AAA"].assign(trade_date=lambda d: pd.to_datetime(d["trade_date"]))
    signal = {"last_seen_date": date(2026, 1, 2), "first_seen_date": date(2026, 1, 1), "price_scale_factor": None}
    assert _ledger_price_scale(aaa, signal) == 0.5


def test_adjusted_at_write_row_is_not_double_scaled():
    """Backfill wrote trigger/invalidation from adjusted indicators (factor 0.5 already applied
    at write time): the stamp cancels the rescale."""
    from Scripts.outcomes import _ledger_price_scale, calculate_outcome

    rows = _split_prices()
    aaa = rows[rows["symbol"] == "AAA"].assign(trade_date=lambda d: pd.to_datetime(d["trade_date"]))
    signal = {"signal_id": "s1", "symbol": "AAA", "first_seen_date": date(2026, 1, 1),
              "last_seen_date": date(2026, 1, 2), "trigger_price": 51.0, "invalidation_price": 47.5,
              "price_scale_factor": 0.5}
    assert _ledger_price_scale(aaa, signal) == 1.0
    result = calculate_outcome(rows, signal, horizons=(4,))[0]
    # same answer as the raw-scale signal (102 / 95 raw) in test_outcomes
    assert result["time_to_failure_sessions"] is None
    assert result["trigger_to_invalidation_return_pct"] == round((47.5 / 51.0 - 1) * 100, 6)


def test_later_split_after_adjusted_write_is_still_applied():
    """Stamp 0.5 at write; another 1:2 split later makes the factor on last_seen_date 0.25:
    the remaining rescale is 0.25 / 0.5 = 0.5."""
    from Scripts.outcomes import _ledger_price_scale

    rows = _split_prices()
    aaa = rows[rows["symbol"] == "AAA"].assign(trade_date=lambda d: pd.to_datetime(d["trade_date"]))
    aaa = aaa.assign(price_factor=aaa["price_factor"] * 0.5)
    signal = {"last_seen_date": date(2026, 1, 2), "price_scale_factor": 0.5}
    assert _ledger_price_scale(aaa, signal) == 0.5


def test_stamp_uses_price_factor_of_last_seen_session():
    from Scripts.signal_service import stamp_price_scale

    indicators = pd.DataFrame({
        "symbol": ["AAA", "AAA", "BBB"],
        "trade_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-02"]),
        "price_factor": [0.5, 0.5, 1.0],
    })
    ledger = pd.DataFrame([
        {"signal_id": "a", "symbol": "AAA", "last_seen_date": date(2026, 1, 2)},
        {"signal_id": "b", "symbol": "BBB", "last_seen_date": date(2026, 1, 2)},
        {"signal_id": "old", "symbol": "AAA", "last_seen_date": date(2025, 12, 1), "price_scale_factor": 0.8},
        {"signal_id": "nopf", "symbol": "CCC", "last_seen_date": date(2026, 1, 2)},
    ])
    out = stamp_price_scale(ledger, indicators, date(2026, 1, 2)).set_index("signal_id")["price_scale_factor"]
    assert out["a"] == 0.5 and out["b"] == 1.0
    assert out["old"] == 0.8  # untouched: not seen this session
    assert out["nopf"] == 1.0  # no indicator row -> raw scale


def test_stamp_without_price_factor_column_is_raw():
    from Scripts.signal_service import stamp_price_scale

    indicators = pd.DataFrame({"symbol": ["AAA"], "trade_date": pd.to_datetime(["2026-01-02"])})
    ledger = pd.DataFrame([{"signal_id": "a", "symbol": "AAA", "last_seen_date": date(2026, 1, 2)}])
    assert stamp_price_scale(ledger, indicators, date(2026, 1, 2))["price_scale_factor"].tolist() == [1.0]


def test_migration_adds_price_scale_factor_to_existing_ledger(tmp_path):
    from Scripts.migrations import run_migrations

    path = tmp_path / "marketpulse.duckdb"
    run_migrations(path)
    with duckdb.connect(str(path)) as db:
        cols = {r[1] for r in db.execute("PRAGMA table_info(signal_ledger)").fetchall()}
        assert "price_scale_factor" in cols
        # simulate a CTAS-copied legacy ledger without the column
        db.execute("DROP TABLE signal_ledger")
        db.execute("CREATE TABLE signal_ledger AS SELECT 'x' AS signal_id, 1.0 AS trigger_price")
    run_migrations(path)
    with duckdb.connect(str(path), read_only=True) as db:
        cols = {r[1] for r in db.execute("PRAGMA table_info(signal_ledger)").fetchall()}
        assert "price_scale_factor" in cols
        assert db.execute("SELECT price_scale_factor FROM signal_ledger").fetchone()[0] is None


def test_write_ledger_persists_and_updates_scale(tmp_path):
    import Scripts.materialize_decision_tables as mdt
    from Scripts.migrations import run_migrations

    path = tmp_path / "marketpulse.duckdb"
    run_migrations(path)
    base = {"signal_id": "s1", "symbol": "AAA", "setup_type": "focused_setup", "score_version": "v",
            "first_seen_date": date(2026, 1, 1), "last_seen_date": date(2026, 1, 2), "status": "observe",
            "trigger_price": 51.0, "invalidation_price": 47.5, "price_scale_factor": 0.5}
    mdt._write_ledger(path, pd.DataFrame([base]))
    mdt._write_ledger(path, pd.DataFrame([{**base, "last_seen_date": date(2026, 1, 5), "price_scale_factor": 1.0}]))
    with duckdb.connect(str(path), read_only=True) as db:
        assert db.execute("SELECT price_scale_factor, last_seen_date FROM signal_ledger").fetchone() == (1.0, date(2026, 1, 5))
