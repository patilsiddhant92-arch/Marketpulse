from __future__ import annotations

from pathlib import Path

import pandas as pd

import append_database


def test_prefers_fresh_ma_history_over_stale_table(monkeypatch, tmp_path):
    fresh = pd.DataFrame({"trade_date": pd.to_datetime(["2026-09-24", "2026-09-25"]),
                          "index_name": ["Nifty 50", "Nifty 50"], "close": [1.0, 2.0]})
    stale = fresh.iloc[:1].copy()
    monkeypatch.setattr(append_database, "load_all_index_history", lambda root: fresh)
    monkeypatch.setattr(append_database, "build_index_features", lambda raw: raw)
    out = append_database.load_index_for_metrics(tmp_path, lambda name: stale)
    assert out["trade_date"].max() == pd.Timestamp("2026-09-25")


def test_falls_back_to_table_when_ma_build_fails(monkeypatch, tmp_path):
    stale = pd.DataFrame({"trade_date": pd.to_datetime(["2026-09-24"]), "index_name": ["Nifty 50"], "close": [1.0]})

    def boom(root):
        raise RuntimeError("no MA files")

    monkeypatch.setattr(append_database, "load_all_index_history", boom)
    out = append_database.load_index_for_metrics(tmp_path, lambda name: stale)
    assert len(out) == 1


def test_load_index_for_metrics_uses_merged_loader(monkeypatch, tmp_path):
    fresh = pd.DataFrame({"trade_date": pd.to_datetime(["2026-09-25"]), "index_name": ["Nifty 50"], "close_price": [2.0]})
    monkeypatch.setattr(append_database, "load_all_index_history", lambda root: fresh)
    monkeypatch.setattr(append_database, "build_index_features", lambda raw: raw)
    out = append_database.load_index_for_metrics(tmp_path, lambda name: pd.DataFrame())
    assert out["trade_date"].max() == pd.Timestamp("2026-09-25")
