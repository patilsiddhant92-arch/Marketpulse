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

from App.indicators.darvas import (
    DARVAS,
    calculate_darvas_box,
    darvas_v2_enabled,
    is_darvas_10ema_squeeze,
    is_darvas_10ema_squeeze_legacy,
)

try:
    from App.cache_manager import get_cached, set_cached, cache_key
except ModuleNotFoundError:
    try:
        from cache_manager import get_cached, set_cached, cache_key  # type: ignore
    except ModuleNotFoundError:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from cache_manager import get_cached, set_cached, cache_key  # type: ignore

try:
    from Scripts.institutional_attribution import fetch_stock_fund_attribution
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "Scripts"))
    try:
        from institutional_attribution import fetch_stock_fund_attribution  # type: ignore
    except ModuleNotFoundError:
        fetch_stock_fund_attribution = None


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


def query_stock_candlestick_data(
    db_path: Path, symbol: str, limit: int = 90, *, predicate: dict | None = None
) -> dict[str, Any]:
    """Query trailing OHLCV, EMAs, and Nicolas Darvas Box for technical candlestick charting."""
    sym = str(symbol).strip().upper()
    use_v2 = predicate is not None or darvas_v2_enabled()
    if predicate:
        pred_tag = "pred_" + "_".join(f"{k}={predicate[k]}" for k in sorted(predicate))
    else:
        pred_tag = "v2" if use_v2 else "v1"
    ckey = cache_key(db_path, "latest", "stock_candlestick_data", sym, limit, pred_tag)
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
    last_ema20 = float(sub["ema_20"].iloc[-1]) if not sub.empty and pd.notna(sub["ema_20"].iloc[-1]) else None
    if use_v2:
        cfg = {**DARVAS, **(predicate or {})}
        is_squeeze = is_darvas_10ema_squeeze(
            last_close,
            last_top,
            last_bottom,
            last_ema10,
            high=last_high,
            low=last_low,
            open_price=last_open,
            max_squeeze_pct=float(cfg["max_squeeze_pct"]),
            max_candle_range_pct=float(cfg["max_range_pct"]),
            require_ohlc_inside=True,
            ema20=last_ema20,
            cfg=cfg,
        )
    else:
        is_squeeze = is_darvas_10ema_squeeze_legacy(
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
    squeeze_pct = (
        round(((last_top - last_ema10) / last_top) * 100.0, 2) if is_squeeze and last_top > 0 else None
    )
    candle_range_pct = (
        round(((last_high - last_low) / last_close) * 100.0, 2) if is_squeeze and last_close > 0 else None
    )

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


def query_stock_peer_comparison(
    db_path: Path,
    symbol: str,
    *,
    db_con: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Any] | None:
    """Fetch live industry and sector peer rankings, comparative metrics, and 'better options'.
    
    Returns a dict with:
        - target: dict of target stock stats
        - group_type: 'Industry' or 'Sector'
        - group_name: name of the peer group
        - industry: str
        - sector: str
        - target_rank: int (1-based rank by RS within peer group)
        - total_peers: int
        - is_leader: bool (True if target_rank == 1)
        - peers_df: pd.DataFrame (all peers sorted by RS DESC)
        - better_options: list[dict] (actionable higher-RS or coiled leader peers)
        - sector_leaders_df: pd.DataFrame (top leaders across parent sector)
    """
    sym = str(symbol).strip().upper()
    if not sym:
        return None

    ckey = cache_key(db_path, "latest", "stock_peer_comparison", sym)
    cached = get_cached(ckey)
    if cached is not None:
        return cached

    def _query(db: duckdb.DuckDBPyConnection) -> dict[str, Any] | None:
        try:
            t_df = db.execute(
                """
                SELECT 
                    m.symbol, m.security_name, m.industry, m.sector, m.broad_industry, m.market_cap_cr,
                    i.trade_date, i.close_price, i.prev_close,
                    ROUND(((i.close_price - NULLIF(i.prev_close, 0)) / NULLIF(i.prev_close, 0)) * 100, 2) AS day_pct,
                    ROUND(COALESCE(i.rs_percentile, 0), 1) AS rs_percentile,
                    ROUND(i.away_10ema_pct, 1) AS away_10ema_pct,
                    ROUND(i.away_52w_high_pct, 1) AS away_52w_pct,
                    ROUND(i.rvol, 1) AS rvol,
                    ROUND(i.delivery_pct, 1) AS delivery_pct,
                    COALESCE(i.vcp_state, '') AS vcp_state
                FROM indicators_daily i
                JOIN stocks_master m ON m.symbol = i.symbol
                WHERE m.symbol = ?
                ORDER BY i.trade_date DESC
                LIMIT 1
                """,
                [sym],
            ).fetchdf()
        except duckdb.Error:
            return None

        if t_df.empty:
            return None

        t_row = t_df.iloc[0].to_dict()
        dt = t_row["trade_date"]
        ind = str(t_row.get("industry") or "").strip()
        sec = str(t_row.get("sector") or "").strip()
        target_rs = float(t_row.get("rs_percentile") or 0.0)
        target_away10 = float(t_row.get("away_10ema_pct") or 0.0)

        where_col = "m.industry" if ind else "m.sector"
        where_val = ind if ind else sec

        def fetch_peers(col_name: str, val: str) -> pd.DataFrame:
            try:
                return db.execute(
                    f"""
                    SELECT 
                        m.symbol, m.security_name, m.industry, m.sector, m.market_cap_cr,
                        i.close_price, 
                        ROUND(((i.close_price - NULLIF(i.prev_close, 0)) / NULLIF(i.prev_close, 0)) * 100, 2) AS day_pct,
                        ROUND(COALESCE(i.rs_percentile, 0), 1) AS rs_percentile,
                        ROUND(i.away_10ema_pct, 1) AS away_10ema_pct,
                        ROUND(i.away_52w_high_pct, 1) AS away_52w_pct,
                        ROUND(i.rvol, 1) AS rvol,
                        ROUND(i.delivery_pct, 1) AS delivery_pct,
                        COALESCE(i.vcp_state, '') AS vcp_state
                    FROM indicators_daily i
                    JOIN stocks_master m ON m.symbol = i.symbol
                    WHERE i.trade_date = ? AND {col_name} = ?
                    ORDER BY i.rs_percentile DESC NULLS LAST, i.close_price DESC
                    """,
                    [dt, val],
                ).fetchdf()
            except duckdb.Error:
                return pd.DataFrame()

        peers_df = fetch_peers(where_col, where_val) if where_val else pd.DataFrame()
        if len(peers_df) < 2 and sec and where_col != "m.sector":
            where_col = "m.sector"
            where_val = sec
            peers_df = fetch_peers(where_col, where_val)

        if peers_df.empty:
            peers_df = t_df.copy()

        peers_df["rs_rank"] = range(1, len(peers_df) + 1)
        target_match = peers_df[peers_df["symbol"] == sym]
        target_rank = int(target_match.iloc[0]["rs_rank"]) if not target_match.empty else 1

        better: list[dict[str, Any]] = []
        for _, r in peers_df.iterrows():
            p_sym = str(r["symbol"])
            if p_sym == sym:
                continue
            p_rs = float(r["rs_percentile"]) if pd.notna(r["rs_percentile"]) else 0.0
            p_10ema = float(r["away_10ema_pct"]) if pd.notna(r["away_10ema_pct"]) else 0.0
            p_52w = float(r["away_52w_pct"]) if pd.notna(r["away_52w_pct"]) else -99.0
            p_rvol = float(r["rvol"]) if pd.notna(r["rvol"]) else 1.0
            p_vcp = str(r.get("vcp_state") or "")

            reasons: list[str] = []
            score = 0.0
            if p_rs > target_rs + 3:
                reasons.append(f"Higher RS ({p_rs:.0f} vs {target_rs:.0f})")
                score += (p_rs - target_rs)
            if target_away10 > 7.0 and -2.0 <= p_10ema <= 5.0 and p_rs >= 70:
                reasons.append(f"Coiled at 10 EMA (+{p_10ema:.1f}%)")
                score += 30
            if p_52w >= -5.0 and p_rs >= 80:
                reasons.append(f"Near 52W High ({p_52w:+.1f}%)")
                score += 20
            if p_rvol >= 2.5:
                reasons.append(f"Surging Volume ({p_rvol:.1f}x RVOL)")
                score += 15
            if p_vcp in ("Breakout", "Near Pivot"):
                reasons.append(f"VCP {p_vcp}")
                score += 15

            if reasons:
                better.append({
                    "symbol": p_sym,
                    "security_name": str(r["security_name"]),
                    "rs_percentile": p_rs,
                    "away_10ema_pct": p_10ema,
                    "away_52w_pct": p_52w,
                    "rvol": p_rvol,
                    "day_pct": r["day_pct"],
                    "close_price": r["close_price"],
                    "rank": int(r["rs_rank"]),
                    "reason": " · ".join(reasons[:2]),
                    "score": score,
                })

        better.sort(key=lambda x: x["score"], reverse=True)

        sec_leaders_df = pd.DataFrame()
        if sec:
            try:
                sec_leaders_df = db.execute(
                    """
                    SELECT 
                        m.symbol, m.security_name, m.industry, m.market_cap_cr,
                        i.close_price, 
                        ROUND(((i.close_price - NULLIF(i.prev_close, 0)) / NULLIF(i.prev_close, 0)) * 100, 2) AS day_pct,
                        ROUND(COALESCE(i.rs_percentile, 0), 1) AS rs_percentile,
                        ROUND(i.away_10ema_pct, 1) AS away_10ema_pct,
                        ROUND(i.away_52w_high_pct, 1) AS away_52w_pct,
                        ROUND(i.rvol, 1) AS rvol
                    FROM indicators_daily i
                    JOIN stocks_master m ON m.symbol = i.symbol
                    WHERE i.trade_date = ? AND m.sector = ?
                    ORDER BY i.rs_percentile DESC NULLS LAST
                    LIMIT 8
                    """,
                    [dt, sec],
                ).fetchdf()
            except duckdb.Error:
                sec_leaders_df = pd.DataFrame()

        return {
            "target": t_row,
            "group_type": "Industry" if where_col == "m.industry" else "Sector",
            "group_name": where_val,
            "industry": ind,
            "sector": sec,
            "target_rank": target_rank,
            "total_peers": len(peers_df),
            "is_leader": target_rank == 1,
            "peers_df": peers_df,
            "better_options": better[:6],
            "sector_leaders_df": sec_leaders_df,
        }

    res = None
    if db_con is not None:
        try:
            res = _query(db_con)
        except Exception:
            pass

    if res is None:
        with duckdb.connect(str(db_path), read_only=True) as db:
            res = _query(db)

    if res is not None:
        set_cached(ckey, res)
    return res


def query_stock_360_data(db_path: Path, symbol: str) -> dict[str, Any]:
    """Fetch complete multi-dimensional data for a symbol in a single query transaction."""
    sym = str(symbol).strip().upper()
    if not sym:
        return {}

    ckey = cache_key(db_path, "latest", "stock_360_data", sym)
    cached = get_cached(ckey)
    if cached is not None:
        return cached

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

        # 2. Latest Decision / Candidate Setup from real candidate_daily table
        try:
            cand = db.execute(
                """
                WITH latest AS (
                    SELECT max(trade_date) AS max_d 
                    FROM candidate_daily 
                    WHERE score_version = 'focused-v2'
                )
                SELECT c.*
                FROM candidate_daily c
                JOIN latest l ON c.trade_date = l.max_d
                WHERE c.symbol = ? AND c.score_version = 'focused-v2'
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

        # 4. Corporate Events from real security_events table
        try:
            events = db.execute(
                """
                SELECT event_date, event_type, headline
                FROM security_events
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

        peer_comparison = query_stock_peer_comparison(db_path, sym, db_con=db)

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

    fund_attribution = []
    if fetch_stock_fund_attribution is not None:
        try:
            fund_attribution = fetch_stock_fund_attribution(db_path, sym)
        except Exception:
            fund_attribution = []

    res = {
        "symbol": sym,
        "profile": profile,
        "candidate_setup": candidate_setup,
        "deals": deals,
        "events": events,
        "reference": ref_row,
        "company_profile": company_profile,
        "thematic_tags": thematic_tags,
        "peer_groups": peer_groups,
        "peer_comparison": peer_comparison,
        "fund_attribution": fund_attribution,
    }
    set_cached(ckey, res)
    return res


def _clean_symbol_param(sym: Any) -> str:
    """Sanitize symbol parameter to handle lists, dicts, or stringified list artifacts."""
    if isinstance(sym, (list, tuple)):
        sym = sym[0] if sym else ""
    if isinstance(sym, dict):
        sym = sym.get("symbol") or sym.get("value") or ""
    s = str(sym or "").strip()
    if (s.startswith("['") and s.endswith("']")) or (s.startswith('["') and s.endswith('"]')):
        s = s[2:-2].strip()
    return s.upper()


def open_stock_360_modal(
    db_path: Path,
    symbol: str,
    *,
    copy_text: Any = None,
) -> None:
    """Open interactive slide-over dialog for any stock."""
    clean_sym = _clean_symbol_param(symbol)
    if not clean_sym:
        ui.notify("No symbol provided", type="warning")
        return
    data = query_stock_360_data(db_path, clean_sym)
    if not data:
        ui.notify(f"No data available for {clean_sym}", type="warning")
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
    peer_comp = data.get("peer_comparison") or query_stock_peer_comparison(db_path, sym)
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
                    if peer_comp:
                        p_rk = peer_comp["target_rank"]
                        p_tot = peer_comp["total_peers"]
                        p_grp = peer_comp["group_name"]
                        rk_tone = "mp-good" if p_rk <= 3 else "mp-info" if p_rk <= 10 else "mp-neutral"
                        ui.label(f"Industry Rank #{p_rk} of {p_tot} ({p_grp})").classes(f"mp-badge {rk_tone} font-semibold")
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
                    ui.button("TV", on_click=lambda url=tv_url: ui.run_javascript(f'window.open("{url}", "_blank")')).props("dense flat size=xs").classes("mp-primary")
                    if copy_text:
                        ui.button("Copy", on_click=lambda *_, s=sym: copy_text(f"Symbol {s}", f"NSE:{s.replace('-', '_')}")).props("dense flat size=xs").classes("mp-button")
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
                            "backgroundColor": "rgba(15, 23, 42, 0.95)",
                            "borderColor": "#334155",
                            "borderWidth": 1,
                            "textStyle": {"color": "#f8fafc", "fontSize": 11, "fontFamily": "IBM Plex Mono"},
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

                # 3. Industry Peer Comparison & Relative Strength Leaderboard
                with ui.card().classes("p-4 mp-card w-full"):
                    all_peer_syms = []
                    if peer_comp and not peer_comp["peers_df"].empty:
                        all_peer_syms = [str(s) for s in peer_comp["peers_df"]["symbol"].dropna().tolist()]

                    with ui.row().classes("w-full items-center justify-between mb-3 border-b border-[var(--mp-border)] pb-2 flex-wrap gap-2"):
                        with ui.column().classes("gap-0.5"):
                            ui.label("Industry Peers & Relative Strength Leaderboard").classes("text-sm font-bold text-[var(--mp-text)]")
                            if peer_comp:
                                ui.label(f"Rank #{peer_comp['target_rank']} of {peer_comp['total_peers']} in {peer_comp['group_name']} (Sector: {peer_comp['sector']})").classes("text-xs text-sky-400 font-medium")
                            else:
                                ui.label("Cross-check momentum and leadership across industry peers").classes("text-xs text-[var(--mp-muted)]")

                        with ui.row().classes("items-center gap-2"):
                            if all_peer_syms and copy_text:
                                tv_copy_str = ",".join(f"NSE:{s.replace('-', '_')}" for s in all_peer_syms)
                                grp_lbl = peer_comp["group_name"] if peer_comp else "Industry"
                                ui.button(
                                    f"📋 Copy All Peers ({len(all_peer_syms)})",
                                    on_click=lambda *_, t=tv_copy_str, g=grp_lbl: copy_text(f"{g} Peers", t)
                                ).props("dense outline size=sm color=primary").classes("text-xs font-mono")

                    # Better Options in this Industry
                    if peer_comp and peer_comp.get("better_options"):
                        better_opts = peer_comp["better_options"]
                        with ui.column().classes("w-full gap-2 mb-4 p-3 bg-emerald-950/20 border border-emerald-500/30 rounded-lg"):
                            with ui.row().classes("items-center gap-2"):
                                ui.label("🌟 BETTER OPTIONS IN THIS INDUSTRY:").classes("text-xs font-bold text-emerald-400 tracking-wider")
                                ui.label("Higher RS / Coiled at 10 EMA / High Volume Breakouts").classes("text-[11px] text-[var(--mp-muted)]")

                            with ui.grid(columns=3).classes("w-full gap-2.5"):
                                for bo in better_opts[:6]:
                                    bo_sym = bo["symbol"]
                                    bo_name = bo.get("security_name") or bo_sym
                                    bo_rs = bo["rs_percentile"]
                                    bo_10ema = bo["away_10ema_pct"]
                                    bo_52w = bo["away_52w_pct"]
                                    bo_rvol = bo["rvol"]
                                    bo_day = bo["day_pct"]
                                    bo_px = bo["close_price"]
                                    bo_rk = bo["rank"]
                                    bo_reason = bo["reason"]

                                    with ui.card().classes("p-2.5 mp-card bg-[var(--mp-surface-raised)] border border-emerald-500/20 hover:border-emerald-500/50 transition-all flex flex-col justify-between gap-1.5"):
                                        with ui.row().classes("w-full items-center justify-between"):
                                            with ui.row().classes("items-center gap-1.5"):
                                                ui.label(f"#{bo_rk}").classes("text-[10px] text-slate-400 font-mono")
                                                ui.label(bo_sym).classes("font-bold text-xs text-sky-400 font-mono")
                                            ui.label(f"RS {bo_rs:.0f}").classes("mp-badge mp-good text-[10px] font-bold")

                                        ui.label(bo_name).classes("text-[11px] text-slate-300 truncate max-w-[200px]")

                                        with ui.row().classes("w-full items-center justify-between text-[11px] font-mono"):
                                            ui.label(f"₹{float(bo_px):,.1f}").classes("text-slate-200")
                                            day_tone = "text-emerald-400" if bo_day and float(bo_day) >= 0 else "text-rose-400"
                                            ui.label(f"{float(bo_day):+.1f}%").classes(f"font-bold {day_tone}")

                                        with ui.row().classes("w-full items-center justify-between text-[10px] font-mono text-[var(--mp-muted)]"):
                                            ui.label(f"10EMA {float(bo_10ema):+.1f}%")
                                            ui.label(f"52W {float(bo_52w):+.1f}%")
                                            ui.label(f"RVOL {float(bo_rvol):.1f}x")

                                        ui.label(bo_reason).classes("text-[10px] font-semibold text-emerald-400/90 truncate")

                                        with ui.row().classes("w-full items-center justify-end gap-1.5 pt-1 border-t border-slate-800"):
                                            def make_bo_open(bsym=bo_sym):
                                                def _h():
                                                    dialog.close()
                                                    open_stock_360_modal(db_path, bsym, copy_text=copy_text)
                                                return _h
                                            ui.button("Open 360", on_click=make_bo_open(bo_sym)).props("dense unelevated size=xs color=primary").classes("text-[10px]")
                                            bo_tv = tradingview_url(bo_sym)
                                            ui.button("TV", on_click=lambda *_, u=bo_tv: ui.run_javascript(f'window.open("{u}", "_blank")')).props("dense flat size=xs").classes("mp-primary text-[10px]")

                    elif peer_comp and peer_comp.get("is_leader"):
                        with ui.row().classes("w-full items-center gap-2 mb-3 p-2.5 bg-amber-950/20 border border-amber-500/40 rounded-lg text-amber-300 text-xs font-bold"):
                            ui.label(f"🏆 {sym} is the #1 Relative Strength Leader in {peer_comp['group_name']} (RS {peer_comp['target'].get('rs_percentile', 0):.0f})!")

                    # Full Interactive Peer Table
                    if peer_comp and not peer_comp["peers_df"].empty:
                        p_rows = []
                        for _, r in peer_comp["peers_df"].iterrows():
                            psym = str(r["symbol"])
                            p_px = r.get("close_price")
                            p_day = r.get("day_pct")
                            p_rs = r.get("rs_percentile")
                            p_10e = r.get("away_10ema_pct")
                            p_52w = r.get("away_52w_pct")
                            p_rv = r.get("rvol")
                            p_del = r.get("delivery_pct")
                            p_vcp = r.get("vcp_state") or "—"
                            is_curr = psym == sym
                            p_rows.append({
                                "Rank": int(r["rs_rank"]),
                                "Symbol": f"▶ {psym}" if is_curr else psym,
                                "Company": str(r.get("security_name") or psym)[:22],
                                "Price": f"₹{float(p_px):,.1f}" if p_px and pd.notna(p_px) else "—",
                                "Day %": f"{float(p_day):+.2f}%" if p_day and pd.notna(p_day) else "—",
                                "RS": f"{float(p_rs):.0f}" if p_rs and pd.notna(p_rs) else "—",
                                "10EMA %": f"{float(p_10e):+.1f}%" if p_10e and pd.notna(p_10e) else "—",
                                "52W High %": f"{float(p_52w):+.1f}%" if p_52w and pd.notna(p_52w) else "—",
                                "RVOL": f"{float(p_rv):.1f}x" if p_rv and pd.notna(p_rv) else "—",
                                "Del %": f"{float(p_del):.1f}%" if p_del and pd.notna(p_del) else "—",
                                "Setup": p_vcp,
                                "_sym": psym,
                            })

                        peer_cols = [
                            {"name": "Rank", "label": "#", "field": "Rank", "align": "center", "sortable": True},
                            {"name": "Symbol", "label": "Symbol", "field": "Symbol", "align": "left", "sortable": True},
                            {"name": "Company", "label": "Company", "field": "Company", "align": "left"},
                            {"name": "Price", "label": "Price", "field": "Price", "align": "right", "sortable": True},
                            {"name": "Day %", "label": "Day %", "field": "Day %", "align": "right", "sortable": True},
                            {"name": "RS", "label": "RS", "field": "RS", "align": "right", "sortable": True},
                            {"name": "10EMA %", "label": "10 EMA %", "field": "10EMA %", "align": "right", "sortable": True},
                            {"name": "52W High %", "label": "52W High %", "field": "52W High %", "align": "right", "sortable": True},
                            {"name": "RVOL", "label": "RVOL", "field": "RVOL", "align": "right", "sortable": True},
                            {"name": "Del %", "label": "Del %", "field": "Del %", "align": "right", "sortable": True},
                            {"name": "Setup", "label": "Setup", "field": "Setup", "align": "center"},
                        ]
                        
                        tbl = ui.table(
                            columns=peer_cols,
                            rows=p_rows,
                            pagination=12,
                        ).classes("w-full mp-table text-xs")

                        def on_peer_table_click(e):
                            try:
                                args = e.args[1] if len(e.args) > 1 else e.args[0]
                                ps = args.get("_sym") or args.get("Symbol")
                                if ps:
                                    ps = ps.replace("▶", "").strip()
                                    if ps != sym:
                                        dialog.close()
                                        open_stock_360_modal(db_path, ps, copy_text=copy_text)
                            except Exception:
                                pass
                        tbl.on("rowClick", on_peer_table_click)
                        tbl.on("row-click", on_peer_table_click)

                    # Parent Sector Leaders
                    if peer_comp and not peer_comp["sector_leaders_df"].empty:
                        sec_df = peer_comp["sector_leaders_df"]
                        with ui.column().classes("w-full gap-1.5 mt-4 pt-3 border-t border-[var(--mp-border)]"):
                            with ui.row().classes("items-center justify-between"):
                                ui.label(f"🏢 Sector Leaders ({peer_comp['sector']})").classes("text-xs font-bold text-[var(--mp-muted)] uppercase tracking-wider")
                                sec_syms = [str(s) for s in sec_df["symbol"].dropna().tolist()]
                                if copy_text:
                                    sec_tv = ",".join(f"NSE:{s.replace('-', '_')}" for s in sec_syms)
                                    ui.button(f"Copy Sector Leaders ({len(sec_syms)})", on_click=lambda *_, t=sec_tv, s=peer_comp['sector']: copy_text(f"{s} Leaders", t)).props("dense flat size=xs color=primary").classes("text-[10px]")

                            with ui.row().classes("gap-1.5 flex-wrap"):
                                for _, sr in sec_df.iterrows():
                                    ssym = str(sr["symbol"])
                                    srs = sr.get("rs_percentile")
                                    spx = sr.get("close_price")
                                    sday = sr.get("day_pct")
                                    tone = "text-emerald-400" if sday and float(sday) >= 0 else "text-rose-400"
                                    def make_sec_open(target_s=ssym):
                                        def _h():
                                            dialog.close()
                                            open_stock_360_modal(db_path, target_s, copy_text=copy_text)
                                        return _h
                                    with ui.button(on_click=make_sec_open(ssym)).props("dense unelevated size=xs color=dark").classes("border border-slate-800 hover:border-slate-700 px-2 py-1"):
                                        with ui.row().classes("items-center gap-1.5 text-[11px] font-mono"):
                                            ui.label(ssym).classes("font-bold text-sky-400")
                                            ui.label(f"RS {float(srs):.0f}" if srs else "—").classes("text-amber-400")
                                            ui.label(f"{float(sday):+.1f}%" if sday else "—").classes(f"font-semibold {tone}")

                    # Curated Supply Chain & Competitor Links
                    if peer_details:
                        with ui.column().classes("w-full gap-2 mt-4 pt-3 border-t border-[var(--mp-border)]"):
                            ui.label("🔗 Supply Chain & Direct Competitor Links (Curated)").classes("text-xs font-bold text-[var(--mp-muted)]")
                            with ui.row().classes("gap-2 flex-wrap"):
                                for p in peer_details:
                                    p_sym = p["peer_symbol"]
                                    sim_raw = p.get("similarity_type") or "thematic"
                                    sim_label = sim_raw.replace("_", " ").title()
                                    tone_sim = "mp-good" if sim_raw == "direct_competitor" else ("mp-info" if sim_raw == "supply_chain" else "mp-neutral")
                                    def make_curated_open(target_s=p_sym):
                                        def _h():
                                            dialog.close()
                                            open_stock_360_modal(db_path, target_s, copy_text=copy_text)
                                        return _h
                                    with ui.row().classes("items-center gap-1.5 px-2 py-1 rounded bg-[var(--mp-surface-raised)] border border-[var(--mp-border)] cursor-pointer hover:border-slate-600", on_click=make_curated_open(p_sym)):
                                        ui.label(p_sym).classes("font-bold text-xs text-sky-400 font-mono")
                                        ui.label(sim_label).classes(f"mp-badge {tone_sim} text-[9px]")
                                        if p.get("close_price"):
                                            ui.label(f"₹{float(p['close_price']):,.1f}").classes("text-[10px] text-slate-300 font-mono")

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

                    fund_attr = data.get("fund_attribution", [])
                    if fund_attr:
                        with ui.card().classes("w-full p-3 mp-card mb-3 border border-amber-500/40 bg-amber-950/10"):
                            with ui.row().classes("w-full items-center justify-between mb-1"):
                                ui.label("⭐ Institutional Alpha & Track Record").classes("text-xs font-bold text-amber-400")
                                ui.label("Forward performance since fund entry").classes("text-[11px] text-[var(--mp-muted)]")
                            for a in fund_attr[:4]:
                                with ui.row().classes("w-full items-center justify-between text-xs py-1.5 border-b border-[var(--mp-border)]/50 last:border-0"):
                                    with ui.column().classes("gap-0.5"):
                                        with ui.row().classes("items-center gap-1.5"):
                                            ui.label(a["fund_house"]).classes("font-semibold text-[var(--mp-text)]")
                                            if a.get("fund_tier"):
                                                ui.label(a["fund_tier"]).classes("text-[10px] px-1.5 py-0.5 bg-amber-500/20 text-amber-300 rounded font-medium")
                                        wr_str = f"Win Rate: {a['fund_win_rate']:.1f}%" if a.get("fund_win_rate") is not None else ""
                                        b_str = f"Bought {a['deal_date']} @ ₹{a['deal_price']:,.2f} ({a['deal_value_cr']:,.1f} Cr)"
                                        meta_str = f"{b_str} · {wr_str}" if wr_str else b_str
                                        ui.label(meta_str).classes("text-[11px] text-[var(--mp-muted)]")
                                    with ui.column().classes("items-end gap-0.5"):
                                        ret_c = a.get("ret_current", 0)
                                        c_color = "text-emerald-400" if ret_c >= 0 else "text-rose-400"
                                        ui.label(f"CMP: ₹{a.get('cmp', 0):,.2f} ({ret_c:+.1f}%)").classes(f"font-bold {c_color}")
                                        peak_g = a.get("max_runup_pct", 0)
                                        ui.label(f"Peak: +{peak_g:.1f}% in {a.get('days_to_peak', 0)}d").classes("text-[11px] text-emerald-400/80 font-mono")

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
    on_select_symbol: Any = None,
) -> None:
    """Render an embedded, persistent stock inspector panel (Zero-Popup Solution)."""
    db_path = Path(db_path)
    if user_db is None:
        user_db = db_path.parent / "marketpulse_user.duckdb"
    user_db = Path(user_db)

    clean_sym = _clean_symbol_param(symbol)
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
    peer_comp = data.get("peer_comparison") or query_stock_peer_comparison(db_path, clean_sym)
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
                if peer_comp:
                    p_rk = peer_comp["target_rank"]
                    p_tot = peer_comp["total_peers"]
                    p_grp = peer_comp["group_name"]
                    rk_color = "text-amber-400" if p_rk <= 3 else "text-sky-400" if p_rk <= 10 else "text-slate-400"
                    ui.label(f"Industry Rank #{p_rk} of {p_tot} in {p_grp}").classes(f"text-[10px] font-bold {rk_color}")

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
        cdata = query_stock_candlestick_data(db_path, sym, limit=250)
        if cdata and cdata.get("ohlc"):
            if cdata.get("is_darvas_squeeze"):
                with ui.row().classes("w-full items-center justify-between px-2 py-1 rounded bg-emerald-950/50 border border-emerald-500/40 text-emerald-300 text-[11px] font-mono"):
                    ui.label("🎯 DARVAS 10 EMA SQUEEZE").classes("font-bold text-emerald-400")
                    sq_val = f"{cdata['darvas_squeeze_pct']:.1f}%" if cdata.get("darvas_squeeze_pct") is not None else ""
                    cr_val = f"Range: {cdata['candle_range_pct']:.1f}%" if cdata.get("candle_range_pct") is not None else ""
                    ui.label(f"Spread: {sq_val} · {cr_val}").classes("font-semibold")

            dates_len = len(cdata["dates"])
            z_start = max(0, int(((dates_len - 65) / max(1, dates_len)) * 100))

            echart_opt = {
                "backgroundColor": "transparent",
                "animation": False,
                "tooltip": {
                    "trigger": "axis",
                    "axisPointer": {"type": "cross"},
                    "backgroundColor": "rgba(15, 23, 42, 0.95)",
                    "borderColor": "#334155",
                    "borderWidth": 1,
                    "textStyle": {"color": "#f8fafc", "fontSize": 11, "fontFamily": "IBM Plex Mono"},
                    "confine": True,
                },
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
                z65 = max(0, int(((dates_len - 65) / max(1, dates_len)) * 100))
                ui.button("20D", on_click=lambda: inspector_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': z20, 'end': 100})).props("dense outline size=xs").classes("mp-button px-1.5 py-0")
                ui.button("65D", on_click=lambda: inspector_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': z65, 'end': 100})).props("dense outline size=xs").classes("mp-button px-1.5 py-0")
                ui.button("All", on_click=lambda: inspector_chart.run_chart_method('dispatchAction', {'type': 'dataZoom', 'dataZoomIndex': 0, 'start': 0, 'end': 100})).props("dense outline size=xs").classes("mp-button px-1.5 py-0")
        else:
            ui.label("Candlestick data not available.").classes("text-xs text-[var(--mp-muted)] py-4 text-center")

        # 4. Risk & Position Sizing Calculator
        cand_row = cand.iloc[0].to_dict() if isinstance(cand, pd.DataFrame) and not cand.empty else (cand if isinstance(cand, dict) else {})
        trigger_px = float(cand_row.get("trigger_price") or profile.get("high_20d") or close_price * 1.01)
        stop_px = float(cand_row.get("invalidation_price") or profile.get("low_10d") or profile.get("ema_20") or close_price * 0.95)
        res_px = float(cand_row.get("first_resistance") or profile.get("high_52w") or (trigger_px + (trigger_px - stop_px) * 2.0))

        risk_per_share = max(0.05, trigger_px - stop_px)
        risk_pct_val = float(cand_row.get("initial_risk_pct") or ((risk_per_share / trigger_px) * 100.0 if trigger_px > 0 else 5.0))
        rr_val = float(cand_row.get("reward_to_risk") or (((res_px - trigger_px) / risk_per_share) if risk_per_share > 0 else 2.0))

        # Dynamic width for R:R track (eliminating hardcoded 30%/70%)
        total_span = max(0.01, res_px - stop_px)
        risk_span_pct = min(90.0, max(10.0, ((trigger_px - stop_px) / total_span) * 100.0))
        reward_span_pct = 100.0 - risk_span_pct

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
                ui.element("div").classes("h-full bg-rose-500/60").style(f"width: {risk_span_pct:.1f}%")
                ui.element("div").classes("h-full bg-emerald-500/70").style(f"width: {reward_span_pct:.1f}%")

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

        # 6. Themes & Dynamic Industry Peer Comparison
        if thematic_tags or peer_comp:
            with ui.card().classes("w-full mp-card p-2.5 bg-[var(--mp-surface-raised)] border border-[var(--mp-border)]"):
                if thematic_tags:
                    with ui.row().classes("items-center gap-1 flex-wrap mb-2"):
                        ui.label("THEMES:").classes("text-[9px] font-bold text-[var(--mp-muted)]")
                        for t in thematic_tags[:3]:
                            ui.label(f"🏷️ {t}").classes("mp-badge mp-good text-[10px] py-0 px-1.5")

                if peer_comp:
                    target_rk = peer_comp["target_rank"]
                    tot_peers = peer_comp["total_peers"]
                    grp_name = peer_comp["group_name"]
                    better_opts = peer_comp.get("better_options", [])
                    is_leader = peer_comp.get("is_leader", False)

                    # Peer Rank Header & TV Copy
                    with ui.row().classes("w-full items-center justify-between mb-1.5 border-b border-slate-800 pb-1"):
                        with ui.row().classes("items-center gap-1.5"):
                            ui.label("👥 PEER STATUS:").classes("text-[9px] font-bold text-[var(--mp-muted)] uppercase")
                            rk_color = "text-amber-400" if target_rk <= 3 else "text-sky-400" if target_rk <= 10 else "text-slate-400"
                            ui.label(f"Rank #{target_rk} of {tot_peers} in {grp_name}").classes(f"text-[10px] font-bold {rk_color}")

                        all_peer_syms = [str(s) for s in peer_comp["peers_df"]["symbol"].dropna().tolist()]
                        if copy_text and all_peer_syms:
                            tv_copy_str = ",".join(f"NSE:{s.replace('-', '_')}" for s in all_peer_syms)
                            ui.button(
                                f"Copy Peers ({len(all_peer_syms)})",
                                on_click=lambda *_, t=tv_copy_str, g=grp_name: copy_text(f"{g} Peers", t)
                            ).props("dense outline size=xs color=primary").classes("text-[9px] px-1 py-0 font-mono")

                    # Better Options Chips
                    if better_opts:
                        with ui.column().classes("w-full gap-1 mb-2 bg-emerald-950/20 p-2 rounded border border-emerald-500/30"):
                            with ui.row().classes("items-center justify-between"):
                                ui.label("🌟 BETTER OPTIONS IN THIS INDUSTRY:").classes("text-[9px] font-bold text-emerald-400 tracking-wider")
                                ui.label("Click to inspect").classes("text-[9px] text-[var(--mp-muted)]")
                            with ui.row().classes("gap-1 flex-wrap"):
                                for bo in better_opts[:4]:
                                    bo_sym = bo["symbol"]
                                    bo_rs = bo["rs_percentile"]
                                    bo_rs_str = f"RS {bo_rs:.0f}" if bo_rs else ""
                                    bo_btn_txt = f"{bo_sym} ({bo_rs_str})"

                                    def make_chip_click(bsym=bo_sym):
                                        if on_select_symbol:
                                            return lambda *_: on_select_symbol(bsym)
                                        return lambda *_: open_stock_360_modal(db_path, bsym, copy_text=copy_text)

                                    ui.button(bo_btn_txt, on_click=make_chip_click(bo_sym)).props(
                                        "dense unelevated size=xs color=dark"
                                    ).classes("text-[10px] font-mono border border-emerald-500/40 text-emerald-300 hover:border-emerald-400")

                    elif is_leader:
                        with ui.row().classes("w-full items-center gap-1.5 mb-1.5 p-1.5 bg-amber-950/30 border border-amber-500/30 rounded text-amber-300 text-[10px] font-bold"):
                            ui.label(f"🏆 {sym} is the #1 RS Leader in {grp_name}!")

                    # Peer Table Preview (Top 5 + target stock)
                    with ui.column().classes("w-full gap-1"):
                        ui.label("TOP PEERS & RELATIVE STRENGTH:").classes("text-[9px] font-bold text-[var(--mp-muted)]")
                        peers_preview = peer_comp["peers_df"].head(5)
                        if target_rk > 5:
                            target_row = peer_comp["peers_df"][peer_comp["peers_df"]["symbol"] == sym]
                            if not target_row.empty:
                                peers_preview = pd.concat([peers_preview, target_row]).drop_duplicates("symbol")

                        for _, p in peers_preview.iterrows():
                            p_sym = str(p.get("symbol"))
                            p_rs = p.get("rs_percentile")
                            p_cmp = p.get("close_price")
                            p_day = p.get("day_pct")
                            p_rk = p.get("rs_rank")
                            p_10ema = p.get("away_10ema_pct")
                            is_current = p_sym == sym

                            row_bg = "bg-primary/10 border-l-2 border-primary font-bold" if is_current else "hover:bg-slate-800/40"
                            p_tone = "text-emerald-400" if p_day and float(p_day) >= 0 else "text-rose-400"

                            def make_row_click(rsym=p_sym):
                                if rsym == sym:
                                    return None
                                if on_select_symbol:
                                    return lambda *_: on_select_symbol(rsym)
                                return lambda *_: open_stock_360_modal(db_path, rsym, copy_text=copy_text)

                            row_click_cb = make_row_click(p_sym)
                            row_el = ui.row().classes(f"w-full items-center justify-between text-[10px] font-mono px-1 py-0.5 rounded cursor-pointer {row_bg}")
                            if row_click_cb:
                                row_el.on("click", row_click_cb)
                            with row_el:
                                with ui.row().classes("items-center gap-1.5"):
                                    ui.label(f"#{int(p_rk):<2}").classes("text-slate-400 text-[9px]")
                                    ui.label(f"{'▶ ' if is_current else ''}{p_sym}").classes(
                                        "text-primary font-bold" if is_current else "text-sky-300 hover:underline"
                                    )
                                    if p_10ema and pd.notna(p_10ema):
                                        ui.label(f"10E:{float(p_10ema):+.0f}%").classes("text-[9px] text-slate-400")

                                with ui.row().classes("items-center gap-2"):
                                    ui.label(f"RS {float(p_rs):.0f}" if p_rs and pd.notna(p_rs) else "—").classes(
                                        "text-amber-400 font-bold" if p_rs and float(p_rs) >= 80 else "text-slate-400"
                                    )
                                    ui.label(f"₹{float(p_cmp):,.1f}" if p_cmp and pd.notna(p_cmp) else "—").classes("text-slate-300")
                                    ui.label(f"{float(p_day):+.1f}%" if p_day and pd.notna(p_day) else "—").classes(f"{p_tone}")
