"""Custom technical indicators package for MarketPulse.

Re-exports pure indicators from Scripts.indicators to prevent namespace collisions
when 'App' is on sys.path, and exposes custom indicator suites like Darvas Box.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

# Load and re-export all functions from Scripts/indicators.py
_scripts_ind_path = Path(__file__).resolve().parent.parent.parent / "Scripts" / "indicators.py"
if _scripts_ind_path.exists():
    _spec = importlib.util.spec_from_file_location("Scripts._indicators_source", str(_scripts_ind_path))
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        for _attr in dir(_mod):
            if not _attr.startswith("_"):
                globals()[_attr] = getattr(_mod, _attr)

# Re-export Darvas Box calculations
try:
    from App.indicators.darvas import (
        calculate_darvas_box,
        compute_darvas_metrics,
        is_darvas_10ema_squeeze,
    )
except ImportError:
    from indicators.darvas import (  # type: ignore
        calculate_darvas_box,
        compute_darvas_metrics,
        is_darvas_10ema_squeeze,
    )
