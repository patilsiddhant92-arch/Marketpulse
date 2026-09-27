"""Shared desk chrome: rotation state colors + peer-rank chip grammar.

One owner for Leading/Lagging/Emerging badges and for stock peer-rank chips
(Template Fin #12 / Action Desk PEER column / Stock 360 peer list).
"""
from __future__ import annotations

from typing import Any

ROTATION_BADGE_CLASS = {
    "Leading": "mp-badge mp-state-leading",
    "Emerging": "mp-badge mp-state-emerging",
    "Improving": "mp-badge mp-state-improving",
    "Weakening": "mp-badge mp-state-weakening",
    "Lagging": "mp-badge mp-state-lagging",
    "Neutral": "mp-badge mp-neutral",
}


def rotation_badge_class(state: str | None) -> str:
    s = str(state or "Neutral").strip()
    return ROTATION_BADGE_CLASS.get(s, "mp-badge mp-neutral")


def signed_pct_class(val: Any) -> str:
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "text-[var(--mp-muted)]"
    return "text-[var(--mp-good)] font-bold" if v >= 0 else "text-[var(--mp-bad)] font-bold"


def away_52w_class(val: Any) -> str:
    """Distance below 52W high: 0%% to -25%% (near highs) = green; farther = red; above high = green."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "text-[var(--mp-muted)]"
    if v > 0:
        return "text-[var(--mp-good)] font-bold"
    if -25.0 <= v <= 0.0:
        return "text-[var(--mp-good)] font-bold"
    return "text-[var(--mp-bad)] font-bold"


def abbrev_group(name: str | None, *, width: int = 10) -> str:
    raw = str(name or "").strip()
    if not raw:
        return "—"
    # Prefer first token for Fin/Banks/Energy style chips
    tok = raw.split()[0]
    return (tok[:width] if len(tok) >= 3 else raw[:width]).rstrip(",.&")


def peer_chip_label(group_name: str | None, rank: int | None) -> str:
    """Template grammar: CapGoods #4 / Lubrican #5 — stock RS rank within peer group."""
    short = abbrev_group(group_name)
    if rank is None:
        return short
    return f"{short} #{int(rank)}"
