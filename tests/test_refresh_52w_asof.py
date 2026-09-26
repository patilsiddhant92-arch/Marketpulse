"""refresh_52w_asof must put NSE's 52W values on the same (adjusted) scale as close_price."""
from __future__ import annotations

import math

import duckdb
import pandas as pd
import pytest

import refresh_52w_asof as r52


def _make_db(path, with_factor: bool) -> None:
    # AAA: a 1:5 split goes ex on 2026-08-05. Adjusted closes are ~100 throughout; the
    # pre-split rows carry price_factor 0.2 (raw close ~500).
    rows = pd.DataFrame({
        "symbol": ["AAA"] * 4,
        "trade_date": pd.to_datetime(["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"]),
        "close_price": [100.0, 101.0, 102.0, 103.0],
        "high_252d": [110.0] * 4,
        "low_252d": [80.0] * 4,
        "high_52w": [float("nan")] * 4,
        "low_52w": [float("nan")] * 4,
        "away_52w_high_pct": [float("nan")] * 4,
        "away_52w_low_pct": [float("nan")] * 4,
    })
    if with_factor:
        rows["price_factor"] = [0.2, 0.2, 1.0, 1.0]
    with duckdb.connect(str(path)) as con:
        con.register("rows_df", rows)
        con.execute("CREATE TABLE indicators_daily AS SELECT * FROM rows_df")


def _reference() -> pd.DataFrame:
    # NSE snapshots: raw scale on their own file date (pre-split 600/400, post-split 120/80).
    return pd.DataFrame({
        "symbol": ["AAA", "AAA"],
        "effective_date": pd.to_datetime(["2026-08-03", "2026-08-05"]),
        "high_52w": [600.0, 120.0],
        "low_52w": [400.0, 80.0],
    })


def _run(tmp_path, monkeypatch, with_factor: bool) -> pd.DataFrame:
    db = tmp_path / "marketpulse.duckdb"
    _make_db(db, with_factor)
    monkeypatch.setattr(r52, "DB_PATH", db)
    monkeypatch.setattr(r52, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(r52, "load_reference_history", lambda root: _reference())
    assert r52.main() == 0
    with duckdb.connect(str(db), read_only=True) as con:
        return con.execute(
            "SELECT trade_date, high_52w, low_52w, away_52w_high_pct FROM indicators_daily ORDER BY trade_date"
        ).fetchdf()


def test_refresh_rescales_nse_52w_by_price_factor(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, with_factor=True)

    # Pre-split rows: 600 * 0.2 = 120, 400 * 0.2 = 80; post-split rows unchanged.
    assert out["high_52w"].tolist() == pytest.approx([120.0, 120.0, 120.0, 120.0])
    assert out["low_52w"].tolist() == pytest.approx([80.0, 80.0, 80.0, 80.0])
    # Scale-invariant: 100 adjusted vs 120 adjusted == 500 raw vs 600 raw.
    assert math.isclose(out.loc[0, "away_52w_high_pct"], (100.0 / 120.0 - 1) * 100, rel_tol=1e-9)


def test_refresh_without_price_factor_column_uses_raw_values(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, with_factor=False)

    assert out["high_52w"].tolist() == pytest.approx([600.0, 600.0, 120.0, 120.0])
