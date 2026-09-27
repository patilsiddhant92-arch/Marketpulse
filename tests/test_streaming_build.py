"""Streaming (symbol-batch) indicators == the in-memory calc_indicators, bit for bit."""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import pytest

import build_database as bd
import streaming_build as sb
from price_adjustment import apply_adjustments, empty_adjustments_frame, indicator_input


def synthetic_prices(n_symbols: int = 7, n_days: int = 420, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_days)
    frames = []
    for i in range(n_symbols):
        start = 0 if i % 3 else 150  # some symbols list later (short histories)
        d = dates[start:]
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, len(d))))
        high = close * (1 + rng.uniform(0, 0.03, len(d)))
        low = close * (1 - rng.uniform(0, 0.03, len(d)))
        open_ = low + (high - low) * rng.uniform(0, 1, len(d))
        vol = rng.integers(1_000, 100_000, len(d))
        frames.append(pd.DataFrame({
            "symbol": f"S{i:02d}", "series": "EQ", "trade_date": d.astype("datetime64[us]"),
            "prev_close": np.r_[np.nan, close[:-1]], "open_price": open_, "high_price": high, "low_price": low,
            "last_price": close, "close_price": close, "avg_price": (high + low) / 2, "volume": vol,
            "turnover_lacs": close * vol / 1e5, "trades": rng.integers(10, 1000, len(d)),
            "delivery_qty": (vol * 0.4).astype(float), "delivery_pct": 40.0, "turnover_cr": close * vol / 1e7,
        }))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture()
def inputs():
    prices = apply_adjustments(synthetic_prices(), empty_adjustments_frame())
    enrichment = pd.DataFrame({"symbol": prices["symbol"].unique(), "high_52w": np.nan, "low_52w": np.nan})
    return prices, enrichment


def test_streaming_indicators_equal_in_memory(tmp_path, monkeypatch, inputs):
    monkeypatch.setenv("MP_DISABLE_MULTIPROCESSING", "1")
    prices, enrichment = inputs
    no_index = pd.DataFrame(columns=["index_name", "trade_date", "close_price"])
    no_membership = RuntimeError("no membership in tests")
    expected = bd.calc_indicators(indicator_input(prices), enrichment, index_raw=no_index, membership=no_membership, quiet=True)

    con = sb.connect_build_db(tmp_path / "stage.duckdb")
    con.register("p", prices)
    con.execute("CREATE TABLE prices_daily AS SELECT * FROM p")
    con.unregister("p")
    rows = sb.stream_full_indicators(
        con, reference=None, enrichment=enrichment, index_raw=no_index, membership=no_membership,
        date_dtype=prices["trade_date"].dtype, batch_rows=900,
    )
    con.register("e", expected)
    con.execute("CREATE TABLE expected AS SELECT * FROM e")
    assert rows == len(expected)
    a = con.execute("SELECT column_name, data_type FROM duckdb_columns() WHERE table_name='indicators_daily' ORDER BY column_index").fetchall()
    b = con.execute("SELECT column_name, data_type FROM duckdb_columns() WHERE table_name='expected' ORDER BY column_index").fetchall()
    assert a == b
    assert con.execute("SELECT count(*) FROM (SELECT * FROM indicators_daily EXCEPT ALL SELECT * FROM expected)").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM (SELECT * FROM expected EXCEPT ALL SELECT * FROM indicators_daily)").fetchone()[0] == 0
    con.close()


def test_windowed_daily_features_match_full_history(inputs):
    """The incremental append computes the kept rows on a trailing window + full history."""
    prices, _ = inputs
    ii = indicator_input(prices)
    g = ii[ii["symbol"] == "S01"].reset_index(drop=True)
    full = bd._calc_single_symbol_indicators(g)
    keep_from = g["trade_date"].iloc[-25]
    first_kept = int(np.flatnonzero(g["trade_date"] >= keep_from)[0])
    window = g.iloc[first_kept - bd.DAILY_LOOKBACK_ROWS:]
    daily = bd._daily_symbol_features(window, history=g)
    daily = daily[daily["trade_date"] >= keep_from]
    part = bd._higher_timeframe_features(daily, g).reset_index(drop=True)
    ref = full[full["trade_date"] >= keep_from].reset_index(drop=True)
    assert list(part.columns) == list(ref.columns)
    for col in ref.columns:
        a, b = ref[col], part[col]
        if pd.api.types.is_float_dtype(a):
            np.testing.assert_allclose(b.to_numpy(float), a.to_numpy(float), rtol=1e-9, atol=1e-12, equal_nan=True, err_msg=col)
        else:
            # object-vs-bool dtype can differ (a bool column with NaN before the first weekly bar
            # is object in the full frame); DuckDB stores both as BOOLEAN - compare values.
            assert [None if pd.isna(x) else x for x in a.astype(object)] == [None if pd.isna(x) else x for x in b.astype(object)], col


def test_build_temp_database_adopts_staged_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "load_all_index_history", lambda root: pd.DataFrame())
    monkeypatch.setattr(bd, "load_reference_history", lambda root: pd.DataFrame())
    db = tmp_path / "marketpulse.duckdb"
    stage = sb.stage_db_path(db)
    with duckdb.connect(str(stage)) as con:
        con.execute("CREATE TABLE prices_daily AS SELECT 'AAA' AS symbol, TIMESTAMP '2026-09-25' AS trade_date, 1.0 AS close_price")
        con.execute("CREATE TABLE indicators_daily AS SELECT 'AAA' AS symbol, TIMESTAMP '2026-09-25' AS trade_date, 1.0 AS close_price")
    small = pd.DataFrame({"symbol": ["AAA"], "trade_date": [pd.Timestamp("2026-09-25")]})
    temp = bd.build_temp_database(
        sb.StagedTable(stage, "prices_daily", 1), pd.DataFrame({"symbol": ["AAA"]}), pd.DataFrame({"symbol": ["AAA"]}),
        sb.StagedTable(stage, "indicators_daily", 1), small.assign(side="BUY"), pd.DataFrame({"trade_date": small["trade_date"]}),
        pd.DataFrame({"level": ["s"], "group_name": ["g"], "trade_date": small["trade_date"]}),
        pd.DataFrame({"screener_name": ["x"], "symbol": ["AAA"]}), db_path=db,
    )
    assert not stage.exists()
    with duckdb.connect(str(temp), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM prices_daily").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM indicators_daily").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM stocks_master").fetchone()[0] == 1


def test_build_prices_batched_dedupe_keeps_last_file(tmp_path, monkeypatch):
    """Collapsing duplicates every BHAV_DEDUPE_BATCH files still lets the last file win."""
    import config

    archive = tmp_path / "archive"
    daily = tmp_path / "daily"
    archive.mkdir()
    daily.mkdir()
    head = "SYMBOL,SERIES,DATE1,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY,DELIV_PER\n"
    for i in range(5):
        day = pd.Timestamp("2026-09-01") + pd.Timedelta(days=i)
        for folder, px in ((archive, 10.0 + i), (daily, 20.0 + i)):
            (folder / f"sec_bhavdata_full_{day:%d%m%Y}.csv").write_text(
                head + f"AAA,EQ,{day:%d-%b-%Y},1,1,1,1,1,{px},1,100,1,1,1,1\n", encoding="utf-8"
            )
    monkeypatch.setattr(bd, "ARCHIVE_DIR", archive)
    monkeypatch.setattr(bd, "DAILY_DIR", daily)
    monkeypatch.setattr(bd, "INPUT_DIR", tmp_path)
    monkeypatch.setattr(bd, "BHAV_DEDUPE_BATCH", 2)
    monkeypatch.setattr(bd, "apply_reference_symbol_changes", lambda p: p)
    out = bd.build_prices(None)
    # sorted paths: archive/... < daily/..., so the daily copy (20+i) is the last file per session
    assert out["close_price"].tolist() == [20.0, 21.0, 22.0, 23.0, 24.0]
