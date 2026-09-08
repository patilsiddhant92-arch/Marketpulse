"""Re-export Darvas Box helpers from Scripts.darvas_squeeze (canonical module)."""
from __future__ import annotations

try:
    from Scripts.darvas_squeeze import (
        DARVAS,
        WEEKLY_LOOKBACK_SESSIONS,
        apply_display_window,
        calculate_darvas_box,
        calendar_friday,
        completed_weeks,
        compute_darvas_metrics,
        darvas_v2_enabled,
        darvas_weekly_enabled,
        evaluate_squeeze_bar,
        is_darvas_10ema_squeeze,
        is_darvas_10ema_squeeze_legacy,
        last_completed_week,
        sort_qualifying_squeezes,
        squeeze_frame,
        week_complete,
        week_end_session,
        weekly_ohlc,
    )
except ImportError:
    import sys
    from pathlib import Path

    _scripts = Path(__file__).resolve().parents[2] / "Scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    from darvas_squeeze import (  # type: ignore
        DARVAS,
        WEEKLY_LOOKBACK_SESSIONS,
        calculate_darvas_box,
        calendar_friday,
        completed_weeks,
        compute_darvas_metrics,
        darvas_v2_enabled,
        darvas_weekly_enabled,
        apply_display_window,
        evaluate_squeeze_bar,
        is_darvas_10ema_squeeze,
        is_darvas_10ema_squeeze_legacy,
        last_completed_week,
        sort_qualifying_squeezes,
        squeeze_frame,
        week_complete,
        week_end_session,
        weekly_ohlc,
    )

__all__ = [
    "DARVAS",
    "WEEKLY_LOOKBACK_SESSIONS",
    "apply_display_window",
    "calculate_darvas_box",
    "calendar_friday",
    "completed_weeks",
    "compute_darvas_metrics",
    "darvas_v2_enabled",
    "darvas_weekly_enabled",
    "evaluate_squeeze_bar",
    "is_darvas_10ema_squeeze",
    "is_darvas_10ema_squeeze_legacy",
    "last_completed_week",
    "sort_qualifying_squeezes",
    "squeeze_frame",
    "week_complete",
    "week_end_session",
    "weekly_ohlc",
]
