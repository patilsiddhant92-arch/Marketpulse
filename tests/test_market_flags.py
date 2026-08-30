from datetime import date

import duckdb

from App.market_flags import deal_when_map
from App.ui.number_format import format_cell


def test_deal_when_uses_calendar_lags(tmp_path):
    db = tmp_path / "m.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE deals (trade_date DATE, symbol TEXT, side TEXT, deal_value_cr DOUBLE)")
        con.executemany(
            "INSERT INTO deals VALUES (?, ?, ?, ?)",
            [
                (date(2026, 8, 28), "AAA", "BUY", 10),
                (date(2026, 8, 26), "AAA", "BUY", 8),
                (date(2026, 8, 18), "AAA", "BUY", 5),
                (date(2026, 8, 28), "BBB", "BUY", 3),
            ],
        )
    labels = deal_when_map(db)
    assert labels["AAA"] == "today · 2d ago · 10d ago"
    assert labels["BBB"] == "today"


def test_distance_format_is_plain_percent():
    assert format_cell("away_52w_high_pct", 2.0) == ("2.0%", "")
    assert format_cell("away_52w_high_pct", -2.0) == ("-2.0%", "")
