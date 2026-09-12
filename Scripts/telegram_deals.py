"""
Send MarketPulse deals lists to Telegram in TradingView paste format.

After DB update:
  NSE:RELIANCE,NSE:TCS,...

Config (environment or project-root .env):
  TELEGRAM_BOT_TOKEN   required
  TELEGRAM_CHAT_ID     required (use --setup to discover)

Usage:
  python Scripts/telegram_deals.py --setup          # find chat_id after you /start the bot
  python Scripts/telegram_deals.py                 # send latest deals TV lists
  python Scripts/telegram_deals.py --dry-run       # print only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd

try:
    from config import DB_PATH, ROOT_DIR
except ModuleNotFoundError:
    from Scripts.config import DB_PATH, ROOT_DIR  # type: ignore

ENV_PATH = ROOT_DIR / ".env"
TELEGRAM_API = "https://api.telegram.org"


def load_dotenv(path: Path = ENV_PATH) -> None:
    """Minimal .env loader (no extra dependency). Does not override existing env."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def tradingview_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("-", "_")


def to_tv_list(symbols: list[str], header: str | None = None) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        if not s or str(s).strip() == "":
            continue
        tok = f"NSE:{tradingview_symbol(s)}"
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    if not out:
        return ""
    syms = ",".join(out)
    if header:
        return f"###{header},{syms}"
    return syms


def telegram_request(token: str, method: str, payload: dict | None = None) -> dict:
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {exc.code}: {err}") from exc
    if not body.get("ok"):
        raise RuntimeError(f"Telegram API error: {body}")
    return body


def send_message(token: str, chat_id: str, text: str) -> None:
    """Send text; split to stay under Telegram 4096 limit."""
    max_len = 4000
    chunks: list[str] = []
    if len(text) <= max_len:
        chunks = [text]
    else:
        # Prefer splitting on commas for TV lists
        parts = text.split(",")
        buf = ""
        for p in parts:
            piece = p if not buf else "," + p
            if len(buf) + len(piece) > max_len:
                if buf:
                    chunks.append(buf)
                buf = p
            else:
                buf += piece
        if buf:
            chunks.append(buf)
    for i, chunk in enumerate(chunks):
        prefix = f"({i + 1}/{len(chunks)})\n" if len(chunks) > 1 else ""
        telegram_request(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": prefix + chunk,
                "disable_web_page_preview": True,
            },
        )


def bot_user_id(token: str) -> int | None:
    """Numeric bot id from token prefix (e.g. 7684702458:AA...)."""
    try:
        return int(token.split(":", 1)[0])
    except (TypeError, ValueError):
        return None


def discover_chat_ids(token: str, exclude_bot_id: int | None = None) -> list[dict]:
    """
    Find chats where a human messaged the bot.
    Never returns the bot's own user id as a destination (that causes 403).
    """
    if exclude_bot_id is None:
        exclude_bot_id = bot_user_id(token)
    body = telegram_request(token, "getUpdates")
    results = []
    for upd in body.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        sender = msg.get("from") or {}
        if not chat:
            continue
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        # Skip bot-to-bot / bot self
        if exclude_bot_id is not None and int(chat_id) == int(exclude_bot_id):
            continue
        if sender.get("is_bot") and chat.get("type") == "private":
            # Ignore pure bot private chats
            if exclude_bot_id is not None and int(sender.get("id") or 0) == int(exclude_bot_id):
                continue
        results.append(
            {
                "chat_id": chat_id,
                "type": chat.get("type"),
                "title": chat.get("title")
                or chat.get("username")
                or chat.get("first_name")
                or sender.get("username")
                or sender.get("first_name"),
                "from_id": sender.get("id"),
                "from_is_bot": bool(sender.get("is_bot")),
                "text": (msg.get("text") or "")[:80],
            }
        )
    # unique by chat_id, prefer private human chats first
    seen = set()
    unique = []
    for r in sorted(
        results,
        key=lambda x: (0 if x.get("type") == "private" and not x.get("from_is_bot") else 1, str(x["chat_id"])),
    ):
        cid = r["chat_id"]
        if cid in seen:
            continue
        seen.add(cid)
        unique.append(r)
    return unique

try:
    from institutional_engine import classify_client
except ModuleNotFoundError:
    from Scripts.institutional_engine import classify_client  # type: ignore


def build_deals_telegram_report(
    lookback_days: int = 20,
    min_mcap_cr: float = 900.0,
    db_path: Path | None = None,
) -> dict:
    """
    Build structured institutional deals report aggregated by:
    1. Count of deal days: 4+ deal days, 3 deal days, 2 deal days
    2. Clientele breakdown: FII, DII, Others, PROP
    3. HIGHEST BUY / SELL turnover leaders
    Each section provides TradingView copy-paste formatted lists.
    """
    target_db = Path(db_path) if db_path is not None else DB_PATH
    if not target_db.exists():
        raise FileNotFoundError(f"Database not found: {target_db}")

    lookback_days = max(1, int(lookback_days))

    with duckdb.connect(str(target_db), read_only=True) as db:
        max_deal = db.execute("SELECT max(trade_date) FROM deals").fetchone()[0]
        if max_deal is None:
            return {"as_of": None, "messages": ["No deals found in database."], "days": [], "tv_strings": {}}

        session_dates = db.execute(
            """
            SELECT DISTINCT trade_date
            FROM deals
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            [lookback_days],
        ).fetchdf()

        if session_dates.empty:
            return {"as_of": str(pd.to_datetime(max_deal).date()), "messages": ["No deal sessions found."], "days": [], "tv_strings": {}}

        dates = [pd.to_datetime(d).date() for d in session_dates["trade_date"].tolist()]
        oldest = min(dates)

        # Check available columns in stocks_master and tables
        master_cols = [c[0] for c in db.execute("DESCRIBE stocks_master").fetchall()]
        band_col = "m.band," if "band" in master_cols else "NULL as band,"
        sec_col = "m.sector, m.industry," if "sector" in master_cols else "NULL as sector, NULL as industry,"

        tables = [t[0] for t in db.execute("SHOW TABLES").fetchall()]
        if "indicators_daily" in tables:
            ind_cols = [c[0] for c in db.execute("DESCRIBE indicators_daily").fetchall()]
            close_col = "i.close_price" if "close_price" in ind_cols else "NULL as close_price"
            ema_col = "i.ema_200" if "ema_200" in ind_cols else "NULL as ema_200"
            away_col = "i.away_52w_high_pct" if "away_52w_high_pct" in ind_cols else "NULL as away_52w_high_pct"
            rs_col = "i.rs_percentile" if "rs_percentile" in ind_cols else "NULL as rs_percentile"
            indicators_join = "LEFT JOIN indicators_daily i ON i.symbol = d.symbol AND i.trade_date = (SELECT max(trade_date) FROM indicators_daily)"
            ind_select = f"{close_col}, {ema_col}, {away_col}, {rs_col}"
        else:
            indicators_join = ""
            ind_select = "NULL as close_price, NULL as ema_200, NULL as away_52w_high_pct, NULL as rs_percentile"

        sql = f"""
        SELECT d.trade_date, d.symbol, d.client_name, d.side, d.deal_value_cr,
               m.market_cap_cr, {sec_col} {band_col}
               {ind_select}
        FROM deals d
        LEFT JOIN stocks_master m USING(symbol)
        {indicators_join}
        WHERE d.trade_date >= ?
        """
        df = db.execute(sql, [oldest]).fetchdf()

    as_of = str(dates[0]) if dates else str(pd.to_datetime(max_deal).date())
    if df.empty:
        return {"as_of": as_of, "messages": [f"No deals found for window ending {as_of}."], "days": [], "tv_strings": {}}

    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["deal_value_cr"] = pd.to_numeric(df["deal_value_cr"], errors="coerce").fillna(0.0)
    df["market_cap_cr"] = pd.to_numeric(df["market_cap_cr"], errors="coerce")
    if "band" in df.columns:
        df["band"] = pd.to_numeric(df["band"], errors="coerce")
    else:
        df["band"] = float("nan")
    if "close_price" in df.columns:
        df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    else:
        df["close_price"] = float("nan")
    if "ema_200" in df.columns:
        df["ema_200"] = pd.to_numeric(df["ema_200"], errors="coerce")
    else:
        df["ema_200"] = float("nan")
    if "away_52w_high_pct" in df.columns:
        df["away_52w_high_pct"] = pd.to_numeric(df["away_52w_high_pct"], errors="coerce")
    else:
        df["away_52w_high_pct"] = float("nan")
    if "rs_percentile" in df.columns:
        df["rs_percentile"] = pd.to_numeric(df["rs_percentile"], errors="coerce")
    else:
        df["rs_percentile"] = float("nan")

    # Hard ban on rights entitlements (-RE / _RE)
    df = df[~df["symbol"].astype(str).str.upper().str.endswith(("-RE", "_RE"))].copy()
    if df.empty:
        return {"as_of": as_of, "messages": ["No valid deals found in window."], "days": [], "tv_strings": {}}

    # Hard gate: strictly exclude any stock below min_mcap_cr (default 900 Cr) or with missing/NaN market cap
    min_mcap_val = float(min_mcap_cr if min_mcap_cr is not None else 900.0)
    df = df[df["market_cap_cr"].notna() & (df["market_cap_cr"] >= min_mcap_val)].copy()
    if df.empty:
        return {"as_of": as_of, "messages": [f"No valid deals found in window with market cap >= ₹{min_mcap_val:,.0f} Cr."], "days": [], "tv_strings": {}}

    # Classify client
    df["client_info"] = df["client_name"].map(classify_client)
    df["clientele"] = df["client_info"].map(lambda x: x.get("clientele") or "OTHER")
    df["is_prop"] = df["client_info"].map(lambda x: bool(x.get("is_prop")))

    # Standardize clientele bucket names: FII, DII, PROP, Others
    def standardize_cat(row):
        if row["is_prop"] or row["clientele"] == "PROP":
            return "PROP"
        if row["clientele"] == "FII":
            return "FII"
        if row["clientele"] == "DII":
            return "DII"
        return "Others"

    df["category"] = df.apply(standardize_cat, axis=1)

    # Aggregate by symbol across the window
    sym_meta = df.groupby("symbol").agg(
        deal_days=("trade_date", "nunique"),
        categories=("category", lambda c: set(c)),
        market_cap_cr=("market_cap_cr", "first"),
        sector=("sector", "first") if "sector" in df.columns else ("close_price", lambda _: None),
        industry=("industry", "first") if "industry" in df.columns else ("close_price", lambda _: None),
        band=("band", "first"),
        close_price=("close_price", "first"),
        ema_200=("ema_200", "first"),
        away_52w_high_pct=("away_52w_high_pct", "first") if "away_52w_high_pct" in df.columns else ("close_price", lambda _: None),
        rs_percentile=("rs_percentile", "first") if "rs_percentile" in df.columns else ("close_price", lambda _: None),
        buy_cr=("deal_value_cr", lambda v: v[df.loc[v.index, "side"] == "BUY"].sum()),
        sell_cr=("deal_value_cr", lambda v: v[df.loc[v.index, "side"] == "SELL"].sum()),
        total_cr=("deal_value_cr", "sum"),
    ).reset_index()
    sym_meta["net_cr"] = sym_meta["buy_cr"] - sym_meta["sell_cr"]

    # -------------------------------------------------------------
    # QUALITY & QUARANTINE CLASSIFICATION
    # -------------------------------------------------------------
    # 1. Circuit filter: Locked in tight <=5% Circuit Bands (illiquid/collar risk)
    sym_meta["is_quarantined_band"] = sym_meta["band"].map(
        lambda b: pd.notna(b) and float(b) <= 5.0
    )

    # 2. Pure Prop Desk filter: ALL recorded deals in the window were PROP desks (zero external participation)
    sym_meta["is_only_prop"] = sym_meta["categories"].map(lambda cats: cats == {"PROP"})

    # 3. Trend classification (for informative labeling & optional UI filtering; NOT a disqualifier)
    sym_meta["is_above_200"] = sym_meta.apply(
        lambda r: bool(pd.notna(r["close_price"]) and pd.notna(r["ema_200"]) and float(r["close_price"]) >= float(r["ema_200"])),
        axis=1,
    )
    sym_meta["trend_stage"] = sym_meta["is_above_200"].map(
        lambda x: "🟢 >200 EMA" if x else "🟡 Base / Turnaround"
    )

    # Tier 3B: Quarantined streams (Locked in <=5% Circuit Bands)
    below_1000cr_df = pd.DataFrame()  # Stocks below min_mcap_cr are completely excluded
    quarantined_df = sym_meta[sym_meta["is_quarantined_band"]].sort_values("buy_cr", ascending=False).copy()
    below_200_df = sym_meta[(~sym_meta["is_quarantined_band"]) & (~sym_meta["is_above_200"])].sort_values("buy_cr", ascending=False).copy()

    # Tier 3A: Prop HFT Churn (100% Prop Desk scalp activity, not quarantined)
    prop_only_df = sym_meta[(~sym_meta["is_quarantined_band"]) & sym_meta["is_only_prop"]].sort_values("buy_cr", ascending=False).copy()

    # Pure Institutional Universe: Not quarantined (band > 5%) and not pure prop churn
    quality_df = sym_meta[
        (~sym_meta["is_quarantined_band"])
        & (~sym_meta["is_only_prop"])
    ].copy()

    # Deals subset for quality symbols
    quality_syms = set(quality_df["symbol"])
    quality_deals = df[df["symbol"].isin(quality_syms)].copy()

    # -------------------------------------------------------------
    # 3-TIER ACTION-FIRST CLASSIFICATION (MUTUALLY EXCLUSIVE)
    # -------------------------------------------------------------
    # Non-prop stocks with BUY side interest
    quality_buys = quality_df[quality_df["buy_cr"] > 0].copy()

    # Tier 1: Conviction Accumulation — Multi-day persistence (2+ Deal Days) OR Substantial Buying (buy_cr >= 25 Cr or net_cr >= 20 Cr)
    conviction_df = quality_buys[
        (quality_buys["deal_days"] >= 2)
        | (quality_buys["buy_cr"] >= 25.0)
        | (quality_buys["net_cr"] >= 20.0)
    ].sort_values(["deal_days", "buy_cr", "net_cr"], ascending=[False, False, False]).copy()

    conviction_syms = set(conviction_df["symbol"])

    # Tier 2: Fresh Whale Radar — Day-1 institutional entries / emerging accumulation
    fresh_radar_df = quality_buys[
        ~quality_buys["symbol"].isin(conviction_syms)
    ].sort_values(["buy_cr", "net_cr"], ascending=[False, False]).copy()

    # Pure Distribution: Non-prop stocks with zero buying and active selling
    distribution_df = quality_df[
        (quality_df["buy_cr"] == 0) & (quality_df["sell_cr"] > 0)
    ].sort_values("sell_cr", ascending=False).copy()

    # Retain backward-compatible persistence slices
    four_plus = quality_df[quality_df["deal_days"] >= 4].sort_values(
        ["deal_days", "net_cr", "buy_cr"], ascending=[False, False, False]
    )
    three = quality_df[quality_df["deal_days"] == 3].sort_values(
        ["net_cr", "buy_cr"], ascending=[False, False]
    )
    two = quality_df[quality_df["deal_days"] == 2].sort_values(
        ["net_cr", "buy_cr"], ascending=[False, False]
    )

    # Retain backward-compatible clientele slices
    clientele_buys = {}
    for cat in ["FII", "DII", "Others"]:
        cat_deals = quality_deals[quality_deals["category"] == cat]
        buys = (
            cat_deals[cat_deals["side"] == "BUY"]
            .groupby("symbol")["deal_value_cr"]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
        )
        clientele_buys[cat] = buys

    prop_buys = prop_only_df[["symbol", "buy_cr"]].rename(columns={"buy_cr": "deal_value_cr"})
    clientele_buys["PROP"] = prop_buys

    # Quality turnover leaders
    top_buys = (
        quality_deals[quality_deals["side"] == "BUY"]
        .groupby("symbol")["deal_value_cr"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )
    top_sells = (
        quality_deals[quality_deals["side"] == "SELL"]
        .groupby("symbol")["deal_value_cr"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )

    # -------------------------------------------------------------
    # TRADINGVIEW LISTS
    # -------------------------------------------------------------
    sec_conviction = to_tv_list(conviction_df["symbol"].tolist(), header="💎 Conviction Accumulation") if not conviction_df.empty else ""
    sec_fresh = to_tv_list(fresh_radar_df["symbol"].tolist(), header="⚡ Fresh Whale Radar") if not fresh_radar_df.empty else ""
    sec_prop = to_tv_list(prop_only_df["symbol"].tolist(), header="🎯 Prop HFT Churn") if not prop_only_df.empty else ""
    sec_quarantined = to_tv_list(quarantined_df["symbol"].tolist(), header="📉 Quarantined (5% Band)") if not quarantined_df.empty else ""
    sec_below_200 = to_tv_list(below_200_df["symbol"].tolist(), header="🟡 Turnaround (<200 EMA)") if not below_200_df.empty else ""
    sec_top_sells = to_tv_list(top_sells["symbol"].tolist(), header="🔴 Institutional Exits") if not top_sells.empty else ""

    # Slices for above 200 EMA and base/turnaround
    above_200_syms = (
        conviction_df[conviction_df["is_above_200"]]["symbol"].tolist()
        + fresh_radar_df[fresh_radar_df["is_above_200"]]["symbol"].tolist()
    )
    turnaround_syms = (
        conviction_df[~conviction_df["is_above_200"]]["symbol"].tolist()
        + fresh_radar_df[~fresh_radar_df["is_above_200"]]["symbol"].tolist()
    )
    sec_above_200 = to_tv_list(above_200_syms, header="🟢 Above 200 EMA") if above_200_syms else ""
    sec_turnaround = to_tv_list(turnaround_syms, header="🟡 Base/Turnaround (<200 EMA)") if turnaround_syms else ""

    # Master TV string: Tier 1 + Tier 2 combined cleanly (Full Institutional Radar)
    master_tv = ",".join([s for s in [sec_conviction, sec_fresh] if s])
    all_tiers_tv = ",".join([s for s in [sec_conviction, sec_fresh, sec_prop, sec_quarantined] if s])

    # Backward compatibility TV strings
    sec_4plus = to_tv_list(four_plus["symbol"].tolist(), header="4+ Deal Days") if not four_plus.empty else ""
    sec_3days = to_tv_list(three["symbol"].tolist(), header="3 Deal Days") if not three.empty else ""
    sec_2days = to_tv_list(two["symbol"].tolist(), header="2 Deal Days") if not two.empty else ""
    sec_fii = to_tv_list(clientele_buys.get("FII", pd.DataFrame())["symbol"].tolist(), header="FII") if not clientele_buys.get("FII", pd.DataFrame()).empty else ""
    sec_dii = to_tv_list(clientele_buys.get("DII", pd.DataFrame())["symbol"].tolist(), header="DII") if not clientele_buys.get("DII", pd.DataFrame()).empty else ""
    sec_others = to_tv_list(clientele_buys.get("Others", pd.DataFrame())["symbol"].tolist(), header="Others") if not clientele_buys.get("Others", pd.DataFrame()).empty else ""
    sec_top_buys = to_tv_list(top_buys["symbol"].tolist(), header="Highest Buys") if not top_buys.empty else ""
    sec_below_1000cr = ""

    persistence_buckets = ",".join([s for s in [sec_4plus, sec_3days, sec_2days] if s])
    clientele_buckets = ",".join([s for s in [sec_fii, sec_dii, sec_others, sec_prop] if s])
    quality_buckets = master_tv if master_tv else ",".join([s for s in [sec_4plus, sec_3days, sec_2days, sec_fii, sec_dii, sec_top_buys] if s])
    all_deal_buckets = all_tiers_tv if all_tiers_tv else ",".join([s for s in [sec_4plus, sec_3days, sec_2days, sec_fii, sec_dii, sec_top_buys, sec_prop, sec_below_200] if s])

    # -------------------------------------------------------------
    # FORMAT TELEGRAM MESSAGES (CONSOLIDATED 2 HIGH-IMPACT MESSAGES)
    # -------------------------------------------------------------
    messages = []

    # Calculate Institutional Net Flow across the window
    inst_deals = quality_deals[quality_deals["category"].isin(["FII", "DII"])]
    inst_buy_cr = float(inst_deals[inst_deals["side"] == "BUY"]["deal_value_cr"].sum()) if not inst_deals.empty else 0.0
    inst_sell_cr = float(inst_deals[inst_deals["side"] == "SELL"]["deal_value_cr"].sum()) if not inst_deals.empty else 0.0
    inst_net_cr = inst_buy_cr - inst_sell_cr
    inst_sign = "+" if inst_net_cr >= 0 else "-"

    # MESSAGE 1: 🎯 SWING DEALS: CONVICTION & RADAR (With Master TV Paste)
    msg1_lines = [
        "🎯 *MARKETPULSE DEALS — SWING RADAR*",
        f"🗓 *As of:* `{as_of}` | *Window:* Last {len(dates)} Deal Sessions",
        f"🏛 *Total Inst Flow:* `{inst_sign}₹{abs(inst_net_cr):,.1f} Cr` (Buy: ₹{inst_buy_cr:,.1f} Cr | Sell: ₹{inst_sell_cr:,.1f} Cr)",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"💎 *TIER 1: CONVICTION ACCUMULATION* ({len(conviction_df)} stocks)",
        "_Multi-day persistence (2+ days) or Whale Inflows (>=₹25Cr)_",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]
    if conviction_df.empty:
        msg1_lines.append("• No conviction accumulation deals recorded in window.")
    else:
        for _, r in conviction_df.head(8).iterrows():
            tags = "/".join(sorted(list(r["categories"])))
            sign = "+" if r["net_cr"] >= -0.05 else "-"
            net_val = abs(r["net_cr"])
            if net_val < 0.05:
                net_val = 0.0
                sign = "+"
            close_str = f"CMP ₹{r['close_price']:,.0f}" if pd.notna(r["close_price"]) else ""
            if pd.notna(r["away_52w_high_pct"]):
                away_val = float(r["away_52w_high_pct"])
                if abs(away_val) < 0.05:
                    away_val = 0.0
                away_str = f"{away_val:+.1f}% 52W"
            else:
                away_str = ""
            metrics = " · ".join([s for s in [close_str, away_str] if s])
            m_bracket = f" | {metrics}" if metrics else ""
            msg1_lines.append(f"• `{r['symbol']}`: {r['deal_days']}d | Net ₹{net_val:,.1f}Cr ({sign}) [{tags}]{m_bracket}")

    msg1_lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"⚡ *TIER 2: FRESH WHALE RADAR* ({len(fresh_radar_df)} stocks)",
        "_Day-1 institutional entries / emerging accumulation_",
        "━━━━━━━━━━━━━━━━━━━━━",
    ])
    if fresh_radar_df.empty:
        msg1_lines.append("• No fresh institutional entries recorded.")
    else:
        for _, r in fresh_radar_df.head(6).iterrows():
            tags = "/".join(sorted(list(r["categories"])))
            sign = "+" if r["net_cr"] >= -0.05 else "-"
            net_val = abs(r["net_cr"])
            if net_val < 0.05:
                net_val = 0.0
                sign = "+"
            close_str = f"CMP ₹{r['close_price']:,.0f}" if pd.notna(r["close_price"]) else ""
            if pd.notna(r["away_52w_high_pct"]):
                away_val = float(r["away_52w_high_pct"])
                if abs(away_val) < 0.05:
                    away_val = 0.0
                away_str = f"{away_val:+.1f}% 52W"
            else:
                away_str = ""
            metrics = " · ".join([s for s in [close_str, away_str] if s])
            m_bracket = f" | {metrics}" if metrics else ""
            msg1_lines.append(f"• `{r['symbol']}`: 1d | Net ₹{net_val:,.1f}Cr ({sign}) [{tags}]{m_bracket}")

    if master_tv:
        msg1_lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "📋 *TRADINGVIEW MASTER PASTE (Tier 1 & 2):*",
            f"`{master_tv}`",
        ])
    messages.append("\n".join(msg1_lines))

    # MESSAGE 2: 🛡️ DEALS: DISTRIBUTION, PROP CHURN & QUARANTINE
    msg2_lines = [
        "🛡 *MARKETPULSE DEALS — RISK & CONTEXT*",
        f"🗓 *As of:* `{as_of}` | *Window:* Last {len(dates)} Deal Sessions",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"🔴 *INSTITUTIONAL EXITS / DISTRIBUTION* ({len(top_sells)} stocks)",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]
    if top_sells.empty:
        msg2_lines.append("• No significant institutional distribution recorded.")
    else:
        for idx, (_, r) in enumerate(top_sells.head(6).iterrows(), 1):
            msg2_lines.append(f"{idx}. `{r['symbol']}` — ₹{r['deal_value_cr']:,.1f} Cr sell")

    msg2_lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"⚡ *TIER 3A: PROP DESK CHURN (HFT Only)* ({len(prop_only_df)} stocks)",
        "_Intraday scalp turnover — NO institutional FII/DII sponsorship_",
        "━━━━━━━━━━━━━━━━━━━━━",
    ])
    if prop_only_df.empty:
        msg2_lines.append("• No prop-only churn recorded.")
    else:
        for _, r in prop_only_df.head(6).iterrows():
            msg2_lines.append(f"• `{r['symbol']}` — ₹{r['buy_cr']:,.1f} Cr buy")
        if sec_prop:
            msg2_lines.extend(["", "📋 *TV Paste (Prop HFT):*", f"`{sec_prop}`"])

    msg2_lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"📉 *TIER 3B: QUARANTINED (5% Band)* ({len(quarantined_df)} stocks)",
        "_Locked in tight <=5% Circuit Bands_",
        "━━━━━━━━━━━━━━━━━━━━━",
    ])
    if quarantined_df.empty:
        msg2_lines.append("• No stocks quarantined in 5% circuit bands.")
    else:
        for _, r in quarantined_df.head(6).iterrows():
            msg2_lines.append(f"• `{r['symbol']}` — ₹{r['buy_cr']:,.1f} Cr buy")
        if sec_quarantined:
            msg2_lines.extend(["", "📋 *TV Paste (Quarantined):*", f"`{sec_quarantined}`"])

    messages.append("\n".join(msg2_lines))

    # Backwards compatibility day_rows
    day_rows = []
    for d in dates[:10]:
        sub = quality_deals[(quality_deals["trade_date"] == d) & (quality_deals["side"] == "BUY")]
        sub_syms = sub.sort_values("deal_value_cr", ascending=False)["symbol"].dropna().unique().tolist()
        day_rows.append({"date": str(d), "tv": to_tv_list(sub_syms), "count": len(sub_syms), "symbols": sub_syms})

    tv_strings = {
        "master_tv": master_tv,
        "conviction_tv": sec_conviction,
        "fresh_radar_tv": sec_fresh,
        "prop_tv": sec_prop,
        "quarantined_tv": sec_quarantined,
        "above_200_tv": sec_above_200,
        "turnaround_tv": sec_turnaround,
        "all_tiers_tv": all_tiers_tv,
        "quality_buckets": quality_buckets,
        "persistence_buckets": persistence_buckets,
        "clientele_buckets": clientele_buckets,
        "all_deal_buckets": all_deal_buckets,
        "all_buys": to_tv_list(top_buys["symbol"].tolist()) if not top_buys.empty else "",
        "persistence_all": to_tv_list(
            [s for s in (four_plus["symbol"].tolist() + three["symbol"].tolist() + two["symbol"].tolist()) if s]
        ),
        "inst_buys": to_tv_list(
            (clientele_buys.get("FII", pd.DataFrame())["symbol"].tolist() if not clientele_buys.get("FII", pd.DataFrame()).empty else [])
            + (clientele_buys.get("DII", pd.DataFrame())["symbol"].tolist() if not clientele_buys.get("DII", pd.DataFrame()).empty else []),
            header="Institutional Buys",
        ),
        "four_plus": sec_4plus,
        "three": sec_3days,
        "two": sec_2days,
        "fii": sec_fii,
        "dii": sec_dii,
        "others": sec_others,
        "prop": sec_prop,
        "top_buys": sec_top_buys,
        "top_sells": sec_top_sells,
        "below_200ema": sec_turnaround,
        "below_1000cr": sec_below_1000cr,
    }

    return {
        "as_of": as_of,
        "messages": messages,
        "days": day_rows,
        "buy_count": len(top_buys),
        "buy_tv": day_rows[0]["tv"] if day_rows else "",
        "tv_strings": tv_strings,
        "tiers": {
            "conviction": conviction_df,
            "fresh_radar": fresh_radar_df,
            "prop_only": prop_only_df,
            "quarantined": quarantined_df,
            "distribution": distribution_df if not distribution_df.empty else top_sells,
        },
        "persistence": {
            "four_plus": four_plus,
            "three": three,
            "two": two,
        },
        "clientele": clientele_buys,
        "highest": {
            "buys": top_buys,
            "sells": top_sells,
        },
        "filtered": {
            "below_200ema": below_200_df,
            "below_1000cr": below_1000cr_df,
            "prop_only": prop_only_df,
        },
    }


def query_deals_tv_lists(lookback_days: int = 20, min_mcap_cr: float = 900.0, db_path: Path | None = None) -> dict:
    """Retained for backward compatibility with external callers."""
    return build_deals_telegram_report(lookback_days=lookback_days, min_mcap_cr=min_mcap_cr, db_path=db_path)


def notify_deals(
    *,
    dry_run: bool = False,
    lookback_days: int = 20,
    min_mcap_cr: float = 900.0,
    token: str | None = None,
    chat_id: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """
    Send structured Telegram report categorized by:
    - 4+ deal days, 3 deal days, 2 deal days
    - FII, DII, Others, PROP
    - HIGHEST BUY / SELL turnover
    Each section includes a TradingView paste list.
    """
    load_dotenv()
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    payload = build_deals_telegram_report(lookback_days=lookback_days, min_mcap_cr=min_mcap_cr, db_path=db_path)
    messages = payload.get("messages") or []

    if dry_run:
        for m in messages:
            print("\n================ TELEGRAM MESSAGE ================")
            print(m)
        payload["sent"] = False
        payload["dry_run"] = True
        payload["message_count"] = len(messages)
        return payload

    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN missing. Set it in project .env or environment."
        )
    if not chat_id:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID missing. Run: python Scripts/telegram_deals.py --setup\n"
            "Then message your bot on Telegram (/start) and re-run --setup."
        )

    bid = bot_user_id(token)
    try:
        if bid is not None and int(chat_id) == int(bid):
            raise RuntimeError(
                f"TELEGRAM_CHAT_ID={chat_id} is the BOT's own id, not your user chat.\n"
                "Open Telegram, message @Sidvinsbot with /start, then run:\n"
                "  python Scripts/telegram_deals.py --setup\n"
                "Your personal chat_id should look different from the bot id."
            )
    except ValueError:
        pass

    for m in messages:
        send_message(token, chat_id, m)
    print(f"Telegram: sent {len(messages)} deal reports (as_of {payload.get('as_of')}, lookback {lookback_days})")
    payload["sent"] = True
    payload["dry_run"] = False
    payload["message_count"] = len(messages)
    return payload


def cmd_setup(token: str | None = None) -> int:
    load_dotenv()
    token = (token or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
    if not token:
        print("Set TELEGRAM_BOT_TOKEN in .env first.", file=sys.stderr)
        return 1
    me = telegram_request(token, "getMe")
    bot = me.get("result", {})
    bot_id = bot.get("id")
    print(f"Bot OK: @{bot.get('username')} ({bot.get('first_name')}) id={bot_id}")
    print()
    print("1) Open Telegram as YOUR account (not the bot).")
    print(f"2) Search @{bot.get('username')} and send /start (any text works).")
    print("3) Re-run --setup if the list below is empty.")
    print()
    print("IMPORTANT: chat_id must be YOUR user id, never the bot id.")
    print()
    chats = discover_chat_ids(token, exclude_bot_id=bot_id)
    if not chats:
        print("No human chats yet. Message the bot from your phone/desktop, then run --setup again.")
        return 2
    print("Human chats seen:")
    for c in chats:
        print(
            f"  chat_id={c['chat_id']}  type={c['type']}  name={c['title']}  "
            f"from_id={c.get('from_id')}  last={c['text']!r}"
        )
    preferred = next(
        (c for c in chats if c["type"] == "private" and not c.get("from_is_bot")),
        next((c for c in chats if c["type"] == "private"), chats[0]),
    )
    cid = str(preferred["chat_id"])
    if bot_id is not None and str(cid) == str(bot_id):
        print("ERROR: resolved chat_id equals bot id — aborting write.", file=sys.stderr)
        return 3
    print()
    print(f"Suggested TELEGRAM_CHAT_ID={cid}  (your chat, not the bot)")
    # Offer to write into .env — single clean file (dedupe keys)
    existing: dict[str, str] = {}
    other_lines: list[str] = []
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                other_lines.append(line)
                continue
            if "=" in s:
                k, _, v = s.partition("=")
                existing[k.strip()] = v.strip()
            else:
                other_lines.append(line)
    existing["TELEGRAM_BOT_TOKEN"] = token
    existing["TELEGRAM_CHAT_ID"] = cid
    out = [
        "# MarketPulse secrets — DO NOT COMMIT",
        f"TELEGRAM_BOT_TOKEN={existing['TELEGRAM_BOT_TOKEN']}",
        f"TELEGRAM_CHAT_ID={existing['TELEGRAM_CHAT_ID']}",
    ]
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote {ENV_PATH} (gitignored).")
    # Smoke-send a short confirmation
    try:
        send_message(token, cid, "MarketPulse connected. You will get deals TV lists here after DB updates.")
        print("Sent test message — check Telegram.")
    except Exception as exc:
        print(f"Test send failed: {exc}", file=sys.stderr)
        return 4
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram deals notify (TradingView paste format).")
    parser.add_argument("--setup", action="store_true", help="Discover chat_id after you /start the bot.")
    parser.add_argument("--dry-run", action="store_true", help="Print lists without sending.")
    parser.add_argument(
        "--lookback",
        type=int,
        default=20,
        help="Number of recent deal sessions (default 20, newest first).",
    )
    parser.add_argument("--min-mcap", type=float, default=900.0, help="Min market cap Cr (default 900).")
    args = parser.parse_args()
    try:
        if args.setup:
            return cmd_setup()
        notify_deals(dry_run=args.dry_run, lookback_days=max(1, args.lookback), min_mcap_cr=args.min_mcap)
        return 0
    except Exception as exc:
        print(f"telegram_deals failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
