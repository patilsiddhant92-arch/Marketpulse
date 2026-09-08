"""
Tests for Action Desk and Cache Manager.
Verifies strict quality filters, setup queue classifications, and in-memory caching.
"""
from __future__ import annotations

from pathlib import Path
import duckdb
import pytest

from App.cache_manager import get_cached, set_cached, invalidate_cache, cache_key
from App.pages.action_desk import compute_exposure_gate, fetch_action_desk_data, resolve_india_vix
from Scripts.config import DB_PATH


def test_cache_manager_lifecycle() -> None:
    invalidate_cache()
    key = cache_key(DB_PATH, "2026-09-03", "test_metric", "arg1")
    assert get_cached(key) is None

    set_cached(key, {"value": 42})
    hit = get_cached(key)
    assert hit is not None
    assert hit["value"] == 42

    # Invalidate specific
    deleted = invalidate_cache("test_metric")
    assert deleted >= 1
    assert get_cached(key) is None


def test_action_desk_data_returns_valid_decision_structure() -> None:
    data = fetch_action_desk_data(DB_PATH)
    assert data.get("ready") is True
    assert "trade_date" in data
    assert "exposure" in data
    assert "themes" in data
    assert "queues" in data
    assert "tv_lists" in data

    exp = data["exposure"]
    assert "pct" in exp
    assert "state" in exp
    assert "guidance" in exp
    assert exp["adv_pct"] >= 0.0
    if exp["vix"] is None:
        assert exp["vix_label"] == "VIX n/a"
    else:
        assert exp["vix"] > 0.0


def test_action_desk_enforces_strict_swing_quality_rules() -> None:
    data = fetch_action_desk_data(DB_PATH)
    queues = data["queues"]

    all_candidates = []
    for q_name, df in queues.items():
        if not df.empty:
            all_candidates.append(df)

    assert len(all_candidates) > 0

    for df in all_candidates:
        # Rule 1: No Rights Entitlements
        syms = df["symbol"].astype(str).tolist()
        for s in syms:
            assert not s.endswith("-RE")
            assert not s.endswith("_RE")
            assert "-RE" not in s

        # Rule 2: MCap >= 1000 Cr
        assert (df["market_cap_cr"] >= 1000.0).all()

        # Rule 3: No 5% Band
        assert (df["band"] > 5.0).all()

    # Rule 4: Classic breakout queues enforce Stage 2 uptrend, above 200 EMA, and within 25% 52W
    for q_name in ["vcp", "pullback", "high52"]:
        q_df = queues.get(q_name)
        if q_df is not None and not q_df.empty:
            assert (q_df["rs_percentile"] >= 70.0).all()
            assert (q_df["away_52w_high_pct"] >= -25.0).all()
            assert (q_df["ema_200"].isna() | (q_df["cmp"] > q_df["ema_200"])).all()

    # Rule 5: Darvas Squeeze & Pre-Move queues are decoupled from RS and include leaders like MIDHANI
    darvas_df = queues.get("darvas")
    assert darvas_df is not None and not darvas_df.empty
    assert "MIDHANI" in darvas_df["symbol"].values

    # Rule 6: Pre-move queues attach institutional ticket flow
    for q_name in ["silent_coil", "stair_step", "spike_pause"]:
        q_df = queues.get(q_name)
        if q_df is not None and not q_df.empty:
            assert "ticket_flow" in q_df.columns
            assert "away_10ema" in q_df.columns
            assert "band_fmt" in q_df.columns


def test_action_desk_tradingview_paste_lists() -> None:
    data = fetch_action_desk_data(DB_PATH)
    tv = data["tv_lists"]
    assert "all_focus" in tv
    assert "vcp" in tv
    assert "pullback" in tv
    assert "episodic" in tv
    assert "high52" in tv
    assert "darvas" in tv
    assert "silent_coil" in tv
    assert "stair_step" in tv
    assert "spike_pause" in tv
    assert "NSE:" in tv["all_focus"]
    assert "NSE:" in tv["darvas"]


def test_action_desk_darvas_squeeze_queue() -> None:
    data = fetch_action_desk_data(DB_PATH)
    darvas_df = data["queues"].get("darvas")
    assert darvas_df is not None
    assert not darvas_df.empty
    assert "squeeze_pct" in darvas_df.columns
    assert "darvas_top" in darvas_df.columns
    assert "trigger_price" in darvas_df.columns
    assert "stop_loss" in darvas_df.columns
    assert "MIDHANI" in darvas_df["symbol"].values
    assert (darvas_df["squeeze_pct"] <= 5.0).all()
    assert (darvas_df["squeeze_pct"] >= 0.0).all()


def test_stock_candlestick_darvas_indicators() -> None:
    from App.ui.stock_drawer import query_stock_candlestick_data
    ad_data = fetch_action_desk_data(DB_PATH)
    darvas_df = ad_data["queues"]["darvas"]
    test_sym = str(darvas_df.iloc[0]["symbol"]) if not darvas_df.empty else "IDFCFIRSTB"
    res = query_stock_candlestick_data(DB_PATH, test_sym, limit=60)
    assert "darvas_top" in res
    assert "darvas_bottom" in res
    assert len(res["darvas_top"]) == len(res["dates"])
    assert len(res["darvas_bottom"]) == len(res["dates"])
    assert "is_darvas_squeeze" in res
    assert res["is_darvas_squeeze"] is True
    assert res["darvas_squeeze_pct"] is not None
    assert res["darvas_squeeze_pct"] <= 3.5
    assert res["candle_range_pct"] is not None
    assert res["candle_range_pct"] <= 3.5

    # LUMAXIND had high poke above box ceiling (6450 vs top 6189), so it must NOT be flagged as in-box squeeze
    res_lumax = query_stock_candlestick_data(DB_PATH, "LUMAXIND", limit=60)
    assert res_lumax["is_darvas_squeeze"] is False


def test_action_desk_deal_accumulation_attached() -> None:
    data = fetch_action_desk_data(DB_PATH)
    queues = data["queues"]
    for q_name, df in queues.items():
        if not df.empty:
            assert "deal_flow" in df.columns
            # Non-empty strings
            assert df["deal_flow"].notna().all()


def test_action_desk_cockpit_layout_structure() -> None:
    page_source = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    assert "mp-cockpit-container" in page_source
    assert "mp-funnel-col" in page_source
    assert "mp-matrix-col" in page_source
    assert "mp-inspector-col" in page_source
    assert "render_stock_inspector_panel" in page_source
    assert "queue_meta" in page_source


def test_action_desk_missing_vix_is_na_not_silent_11_3(tmp_path) -> None:
    """Fails on current main: missing India VIX silently defaulted to 11.3 and still took vix < 15 branches."""
    source = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    assert "vix_val = 11.3" not in source
    assert "VIX n/a" in source

    db_path = tmp_path / "vix.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            "CREATE TABLE index_daily (trade_date DATE, index_name TEXT, close_price DOUBLE, prev_close DOUBLE)"
        )
        con.execute("INSERT INTO index_daily VALUES ('2026-09-07', 'Nifty 50', 25000, 24900)")
        vix, chg = resolve_india_vix(con, "2026-09-07")
    assert vix is None
    assert vix != 11.3
    assert chg == 0.0

    exp = compute_exposure_gate(
        adv_pct=70.0,
        ab20_pct=60.0,
        ab200_pct=55.0,
        vix=vix,
        vix_1d_pct=chg,
        net_lows_expanding=False,
        count_52w_highs=80,
        count_52w_lows=20,
    )
    assert exp["vix"] is None
    assert exp["vix_available"] is False
    assert exp["vix_label"] == "VIX n/a"
    assert exp["state"] == "Risk-Off / Defensive"
    assert exp["pct"] == "0% - 15%"
    assert "11.3" not in exp["guidance"]

    present = compute_exposure_gate(
        adv_pct=70.0,
        ab20_pct=60.0,
        ab200_pct=55.0,
        vix=11.3,
        vix_1d_pct=0.0,
        net_lows_expanding=False,
        count_52w_highs=80,
        count_52w_lows=20,
    )
    assert present["state"] == "Aggressive / Full Trend"
    assert present["vix_label"] != "VIX n/a"

