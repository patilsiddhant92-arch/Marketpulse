from __future__ import annotations

import numpy as np
import pandas as pd

from Scripts.indicators import sma
from Scripts.minervini_geometry import Contraction, TSequence, detect_contractions, evaluate_trend_template, t_graph_svg


def test_sma_is_rolling_mean() -> None:
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    actual = sma(close, 3)
    expected = close.rolling(3, min_periods=3).mean()
    pd.testing.assert_series_equal(actual, expected)


def _path_ohlc() -> pd.DataFrame:
    """Stage-2 advance then 25% / 12% / 6% pullbacks with 5-bar fractal extrema."""
    segments = [
        (8, 80, 82),
        (12, 82, 130),
        (12, 130, 97.5),
        (10, 97.5, 128),
        (10, 128, 112.6),
        (10, 112.6, 126),
        (8, 126, 118.4),
        (6, 118.4, 125),
    ]
    close = []
    for n, a, b in segments:
        close.extend(np.linspace(a, b, n, endpoint=False).tolist())
    close.append(125.0)
    close = np.array(close)
    high = close + 0.4
    low = close - 0.4
    # Force unique fractal peaks/troughs at segment joints
    joints = np.cumsum([s[0] for s in segments])
    for j, (_n, a, b) in zip(joints, segments):
        if j >= len(close):
            continue
        if b > a:
            high[j - 1] = b + 0.8
            high[max(0, j - 2)] = b
            high[min(len(high) - 1, j)] = b
        else:
            low[j - 1] = b - 0.8
            low[max(0, j - 2)] = b
            low[min(len(low) - 1, j)] = b
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2025-01-01", periods=len(close), freq="B"),
            "open_price": close,
            "high_price": high,
            "low_price": low,
            "close_price": close,
            "volume": np.linspace(200, 40, len(close)),
        }
    )


def test_detect_contractions_names_decreasing_ts() -> None:
    seq = detect_contractions(_path_ohlc())
    assert len(seq.contractions) >= 1
    depths = [c.depth_pct for c in seq.contractions]
    assert all(depths[i] > depths[i + 1] for i in range(len(depths) - 1))
    assert seq.footprint.endswith("T")
    svg = t_graph_svg(seq)
    assert "1T" in svg
    assert "PIVOT" in svg


def test_t_graph_svg_draws_named_ts() -> None:
    seq = TSequence(
        contractions=[
            Contraction("1T", None, None, None, 100, 75, 25, 20, 0.9),
            Contraction("2T", None, None, None, 98, 86, 12, 12, 0.6),
            Contraction("3T", None, None, None, 97, 91, 6, 10, 0.4),
        ],
        pivot=97,
        stop=91,
        weeks=8,
        footprint="8W 25/6 3T",
    )
    svg = t_graph_svg(seq)
    assert "1T 25%" in svg
    assert "2T 12%" in svg
    assert "3T 6%" in svg
    assert "PIVOT" in svg
    assert "STOP" in svg


def test_expanding_swing_ends_sequence() -> None:
    seq = detect_contractions(_path_ohlc())
    # After a valid T, a deeper pullback must not be appended.
    deeper = _path_ohlc()
    extra = pd.DataFrame(
        {
            "trade_date": pd.date_range(deeper["trade_date"].iloc[-1] + pd.Timedelta(days=1), periods=16, freq="B"),
            "open_price": np.linspace(125, 80, 16),
            "high_price": np.linspace(126, 82, 16),
            "low_price": np.linspace(124, 78, 16),
            "close_price": np.linspace(125, 80, 16),
            "volume": np.ones(16) * 80,
        }
    )
    seq = detect_contractions(pd.concat([deeper, extra], ignore_index=True))
    if seq.contractions:
        assert seq.contractions[-1].depth_pct < 30


def test_trend_template_counts_eight_sma_checks() -> None:
    ctx = {
        "close": 120,
        "sma_50": 110,
        "sma_150": 100,
        "sma_200": 90,
        "sma_200_rising": True,
        "away_52w_low_pct": 40,
        "distance_below_52w": 10,
        "rs_percentile": 80,
    }
    result = evaluate_trend_template(ctx)
    assert result["pass_n"] == 8
    assert result["pass_all"] is True
    assert result["label"] == "8/8"


def test_desk_is_home_and_momentum_untouched() -> None:
    from pathlib import Path

    app = Path("App/app.py").read_text(encoding="utf-8")
    desk = Path("App/pages/desk.py").read_text(encoding="utf-8")
    assert '("Desk", desk_page, "desk", True)' in app
    assert '("Momentum", special_watchlist_page, "scanner", False)' in app
    assert "special_watchlist_page" in app
    assert "What moved today" in desk
    assert "Turnover" in desk
    assert "candidate_state" not in desk
    assert "load_decision_snapshot" not in desk
