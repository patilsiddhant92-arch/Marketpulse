"""Deprecated shim — use Scripts.vcp. Kept briefly for import safety."""
from __future__ import annotations

from Scripts.vcp import VCP as MANAS
from Scripts.vcp import classify_vcp_frame as classify_manas_focus_frame
from Scripts.vcp import purple_density, ret_3m_pct

__all__ = ["MANAS", "classify_manas_focus_frame", "purple_density", "ret_3m_pct"]
