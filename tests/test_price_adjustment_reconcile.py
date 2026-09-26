from __future__ import annotations

import math

import pandas as pd

from price_adjustment import gap_candidates, load_overrides, reconcile


def _a(sym, d, kind, factor, source):
    return {"symbol": sym, "ex_date": pd.Timestamp(d), "kind": kind, "factor": factor, "description": kind, "source": source}


def test_gap_candidates():
    p = pd.DataFrame({"symbol": ["G"] * 3 + ["X"] * 2,
                      "trade_date": pd.to_datetime(["2026-08-19", "2026-08-20", "2026-08-21", "2026-08-20", "2026-08-21"]),
                      "close_price": [1363.3, 1439.4, 490.9, 100.0, 104.0]})
    g = gap_candidates(p)
    assert g["symbol"].tolist() == ["G"] and math.isclose(g["gap_ratio"].iloc[0], 490.9 / 1439.4)


def test_reconcile_confirms_and_merges_sources():
    bc = pd.DataFrame([_a("GOODLUCK", "2026-08-21", "bonus", 1 / 3, "bc"),
                       _a("SIYSIL", "2026-08-21", "pref_bonus", None, "bc")])
    mcap = pd.DataFrame([_a("GOODLUCK", "2026-08-21", "bonus", 1 / 3, "mcap_issue"),
                         _a("KIRLPNU", "2026-08-18", "split", 0.5, "mcap_fv")])
    gaps = pd.DataFrame({"symbol": ["GOODLUCK", "HEG"], "ex_date": pd.to_datetime(["2026-08-21", "2026-09-01"]),
                         "gap_ratio": [490.9 / 1439.4, 0.33]})
    out = reconcile(bc, mcap, gaps, pd.DataFrame()).set_index("symbol")
    g = out.loc["GOODLUCK"]
    assert g["applied"] and g["confidence"] == "confirmed" and g["source"] == "bc+mcap_issue" and math.isclose(g["factor"], 1 / 3)
    assert out.loc["KIRLPNU", "applied"] and out.loc["KIRLPNU", "source"] == "mcap_fv"
    assert not out.loc["SIYSIL", "applied"] and out.loc["SIYSIL", "confidence"] == "not_adjusting"
    assert out.loc["HEG", "kind"] == "unexplained_gap" and not out.loc["HEG", "applied"]


def test_overrides_suppress_and_add(tmp_path):
    y = tmp_path / "o.yaml"
    y.write_text("- {symbol: KIRLPNU, ex_date: 2026-08-18, factor: null, note: wrong}\n"
                 "- {symbol: NEWCO, ex_date: 2021-01-04, factor: 0.5, note: manual}\n")
    ov = load_overrides(y)
    mcap = pd.DataFrame([_a("KIRLPNU", "2026-08-18", "split", 0.5, "mcap_fv")])
    out = reconcile(pd.DataFrame(), mcap, pd.DataFrame(), ov).set_index("symbol")
    assert not out.loc["KIRLPNU", "applied"] and out.loc["KIRLPNU", "confidence"] == "suppressed"
    assert out.loc["NEWCO", "applied"] and out.loc["NEWCO", "source"] == "override"
    assert load_overrides(tmp_path / "missing.yaml").empty


def test_mcap_issue_bonus_conflicts_with_bc_rights():
    bc = pd.DataFrame([_a("MPEL", "2026-08-31", "rights", None, "bc")])
    bc.loc[0, "description"] = "RIGHTS 2:1 @ PRM RS 6/-"
    mcap = pd.DataFrame([_a("MPEL", "2026-08-31", "bonus", 1 / 3, "mcap_issue")])
    gaps = pd.DataFrame({"symbol": ["MPEL"], "ex_date": pd.to_datetime(["2026-08-31"]), "gap_ratio": [0.34]})
    out = reconcile(bc, mcap, gaps, pd.DataFrame())
    row = out[(out["symbol"] == "MPEL") & (out["source"] == "mcap_issue")].iloc[0]
    assert not row["applied"] and row["confidence"] == "rights_conflict"


def test_mcap_issue_bonus_unconfirmed_without_evidence():
    mcap = pd.DataFrame([_a("ONDOOR", "2026-07-31", "bonus", 0.8, "mcap_issue")])
    out = reconcile(pd.DataFrame(), mcap, pd.DataFrame(), pd.DataFrame()).set_index("symbol")
    assert not out.loc["ONDOOR", "applied"] and out.loc["ONDOOR", "confidence"] == "unconfirmed"


def test_mcap_issue_bonus_confirmed_by_gap_without_bc():
    mcap = pd.DataFrame([_a("XYZ", "2026-07-31", "bonus", 0.5, "mcap_issue")])
    gaps = pd.DataFrame({"symbol": ["XYZ"], "ex_date": pd.to_datetime(["2026-07-31"]), "gap_ratio": [0.51]})
    out = reconcile(pd.DataFrame(), mcap, gaps, pd.DataFrame()).set_index("symbol")
    row = out.loc["XYZ"]
    assert row["applied"] and row["confidence"] == "confirmed" and row["source"] == "mcap_issue"
