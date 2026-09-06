"""Tests for the Market Info Desk, Macro Playbook, Chronological Timeline, and Case Studies."""
from pathlib import Path
import pytest

from App.pages.info_page import (
    MACRO_PLAYBOOK_CARDS,
    CHRONOLOGY_STAGES,
    CASE_STUDIES,
    build_info_page,
)


def test_macro_playbook_cards_coverage():
    """Verify that all required macroeconomic assets are covered with plain language rules."""
    titles = [card["title"] for card in MACRO_PLAYBOOK_CARDS]
    
    assert any("Crude Oil" in t for t in titles), "Crude Oil missing from Playbook"
    assert any("Silver" in t for t in titles), "Silver missing from Playbook"
    assert any("Gold" in t for t in titles), "Gold missing from Playbook"
    assert any("Copper" in t for t in titles), "Copper missing from Playbook"
    assert any("Natural Gas" in t for t in titles), "Natural Gas missing from Playbook"
    assert any("US 10Y" in t or "Dollar" in t for t in titles), "US 10Y / Dollar missing from Playbook"
    assert any("Bitcoin" in t or "Crypto" in t for t in titles), "Bitcoin / Crypto missing from Playbook"

    # Check that each card has non-empty simple rule and stock tickers
    for card in MACRO_PLAYBOOK_CARDS:
        assert len(card["simple_rule"]) > 20
        all_stocks = card["when_drops_stocks"] + card["when_rises_stocks"]
        assert len(all_stocks) > 0, f"Card {card['title']} has no stock tickers"
        for sym, reason in all_stocks:
            assert sym.isupper()
            assert len(reason) > 5


def test_chronology_stages_sequence():
    """Verify that the 5 chronological stages form a logical progression in time."""
    assert len(CHRONOLOGY_STAGES) == 5
    
    expected_stages = ["Stage 1", "Stage 2", "Stage 3", "Stage 4", "Stage 5"]
    actual_stages = [item["stage"] for item in CHRONOLOGY_STAGES]
    assert actual_stages == expected_stages

    # Verify Stage 1 is the fast reaction
    assert "Fast Movers" in CHRONOLOGY_STAGES[0]["label"] or "Spark" in CHRONOLOGY_STAGES[0]["label"]
    
    # Verify Stage 3 is the currency / RBI intervention
    assert "Currency" in CHRONOLOGY_STAGES[2]["label"] or "RBI" in CHRONOLOGY_STAGES[2]["label"]

    # Verify Stage 4 is Indian equity sector rotation
    assert "Sector Rotation" in CHRONOLOGY_STAGES[3]["label"] or "Equity" in CHRONOLOGY_STAGES[3]["label"]

    # Verify Stage 5 is quarterly earnings
    assert "Earnings" in CHRONOLOGY_STAGES[4]["label"]

    for stage in CHRONOLOGY_STAGES:
        assert len(stage["reaction_points"]) >= 2


def test_case_studies_integrity():
    """Verify that the real-world case studies have concrete historical contexts."""
    assert len(CASE_STUDIES) >= 4

    titles = [c["title"] for c in CASE_STUDIES]
    assert any("Asian Paints" in t for t in titles), "Asian Paints case study missing"
    assert any("Hindustan Zinc" in t for t in titles), "Hindustan Zinc case study missing"
    assert any("Muthoot Finance" in t for t in titles), "Muthoot Finance case study missing"
    assert any("Bitcoin" in t for t in titles), "Bitcoin case study missing"

    for case in CASE_STUDIES:
        assert len(case["summary"]) > 20
        assert len(case["the_mechanism"]) > 20
        assert len(case["the_stock_result"]) > 20
        assert len(case["takeaway"]) > 20
