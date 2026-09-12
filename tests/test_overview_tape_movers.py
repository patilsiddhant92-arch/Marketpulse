"""Unit tests for Overview Page Tape Movers."""
from pathlib import Path
import pytest
from nicegui import ui
from App.pages.overview import build_overview_page

DB_PATH = Path("Database/marketpulse.duckdb")


def test_overview_page_builds_with_tape_movers():
    if not DB_PATH.exists():
        pytest.skip("MarketPulse DuckDB not found.")

    rendered_tables = []

    def mock_table_from_df(df, title, **kwargs):
        rendered_tables.append((title, len(df)))
        return None

    def dummy_copy(*args, **kwargs):
        pass

    with ui.column():
        build_overview_page(
            DB_PATH,
            copy_text=dummy_copy,
            table_from_df=mock_table_from_df,
        )

    # Verify that the tape mover tables were built
    titles = [t[0] for t in rendered_tables]
    assert "Top Gainers (Up)" in titles
    assert "Top Losers (Down)" in titles
    assert "Volume Shock Leaders (Top RVOL)" in titles
    assert "Cash Turnover Leaders (Today / 1W / 1M)" in titles
    assert "Near 52-Week High (Within 5%)" in titles
