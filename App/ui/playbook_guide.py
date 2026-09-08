"""
Action Desk Playbook & Field Guide.
Provides interactive guidance, decision framework, and case studies directly inside the application.
Copy compiles from Scripts.desk_contract — do not hardcode exposure bands or hit rates here.
"""
from __future__ import annotations

from nicegui import ui

try:
    from Scripts.desk_contract import (
        EXPOSURE_RULES,
        FIELD_GUIDE_TIPS,
        HOLY_BONUS,
        HOLY_TRINITY,
        METRICS_CHEATSHEET,
        PLAYBOOK,
        ROUTINE_HEADLINE,
        ROUTINE_STEPS,
        SWING_CASE_STUDIES,
        exposure_playbook_line,
    )
except ModuleNotFoundError:
    from desk_contract import (  # type: ignore
        EXPOSURE_RULES,
        FIELD_GUIDE_TIPS,
        HOLY_BONUS,
        HOLY_TRINITY,
        METRICS_CHEATSHEET,
        PLAYBOOK,
        ROUTINE_HEADLINE,
        ROUTINE_STEPS,
        SWING_CASE_STUDIES,
        exposure_playbook_line,
    )


def open_playbook_modal() -> None:
    """Render the full interactive Action Desk Trading Playbook modal."""
    with ui.dialog() as dlg, ui.card().classes("w-[920px] max-w-[95vw] max-h-[90vh] mp-card p-5 border border-[var(--mp-border)] bg-[var(--mp-surface)] overflow-y-auto flex flex-col"):
        with ui.row().classes("w-full items-center justify-between pb-3 border-b border-[var(--mp-border)]"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("menu_book", size="sm").classes("text-emerald-400")
                ui.label(PLAYBOOK["modal_title"]).classes("text-sm font-bold tracking-wider text-[var(--mp-text)] uppercase")
            ui.button(icon="close", on_click=dlg.close).props("dense flat round size=sm").classes("text-slate-400 hover:text-white")

        with ui.tabs().classes("w-full text-xs border-b border-[var(--mp-border)] mt-2") as tabs:
            tab_flow = ui.tab(PLAYBOOK["tab_flow"], icon="alt_route")
            tab_cols = ui.tab(PLAYBOOK["tab_cols"], icon="view_column")
            tab_holy = ui.tab(PLAYBOOK["tab_holy"], icon="checklist")
            tab_cases = ui.tab(PLAYBOOK["tab_cases"], icon="psychology")
            tab_routine = ui.tab(PLAYBOOK["tab_routine"], icon="timer")

        with ui.tab_panels(tabs, value=tab_flow).classes("w-full bg-transparent p-2 text-xs text-[var(--mp-text)]"):

            with ui.tab_panel(tab_flow).classes("w-full gap-3 flex flex-col"):
                ui.label(PLAYBOOK["workflow_intro"]).classes("font-semibold text-emerald-400 mb-1")

                with ui.column().classes("w-full gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                    ui.label(PLAYBOOK["step1_title"]).classes("font-bold text-xs text-sky-400")
                    ui.label(PLAYBOOK["step1_intro"]).classes("text-[11px] text-[var(--mp-muted)]")
                    with ui.column().classes("gap-1 pl-2 border-l-2 border-slate-700 text-[11px] font-mono"):
                        for rule in EXPOSURE_RULES:
                            ui.label(exposure_playbook_line(rule))

                with ui.column().classes("w-full gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                    ui.label(PLAYBOOK["step2_title"]).classes("font-bold text-xs text-amber-400")
                    ui.label(PLAYBOOK["step2_intro"]).classes("text-[11px] text-[var(--mp-muted)]")
                    with ui.column().classes("gap-1 pl-2 border-l-2 border-slate-700 text-[11px] font-mono"):
                        for bullet in PLAYBOOK["step2_bullets"]:
                            ui.label(f"• {bullet}")

                with ui.column().classes("w-full gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                    ui.label(PLAYBOOK["step3_title"]).classes("font-bold text-xs text-emerald-400")
                    with ui.column().classes("gap-1 pl-2 border-l-2 border-slate-700 text-[11px] font-mono"):
                        for bullet in PLAYBOOK["step3_bullets"]:
                            ui.label(f"• {bullet}")

            with ui.tab_panel(tab_cols).classes("w-full gap-3 flex flex-col"):
                ui.label(PLAYBOOK["metrics_intro"]).classes("font-semibold text-emerald-400 mb-1")

                with ui.column().classes("w-full gap-1.5"):
                    for col_name, full_name, desc, rule in METRICS_CHEATSHEET:
                        with ui.column().classes("w-full p-2.5 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)] gap-1"):
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label(f"{col_name} — {full_name}").classes("font-bold text-xs text-sky-400 font-mono")
                            ui.label(desc).classes("text-[11px] text-[var(--mp-muted)]")
                            ui.label(f"💡 Actionable Rule: {rule}").classes("text-[11px] font-mono text-emerald-300")

            with ui.tab_panel(tab_holy).classes("w-full gap-3 flex flex-col"):
                ui.label(PLAYBOOK["holy_title"]).classes("font-semibold text-emerald-400 mb-1")
                ui.label(PLAYBOOK["holy_sub"]).classes("text-xs text-[var(--mp-muted)]")

                with ui.column().classes("w-full gap-2 mt-1"):
                    for idx, item in enumerate(HOLY_TRINITY, 1):
                        with ui.row().classes("w-full items-start gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-emerald-500/30"):
                            ui.label(str(idx)).classes("text-lg font-black text-emerald-400 font-mono px-2 py-0.5 rounded bg-emerald-950 border border-emerald-500/40")
                            with ui.column().classes("gap-0.5 flex-1"):
                                ui.label(item["title"]).classes("font-bold text-xs text-[var(--mp-text)]")
                                ui.label(item["body"]).classes("text-[11px] text-[var(--mp-muted)] font-mono")

                with ui.card().classes("w-full p-2.5 rounded bg-emerald-950/40 border border-emerald-500/40 mt-1"):
                    ui.label(f"🎯 {HOLY_BONUS}").classes("text-[11px] font-mono font-bold text-emerald-300")

            with ui.tab_panel(tab_cases).classes("w-full gap-3 flex flex-col"):
                ui.label(PLAYBOOK["cases_intro"]).classes("font-semibold text-emerald-400 mb-1")

                for case in SWING_CASE_STUDIES:
                    with ui.column().classes("w-full gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                        ui.label(case["title"]).classes(f"font-bold text-xs {case['tone']}")
                        with ui.column().classes("gap-1 pl-2 border-l-2 border-slate-700 text-[11px] font-mono"):
                            for bullet in case["bullets"]:
                                ui.label(bullet)

            with ui.tab_panel(tab_routine).classes("w-full gap-3 flex flex-col"):
                ui.label(ROUTINE_HEADLINE).classes("font-semibold text-emerald-400 mb-1")

                with ui.column().classes("w-full gap-2"):
                    for min_str, title, desc in ROUTINE_STEPS:
                        with ui.row().classes("w-full items-start gap-2 p-2.5 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                            ui.label(min_str).classes("text-xs font-mono font-bold text-amber-400 w-24 shrink-0")
                            with ui.column().classes("gap-0.5 flex-1"):
                                ui.label(title).classes("font-bold text-xs text-[var(--mp-text)]")
                                ui.label(desc).classes("text-[11px] text-[var(--mp-muted)] font-mono")

        with ui.row().classes("w-full items-center justify-end pt-3 border-t border-[var(--mp-border)] mt-2"):
            ui.button(PLAYBOOK["close_label"], on_click=dlg.close).classes("mp-button text-xs").props("dense outline")

    dlg.open()


def render_inline_field_guide_banner(q_key: str) -> None:
    """Render an inline quick-guidance strip specific to the active queue."""
    tip = FIELD_GUIDE_TIPS.get(q_key, PLAYBOOK["field_guide_fallback"])

    with ui.row().classes("w-full items-center justify-between px-3 py-1.5 rounded bg-emerald-950/30 border border-emerald-500/30 text-[11px] text-emerald-300 font-mono mt-2"):
        ui.label(tip).classes("truncate flex-1")
        ui.button(PLAYBOOK["open_full_label"], on_click=open_playbook_modal).props("dense flat size=xs").classes("text-emerald-400 font-bold hover:underline shrink-0 ml-2")
