"""Parse and persist NSE PR ZIP event, action, and participation reports."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zipfile import ZipFile

import duckdb
import pandas as pd

try:
    from migrations import run_migrations
except ModuleNotFoundError:  # pragma: no cover - package import path
    from Scripts.migrations import run_migrations


EVENT_CATEGORY_MAP = {
    "financial result": "financial_results",
    "financial results": "financial_results",
    "outcome of board meeting": "board_meeting",
    "board meeting": "board_meeting",
    "general updates": "material_corporate_announcement",
    "analysts/institutional investor meet/con. call updates": "investor_meeting",
    "investor presentation": "investor_meeting",
    "acquisition": "order_or_contract",
    "order": "order_or_contract",
    "fund raise": "fund_raise",
    "regulatory": "regulatory_action",
}


@dataclass(frozen=True)
class PRReportBundle:
    trade_date: date
    events: pd.DataFrame
    corporate_actions: pd.DataFrame
    risk_daily: pd.DataFrame
    top_value: pd.DataFrame


def _read_member(archive: ZipFile, suffix: str) -> str:
    names = [name for name in archive.namelist() if name.lower().endswith(suffix.lower())]
    if not names:
        return ""
    return archive.read(names[0]).decode("utf-8-sig", errors="replace")


def _read_csv(text: str) -> pd.DataFrame:
    if not text.strip():
        return pd.DataFrame()
    try:
        return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, UnicodeError):
        return pd.DataFrame()


def _date(value: object, formats: tuple[str, ...] = ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y")) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(text.upper(), fmt).date()
        except ValueError:
            continue
    parsed = pd.to_datetime(text, errors="coerce")
    return parsed.date() if not pd.isna(parsed) else None


def _symbol(value: object) -> str:
    return re.sub(r"[^A-Z0-9&-]", "", str(value or "").strip().upper())


def _event_type(category: str, headline: str) -> str:
    text = f"{category} {headline}".strip().lower()
    for phrase, event_type in EVENT_CATEGORY_MAP.items():
        if phrase in text:
            return event_type
    if "dividend" in text:
        return "dividend"
    if "bonus" in text:
        return "bonus"
    if "split" in text:
        return "split"
    if "rights" in text:
        return "rights_issue"
    return "other"


def normalize_announcement(text: str, trade_date: date) -> pd.DataFrame:
    columns = ["symbol", "event_date", "event_type", "headline", "source_id"]
    rows: list[dict[str, object]] = []
    pattern = re.compile(r"^(?P<company>.*?)\s+(?P<symbol>[A-Z0-9&-]+)\s*:\s*(?P<category>[^:]+?)\s*:\s*(?P<headline>.*)$")
    for index, raw in enumerate(str(text or "").splitlines()):
        line = raw.strip()
        match = pattern.match(line)
        if not match:
            continue
        symbol = _symbol(match.group("symbol"))
        category = match.group("category").strip()
        headline = match.group("headline").strip()
        if not symbol or not headline:
            continue
        rows.append(
            {
                "symbol": symbol,
                "event_date": trade_date,
                "event_type": _event_type(category, headline),
                "headline": headline,
                "source_id": f"an:{index}",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _parse_board_meetings(text: str, trade_date: date) -> pd.DataFrame:
    columns = ["symbol", "event_date", "event_type", "headline", "source_id"]
    rows: list[dict[str, object]] = []
    pattern = re.compile(r"^(?P<company>.*?)\s+(?P<symbol>[A-Z0-9&-]+)\s*:\s*(?P<event_date>\d{1,2}-[A-Z]{3}-\d{4})\s*:\s*(?P<purpose>[^:]+?)\s*:??\s*(?P<headline>.*)$")
    for index, raw in enumerate(str(text or "").splitlines()):
        match = pattern.match(raw.strip())
        if not match:
            continue
        symbol = _symbol(match.group("symbol"))
        event_date = _date(match.group("event_date")) or trade_date
        purpose = match.group("purpose").strip()
        headline = match.group("headline").strip() or purpose
        if symbol:
            rows.append({"symbol": symbol, "event_date": event_date, "event_type": "board_meeting", "headline": headline, "source_id": f"bm:{index}"})
    return pd.DataFrame(rows, columns=columns)


def _parse_corporate_actions(text: str) -> pd.DataFrame:
    columns = ["symbol", "ex_date", "action_type", "ratio_from", "ratio_to", "cash_amount", "description"]
    frame = _read_csv(text)
    rows: list[dict[str, object]] = []
    if frame.empty:
        return pd.DataFrame(rows, columns=columns)
    for row in frame.to_dict("records"):
        series = str(row.get("SERIES") or "").strip().upper()
        if series not in {"EQ", "BE", "BZ", "SM", "ST"}:
            continue
        symbol = _symbol(row.get("SYMBOL"))
        purpose = str(row.get("PURPOSE") or "").strip()
        text_lower = purpose.lower()
        action_type = "other"
        for needle, normalized in (("dividend", "dividend"), ("bonus", "bonus"), ("split", "split"), ("rights", "rights_issue"), ("merger", "merger_demerger"), ("demerger", "merger_demerger")):
            if needle in text_lower:
                action_type = normalized
                break
        ex_date = _date(row.get("EX_DT")) or _date(row.get("RECORD_DT")) or _date(row.get("BC_STRT_DT"))
        if symbol and ex_date:
            rows.append({"symbol": symbol, "ex_date": ex_date, "action_type": action_type, "ratio_from": 1.0, "ratio_to": 1.0, "cash_amount": None, "description": purpose})
    return pd.DataFrame(rows, columns=columns)


def _parse_risk_daily(text: str, trade_date: date) -> pd.DataFrame:
    columns = ["trade_date", "symbol", "security_name", "risk_type", "new_value", "previous_value", "status"]
    frame = _read_csv(text)
    rows: list[dict[str, object]] = []
    if frame.empty:
        return pd.DataFrame(rows, columns=columns)
    normalized = {str(col).strip().upper(): col for col in frame.columns}
    if "HIGH/LOW" in normalized:
        for row in frame.to_dict("records"):
            symbol = _symbol(row.get(normalized.get("SYMBOL", "SYMBOL")))
            status = str(row.get(normalized["HIGH/LOW"]) or "").strip().upper()
            if symbol and status in {"H", "L"}:
                rows.append({"trade_date": trade_date, "symbol": symbol, "security_name": str(row.get(normalized.get("SECURITY", "SECURITY")) or "").strip(), "risk_type": "new_high" if status == "H" else "new_low", "new_value": None, "previous_value": None, "status": status})
    elif "NEW_STATUS" in normalized:
        for row in frame.to_dict("records"):
            status = str(row.get(normalized["NEW_STATUS"]) or "").strip().upper()
            if status in {"H", "L"}:
                rows.append({"trade_date": trade_date, "symbol": "", "security_name": str(row.get(normalized.get("SECURITY", "SECURITY")) or "").strip(), "risk_type": "new_high" if status == "H" else "new_low", "new_value": float(str(row.get(normalized.get("NEW", "NEW")) or "0").replace(",", "") or 0), "previous_value": float(str(row.get(normalized.get("PREVIOUS", "PREVIOUS")) or "0").replace(",", "") or 0), "status": status})
    return pd.DataFrame(rows, columns=columns)


def _parse_top_value(text: str, trade_date: date) -> pd.DataFrame:
    columns = ["trade_date", "symbol", "security_name", "previous_close", "close_price", "net_trade_qty", "net_trade_value_cr"]
    frame = _read_csv(text)
    rows: list[dict[str, object]] = []
    if frame.empty:
        return pd.DataFrame(rows, columns=columns)
    for row in frame.to_dict("records"):
        security_name = str(row.get("SECURITY") or "").strip()
        value = float(str(row.get("NET_TRDVAL") or "0").replace(",", "").strip() or 0) / 10_000_000
        rows.append({"trade_date": trade_date, "symbol": "", "security_name": security_name, "previous_close": float(str(row.get("PREV_CL_PR") or "0").replace(",", "").strip() or 0), "close_price": float(str(row.get("CLOSE_PRIC") or "0").replace(",", "").strip() or 0), "net_trade_qty": int(float(str(row.get("NET_TRDQTY") or "0").replace(",", "").strip() or 0)), "net_trade_value_cr": value})
    return pd.DataFrame(rows, columns=columns)


def parse_pr_zip(path: Path, trade_date: date) -> PRReportBundle:
    path = Path(path)
    with ZipFile(path) as archive:
        events = pd.concat(
            [normalize_announcement(_read_member(archive, "an" + trade_date.strftime("%d%m%Y") + ".txt"), trade_date), _parse_board_meetings(_read_member(archive, "bm" + trade_date.strftime("%d%m%Y") + ".txt"), trade_date)],
            ignore_index=True,
        )
        return PRReportBundle(
            trade_date=trade_date,
            events=events,
            corporate_actions=_parse_corporate_actions(_read_member(archive, "bc" + trade_date.strftime("%d%m%Y") + ".csv")),
            risk_daily=pd.concat([_parse_risk_daily(_read_member(archive, "bh" + trade_date.strftime("%d%m%Y") + ".csv"), trade_date), _parse_risk_daily(_read_member(archive, "hl" + trade_date.strftime("%d%m%Y") + ".csv"), trade_date)], ignore_index=True),
            top_value=_parse_top_value(_read_member(archive, "tt" + trade_date.strftime("%d%m%Y") + ".csv"), trade_date),
        )


def _insert_frame(db: duckdb.DuckDBPyConnection, name: str, frame: pd.DataFrame, columns: list[str], conflict: str) -> int:
    if frame.empty:
        return 0
    values = frame.reindex(columns=columns).where(pd.notna(frame), None)
    db.register("pr_rows", values)
    quoted = ",".join(f'"{col}"' for col in columns)
    db.execute(f'INSERT INTO "{name}" ({quoted}) SELECT {quoted} FROM pr_rows ON CONFLICT {conflict} DO UPDATE SET ' + ",".join(f'"{col}"=excluded."{col}"' for col in columns if col not in conflict.strip("()").split(",")))
    db.unregister("pr_rows")
    return len(values)


def upsert_pr_bundle(db_path: Path, bundle: PRReportBundle, source_checksum: str) -> dict[str, int]:
    run_migrations(Path(db_path))
    with duckdb.connect(str(db_path)) as db:
        events = bundle.events.copy()
        events["source_checksum"] = source_checksum
        event_count = _insert_frame(db, "security_events", events, ["symbol", "event_date", "event_type", "headline", "source_id", "source_checksum"], "(symbol, event_date, event_type, source_id)")

        actions = bundle.corporate_actions.copy()
        actions["source_checksum"] = source_checksum
        action_count = _insert_frame(db, "corporate_actions", actions, ["symbol", "ex_date", "action_type", "ratio_from", "ratio_to", "cash_amount", "description", "source_checksum"], "(symbol, ex_date, action_type, description)")

        risk = bundle.risk_daily.copy()
        risk["source_checksum"] = source_checksum
        risk["source_file"] = "bh/hl"
        risk_count = _insert_frame(db, "security_risk_daily", risk, ["trade_date", "symbol", "security_name", "risk_type", "new_value", "previous_value", "status", "source_file", "source_checksum"], "(trade_date, symbol, security_name, risk_type, source_file)")

        top_value = bundle.top_value.copy()
        top_value["source_checksum"] = source_checksum
        top_count = _insert_frame(db, "top_value_daily", top_value, ["trade_date", "symbol", "security_name", "previous_close", "close_price", "net_trade_qty", "net_trade_value_cr", "source_checksum"], "(trade_date, security_name)")
    return {"security_events": event_count, "corporate_actions": action_count, "security_risk_daily": risk_count, "top_value_daily": top_count}


def zip_checksum(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


__all__ = ["PRReportBundle", "normalize_announcement", "parse_pr_zip", "upsert_pr_bundle", "zip_checksum"]
