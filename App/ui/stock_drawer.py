"""Universal Stock 360° Drawer / Modal — Deep-dive institutional, technical, and event profile."""

from __future__ import annotations

import json
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

from App.indicators.darvas import calculate_darvas_box, is_darvas_10ema_squeeze

try:
    from App.cache_manager import get_cached, set_cached, cache_key
except ModuleNotFoundError:
    try:
        from cache_manager import get_cached, set_cached, cache_key  # type: ignore
    except ModuleNotFoundError:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from cache_manager import get_cached, set_cached, cache_key  # type: ignore


def tradingview_url(symbol: str) -> str:
    tok = str(symbol).strip().upper().replace("-", "_")
    return f"https://www.tradingview.com/chart/?symbol=NSE:{tok}"


def load_stock_note(user_db: Path, symbol: str) -> str:
    """Load user notes for symbol from portfolio_settings in marketpulse_user.duckdb."""
    try:
        with duckdb.connect(str(user_db), read_only=True) as db:
            r = db.execute("SELECT setting_value FROM portfolio_settings WHERE setting_key = ?", [f"note_{symbol}"]).fetchone()
            return str(r[0]) if r else ""
    except Exception:
        return ""


def save_stock_note(user_db: Path, symbol: str, text: str) -> None:
    """Save user notes for symbol to portfolio_settings in marketpulse_user.duckdb."""
    try:
        with duckdb.connect(str(user_db)) as db:
            db.execute(
                """
                INSERT INTO portfolio_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, now())
                ON CONFLICT (setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = now()
                """,
                [f"note_{symbol}", text],
            )
    except Exception:
        pass


def toggle_watchlist_symbol(user_db: Path, wl_num: int, symbol: str) -> bool:
    """Toggle symbol membership in quick watchlist 1, 2, or 3."""
    key = f"watchlist_{wl_num}"
    try:
        with duckdb.connect(str(user_db)) as db:
            r = db.execute("SELECT setting_value FROM portfolio_settings WHERE setting_key = ?", [key]).fetchone()
            current = set(json.loads(r[0])) if (r and r[0]) else set()
            if symbol in current:
                current.remove(symbol)
                added = False
            else:
                current.add(symbol)
                added = True
            db.execute(
                """
                INSERT INTO portfolio_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, now())
                ON CONFLICT (setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = now()
                """,
                [key, json.dumps(sorted(list(current)))],
            )
            return added
    except Exception:
        return False


def is_in_watchlist(user_db: Path, wl_num: int, symbol: str) -> bool:
    """Check if symbol is currently in quick watchlist 1, 2, or 3."""
    key = f"watchlist_{wl_num}"
    try:
        with duckdb.connect(str(user_db), read_only=True) as db:
            r = db.execute("SELECT setting_value FROM portfolio_settings WHERE setting_key = ?", [key]).fetchone()
            current = set(json.loads(r[0])) if (r and r[0]) else set()
            return symbol in current
    except Exception:
        return False


def query_stock_candlestick_data(db_path: Path, symbol: str, limit: int = 90) -> dict[str, Any]:
    """Query trailing OHLCV, EMAs, and Nicolas Darvas Box for technical candlestick charting."""
    sym = str(symbol).strip().upper()
    ckey = cache_key(db_path, "latest", "stock_candlestick_data", sym, limit)
    cached = get_cached(ckey)
    if cached is not None:
        return cached

    with duckdb.connect(str(db_path), read_only=True) as db:
        df = db.execute(
            """
            SELECT trade_date, open_price, close_price, low_price, high_price, volume,
                   ema_10, ema_20, ema_50, ema_200, rsi_14
            FROM indicators_daily
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT 400
            """,
            [sym],
        ).fetchdf()

    if df.empty:
        return {}

    df = df.iloc[::-1].reset_index(drop=True)

    # Darvas box on the trailing 400 sessions, then tail to the display window
    top_box, bottom_box = calculate_darvas_box(
        df["high_price"].values, df["low_price"].values, boxp=5
    )
    df["darvas_top"] = top_box
    df["darvas_bottom"] = bottom_box

    sub = df.tail(limit)
    dates = [str(pd.to_datetime(d).strftime("%Y-%m-%d")) for d in sub["trade_date"]]
    ohlc = [
        [
            float(r["open_price"] or 0),
            float(r["close_price"] or 0),
            float(r["low_price"] or 0),
            float(r["high_price"] or 0),
        ]
        for _, r in sub.iterrows()
    ]
    ema10 = [round(float(x), 2) if pd.notna(x) else None for x in sub["ema_10"]]
    ema20 = [round(float(x), 2) if pd.notna(x) else None for x in sub["ema_20"]]
    ema50 = [round(float(x), 2) if pd.notna(x) else None for x in sub["ema_50"]]
    ema200 = [round(float(x), 2) if pd.notna(x) else None for x in sub["ema_200"]]
    darvas_top = [round(float(x), 2) if pd.notna(x) else None for x in sub["darvas_top"]]
    darvas_bottom = [round(float(x), 2) if pd.notna(x) else None for x in sub["darvas_bottom"]]
    vol = [float(x or 0) for x in sub["volume"]]
    rsi = [round(float(x), 1) if pd.notna(x) else None for x in sub["rsi_14"]]

    # Squeeze evaluation on the most recent bar (verifying OHLC is inside the box in near range)
    last_close = float(sub["close_price"].iloc[-1]) if not sub.empty and pd.notna(sub["close_price"].iloc[-1]) else 0.0
    last_high = float(sub["high_price"].iloc[-1]) if not sub.empty and pd.notna(sub["high_price"].iloc[-1]) else 0.0
    last_low = float(sub["low_price"].iloc[-1]) if not sub.empty and pd.notna(sub["low_price"].iloc[-1]) else 0.0
    last_open = float(sub["open_price"].iloc[-1]) if not sub.empty and pd.notna(sub["open_price"].iloc[-1]) else 0.0
    last_top = float(top_box[-1]) if len(top_box) > 0 and pd.notna(top_box[-1]) else 0.0
    last_bottom = float(bottom_box[-1]) if len(bottom_box) > 0 and pd.notna(bottom_box[-1]) else 0.0
    last_ema10 = float(sub["ema_10"].iloc[-1]) if not sub.empty and pd.notna(sub["ema_10"].iloc[-1]) else 0.0
    is_squeeze = is_darvas_10ema_squeeze(
        last_close,
        last_top,
        last_bottom,
        last_ema10,
        high=last_high,
        low=last_low,
        open_price=last_open,
        max_squeeze_pct=3.5,
        max_candle_range_pct=3.5,
        require_ohlc_inside=True,
    )
    squeeze_pct = round(((last_top - last_ema10) / last_top) * 100.0, 2) if is_squeeze else None
    candle_range_pct = round(((last_high - last_low) / last_close) * 100.0, 2) if is_squeeze and last_close > 0 else None

    res = {
        "dates": dates,
        "ohlc": ohlc,
        "ema10": ema10,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "darvas_top": darvas_top,
        "darvas_bottom": darvas_bottom,
        "volume": vol,
        "rsi": rsi,
        "is_darvas_squeeze": is_squeeze,
        "darvas_squeeze_pct": squeeze_pct,
        "candle_range_pct": candle_range_pct,
        "latest_darvas_top": last_top if last_top > 0 else None,
        "latest_darvas_bottom": last_bottom if last_bottom > 0 else None,
    }
    set_cached(ckey, res)
    return res


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
                """,
                [sym],
            ).fetchdf()
        except duckdb.Error:
            ind = pd.DataFrame()

        # 2. Latest Decision / Candidate Setup
        try:
            cand = db.execute(
                """
                WITH latest AS (SELECT max(trade_date) AS max_d FROM candidate_setups)
                SELECT c.*, s.candidate_state, s.total_score, s.market_regime, s.sector_state, s.why_now, s.latest_change, s.risk_summary
                FROM candidate_setups c
                JOIN latest l ON c.trade_date = l.max_d
                LEFT JOIN swing_candidates s ON s.symbol = c.symbol AND s.trade_date = c.trade_date
                WHERE c.symbol = ?
                """,
                [sym],
            ).fetchdf()
        except duckdb.Error:
            cand = pd.DataFrame()

        # 3. Institutional Deals (Trailing 90 Days)
        try:
            deals = db.execute(
                """
                SELECT trade_date, deal_type, side, client_name, quantity, price, deal_value_cr
                FROM deals_daily
                WHERE symbol = ?
                ORDER BY trade_date DESC
                LIMIT 50
                """,
                [sym],
            ).fetchdf()
        except duckdb.Error:
            try:
                deals = db.execute(
                    """
                    SELECT trade_date, 'Bulk' AS deal_type, side, client_name, quantity, price, deal_value_cr
                    FROM deals
                    WHERE symbol = ?
                    ORDER BY trade_date DESC
                    LIMIT 50
                    """,
                    [sym],
                ).fetchdf()
            except duckdb.Error:
                deals = pd.DataFrame()

        # 4. Corporate Events
        try:
            events = db.execute(
                """
                SELECT event_date, event_type, headline
                FROM corporate_events
                WHERE symbol = ?
                ORDER BY event_date DESC
                LIMIT 20
                """,
                [sym],
            ).fetchdf()
        except duckdb.Error:
            events = pd.DataFrame()

        # 5. Master Reference (Circuits & Band Remarks)
        try:
            ref = db.execute(
                """
                SELECT band, band_remarks, is_trade_to_trade, is_fno
                FROM stocks_master
                WHERE symbol = ?
                """,
                [sym],
            ).fetchdf()
        except duckdb.Error:
            ref = pd.DataFrame()

        # 6. Company Enrichment (Business profile, themes, peers)
        user_db = db_path.parent / "marketpulse_user.duckdb"
        company_profile = {}
        thematic_tags = []
        peer_groups = []
        if user_db.exists():
            try:
                with duckdb.connect(str(user_db), read_only=True) as udb:
                    cp_df = udb.execute(
                        "SELECT company_name, business_summary, key_segments, core_products FROM company_profiles WHERE symbol = ?",
                        [sym],
                    ).fetchdf()
                    if not cp_df.empty:
                        company_profile = cp_df.iloc[0].to_dict()

                    tt_df = udb.execute(
                        "SELECT tag FROM thematic_tags WHERE symbol = ? ORDER BY tag",
                        [sym],
                    ).fetchall()
                    thematic_tags = [r[0] for r in tt_df]

                    pg_df = udb.execute(
                        "SELECT peer_symbol, similarity_type FROM peer_groups WHERE symbol = ? ORDER BY similarity_type, peer_symbol",
                        [sym],
                    ).fetchdf()
                    if not pg_df.empty:
                        peer_syms = pg_df["peer_symbol"].tolist()
                        placeholders = ",".join(["?"] * len(peer_syms))
                        peer_stats = db.execute(
                            f"""
                            WITH latest AS (SELECT max(trade_date) AS max_d FROM indicators_daily)
                            SELECT i.symbol, m.security_name, i.close_price,
                                   ROUND(((i.close_price - NULLIF(i.prev_close, 0)) / NULLIF(i.prev_close, 0)) * 100, 2) AS day_change_pct,
                                   m.market_cap_cr, m.industry
                            FROM indicators_daily i
                            JOIN latest l ON i.trade_date = l.max_d
                            LEFT JOIN stocks_master m ON m.symbol = i.symbol
                            WHERE i.symbol IN ({placeholders})
                            """,
                            peer_syms,
                        ).fetchdf()

                        stats_map = {r["symbol"]: r for r in peer_stats.to_dict("records")}
                        for _, row in pg_df.iterrows():
                            p_sym = row["peer_symbol"]
                            stat = stats_map.get(p_sym, {})
                            peer_groups.append({
                                "peer_symbol": p_sym,
                                "similarity_type": row["similarity_type"],
                                "company_name": stat.get("security_name") or p_sym,
                                "close_price": stat.get("close_price"),
                                "day_change_pct": stat.get("day_change_pct"),
                                "market_cap_cr": stat.get("market_cap_cr"),
                                "industry": stat.get("industry") or "—",
                            })
            except Exception:
                pass

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
        "company_profile": company_profile,
        "thematic_tags": thematic_tags,
        "peer_groups": peer_groups,
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
    events = data.get("events", pd.DataFrame())
    ref = data.get("reference", {})
    comp_prof = data.get("company_profile", {})
    thematic_tags = data.get("thematic_tags", [])
    peer_details = data.get("peer_groups", [])
    full_name = comp_prof.get("company_name") or profile.get("security_name") or ""

    user_db = db_path.parent / "marketpulse_user.duckdb"

    close_price = profile.get("close_price") or profile.get("latest_close") or 0.0
    day_change = profile.get("day_change_pct") or 0.0
    sector = profile.get("sector") or "Unclassified"
    industry = profile.get("industry") or "Unclassified"
    mcap = profile.get("market_cap_cr")
    rs = profile.get("rs_percentile")
    vcp_score = profile.get("vcp_score")
    vcp_state = profile.get("vcp_state") or "None"
    band_remarks = ref.get("band_remarks") or profile.get("band_remarks") or ""
    candidate_state = str(cand.get("candidate_state") or "No active setup")
    market_regime = str(cand.get("market_regime") or "Unknown")
    event_risk = str(cand.get("event_risk") or "none").title()
    data_as_of = str(cand.get("trade_date") or profile.get("trade_date") or "—")[:10]

    with ui.dialog().classes("mp-stock-dialog") as dialog, ui.card().classes(
        "w-[94vw] max-w-[1100px] h-[90vh] p-4 flex flex-col bg-[var(--mp-surface)] text-[var(--mp-text)] overflow-hidden"
    ):
        # Header Row
        with ui.row().classes("w-full items-start justify-between border-b border-[var(--mp-border)] pb-3 mb-2 mp-confirmation-header"):
            with ui.column().classes("gap-1"):
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    ui.label(sym).classes("text-2xl font-bold tracking-tight text-[var(--mp-text)]")
                    if full_name:
                        ui.label(full_name).classes("text-xs text-slate-300 font-medium self-center")
                    if mcap and pd.notna(mcap):
                        ui.label(f"MCap ₹{float(mcap):,.0f} Cr").classes("mp-badge mp-neutral")
                    if band_remarks:
                        ui.label(f"⚠️ {band_remarks}").classes("mp-badge mp-warn")
                    if vcp_state and vcp_state != "None":
                        tone = "mp-good" if vcp_state in ("Breakout", "Near Pivot") else "mp-info"
                        ui.label(vcp_state).classes(f"mp-badge {tone}")
                ui.label(f"{sector} · {industry}").classes("text-xs text-[var(--mp-muted)]")

                if thematic_tags:
                    with ui.row().classes("gap-1.5 items-center flex-wrap mt-1"):
                        for tag in thematic_tags:
                            ui.label(f"🏷️ {tag}").classes("mp-badge mp-info text-[10px]")

                with ui.row().classes("gap-2 flex-wrap mt-2"):
                    ui.label(f"Action State · {candidate_state}").classes("mp-badge mp-warn")
                    ui.label(f"Market Regime · {market_regime}").classes("mp-badge mp-neutral")
                    ui.label(f"Event Risk · {event_risk}").classes("mp-badge mp-neutral")
                    ui.label(f"Data As Of · {data_as_of}").classes("mp-badge mp-neutral")

            with ui.column().classes("items-end gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"₹{float(close_price):,.2f}").classes("text-2xl font-bold text-[var(--mp-text)]")
                    if pd.notna(day_change):
                        tone = "text-emerald-400" if day_change >= 0 else "text-rose-400"
                        ui.label(f"{day_change:+.2f}%").classes(f"text-sm font-semibold {tone}")

                # Quick Watchlists + Tools
                with ui.row().classes("gap-1.5 items-center mt-1 flex-wrap"):
                    wl_names = {1: "WL1 (Swing)", 2: "WL2 (Breakout)", 3: "WL3 (Core)"}
                    for wl_idx in (1, 2, 3):
                        in_wl = is_in_watchlist(user_db, wl_idx, sym)
                        name_str = wl_names[wl_idx]
                        btn_txt = f"{name_str} {'★' if in_wl else '+'}"
                        btn_color = "amber-9" if in_wl else "primary"
                        wl_btn = ui.button(btn_txt).props(f"dense {'unelevated' if in_wl else 'outline'} color={btn_color} size=xs").classes("text-xs font-semibold")

                        def make_toggle(idx=wl_idx, b=wl_btn, name=name_str):
                            def _handler():
                                added = toggle_watchlist_symbol(user_db, idx, sym)
                                color_val = "amber-9" if added else "primary"
                                b.props(f"dense {'unelevated' if added else 'outline'} color={color_val} size=xs")
                                b.set_text(f"{name} {'★' if added else '+'}")
                                ui.notify(f"{'★ Added to' if added else 'Removed from'} {name}: {sym}", type="positive" if added else "info")
                            return _handler

                        wl_btn.on_click(make_toggle(wl_idx, wl_btn, name_str))

                    tv_url = tradingview_url(sym)
                    ui.button("TV", on_click=lambda: ui.run_javascript(f'window.open("{tv_url}", "_blank")')).props("dense flat size=xs").classes("mp-primary")
                    if copy_text:
                        ui.button("Copy", on_click=lambda: copy_text(f"Symbol {sym}", f"NSE:{sym.replace('-', '_')}")).props("dense flat size=xs").classes("mp-button")
                    ui.button(icon="close", on_click=dialog.close).props("dense flat round size=xs").classes("text-slate-400")

        # Tabs for 360 sections
        with ui.tabs().classes("w-full mb-2") as tabs:
            t_chart = ui.tab("Technical Candlestick", icon="candlestick_chart")
            t_business = ui.tab("Business & Peers", icon="domain")
            t_overview = ui.tab("Overview & Indicators", icon="show_chart")
            t_notes = ui.tab("Notes & Study", icon="edit_note")
            t_deals = ui.tab("Institutional Pedigree", icon="account_balance")
            t_risk = ui.tab("Risk & Setup Geometry", icon="verified_user")
            t_events = ui.tab("Corporate Events", icon="event")

        with ui.tab_panels(tabs, value=t_chart).classes("w-full flex-1 overflow-y-auto"):
            # Tab 0: Candlestick + EMAs + Volume + RSI Chart
            with ui.tab_panel(t_chart).classes("mp-confirmation-section p-2 flex flex-col flex-nowrap gap-2"):
                cdata = query_stock_candlestick_data(db_path, sym, limit=90)
                if not cdata:
                    ui.label("No historical OHLCV indicators available for candlestick rendering.").classes("text-sm text-[var(--mp-muted)] p-4")
                else:
                    if cdata.get("is_darvas_squeeze"):
                        with ui.row().classes("w-full items-center justify-between px-3 py-1.5 rounded bg-emerald-950/40 border border-emerald-500/50 text-emerald-300 text-xs font-mono"):
                            ui.label("🎯 DARVAS 10 EMA SQUEEZE (OHLC INSIDE BOX)").classes("font-bold text-emerald-400 tracking-wide")
                            cr = f" · Candle Range: {cdata['candle_range_pct']:.1f}%" if cdata.get('candle_range_pct') is not None else ""
                            ui.label(f"Spread: {cdata['darvas_squeeze_pct']:.1f}%{cr} · Green Line: ₹{cdata['latest_darvas_top']:,.1f} · 10 EMA: ₹{cdata['ema10'][-1]:,.1f}").classes("font-semibold")

                    squeeze_mark_area = None
                    if cdata.get("is_darvas_squeeze") and cdata.get("latest_darvas_top"):
                        top_val = cdata["latest_darvas_top"]
                        ema_val = cdata["ema10"][-1] if cdata.get("ema10") and cdata["ema10"][-1] else None
                        bot_val = cdata.get("latest_darvas_bottom")
                        lower_bound = ema_val if ema_val is not None else bot_val
                        if lower_bound:
                            recent_idx = max(0, len(cdata["dates"]) - 15)
                            start_d = cdata["dates"][recent_idx]
                            end_d = cdata["dates"][-1]
                            squeeze_mark_area = {
                                "silent": True,
                                "itemStyle": {
                                    "color": "rgba(16, 185, 129, 0.09)",
                                    "borderColor": "rgba(16, 185, 129, 0.45)",
                                    "borderWidth": 1.5,
                                    "borderType": "dashed",
                                },
                                "data": [
                                    [
                                        {
                                            "name": "🎯 Squeeze Zone",
                                            "coord": [start_d, top_val],
                                            "label": {
                                                "show": True,
                                                "color": "#34d399",
                                                "fontSize": 10,
                                                "position": "insideTopRight",
                                                "formatter": f"🎯 Darvas Squeeze ({cdata.get('darvas_squeeze_pct', 0):.1f}%)" if cdata.get("darvas_squeeze_pct") else "🎯 Darvas Squeeze",
                                            },
                                        },
                                        {"coord": [end_d, min(top_val, lower_bound)]},
                                    ]
                                ],
                            }

                    total_bars = len(cdata["dates"])
                    zoom_20d_pct = max(0.0, round(((total_bars - 22) / max(total_bars, 1)) * 100.0, 1))
                    zoom_45d_pct = max(0.0, round(((total_bars - 45) / max(total_bars, 1)) * 100.0, 1))
                    zoom_start_pct = zoom_20d_pct

                    echart_opt = {
                        "backgroundColor": "transparent",
                        "animation": False,
                        "tooltip": {
                            "trigger": "axis",
                            "axisPointer": {"type": "cross"},
                            "confine": True,
                        },
                        "legend": {
                            "data": ["Price", "Darvas Top", "Darvas Bottom", "10 EMA", "20 EMA", "50 EMA", "200 EMA"],
                            "textStyle": {"color": "#94a3b8", "fontSize": 10},
                            "top": 0
                        },
                        "grid": [
                            {"left": "5%", "right": "3%", "top": "7%", "height": "60%"},
                            {"left": "5%", "right": "3%", "top": "70%", "height": "12%"},
                            {"left": "5%", "right": "3%", "top": "84%", "height": "10%"},
                        ],
                        "xAxis": [
                            {"type": "category", "gridIndex": 0, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"onZero": False, "lineStyle": {"color": "#334155"}}, "axisLabel": {"show": False}},
                            {"type": "category", "gridIndex": 1, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"onZero": False, "lineStyle": {"color": "#334155"}}, "axisLabel": {"show": False}},
                            {"type": "category", "gridIndex": 2, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"onZero": False, "lineStyle": {"color": "#334155"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 9}},
                        ],
                        "yAxis": [
                            {"scale": True, "gridIndex": 0, "splitLine": {"lineStyle": {"color": "#1e293b"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 10}},
                            {"scale": True, "gridIndex": 1, "splitLine": {"show": False}, "axisLabel": {"show": False}},
                            {"scale": True, "gridIndex": 2, "min": 0, "max": 100, "splitLine": {"lineStyle": {"color": "#1e293b"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 9}},
                        ],
                        "dataZoom": [
                            {
                                "type": "inside",
                                "xAxisIndex": [0, 1, 2],
                                "start": zoom_start_pct,
                                "end": 100,
                                "minValueSpan": 10,
                                "zoomOnMouseWheel": True,
                                "moveOnMouseMove": True,
                            },
                            {
                                "type": "slider",
                                "xAxisIndex": [0, 1, 2],
                                "start": zoom_start_pct,
                                "end": 100,
                                "height": 18,
                                "bottom": 2,
                                "borderColor": "#334155",
                                "fillerColor": "rgba(16, 185, 129, 0.18)",
                                "handleStyle": {"color": "#10b981", "borderColor": "#059669"},
                                "moveHandleStyle": {"color": "#10b981"},
                                "dataBackground": {
                                    "lineStyle": {"color": "#64748b"},
                                    "areaStyle": {"color": "rgba(100, 116, 139, 0.2)"},
                                },
                                "selectedDataBackground": {
                                    "lineStyle": {"color": "#10b981"},
                                    "areaStyle": {"color": "rgba(16, 185, 129, 0.3)"},
                                },
                                "textStyle": {"color": "#94a3b8", "fontSize": 10},
                            },
                        ],
                        "series": [
                            {
                                "name": "Price",
                                "type": "candlestick",
                                "xAxisIndex": 0,
                                "yAxisIndex": 0,
                                "data": cdata["ohlc"],
                                "itemStyle": {
                                    "color": "#10b981",
                                    "color0": "#ef4444",
                                    "borderColor": "#10b981",
                                    "borderColor0": "#ef4444"
                                },
                                "markArea": squeeze_mark_area,
                            },
                            {
                                "name": "Darvas Top",
                                "type": "line",
                                "step": "end",
                                "xAxisIndex": 0,
                                "yAxisIndex": 0,
                                "data": cdata.get("darvas_top", []),
                                "lineStyle": {"color": "#22c55e", "width": 2.5},
                                "showSymbol": False,
                            },
                            {
                                "name": "Darvas Bottom",
                                "type": "line",
                                "step": "end",
                                "xAxisIndex": 0,
                                "yAxisIndex": 0,
                                "data": cdata.get("darvas_bottom", []),
                                "lineStyle": {"color": "#ef4444", "width": 1.5},
                                "showSymbol": False,
                            },
                            {"name": "10 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema10"], "smooth": True, "lineStyle": {"color": "#ffffff", "width": 2.0}, "showSymbol": False},
                            {"name": "20 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema20"], "smooth": True, "lineStyle": {"color": "#fbbf24", "width": 1.5}, "showSymbol": False},
                            {"name": "50 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema50"], "smooth": True, "lineStyle": {"color": "#f97316", "width": 1.5}, "showSymbol": False},
                            {"name": "200 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema200"], "smooth": True, "lineStyle": {"color": "#ec4899", "width": 1.5}, "showSymbol": False},
                            {
                                "name": "Volume",
                                "type": "bar",
                                "xAxisIndex": 1,
                                "yAxisIndex": 1,
                                "data": cdata["volume"],
                                "itemStyle": {"color": "#475569"}
                            },
                            {
                                "name": "RSI(14)",
                                "type": "line",
                                "xAxisIndex": 2,
                                "yAxisIndex": 2,
                                "data": cdata["rsi"],
                                "lineStyle": {"color": "#a855f7", "width": 1.5},
                                "showSymbol": False
                            }
                        ]
                    }
                    modal_chart = ui.echart(echart_opt).classes("w-full h-[500px]")
                    with ui.row().classes("w-full items-center justify-end gap-2 my-1 text-xs"):
                        ui.label("Zoom Focus:").classes("text-[var(--mp-muted)] font-mono")
                        ui.button("🎯 20D (Squeeze Focus)", on_click=lambda: modal_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': zoom_20d_pct, 'end': 100})).props("dense outline size=xs").classes("mp-button")
                        ui.button("⏳ 45D (Base)", on_click=lambda: modal_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': zoom_45d_pct, 'end': 100})).props("dense outline size=xs").classes("mp-button")
                        ui.button("📊 90D (All)", on_click=lambda: modal_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': 0, 'end': 100})).props("dense outline size=xs").classes("mp-button")

            # Tab: Business & Peers
            with ui.tab_panel(t_business).classes("mp-confirmation-section p-3 flex flex-col flex-nowrap gap-3"):
                # 1. Business Profile Card
                with ui.card().classes("p-4 mp-card w-full"):
                    with ui.row().classes("w-full items-center justify-between mb-2"):
                        ui.label("Business Profile & Revenue Drivers").classes("text-sm font-bold text-[var(--mp-text)]")
                        if comp_prof.get("company_name"):
                            ui.label(comp_prof["company_name"]).classes("text-xs text-[var(--mp-muted)] font-mono")

                    if comp_prof.get("business_summary"):
                        ui.label(comp_prof["business_summary"]).classes("text-sm text-slate-200 leading-relaxed")
                    else:
                        ui.label("No business profile description available for this stock.").classes("text-xs text-[var(--mp-muted)] italic")

                    raw_segs = comp_prof.get("key_segments") or "[]"
                    raw_prods = comp_prof.get("core_products") or "[]"
                    try:
                        segments = json.loads(raw_segs) if isinstance(raw_segs, str) else raw_segs
                    except Exception:
                        segments = []
                    try:
                        products = json.loads(raw_prods) if isinstance(raw_prods, str) else raw_prods
                    except Exception:
                        products = []

                    if segments or products:
                        with ui.grid(columns=2).classes("w-full gap-4 mt-3 pt-3 border-t border-[var(--mp-border)]"):
                            with ui.column().classes("gap-1.5"):
                                ui.label("Key Operating Segments").classes("text-xs font-semibold text-[var(--mp-muted)]")
                                if segments:
                                    with ui.row().classes("gap-1.5 flex-wrap"):
                                        for seg in segments:
                                            ui.label(seg).classes("mp-badge mp-neutral text-xs")
                                else:
                                    ui.label("—").classes("text-xs text-[var(--mp-muted)]")

                            with ui.column().classes("gap-1.5"):
                                ui.label("Core Products & Services").classes("text-xs font-semibold text-[var(--mp-muted)]")
                                if products:
                                    with ui.row().classes("gap-1.5 flex-wrap"):
                                        for prod in products:
                                            ui.label(prod).classes("mp-badge mp-neutral text-xs")
                                else:
                                    ui.label("—").classes("text-xs text-[var(--mp-muted)]")

                # 2. Macro Thematic Catalysts Card
                with ui.card().classes("p-4 mp-card w-full"):
                    ui.label("Macro Investment Themes & Sectoral Tailwinds").classes("text-sm font-bold text-[var(--mp-text)] mb-2")
                    if thematic_tags:
                        with ui.row().classes("gap-2 flex-wrap"):
                            for tag in thematic_tags:
                                ui.label(f"🏷️ {tag}").classes("mp-badge mp-good text-xs font-semibold py-1 px-2.5")
                    else:
                        ui.label("No thematic tags mapped.").classes("text-xs text-[var(--mp-muted)] italic")

                # 3. Direct Peers & Sympathy Plays Card
                with ui.card().classes("p-4 mp-card w-full"):
                    with ui.row().classes("w-full items-center justify-between mb-2"):
                        with ui.column().classes("gap-0.5"):
                            ui.label("Direct Peers & Sympathy Plays").classes("text-sm font-bold text-[var(--mp-text)]")
                            ui.label("Tickers with correlated business drivers — cross-check when sector or stock moves").classes("text-xs text-[var(--mp-muted)]")
                        ui.label(f"{len(peer_details)} peers identified").classes("text-xs text-[var(--mp-muted)]")

                    if not peer_details:
                        ui.label("No direct peer relationships identified for this symbol.").classes("text-xs text-[var(--mp-muted)] italic")
                    else:
                        with ui.column().classes("w-full gap-2 mt-2"):
                            for p in peer_details:
                                p_sym = p["peer_symbol"]
                                sim_raw = p.get("similarity_type") or "thematic"
                                sim_label = sim_raw.replace("_", " ").title()
                                tone_sim = "mp-good" if sim_raw == "direct_competitor" else ("mp-info" if sim_raw == "supply_chain" else "mp-neutral")
                                p_px = p.get("close_price")
                                p_chg = p.get("day_change_pct")
                                p_mcap = p.get("market_cap_cr")
                                p_ind = p.get("industry") or "—"

                                with ui.row().classes("w-full items-center justify-between p-2.5 rounded-lg border border-[var(--mp-border)] bg-[var(--mp-surface-raised)] hover:bg-[var(--mp-surface-hover)] transition-colors"):
                                    with ui.row().classes("items-center gap-3"):
                                        def make_peer_open(peer_s=p_sym):
                                            def _handler():
                                                dialog.close()
                                                open_stock_360_modal(db_path, peer_s, copy_text=copy_text)
                                            return _handler
                                        ui.button(p_sym, on_click=make_peer_open(p_sym)).props("dense unelevated size=sm color=primary").classes("font-mono font-bold text-xs")
                                        ui.label(sim_label).classes(f"mp-badge {tone_sim} text-[10px]")
                                        ui.label(p["company_name"]).classes("text-xs text-slate-300 font-medium truncate max-w-[240px]")

                                    with ui.row().classes("items-center gap-3"):
                                        ui.label(p_ind).classes("text-xs text-[var(--mp-muted)] hidden md:block")
                                        if p_mcap and pd.notna(p_mcap):
                                            ui.label(f"₹{float(p_mcap):,.0f} Cr").classes("text-xs text-[var(--mp-muted)] font-mono")
                                        if p_px and pd.notna(p_px):
                                            ui.label(f"₹{float(p_px):,.2f}").classes("text-xs font-semibold font-mono")
                                        if pd.notna(p_chg):
                                            c_tone = "text-emerald-400" if float(p_chg) >= 0 else "text-rose-400"
                                            ui.label(f"{float(p_chg):+.2f}%").classes(f"text-xs font-semibold font-mono {c_tone}")

                                        p_tv = tradingview_url(p_sym)
                                        ui.button("TV", on_click=lambda url=p_tv: ui.run_javascript(f'window.open("{url}", "_blank")')).props("dense flat size=xs").classes("mp-primary")

            # Tab 2: Overview
            with ui.tab_panel(t_overview).classes("mp-confirmation-section"):
                try:
                    from App.ui.t_graph import geometry_for_symbol, render_t_panel
                except ModuleNotFoundError:
                    from ui.t_graph import geometry_for_symbol, render_t_panel  # type: ignore
                geo = geometry_for_symbol(db_path, sym)
                render_t_panel(db_path, sym)
                with ui.grid(columns=4).classes("w-full gap-3 mb-4 mt-3"):
                    with ui.card().classes("p-3 mp-card text-center"):
                        ui.label("RS Percentile").classes("text-xs text-[var(--mp-muted)]")
                        ui.label(f"{float(rs):.0f}" if pd.notna(rs) else "—").classes("text-xl font-bold")
                    with ui.card().classes("p-3 mp-card text-center"):
                        ui.label("SMA template").classes("text-xs text-[var(--mp-muted)]")
                        ui.label(geo["template"]["label"]).classes("text-xl font-bold")
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
                            tone = "text-emerald-400" if dist >= 0 else "text-rose-400"
                            with ui.card().classes("p-2 mp-card flex-1 min-w-[120px]"):
                                ui.label(name).classes("text-xs text-[var(--mp-muted)]")
                                ui.label(f"₹{float(val):,.1f}").classes("text-sm font-semibold")
                                ui.label(f"{dist:+.1f}%").classes(f"text-xs {tone}")

                # Volume & Delivery Profile
                deliv_pct = profile.get("delivery_pct")
                deliv_qty = profile.get("delivery_qty")
                turnover_cr = profile.get("turnover_cr")
                ui.label(f"Turnover: ₹{float(turnover_cr or 0):,.1f} Cr · Delivery: {float(deliv_pct or 0):.1f}% ({float(deliv_qty or 0):,.0f} shares)").classes("text-xs text-[var(--mp-muted)]")

            # Tab 2: User Notes & Study
            with ui.tab_panel(t_notes).classes("mp-confirmation-section p-4"):
                ui.label("Personal Research & Study Log").classes("text-sm font-bold text-[var(--mp-text)]")
                ui.label("Saved locally to marketpulse_user.duckdb").classes("text-xs text-[var(--mp-muted)] mb-3")
                existing_note = load_stock_note(user_db, sym)
                note_input = ui.textarea(
                    placeholder="Enter setup thesis, trade journal notes, catalysts, or levels...",
                    value=existing_note,
                ).classes("w-full font-mono text-xs border border-[var(--mp-border)] rounded-md p-2 bg-[var(--mp-surface-raised)]").props("rows=8")

                def _do_save():
                    save_stock_note(user_db, sym, note_input.value)
                    ui.notify(f"Note saved for {sym}", type="positive")

                ui.button("Save Research Note", on_click=_do_save).classes("mp-primary text-xs mt-2")

            # Tab 3: Institutional Pedigree
            with ui.tab_panel(t_deals).classes("mp-confirmation-section"):
                if deals.empty:
                    ui.label("No Bulk or Block deals recorded for this symbol.").classes("text-sm text-[var(--mp-muted)] p-4")
                else:
                    inst_only = deals[deals["is_institutional"] & (~deals["is_hft"])]
                    total_inst_buy = inst_only[inst_only["side"] == "BUY"]["deal_value_cr"].sum()
                    total_inst_sell = inst_only[inst_only["side"] == "SELL"]["deal_value_cr"].sum()

                    with ui.row().classes("w-full gap-3 mb-3"):
                        with ui.card().classes("p-3 mp-card flex-1"):
                            ui.label("Institutional BUY").classes("text-xs text-[var(--mp-muted)]")
                            ui.label(f"₹{total_inst_buy:,.1f} Cr").classes("text-lg font-bold text-emerald-400")
                        with ui.card().classes("p-3 mp-card flex-1"):
                            ui.label("Institutional SELL").classes("text-xs text-[var(--mp-muted)]")
                            ui.label(f"₹{total_inst_sell:,.1f} Cr").classes("text-lg font-bold text-rose-400")
                        with ui.card().classes("p-3 mp-card flex-1"):
                            net = total_inst_buy - total_inst_sell
                            tone = "text-emerald-400" if net >= 0 else "text-rose-400"
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

            # Tab 4: Risk & Setup Geometry
            with ui.tab_panel(t_risk).classes("mp-confirmation-section"):
                if not cand:
                    ui.label("No active focused-v2 candidate setup for this symbol.").classes("text-sm text-[var(--mp-muted)] p-4")
                else:
                    trigger = cand.get("trigger_price")
                    invalidation = cand.get("invalidation_price")
                    resistance = cand.get("first_resistance")
                    rr = cand.get("reward_to_risk")
                    rr_numeric = pd.to_numeric(rr, errors="coerce")
                    rr_valid = pd.notna(rr_numeric) and 0 < float(rr_numeric) <= 10
                    risk_pct = cand.get("initial_risk_pct")
                    why_now = cand.get("why_now") or "—"
                    latest_chg = cand.get("latest_change") or "—"
                    risk_sum = cand.get("risk_summary") or "—"

                    with ui.grid(columns=3).classes("w-full gap-3 mb-4 mp-risk-grid"):
                        with ui.card().classes("p-3 mp-card text-center"):
                            ui.label("Breakout Trigger").classes("text-xs text-[var(--mp-muted)]")
                            ui.label(f"₹{float(trigger):,.2f}" if trigger and pd.notna(trigger) else "—").classes("text-lg font-bold text-emerald-400")
                        with ui.card().classes("p-3 mp-card text-center"):
                            ui.label("Invalidation Support").classes("text-xs text-[var(--mp-muted)]")
                            ui.label(f"₹{float(invalidation):,.2f}" if invalidation and pd.notna(invalidation) else "—").classes("text-lg font-bold text-rose-400")
                        with ui.card().classes("p-3 mp-card text-center"):
                            ui.label("Reward / Risk").classes("text-xs text-[var(--mp-muted)]")
                            ui.label(f"{float(rr_numeric):.2f} R" if rr_valid else "Invalid geometry").classes("text-lg font-bold text-sky-400")

                    with ui.column().classes("gap-2 w-full p-3 mp-surface-2 rounded-lg"):
                        with ui.row().classes("gap-2"):
                            ui.label("Why Now:").classes("font-semibold text-xs text-[var(--mp-muted)]")
                            ui.label(why_now).classes("text-xs font-medium")
                        with ui.row().classes("gap-2"):
                            ui.label("Latest Change:").classes("font-semibold text-xs text-[var(--mp-muted)]")
                            ui.label(latest_chg).classes("text-xs font-medium")
                        with ui.row().classes("gap-2"):
                            ui.label("Risk Summary:").classes("font-semibold text-xs text-[var(--mp-muted)]")
                            ui.label(risk_sum).classes("text-xs font-medium text-amber-500")

            # Tab 5: Corporate Events
            with ui.tab_panel(t_events).classes("mp-confirmation-section"):
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


def render_stock_inspector_panel(
    db_path: Path,
    symbol: str,
    *,
    user_db: Path | None = None,
    copy_text: Any = None,
    on_close: Any = None,
) -> None:
    """Render an embedded, persistent stock inspector panel (Zero-Popup Solution)."""
    db_path = Path(db_path)
    if user_db is None:
        user_db = db_path.parent / "marketpulse_user.duckdb"
    user_db = Path(user_db)

    clean_sym = str(symbol or "").strip().upper()
    if not clean_sym:
        with ui.card().classes("w-full mp-card p-6 text-center border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
            ui.label("🔍 Stock Inspector").classes("text-sm font-bold uppercase tracking-wider text-[var(--mp-primary)] mb-2")
            ui.label("Click any stock from the matrix to view instant candlestick chart, Darvas levels, risk sizing, and institutional deals.").classes("text-xs text-[var(--mp-muted)] leading-relaxed")
        return

    data = query_stock_360_data(db_path, clean_sym)
    if not data:
        with ui.card().classes("w-full mp-card p-4 border border-[var(--mp-border)] bg-[var(--mp-surface)]"):
            ui.label(f"No technical profile found for {clean_sym}.").classes("text-xs text-[var(--mp-muted)]")
        return

    sym = data["symbol"]
    profile = data["profile"]
    cand = data["candidate_setup"]
    deals = data["deals"]
    comp_prof = data.get("company_profile", {})
    thematic_tags = data.get("thematic_tags", [])
    peer_details = data.get("peer_groups", [])
    full_name = comp_prof.get("company_name") or profile.get("security_name") or ""

    close_price = profile.get("close_price") or profile.get("latest_close") or 0.0
    day_change = profile.get("day_change_pct") or 0.0
    sector = profile.get("sector") or "Unclassified"
    industry = profile.get("industry") or "Unclassified"
    mcap = profile.get("market_cap_cr")
    rs = profile.get("rs_percentile")
    vcp_state = profile.get("vcp_state") or "None"

    with ui.card().classes("w-full mp-card p-3 border border-[var(--mp-border)] bg-[var(--mp-surface)] shadow-lg flex flex-col gap-2.5"):
        # 1. Header Row
        with ui.row().classes("w-full items-start justify-between border-b border-[var(--mp-border)] pb-2 flex-wrap gap-2"):
            with ui.column().classes("gap-0.5"):
                with ui.row().classes("items-center gap-1.5 flex-wrap"):
                    ui.label(sym).classes("text-xl font-bold tracking-tight text-[var(--mp-text)] font-mono")
                    if rs and pd.notna(rs):
                        ui.label(f"RS {float(rs):.0f}").classes("mp-badge mp-good text-[11px]")
                    if vcp_state and vcp_state != "None":
                        tone = "mp-good" if vcp_state in ("Breakout", "Near Pivot") else "mp-info"
                        ui.label(vcp_state).classes(f"mp-badge {tone} text-[10px]")
                if full_name:
                    ui.label(full_name).classes("text-[11px] text-slate-300 font-medium truncate max-w-[280px]")
                ui.label(f"{sector} · {industry}").classes("text-[10px] text-[var(--mp-muted)]")

            with ui.column().classes("items-end gap-1"):
                with ui.row().classes("items-center gap-1.5"):
                    ui.label(f"₹{float(close_price):,.2f}").classes("text-xl font-bold font-mono text-[var(--mp-text)]")
                    tone = "text-emerald-400" if float(day_change) >= 0 else "text-rose-400"
                    ui.label(f"{float(day_change):+.2f}%").classes(f"text-xs font-semibold font-mono {tone}")
                if mcap and pd.notna(mcap):
                    ui.label(f"MCap ₹{float(mcap):,.0f} Cr").classes("text-[10px] text-[var(--mp-muted)] font-mono")

        # 2. Quick Action Strip (Watchlist toggles + TV + Full 360)
        with ui.row().classes("w-full items-center justify-between py-1 border-b border-[var(--mp-border)] flex-wrap gap-1.5 text-xs"):
            with ui.row().classes("items-center gap-1"):
                wl_names = {1: "WL1", 2: "WL2", 3: "WL3"}
                for wl_idx in (1, 2, 3):
                    in_wl = is_in_watchlist(user_db, wl_idx, sym)
                    name_str = wl_names[wl_idx]
                    btn_color = "amber-9" if in_wl else "primary"
                    btn_txt = f"{name_str} {'★' if in_wl else '+'}"
                    wl_btn = ui.button(btn_txt).props(f"dense {'unelevated' if in_wl else 'outline'} color={btn_color} size=xs").classes("text-[10px] font-semibold")

                    def make_toggle(idx=wl_idx, b=wl_btn, nstr=name_str):
                        def _handler():
                            added = toggle_watchlist_symbol(user_db, idx, sym)
                            b.props(f"dense {'unelevated' if added else 'outline'} color={'amber-9' if added else 'primary'} size=xs")
                            b.set_text(f"{nstr} {'★' if added else '+'}")
                            ui.notify(f"{'★ Added to' if added else 'Removed from'} {nstr}: {sym}", type="positive" if added else "info")
                        return _handler
                    wl_btn.on_click(make_toggle(wl_idx, wl_btn, name_str))

            with ui.row().classes("items-center gap-1"):
                tv_url = tradingview_url(sym)
                ui.button("TV ↗", on_click=lambda: ui.run_javascript(f'window.open("{tv_url}", "_blank")')).props("dense flat size=xs").classes("text-[11px] text-sky-400")
                ui.button("Full 360", on_click=lambda: open_stock_360_modal(db_path, sym, copy_text=copy_text)).props("dense outline size=xs").classes("mp-button text-[10px]")
                if on_close:
                    ui.button("✕", on_click=on_close).props("dense flat round size=xs").classes("text-slate-400 text-xs")

        # 3. Interactive Candlestick + Darvas + EMAs Chart
        cdata = query_stock_candlestick_data(db_path, sym, limit=90)
        if cdata and cdata.get("ohlc"):
            if cdata.get("is_darvas_squeeze"):
                with ui.row().classes("w-full items-center justify-between px-2 py-1 rounded bg-emerald-950/50 border border-emerald-500/40 text-emerald-300 text-[11px] font-mono"):
                    ui.label("🎯 DARVAS 10 EMA SQUEEZE").classes("font-bold text-emerald-400")
                    sq_val = f"{cdata['darvas_squeeze_pct']:.1f}%" if cdata.get("darvas_squeeze_pct") is not None else ""
                    cr_val = f"Range: {cdata['candle_range_pct']:.1f}%" if cdata.get("candle_range_pct") is not None else ""
                    ui.label(f"Spread: {sq_val} · {cr_val}").classes("font-semibold")

            dates_len = len(cdata["dates"])
            z_start = max(0, int(((dates_len - 30) / max(1, dates_len)) * 100))

            echart_opt = {
                "backgroundColor": "transparent",
                "animation": False,
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
                "legend": {
                    "data": ["Price", "Darvas Top", "10 EMA", "20 EMA", "50 EMA", "200 EMA"],
                    "textStyle": {"color": "#94a3b8", "fontSize": 9},
                    "top": 0,
                    "itemWidth": 12,
                    "itemHeight": 6,
                },
                "grid": [
                    {"left": "8%", "right": "4%", "top": "12%", "height": "54%"},
                    {"left": "8%", "right": "4%", "top": "68%", "height": "14%"},
                    {"left": "8%", "right": "4%", "top": "84%", "height": "12%"},
                ],
                "xAxis": [
                    {"type": "category", "gridIndex": 0, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"lineStyle": {"color": "#334155"}}, "axisLabel": {"show": False}},
                    {"type": "category", "gridIndex": 1, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"lineStyle": {"color": "#334155"}}, "axisLabel": {"show": False}},
                    {"type": "category", "gridIndex": 2, "data": cdata["dates"], "boundaryGap": False, "scale": True, "axisLine": {"lineStyle": {"color": "#334155"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 9}},
                ],
                "yAxis": [
                    {"scale": True, "gridIndex": 0, "splitLine": {"lineStyle": {"color": "#1e293b"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 9}},
                    {"scale": True, "gridIndex": 1, "splitLine": {"show": False}, "axisLabel": {"show": False}},
                    {"scale": True, "gridIndex": 2, "min": 0, "max": 100, "splitLine": {"lineStyle": {"color": "#1e293b"}}, "axisLabel": {"color": "#94a3b8", "fontSize": 8}},
                ],
                "dataZoom": [
                    {"type": "inside", "xAxisIndex": [0, 1, 2], "start": z_start, "end": 100},
                ],
                "series": [
                    {
                        "name": "Price",
                        "type": "candlestick",
                        "xAxisIndex": 0,
                        "yAxisIndex": 0,
                        "data": cdata["ohlc"],
                        "itemStyle": {"color": "#10b981", "color0": "#ef4444", "borderColor": "#10b981", "borderColor0": "#ef4444"},
                    },
                    {
                        "name": "Darvas Top",
                        "type": "line",
                        "step": "end",
                        "xAxisIndex": 0,
                        "yAxisIndex": 0,
                        "data": cdata.get("darvas_top", []),
                        "lineStyle": {"color": "#22c55e", "width": 2},
                        "showSymbol": False,
                    },
                    {"name": "10 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema10"], "smooth": True, "lineStyle": {"color": "#ffffff", "width": 1.5}, "showSymbol": False},
                    {"name": "20 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema20"], "smooth": True, "lineStyle": {"color": "#fbbf24", "width": 1.5}, "showSymbol": False},
                    {"name": "50 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema50"], "smooth": True, "lineStyle": {"color": "#f97316", "width": 1.5}, "showSymbol": False},
                    {"name": "200 EMA", "type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": cdata["ema200"], "smooth": True, "lineStyle": {"color": "#ec4899", "width": 1.5}, "showSymbol": False},
                    {
                        "name": "Volume",
                        "type": "bar",
                        "xAxisIndex": 1,
                        "yAxisIndex": 1,
                        "data": cdata["volume"],
                        "itemStyle": {"color": "#475569"},
                    },
                    {
                        "name": "RSI(14)",
                        "type": "line",
                        "xAxisIndex": 2,
                        "yAxisIndex": 2,
                        "data": cdata["rsi"],
                        "lineStyle": {"color": "#a855f7", "width": 1.5},
                        "showSymbol": False,
                    },
                ],
            }
            inspector_chart = ui.echart(echart_opt).classes("w-full h-[320px]")
            with ui.row().classes("w-full items-center justify-end gap-1.5 text-[10px] font-mono"):
                ui.label("Zoom:").classes("text-[var(--mp-muted)]")
                z20 = max(0, int(((dates_len - 20) / max(1, dates_len)) * 100))
                z45 = max(0, int(((dates_len - 45) / max(1, dates_len)) * 100))
                ui.button("20D", on_click=lambda: inspector_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': z20, 'end': 100})).props("dense outline size=xs").classes("mp-button px-1.5 py-0")
                ui.button("45D", on_click=lambda: inspector_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': z45, 'end': 100})).props("dense outline size=xs").classes("mp-button px-1.5 py-0")
                ui.button("All", on_click=lambda: inspector_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': 0, 'end': 100})).props("dense outline size=xs").classes("mp-button px-1.5 py-0")
        else:
            ui.label("Candlestick data not available.").classes("text-xs text-[var(--mp-muted)] py-4 text-center")

        # 4. Risk & Position Sizing Calculator
        trigger_px = float(cand.get("trigger_price") or close_price * 1.01)
        stop_px = float(cand.get("invalidation_price") or profile.get("ema_20") or close_price * 0.95)
        res_px = float(cand.get("first_resistance") or trigger_px + (trigger_px - stop_px) * 2.0)
        risk_per_share = max(0.05, trigger_px - stop_px)
        risk_pct_val = (risk_per_share / trigger_px) * 100.0 if trigger_px > 0 else 5.0
        rr_val = ((res_px - trigger_px) / risk_per_share) if risk_per_share > 0 else 2.0

        with ui.card().classes("w-full mp-card p-2.5 bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
            with ui.row().classes("w-full items-center justify-between mb-1 text-[11px]"):
                ui.label("🎯 RISK GEOMETRY & SIZING").classes("font-bold text-[var(--mp-primary)] uppercase tracking-wider")
                ui.label(f"R:R {rr_val:.2f}").classes("font-bold font-mono text-sky-400 bg-sky-950/80 px-1.5 py-0.5 rounded border border-sky-500/30")

            with ui.grid(columns=3).classes("w-full gap-1.5 mb-2 text-center text-xs font-mono"):
                with ui.element("div").classes("p-1.5 rounded bg-[var(--mp-surface)] border border-[var(--mp-border)]"):
                    ui.label("Trigger").classes("text-[9px] text-[var(--mp-muted)] uppercase")
                    ui.label(f"₹{trigger_px:,.2f}").classes("font-bold text-emerald-400")
                with ui.element("div").classes("p-1.5 rounded bg-[var(--mp-surface)] border border-[var(--mp-border)]"):
                    ui.label("Stop Loss").classes("text-[9px] text-[var(--mp-muted)] uppercase")
                    ui.label(f"₹{stop_px:,.2f}").classes("font-bold text-rose-400")
                with ui.element("div").classes("p-1.5 rounded bg-[var(--mp-surface)] border border-[var(--mp-border)]"):
                    ui.label("Risk %").classes("text-[9px] text-[var(--mp-muted)] uppercase")
                    ui.label(f"{risk_pct_val:.1f}%").classes("font-bold text-amber-400")

            # Visual R:R track
            with ui.row().classes("w-full items-center justify-between text-[9px] font-mono text-[var(--mp-muted)]"):
                ui.label(f"Stop ₹{stop_px:,.1f}")
                ui.label(f"Target ₹{res_px:,.1f}")
            with ui.element("div").classes("w-full h-2 rounded-full overflow-hidden bg-slate-800 border border-slate-700 flex mb-2"):
                ui.element("div").classes("h-full bg-rose-500/60 w-[30%]")
                ui.element("div").classes("h-full bg-emerald-500/70 w-[70%]")

            # Interactive Position Sizer
            with ui.row().classes("w-full items-center justify-between gap-2 pt-1 border-t border-[var(--mp-border)]"):
                with ui.row().classes("items-center gap-1"):
                    ui.label("Cap: ₹").classes("text-[10px] text-[var(--mp-muted)]")
                    cap_in = ui.number(value=1000000, step=100000).classes("w-20 text-[11px] font-mono").props("dense borderless")
                with ui.row().classes("items-center gap-1"):
                    ui.label("Risk %:").classes("text-[10px] text-[var(--mp-muted)]")
                    risk_in = ui.number(value=1.0, step=0.5, min=0.25, max=5.0).classes("w-14 text-[11px] font-mono").props("dense borderless")

            shares_lbl = ui.label("Shares: —").classes("text-[11px] font-mono text-emerald-300 font-bold mt-1")

            def update_shares():
                cap_val = float(cap_in.value or 1000000)
                r_pct = float(risk_in.value or 1.0)
                r_amt = cap_val * (r_pct / 100.0)
                shares = max(1, int(r_amt / risk_per_share))
                tot_val = shares * float(close_price)
                shares_lbl.set_text(f"Size: {shares:,} shares (₹{tot_val:,.0f} · {tot_val/cap_val*100:.1f}% cap)")

            cap_in.on_value_change(lambda _: update_shares())
            risk_in.on_value_change(lambda _: update_shares())
            update_shares()

        # 5. Recent Institutional Deals
        if deals is not None and not deals.empty:
            with ui.card().classes("w-full mp-card p-2.5 bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                with ui.row().classes("w-full items-center justify-between mb-1.5"):
                    ui.label("🏛️ INSTITUTIONAL ACCUMULATION").classes("font-bold text-[10px] text-[var(--mp-primary)] uppercase tracking-wider")
                    deal_cnt = len(deals)
                    ui.label(f"{deal_cnt} Deals (20D)").classes("text-[10px] text-[var(--mp-muted)] font-mono")

                with ui.column().classes("w-full gap-1"):
                    for _, d in deals.head(3).iterrows():
                        client = str(d.get("client_name") or "Institution")
                        tier = str(d.get("tier") or "FII")
                        side = str(d.get("side") or "BUY")
                        d_val = float(d.get("deal_value_cr") or 0.0)
                        d_px = float(d.get("price") or 0.0)
                        side_tone = "text-emerald-400" if side == "BUY" else "text-rose-400"
                        badge_cls = "mp-deal-badge-fii" if "FII" in tier else "mp-deal-badge-prop" if "HFT" in tier or "PROP" in tier else "mp-deal-badge-dii"

                        with ui.row().classes("w-full items-center justify-between text-[11px] font-mono py-0.5 border-b border-slate-800"):
                            with ui.row().classes("items-center gap-1 truncate max-w-[240px]"):
                                ui.label(tier[:4]).classes(f"text-[9px] px-1 py-0 rounded font-bold uppercase {badge_cls}")
                                ui.label(client).classes("truncate text-[11px] text-slate-200")
                            with ui.row().classes("items-center gap-1"):
                                ui.label(side).classes(f"font-bold {side_tone}")
                                ui.label(f"₹{d_val:,.1f}Cr").classes("font-bold text-slate-100")

        # 6. Themes & Peers Context
        if thematic_tags or peer_details:
            with ui.card().classes("w-full mp-card p-2.5 bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                if thematic_tags:
                    with ui.row().classes("items-center gap-1 flex-wrap mb-2"):
                        ui.label("THEMES:").classes("text-[9px] font-bold text-[var(--mp-muted)]")
                        for t in thematic_tags[:3]:
                            ui.label(f"🏷️ {t}").classes("mp-badge mp-good text-[10px] py-0 px-1.5")
                if peer_details:
                    with ui.row().classes("items-center justify-between mb-1"):
                        ui.label("INDUSTRY PEERS").classes("text-[9px] font-bold text-[var(--mp-muted)] uppercase")
                    with ui.column().classes("w-full gap-1"):
                        for p in peer_details[:3]:
                            p_sym = p.get("symbol")
                            p_rs = p.get("rs_percentile")
                            p_cmp = p.get("close_price")
                            p_5d = p.get("return_5d_pct")
                            p_tone = "text-emerald-400" if p_5d and float(p_5d) >= 0 else "text-rose-400"
                            with ui.row().classes("w-full items-center justify-between text-[11px] font-mono"):
                                ui.label(p_sym).classes("font-bold text-sky-400")
                                ui.label(f"RS {float(p_rs):.0f}" if p_rs else "—").classes("text-[var(--mp-muted)]")
                                ui.label(f"₹{float(p_cmp):,.1f}" if p_cmp else "—").classes("text-slate-300")
                                ui.label(f"{float(p_5d):+.1f}%" if p_5d else "—").classes(f"font-bold {p_tone}")
