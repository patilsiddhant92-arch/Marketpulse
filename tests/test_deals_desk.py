from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd


def _seed_deals_db(path: Path) -> None:
    with duckdb.connect(str(path)) as db:
        db.execute(
            "CREATE TABLE deals (trade_date DATE, symbol TEXT, side TEXT, client_name TEXT, deal_value_cr DOUBLE)"
        )
        db.execute(
            "CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, ema_200 DOUBLE, rs_percentile DOUBLE, away_52w_high_pct DOUBLE)"
        )
        db.execute(
            "CREATE TABLE stocks_master (symbol TEXT, market_cap_cr DOUBLE, sector TEXT, industry TEXT)"
        )
        # Latest session 2026-08-07
        rows = [
            ("2026-08-07", "AAA", "BUY", "Fund A", 50.0),
            ("2026-08-07", "AAA", "BUY", "Fund B", 30.0),
            ("2026-08-07", "BBB", "BUY", "Fund A", 20.0),
            ("2026-08-07", "CCC", "BUY", "Fund C", 10.0),  # fails structure (close < ema)
            ("2026-08-07", "DDD", "SELL", "Fund D", 5.0),
            ("2026-08-06", "EEE", "BUY", "Fund E", 100.0),  # prior session — not in TV
        ]
        db.executemany("INSERT INTO deals VALUES (?, ?, ?, ?, ?)", rows)
        db.executemany(
            "INSERT INTO indicators_daily VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("AAA", "2026-08-07", 110.0, 100.0, 90.0, -3.0),
                ("BBB", "2026-08-07", 105.0, 100.0, 80.0, -5.0),
                ("CCC", "2026-08-07", 90.0, 100.0, 50.0, -10.0),
                ("EEE", "2026-08-06", 120.0, 100.0, 95.0, -1.0),
            ],
        )
        db.executemany(
            "INSERT INTO stocks_master VALUES (?, ?, ?, ?)",
            [
                ("AAA", 2500.0, "Tech", "Software"),
                ("BBB", 1500.0, "Tech", "Software"),
                ("CCC", 2000.0, "Tech", "Software"),
                ("DDD", 3000.0, "Bank", "Private"),
                ("EEE", 5000.0, "Auto", "OEM"),
            ],
        )


def test_desk_default_query_budget_and_full_tv(tmp_path):
    from App.deals_read_model import query_deals_desk_default

    db = tmp_path / "marketpulse.duckdb"
    _seed_deals_db(db)
    desk = query_deals_desk_default(db, card_limit=12)

    assert desk.query_count <= 2
    assert desk.as_of == "2026-08-07"
    # CCC filtered by close < ema_200; EEE is prior session; DDD is SELL
    assert set(desk.symbols_for_tv) == {"AAA", "BBB"}
    assert desk.buy_count == 2
    assert desk.buy_count == len(desk.symbols_for_tv)
    assert "NSE:AAA" in desk.buy_tv
    assert "NSE:BBB" in desk.buy_tv
    assert "NSE:CCC" not in desk.buy_tv
    assert "NSE:EEE" not in desk.buy_tv
    # Cards are slice of full set, not a different universe
    assert len(desk.cards) <= 12
    assert set(desk.cards["symbol"].astype(str).str.upper()) <= set(desk.symbols_for_tv)
    # AAA has higher buy value (80) than BBB (20)
    assert desk.cards.iloc[0]["symbol"] == "AAA"
    assert not desk.flow.empty


def test_card_limit_does_not_truncate_tv(tmp_path):
    from App.deals_read_model import query_deals_desk_default

    db = tmp_path / "marketpulse.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute(
            "CREATE TABLE deals (trade_date DATE, symbol TEXT, side TEXT, client_name TEXT, deal_value_cr DOUBLE)"
        )
        con.execute(
            "CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, ema_200 DOUBLE, rs_percentile DOUBLE, away_52w_high_pct DOUBLE)"
        )
        con.execute(
            "CREATE TABLE stocks_master (symbol TEXT, market_cap_cr DOUBLE, sector TEXT, industry TEXT)"
        )
        for i in range(20):
            sym = f"S{i:02d}"
            con.execute(
                "INSERT INTO deals VALUES ('2026-08-07', ?, 'BUY', 'Fund', ?)",
                [sym, float(100 - i)],
            )
            con.execute(
                "INSERT INTO indicators_daily VALUES (?, '2026-08-07', 110, 100, 70, -2)",
                [sym],
            )
            con.execute(
                "INSERT INTO stocks_master VALUES (?, 2000, 'Tech', 'Soft')",
                [sym],
            )

    desk = query_deals_desk_default(db, card_limit=5)
    assert desk.buy_count == 20
    assert len(desk.symbols_for_tv) == 20
    assert len(desk.cards) == 5
    # Full TV has more names than cards
    assert desk.buy_tv.count("NSE:") == 20


def test_advanced_clients_return_ordered_tradingview_symbols(tmp_path):
    from App.deals_read_model import query_deals_advanced

    db = tmp_path / "advanced-deals.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute(
            "CREATE TABLE deals (trade_date DATE, symbol TEXT, side TEXT, client_name TEXT, deal_value_cr DOUBLE)"
        )
        con.execute(
            "CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, ema_200 DOUBLE, rs_percentile DOUBLE, vcp_score DOUBLE, vcp_state TEXT, away_52w_high_pct DOUBLE)"
        )
        con.execute(
            "CREATE TABLE stocks_master (symbol TEXT, market_cap_cr DOUBLE, sector TEXT, industry TEXT)"
        )
        con.executemany(
            "INSERT INTO deals VALUES (?, ?, 'BUY', ?, ?)",
            [
                ("2026-08-10", "NEWEST", "Fund A", 10.0),
                ("2026-08-09", "MIDDLE", "Fund A", 10.0),
                ("2026-08-07", "OLD-EST", "Fund A", 10.0),
                ("2026-08-10", "OTHER", "Fund B", 12.0),
            ],
        )
        con.executemany(
            "INSERT INTO indicators_daily VALUES (?, ?, 110, 100, 80, 70, 'ready', -2)",
            [
                ("NEWEST", "2026-08-10"),
                ("MIDDLE", "2026-08-10"),
                ("OLD-EST", "2026-08-10"),
                ("OTHER", "2026-08-10"),
            ],
        )
        con.executemany(
            "INSERT INTO stocks_master VALUES (?, 2000, 'Tech', 'Software')",
            [("NEWEST",), ("MIDDLE",), ("OLD-EST",), ("OTHER",)],
        )

    data = query_deals_advanced(db, side="BUY", min_value_cr=0, lookback_days=10)
    clients = data["clients"].set_index("client_name")

    assert clients.loc["Fund A", "symbols"] == 3
    assert clients.loc["Fund A", "symbol_list"] == "NSE:NEWEST,NSE:MIDDLE,NSE:OLD_EST"


def test_app_wires_deals_to_research_module():
    source = Path("App/app.py").read_text(encoding="utf-8")
    assert "build_deals_page" in source
    assert "pages.research.deals" in source or "App.pages.research.deals" in source
    # Old heavy open-path client_history must not remain in app.py deals path
    assert "Institution Flow Leaderboard" not in source


def test_institution_leaderboard_view_prepares_preview_and_copy_column():
    from App.pages.research.deals import prepare_institution_leaderboard

    clients = pd.DataFrame(
        [
            {
                "client_name": "Fund A",
                "symbol_list": "NSE:NEWEST,NSE:MIDDLE,NSE:OLD_EST,NSE:FOURTH,NSE:FIFTH,NSE:SIXTH",
            }
        ]
    )

    view, columns = prepare_institution_leaderboard(clients)

    assert columns[-2:] == ["copy_symbols", "symbol_preview"]
    assert view.loc[0, "symbol_preview"] == "NEWEST, MIDDLE, OLD_EST, FOURTH, FIFTH +1 more"
    assert view.loc[0, "copy_symbols"] == ""
    assert view.loc[0, "symbol_list"] == "NSE:NEWEST,NSE:MIDDLE,NSE:OLD_EST,NSE:FOURTH,NSE:FIFTH,NSE:SIXTH"


def test_institution_copy_event_extracts_full_symbol_list():
    from App.app import institution_copy_text

    assert institution_copy_text({"symbol_list": "NSE:NEWEST,NSE:OLD_EST"}) == "NSE:NEWEST,NSE:OLD_EST"
    assert institution_copy_text({"symbol_list": None}) == ""


def test_styles_live_in_ui_kit():
    styles = Path("App/ui/styles.py").read_text(encoding="utf-8")
    assert "--mp-primary" in styles
    assert "def add_styles" in styles
    app = Path("App/app.py").read_text(encoding="utf-8")
    assert "App.ui.styles" in app or "ui.styles" in app
