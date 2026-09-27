from __future__ import annotations

from App.services.market import shape_regime_row


def test_old_tables_fall_back_to_rule_level_evidence():
    row = shape_regime_row({"trade_date": "2026-09-25", "verdict": "Mixed"})
    assert row["verdict_evidence"] == "descriptive_only"
    assert "not as a trade filter" in row["verdict_evidence_note"]


def test_null_verdict_has_no_evidence_claim():
    row = shape_regime_row({"trade_date": "2020-01-02", "verdict": None})
    assert row["verdict_evidence"] is None and row["verdict_evidence_note"] is None


def test_served_columns_win():
    row = shape_regime_row({"trade_date": "2026-09-25", "verdict": "Weak",
                            "verdict_evidence": "validated", "verdict_evidence_note": "passes"})
    assert (row["verdict_evidence"], row["verdict_evidence_note"]) == ("validated", "passes")
    assert "verdict_evidence" not in row["inputs"]
