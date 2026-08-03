from __future__ import annotations

from pathlib import Path

from nicegui import ui

from App.query_service import load_app_snapshot


def render_today(db_path: Path, limit: int = 15) -> None:
    snapshot = load_app_snapshot(db_path, limit=limit)
    with ui.row().classes("w-full items-center justify-between"):
        ui.label("Today").classes("text-2xl font-bold")
        ui.label("Decision-first focused watchlist").classes("text-gray-500")
    breadth = snapshot["breadth"]
    if breadth.empty:
        ui.notify("Market breadth is not available for the latest session", type="warning")
    else:
        row = breadth.iloc[0]
        with ui.row().classes("w-full gap-3"):
            ui.label(f"Breadth: {row.get('breadth_state', 'Unknown')}")
            ui.label(f"Advance: {row.get('advance_pct', '—'):.1f}%" if row.get("advance_pct") is not None else "Advance: —")
            ui.label(f"Above 50 EMA: {row.get('above_50ema_pct', '—'):.1f}%" if row.get("above_50ema_pct") is not None else "Above 50 EMA: —")
    candidates = snapshot["candidates"]
    if candidates.empty:
        ui.label("No focused candidates for the latest session.")
        return
    ui.label(f"Focused preparation list ({min(len(candidates), limit)} names)").classes("text-lg font-semibold mt-4")
    ui.table(columns=[{"name": col, "label": col.replace("_", " ").title(), "field": col} for col in ["symbol", "candidate_state", "total_score", "why_now", "latest_change", "trigger_price", "invalidation_price", "initial_risk_pct", "event_risk"] if col in candidates.columns], rows=candidates.fillna("").to_dict("records"), row_key="symbol").classes("w-full")
