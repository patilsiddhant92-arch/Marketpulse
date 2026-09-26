"""Split / bonus / consolidation price adjustment from official NSE data."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ADJUSTING_KINDS = frozenset({"split", "bonus", "consolidation"})

_NUM = r"(\d+(?:\.\d+)?)"
# Match BONUS followed optionally by ISSUE/SHARES, then ratio; restricts to nearby numbers
_BONUS_RE = re.compile(rf"BONUS(?:\s+(?:ISSUE|SHARES?))?[\s:-]*{_NUM}\s*:\s*{_NUM}")
# "FROM RS 10 ... TO RE 1", "RS.10 TO RS.2", "FRM RS 2 TO RE 1"
_FV_RE = re.compile(rf"(?:FROM|FRM)?\s*R[SE]\.?\s*{_NUM}\D*?\bTO\b\s*R[SE]\.?\s*{_NUM}")
# Match SPLIT, SPLT, SUB-DIVISION, SUB - DIVISION, SUB DIVISION, SUBDIVISION
_SPLIT_RE = re.compile(r"SPLIT|SPLT|SUB\s*-?\s*DIVISION")
# Match DIV with word boundaries to avoid matching inside DIVISION
_DIV_RE = re.compile(r"\bDIV(IDEND)?\b|\bDIV\s*-")


@dataclass(frozen=True)
class ParsedAction:
    kind: str
    factor: float | None


def parse_purpose(purpose: str) -> ParsedAction:
    text = re.sub(r"\s+", " ", str(purpose or "").upper()).strip()
    if not text:
        return ParsedAction("other", None)

    # Check for pref_bonus first (takes precedence even if BONUS pattern matches)
    if "BONUS" in text and ("NCRPS" in text or "PREF" in text or "DEBENTURE" in text):
        return ParsedAction("pref_bonus", None)

    # Try to parse adjusting actions (bonus, split, consolidation)
    # These should be checked before non-adjusting (rights, demerger, div)
    # so that combined purposes like "BONUS 1:1 AND RIGHTS" return the bonus

    # Try bonus first
    has_bonus = "BONUS" in text
    if has_bonus:
        m = _BONUS_RE.search(text)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if a > 0 and b > 0:
                return ParsedAction("bonus", b / (a + b))
        # BONUS text exists but no valid pattern; continue to check non-adjusting keywords
        # only return "other" if no other keywords match

    # Try split/consolidation
    is_split = _SPLIT_RE.search(text) is not None
    is_consolidation = "CONSOLIDAT" in text
    has_adjusting_keyword = has_bonus or is_split or is_consolidation
    if is_split or is_consolidation:
        m = _FV_RE.search(text)
        if m:
            old, new = float(m.group(1)), float(m.group(2))
            if old > 0 and new > 0 and old != new:
                return ParsedAction("consolidation" if new > old else "split", new / old)
        # SPLIT/CONSOLIDATION text exists but no valid pattern; continue to check non-adjusting keywords

    # Fall back to non-adjusting keywords
    if "RIGHTS" in text:
        return ParsedAction("rights", None)
    if "DEMERGER" in text or "DE-MERGER" in text:
        return ParsedAction("demerger", None)
    if _DIV_RE.search(text):
        return ParsedAction("dividend", None)

    # If we had adjusting keywords (BONUS/SPLIT/CONSOLIDATION) but no valid ratio and no other keywords, return "other"
    if has_adjusting_keyword:
        return ParsedAction("other", None)

    return ParsedAction("other", None)


ACTION_COLUMNS = ["symbol", "ex_date", "kind", "factor", "description", "source"]
_BC_MEMBER = re.compile(r"(?i)^bc\d{6,8}\.csv$")
_ACTION_SERIES = {"EQ", "BE", "BZ", "SM", "ST"}


def _parse_date(value) -> pd.Timestamp:
    text = str(value or "").strip()
    if not text:
        return pd.NaT
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%d-%m-%Y"):
        ts = pd.to_datetime(text, format=fmt, errors="coerce")
        if not pd.isna(ts):
            return ts.normalize()
    return pd.NaT


def read_bc_member(zf: zipfile.ZipFile) -> pd.DataFrame:
    names = [n for n in zf.namelist() if _BC_MEMBER.match(Path(n).name)]
    if not names:
        return pd.DataFrame()
    text = zf.read(names[0]).decode("utf-8-sig", errors="replace")
    if not text.strip():
        return pd.DataFrame()
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)


def _action_rows(symbols, ex_dates, purposes, source: str) -> pd.DataFrame:
    rows = []
    for sym, ex, purpose in zip(symbols, ex_dates, purposes):
        if not sym or pd.isna(ex):
            continue
        parsed = parse_purpose(purpose)
        rows.append({"symbol": sym, "ex_date": ex, "kind": parsed.kind, "factor": parsed.factor,
                     "description": str(purpose).strip(), "source": source})
    return pd.DataFrame(rows, columns=ACTION_COLUMNS)


def _first_date(row: dict, keys: tuple[str, ...]) -> pd.Timestamp:
    """Return the first parseable date among `keys` in `row`, else NaT."""
    for key in keys:
        parsed = _parse_date(row.get(key))
        if not pd.isna(parsed):
            return parsed
    return pd.NaT


def actions_from_bc_frame(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    df = raw.rename(columns=lambda c: str(c).strip().upper())
    df = df[df.get("SERIES", pd.Series("", index=df.index)).astype(str).str.strip().str.upper().isin(_ACTION_SERIES)]
    ex = [_first_date(r, ("EX_DT", "RECORD_DT", "BC_STRT_DT")) for r in df.to_dict("records")]
    syms = df["SYMBOL"].astype(str).str.strip().str.upper().tolist()
    return _action_rows(syms, ex, df["PURPOSE"].tolist(), "bc")


def collect_bc_actions(zip_paths: list[Path]) -> pd.DataFrame:
    frames = []
    for p in zip_paths:
        try:
            with zipfile.ZipFile(p) as zf:
                frames.append(actions_from_bc_frame(read_bc_member(zf)))
        except (zipfile.BadZipFile, OSError, pd.errors.ParserError) as exc:
            print(f"Skipped {Path(p).name}: {exc}")
    if not frames:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(["symbol", "ex_date", "description"]).reset_index(drop=True)


def actions_from_corporate_actions_table(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    ex = pd.to_datetime(df["ex_date"], errors="coerce").dt.normalize()
    syms = df["symbol"].astype(str).str.strip().str.upper().tolist()
    return _action_rows(syms, ex.tolist(), df["description"].fillna("").tolist(), "bc")


def find_pr_zips(root: Path) -> list[Path]:
    root = Path(root)
    found = set((root / "Input" / "archive").glob("PR*.zip"))
    found |= set((root / "Input" / "archive" / "backfill" / "pr").glob("PR*.zip"))
    downloads = root / "Input" / "downloads"
    if downloads.exists():
        found |= set(downloads.rglob("PR*.zip"))
    return sorted(found)
