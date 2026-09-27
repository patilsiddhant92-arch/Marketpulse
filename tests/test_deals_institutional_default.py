"""Deals desk opens institutional-first (PROP/HFT hidden by default)."""
from pathlib import Path


def test_deals_page_defaults_exclude_hft_true():
    src = Path("App/pages/research/deals.py").read_text(encoding="utf-8")
    assert 'hft_state = {"exclude_hft": True}' in src
    assert "Institutional only" in src
