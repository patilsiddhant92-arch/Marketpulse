"""P1 Morning honesty: gate single-owner + brief fields + health default."""
from __future__ import annotations

from Scripts.desk_contract import EXPOSURE_RULES, brief_fields_from_gate, match_exposure
from pathlib import Path


def test_brief_fields_mirror_gate_pct_and_state():
    gate = match_exposure(
        {
            "adv_pct": 36.0,
            "ab20_pct": 36.0,
            "ab200_pct": 38.0,
            "vix": 12.0,
            "vix_spike": False,
            "net_lows_expanding": True,
            "count_52w_lows": 138,
            "count_52w_highs": 67,
            "vix_1d_pct": 4.0,
        }
    )
    brief = brief_fields_from_gate(gate)
    assert brief["exposure_pct"] == gate["pct"]
    assert brief["exposure_state"] == gate["state"]
    assert gate["pct"] in brief["posture_title"]
    assert gate["state"] in brief["posture_title"]
    # Must not resurrect the old Overview-only 25–40% band wording
    assert "25% – 40%" not in brief["posture_title"]
    assert "60% – 75% Cash" not in brief["posture_title"]


def test_brief_fields_cover_every_exposure_rule_id():
    for rule in EXPOSURE_RULES:
        brief = brief_fields_from_gate(
            {"id": rule["id"], "pct": rule["pct"], "state": rule["state"], "guidance": rule["guidance"]}
        )
        assert brief["exposure_id"] == rule["id"]
        assert rule["pct"] in brief["posture_title"]
        assert "Cash" in brief["cash_recommendation"]


def test_market_health_strip_accepts_expanded_kwarg():
    import inspect
    from App.ui.market_health import render_market_health_strip

    sig = inspect.signature(render_market_health_strip)
    assert "expanded" in sig.parameters
    assert sig.parameters["expanded"].default is True


def test_nav_weight_p14_morning_cluster_and_demote_classes():
    """P1.4: Morning tabs clustered; Overview/Watchlists demoted; Lab/Ops quieter CSS."""
    app = Path(__file__).resolve().parents[1] / "App" / "app.py"
    styles = Path(__file__).resolve().parents[1] / "App" / "ui" / "styles.py"
    app_src = app.read_text(encoding="utf-8")
    styles_src = styles.read_text(encoding="utf-8")
    start = app_src.index("tab_specs = [")
    end = app_src.index("]", start)
    block = app_src[start:end]
    names = []
    for label in (
        "Action Desk",
        "Overview",
        "Sector Intel",
        "Market Trends",
        "Momentum",
        "Deals",
        "Portfolio",
        "Watchlists",
        "Info",
    ):
        assert f'"{label}"' in block, label
        names.append((block.index(f'"{label}"'), label))
    # Template retired from primary nav (legacy only)
    assert '"Template"' not in block or "sma-template" not in block.split("Watchlists")[0]
    ordered = [n for _, n in sorted(names)]
    assert ordered[:3] == ["Action Desk", "Overview", "Sector Intel"]
    assert ordered.index("Watchlists") > ordered.index("Portfolio")
    assert '"morning-secondary"' in block
    assert '"ops-demoted"' in block
    assert "mp-tab-demoted" in app_src and "mp-tab-demoted" in styles_src
    assert "mp-tab-group-start" in styles_src



def test_overview_gate_args_include_vix_and_52w():
    """Commentary must not call breadth-only inputs (VIX None -> false risk_off)."""
    from App.ui import market_health as mh
    src = Path(mh.__file__).read_text(encoding="utf-8")
    assert "def load_exposure_gate_args" in src
    assert "resolve_india_vix" in src
    assert "count_52w_extremes" in src
    ce = Path(__file__).resolve().parents[1] / "App" / "market_commentary_engine.py"
    ce_src = ce.read_text(encoding="utf-8")
    assert "load_exposure_gate_args" in ce_src
    assert "load_exposure_inputs(" not in ce_src


def test_live_db_overview_gate_matches_action_desk():
    """On the live DuckDB, Overview brief must match AD Selective when VIX is present."""
    import duckdb
    from config import DB_PATH
    from App.ui.market_health import load_exposure_gate_args
    from Scripts.desk_contract import brief_fields_from_gate, match_exposure

    if not Path(DB_PATH).exists():
        return
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        args = load_exposure_gate_args(con)
    assert args.get("vix") is not None, "India VIX should exist for honesty check"
    gate = match_exposure(args)
    brief = brief_fields_from_gate(gate)
    assert gate["pct"] in brief["posture_title"]
    assert gate["state"] in brief["posture_title"]
    # Live tape on 2026-09-11 is Selective / Caution, not risk_off
    assert gate["id"] != "risk_off" or args.get("vix") is None
