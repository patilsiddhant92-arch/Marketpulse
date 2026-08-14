"""Universal Stock 360° Drawer / Modal — Deep-dive institutional, technical, and event profile."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import duckdb
import pandas as pd
from nicegui import ui

try:
    from Scripts.institutional_engine import classify_client
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "Scripts"))
    from institutional_engine import classify_client  # type: ignore


def tradingview_url(symbol: str) -> str:
    tok = str(symbol).strip().upper().replace("-", "_")
    return f"https://www.tradingview.com/chart/?symbol=NSE:{tok}"


def query_stock_360_data(db_path: Path, symbol: str) -> dict[str, Any]:
    """Fetch complete multi-dimensional data for a symbol in a single query transaction."""
    sym = str(symbol).strip().upper()
    if not sym:
        return {}

    with duckdb.connect(str(db_path), read_only=True) as db:
        # 1. Latest Indicator & Master Profile
        try:
            ind = db.execute(
                """
                WITH latest AS (SELECT max(trade_date) AS max_d FROM indicators_daily)
                SELECT i.*, m.market_cap_cr, m.broad_sector, m.sector, m.broad_industry, m.industry, m.band
                FROM indicators_daily i
                JOIN latest l ON i.trade_date = l.max_d
                LEFT JOIN stocks_master m ON m.symbol = i.symbol
                WHERE i.symbol = ?
                LIMIT 1
                """,
                [sym],
            ).fetchdf()
        except duckdb.Error:
            ind = pd.DataFrame()

        # 2. Decision Setup & Risk Geometry
        try:
            cand = db.execute(
                """
                SELECT * FROM candidate_daily
                WHERE symbol = ?
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                [sym],
            ).fetchdf()
        except duckdb.Error:
            cand = pd.DataFrame()

        # 3. Institutional Deals History
        try:
            deals = db.execute(
                """
                SELECT d.*, m.market_cap_cr
                FROM deals d
                LEFT JOIN stocks_master m ON m.symbol = d.symbol
                WHERE d.symbol = ?
                ORDER BY d.trade_date DESC
                LIMIT 50
                """,
                [sym],
            ).fetchdf()
        except duckdb.Error:
            deals = pd.DataFrame()

        # 4. Corporate Announcements & Events
        try:
            events = db.execute(
                """
                SELECT * FROM security_events
                WHERE symbol = ?
                ORDER BY event_date DESC
                LIMIT 20
                """,
                [sym],
            ).fetchdf()
        except duckdb.Error:
            events = pd.DataFrame()

        # 5. Surveillance Remarks & 52W Date
        try:
            ref = db.execute(
                """
                SELECT * FROM security_reference_daily
                WHERE symbol = ?
                ORDER BY effective_date DESC
                LIMIT 1
                """,
                [sym],
            ).fetchdf()
        except duckdb.Error:
            ref = pd.DataFrame()


    profile = ind.iloc[0].to_dict() if not ind.empty else {"symbol": sym}
    candidate_setup = cand.iloc[0].to_dict() if not cand.empty else {}
    ref_row = ref.iloc[0].to_dict() if not ref.empty else {}

    # Classify deals
    if not deals.empty:
        classifications = [classify_client(c) for c in deals["client_name"]]
        deals["tier"] = [c["tier"] for c in classifications]
        deals["category"] = [c["category"] for c in classifications]
        deals["is_hft"] = [c["is_hft"] for c in classifications]
        deals["is_institutional"] = [c["is_institutional"] for c in classifications]

    return {
        "symbol": sym,
        "profile": profile,
        "candidate_setup": candidate_setup,
        "deals": deals,
        "events": events,
        "reference": ref_row,
    }


def open_stock_360_modal(
    db_path: Path,
    symbol: str,
    *,
    copy_text: Any = None,
) -> None:
    """Open interactive slide-over dialog for any stock."""
    data = query_stock_360_data(db_path, symbol)
    if not data:
        ui.notify(f"No data available for {symbol}", type="warning")
        return

    sym = data["symbol"]
    profile = data["profile"]
    cand = data["candidate_setup"]
    deals = data["deals"]
    events = data["events"]
    ref = data["reference"]

    close_price = profile.get("close_price") or profile.get("latest_close") or 0.0
    day_change = profile.get("day_change_pct") or 0.0
    sector = profile.get("sector") or "Unclassified"
    industry = profile.get("industry") or "Unclassified"
    mcap = profile.get("market_cap_cr")
    rs = profile.get("rs_percentile")
    vcp_score = profile.get("vcp_score")
    vcp_state = profile.get("vcp_state") or "None"
    band_remarks = ref.get("band_remarks") or profile.get("band_remarks") or ""

    with ui.dialog().classes("mp-stock-dialog") as dialog, ui.card().classes("w-[900px] max-w-[95vw] max-h-[90vh] overflow-y-auto p-5 mp-card"):
        # Header Row
        with ui.row().classes("w-full items-start justify-between border-b pb-3 mb-3"):
            with ui.column().classes("gap-1"):
                with ui.row().classes("items-center gap-3"):
                    ui.label(sym).classes("text-2xl font-bold mp-symbol tracking-wide")
                    if mcap and pd.notna(mcap):
                        ui.label(f"MCap ₹{float(mcap):,.0f} Cr").classes("mp-badge mp-neutral")
                    if band_remarks:
                        ui.label(f"⚠️ {band_remarks}").classes("mp-badge mp-warn")
                    if vcp_state and vcp_state != "None":
                        tone = "mp-good" if vcp_state in ("Breakout", "Near Pivot") else "mp-info"
                        ui.label(vcp_state).classes(f"mp-badge {tone}")
                ui.label(f"{sector} · {industry}").classes("text-xs text-[var(--mp-muted)]")

            with ui.column().classes("items-end gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"₹{float(close_price):,.2f}").classes("text-2xl font-bold")
                    if pd.notna(day_change):
                        tone = "text-green-600" if day_change >= 0 else "text-red-600"
                        ui.label(f"{day_change:+.2f}%").classes(f"text-sm font-semibold {tone}")
                with ui.row().classes("gap-2 mt-1"):
                    tv_url = tradingview_url(sym)
                    ui.button("TradingView", on_click=lambda: ui.run_javascript(f'window.open("{tv_url}", "_blank")')).props("dense flat").classes("mp-primary")
                    if copy_text:
                        ui.button("Copy Symbol", on_click=lambda: copy_text(f"Symbol {sym}", f"NSE:{sym.replace('-', '_')}")).props("dense flat").classes("mp-button")
                    ui.button(icon="close", on_click=dialog.close).props("dense flat round").classes("text-gray-400")

        # Tabs for 360 sections
        with ui.tabs().classes("w-full mb-3") as tabs:
            t_overview = ui.tab("Overview & Technicals", icon="show_chart")
            t_deals = ui.tab("Institutional Pedigree", icon="account_balance")
            t_risk = ui.tab("Risk & Setup Geometry", icon="verified_user")
            t_events = ui.tab("Corporate Events", icon="event")

        with ui.tab_panels(tabs, value=t_overview).classes("w-full"):
            # Tab 1: Overview
            with ui.tab_panel(t_overview):
                with ui.grid(columns=4).classes("w-full gap-3 mb-4"):
                    with ui.card().classes("p-3 mp-card text-center"):
                        ui.label("RS Percentile").classes("text-xs text-[var(--mp-muted)]")
                        ui.label(f"{float(rs):.0f}" if pd.notna(rs) else "—").classes("text-xl font-bold text-teal-600")
                    with ui.card().classes("p-3 mp-card text-center"):
                        ui.label("VCP Score").classes("text-xs text-[var(--mp-muted)]")
                        ui.label(f"{float(vcp_score):.0f}" if pd.notna(vcp_score) else "—").classes("text-xl font-bold text-indigo-600")
                    with ui.card().classes("p-3 mp-card text-center"):
                        away_52w = profile.get("away_52w_high_pct")
                        ui.label("52W High %").classes("text-xs text-[var(--mp-muted)]")
                        ui.label(f"{float(away_52w):+.1f}%" if pd.notna(away_52w) else "—").classes("text-xl font-bold")
                    with ui.card().classes("p-3 mp-card text-center"):
                        rvol = profile.get("rvol")
                        ui.label("RVOL (20D)").classes("text-xs text-[var(--mp-muted)]")
                        ui.label(f"{float(rvol):.2f}x" if pd.notna(rvol) else "—").classes("text-xl font-bold")

                ui.label("Moving Averages & Key Levels").classes("text-sm font-bold mb-2")
                with ui.row().classes("w-full gap-2 flex-wrap mb-3"):
                    for ema, name in [("ema_10", "10 EMA"), ("ema_20", "20 EMA"), ("ema_50", "50 EMA"), ("ema_200", "200 EMA"), ("wema_10", "10 WEMA"), ("mema_10", "10 MEMA")]:
                        val = profile.get(ema)
                        if val and pd.notna(val):
                            dist = ((float(close_price) / float(val)) - 1) * 100
                            tone = "text-green-600" if dist >= 0 else "text-red-600"
                            with ui.card().classes("p-2 mp-card flex-1 min-w-[120px]"):
                                ui.label(name).classes("text-xs text-[var(--mp-muted)]")
                                ui.label(f"₹{float(val):,.1f}").classes("text-sm font-semibold")
                                ui.label(f"{dist:+.1f}%").classes(f"text-xs {tone}")

                # Volume & Delivery Profile
                deliv_pct = profile.get("delivery_pct")
                deliv_qty = profile.get("delivery_qty")
                turnover_cr = profile.get("turnover_cr")
                ui.label(f"Turnover: ₹{float(turnover_cr or 0):,.1f} Cr · Delivery: {float(deliv_pct or 0):.1f}% ({float(deliv_qty or 0):,.0f} shares)").classes("text-xs text-[var(--mp-muted)]")

            # Tab 2: Institutional Pedigree
            with ui.tab_panel(t_deals):
                if deals.empty:
                    ui.label("No Bulk or Block deals recorded for this symbol.").classes("text-sm text-[var(--mp-muted)] p-4")
                else:
                    inst_only = deals[deals["is_institutional"] & (~deals["is_hft"])]
                    total_inst_buy = inst_only[inst_only["side"] == "BUY"]["deal_value_cr"].sum()
                    total_inst_sell = inst_only[inst_only["side"] == "SELL"]["deal_value_cr"].sum()

                    with ui.row().classes("w-full gap-3 mb-3"):
                        with ui.card().classes("p-3 mp-card flex-1"):
                            ui.label("Institutional BUY").classes("text-xs text-[var(--mp-muted)]")
                            ui.label(f"₹{total_inst_buy:,.1f} Cr").classes("text-lg font-bold text-green-600")
                        with ui.card().classes("p-3 mp-card flex-1"):
                            ui.label("Institutional SELL").classes("text-xs text-[var(--mp-muted)]")
                            ui.label(f"₹{total_inst_sell:,.1f} Cr").classes("text-lg font-bold text-red-600")
                        with ui.card().classes("p-3 mp-card flex-1"):
                            net = total_inst_buy - total_inst_sell
                            tone = "text-green-600" if net >= 0 else "text-red-600"
                            ui.label("Net Institutional Flow").classes("text-xs text-[var(--mp-muted)]")
                            ui.label(f"₹{net:+,.1f} Cr").classes(f"text-lg font-bold {tone}")

                    deal_rows = []
                    for _, d in deals.iterrows():
                        d_price = float(d["price"])
                        d_vs_cmp = ((float(close_price) / d_price) - 1) * 100 if d_price > 0 else 0.0
                        deal_rows.append({
                            "Date": str(pd.to_datetime(d["trade_date"]).date()),
                            "Side": d["side"],
                            "Type": d["deal_type"],
                            "Client": d["client_name"],
                            "Tier": d["tier"],
                            "Qty": f"{int(d['quantity']):,}",
                            "Price": f"₹{d_price:,.2f}",
                            "Value Cr": f"₹{float(d['deal_value_cr']):,.2f}",
                            "CMP vs Entry": f"{d_vs_cmp:+.1f}%",
                        })
                    ui.table(
                        columns=[{"name": k, "label": k, "field": k, "align": "left"} for k in deal_rows[0].keys()],
                        rows=deal_rows,
                        pagination=10,
                    ).classes("w-full mp-table text-xs")

            # Tab 3: Risk & Setup Geometry
            with ui.tab_panel(t_risk):
                if not cand:
                    ui.label("No active focused-v2 candidate setup for this symbol.").classes("text-sm text-[var(--mp-muted)] p-4")
                else:
                    trigger = cand.get("trigger_price")
                    invalidation = cand.get("invalidation_price")
                    resistance = cand.get("first_resistance")
                    rr = cand.get("reward_to_risk")
                    risk_pct = cand.get("initial_risk_pct")
                    why_now = cand.get("why_now") or "—"
                    latest_chg = cand.get("latest_change") or "—"
                    risk_sum = cand.get("risk_summary") or "—"

                    with ui.grid(columns=3).classes("w-full gap-3 mb-4"):
                        with ui.card().classes("p-3 mp-card text-center"):
                            ui.label("Breakout Trigger").classes("text-xs text-[var(--mp-muted)]")
                            ui.label(f"₹{float(trigger):,.2f}" if trigger and pd.notna(trigger) else "—").classes("text-lg font-bold text-green-600")
                        with ui.card().classes("p-3 mp-card text-center"):
                            ui.label("Invalidation Support").classes("text-xs text-[var(--mp-muted)]")
                            ui.label(f"₹{float(invalidation):,.2f}" if invalidation and pd.notna(invalidation) else "—").classes("text-lg font-bold text-red-600")
                        with ui.card().classes("p-3 mp-card text-center"):
                            ui.label("Reward / Risk").classes("text-xs text-[var(--mp-muted)]")
                            ui.label(f"{float(rr):.2f} R" if rr and pd.notna(rr) else "—").classes("text-lg font-bold text-blue-600")

                    with ui.column().classes("gap-2 w-full p-3 mp-surface-2 rounded-lg"):
                        with ui.row().classes("gap-2"):
                            ui.label("Why Now:").classes("font-semibold text-xs text-[var(--mp-muted)]")
                            ui.label(why_now).classes("text-xs font-medium")
                        with ui.row().classes("gap-2"):
                            ui.label("Latest Change:").classes("font-semibold text-xs text-[var(--mp-muted)]")
                            ui.label(latest_chg).classes("text-xs font-medium")
                        with ui.row().classes("gap-2"):
                            ui.label("Risk Summary:").classes("font-semibold text-xs text-[var(--mp-muted)]")
                            ui.label(risk_sum).classes("text-xs font-medium text-amber-600")

            # Tab 4: Corporate Events
            with ui.tab_panel(t_events):
                if events.empty:
                    ui.label("No corporate announcements or board meetings recorded in the archive.").classes("text-sm text-[var(--mp-muted)] p-4")
                else:
                    event_rows = [
                        {
                            "Date": str(pd.to_datetime(e["event_date"]).date()),
                            "Type": str(e["event_type"]).replace("_", " ").title(),
                            "Headline": str(e["headline"]),
                        }
                        for _, e in events.iterrows()
                    ]
                    ui.table(
                        columns=[{"name": k, "label": k, "field": k, "align": "left"} for k in ["Date", "Type", "Headline"]],
                        rows=event_rows,
                        pagination=10,
                    ).classes("w-full mp-table text-xs")

    dialog.open()
