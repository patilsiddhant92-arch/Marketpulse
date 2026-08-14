"""Quarantined stub — not a production Watchlist page.

Production Watchlist UI is deferred (PR-WL-UI). Do not wire this stub into
navigation until eligible-only focused-v2 persistence (PR-WL-DATA) is ready.
"""

from __future__ import annotations

from pathlib import Path


def render_watchlist(db_path: Path) -> None:
    raise NotImplementedError(
        "App.pages.watchlist is quarantined until PR-WL-DATA/PR-WL-UI land. "
        "Do not load unversioned watchlist snapshots as a production queue."
    )
