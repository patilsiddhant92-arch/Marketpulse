"""Quarantined stub — not a production Today page.

Production Today is `build_today_decision_panel` in `App/candidates_page.py`,
wired from `App/app.py` tab_specs. This module must not load unversioned
app snapshot queues.
"""

from __future__ import annotations

from pathlib import Path


def render_today(db_path: Path, limit: int = 15) -> None:
    raise NotImplementedError(
        "App.pages.today is quarantined. Use App.candidates_page.build_today_decision_panel "
        "(focused-v2 decision_read_model) via the production Today tab."
    )
