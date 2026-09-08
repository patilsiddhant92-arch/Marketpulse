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


def test_default_deals_reject_missing_market_cap_and_label_the_universe(tmp_path):
    from App.deals_read_model import query_deals_desk_default

    db = tmp_path / "missing-mcap.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE deals (trade_date DATE, symbol TEXT, side TEXT, client_name TEXT, deal_value_cr DOUBLE)")
        con.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, ema_200 DOUBLE, rs_percentile DOUBLE, away_52w_high_pct DOUBLE)")
        con.execute("CREATE TABLE stocks_master (symbol TEXT, market_cap_cr DOUBLE, sector TEXT, industry TEXT)")
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'UNKNOWNCAP', 'BUY', 'Fund', 50)")
        con.execute("INSERT INTO indicators_daily VALUES ('UNKNOWNCAP', '2026-08-07', 110, 100, 80, -2)")
        con.execute("INSERT INTO stocks_master VALUES ('UNKNOWNCAP', NULL, 'Tech', 'Software')")

    desk = query_deals_desk_default(db)

    assert desk.buy_count == 0
    assert desk.universe_label == "₹900 Cr+ and CMP > 200 EMA"
    assert "missing market cap" in desk.filter_notes.lower()


def test_deals_desk_rejects_stocks_below_900_cr(tmp_path):
    from App.deals_read_model import query_deals_desk_default

    db = tmp_path / "sub-900-mcap.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE deals (trade_date DATE, symbol TEXT, side TEXT, client_name TEXT, deal_value_cr DOUBLE)")
        con.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, ema_200 DOUBLE, rs_percentile DOUBLE, away_52w_high_pct DOUBLE)")
        con.execute("CREATE TABLE stocks_master (symbol TEXT, market_cap_cr DOUBLE, sector TEXT, industry TEXT)")
        # Micro-cap 850 Cr should be rejected
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'MICRO850', 'BUY', 'Fund', 50)")
        con.execute("INSERT INTO indicators_daily VALUES ('MICRO850', '2026-08-07', 110, 100, 80, -2)")
        con.execute("INSERT INTO stocks_master VALUES ('MICRO850', 850.0, 'Tech', 'Software')")
        # Quality 950 Cr should pass
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'PASS950', 'BUY', 'Fund', 50)")
        con.execute("INSERT INTO indicators_daily VALUES ('PASS950', '2026-08-07', 110, 100, 80, -2)")
        con.execute("INSERT INTO stocks_master VALUES ('PASS950', 950.0, 'Tech', 'Software')")

    desk = query_deals_desk_default(db)
    assert "MICRO850" not in desk.symbols_for_tv
    assert "PASS950" in desk.symbols_for_tv
    assert desk.buy_count == 1


def test_default_deals_reject_missing_structure_values(tmp_path):
    from App.deals_read_model import query_deals_desk_default

    db = tmp_path / "missing-structure.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE deals (trade_date DATE, symbol TEXT, side TEXT, client_name TEXT, deal_value_cr DOUBLE)")
        con.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, ema_200 DOUBLE, rs_percentile DOUBLE, away_52w_high_pct DOUBLE)")
        con.execute("CREATE TABLE stocks_master (symbol TEXT, market_cap_cr DOUBLE, sector TEXT, industry TEXT)")
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'UNKNOWNSTRUCTURE', 'BUY', 'Fund', 50)")
        con.execute("INSERT INTO indicators_daily VALUES ('UNKNOWNSTRUCTURE', '2026-08-07', NULL, 100, 80, -2)")
        con.execute("INSERT INTO stocks_master VALUES ('UNKNOWNSTRUCTURE', 2000, 'Tech', 'Software')")

    desk = query_deals_desk_default(db)

    assert desk.buy_count == 0


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


def test_telegram_deals_tv_strings_and_db_override(tmp_path):
    from Scripts.telegram_deals import build_deals_telegram_report

    db = tmp_path / "marketpulse.duckdb"
    _seed_deals_db(db)

    report = build_deals_telegram_report(lookback_days=20, min_mcap_cr=500.0, db_path=db)
    assert report["as_of"] == "2026-08-07"
    assert "tv_strings" in report

    tv = report["tv_strings"]
    assert "four_plus" in tv
    assert "three" in tv
    assert "two" in tv
    assert "persistence_all" in tv
    assert "fii" in tv
    assert "dii" in tv
    assert "inst_buys" in tv
    assert "others" in tv
    assert "prop" in tv
    assert "top_buys" in tv
    assert "top_sells" in tv
    assert "all_buys" in tv

    # AAA and BBB were bought, CCC fails mcap/structure or side
    assert "NSE:AAA" in tv["all_buys"]
    assert "NSE:BBB" in tv["all_buys"]


def test_deals_telegram_fetch_cache(tmp_path):
    from App.pages.research.deals import fetch_deals_telegram_data
    from App.cache_manager import invalidate_cache

    invalidate_cache()
    db = tmp_path / "marketpulse.duckdb"
    _seed_deals_db(db)

    # First fetch (cache miss -> populate)
    r1 = fetch_deals_telegram_data(db, 20)
    assert "tv_strings" in r1

    # Second fetch (cache hit)
    r2 = fetch_deals_telegram_data(db, 20)
    assert r1 is r2

    # Different lookback (different cache key)
    r3 = fetch_deals_telegram_data(db, 10)
    assert "tv_strings" in r3


def test_prop_only_stocks_excluded_from_persistence_and_routed_to_prop_header(tmp_path):
    from Scripts.telegram_deals import build_deals_telegram_report

    db = tmp_path / "prop-test.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE deals (trade_date DATE, symbol TEXT, side TEXT, client_name TEXT, deal_value_cr DOUBLE)")
        con.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, ema_200 DOUBLE, rs_percentile DOUBLE, away_52w_high_pct DOUBLE)")
        con.execute("CREATE TABLE stocks_master (symbol TEXT, market_cap_cr DOUBLE, sector TEXT, industry TEXT)")

        # QUADFUTURE has 3 days of deals, but all from PROP desks (Jump, Alphagrep, Silverleaf)
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'QUADFUTURE', 'BUY', 'JUMP TRADING FINANCIAL INDIA PRIVATE LIMITED', 30.0)")
        con.execute("INSERT INTO deals VALUES ('2026-08-06', 'QUADFUTURE', 'BUY', 'ALPHAGREP SECURITIES PRIVATE LIMITED', 25.0)")
        con.execute("INSERT INTO deals VALUES ('2026-08-05', 'QUADFUTURE', 'BUY', 'SILVERLEAF CAPITAL SERVICES PRIVATE LIMITED', 20.0)")

        # REALINST has 3 days of deals from real mutual fund
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'REALINST', 'BUY', 'HDFC MUTUAL FUND', 50.0)")
        con.execute("INSERT INTO deals VALUES ('2026-08-06', 'REALINST', 'BUY', 'SBI MUTUAL FUND', 40.0)")
        con.execute("INSERT INTO deals VALUES ('2026-08-05', 'REALINST', 'BUY', 'NIPPON INDIA MUTUAL FUND', 30.0)")

        con.execute("INSERT INTO indicators_daily VALUES ('QUADFUTURE', '2026-08-07', 400.0, 350.0, 85.0, -5.0)")
        con.execute("INSERT INTO indicators_daily VALUES ('REALINST', '2026-08-07', 500.0, 420.0, 90.0, -3.0)")

        con.execute("INSERT INTO stocks_master VALUES ('QUADFUTURE', 2000.0, 'Technology', 'Software')")
        con.execute("INSERT INTO stocks_master VALUES ('REALINST', 5000.0, 'Finance', 'Banks')")

    report = build_deals_telegram_report(lookback_days=20, min_mcap_cr=900.0, db_path=db)
    persistence = report["persistence"]
    three_days = persistence["three"]["symbol"].tolist()
    prop_stocks = report["clientele"]["PROP"]["symbol"].tolist()

    # QUADFUTURE must NOT be in 3 Deal Days persistence
    assert "QUADFUTURE" not in three_days
    # REALINST must be in 3 Deal Days persistence
    assert "REALINST" in three_days
    # QUADFUTURE must be in PROP category header
    assert "QUADFUTURE" in prop_stocks


def test_streamlined_3tier_deals_architecture(tmp_path):
    from Scripts.telegram_deals import build_deals_telegram_report

    db = tmp_path / "3tier-test.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE deals (trade_date DATE, symbol TEXT, side TEXT, client_name TEXT, deal_value_cr DOUBLE)")
        con.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE, close_price DOUBLE, ema_200 DOUBLE, rs_percentile DOUBLE, away_52w_high_pct DOUBLE)")
        con.execute("CREATE TABLE stocks_master (symbol TEXT, market_cap_cr DOUBLE, sector TEXT, industry TEXT, band DOUBLE)")

        # 1. TIER 1: MULTI_ACC (2 deal days, FII backed)
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'MULTI_ACC', 'BUY', 'MORGAN STANLEY ASIA', 25.0)")
        con.execute("INSERT INTO deals VALUES ('2026-08-06', 'MULTI_ACC', 'BUY', 'GOLDMAN SACHS', 20.0)")

        # 2. TIER 1: WHALE_ONE (1 deal day, but buy >= 25 Cr whale inflow)
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'WHALE_ONE', 'BUY', 'HDFC MUTUAL FUND', 75.0)")

        # 3. TIER 1: TURNAROUND_WHALE (Stage 1 base turnaround below 200 EMA, buy >= 25 Cr)
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'TURNAROUND_WHALE', 'BUY', 'NIPPON MUTUAL FUND', 60.0)")

        # 4. TIER 2: FRESH_RADAR (1 deal day, buy < 25 Cr, DII backed)
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'FRESH_RADAR', 'BUY', 'SBI MUTUAL FUND', 15.0)")

        # 5. TIER 3A: PURE_PROP (Prop desk only, Jump Trading)
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'PURE_PROP', 'BUY', 'JUMP TRADING FINANCIAL INDIA', 40.0)")

        # 6. TIER 3B: QUARANTINED (Locked in tight 5% circuit band)
        con.execute("INSERT INTO deals VALUES ('2026-08-07', 'LOCKED_5PCT', 'BUY', 'FRANKLIN TEMPLETON', 30.0)")

        # Indicators
        con.execute("INSERT INTO indicators_daily VALUES ('MULTI_ACC', '2026-08-07', 300.0, 250.0, 85.0, -4.0)")
        con.execute("INSERT INTO indicators_daily VALUES ('WHALE_ONE', '2026-08-07', 500.0, 420.0, 90.0, -2.0)")
        con.execute("INSERT INTO indicators_daily VALUES ('TURNAROUND_WHALE', '2026-08-07', 80.0, 100.0, 40.0, -25.0)")
        con.execute("INSERT INTO indicators_daily VALUES ('FRESH_RADAR', '2026-08-07', 200.0, 180.0, 75.0, -6.0)")
        con.execute("INSERT INTO indicators_daily VALUES ('PURE_PROP', '2026-08-07', 150.0, 130.0, 70.0, -8.0)")
        con.execute("INSERT INTO indicators_daily VALUES ('LOCKED_5PCT', '2026-08-07', 120.0, 110.0, 60.0, -10.0)")

        # Stocks master (all Mcap >= 900 Cr)
        con.execute("INSERT INTO stocks_master VALUES ('MULTI_ACC', 3000.0, 'Technology', 'Software', 20.0)")
        con.execute("INSERT INTO stocks_master VALUES ('WHALE_ONE', 5000.0, 'Finance', 'Banks', 20.0)")
        con.execute("INSERT INTO stocks_master VALUES ('TURNAROUND_WHALE', 4000.0, 'Energy', 'Power', 20.0)")
        con.execute("INSERT INTO stocks_master VALUES ('FRESH_RADAR', 1800.0, 'Auto', 'OEM', 20.0)")
        con.execute("INSERT INTO stocks_master VALUES ('PURE_PROP', 2200.0, 'Metals', 'Steel', 20.0)")
        con.execute("INSERT INTO stocks_master VALUES ('LOCKED_5PCT', 2500.0, 'Textiles', 'Apparel', 5.0)")

    report = build_deals_telegram_report(lookback_days=20, min_mcap_cr=900.0, db_path=db)
    tiers = report["tiers"]
    tv = report["tv_strings"]
    msgs = report["messages"]

    tier1_syms = set(tiers["conviction"]["symbol"])
    tier2_syms = set(tiers["fresh_radar"]["symbol"])
    prop_syms = set(tiers["prop_only"]["symbol"])
    quarantine_syms = set(tiers["quarantined"]["symbol"])

    # 1. Tier membership checks
    assert "MULTI_ACC" in tier1_syms
    assert "WHALE_ONE" in tier1_syms
    assert "TURNAROUND_WHALE" in tier1_syms  # Stage 1 base turnarounds <200 EMA belong in Tier 1
    assert "FRESH_RADAR" in tier2_syms
    assert "PURE_PROP" in prop_syms
    assert "LOCKED_5PCT" in quarantine_syms  # 5% circuit band stocks are quarantined

    # 2. Strict Mutual Exclusivity (Zero duplicate symbols across all tiers)
    all_tier_sets = [tier1_syms, tier2_syms, prop_syms, quarantine_syms]
    total_unique = len(tier1_syms | tier2_syms | prop_syms | quarantine_syms)
    total_elements = sum(len(s) for s in all_tier_sets)
    assert total_unique == total_elements, "Duplicate tickers detected across tiers!"

    # 3. TV Strings validation
    assert "NSE:MULTI_ACC" in tv["master_tv"]
    assert "NSE:WHALE_ONE" in tv["master_tv"]
    assert "NSE:TURNAROUND_WHALE" in tv["master_tv"]
    assert "NSE:FRESH_RADAR" in tv["master_tv"]
    assert "NSE:PURE_PROP" not in tv["master_tv"]
    assert "NSE:LOCKED_5PCT" not in tv["master_tv"]

    assert "NSE:MULTI_ACC" in tv["conviction_tv"]
    assert "NSE:WHALE_ONE" in tv["conviction_tv"]
    assert "NSE:TURNAROUND_WHALE" in tv["conviction_tv"]
    assert "NSE:FRESH_RADAR" not in tv["conviction_tv"]

    assert "NSE:FRESH_RADAR" in tv["fresh_radar_tv"]
    assert "NSE:PURE_PROP" in tv["prop_tv"]
    assert "NSE:LOCKED_5PCT" in tv["quarantined_tv"]

    # 4. Message count check
    assert len(msgs) == 2

