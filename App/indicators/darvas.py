"""Re-export Darvas Box helpers from Scripts.darvas_squeeze (canonical module)."""
from __future__ import annotations

try:
    from Scripts.darvas_squeeze import (
        DARVAS,
        calculate_darvas_box,
        compute_darvas_metrics,
        darvas_v2_enabled,
        evaluate_squeeze_bar,
        is_darvas_10ema_squeeze,
        is_darvas_10ema_squeeze_legacy,
        sort_qualifying_squeezes,
        squeeze_frame,
    )
except ImportError:
    import sys
    from pathlib import Path

    _scripts = Path(__file__).resolve().parents[2] / "Scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    from darvas_squeeze import (  # type: ignore
        DARVAS,
        calculate_darvas_box,
        compute_darvas_metrics,
        darvas_v2_enabled,
        evaluate_squeeze_bar,
        is_darvas_10ema_squeeze,
        is_darvas_10ema_squeeze_legacy,
        sort_qualifying_squeezes,
        squeeze_frame,
    )

__all__ = [
    "DARVAS",
    "calculate_darvas_box",
    "compute_darvas_metrics",
    "darvas_v2_enabled",
    "evaluate_squeeze_bar",
    "is_darvas_10ema_squeeze",
    "is_darvas_10ema_squeeze_legacy",
    "sort_qualifying_squeezes",
    "squeeze_frame",
]
