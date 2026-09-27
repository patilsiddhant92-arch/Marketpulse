"""`kind: break` overrides: a symbol's history before the break is excluded from indicators (treated as
a new listing) while its raw rows stay in prices_daily, flagged `pre_break`."""
from __future__ import annotations

import math

import duckdb
import numpy as np
import pandas as pd
import pytest

import build_database as bd
import streaming_build as sb
from price_adjustment import (
    PRE_BREAK_COL, apply_adjustments, empty_adjustments_frame, indicator_input, load_overrides, reconcile,
    series_breaks, summarize_adjustments,
)
from test_streaming_build import synthetic_prices


def _gaps(*rows):
    return pd.DataFrame({"symbol": [r[0] for r in rows], "ex_date": pd.to_datetime([r[1] for r in rows]),
                         "gap_ratio": [r[2] for r in rows]})


def _load(tmp_path, text):
    y = tmp_path / "adjustments_override.yaml"
    y.write_text(text, encoding="utf-8")
    return load_overrides(y)


def _break_adj(symbol: str, day) -> pd.DataFrame:
    return pd.DataFrame([{"symbol": symbol, "ex_date": pd.Timestamp(day), "kind": "break", "factor": float("nan"),
                          "source": "override", "confidence": "override", "applied": False, "description": "relisting"}])


def test_break_kind_loads_and_turns_the_gap_into_a_break_row(tmp_path):
    ov = _load(tmp_path, "- {symbol: mbecl, ex_date: 2026-09-01, kind: Break, note: relisted after capital reduction}\n")
    assert ov["kind"].iloc[0] == "break" and ov["symbol"].iloc[0] == "MBECL"
    out = reconcile(pd.DataFrame(), pd.DataFrame(), _gaps(("MBECL", "2026-09-01", 68.39), ("ZZZ", "2026-03-03", 0.5)), ov)
    row = out[out["symbol"] == "MBECL"].iloc[0]
    assert row["kind"] == "break" and not row["applied"] and row["confidence"] == "override"
    assert math.isnan(row["factor"]) and row["ex_date"] == pd.Timestamp("2026-09-01")
    assert "68.39" in row["description"] and "capital reduction" in row["description"]
    assert "0 applied" in summarize_adjustments(out) and "1 unconfirmed gaps" in summarize_adjustments(out)
    assert series_breaks(out).to_dict() == {"MBECL": pd.Timestamp("2026-09-01")}


def test_break_without_a_gap_adds_a_row(tmp_path):
    ov = _load(tmp_path, "- {symbol: ABC, ex_date: 2026-05-04, kind: break}\n")
    out = reconcile(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), ov)
    assert len(out) == 1 and out.iloc[0]["kind"] == "break" and not out.iloc[0]["applied"]


def _prices() -> pd.DataFrame:
    days = pd.bdate_range("2026-08-24", periods=8)
    closes = [3.0, 3.1, 3.2, 3.27, 223.65, 234.8, 246.6, 258.9]
    return pd.DataFrame({
        "symbol": "MBECL", "series": "BE", "trade_date": days, "close_price": closes, "open_price": closes,
        "high_price": closes, "low_price": closes, "volume": 1000.0,
        "prev_close": [2.9, 3.0, 3.1, 3.2, 10.0, 223.65, 234.8, 246.6],
    })


def test_apply_adjustments_flags_pre_break_rows_and_restarts_prev_close():
    out = apply_adjustments(_prices(), _break_adj("MBECL", "2026-08-28"))
    assert out[PRE_BREAK_COL].tolist() == [True] * 4 + [False] * 4
    # the first row of the new series uses the exchange's previous close (new-listing rule), not 3.27
    assert out["adj_prev_close"].iloc[4] == 10.0 and out["adj_prev_close"].iloc[5] == 223.65
    assert out["adj_prev_close"].iloc[1] == 3.0  # the old series is unchanged
    plain = apply_adjustments(_prices(), empty_adjustments_frame())
    assert PRE_BREAK_COL not in plain.columns  # no breaks -> table schema unchanged


def test_indicator_input_drops_pre_break_history():
    ind = indicator_input(apply_adjustments(_prices(), _break_adj("MBECL", "2026-08-28")))
    assert PRE_BREAK_COL not in ind.columns
    assert ind["trade_date"].min() == pd.Timestamp("2026-08-28") and len(ind) == 4
    assert list(ind.index) == [0, 1, 2, 3]


def test_streaming_build_excludes_pre_break_rows_like_the_in_memory_build(tmp_path, monkeypatch):
    monkeypatch.setenv("MP_DISABLE_MULTIPROCESSING", "1")
    raw = synthetic_prices(n_symbols=4, n_days=320)
    brk = raw.loc[raw["symbol"] == "S01", "trade_date"].iloc[200]
    prices = apply_adjustments(raw, _break_adj("S01", brk))
    enrichment = pd.DataFrame({"symbol": prices["symbol"].unique(), "high_52w": np.nan, "low_52w": np.nan})
    no_index = pd.DataFrame(columns=["index_name", "trade_date", "close_price"])
    expected = bd.calc_indicators(indicator_input(prices), enrichment, index_raw=no_index,
                                  membership=RuntimeError("none"), quiet=True)
    con = sb.connect_build_db(tmp_path / "stage.duckdb")
    con.register("p", prices)
    con.execute("CREATE TABLE prices_daily AS SELECT * FROM p")
    con.unregister("p")
    assert sb.indicator_input_where(sb.table_columns(con, "prices_daily")) == 'NOT COALESCE("pre_break", FALSE)'
    rows = sb.stream_full_indicators(con, reference=None, enrichment=enrichment, index_raw=no_index,
                                     membership=RuntimeError("none"), date_dtype=prices["trade_date"].dtype,
                                     batch_rows=500)
    assert rows == len(expected) == len(prices) - 200
    first = con.execute("SELECT min(trade_date) FROM indicators_daily WHERE symbol = 'S01'").fetchone()[0]
    assert pd.Timestamp(first) == brk
    # raw history stays for reference
    assert con.execute("SELECT count(*) FROM prices_daily WHERE symbol = 'S01' AND pre_break").fetchone()[0] == 200
    con.register("e", expected)
    con.execute("CREATE TABLE expected AS SELECT * FROM e")
    assert con.execute("SELECT count(*) FROM (SELECT * FROM indicators_daily EXCEPT ALL SELECT * FROM expected)").fetchone()[0] == 0
    con.close()


def test_incremental_append_requires_full_recompute_when_breaks_change(tmp_path):
    from incremental_append import FullRecomputeRequired, _require_same_series_breaks

    con = duckdb.connect(str(tmp_path / "db.duckdb"))
    con.execute("CREATE TABLE prices_daily (symbol VARCHAR, trade_date TIMESTAMP, close_price DOUBLE)")
    con.execute("CREATE TABLE price_adjustments (symbol VARCHAR, ex_date TIMESTAMP, kind VARCHAR)")
    _require_same_series_breaks(con, empty_adjustments_frame())  # none before, none now: fine
    with pytest.raises(FullRecomputeRequired, match="changed"):
        _require_same_series_breaks(con, _break_adj("MBECL", "2026-09-01"))
    con.execute("INSERT INTO price_adjustments VALUES ('MBECL', TIMESTAMP '2026-09-01', 'break')")
    with pytest.raises(FullRecomputeRequired, match="pre_break"):
        _require_same_series_breaks(con, _break_adj("MBECL", "2026-09-01"))
    con.execute("ALTER TABLE prices_daily ADD COLUMN pre_break BOOLEAN")
    _require_same_series_breaks(con, _break_adj("MBECL", "2026-09-01"))
    con.close()
