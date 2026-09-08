"""Info Page: Plain-English Macro Intelligence, Chronological Event Ripple Effects,
Real-World Case Studies, and System Data Health Diagnostics.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd
from nicegui import ui

try:
    from App.data_health_page import build_data_health_page
except ModuleNotFoundError:
    from data_health_page import build_data_health_page  # type: ignore

try:
    from App.ui.playbook_guide import open_playbook_modal
except ModuleNotFoundError:
    from ui.playbook_guide import open_playbook_modal  # type: ignore

try:
    from Scripts.desk_contract import (
        EXPOSURE_RULES,
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
        HOLY_BONUS,
        HOLY_TRINITY,
        METRICS_CHEATSHEET,
        PLAYBOOK,
        ROUTINE_HEADLINE,
        ROUTINE_STEPS,
        SWING_CASE_STUDIES,
        exposure_playbook_line,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. MACRO PLAYBOOK DEFINITION (Plain English)
# ─────────────────────────────────────────────────────────────────────────────
MACRO_PLAYBOOK_CARDS = [
    {
        "icon": "🛢",
        "title": "Crude Oil (Brent)",
        "asset_type": "Raw Material / Energy Fuel",
        "simple_rule": (
            "Paint is made from petroleum chemicals, and planes run on jet fuel. "
            "Oil is a massive manufacturing/operating expense for paints and airlines, "
            "but direct revenue for crude drillers."
        ),
        "when_drops": (
            "Cheaper Costs = Bigger Profits! Making paint and flying planes costs much less money. "
            "Profit margins immediately expand."
        ),
        "when_drops_stocks": [
            ("ASIANPAINT", "Paint raw material costs drop (~25 bps margin relief per $1 drop)"),
            ("BERGEPAINT", "Solvent & resin costs fall; higher retail profit"),
            ("INDIGO", "Jet fuel is 35–40% of airline operating costs; major fuel savings"),
            ("PIDILITIND", "Chemical adhesive input costs drop"),
        ],
        "when_rises": (
            "Oil drillers sell every barrel of crude for more cash, boosting top-line revenue."
        ),
        "when_rises_stocks": [
            ("ONGC", "State oil producer collects higher price per barrel"),
            ("OIL", "Upstream exploration revenue shoots higher"),
        ],
        "watch_out": "Paints, airlines, and specialty chemicals face sudden cost pressure when oil spikes.",
    },
    {
        "icon": "⚪",
        "title": "Silver (XAG / USD)",
        "asset_type": "Free Byproduct Metal / Solar Component",
        "simple_rule": (
            "Hindustan Zinc digs zinc from the earth. In the process, they recover massive amounts of silver "
            "almost for free as a byproduct. Silver accounts for 35% to 45% of their total company operating profit!"
        ),
        "when_drops": "Normal zinc operations continue, but bonus silver cash collections moderate.",
        "when_drops_stocks": [],
        "when_rises": (
            "Pure Extra Cash! Because mining costs are already paid for zinc, ~88% of higher silver revenue "
            "flows straight into the bank account as pure profit."
        ),
        "when_rises_stocks": [
            ("HINDZINC", "Every $1/oz rise in silver adds ~₹200–225 Cr in annual profit!"),
        ],
        "watch_out": (
            "Solar panel and cell manufacturers (WAAREEENER, PREMIERENE, WEBSOL) use conductive silver paste "
            "as an expensive input; sharp silver spikes increase panel assembly costs."
        ),
    },
    {
        "icon": "🟡",
        "title": "Gold (XAU / USD)",
        "asset_type": "Loan Collateral & Store of Value",
        "simple_rule": (
            "Customers pledge gold jewellery as security to borrow cash from gold-loan companies. "
            "When gold prices rise, that pledged jewellery becomes worth significantly more money."
        ),
        "when_drops": (
            "Collateral cushion narrows. Lenders maintain a 60–65% safety buffer to protect against loan defaults."
        ),
        "when_drops_stocks": [],
        "when_rises": (
            "Rock-Solid Loan Safety & Growth! With gold worth more, default risk vanishes, loan auction notices "
            "drop to near-zero, and companies can safely disburse larger loans per gram."
        ),
        "when_rises_stocks": [
            ("MUTHOOTFIN", "Gold loan leader; loan book expands safely with near-zero credit cost"),
            ("MANAPPURAM", "Higher collateral backing drives loan growth across branches"),
            ("TITAN", "Jewellery in retail showroom vaults gains immediate inventory value"),
            ("KALYANKJIL", "Strong gold prices accelerate customer shift to trusted hallmarked brands"),
        ],
        "watch_out": "Gold surges during extreme geopolitical panic when general stock markets face risk-off selling.",
    },
    {
        "icon": "🔴",
        "title": "Copper ('Dr. Copper')",
        "asset_type": "Global Building Block & Wire Input",
        "simple_rule": (
            "Nicknamed 'Dr. Copper' because it has a PhD in Economics—it is required in every electric wire, "
            "power grid, vehicle, and building. For Indian cable makers, copper is 60–70% of total raw material costs."
        ),
        "when_drops": "Raw material costs drop for wire makers, giving them pricing flexibility.",
        "when_drops_stocks": [],
        "when_rises": (
            "Higher Selling Realization for Metal Miners, but Wire Makers must pass costs along to dealers."
        ),
        "when_rises_stocks": [
            ("HINDALCO", "Copper smelting and mining margins surge with global prices"),
            ("VEDL", "Diversified natural resource producer benefits from high metal prices"),
            ("POLYCAB", "Passes costs with 15–30 day price resets; wins if construction demand is strong"),
            ("KEI", "Leading institutional cable maker; benefits from industrial capex"),
        ],
        "watch_out": (
            "If copper spikes unexpectedly while construction is sluggish, wire makers struggle to raise "
            "store prices and their profit margins get squeezed."
        ),
    },
    {
        "icon": "🔥",
        "title": "Natural Gas",
        "asset_type": "Factory Kiln Fuel & Chemical Feedstock",
        "simple_rule": (
            "Making ceramic floor and bathroom tiles requires keeping giant industrial kilns burning "
            "24 hours a day at 1,200°C. Gas fuel accounts for 20% to 25% of total tile manufacturing costs."
        ),
        "when_drops": (
            "Big Fuel Bill Savings! Factory gas bills drop dramatically, leaving higher profit on every square foot of tile."
        ),
        "when_drops_stocks": [
            ("KAJARIACER", "India's largest tile maker saves huge fuel expense in industrial ovens"),
            ("CERA", "Sanitaryware and ceramic firing costs fall"),
            ("CHAMBLFERT", "Natural gas is key feedstock for urea fertilizer synthesis"),
        ],
        "when_rises": "Drillers and LNG suppliers earn more; tile factories face margin compression.",
        "when_rises_stocks": [
            ("ONGC", "State gas producer collects domestic gas price allocation"),
        ],
        "watch_out": "City Gas Distributors (MGL, IGL) face margin pressure when global spot LNG prices spike.",
    },
    {
        "icon": "💵",
        "title": "US 10Y Bond Yields & The US Dollar (DXY)",
        "asset_type": "Global Magnet for Capital & Currency",
        "simple_rule": (
            "The US 10-Year Treasury yield is the global baseline interest rate. When US yields rise, foreign funds (FIIs) "
            "ask: 'Why take risk in India when I can earn 4.5% risk-free in US Government bonds?'"
        ),
        "when_drops": (
            "Global Easy Money! Lower US rates push foreign capital out into high-growth emerging markets like India. "
            "FIIs buy Indian banking heavyweights and liquidity surges."
        ),
        "when_drops_stocks": [
            ("HDFCBANK", "Large FII ownership; inflows drive institutional buying"),
            ("ICICIBANK", "Core beneficiary of foreign institutional equity allocations"),
        ],
        "when_rises": (
            "Dollar Strengthens (USD/INR Rises). Indian IT and Pharma companies bill American clients in US Dollars "
            "and pay Indian employee salaries in Rupees. A stronger dollar gives them automatic Rupee profit!"
        ),
        "when_rises_stocks": [
            ("TCS", "Exports tech services to US clients; each $1 billing translates to more Rupees"),
            ("INFY", "High US revenue concentration; currency depreciation provides profit cushion"),
            ("SUNPHARMA", "US generic pharmaceutical sales benefit from stronger dollar realization"),
        ],
        "watch_out": (
            "Rising US yields trigger FII selling in Indian large-caps. When the RBI defends the Rupee by selling USD, "
            "it drains domestic Rupee cash from Indian banks, pushing up short-term borrowing costs."
        ),
    },
    {
        "icon": "₿",
        "title": "Bitcoin & Crypto (Global Net Liquidity)",
        "asset_type": "24/7 Global Speculative Liquidity Radar",
        "simple_rule": (
            "Crypto trades 24 hours a day, 7 days a week with zero closing bells. It is the purest real-time barometer "
            "of global risk appetite and dollar liquidity. When central banks expand liquidity, crypto moves first."
        ),
        "when_drops": (
            "Liquidity Warning: If Bitcoin crashes -10% over the weekend, it is an early warning that Monday's "
            "Indian market open will face global risk-off selling, with speculative mid/small-caps hit hardest."
        ),
        "when_drops_stocks": [],
        "when_rises": (
            "Speculative Risk-On Appetite! When crypto booms, retail investors feel confident and take risks. "
            "Trading volumes, Demat account openings, and F&O turnover surge on retail brokerage platforms."
        ),
        "when_rises_stocks": [
            ("ANGELONE", "Digital discount broker; thrives on surging retail active client trading volume"),
            ("BSE", "Exchange transaction charges soar as retail options and cash turnover spike"),
            ("MOTILALOFS", "Retail broking and wealth management fees expand with market sentiment"),
        ],
        "watch_out": "Weekend crypto flash crashes often foreshadow Monday morning gap-downs on the Indian market.",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 2. CHRONOLOGY & RIPPLE TIMELINE DEFINITION
# ─────────────────────────────────────────────────────────────────────────────
CHRONOLOGY_STAGES = [
    {
        "stage": "Stage 1",
        "timeframe": "Minutes 0 to 12 Hours",
        "label": "The Spark & Fast Movers",
        "icon": "⚡",
        "color": "amber",
        "headline": "Global News Hits ➔ Fast Assets React Instantly",
        "description": (
            "A major global macroeconomic catalyst occurs—such as a US Federal Reserve rate announcement, "
            "an unexpected US inflation report, or a geopolitical flare-up in an oil-rich region."
        ),
        "reaction_points": [
            "US 10-Year Bond Yields instantly reprice higher or lower based on rate expectations.",
            "The US Dollar Index (DXY) surges or weakens against world currencies.",
            "Bitcoin and Crypto (which trade 24/7) react within minutes, acting as the global canary in the coal mine.",
        ],
    },
    {
        "stage": "Stage 2",
        "timeframe": "Hours 12 to 24",
        "label": "Commodity Repricing",
        "icon": "🌐",
        "color": "blue",
        "headline": "Global Exchanges Adjust Raw Material Prices",
        "description": (
            "As international trading hubs in New York (NYMEX), Chicago (COMEX), and London (LME) trade, "
            "physical commodities and raw materials establish new price levels."
        ),
        "reaction_points": [
            "Brent Crude Oil jumps or tumbles based on supply risks and economic demand forecasts.",
            "Gold and Silver surge if fear or inflation expectations rise.",
            "Copper ('Dr. Copper') adjusts, signaling whether global factory orders are expanding or shrinking.",
        ],
    },
    {
        "stage": "Stage 3",
        "timeframe": "Day 1 (9:00 AM IST)",
        "label": "Currency & RBI Liquidity Shock",
        "icon": "🏦",
        "color": "purple",
        "headline": "The Rupee Gaps ➔ The RBI Defends the Currency",
        "description": (
            "At 9:00 AM Indian Standard Time, the currency market opens. If the US Dollar spiked overnight, "
            "the Indian Rupee faces immediate downward pressure (USD/INR gaps up)."
        ),
        "reaction_points": [
            "To prevent the Rupee from tumbling uncontrollably, the Reserve Bank of India (RBI) steps in.",
            "The RBI sells US Dollars from its reserves and SOAKS UP Indian Rupees from the interbank market.",
            "This drains Rupee liquidity from Indian banks, causing short-term borrowing costs for NBFCs to rise.",
        ],
    },
    {
        "stage": "Stage 4",
        "timeframe": "Days 1 to 5",
        "label": "Indian Equity Sector Rotation",
        "icon": "📊",
        "color": "emerald",
        "headline": "Institutional Fund Managers Shift Billions Across Sectors",
        "description": (
            "Domestic mutual funds and Foreign Institutional Investors (FIIs) rebalance their equity portfolios "
            "based on the new raw material costs and currency realities."
        ),
        "reaction_points": [
            "FIIs sell high-liquidity private banks (Bank Nifty) if US yields rose, using them as cash ATMs.",
            "Paints and Airlines gap up if crude oil dropped (fuel costs saved), or sell off if crude spiked.",
            "Indian IT and US-focused Pharma rally as defensive hedges because their dollar revenue is worth more Rupees.",
            "Metals and mining stocks re-rate in tandem with LME copper and silver prices.",
        ],
    },
    {
        "stage": "Stage 5",
        "timeframe": "Weeks 4 to 12",
        "label": "Quarterly Earnings Reality",
        "icon": "📈",
        "color": "teal",
        "headline": "Audited Financial Results Prove the Margin Expansion",
        "description": (
            "The multi-week shift in raw material and currency prices finally shows up in the official quarterly "
            "P&L statements filed by companies on the NSE."
        ),
        "reaction_points": [
            "Asian Paints reports 200–300 bps higher profit margins thanks to cheaper petroleum solvents.",
            "Hindustan Zinc reports a multi-hundred crore profit windfall from higher silver sales.",
            "Muthoot Finance reports record low loan defaults and accelerated gold loan book growth.",
            "Stock prices complete their major trend swings as equity research analysts upgrade their target valuations.",
        ],
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 3. REAL-WORLD CASE STUDIES DEFINITION
# ─────────────────────────────────────────────────────────────────────────────
CASE_STUDIES = [
    {
        "title": "Case 1: The Crude Oil Drop & Asian Paints",
        "icon": "🛢",
        "badge": "Input Cost Relief",
        "badge_color": "emerald",
        "summary": (
            "In 2023, Brent Crude dropped from $98 down to $72 per barrel. Petroleum-based derivatives "
            "(monomers, solvents, resins) make up nearly 50% of a paint manufacturer's raw material basket."
        ),
        "the_mechanism": (
            "With oil $26 cheaper, Asian Paints' raw material cost per liter plummeted. Even while keeping retail "
            "paint prices competitive, their operating profit margin expanded from ~15.2% to ~22.4%."
        ),
        "the_stock_result": (
            "As quarterly margins expanded by over 700 basis points, institutional mutual funds aggressively accumulated "
            "Asian Paints, driving a massive multi-month rally in the stock."
        ),
        "takeaway": (
            "Rule: When Crude Oil breaks down below key moving averages, immediately look for long swing breakout setups "
            "in Paints (ASIANPAINT, BERGEPAINT) and Airlines (INDIGO)."
        ),
    },
    {
        "title": "Case 2: The Silver Supercycle & Hindustan Zinc",
        "icon": "⚪",
        "badge": "Pure Profit Windfall",
        "badge_color": "blue",
        "summary": (
            "Between late 2023 and 2026, global silver prices broke out from $22/oz to over $32/oz, fueled by booming "
            "industrial demand for Solar Photovoltaic (PV) cells and electronics."
        ),
        "the_mechanism": (
            "Hindustan Zinc is primary a zinc and lead miner. Silver is refined as an automatic byproduct of lead smelting. "
            "Because zinc mining costs were already accounted for, ~88% of the higher silver price was pure, unencumbered profit."
        ),
        "the_stock_result": (
            "Every $1 move in silver delivered ~₹220 Crore in annualized profit. Silver quickly grew to contribute "
            "over 40% of the entire company's operating profit, sending Hindustan Zinc shares on a massive run and paying record dividends."
        ),
        "takeaway": (
            "Rule: When Silver outperforms Gold on global charts, Hindustan Zinc (HINDZINC) is India's premier equity proxy "
            "that captures silver upside directly."
        ),
    },
    {
        "title": "Case 3: Gold at Record Highs & Muthoot Finance",
        "icon": "🟡",
        "badge": "Collateral Supercycle",
        "badge_color": "amber",
        "summary": (
            "As domestic Indian gold prices surged past ₹75,000 per 10 grams, millions of borrowers who pledged gold "
            "with Muthoot Finance saw the market value of their collateral surge."
        ),
        "the_mechanism": (
            "The Loan-to-Value (LTV) ratio dropped from 72% to under 58%. This meant that even if a borrower stopped paying, "
            "the gold held in Muthoot's vaults was worth nearly double the loan balance. Bad loan auctions hit near-zero."
        ),
        "the_stock_result": (
            "With virtually zero credit risk, Muthoot safely disbursed larger loan tickets per gram, expanding its Assets "
            "Under Management (AUM) by over 20% year-on-year and delivering exceptional stock appreciation."
        ),
        "takeaway": (
            "Rule: Sustained bull markets in Gold are not just about jewellery; they are the single most powerful fundamental "
            "tailwind for Gold Loan NBFCs (MUTHOOTFIN, MANAPPURAM)."
        ),
    },
    {
        "title": "Case 4: The Weekend Bitcoin Warning",
        "icon": "₿",
        "badge": "24/7 Early Warning",
        "badge_color": "rose",
        "summary": (
            "During a global macroeconomic carry-trade unwind, global central bank liquidity tightened abruptly over a weekend "
            "while traditional stock exchanges across Mumbai, New York, and Tokyo were closed."
        ),
        "the_mechanism": (
            "Bitcoin, trading 24/7, took the full force of the liquidity shock, plummeting -11% on Sunday afternoon with "
            "cascading liquidations across crypto derivative exchanges."
        ),
        "the_stock_result": (
            "When the Indian market opened on Monday at 9:15 AM, high-beta mid-caps and speculative small-caps gapped down "
            "-2% to -4% immediately. Traders who tracked the weekend crypto liquidation were forewarned to trim aggressive positions."
        ),
        "takeaway": (
            "Rule: Treat Bitcoin as your weekend radar. If Bitcoin suffers a violent Sunday liquidation, expect global risk-off "
            "at the Indian Monday open."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# 4. MAIN PAGE BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_info_page(
    db_path: Path,
    status_path: Path,
    user_db: Path,
    section_header: Callable,
    table_from_df: Callable,
    compact_kpi: Callable,
) -> None:
    """Build the comprehensive Info desk with Macro Playbook, Chronology, Case Studies, and Data Health."""
    section_header(
        "Market Info & Macro Intelligence",
        "Plain-English macroeconomic transmission, chronological market ripple effects, real-world case studies, and pipeline health diagnostics.",
    )

    current_tab = {"value": "playbook"}

    with ui.row().classes("gap-2 flex-wrap items-center mt-2 mb-4 mp-desk-action"):
        btn_playbook = ui.button("🌍 Macro Playbook", on_click=lambda: _select_tab("playbook")).props("dense").classes("mp-button")
        btn_trading_guide = ui.button("🎯 Swing Trading Playbook", on_click=lambda: _select_tab("trading_guide")).props("dense outline").classes("mp-button")
        btn_chrono = ui.button("⏱ Chronology & Ripple Effects", on_click=lambda: _select_tab("chrono")).props("dense outline").classes("mp-button")
        btn_cases = ui.button("💡 Real-World Case Studies", on_click=lambda: _select_tab("cases")).props("dense outline").classes("mp-button")
        btn_health = ui.button("⚙️ System & Data Health", on_click=lambda: _select_tab("health")).props("dense outline").classes("mp-button")

    buttons = {
        "playbook": btn_playbook,
        "trading_guide": btn_trading_guide,
        "chrono": btn_chrono,
        "cases": btn_cases,
        "health": btn_health,
    }

    content_host = ui.column().classes("w-full")

    def _select_tab(tab_name: str) -> None:
        current_tab["value"] = tab_name
        for name, btn in buttons.items():
            if name == tab_name:
                btn.props(remove="outline")
            else:
                btn.props("outline")
        render_content()

    def render_content() -> None:
        content_host.clear()
        with content_host:
            active = current_tab["value"]
            if active == "playbook":
                _render_playbook()
            elif active == "trading_guide":
                _render_trading_guide()
            elif active == "chrono":
                _render_chronology()
            elif active == "cases":
                _render_case_studies()
            elif active == "health":
                _render_data_health()

    def _render_trading_guide() -> None:
        with ui.row().classes("w-full items-center justify-between pb-2 mb-3 border-b border-zinc-800 flex-wrap gap-2"):
            with ui.column().classes("gap-0.5"):
                ui.label(PLAYBOOK["info_header"]).classes("text-lg font-bold text-zinc-100")
                ui.label(PLAYBOOK["info_sub"]).classes("text-xs text-zinc-400")
            ui.button(PLAYBOOK["open_modal_label"], on_click=open_playbook_modal).classes("mp-button text-xs bg-emerald-500 text-slate-950 font-bold hover:bg-emerald-400").props("dense unelevated")

        with ui.column().classes("w-full gap-4"):
            with ui.card().classes("w-full p-4 rounded-lg bg-zinc-900/90 border border-zinc-800 shadow-md"):
                ui.label(PLAYBOOK["workflow_intro"]).classes("text-sm font-bold text-emerald-400 uppercase tracking-wider mb-2")
                with ui.column().classes("w-full gap-2"):
                    ui.label(PLAYBOOK["step1_title"]).classes("font-bold text-xs text-sky-400")
                    for rule in EXPOSURE_RULES:
                        ui.label(exposure_playbook_line(rule)).classes("text-[11px] text-zinc-300 font-mono")
                    ui.label(PLAYBOOK["step2_title"]).classes("font-bold text-xs text-amber-400 mt-2")
                    ui.label(PLAYBOOK["step2_intro"]).classes("text-[11px] text-zinc-300")
                    for bullet in PLAYBOOK["step2_bullets"]:
                        ui.label(f"• {bullet}").classes("text-[11px] text-zinc-300")
                    ui.label(PLAYBOOK["step3_title"]).classes("font-bold text-xs text-emerald-400 mt-2")
                    for bullet in PLAYBOOK["step3_bullets"]:
                        ui.label(f"• {bullet}").classes("text-[11px] text-zinc-300")

            with ui.card().classes("w-full p-4 rounded-lg bg-zinc-900/90 border border-emerald-500/30 shadow-md"):
                ui.label(PLAYBOOK["holy_title"]).classes("text-sm font-bold text-emerald-400 uppercase tracking-wider mb-2")
                with ui.column().classes("w-full gap-2 text-xs font-mono"):
                    for idx, item in enumerate(HOLY_TRINITY, 1):
                        ui.label(f"✓ {idx}. {item['title']}: {item['body']}").classes("text-zinc-200")
                    ui.label(f"⭐ {HOLY_BONUS}").classes("text-emerald-300 font-bold")

            with ui.card().classes("w-full p-4 rounded-lg bg-zinc-900/90 border border-zinc-800 shadow-md"):
                ui.label(PLAYBOOK["metrics_intro"]).classes("text-sm font-bold text-sky-400 uppercase tracking-wider mb-2")
                with ui.column().classes("w-full gap-1.5 text-xs font-mono"):
                    for col_name, _full_name, desc, rule in METRICS_CHEATSHEET:
                        ui.label(f"• {col_name}: {desc} {rule}").classes("text-zinc-300")

            with ui.card().classes("w-full p-4 rounded-lg bg-zinc-900/90 border border-zinc-800 shadow-md"):
                ui.label(PLAYBOOK["cases_intro"]).classes("text-sm font-bold text-amber-400 uppercase tracking-wider mb-2")
                with ui.column().classes("w-full gap-2 text-xs font-mono"):
                    for case in SWING_CASE_STUDIES:
                        ui.label(case["title"]).classes("text-zinc-200 font-bold")
                        for bullet in case["bullets"]:
                            ui.label(bullet).classes("text-zinc-300")

            with ui.card().classes("w-full p-4 rounded-lg bg-zinc-900/90 border border-zinc-800 shadow-md"):
                ui.label(ROUTINE_HEADLINE).classes("text-sm font-bold text-emerald-400 uppercase tracking-wider mb-2")
                with ui.column().classes("w-full gap-1.5 text-xs font-mono"):
                    for idx, (_min_str, title, desc) in enumerate(ROUTINE_STEPS, 1):
                        ui.label(f"{idx}. {title}: {desc}").classes("text-zinc-300")

    def _render_playbook() -> None:
        ui.label("How to Think About Global Macros in Plain English").classes("text-lg font-bold text-zinc-100 mt-1")
        ui.label(
            "Every global commodity or currency is either an Expense (a raw material a company must buy) or a Product (what a company sells). "
            "When raw material costs drop, profits surge. When product selling prices rise, earnings explode."
        ).classes("text-sm text-zinc-400 mb-4")

        with ui.column().classes("w-full gap-4"):
            for card in MACRO_PLAYBOOK_CARDS:
                with ui.card().classes("w-full p-4 rounded-lg bg-zinc-900/90 border border-zinc-800 shadow-md"):
                    with ui.row().classes("items-center justify-between w-full border-b border-zinc-800/80 pb-2 mb-3"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(card["icon"]).classes("text-2xl")
                            ui.label(card["title"]).classes("text-base font-bold text-zinc-100")
                        ui.label(card["asset_type"]).classes("text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono")

                    ui.label(card["simple_rule"]).classes("text-sm text-zinc-300 mb-3 leading-relaxed")

                    with ui.row().classes("w-full gap-4 flex-wrap md:flex-nowrap"):
                        # Winner / Lower cost side
                        with ui.column().classes("flex-1 p-3 rounded bg-emerald-950/20 border border-emerald-800/30"):
                            ui.label("🟢 When Price Moves Favorably:").classes("text-xs font-bold text-emerald-400 mb-1")
                            ui.label(card["when_drops"] if card["when_drops_stocks"] else card["when_rises"]).classes("text-xs text-zinc-300 mb-2")
                            active_stocks = card["when_drops_stocks"] if card["when_drops_stocks"] else card["when_rises_stocks"]
                            for sym, reason in active_stocks:
                                with ui.row().classes("items-center gap-2 mt-1"):
                                    ui.label(sym).classes("text-xs font-bold text-emerald-300 font-mono px-1.5 py-0.5 rounded bg-emerald-900/40 border border-emerald-700/50")
                                    ui.label(reason).classes("text-xs text-zinc-400")

                        # Watch out / Headwind side
                        with ui.column().classes("flex-1 p-3 rounded bg-rose-950/20 border border-rose-800/30"):
                            ui.label("🔴 Stocks Under Pressure / Headwinds:").classes("text-xs font-bold text-rose-400 mb-1")
                            ui.label(card["watch_out"]).classes("text-xs text-zinc-300")
                            if card["when_drops_stocks"] and card["when_rises_stocks"]:
                                ui.label("Beneficiaries When It Rises:").classes("text-xs font-bold text-zinc-400 mt-2 mb-1")
                                for sym, reason in card["when_rises_stocks"]:
                                    with ui.row().classes("items-center gap-2 mt-1"):
                                        ui.label(sym).classes("text-xs font-bold text-zinc-200 font-mono px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700")
                                        ui.label(reason).classes("text-xs text-zinc-400")

    def _render_chronology() -> None:
        ui.label("The Chronological Ripple Effect: How a Macro Event Unfolds").classes("text-lg font-bold text-zinc-100 mt-1")
        ui.label(
            "Global events do not impact all assets at once. They ripple through financial markets in a distinct chronological sequence—from "
            "fast electronic markets, to physical commodities, to currency reserves, and finally into Indian stock prices and quarterly earnings."
        ).classes("text-sm text-zinc-400 mb-4")

        with ui.column().classes("w-full gap-4 relative pl-4 border-l-2 border-zinc-800 ml-2"):
            for item in CHRONOLOGY_STAGES:
                with ui.card().classes(f"w-full p-4 rounded-lg bg-zinc-900/90 border border-{item['color']}-900/40 shadow-md"):
                    with ui.row().classes("items-center justify-between w-full border-b border-zinc-800/80 pb-2 mb-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(item["icon"]).classes("text-xl")
                            ui.label(f"{item['stage']}: {item['label']}").classes("text-sm font-bold text-zinc-100")
                        ui.label(item["timeframe"]).classes(f"text-xs px-2 py-0.5 rounded bg-{item['color']}-950/60 text-{item['color']}-300 font-mono border border-{item['color']}-800/40")

                    ui.label(item["headline"]).classes("text-sm font-semibold text-zinc-200 mb-1")
                    ui.label(item["description"]).classes("text-xs text-zinc-400 mb-3 leading-relaxed")

                    with ui.column().classes("gap-1.5 pl-2 border-l border-zinc-700/50"):
                        for pt in item["reaction_points"]:
                            with ui.row().classes("items-start gap-2"):
                                ui.label("➔").classes(f"text-xs text-{item['color']}-400 font-bold")
                                ui.label(pt).classes("text-xs text-zinc-300 leading-normal")

    def _render_case_studies() -> None:
        ui.label("Real-World Case Studies: How Indian Stocks Moved in Past Cycles").classes("text-lg font-bold text-zinc-100 mt-1")
        ui.label(
            "Historical proof and concrete numbers showing how macroeconomic shifts translated directly into corporate profits and stock price rallies."
        ).classes("text-sm text-zinc-400 mb-4")

        with ui.column().classes("w-full gap-4"):
            for case in CASE_STUDIES:
                with ui.card().classes("w-full p-4 rounded-lg bg-zinc-900/90 border border-zinc-800 shadow-md"):
                    with ui.row().classes("items-center justify-between w-full border-b border-zinc-800/80 pb-2 mb-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(case["icon"]).classes("text-xl")
                            ui.label(case["title"]).classes("text-base font-bold text-zinc-100")
                        ui.label(case["badge"]).classes(f"text-xs px-2 py-0.5 rounded bg-{case['badge_color']}-950/60 text-{case['badge_color']}-300 font-semibold border border-{case['badge_color']}-800/40")

                    ui.label("What Happened:").classes("text-xs font-bold text-zinc-400 mt-1")
                    ui.label(case["summary"]).classes("text-xs text-zinc-300 mb-2 leading-relaxed")

                    ui.label("The Transmission Mechanism:").classes("text-xs font-bold text-zinc-400 mt-1")
                    ui.label(case["the_mechanism"]).classes("text-xs text-zinc-300 mb-2 leading-relaxed")

                    ui.label("The Stock Market Outcome:").classes("text-xs font-bold text-emerald-400 mt-1")
                    ui.label(case["the_stock_result"]).classes("text-xs text-zinc-200 mb-3 leading-relaxed")

                    with ui.row().classes("w-full p-2 rounded bg-zinc-950/60 border border-zinc-800 items-center gap-2"):
                        ui.label("💡 Trader Takeaway:").classes("text-xs font-bold text-amber-400")
                        ui.label(case["takeaway"]).classes("text-xs text-zinc-300")

    def _render_data_health() -> None:
        ui.label("System Data Health & Pipeline Diagnostics").classes("text-base font-bold text-zinc-200 mb-2")
        # Build the exact data health diagnostics page preserved from data_health_page.py
        build_data_health_page(db_path, status_path, user_db, lambda title, sub: None, table_from_df, compact_kpi)

    # Initial render
    render_content()


__all__ = ["build_info_page", "MACRO_PLAYBOOK_CARDS", "CHRONOLOGY_STAGES", "CASE_STUDIES"]
