"""
Action Desk Playbook & Field Guide.
Provides interactive guidance, decision framework, and case studies directly inside the application.
"""
from __future__ import annotations

from nicegui import ui


def open_playbook_modal() -> None:
    """Render the full interactive Action Desk Trading Playbook modal."""
    with ui.dialog() as dlg, ui.card().classes("w-[920px] max-w-[95vw] max-h-[90vh] mp-card p-5 border border-[var(--mp-border)] bg-[var(--mp-surface)] overflow-y-auto flex flex-col"):
        with ui.row().classes("w-full items-center justify-between pb-3 border-b border-[var(--mp-border)]"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("menu_book", size="sm").classes("text-emerald-400")
                ui.label("ACTION DESK FIELD GUIDE & TRADING PLAYBOOK").classes("text-sm font-bold tracking-wider text-[var(--mp-text)] uppercase")
            ui.button(icon="close", on_click=dlg.close).props("dense flat round size=sm").classes("text-slate-400 hover:text-white")

        with ui.tabs().classes("w-full text-xs border-b border-[var(--mp-border)] mt-2") as tabs:
            tab_flow = ui.tab("1. 3-Step Workflow", icon="alt_route")
            tab_cols = ui.tab("2. How to Read Data", icon="view_column")
            tab_holy = ui.tab("3. Holy Trinity Checklist", icon="checklist")
            tab_cases = ui.tab("4. Case Studies (MVGJL/XTRANET)", icon="psychology")
            tab_routine = ui.tab("5. 15-Min Daily Routine", icon="timer")

        with ui.tab_panels(tabs, value=tab_flow).classes("w-full bg-transparent p-2 text-xs text-[var(--mp-text)]"):
            
            # PANEL 1: 3-STEP WORKFLOW
            with ui.tab_panel(tab_flow).classes("w-full gap-3 flex flex-col"):
                ui.label("Never buy stocks in isolation. Always execute in this 3-step sequence:").classes("font-semibold text-emerald-400 mb-1")
                
                with ui.column().classes("w-full gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                    ui.label("STEP 1: THE EXPOSURE GATE (Market Breadth)").classes("font-bold text-xs text-sky-400")
                    ui.label("Look at the top-left card before reviewing any stocks:").classes("text-[11px] text-[var(--mp-muted)]")
                    with ui.column().classes("gap-1 pl-2 border-l-2 border-slate-700 text-[11px] font-mono"):
                        ui.label("🟢 75% - 100% (Aggressive): Breadth is expanding (>50% above 20 EMA, VIX < 15). Deploy full position sizing (10-15% per trade). Let leaders compound.")
                        ui.label("🟡 25% - 50% (Selective): Choppy market or elevated VIX. Deploy partial sizing (5-7%), take quick profits (+10% to +15%), and avoid chasing extended stocks.")
                        ui.label("🔴 0% - 25% (Defensive): Net new 52W lows expanding. Capital preservation mode. Do not enter new breakouts.")

                with ui.column().classes("w-full gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                    ui.label("STEP 2: LEADING SECTOR THEMES (Industry Momentum)").classes("font-bold text-xs text-amber-400")
                    ui.label("Over 50% of a winning stock's explosive move is driven by its industry group momentum:").classes("text-[11px] text-[var(--mp-muted)]")
                    with ui.column().classes("gap-1 pl-2 border-l-2 border-slate-700 text-[11px] font-mono"):
                        ui.label("• Pick setups from #1, #2, or #3 ranked leading sectors (e.g. Capital Goods, Auto Components, Financial Services, Defense).")
                        ui.label("• Avoid isolated 'lone-wolf' stocks in dead or lagging sectors.")

                with ui.column().classes("w-full gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                    ui.label("STEP 3: SETUP QUEUES (Choose Your Strategy)").classes("font-bold text-xs text-emerald-400")
                    with ui.column().classes("gap-1 pl-2 border-l-2 border-slate-700 text-[11px] font-mono"):
                        ui.label("• PRE-MOVE ACCUMULATION (Before the move): Use '6. Silent Coil', '7. Stair-Step', or '5. Darvas Squeeze' to enter right near 10 EMA before expansion.")
                        ui.label("• CONTINUATION (Second leg): Use '8. Spike-Pause' to catch high-tight flags after an initial 10%+ thrust.")
                        ui.label("• CLASSIC BREAKOUTS: Use '1. VCP', '2. Pullback', or '4. 52W Breakouts' for established Stage 2 leaders.")

            # PANEL 2: HOW TO READ DATA
            with ui.tab_panel(tab_cols).classes("w-full gap-3 flex flex-col"):
                ui.label("Metrics Cheatsheet: What Every Column Means & What to Look For").classes("font-semibold text-emerald-400 mb-1")
                
                metrics_data = [
                    ("TICKET 🏛️", "Institutional Order Size", "avg_trade_size / 20D avg. Large institutions place block orders that small retail cannot.", "Look for 1.3x 🏛️ to 2.2x 🏛️ (+50% higher runner probability). Avoid <0.8x."),
                    ("BAND", "Circuit Limit Collar", "Daily price band limit (10% vs 20%).", "10% ⚡ stocks delivered 21.6% runner rate (vs 9.6% baseline) due to supply-starvation rolling demand to next day."),
                    ("10 EMA %", "Support Proximity", "Distance from current price to the rising 10-day exponential moving average.", "Target [-1.5%, +1.5%]. Never chase if > +6.0% extended from 10 EMA!"),
                    ("RVOL TRAIL", "7-Day Volume Story", "Multi-day relative volume progression (e.g. 0.4x -> 0.3x -> 0.2x).", "Drying up (VDU) OR Stair-stepping higher (0.5x -> 1.0x -> 1.8x). Avoid sudden 9x exhaustion churn."),
                    ("DELIV %", "Delivery Percentage", "Percentage of traded shares taken as delivery into demat accounts.", "Target >= 50% to 70% (real absorption). Blast days with <15% deliv had a 40% trap failure rate!"),
                    ("DEAL FLOW", "Institutional Deals", "Large block/bulk deals reported to exchange in the last 25 sessions.", "Look for '🏛️ +₹50Cr' tags confirming institutional buying."),
                    ("CMP / TRIGGER", "Execution Price", "Current market price vs breakout trigger level.", "Buy at CMP near 10 EMA support or on breakout through trigger price."),
                ]
                
                with ui.column().classes("w-full gap-1.5"):
                    for col_name, full_name, desc, rule in metrics_data:
                        with ui.column().classes("w-full p-2.5 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)] gap-1"):
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label(f"{col_name} — {full_name}").classes("font-bold text-xs text-sky-400 font-mono")
                            ui.label(desc).classes("text-[11px] text-[var(--mp-muted)]")
                            ui.label(f"💡 Actionable Rule: {rule}").classes("text-[11px] font-mono text-emerald-300")

            # PANEL 3: HOLY TRINITY CHECKLIST
            with ui.tab_panel(tab_holy).classes("w-full gap-3 flex flex-col"):
                ui.label("The 'Holy Trinity' Checklist: DNA of a 10% / 20% UC Super-Mover").classes("font-semibold text-emerald-400 mb-1")
                ui.label("Before entering any stock, verify these 3 empirical criteria from our 581-session database audit:").classes("text-xs text-[var(--mp-muted)]")

                with ui.column().classes("w-full gap-2 mt-1"):
                    with ui.row().classes("w-full items-start gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-emerald-500/30"):
                        ui.label("1").classes("text-lg font-black text-emerald-400 font-mono px-2 py-0.5 rounded bg-emerald-950 border border-emerald-500/40")
                        with ui.column().classes("gap-0.5 flex-1"):
                            ui.label("SUPPORT PROXIMITY (Unextended Near 10 or 20 EMA)").classes("font-bold text-xs text-[var(--mp-text)]")
                            ui.label("Price must be within [-1.5%, +2.5%] of the 10 EMA or 20 EMA. Never chase a stock already 8% away from its moving average. 78% of explosive movers consolidated within ±3% of 10 EMA the day before.").classes("text-[11px] text-[var(--mp-muted)] font-mono")

                    with ui.row().classes("w-full items-start gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-emerald-500/30"):
                        ui.label("2").classes("text-lg font-black text-emerald-400 font-mono px-2 py-0.5 rounded bg-emerald-950 border border-emerald-500/40")
                        with ui.column().classes("gap-0.5 flex-1"):
                            ui.label("VOLUME SIGNATURE (Severe VDU or Stair-Step)").classes("font-bold text-xs text-[var(--mp-text)]")
                            ui.label("Either RVOL is completely dry (<= 0.65x) showing zero selling pressure, OR RVOL is stair-stepping higher (0.6x -> 1.1x -> 1.8x) into a tight range showing stealth accumulation.").classes("text-[11px] text-[var(--mp-muted)] font-mono")

                    with ui.row().classes("w-full items-start gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-emerald-500/30"):
                        ui.label("3").classes("text-lg font-black text-emerald-400 font-mono px-2 py-0.5 rounded bg-emerald-950 border border-emerald-500/40")
                        with ui.column().classes("gap-0.5 flex-1"):
                            ui.label("INSTITUTIONAL FOOTPRINT (Ticket Size Expansion 🏛️ OR High Delivery >=50%)").classes("font-bold text-xs text-[var(--mp-text)]")
                            ui.label("Large orders leave footprints. Look for the '🏛️' ticket expansion badge (>=1.2x) and delivery >= 50%. This separates real institutional accumulation from retail day-trader churn traps.").classes("text-[11px] text-[var(--mp-muted)] font-mono")

                with ui.card().classes("w-full p-2.5 rounded bg-emerald-950/40 border border-emerald-500/40 mt-1"):
                    ui.label("🎯 BONUS EDGE: If the stock is in a 10% Band (marked 10% ⚡), its odds of rolling into a multi-day runner more than double (21.6% vs 9.6%) due to supply starvation!").classes("text-[11px] font-mono font-bold text-emerald-300")

            # PANEL 4: CASE STUDIES
            with ui.tab_panel(tab_cases).classes("w-full gap-3 flex flex-col"):
                ui.label("Empirical Case Studies: Exactly What Winners Looked Like Before The Move").classes("font-semibold text-emerald-400 mb-1")

                with ui.column().classes("w-full gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                    ui.label("CASE 1: MVGJL — From ₹151 to ₹215.88 (+43% in 5 Days, 20% UC)").classes("font-bold text-xs text-amber-400")
                    with ui.column().classes("gap-1 pl-2 border-l-2 border-slate-700 text-[11px] font-mono"):
                        ui.label("• Day -1 (Aug 31): Price ₹151.03, sitting -1.47% on 10 EMA support.")
                        ui.label("• Volume & Delivery: RVOL was 0.67x (VDU), Delivery was 61.11% (Massive institutional absorption).")
                        ui.label("• Ticket Size: 1.32x 🏛️ institutional order expansion.")
                        ui.label("• 52W High Distance: -29.68% (Emerging Stage 1 base turnaround).")
                        ui.label("• Outcome: Surged +7.5% next day on 6.7x RVOL -> paused 2 days at 10 EMA -> locked 20.00% UPPER CIRCUIT!")

                with ui.column().classes("w-full gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                    ui.label("CASE 2: XTRANET — Three Consecutive 20% Upper Circuits").classes("font-bold text-xs text-sky-400")
                    with ui.column().classes("gap-1 pl-2 border-l-2 border-slate-700 text-[11px] font-mono"):
                        ui.label("• Day -1 (Aug 26): Resting at ₹159.83, sitting -0.41% right on 10 EMA.")
                        ui.label("• Volume & Delivery: RVOL dried up to 0.37x (Extreme VDU), Delivery was 48.31%.")
                        ui.label("• 200 EMA status: Newer stock with no 200 EMA (would be blocked by old screener, caught by new screener).")
                        ui.label("• Outcome: Exploded 20.00% Upper Circuit on Day 2 -> paused at 10 EMA (0.38x RVOL) -> hit two more 20% Upper Circuits!")

                with ui.column().classes("w-full gap-2 p-3 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                    ui.label("CASE 3: COMSYN & HDBFS (Current Real-Time Setups)").classes("font-bold text-xs text-emerald-400")
                    with ui.column().classes("gap-1 pl-2 border-l-2 border-slate-700 text-[11px] font-mono"):
                        ui.label("• COMSYN: 1.6x 🏛️ ticket size, 10% ⚡ supply-starvation band, +0.0% on 10 EMA, 0.56x RVOL, 50.8% delivery.")
                        ui.label("• HDBFS: 2.2x 🏛️ ticket size, +0.1% on 10 EMA, 1.96x stair-step RVOL, 85.8% delivery (extreme block buying).")

            # PANEL 5: 15-MINUTE DAILY ROUTINE
            with ui.tab_panel(tab_routine).classes("w-full gap-3 flex flex-col"):
                ui.label("Your 15-Minute Evening Checklist (Run every day between 4:00 PM and 9:00 AM)").classes("font-semibold text-emerald-400 mb-1")

                routine_steps = [
                    ("Minute 1-2", "Check Exposure Gate", "Look at Step 1 card. If Green/Yellow, proceed. If Red, halt new trades and protect existing positions."),
                    ("Minute 3-5", "Review Leading Sectors", "Note which sectors are in the top 3 (e.g. Capital Goods, Auto, Finance). Setups in these sectors have highest follow-through."),
                    ("Minute 6-10", "Scan '6. Silent Coil' & '7. Stair-Step'", "Look down the center matrix for rows displaying the '🏛️' ticket expansion badge and '10% ⚡' band."),
                    ("Minute 11-13", "Inspect the Top 3 Charts", "Click on candidate rows. Verify in the right-pane chart that candles are orderly (tight horizontal bars, not wild wicks) and hugging the white 10 EMA line."),
                    ("Minute 14-15", "Copy to TradingView", "Click '📋 Copy [Queue] (TV)' to paste into your TradingView watchlist and set GTT trigger orders near the 10 EMA or at trigger price."),
                ]

                with ui.column().classes("w-full gap-2"):
                    for min_str, title, desc in routine_steps:
                        with ui.row().classes("w-full items-start gap-2 p-2.5 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                            ui.label(min_str).classes("text-xs font-mono font-bold text-amber-400 w-24 shrink-0")
                            with ui.column().classes("gap-0.5 flex-1"):
                                ui.label(title).classes("font-bold text-xs text-[var(--mp-text)]")
                                ui.label(desc).classes("text-[11px] text-[var(--mp-muted)] font-mono")

        with ui.row().classes("w-full items-center justify-end pt-3 border-t border-[var(--mp-border)] mt-2"):
            ui.button("Close Playbook", on_click=dlg.close).classes("mp-button text-xs").props("dense outline")

    dlg.open()


def render_inline_field_guide_banner(q_key: str) -> None:
    """Render an inline quick-guidance strip specific to the active queue."""
    guide_tips = {
        "silent_coil": "🤫 Silent Coil Field Guide: Look for TICKET 🏛️ >= 1.2x and 10 EMA % within [-1.5%, +1.5%]. High delivery (>=50%) with dry volume (RVOL <= 0.6x) indicates smart money accumulation before the move.",
        "stair_step": "📈 Volume Stair-Step Field Guide: RVOL expanding day-over-day at 10/20 EMA support. Look for large TICKET 🏛️ expansion (block buyers entering before the breakout).",
        "spike_pause": "⚡ Spike-Pause Field Guide: High-Tight Flag setup. Stock already made a 10%+ thrust or 2x RVOL surge, now resting 2-4 days along 10 EMA on low volume. Buy the pause for the second leg.",
        "darvas": "📦 Darvas Squeeze Field Guide: Price is compressed inside the top 5% of the Darvas box with rising 10/20 EMA support. Look for squeeze_pct < 3.5% and tight candle range.",
        "vcp": "💎 VCP Breakout Field Guide: Stage 2 Minervini volatility contraction. Enter as price breaks out through the 20-day high pivot with expanding volume.",
        "pullback": "🎯 EMA Pullback Field Guide: High-RS trend leader pulling back to test the rising 10 or 20 EMA on low volume in an established uptrend.",
        "episodic": "💥 Episodic Pivot Field Guide: Explosive 2x+ RVOL surge out of base, typically on earnings or macro catalysts. Invalidation is the low of the blast day.",
        "high52": "🏆 52W Breakout Field Guide: Printing or testing fresh 52-week highs with leadership relative strength (RS >= 70).",
    }
    tip = guide_tips.get(q_key, "💡 Pro Tip: Filter for stocks sitting within ±1.5% of 10 EMA with institutional ticket expansion (🏛️).")
    
    with ui.row().classes("w-full items-center justify-between px-3 py-1.5 rounded bg-emerald-950/30 border border-emerald-500/30 text-[11px] text-emerald-300 font-mono mt-2"):
        ui.label(tip).classes("truncate flex-1")
        ui.button("📖 Open Full Playbook", on_click=open_playbook_modal).props("dense flat size=xs").classes("text-emerald-400 font-bold hover:underline shrink-0 ml-2")
