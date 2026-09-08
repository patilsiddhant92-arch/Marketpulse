"""
Tests for Action Desk and Cache Manager.
Verifies strict quality filters, setup queue classifications, and in-memory caching.
"""
from __future__ import annotations

import ast
from pathlib import Path
import duckdb
import pytest

from App.cache_manager import get_cached, set_cached, invalidate_cache, cache_key
from App.pages.action_desk import fetch_action_desk_data
from Scripts.config import DB_PATH
from Scripts.desk_contract import (
    ACTION_DESK_SUBTITLE,
    EXPOSURE_RULES,
    QUEUE_DISPLAY_CAPS,
    QUEUE_META,
    ROUTINE_HEADLINE,
    ROUTINE_WINDOWS,
    flag_on,
    iter_playbook_copy,
    match_exposure,
)

UNVERIFIED_HIT_RATES = ("82%", "71%", "56%", "21.6%", "9.6%", "78%")
PLAYBOOK_COPY_FILES = (
    Path("App/ui/playbook_guide.py"),
    Path("App/pages/info_page.py"),
    Path("App/pages/action_desk.py"),
    Path("Scripts/desk_contract.py"),
)


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
    vix = exp["vix"]
    assert vix is None or float(vix) > 0.0
    if vix is None:
        assert exp.get("vix_na") is True
        assert exp.get("vix_label") == "VIX n/a"


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
    assert "QUEUE_META" in page_source
    assert "render_market_health_strip" in page_source
    assert "8 setup queues" in page_source
    assert "5 Actionable Setup Queues" not in page_source
    assert "1. VCP / Coiling Breakouts" not in page_source


def _exposure_args(**overrides):
    args = dict(
        adv_pct=58.0,
        ab20_pct=48.0,
        ab200_pct=45.0,
        vix=14.0,
        vix_spike=False,
        net_lows_expanding=False,
        vix_1d_pct=0.0,
        count_52w_highs=10,
        count_52w_lows=4,
    )
    args.update(overrides)
    return args


def test_flag_on_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("MP_DARVAS_V2", raising=False)
    monkeypatch.delenv("MP_SECTOR_V2", raising=False)
    assert flag_on("MP_DARVAS_V2") is False
    assert flag_on("MP_SECTOR_V2") is False
    monkeypatch.setenv("MP_DARVAS_V2", "true")
    assert flag_on("MP_DARVAS_V2") is True


def test_queue_display_caps_uses_near_pivot_not_vcp() -> None:
    assert "near_pivot" in QUEUE_DISPLAY_CAPS
    assert "vcp" not in QUEUE_DISPLAY_CAPS
    assert QUEUE_DISPLAY_CAPS["near_pivot"] == 15
    assert QUEUE_META["vcp"]["title"] == "1. Near 20D Pivot"
    assert QUEUE_META["vcp"]["cap_key"] == "near_pivot"


def test_action_desk_header_and_docstring_say_8_setup_queues() -> None:
    desk = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    app = Path("App/app.py").read_text(encoding="utf-8")
    assert "8 setup queues" in desk
    assert "5 Actionable Setup Queues" not in desk
    assert "ACTION_DESK_SUBTITLE" in app
    assert ACTION_DESK_SUBTITLE not in app
    assert "8 setup queues" in ACTION_DESK_SUBTITLE
    assert "4 actionable setup queues" not in app


def test_playbook_copy_has_no_unverified_hit_rates() -> None:
    """Fails on current main: playbook 21.6% and Action Desk 82% mythology."""
    for path in PLAYBOOK_COPY_FILES:
        text = path.read_text(encoding="utf-8")
        for token in UNVERIFIED_HIT_RATES:
            assert token not in text, f"{path} still contains unverified {token}"


def _ui_label_text_fragments(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fragments: list[str] = []

    def _from_expr(expr: ast.AST) -> None:
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            fragments.append(expr.value)
        elif isinstance(expr, ast.JoinedStr):
            for part in expr.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    fragments.append(part.value)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "label"):
            continue
        if node.args:
            _from_expr(node.args[0])
    return fragments


def test_playbook_modal_copy_is_locked_to_desk_contract() -> None:
    """A string change in the modal without a contract change must fail."""
    contract = set(iter_playbook_copy())
    guide_path = Path("App/ui/playbook_guide.py")
    src = guide_path.read_text(encoding="utf-8")
    assert "desk_contract" in src
    assert "EXPOSURE_RULES" in src
    for frag in _ui_label_text_fragments(guide_path):
        if len(frag) < 24:
            continue
        assert frag in contract, f"Modal label not in desk_contract: {frag!r}"
    info_src = Path("App/pages/info_page.py").read_text(encoding="utf-8")
    assert "EXPOSURE_RULES" in info_src
    assert "desk_contract" in info_src
    for text in contract:
        assert "fetch_action_desk_data" not in text
    for rule in EXPOSURE_RULES:
        assert rule["pct"] in contract
        assert rule["state"] in contract


def test_playbook_routine_windows_are_1545_and_0830() -> None:
    assert ROUTINE_WINDOWS == ("15:45", "08:30")
    assert "15:45" in ROUTINE_HEADLINE
    assert "08:30" in ROUTINE_HEADLINE
    guide = Path("App/ui/playbook_guide.py").read_text(encoding="utf-8")
    assert "ROUTINE_HEADLINE" in guide
    assert "4:00 PM" not in guide
    info = Path("App/pages/info_page.py").read_text(encoding="utf-8")
    assert "4:00 PM - 9:00 AM" not in info


def test_exposure_rules_copy_live_thresholds_first_match_wins() -> None:
    aggressive = match_exposure(_exposure_args())
    assert aggressive["id"] == "aggressive"
    assert aggressive["pct"] == "75% - 100%"
    assert aggressive["vix_na"] is False

    # vix < 15 is required; 15.0 falls through to constructive.
    constructive = match_exposure(_exposure_args(vix=15.0))
    assert constructive["id"] == "constructive"
    assert constructive["pct"] == "50% - 75%"

    selective = match_exposure(_exposure_args(adv_pct=35.0, ab20_pct=10.0, vix=21.9))
    assert selective["id"] == "selective"
    assert selective["pct"] == "25% - 50%"

    risk_off = match_exposure(_exposure_args(adv_pct=34.9, ab20_pct=10.0, vix=21.9))
    assert risk_off["id"] == "risk_off"
    assert risk_off["pct"] == "0% - 15%"


def test_exposure_vix_none_skips_vix_threshold_branches() -> None:
    """Missing VIX must not match vix < X branches; fall through; surface VIX n/a."""
    result = match_exposure(_exposure_args(vix=None, adv_pct=80.0, ab20_pct=80.0, ab200_pct=80.0))
    assert result["id"] == "risk_off"
    assert result["vix_na"] is True
    assert result["vix_label"] == "VIX n/a"

    still_selective = match_exposure(_exposure_args(adv_pct=40.0, ab20_pct=10.0, vix=20.0))
    assert still_selective["id"] == "selective"

    missing_vix_same_tape = match_exposure(_exposure_args(adv_pct=40.0, ab20_pct=10.0, vix=None))
    assert missing_vix_same_tape["id"] == "risk_off"
    assert missing_vix_same_tape["vix_label"] == "VIX n/a"


def test_exposure_rules_are_four_named_branches() -> None:
    assert [rule["id"] for rule in EXPOSURE_RULES] == [
        "aggressive",
        "constructive",
        "selective",
        "risk_off",
    ]

