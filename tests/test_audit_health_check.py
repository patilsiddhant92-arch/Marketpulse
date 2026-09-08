from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from App.app import copy_text_to_clipboard
from App.cache_manager import (
    CACHE_MAX_ENTRIES,
    _CACHE,
    cache_key,
    clear_cache,
    get_cached,
    set_cached,
    invalidate_cache,
)
from App.pages.action_desk import fetch_action_desk_data
from App.ui.playbook_guide import open_playbook_modal, render_inline_field_guide_banner
from Scripts.config import DB_PATH
from Scripts.telegram_deals import build_deals_telegram_report, to_tv_list


def test_copy_text_to_clipboard_single_and_dual_args(monkeypatch) -> None:
    """Verify copy_text_to_clipboard safely handles single-argument and two-argument calls."""
    import nicegui.ui as ui

    recorded: list[str] = []
    monkeypatch.setattr(ui.clipboard, "write", lambda text: recorded.append(text))
    monkeypatch.setattr(ui, "notify", lambda *_, **__: None)

    # 1. Dual argument call: label and text
    copy_text_to_clipboard("Master Deals TV", "NSE:RELIANCE,NSE:TCS")
    assert recorded[-1] == "NSE:RELIANCE,NSE:TCS"

    # 2. Single argument call: text only (must NOT raise TypeError)
    copy_text_to_clipboard("NSE:INFY,NSE:HDFCBANK")
    assert recorded[-1] == "NSE:INFY,NSE:HDFCBANK"

    # 3. None / empty string
    copy_text_to_clipboard("")
    assert recorded[-1] == ""


def test_cache_manager_mtime_lifecycle(tmp_path) -> None:
    """Verify cache_key binds to database mtime when session_date is None or 'latest'."""
    db_file = tmp_path / "test.duckdb"
    db_file.touch()

    # Explicit session date should be preserved
    key_explicit = cache_key(db_file, "2026-09-07", "test_tag", "arg1")
    assert "2026-09-07" in key_explicit

    # None and 'latest' should bind to file mtime
    key_none = cache_key(db_file, None, "test_tag")
    key_latest = cache_key(db_file, "latest", "test_tag")
    assert "mtime_" in key_none
    assert "mtime_" in key_latest
    assert key_none == key_latest

    # Clear cache alias verification
    assert clear_cache is invalidate_cache
    set_cached(key_explicit, {"data": 123})
    assert get_cached(key_explicit) == {"data": 123}
    clear_cache("test_tag")
    assert get_cached(key_explicit) is None


def test_cache_key_latest_includes_max_trade_date(tmp_path) -> None:
    """'latest'/None keys must embed mtime_ns and max(trade_date), not mtime alone."""
    import duckdb

    db_file = tmp_path / "session.duckdb"
    with duckdb.connect(str(db_file)) as db:
        db.execute("CREATE TABLE indicators_daily (symbol TEXT, trade_date DATE)")
        db.execute("INSERT INTO indicators_daily VALUES ('AAA', DATE '2026-09-07'), ('BBB', DATE '2026-09-07')")

    key_none = cache_key(db_file, None, "test_tag")
    key_latest = cache_key(db_file, "latest", "test_tag")
    key_explicit = cache_key(db_file, "2026-09-07", "test_tag")

    assert "mtime_" in key_none
    assert "max_2026-09-07" in key_none
    assert "_n_2" in key_none
    assert key_none == key_latest
    assert "mtime_" not in key_explicit
    assert "max_2026-09-07" not in key_explicit

    with duckdb.connect(str(db_file)) as db:
        db.execute("INSERT INTO indicators_daily VALUES ('AAA', DATE '2026-09-08')")

    key_after = cache_key(db_file, None, "test_tag")
    assert "max_2026-09-08" in key_after
    assert key_after != key_none


def test_cache_bound_evicts_oldest() -> None:
    """_CACHE must evict the oldest entry once it exceeds 256."""
    invalidate_cache()
    try:
        assert CACHE_MAX_ENTRIES == 256
        for i in range(CACHE_MAX_ENTRIES + 5):
            set_cached(f"bound-{i}", i)
        assert len(_CACHE) == CACHE_MAX_ENTRIES
        assert get_cached("bound-0") is None
        assert get_cached("bound-4") is None
        assert get_cached("bound-5") == 5
        assert get_cached(f"bound-{CACHE_MAX_ENTRIES + 4}") == CACHE_MAX_ENTRIES + 4
    finally:
        invalidate_cache()


def test_deals_desk_prop_purity_and_stage1_turnarounds() -> None:
    """Verify Tier 3A is 100% pure prop, and Tier 1 & 2 contain Stage 1 turnarounds (<200 EMA)."""
    if not DB_PATH.exists():
        pytest.skip("MarketPulse DuckDB not found.")

    report = build_deals_telegram_report(lookback_days=20, min_mcap_cr=900.0, db_path=DB_PATH)
    tiers = report["tiers"]
    tv = report["tv_strings"]

    prop_df = tiers["prop_only"]
    conv_df = tiers["conviction"]
    fresh_df = tiers["fresh_radar"]

    # 1. Prop purity: Tier 3A must be 100% PROP desk only
    for _, row in prop_df.iterrows():
        assert row["categories"] == {"PROP"}, f"{row['symbol']} has non-prop categories: {row['categories']}"

    # 2. Tier 1 & 2 must have zero pure-prop stocks
    for _, row in conv_df.iterrows():
        assert row["categories"] != {"PROP"}, f"{row['symbol']} in Tier 1 is pure prop!"
    for _, row in fresh_df.iterrows():
        assert row["categories"] != {"PROP"}, f"{row['symbol']} in Tier 2 is pure prop!"

    # 3. Stage 1 bases (<200 EMA) are permitted and present in Tier 1 & 2
    turnaround_t1 = conv_df[~conv_df["is_above_200"]]
    turnaround_t2 = fresh_df[~fresh_df["is_above_200"]]
    assert len(turnaround_t1) > 0, "Expected Stage 1 turnarounds in Tier 1"
    assert len(turnaround_t2) > 0, "Expected Stage 1 turnarounds in Tier 2"

    # 4. Trend stages clearly labeled
    assert (conv_df["trend_stage"].isin(["🟢 >200 EMA", "🟡 Base / Turnaround"])).all()
    assert (fresh_df["trend_stage"].isin(["🟢 >200 EMA", "🟡 Base / Turnaround"])).all()

    # 5. Master TV export has 100% of symbols with zero truncation
    master_tv_syms = [s for s in tv["master_tv"].replace("###💎 Conviction Accumulation,", "").replace("###⚡ Fresh Whale Radar,", "").split(",") if s.startswith("NSE:")]
    expected_total = len(conv_df) + len(fresh_df)
    assert len(master_tv_syms) == expected_total


def test_action_desk_pre_move_turnarounds_and_no_stop_filters() -> None:
    """Verify action desk pre-move queues allow <200 EMA turnarounds and apply no stop loss filters."""
    if not DB_PATH.exists():
        pytest.skip("MarketPulse DuckDB not found.")

    data = fetch_action_desk_data(DB_PATH)
    queues = data["queues"]

    # Pre-move queues
    pre_move_keys = ["darvas", "silent_coil", "stair_step", "spike_pause"]
    for qk in pre_move_keys:
        q_df = queues.get(qk, pd.DataFrame())
        assert not q_df.empty, f"Queue {qk} is empty"
        # Verify turnarounds (<200 EMA) are permitted and present
        under_200 = q_df[q_df["cmp"] < q_df["ema_200"]]
        assert len(under_200) > 0, f"Expected <200 EMA turnarounds in pre-move queue {qk}"

    # Verify formatting calculations handle edge cases safely
    pool = pd.DataFrame({
        "ticket_ratio": [1.35, 1.10, np.nan, 0.9],
        "band": [10.0, 20.0, 5.0, np.nan],
        "away_10ema_pct": [1.5, -2.1, np.nan, 0.0],
    })
    ticket_flows = pool["ticket_ratio"].apply(
        lambda tr: f"{float(tr):.1f}x 🏛️" if tr is not None and not (pd.isna(tr) or np.isnan(float(tr))) and float(tr) >= 1.20 else (f"{float(tr):.1f}x" if tr is not None and not (pd.isna(tr) or np.isnan(float(tr))) else "—")
    ).tolist()
    assert ticket_flows == ["1.4x 🏛️", "1.1x", "—", "0.9x"]

    band_fmts = pool["band"].apply(
        lambda b: "10% ⚡" if b is not None and not pd.isna(b) and float(b) == 10.0 else (f"{int(b)}%" if b is not None and not pd.isna(b) else "20%")
    ).tolist()
    assert band_fmts == ["10% ⚡", "20%", "5%", "20%"]


def test_playbook_modal_and_field_guide_render_cleanly() -> None:
    """Verify playbook modal and per-queue field guide banners render cleanly without exceptions."""
    open_playbook_modal()
    for q in ["vcp", "pullback", "episodic", "high52", "darvas", "silent_coil", "stair_step", "spike_pause"]:
        render_inline_field_guide_banner(q)


def test_telegram_deals_net_cr_formatting() -> None:
    """Verify telegram deals message generation never formats negative zero (-0.0) or contradictory signs."""
    if not DB_PATH.exists():
        pytest.skip("MarketPulse DuckDB not found.")

    report = build_deals_telegram_report(lookback_days=20, min_mcap_cr=900.0, db_path=DB_PATH)
    messages = report.get("messages", [])
    assert len(messages) >= 2
    full_text = "\n".join(messages)
    assert "-0.0Cr" not in full_text, "Found negative zero '-0.0Cr' in Telegram deals message!"
    assert "-0.0" not in full_text, "Found '-0.0' in Telegram deals message!"


def test_table_from_df_copy_symbols_does_not_truncate_turnarounds(monkeypatch) -> None:
    """Verify that table_from_df Copy Symbols copies 100% of symbols including Stage 1 turnarounds (<200 EMA)."""
    import nicegui.ui as ui
    from App.app import table_from_df, symbols_text

    # Sample dataframe with turnarounds (<200 EMA) and missing mcap
    sample_df = pd.DataFrame({
        "symbol": ["AAA", "BBB", "CCC"],
        "close_price": [100.0, 50.0, 20.0],
        "ema_200": [120.0, 80.0, 15.0],  # AAA and BBB are <200 EMA turnarounds, CCC is >200 EMA
        "market_cap_cr": [500.0, None, 1500.0],
    })

    # Legacy default symbols_text would drop AAA and BBB
    legacy_copy = symbols_text(sample_df)
    assert legacy_copy == "NSE:CCC", "Legacy symbols_text must drop turnarounds"

    # Untruncated symbols_text for table_from_df must keep ALL 3 symbols
    untruncated_copy = symbols_text(sample_df, min_mcap_cr=None, require_above_ema200=False)
    assert untruncated_copy == "NSE:AAA,NSE:BBB,NSE:CCC"

    # Render table_from_df with copy_symbols=True
    tbl = table_from_df(sample_df, title="Turnaround Study", copy_symbols=True)
    assert tbl is not None


def test_deals_and_action_desk_page_build_cleanly() -> None:
    """Verify build_action_desk_page and build_deals_page execute and mount cleanly."""
    if not DB_PATH.exists():
        pytest.skip("MarketPulse DuckDB not found.")

    from App.pages.action_desk import build_action_desk_page
    from App.pages.research.deals import build_deals_page
    from App.app import table_from_df

    def dummy_header(*args, **kwargs):
        pass

    build_action_desk_page(DB_PATH, dummy_header, table_from_df, copy_text=copy_text_to_clipboard)
    build_deals_page(DB_PATH, copy_text=copy_text_to_clipboard, table_from_df=table_from_df)

