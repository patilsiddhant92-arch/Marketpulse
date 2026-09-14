"""Star/quick_wl must toggle USER_DB_PATH, not market DB_PATH."""
from __future__ import annotations

from pathlib import Path

import duckdb

from Scripts.config import DB_PATH, USER_DB_PATH


def test_quick_watchlist_helper_uses_user_db_source():
    """Regression: app._quick_watchlist_toggle must call USER_DB_PATH."""
    src = Path("App/app.py").read_text(encoding="utf-8")
    assert "toggle_watchlist_symbol(USER_DB_PATH, 1, sym)" in src
    assert "toggle_watchlist_symbol(DB_PATH, 1, sym)" not in src


def test_toggle_on_user_db_adds_and_removes(tmp_path: Path):
    from App.ui.stock_drawer import is_in_watchlist, toggle_watchlist_symbol

    user = tmp_path / "marketpulse_user.duckdb"
    with duckdb.connect(str(user)) as db:
        db.execute(
            """
            CREATE TABLE portfolio_settings (
                setting_key VARCHAR PRIMARY KEY,
                setting_value VARCHAR,
                updated_at TIMESTAMP
            )
            """
        )
    sym = "STARTEST"
    assert toggle_watchlist_symbol(user, 1, sym) is True
    assert is_in_watchlist(user, 1, sym) is True
    assert toggle_watchlist_symbol(user, 1, sym) is False
    assert is_in_watchlist(user, 1, sym) is False
