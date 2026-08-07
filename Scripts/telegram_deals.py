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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd

from config import DB_PATH, ROOT_DIR

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


def to_tv_list(symbols: list[str]) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        if not s or str(s).strip() == "":
            continue
        tok = f"NSE:{tradingview_symbol(s)}"
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return ",".join(out)


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

def query_deals_tv_lists(lookback_days: int = 10, min_mcap_cr: float = 1000.0) -> dict:
    """
    Build BUY-only TradingView lists per deal session for the last N deal days.
    Newest session first. Filters: MCap >= min when known; prefer close > 200 EMA.
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    lookback_days = max(1, int(lookback_days))

    with duckdb.connect(str(DB_PATH), read_only=True) as db:
        max_deal = db.execute("SELECT max(trade_date) FROM deals").fetchone()[0]
        if max_deal is None:
            return {
                "as_of": None,
                "days": [],
                "buy_count": 0,
                "lookback_days": lookback_days,
                "min_mcap_cr": min_mcap_cr,
            }

        # Last N distinct deal sessions (not calendar days), newest first
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
            return {
                "as_of": str(pd.to_datetime(max_deal).date()),
                "days": [],
                "buy_count": 0,
                "lookback_days": lookback_days,
                "min_mcap_cr": min_mcap_cr,
            }

        dates = [pd.to_datetime(d).date() for d in session_dates["trade_date"].tolist()]
        # Keep newest → oldest
        oldest = min(dates)

        sql = """
        WITH buys AS (
            SELECT d.trade_date, d.symbol, sum(d.deal_value_cr) AS deal_value_cr
            FROM deals d
            WHERE d.side = 'BUY'
              AND d.trade_date >= ?
            GROUP BY d.trade_date, d.symbol
        ),
        ind AS (
            SELECT i.symbol, i.trade_date, i.close_price, i.ema_200, m.market_cap_cr
            FROM indicators_daily i
            JOIN stocks_master m USING(symbol)
            WHERE i.trade_date >= ?
        )
        SELECT b.trade_date, b.symbol, b.deal_value_cr,
               i.market_cap_cr, i.close_price, i.ema_200
        FROM buys b
        LEFT JOIN ind i ON i.symbol = b.symbol AND i.trade_date = b.trade_date
        ORDER BY b.trade_date DESC, b.deal_value_cr DESC
        """
        df = db.execute(sql, [oldest, oldest]).fetchdf()

    if df.empty:
        return {
            "as_of": str(pd.to_datetime(max_deal).date()),
            "days": [],
            "buy_count": 0,
            "lookback_days": lookback_days,
            "min_mcap_cr": min_mcap_cr,
        }

    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["market_cap_cr"] = pd.to_numeric(df["market_cap_cr"], errors="coerce")
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    df["ema_200"] = pd.to_numeric(df["ema_200"], errors="coerce")

    # Only the requested sessions, newest first
    day_rows: list[dict] = []
    total_buy = 0
    for d in dates:
        part = df[df["trade_date"] == d].copy()
        if part.empty:
            day_rows.append({"date": str(d), "tv": "", "count": 0, "symbols": []})
            continue
        part = part[(part["market_cap_cr"].isna()) | (part["market_cap_cr"] >= min_mcap_cr)]
        part = part[
            part["ema_200"].isna()
            | part["close_price"].isna()
            | (part["close_price"] > part["ema_200"])
        ]
        part = part.sort_values("deal_value_cr", ascending=False)
        symbols = part["symbol"].dropna().astype(str).str.upper().drop_duplicates().tolist()
        tv = to_tv_list(symbols)
        total_buy += len(symbols)
        day_rows.append({"date": str(d), "tv": tv, "count": len(symbols), "symbols": symbols})

    as_of = str(dates[0]) if dates else str(pd.to_datetime(max_deal).date())
    return {
        "as_of": as_of,
        "days": day_rows,
        "buy_count": total_buy,
        "lookback_days": lookback_days,
        "min_mcap_cr": min_mcap_cr,
        # convenience: today's (latest) pure list
        "buy_tv": day_rows[0]["tv"] if day_rows else "",
    }


def notify_deals(
    *,
    dry_run: bool = False,
    lookback_days: int = 10,
    min_mcap_cr: float = 1000.0,
    token: str | None = None,
    chat_id: str | None = None,
) -> dict:
    """
    Send BUY-only TV paste lists for the last N deal sessions.
    Newest day first. Message body is pure NSE:SYM,... (date line only as separator).
    No SELL. No 'BUY (TV paste)' labels.
    """
    load_dotenv()
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    payload = query_deals_tv_lists(lookback_days=lookback_days, min_mcap_cr=min_mcap_cr)
    days = payload.get("days") or []

    messages: list[str] = []
    for day in days:
        d = day["date"]
        tv = (day.get("tv") or "").strip()
        if not tv:
            continue
        # Date only so you know which session — then pure TV paste line(s)
        messages.append(f"{d}\n{tv}")

    if not messages:
        messages = [f"{payload.get('as_of') or 'n/a'}\n(none)"]

    if dry_run:
        for m in messages:
            print("---")
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
    n_days = len([d for d in days if d.get("tv")])
    print(
        f"Telegram: sent BUY TV lists for {n_days} sessions "
        f"(newest {payload.get('as_of')}, lookback {lookback_days})"
    )
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
        default=10,
        help="Number of recent deal sessions (default 10, newest first).",
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
