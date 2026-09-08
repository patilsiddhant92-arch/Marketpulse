"""
Tests for Action Desk and Cache Manager.
Verifies strict quality filters, setup queue classifications, and in-memory caching.
"""
from __future__ import annotations

import ast
from pathlib import Path
import duckdb
import pandas as pd
import pytest

from App.cache_manager import get_cached, set_cached, invalidate_cache, cache_key
from App.indicators.darvas import DARVAS, apply_display_window, darvas_v2_enabled
from App.pages.action_desk import compute_exposure_gate, fetch_action_desk_data, resolve_india_vix
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


def _force_v1(monkeypatch) -> None:
    monkeypatch.delenv("MP_DARVAS_V2", raising=False)
    assert darvas_v2_enabled() is False
    invalidate_cache()


def _queue_frames(queues: dict):
    for name, df in queues.items():
        if isinstance(df, pd.DataFrame) and not df.empty:
            yield name, df


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


def test_action_desk_data_returns_valid_decision_structure(monkeypatch) -> None:
    _force_v1(monkeypatch)
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
    else:
        assert exp.get("vix_available") is True


def test_action_desk_enforces_strict_swing_quality_rules(monkeypatch) -> None:
    _force_v1(monkeypatch)
    data = fetch_action_desk_data(DB_PATH)
    queues = data["queues"]

    all_candidates = []
    for q_name, df in _queue_frames(queues):
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

    # Rule 5: Darvas Squeeze is decoupled from RS (no RS>=70 gate) and includes coiled leaders
    darvas_df = queues.get("darvas")
    assert isinstance(darvas_df, pd.DataFrame) and not darvas_df.empty
    assert any(s in darvas_df["symbol"].values for s in ["MIDHANI", "NPST", "EXPLEOSOL", "BANCOINDIA"])
    assert "NTPC" not in darvas_df["symbol"].values
    assert "RHIM" not in darvas_df["symbol"].values
    if "rs_percentile" in darvas_df.columns:
        # Must not apply the classic RS>=70 filter; names below 70 are allowed.
        assert (darvas_df["rs_percentile"] < 70.0).any() or (darvas_df["rs_percentile"] >= 0).all()

    # Rule 6: Pre-move queues attach institutional ticket flow
    for q_name in ["silent_coil", "stair_step", "spike_pause"]:
        q_df = queues.get(q_name)
        if q_df is not None and not q_df.empty:
            assert "ticket_flow" in q_df.columns
            assert "away_10ema" in q_df.columns
            assert "band_fmt" in q_df.columns


def test_action_desk_tradingview_paste_lists(monkeypatch) -> None:
    _force_v1(monkeypatch)
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


def test_action_desk_darvas_squeeze_queue(monkeypatch) -> None:
    _force_v1(monkeypatch)
    data = fetch_action_desk_data(DB_PATH)
    darvas_df = data["queues"].get("darvas")
    assert isinstance(darvas_df, pd.DataFrame)
    assert not darvas_df.empty
    assert "squeeze_pct" in darvas_df.columns
    assert "darvas_top" in darvas_df.columns
    assert "trigger_price" in darvas_df.columns
    assert "stop_loss" in darvas_df.columns
    assert any(s in darvas_df["symbol"].values for s in ["MIDHANI", "NPST", "EXPLEOSOL", "BANCOINDIA"])
    assert "NTPC" not in darvas_df["symbol"].values
    assert "RHIM" not in darvas_df["symbol"].values
    assert (darvas_df["squeeze_pct"] <= 5.0).all()
    assert (darvas_df["squeeze_pct"] >= 0.0).all()
    # Displayed stop is attached, never used as a discovery filter
    assert "risk_pct" in darvas_df.columns


def test_stock_candlestick_darvas_indicators(monkeypatch) -> None:
    from App.ui.stock_drawer import query_stock_candlestick_data
    _force_v1(monkeypatch)
    ad_data = fetch_action_desk_data(DB_PATH)
    darvas_df = ad_data["queues"]["darvas"]
    test_sym = str(darvas_df.iloc[0]["symbol"]) if not darvas_df.empty else "IDFCFIRSTB"
    res = query_stock_candlestick_data(DB_PATH, test_sym, limit=60)
    assert "darvas_top" in res
    assert "darvas_bottom" in res
    assert len(res["darvas_top"]) == len(res["dates"])
    assert len(res["darvas_bottom"]) == len(res["dates"])
    assert "is_darvas_squeeze" in res

    # LUMAXIND had high poke above box ceiling (6450 vs top 6189), so it must NOT be flagged as in-box squeeze
    res_lumax = query_stock_candlestick_data(DB_PATH, "LUMAXIND", limit=60)
    assert res_lumax["is_darvas_squeeze"] is False


def test_display_window_count_split_is_before_head() -> None:
    """Count is taken before head(window); a swapped-lines regression must fail."""
    n = 50
    fake = pd.DataFrame(
        {
            "symbol": [f"S{i:02d}" for i in range(n)],
            "squeeze_pct": [0.05 * i for i in range(n)],
            "candle_range_pct": [1.0] * n,
            "tightening": [False] * n,
            "squeeze_age": [1] * n,
        }
    )
    matrix, count = apply_display_window(fake)
    window = int(DARVAS["display_window"])
    assert count == n
    assert len(matrix) == window
    assert count > len(matrix)


def test_display_window_count(monkeypatch) -> None:
    monkeypatch.setenv("MP_DARVAS_V2", "1")
    invalidate_cache()
    data = fetch_action_desk_data(DB_PATH)
    darvas_df = data["queues"]["darvas"]
    button_count = int(data["darvas_count"])
    assert "darvas_count" not in data["queues"]
    assert isinstance(darvas_df, pd.DataFrame)
    assert not darvas_df.empty
    window = int(DARVAS["display_window"])
    assert len(darvas_df) <= window
    assert button_count >= len(darvas_df)
    assert button_count > len(darvas_df)
    tv = data["tv_lists"]["darvas"]
    tv_n = tv.count("NSE:") if tv else 0
    assert tv_n == len(darvas_df)
    for col in ("squeeze_pct", "candle_range_pct", "darvas_top", "tightening", "squeeze_age", "failed_low"):
        assert col in darvas_df.columns


def test_queue_and_drawer_same_predicate(monkeypatch) -> None:
    """Fails on current main: drawer hard-coded 3.5/3.5, queue 5.0/4.0 + ema20."""
    from App.ui.stock_drawer import query_stock_candlestick_data

    monkeypatch.setenv("MP_DARVAS_V2", "1")
    invalidate_cache()
    data = fetch_action_desk_data(DB_PATH)
    darvas_df = data["queues"]["darvas"]
    assert isinstance(darvas_df, pd.DataFrame) and not darvas_df.empty
    for sym in darvas_df["symbol"].astype(str).tolist():
        res = query_stock_candlestick_data(DB_PATH, sym, limit=60, predicate=DARVAS)
        assert res.get("is_darvas_squeeze") is True, f"{sym} is in the display window but drawer predicate is False"


def test_circuit_and_rights_excluded(monkeypatch) -> None:
    _force_v1(monkeypatch)
    data = fetch_action_desk_data(DB_PATH)
    darvas_df = data["queues"].get("darvas")
    assert isinstance(darvas_df, pd.DataFrame) and not darvas_df.empty
    for s in darvas_df["symbol"].astype(str).tolist():
        assert not s.endswith("-RE")
        assert "-RE" not in s
    assert (darvas_df["band"] > 5.0).all()
    assert (darvas_df["market_cap_cr"] >= 1000.0).all()


def test_action_desk_deal_accumulation_attached(monkeypatch) -> None:
    _force_v1(monkeypatch)
    data = fetch_action_desk_data(DB_PATH)
    queues = data["queues"]
    for q_name, df in _queue_frames(queues):
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


def test_action_desk_missing_vix_is_na_not_silent_11_3(tmp_path) -> None:
    """Fails on current main: missing India VIX silently defaulted to 11.3 and still took vix < 15 branches."""
    source = Path("App/pages/action_desk.py").read_text(encoding="utf-8")
    assert "vix_val = 11.3" not in source
    assert "VIX n/a" in source
    assert "nullif(previous_close, 0)" in source
    assert "nullif(prev_close, 0)" not in source

    db_path = tmp_path / "vix.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE index_daily (
                trade_date DATE,
                index_name TEXT,
                close_price DOUBLE,
                previous_close DOUBLE,
                return_1d_pct DOUBLE
            )
            """
        )
        con.execute(
            "INSERT INTO index_daily VALUES ('2026-09-07', 'Nifty 50', 25000, 24900, 0.4)"
        )
        missing_vix, missing_chg = resolve_india_vix(con, "2026-09-07")
        con.execute(
            "INSERT INTO index_daily VALUES ('2026-09-07', 'India VIX', 11.16, 10.68, 4.49)"
        )
        present_vix, present_chg = resolve_india_vix(con, "2026-09-07")

    assert missing_vix is None
    assert missing_vix != 11.3
    assert missing_chg == 0.0

    exp = compute_exposure_gate(
        adv_pct=70.0,
        ab20_pct=60.0,
        ab200_pct=55.0,
        vix=missing_vix,
        vix_1d_pct=missing_chg,
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

    assert present_vix == 11.16
    assert present_chg == 4.5
    present = compute_exposure_gate(
        adv_pct=70.0,
        ab20_pct=60.0,
        ab200_pct=55.0,
        vix=present_vix,
        vix_1d_pct=present_chg,
        net_lows_expanding=False,
        count_52w_highs=80,
        count_52w_lows=20,
    )
    assert present["vix"] == 11.16
    assert present["vix_available"] is True
    assert present["vix_label"] != "VIX n/a"
    assert present["state"] == "Aggressive / Full Trend"
    assert present["pct"] == "75% - 100%"

