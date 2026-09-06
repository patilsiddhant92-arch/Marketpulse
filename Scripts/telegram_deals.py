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
    min_mcap_cr: float = 1000.0,
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

        tables = [t[0] for t in db.execute("SHOW TABLES").fetchall()]
        if "indicators_daily" in tables:
            indicators_join = "LEFT JOIN indicators_daily i ON i.symbol = d.symbol AND i.trade_date = (SELECT max(trade_date) FROM indicators_daily)"
            ind_select = "i.close_price, i.ema_200"
        else:
            indicators_join = ""
            ind_select = "NULL as close_price, NULL as ema_200"

        sql = f"""
        SELECT d.trade_date, d.symbol, d.client_name, d.side, d.deal_value_cr,
               m.market_cap_cr, {band_col}
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

    # Hard ban on rights entitlements (-RE / _RE)
    df = df[~df["symbol"].astype(str).str.upper().str.endswith(("-RE", "_RE"))].copy()
    if df.empty:
        return {"as_of": as_of, "messages": ["No valid deals found in window."], "days": [], "tv_strings": {}}

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
        band=("band", "first"),
        close_price=("close_price", "first"),
        ema_200=("ema_200", "first"),
        buy_cr=("deal_value_cr", lambda v: v[df.loc[v.index, "side"] == "BUY"].sum()),
        sell_cr=("deal_value_cr", lambda v: v[df.loc[v.index, "side"] == "SELL"].sum()),
        total_cr=("deal_value_cr", "sum"),
    ).reset_index()
    sym_meta["net_cr"] = sym_meta["buy_cr"] - sym_meta["sell_cr"]

    # -------------------------------------------------------------
    # QUALITY & QUARANTINE CLASSIFICATION
    # -------------------------------------------------------------
    # 1. Micro-caps: Market Cap < 1000 Cr
    sym_meta["is_below_1000cr"] = sym_meta["market_cap_cr"].map(
        lambda m: pd.notna(m) and float(m) < float(min_mcap_cr)
    )

    # 2. Trend & Circuit filter: Below 200 EMA or in 5% Band
    sym_meta["is_below_200_or_band5"] = sym_meta.apply(
        lambda r: (pd.notna(r["band"]) and float(r["band"]) <= 5.0)
        or (pd.notna(r["close_price"]) and pd.notna(r["ema_200"]) and float(r["close_price"]) < float(r["ema_200"])),
        axis=1,
    )

    # 3. Only in PROP filter: all recorded deals were PROP
    sym_meta["is_only_prop"] = sym_meta["categories"].map(lambda cats: cats == {"PROP"})

    # Quarantined streams
    below_1000cr_df = sym_meta[sym_meta["is_below_1000cr"]].sort_values("buy_cr", ascending=False)
    below_200_df = sym_meta[(~sym_meta["is_below_1000cr"]) & sym_meta["is_below_200_or_band5"]].sort_values("buy_cr", ascending=False)
    prop_only_df = sym_meta[(~sym_meta["is_below_1000cr"]) & (~sym_meta["is_below_200_or_band5"]) & sym_meta["is_only_prop"]].sort_values("buy_cr", ascending=False)

    # Pure Quality Universe (Market Cap >= 1000 Cr, Above 200 EMA, Band > 5%, Real Institutional Backing)
    quality_df = sym_meta[
        (~sym_meta["is_below_1000cr"])
        & (~sym_meta["is_below_200_or_band5"])
        & (~sym_meta["is_only_prop"])
    ].copy()

    # Deals subset for quality symbols
    quality_syms = set(quality_df["symbol"])
    quality_deals = df[df["symbol"].isin(quality_syms)].copy()

    # -------------------------------------------------------------
    # 1. GROUP BY DEAL DAYS COUNT (PERSISTENCE) — QUALITY ONLY
    # -------------------------------------------------------------
    four_plus = quality_df[quality_df["deal_days"] >= 4].sort_values(
        ["deal_days", "net_cr", "buy_cr"], ascending=[False, False, False]
    )
    three = quality_df[quality_df["deal_days"] == 3].sort_values(
        ["net_cr", "buy_cr"], ascending=[False, False]
    )
    two = quality_df[quality_df["deal_days"] == 2].sort_values(
        ["net_cr", "buy_cr"], ascending=[False, False]
    )

    # -------------------------------------------------------------
    # 2. CLIENTELE BREAKDOWN — QUALITY (FII, DII, Others) + PROP ONLY
    # -------------------------------------------------------------
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

    # PROP header receives ONLY the stocks that were only in prop!
    prop_buys = prop_only_df[["symbol", "buy_cr"]].rename(columns={"buy_cr": "deal_value_cr"})
    clientele_buys["PROP"] = prop_buys

    # -------------------------------------------------------------
    # 3. HIGHEST BUY / SELL (QUALITY TURNOVER LEADERS)
    # -------------------------------------------------------------
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
    # 4. FORMAT TELEGRAM MESSAGES
    # -------------------------------------------------------------
    messages = []

    # MESSAGE 1: Deal Persistence by Count (Quality Only)
    msg1_lines = [
        "📊 *MARKETPULSE DEALS — PERSISTENCE REPORT*",
        f"🗓 *As of:* `{as_of}` | *Window:* Last {len(dates)} Deal Sessions",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "🔥 *DEAL PERSISTENCE BY COUNT (QUALITY STOCKS)*",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"💎 *4+ DEAL DAYS* ({len(four_plus)} stocks · Heavy Accumulation)",
    ]
    for _, r in four_plus.head(8).iterrows():
        tags = "/".join(sorted(list(r["categories"])))
        sign = "+" if r["net_cr"] >= 0 else "-"
        msg1_lines.append(f"• `{r['symbol']}`: {r['deal_days']}d | Net ₹{abs(r['net_cr']):,.1f}Cr ({sign}) [{tags}]")
    if not four_plus.empty:
        msg1_lines.extend(["", "📋 *TV Paste (4+ Days):*", f"`{to_tv_list(four_plus['symbol'].tolist(), header='4+ Deal Days')}`", ""])

    msg1_lines.append(f"⚡ *3 DEAL DAYS* ({len(three)} stocks)")
    for _, r in three.head(6).iterrows():
        tags = "/".join(sorted(list(r["categories"])))
        sign = "+" if r["net_cr"] >= 0 else "-"
        msg1_lines.append(f"• `{r['symbol']}`: Net ₹{abs(r['net_cr']):,.1f}Cr ({sign}) [{tags}]")
    if not three.empty:
        msg1_lines.extend(["", "📋 *TV Paste (3 Days):*", f"`{to_tv_list(three['symbol'].tolist(), header='3 Deal Days')}`", ""])

    msg1_lines.append(f"🎯 *2 DEAL DAYS* ({len(two)} stocks)")
    for _, r in two.head(6).iterrows():
        tags = "/".join(sorted(list(r["categories"])))
        sign = "+" if r["net_cr"] >= 0 else "-"
        msg1_lines.append(f"• `{r['symbol']}`: Net ₹{abs(r['net_cr']):,.1f}Cr ({sign}) [{tags}]")
    if not two.empty:
        msg1_lines.extend(["", "📋 *TV Paste (2 Days):*", f"`{to_tv_list(two['symbol'].tolist(), header='2 Deal Days')}`"])

    messages.append("\n".join(msg1_lines))

    # MESSAGE 2: Clientele Breakdown
    msg2_lines = [
        "🏛 *CLIENTELE FLOW BREAKDOWN*",
        f"🗓 *As of:* `{as_of}` | *Window:* Last {len(dates)} Deal Sessions",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "🌍 *FII (Foreign Institutional Investors)*",
    ]
    fii_df = clientele_buys.get("FII", pd.DataFrame())
    if fii_df.empty:
        msg2_lines.append("• No FII buy deals recorded.")
    else:
        for _, r in fii_df.head(6).iterrows():
            msg2_lines.append(f"• `{r['symbol']}` — ₹{r['deal_value_cr']:,.1f} Cr")
        msg2_lines.extend(["", "📋 *TV Paste (FII):*", f"`{to_tv_list(fii_df['symbol'].tolist(), header='FII')}`"])

    msg2_lines.extend(["", "━━━━━━━━━━━━━━━━━━━━━", "🏦 *DII (Mutual Funds, Insurance, Pension)*"])
    dii_df = clientele_buys.get("DII", pd.DataFrame())
    if dii_df.empty:
        msg2_lines.append("• No DII buy deals recorded.")
    else:
        for _, r in dii_df.head(6).iterrows():
            msg2_lines.append(f"• `{r['symbol']}` — ₹{r['deal_value_cr']:,.1f} Cr")
        msg2_lines.extend(["", "📋 *TV Paste (DII):*", f"`{to_tv_list(dii_df['symbol'].tolist(), header='DII')}`"])

    msg2_lines.extend(["", "━━━━━━━━━━━━━━━━━━━━━", "👥 *OTHERS (Promoters, Super Investors, HNIs)*"])
    oth_df = clientele_buys.get("Others", pd.DataFrame())
    if oth_df.empty:
        msg2_lines.append("• No Other buy deals recorded.")
    else:
        for _, r in oth_df.head(6).iterrows():
            msg2_lines.append(f"• `{r['symbol']}` — ₹{r['deal_value_cr']:,.1f} Cr")
        msg2_lines.extend(["", "📋 *TV Paste (Others):*", f"`{to_tv_list(oth_df['symbol'].head(30).tolist(), header='Others')}`"])

    msg2_lines.extend(["", "━━━━━━━━━━━━━━━━━━━━━", "⚡ *PROP (Only Prop Trading Desks)*"])
    prop_df = clientele_buys.get("PROP", pd.DataFrame())
    if prop_df.empty:
        msg2_lines.append("• No Prop deals recorded.")
    else:
        for _, r in prop_df.head(6).iterrows():
            msg2_lines.append(f"• `{r['symbol']}` — ₹{r['deal_value_cr']:,.1f} Cr")
        msg2_lines.extend(["", "📋 *TV Paste (PROP):*", f"`{to_tv_list(prop_df['symbol'].head(30).tolist(), header='PROP')}`"])

    messages.append("\n".join(msg2_lines))

    # MESSAGE 3: Highest Buy / Sell Leaders
    msg3_lines = [
        "💰 *HIGHEST TURNOVER DEALS (BUY / SELL)*",
        f"🗓 *As of:* `{as_of}` | *Window:* Last {len(dates)} Deal Sessions",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "🟢 *HIGHEST BUY (Top Institutional Inflows)*",
    ]
    for idx, (_, r) in enumerate(top_buys.head(10).iterrows(), 1):
        msg3_lines.append(f"{idx}. `{r['symbol']}` — ₹{r['deal_value_cr']:,.1f} Cr")
    if not top_buys.empty:
        msg3_lines.extend(["", "📋 *TV Paste (Highest Buys):*", f"`{to_tv_list(top_buys['symbol'].head(25).tolist(), header='Highest Buys')}`"])

    msg3_lines.extend(["", "━━━━━━━━━━━━━━━━━━━━━", "🔴 *HIGHEST SELL (Top Distribution / Exits)*"])
    for idx, (_, r) in enumerate(top_sells.head(10).iterrows(), 1):
        msg3_lines.append(f"{idx}. `{r['symbol']}` — ₹{r['deal_value_cr']:,.1f} Cr")
    if not top_sells.empty:
        msg3_lines.extend(["", "📋 *TV Paste (Highest Sells):*", f"`{to_tv_list(top_sells['symbol'].head(25).tolist(), header='Highest Sells')}`"])

    messages.append("\n".join(msg3_lines))

    # MESSAGE 4: Filtered / Quarantined Streams
    msg4_lines = [
        "🛡 *FILTERED / QUARANTINED STREAMS*",
        f"🗓 *As of:* `{as_of}` | *Window:* Last {len(dates)} Deal Sessions",
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"📉 *BELOW 200EMA & 5% BAND* ({len(below_200_df)} stocks · Trend/Circuit Filter)",
    ]
    for _, r in below_200_df.head(6).iterrows():
        msg4_lines.append(f"• `{r['symbol']}` — ₹{r['buy_cr']:,.1f} Cr buy")
    if not below_200_df.empty:
        msg4_lines.extend(["", "📋 *TV Paste (Below 200EMA):*", f"`{to_tv_list(below_200_df['symbol'].tolist(), header='below 200EMA')}`", ""])

    msg4_lines.append(f"🪙 *<1000 CR MCAP* ({len(below_1000cr_df)} stocks · Micro-Cap Filter)")
    for _, r in below_1000cr_df.head(6).iterrows():
        msg4_lines.append(f"• `{r['symbol']}` — ₹{r['buy_cr']:,.1f} Cr buy")
    if not below_1000cr_df.empty:
        msg4_lines.extend(["", "📋 *TV Paste (<1000 Cr):*", f"`{to_tv_list(below_1000cr_df['symbol'].tolist(), header='<1000 Cr')}`", ""])

    msg4_lines.append(f"⚡ *ONLY IN PROP* ({len(prop_only_df)} stocks · Prop-Only Churn)")
    for _, r in prop_only_df.head(6).iterrows():
        msg4_lines.append(f"• `{r['symbol']}` — ₹{r['buy_cr']:,.1f} Cr buy")
    if not prop_only_df.empty:
        msg4_lines.extend(["", "📋 *TV Paste (PROP):*", f"`{to_tv_list(prop_only_df['symbol'].tolist(), header='PROP')}`"])

    messages.append("\n".join(msg4_lines))

    # Backwards compatibility day_rows
    day_rows = []
    for d in dates[:10]:
        sub = quality_deals[(quality_deals["trade_date"] == d) & (quality_deals["side"] == "BUY")]
        sub_syms = sub.sort_values("deal_value_cr", ascending=False)["symbol"].dropna().unique().tolist()
        day_rows.append({"date": str(d), "tv": to_tv_list(sub_syms), "count": len(sub_syms), "symbols": sub_syms})

    # Sectioned TV strings (matching Momentum tab bucket_copy_text: ###Section,NSE:...)
    sec_4plus = to_tv_list(four_plus["symbol"].tolist(), header="4+ Deal Days") if not four_plus.empty else ""
    sec_3days = to_tv_list(three["symbol"].tolist(), header="3 Deal Days") if not three.empty else ""
    sec_2days = to_tv_list(two["symbol"].tolist(), header="2 Deal Days") if not two.empty else ""
    sec_fii = to_tv_list(clientele_buys.get("FII", pd.DataFrame())["symbol"].tolist(), header="FII") if not clientele_buys.get("FII", pd.DataFrame()).empty else ""
    sec_dii = to_tv_list(clientele_buys.get("DII", pd.DataFrame())["symbol"].tolist(), header="DII") if not clientele_buys.get("DII", pd.DataFrame()).empty else ""
    sec_others = to_tv_list(clientele_buys.get("Others", pd.DataFrame())["symbol"].head(30).tolist(), header="Others") if not clientele_buys.get("Others", pd.DataFrame()).empty else ""
    sec_prop = to_tv_list(prop_only_df["symbol"].tolist(), header="PROP") if not prop_only_df.empty else ""
    sec_top_buys = to_tv_list(top_buys["symbol"].head(25).tolist(), header="Highest Buys") if not top_buys.empty else ""
    sec_top_sells = to_tv_list(top_sells["symbol"].head(25).tolist(), header="Highest Sells") if not top_sells.empty else ""

    sec_below_200 = to_tv_list(below_200_df["symbol"].tolist(), header="below 200EMA") if not below_200_df.empty else ""
    sec_below_1000cr = to_tv_list(below_1000cr_df["symbol"].tolist(), header="<1000 Cr") if not below_1000cr_df.empty else ""

    persistence_buckets = ",".join([s for s in [sec_4plus, sec_3days, sec_2days] if s])
    clientele_buckets = ",".join([s for s in [sec_fii, sec_dii, sec_others, sec_prop] if s])
    quality_buckets = ",".join([s for s in [sec_4plus, sec_3days, sec_2days, sec_fii, sec_dii, sec_top_buys] if s])
    all_deal_buckets = ",".join([s for s in [sec_4plus, sec_3days, sec_2days, sec_fii, sec_dii, sec_top_buys, sec_prop, sec_below_200, sec_below_1000cr] if s])

    tv_strings = {
        "four_plus": sec_4plus,
        "three": sec_3days,
        "two": sec_2days,
        "fii": sec_fii,
        "dii": sec_dii,
        "others": sec_others,
        "prop": sec_prop,
        "top_buys": sec_top_buys,
        "top_sells": sec_top_sells,
        "below_200ema": sec_below_200,
        "below_1000cr": sec_below_1000cr,
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
    }

    return {
        "as_of": as_of,
        "messages": messages,
        "days": day_rows,
        "buy_count": len(top_buys),
        "buy_tv": day_rows[0]["tv"] if day_rows else "",
        "tv_strings": tv_strings,
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


def query_deals_tv_lists(lookback_days: int = 20, min_mcap_cr: float = 1000.0, db_path: Path | None = None) -> dict:
    """Retained for backward compatibility with external callers."""
    return build_deals_telegram_report(lookback_days=lookback_days, min_mcap_cr=min_mcap_cr, db_path=db_path)


def notify_deals(
    *,
    dry_run: bool = False,
    lookback_days: int = 20,
    min_mcap_cr: float = 1000.0,
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
    parser.add_argument("--min-mcap", type=float, default=1000.0, help="Min market cap Cr (default 1000).")
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
