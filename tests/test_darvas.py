"""Unit tests for Darvas Box indicator and 10 EMA squeeze logic."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from datetime import date
from pathlib import Path

from App.indicators.darvas import (
    DARVAS,
    calculate_darvas_box,
    calendar_friday,
    compute_darvas_metrics,
    darvas_weekly_enabled,
    evaluate_squeeze_bar,
    is_darvas_10ema_squeeze,
    is_darvas_10ema_squeeze_legacy,
    last_completed_week,
    squeeze_frame,
    week_complete,
    week_end_session,
    weekly_ohlc,
)


def test_darvas_box_minimum_bars():
    highs = np.array([10, 11, 12])
    lows = np.array([9, 10, 11])
    top, bot = calculate_darvas_box(highs, lows, boxp=5)
    assert len(top) == 3
    assert np.all(np.isnan(top))
    assert np.all(np.isnan(bot))


def test_darvas_box_trigger_confirmation():
    # Bar 5 makes high=20, then 3 bars stay below 20
    highs = np.array([10, 12, 11, 13, 14, 20, 18, 17, 16, 15])
    lows = np.array([8, 10, 9, 11, 12, 16, 15, 14, 13, 12])
    top, bot = calculate_darvas_box(highs, lows, boxp=5)

    # After bar index 5 (which made new high of 20),
    # 3 bars later (index 8), top box confirms at 20.0
    assert top[8] == 20.0
    assert top[9] == 20.0
    # Bottom box should be lowest low of the last 5 bars (lows[4:9] -> min is 12)
    assert bot[8] == 12.0


def test_darvas_box_persists_beyond_45_bars():
    """A box confirmed at the start of the series must still be present 80 bars later."""
    highs = np.array([10, 12, 11, 13, 14, 20, 18, 17, 16] + [15.0] * 80, dtype=float)
    lows = np.array([8, 10, 9, 11, 12, 16, 15, 14, 13] + [13.0] * 80, dtype=float)
    top, bot = calculate_darvas_box(highs, lows, boxp=5)
    assert top[8] == 20.0
    assert top[-1] == 20.0
    assert bot[-1] == 12.0
    assert len(highs) > 45

    # The 45-session miss: computing the box only on the last 45 bars drops the confirm.
    top_tail, _ = calculate_darvas_box(highs[-45:], lows[-45:], boxp=5)
    assert np.isnan(top_tail[-1])


def test_darvas_10ema_squeeze_criteria():
    # Squeezed & full OHLC inside box: top=100, ema10=98, O=98.5, H=99.5, L=98.2, C=99.0
    # Range = (99.5 - 98.2)/99.0 = 1.31% (near range)
    assert is_darvas_10ema_squeeze(
        close=99.0, top_box=100.0, bottom_box=92.0, ema10=98.0,
        high=99.5, low=98.2, open_price=98.5,
        max_squeeze_pct=3.5, max_candle_range_pct=3.5, require_ohlc_inside=True
    )

    # Rejection: High exceeds TopBox (pierced ceiling, not inside box)
    assert not is_darvas_10ema_squeeze(
        close=99.0, top_box=100.0, bottom_box=92.0, ema10=98.0,
        high=102.5, low=98.2, open_price=98.5,
        max_squeeze_pct=3.5, require_ohlc_inside=True
    )

    # Rejection: Candle range too wide (> 3.5%, not near range)
    assert not is_darvas_10ema_squeeze(
        close=99.0, top_box=100.0, bottom_box=92.0, ema10=98.0,
        high=100.0, low=95.0, open_price=98.0,
        max_squeeze_pct=3.5, max_candle_range_pct=3.5, require_ohlc_inside=True
    )

    # Rejection: Low breaks below 10 EMA support (over the 1.5% failed-low cap)
    assert not is_darvas_10ema_squeeze(
        close=99.0, top_box=100.0, bottom_box=92.0, ema10=98.0,
        high=99.5, low=94.0, open_price=98.5,
        max_squeeze_pct=3.5, require_ohlc_inside=True
    )

    # Rejection: Spread too wide (top=100, ema10=90 -> 10% spread)
    assert not is_darvas_10ema_squeeze(
        close=95.0, top_box=100.0, bottom_box=85.0, ema10=90.0,
        max_squeeze_pct=3.5
    )


def test_darvas_squeeze_real_examples_and_rejections():
    """Verify exact real market examples: ROSSTECH, NPST, EXPLEOSOL, CHALET must PASS; NTPC, RHIM must FAIL."""
    # 1. ROSSTECH (PASS): Squeezed 4.41%, 10EMA > 20EMA, OHLC inside [1120.37, 1172.0]
    assert is_darvas_10ema_squeeze(
        close=1148.2, top_box=1172.0, bottom_box=1057.95, ema10=1120.37,
        high=1172.0, low=1139.6, open_price=1156.3, ema20=1098.06
    )

    # 2. NPST (PASS): Squeezed 4.65%, 10EMA > 20EMA, OHLC inside [1682.82, 1764.8]
    assert is_darvas_10ema_squeeze(
        close=1740.4, top_box=1764.8, bottom_box=1561.8, ema10=1682.82,
        high=1746.8, low=1691.2, open_price=1713.8, ema20=1646.14
    )

    # 3. EXPLEOSOL (PASS): Squeezed 4.61%, 10EMA > 20EMA, OHLC inside [884.21, 926.9]
    assert is_darvas_10ema_squeeze(
        close=899.55, top_box=926.9, bottom_box=849.0, ema10=884.21,
        high=922.0, low=895.0, open_price=910.45, ema20=872.78
    )

    # 4. CHALET (PASS): Squeezed 4.93%, 10EMA > 20EMA, Low holds 10EMA (893.1 vs 893.65)
    assert is_darvas_10ema_squeeze(
        close=908.75, top_box=939.95, bottom_box=884.5, ema10=893.65,
        high=913.45, low=893.1, open_price=900.0, ema20=879.00
    )

    # 5. NTPC (FAIL): 10EMA < 20EMA (downtrend: 332.27 < 335.14), Low & Close < 10EMA
    assert not is_darvas_10ema_squeeze(
        close=332.0, top_box=344.45, bottom_box=323.5, ema10=332.27,
        high=333.8, low=330.35, open_price=332.5, ema20=335.14
    )

    # 6. RHIM (FAIL): 10EMA < 20EMA (downtrend: 372.55 < 377.45), Open & Low < 10EMA
    assert not is_darvas_10ema_squeeze(
        close=373.8, top_box=377.8, bottom_box=361.35, ema10=372.55,
        high=375.15, low=369.0, open_price=371.8, ema20=377.45
    )


def test_chalet_still_passes():
    """0.06% dip is a strict wick, not the 1% undercut fixture."""
    assert is_darvas_10ema_squeeze(
        close=908.75, top_box=939.95, bottom_box=884.5, ema10=893.65,
        high=913.45, low=893.1, open_price=900.0, ema20=879.00
    )


def test_ntpc_rhim_still_fail():
    assert not is_darvas_10ema_squeeze(
        close=332.0, top_box=344.45, bottom_box=323.5, ema10=332.27,
        high=333.8, low=330.35, open_price=332.5, ema20=335.14
    )
    assert not is_darvas_10ema_squeeze(
        close=373.8, top_box=377.8, bottom_box=361.35, ema10=372.55,
        high=375.15, low=369.0, open_price=371.8, ema20=377.45
    )


def test_failed_low_1pct_open_below():
    """Wick may poke 1% below ema_floor if close holds; open-floor is dropped in v2."""
    ema10 = 100.0
    kwargs = dict(
        close=102.0,
        top_box=104.0,
        bottom_box=90.0,
        ema10=ema10,
        high=103.0,
        low=0.99 * ema10,
        open_price=ema10 * 0.994,
        ema20=98.5,
        max_squeeze_pct=5.0,
        max_candle_range_pct=4.0,
        require_ohlc_inside=True,
    )
    assert kwargs["open_price"] < ema10 * 0.995
    assert is_darvas_10ema_squeeze(**kwargs) is True
    assert is_darvas_10ema_squeeze_legacy(**kwargs) is False


def test_failed_low_over_cap_fails():
    ema10 = 100.0
    assert not is_darvas_10ema_squeeze(
        close=102.0,
        top_box=104.0,
        bottom_box=90.0,
        ema10=ema10,
        high=103.0,
        low=ema10 * 0.984,
        open_price=101.0,
        ema20=98.5,
        max_squeeze_pct=5.0,
        max_candle_range_pct=4.0,
    )


def test_stacked_ema_floor_uses_min_10_20():
    """Wick through 10 EMA, above 20 EMA, close above 10 → True when stacked."""
    ema10 = 100.0
    ema20 = 99.7  # |100-99.7|/100 = 0.3% <= 0.4%, and 10 >= 20 * 0.995
    low = 99.85  # through 10, above 20
    state = evaluate_squeeze_bar(
        close=99.9,
        top_box=104.0,
        bottom_box=90.0,
        ema10=ema10,
        high=103.0,
        low=low,
        open_price=100.2,
        ema20=ema20,
        max_squeeze_pct=5.0,
        max_candle_range_pct=4.0,
    )
    assert state["stacked"] is True
    assert state["ema_floor"] == pytest.approx(min(ema10, ema20))
    assert low < ema10 and low > ema20
    assert state["qualifies"] is True


def test_is_darvas_reads_cfg_when_max_kwargs_none():
    """cfg caps apply when max_squeeze_pct / max_candle_range_pct are left None."""
    kwargs = dict(
        close=97.5,
        top_box=100.0,
        bottom_box=90.0,
        ema10=95.8,
        high=98.0,
        low=96.0,
        open_price=96.5,
        ema20=95.5,
    )
    squeeze = ((100.0 - 95.8) / 100.0) * 100.0
    assert 3.5 < squeeze <= 5.0
    assert is_darvas_10ema_squeeze(**kwargs) is True
    assert is_darvas_10ema_squeeze(**kwargs, cfg={"max_squeeze_pct": 3.5}) is False


def test_legacy_drawer_queue_predicate_split():
    """Fails on current main if queue 5.0/4.0 and drawer 3.5/3.5 are treated as one predicate.

    A 4.2% coil is queue-true and old-drawer-false. v2 uses DARVAS for both.
    """
    kwargs = dict(
        close=97.5,
        top_box=100.0,
        bottom_box=90.0,
        ema10=95.8,
        high=98.0,
        low=96.0,
        open_price=96.5,
        ema20=95.5,
    )
    squeeze = ((100.0 - 95.8) / 100.0) * 100.0
    assert 3.5 < squeeze <= 5.0
    assert is_darvas_10ema_squeeze_legacy(
        **kwargs, max_squeeze_pct=5.0, max_candle_range_pct=4.0, require_ohlc_inside=True
    ) is True
    drawer_kwargs = {k: v for k, v in kwargs.items() if k != "ema20"}
    assert is_darvas_10ema_squeeze_legacy(
        **drawer_kwargs, max_squeeze_pct=3.5, max_candle_range_pct=3.5, require_ohlc_inside=True
    ) is False
    assert is_darvas_10ema_squeeze(
        **kwargs,
        max_squeeze_pct=DARVAS["max_squeeze_pct"],
        max_candle_range_pct=DARVAS["max_range_pct"],
        require_ohlc_inside=True,
    ) is True


def _coil_after_box(n_coil: int = 10) -> pd.DataFrame:
    """Confirmed top=20 at index 8, then n_coil inside-box bars with shrinking spread."""
    n_head = 10
    n = n_head + n_coil
    highs = np.array([10, 12, 11, 13, 14, 20, 18, 17, 16, 15] + [19.6] * n_coil, dtype=float)
    lows = np.array([8, 10, 9, 11, 12, 16, 15, 14, 13, 12] + [19.35] * n_coil, dtype=float)
    opens = np.array([9, 11, 10, 12, 13, 18, 16, 15, 14, 13] + [19.4] * n_coil, dtype=float)
    closes = np.array([9.5, 11.5, 10.5, 12.5, 13.5, 19, 17, 16, 15, 14] + [19.5] * n_coil, dtype=float)
    ema10 = np.full(n, 18.0, dtype=float)
    ema20 = np.full(n, 17.8, dtype=float)
    # Last 6 coil bars: 4.8% -> 3.1% squeeze vs top=20 → ema 19.04 -> 19.38
    ema10[-6:] = np.array([19.04, 19.10, 19.16, 19.22, 19.30, 19.38])
    ema20[-6:] = ema10[-6:] - 0.18
    dates = pd.bdate_range("2025-01-02", periods=n)
    return pd.DataFrame(
        {
            "symbol": "TESTCOIL",
            "trade_date": dates,
            "open_price": opens,
            "high_price": highs,
            "low_price": lows,
            "close_price": closes,
            "ema_10": ema10,
            "ema_20": ema20,
        }
    )


def test_tightening_column():
    frame = squeeze_frame(_coil_after_box(10), timeframe="D")
    assert not frame.empty
    row = frame.iloc[0]
    assert row["qualifies"]
    assert abs(row["squeeze_pct"] - 3.1) < 0.05
    assert abs(row["squeeze_pct_5d_ago"] - 4.8) < 0.05
    assert pd.isna(row["squeeze_pct_5w_ago"])
    assert bool(row["tightening"]) is True
    assert int(row["squeeze_age"]) >= 2


def test_squeeze_frame_columns_and_unclipped_spread():
    frame = squeeze_frame(_coil_after_box(10), timeframe="D")
    for col in (
        "symbol", "darvas_top", "darvas_bottom", "squeeze_pct", "squeeze_pct_5d_ago",
        "squeeze_pct_5w_ago",
        "tightening", "squeeze_age", "failed_low", "ema_floor", "candle_range_pct",
        "box_age_sessions", "qualifies",
    ):
        assert col in frame.columns
    row = frame.iloc[0]
    raw = ((row["darvas_top"] - 19.38) / row["darvas_top"]) * 100.0
    assert row["squeeze_pct"] == pytest.approx(raw, abs=1e-9)
    assert row["squeeze_pct"] != 5.0 or raw == 5.0


def test_darvas_reexport_is_canonical_module():
    import App.indicators.darvas as app_d
    import Scripts.darvas_squeeze as scripts_d

    assert app_d.calculate_darvas_box is scripts_d.calculate_darvas_box
    assert app_d.is_darvas_10ema_squeeze is scripts_d.is_darvas_10ema_squeeze
    assert app_d.squeeze_frame is scripts_d.squeeze_frame
    assert app_d.weekly_ohlc is scripts_d.weekly_ohlc
    assert app_d.last_completed_week is scripts_d.last_completed_week
    assert app_d.DARVAS is scripts_d.DARVAS


def test_compute_darvas_metrics_series_length():
    highs = np.array([10, 12, 11, 13, 14, 20, 18, 17, 16, 15], dtype=float)
    lows = np.array([8, 10, 9, 11, 12, 16, 15, 14, 13, 12], dtype=float)
    closes = (highs + lows) / 2.0
    metrics = compute_darvas_metrics(closes, highs, lows)
    assert len(metrics["top_box"]) == 10
    assert len(metrics["squeeze_pct"]) == 10


def _ohlc_frame(dates, *, symbol="WKLY", high=None, low=None, open_=None, close=None) -> pd.DataFrame:
    dates = pd.to_datetime(list(dates))
    n = len(dates)
    close_arr = np.asarray(close if close is not None else np.linspace(100.0, 100.0 + n - 1, n), dtype=float)
    high_arr = np.asarray(high if high is not None else close_arr + 1.0, dtype=float)
    low_arr = np.asarray(low if low is not None else close_arr - 1.0, dtype=float)
    open_arr = np.asarray(open_ if open_ is not None else close_arr, dtype=float)
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": dates,
            "open_price": open_arr,
            "high_price": high_arr,
            "low_price": low_arr,
            "close_price": close_arr,
            "volume": np.full(n, 1000.0),
        }
    )


def test_weekly_fixture_research_wednesday():
    """§8.4 fixture A: Friday still in the frame; as_of Wednesday → no current-week bar."""
    dates = pd.bdate_range("2026-08-31", "2026-09-04")
    assert pd.Timestamp("2026-09-04") in dates
    as_of = date(2026, 9, 2)
    frame = _ohlc_frame(dates)
    weekly = weekly_ohlc(frame, as_of=as_of)
    sessions = [d.date() for d in dates]
    assert calendar_friday(as_of) == date(2026, 9, 4)
    assert week_complete(as_of, as_of) is False
    assert last_completed_week(sessions, as_of) is None
    assert weekly.empty
    assert not (pd.to_datetime(weekly["trade_date"]).dt.date == date(2026, 9, 4)).any() if not weekly.empty else True
    assert not (pd.to_datetime(weekly["trade_date"]).dt.date == date(2026, 9, 2)).any() if not weekly.empty else True


def test_weekly_fixture_desk_wednesday_truncated():
    """§8.4 fixture B (production path): no Friday 2026-09-04; as_of=Wed.

    Sessions 2026-08-24..08-28 PLUS 08-31..09-02. Assert no current-week bar and
    last_completed_week == 2026-08-28. as_of == current week_end_session must NOT complete.
    """
    prior = pd.bdate_range("2026-08-24", "2026-08-28")
    current = pd.bdate_range("2026-08-31", "2026-09-02")
    dates = prior.append(current)
    assert pd.Timestamp("2026-09-04") not in dates
    as_of = date(2026, 9, 2)
    frame = _ohlc_frame(dates)
    weekly = weekly_ohlc(frame, as_of=as_of)
    sessions = [d.date() for d in dates]
    current_period = pd.Period(as_of, freq="W-FRI")
    wes_current = week_end_session(current_period, sessions)
    assert wes_current == as_of
    assert week_complete(current_period, as_of) is False
    assert last_completed_week(sessions, as_of) == date(2026, 8, 28)
    ends = set(pd.to_datetime(weekly["trade_date"]).dt.date)
    assert date(2026, 8, 28) in ends
    assert date(2026, 9, 2) not in ends
    assert date(2026, 9, 4) not in ends
    assert len(weekly) == 1


def test_weekly_fixture_friday_full_week():
    """§8.4 fixture C: trading Friday completes; high = max(Mon..Fri); close = Friday."""
    dates = pd.bdate_range("2026-08-31", "2026-09-04")
    as_of = date(2026, 9, 4)
    highs = [101.0, 102.0, 115.0, 104.0, 105.0]
    closes = [100.0, 101.0, 103.0, 104.0, 108.0]
    frame = _ohlc_frame(dates, high=highs, close=closes)
    weekly = weekly_ohlc(frame, as_of=as_of)
    sessions = [d.date() for d in dates]
    assert as_of.weekday() == 4
    assert last_completed_week(sessions, as_of) == date(2026, 9, 4)
    assert len(weekly) == 1
    row = weekly.iloc[0]
    assert pd.Timestamp(row["trade_date"]).date() == date(2026, 9, 4)
    assert float(row["high_price"]) == 115.0
    assert float(row["close_price"]) == 108.0
    assert float(row["open_price"]) == float(closes[0])


def test_weekly_holiday_friday_completes_monday():
    """§8.4 fixture D: holiday Friday completes Monday; week_end_session = Thursday."""
    thu_dates = pd.to_datetime(["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"])
    mon_dates = pd.to_datetime(["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-12"])
    closes_thu = [10.0, 11.0, 12.0, 77.0]
    closes_mon = [10.0, 11.0, 12.0, 77.0, 99.0]
    as_of_thu = date(2026, 10, 8)
    as_of_mon = date(2026, 10, 12)
    cal_fri = date(2026, 10, 9)
    assert calendar_friday(as_of_thu) == cal_fri
    assert calendar_friday(as_of_mon) == date(2026, 10, 16)

    weekly_thu = weekly_ohlc(_ohlc_frame(thu_dates, close=closes_thu), as_of=as_of_thu)
    assert week_complete(as_of_thu, as_of_thu) is False
    assert last_completed_week([d.date() for d in thu_dates], as_of_thu) is None
    assert weekly_thu.empty

    weekly_mon = weekly_ohlc(_ohlc_frame(mon_dates, close=closes_mon), as_of=as_of_mon)
    sessions_mon = [d.date() for d in mon_dates]
    holiday_period = pd.Period(date(2026, 10, 8), freq="W-FRI")
    assert week_complete(holiday_period, as_of_mon) is True
    assert week_end_session(holiday_period, sessions_mon) == date(2026, 10, 8)
    assert last_completed_week(sessions_mon, as_of_mon) == date(2026, 10, 8)
    assert len(weekly_mon) == 1
    row = weekly_mon.iloc[0]
    assert pd.Timestamp(row["trade_date"]).date() == date(2026, 10, 8)
    assert float(row["close_price"]) == 77.0
    assert float(row["close_price"]) != 99.0


def test_squeeze_frame_weekly_evaluates_last_completed_week():
    """Weekly squeeze uses completed weeks only; Wednesday as_of does not emit a current-week bar."""
    weeks = []
    # 8 full weeks Mon–Fri ending 2026-08-28, then Mon–Wed of next week.
    start = pd.Timestamp("2026-07-06")  # Monday
    for i in range(8):
        weeks.extend(pd.bdate_range(start + pd.Timedelta(days=7 * i), periods=5))
    weeks.extend(pd.bdate_range("2026-08-31", "2026-09-02"))
    dates = pd.DatetimeIndex(weeks)
    as_of = date(2026, 9, 2)
    frame = _ohlc_frame(dates)
    weekly = weekly_ohlc(frame, as_of=as_of)
    ends = list(pd.to_datetime(weekly["trade_date"]).dt.date)
    assert date(2026, 8, 28) == ends[-1]
    assert date(2026, 9, 2) not in ends
    assert date(2026, 9, 4) not in ends
    sq = squeeze_frame(frame, timeframe="W", as_of=as_of)
    daily_sq = squeeze_frame(frame, timeframe="D", as_of=as_of)
    assert list(sq.columns) == list(daily_sq.columns)
    assert not sq.empty
    assert sq.iloc[0]["symbol"] == "WKLY"
    assert pd.isna(sq.iloc[0]["squeeze_pct_5d_ago"])
    assert "squeeze_pct_5w_ago" in sq.columns


def test_wema_200_min_periods_unchanged_and_wema_20_owned():
    src = Path("Scripts/build_database.py").read_text(encoding="utf-8")
    assert "ewm(span=200, adjust=False, min_periods=10)" in src
    assert "ewm(span=20, adjust=False, min_periods=20)" in src
    assert "g[\"wema_20\"]" in src or "g['wema_20']" in src
    assert darvas_weekly_enabled() is False
    mig = Path("Scripts/migrations.py").read_text(encoding="utf-8")
    assert "wema_20" in mig
    assert "CURRENT_SCHEMA_VERSION = 7" in mig
    assert "INSERT INTO schema_migrations(version) VALUES (8)" not in mig
    assert "_MIGRATION_8" not in mig


def test_no_ca_box_reset_in_weekly_path():
    src = Path("Scripts/darvas_squeeze.py").read_text(encoding="utf-8")
    assert "price_adjustment_factors" not in src
    assert "corporate_actions" not in src
