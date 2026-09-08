"""Test Market Health Regime Strip and Summary Query."""

from __future__ import annotations

import ast
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from App.pages.action_desk import fetch_action_desk_data
from App.ui.market_health import (
    BREADTH_EXPOSURE_MAP,
    exposure_inputs_from_breadth_row,
    load_exposure_inputs,
    query_market_health_summary,
)
from Scripts.config import DB_PATH

EXPECTED_CARD_TITLES = {
    "ad_net": "Advance / decline",
    "above_20": "Above 20 EMA",
    "above_200": "Above 200 EMA",
    "rsi_60": "RSI above 60",
    "pivot": "Above daily pivot",
    "near_52w": "Near 52W high",
    "breakout": "VCP heuristic",
}


def _calls_in_function(path: Path, func_name: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node: ast.Call) -> None:
            ident = None
            func = node.func
            if isinstance(func, ast.Name):
                ident = func.id
            elif isinstance(func, ast.Attribute):
                ident = func.attr
            if ident and self.stack:
                found.append(f"{self.stack[-1]}:{ident}")
            self.generic_visit(node)

    Visitor().visit(tree)
    return [c for c in found if c.startswith(f"{func_name}:")]


def test_breakout_card_keeps_key_and_is_titled_vcp_heuristic() -> None:
    src = Path("App/ui/market_health.py").read_text(encoding="utf-8")
    assert '"key": "breakout"' in src
    assert '"title": "VCP heuristic"' in src
    assert '"title": "Recent breakout"' not in src
    assert "heuristic names" in src
    assert "VCP setups" not in src


def test_health_strip_mounted_on_desk_action_desk_and_sectors() -> None:
    desk_calls = _calls_in_function(Path("App/pages/desk.py"), "build_desk_page")
    action_calls = _calls_in_function(Path("App/pages/action_desk.py"), "build_action_desk_page")
    sector_calls = _calls_in_function(Path("App/pages/research/sector_board.py"), "build_sector_board_page")
    assert "build_desk_page:render_market_health_strip" in desk_calls
    assert "build_action_desk_page:render_market_health_strip" in action_calls
    assert "build_sector_board_page:render_market_health_strip" in sector_calls
    strip = Path("App/ui/market_health.py").read_text(encoding="utf-8")
    assert "{as_of} · {stocks_n:,} stocks" in strip


def test_exposure_map_matches_design_columns() -> None:
    assert BREADTH_EXPOSURE_MAP == {
        "adv_pct": "advance_pct",
        "ab20_pct": "above_20ema_pct",
        "ab50_pct": "above_50ema_pct",
        "ab200_pct": "above_200ema_pct",
    }
    row = pd.Series(
        {
            "trade_date": "2026-09-07",
            "stocks": 2401,
            "advance_pct": 41.23,
            "above_20ema_pct": 38.91,
            "above_50ema_pct": 44.44,
            "above_200ema_pct": 52.07,
        }
    )
    got = exposure_inputs_from_breadth_row(row)
    assert got["adv_pct"] == 41.2
    assert got["ab20_pct"] == 38.9
    assert got["ab50_pct"] == 44.4
    assert got["ab200_pct"] == 52.1
    assert got["total_stocks"] == 2401
    assert got["as_of"] == "2026-09-07"
    assert got["source"] == "breadth_daily"

    zero = exposure_inputs_from_breadth_row(
        pd.Series(
            {
                "trade_date": "2026-09-07",
                "stocks": 0,
                "advance_pct": 0.0,
                "above_20ema_pct": 0.0,
                "above_50ema_pct": 0.0,
                "above_200ema_pct": 0.0,
            }
        )
    )
    assert zero["adv_pct"] == 0.0
    assert zero["total_stocks"] == 0


def _mem() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


def _create_breadth(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE breadth_daily (
            trade_date DATE,
            stocks INTEGER,
            advancers INTEGER,
            decliners INTEGER,
            unchanged INTEGER,
            advance_pct DOUBLE,
            above_20ema_pct DOUBLE,
            above_50ema_pct DOUBLE,
            above_200ema_pct DOUBLE,
            near_52w_highs INTEGER,
            vcp_candidates INTEGER,
            breadth_state VARCHAR
        )
        """
    )


def _create_indicators(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE indicators_daily (
            trade_date DATE,
            close_price DOUBLE,
            prev_close DOUBLE,
            ema_20 DOUBLE,
            ema_50 DOUBLE,
            ema_200 DOUBLE
        )
        """
    )


def test_load_exposure_uses_breadth_daily_row_not_indicators_avg() -> None:
    con = _mem()
    _create_breadth(con)
    _create_indicators(con)
    con.execute(
        """
        INSERT INTO breadth_daily VALUES
        ('2026-09-07', 99, 10, 80, 9, 12.3, 11.1, 22.2, 33.3, 1, 2, 'Weakening')
        """
    )
    # indicators would recompute to 100% if the fallback AVG ran
    con.execute(
        """
        INSERT INTO indicators_daily VALUES
        ('2026-09-07', 110, 100, 90, 90, 90),
        ('2026-09-07', 120, 100, 90, 90, 90)
        """
    )
    got = load_exposure_inputs(con, trade_date="2026-09-07")
    assert got["source"] == "breadth_daily"
    assert got["as_of"] == "2026-09-07"
    assert got["adv_pct"] == 12.3
    assert got["ab20_pct"] == 11.1
    assert got["ab50_pct"] == 22.2
    assert got["ab200_pct"] == 33.3
    assert got["total_stocks"] == 99


def test_load_exposure_fallback_keeps_zero_and_does_not_invent_50() -> None:
    con = _mem()
    _create_indicators(con)
    # Every name declined and sits below all EMAs → real 0%, not 50%.
    con.execute(
        """
        INSERT INTO indicators_daily VALUES
        ('2026-09-07', 10, 11, 20, 20, 20),
        ('2026-09-07', 9, 12, 20, 20, 20)
        """
    )
    got = load_exposure_inputs(con, trade_date="2026-09-07")
    assert got["source"] == "indicators_daily"
    assert got["as_of"] == "2026-09-07"
    assert got["adv_pct"] == 0.0
    assert got["ab20_pct"] == 0.0
    assert got["ab50_pct"] == 0.0
    assert got["ab200_pct"] == 0.0
    assert got["total_stocks"] == 2


def test_load_exposure_fallback_empty_session_leaves_pct_unset() -> None:
    con = _mem()
    _create_breadth(con)  # empty table → missing row
    _create_indicators(con)
    got = load_exposure_inputs(con, trade_date="2026-09-07")
    assert got["source"] == "indicators_daily"
    assert got["adv_pct"] is None
    assert got["ab20_pct"] is None
    assert got["ab50_pct"] is None
    assert got["ab200_pct"] is None
    assert got["total_stocks"] == 0


def test_load_exposure_fallback_when_breadth_table_missing() -> None:
    con = _mem()
    _create_indicators(con)
    con.execute(
        "INSERT INTO indicators_daily VALUES ('2026-09-07', 10, 11, 20, 20, 20)"
    )
    got = load_exposure_inputs(con, trade_date="2026-09-07")
    assert got["source"] == "indicators_daily"
    assert got["adv_pct"] == 0.0
    assert got["total_stocks"] == 1


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_query_market_health_summary_returns_7_cards():
    data = query_market_health_summary(DB_PATH)
    assert data, "Market health data must not be empty"
    assert data["as_of"] is not None
    assert data["total_stocks"] > 0
    assert "cards" in data
    assert len(data["cards"]) == 7, "Must contain exactly 7 regime cards"

    card_keys = [c["key"] for c in data["cards"]]
    expected = ["ad_net", "above_20", "above_200", "rsi_60", "pivot", "near_52w", "breakout"]
    for k in expected:
        assert k in card_keys, f"Card {k} must be present"

    by_key = {c["key"]: c for c in data["cards"]}
    for key, title in EXPECTED_CARD_TITLES.items():
        assert by_key[key]["title"] == title
    assert by_key["breakout"]["key"] == "breakout"
    assert "heuristic names" in by_key["breakout"]["context"]
    assert "VCP setups" not in by_key["breakout"]["context"]


@pytest.mark.skipif(not DB_PATH.exists(), reason="Database not built")
def test_action_desk_exposure_reads_same_breadth_daily_row_as_strip():
    health = query_market_health_summary(DB_PATH)
    desk = fetch_action_desk_data(DB_PATH)
    exp = desk["exposure"]
    assert health, "Market health data must not be empty"
    assert desk.get("ready") is True
    assert exp["breadth_source"] == "breadth_daily"
    assert exp["as_of"] == health["as_of"]
    assert exp["adv_pct"] == health["adv_pct"]
    assert exp["ab20_pct"] == health["ab20_pct"]
    assert exp["ab50_pct"] == health["ab50_pct"]
    assert exp["ab200_pct"] == health["ab200_pct"]
