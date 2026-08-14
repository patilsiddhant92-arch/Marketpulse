from __future__ import annotations

from pathlib import Path


def test_today_page_has_no_prep_score_sql_on_default_path():
    """PR-TODAY-IA: default open must not run dual-ranking prep_score SQL."""
    text = Path("App/app.py").read_text(encoding="utf-8")
    start = text.index("def today_page() -> None:")
    end = text.index("def candidates_page() -> None:")
    body = text[start:end]
    # Mentions of prep_score only allowed in comments / LEGACY messaging, not SQL.
    assert "AS prep_score" not in body
    assert "ORDER BY prep_score" not in body
    assert "build_today_page" in body
    assert "Market context" in body
    assert "near_entry" not in body.lower() or "MP_TODAY_LEGACY" in body


def test_decision_preset_is_at_most_ten_columns():
    from App.candidates_page import DECISION_PRESET_COLUMNS

    assert len(DECISION_PRESET_COLUMNS) <= 10
    assert DECISION_PRESET_COLUMNS[0] == "symbol"
    assert "candidate_state" in DECISION_PRESET_COLUMNS
    assert "warning_reasons" not in DECISION_PRESET_COLUMNS


def test_friendly_columns_cover_decision_preset():
    from Scripts.config import FRIENDLY_COLUMNS
    from App.candidates_page import DECISION_PRESET_COLUMNS

    for col in DECISION_PRESET_COLUMNS:
        assert col in FRIENDLY_COLUMNS, f"missing FRIENDLY for {col}"
