"""Re-export the RSI divergence engine from Scripts.rsi_divergence (canonical module)."""
from __future__ import annotations

try:
    from Scripts.rsi_divergence import *  # noqa: F401,F403
    from Scripts.rsi_divergence import __all__  # noqa: F401
except ImportError:  # pragma: no cover - App run with Scripts/ on sys.path only
    import sys
    from pathlib import Path

    _scripts = Path(__file__).resolve().parents[2] / "Scripts"
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))
    from rsi_divergence import *  # type: ignore  # noqa: F401,F403
    from rsi_divergence import __all__  # type: ignore  # noqa: F401
