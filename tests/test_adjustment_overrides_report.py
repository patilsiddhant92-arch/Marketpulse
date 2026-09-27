"""adjustment_overrides_report: read-only list of open (unconfirmed) gaps + commented YAML stub."""
from __future__ import annotations

import hashlib

import duckdb
import pandas as pd
import yaml

import adjustment_overrides_report as rep


def _prices():
    rows = []
    for d, c in [("2026-08-27", 500.0), ("2026-08-28", 510.0), ("2026-09-01", 102.0), ("2026-09-02", 104.0)]:
        rows.append({"symbol": "HEG", "series": "EQ", "trade_date": pd.Timestamp(d), "close_price": c,
                     "open_price": c, "high_price": c, "low_price": c, "prev_close": None})
    for d, c in [("2026-08-27", 100.0), ("2026-08-28", 101.0), ("2026-09-01", 102.0), ("2026-09-02", 103.0)]:
        rows.append({"symbol": "CALM", "series": "EQ", "trade_date": pd.Timestamp(d), "close_price": c,
                     "open_price": c, "high_price": c, "low_price": c, "prev_close": None})
    return pd.DataFrame(rows)


def _adjustments():
    return pd.DataFrame([
        {"symbol": "HEG", "ex_date": pd.Timestamp("2026-09-01"), "kind": "unexplained_gap", "factor": 0.2, "source": "gap",
         "confidence": "unconfirmed", "applied": False, "description": ""},
        {"symbol": "HEG", "ex_date": pd.Timestamp("2026-08-20"), "kind": "dividend", "factor": float("nan"), "source": "bc",
         "confidence": "not_adjusting", "applied": False, "description": "DIVIDEND RS 5"},
        {"symbol": "OLD", "ex_date": pd.Timestamp("2025-01-01"), "kind": "unexplained_gap", "factor": 0.5, "source": "gap+override",
         "confidence": "reviewed", "applied": False, "description": "reviewed"},
        {"symbol": "KIR", "ex_date": pd.Timestamp("2026-08-18"), "kind": "split", "factor": 0.5, "source": "mcap_fv",
         "confidence": "confirmed", "applied": True, "description": ""},
    ])


def _corp():
    return pd.DataFrame([{"symbol": "HEG", "ex_date": pd.Timestamp("2026-08-29"), "action_type": "split",
                          "description": "FV SPLIT RS 10 TO RS 2"}])


def test_report_lists_open_gaps_with_prices_and_nearest_action():
    out = rep.build_report(_prices(), _adjustments(), _corp(), window_days=30)
    assert list(out["symbol"]) == ["HEG"]  # reviewed / applied rows excluded
    row = out.iloc[0]
    assert row["ratio"] == 0.2 and row["prev_close"] == 510.0 and row["close"] == 102.0
    assert row["prev_date"] == pd.Timestamp("2026-08-28")
    assert "FV SPLIT RS 10 TO RS 2" in row["nearest_action"] and row["action_days_off"] == -3


def test_open_row_is_not_its_own_nearest_action():
    adj = _adjustments()
    adj.loc[len(adj)] = {"symbol": "ABC", "ex_date": pd.Timestamp("2025-06-30"), "kind": "bonus", "factor": 0.75,
                         "source": "mcap_issue", "confidence": "unconfirmed", "applied": False, "description": "ISSUE x1.33"}
    out = rep.build_report(_prices(), adj, _corp(), window_days=30).set_index("symbol")
    assert out.loc["ABC", "nearest_action"] == ""


def test_nearest_action_outside_window_is_blank():
    out = rep.build_report(_prices(), _adjustments(), _corp(), window_days=1)
    assert out.iloc[0]["nearest_action"] == ""


def test_yaml_stub_is_fully_commented_and_valid_when_uncommented():
    out = rep.build_report(_prices(), _adjustments(), _corp(), window_days=30)
    stub = rep.yaml_stub(out)
    lines = [ln for ln in stub.splitlines() if ln.strip()]
    assert lines and all(ln.lstrip().startswith("#") for ln in lines)
    entries = [ln.lstrip()[1:].strip() for ln in lines if ln.lstrip()[1:].strip().startswith("- {")]
    parsed = [yaml.safe_load(e)[0] for e in entries]
    kinds = {p.get("kind") for p in parsed}
    assert kinds == {None, "ignore", "demerger"}
    assert all(p["symbol"] == "HEG" and str(p["ex_date"]) == "2026-09-01" for p in parsed)


def _db(tmp_path):
    db = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(db)) as con:
        con.register("p", _prices())
        con.execute("CREATE TABLE prices_daily AS SELECT * FROM p")
        con.register("a", _adjustments())
        con.execute("CREATE TABLE price_adjustments AS SELECT * FROM a")
        con.register("c", _corp())
        con.execute("CREATE TABLE corporate_actions AS SELECT * FROM c")
    return db


def test_main_from_db_is_read_only(tmp_path, capsys):
    db = _db(tmp_path)
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    assert rep.main(["--db", str(db), "--root", str(tmp_path), "--from-db"]) == 0
    text = capsys.readouterr().out
    assert "HEG" in text and "FV SPLIT" in text and "# - {symbol: HEG" in text
    assert hashlib.sha256(db.read_bytes()).hexdigest() == digest
    assert not list(tmp_path.glob("*.wal"))


def test_main_recompute_finds_gap_without_pr_files(tmp_path, capsys):
    db = _db(tmp_path)
    with duckdb.connect(str(db)) as con:  # a split text near the gap would (correctly) explain it
        con.execute("DROP TABLE corporate_actions")
    assert rep.main(["--db", str(db), "--root", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert "HEG" in text and "2026-09-01" in text
    assert not (tmp_path / "Input").exists()  # no parse cache written
