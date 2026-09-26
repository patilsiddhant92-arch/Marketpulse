"""Split / bonus / consolidation price adjustment from official NSE data."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

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


# RS/RE-less face-value forms, only searched *after* a SPLIT/CONSOLIDATION keyword:
# "FVSPLIT10TO2", "FV SPLIT 10 TO 2", "SPLIT FROM 10 TO 1" (either side may still carry RS/RE).
_FV_BARE_RE = re.compile(rf"(?:R[SE]\.?\s*)?{_NUM}\s*(?:/-)?\s*TO\s*(?:R[SE]\.?\s*)?{_NUM}")
_CONSOLIDATION_RE = re.compile(r"CONSOLIDAT")
# Indian face values are at most Rs 1000; anything larger in a bare "X TO Y" is not a face value
# (e.g. the "2021 TO 05" inside a "01/08/2021 TO 05/08/2021" date range).
_MAX_FACE_VALUE = 1000.0


@dataclass(frozen=True)
class ParsedAction:
    kind: str
    factor: float | None


def _normalize_purpose(purpose) -> str:
    return re.sub(r"\s+", " ", str(purpose or "").upper()).strip()


def _is_pref_bonus(text: str) -> bool:
    return "BONUS" in text and ("NCRPS" in text or "PREF" in text or "DEBENTURE" in text)


def _fv_action(text: str, start: int) -> ParsedAction | None:
    """The face-value change after position `start` (a SPLIT/CONSOLIDATION keyword), else None.

    Tries the strict "RS x ... TO RS y" form after the keyword, then the RS-less form after the
    keyword (plausible face values only), then -- for backward compatibility -- the strict form
    anywhere in the text.
    """
    def _valid(old: float, new: float) -> ParsedAction | None:
        if old > 0 and new > 0 and old != new:
            return ParsedAction("consolidation" if new > old else "split", new / old)
        return None

    tail = text[start:]
    m = _FV_RE.search(tail)
    if m and (act := _valid(float(m.group(1)), float(m.group(2)))):
        return act
    for m in _FV_BARE_RE.finditer(tail):
        old, new = float(m.group(1)), float(m.group(2))
        if old <= _MAX_FACE_VALUE and new <= _MAX_FACE_VALUE and (act := _valid(old, new)):
            return act
    m = _FV_RE.search(text)
    if m and (act := _valid(float(m.group(1)), float(m.group(2)))):
        return act
    return None


def _adjusting_actions(text: str) -> list[ParsedAction]:
    """Every adjusting action (bonus a:b; split/consolidation x->y) in `text`, in text order."""
    found: list[tuple[int, ParsedAction]] = []
    if "BONUS" in text:
        for m in _BONUS_RE.finditer(text):
            a, b = float(m.group(1)), float(m.group(2))
            if a > 0 and b > 0:
                found.append((m.start(), ParsedAction("bonus", b / (a + b))))
    keyword_pos = [m.start() for m in (_SPLIT_RE.search(text), _CONSOLIDATION_RE.search(text)) if m]
    if keyword_pos:
        start = min(keyword_pos)
        act = _fv_action(text, start)
        if act is not None:
            found.append((start, act))
    found.sort(key=lambda t: t[0])
    return [act for _, act in found]


def _non_adjusting_kind(text: str) -> ParsedAction:
    if "RIGHTS" in text:
        return ParsedAction("rights", None)
    if "DEMERGER" in text or "DE-MERGER" in text:
        return ParsedAction("demerger", None)
    if _DIV_RE.search(text):
        return ParsedAction("dividend", None)
    # Includes BONUS/SPLIT/CONSOLIDATION text without a parseable ratio: never guessed.
    return ParsedAction("other", None)


def parse_purpose_all(purpose: str) -> list[ParsedAction]:
    """Every adjusting action in an NSE purpose text, in text order.

    `BONUS2:1/FVSPLIT10TO2` -> [bonus 1/3, split 0.2]. When the text holds no adjusting action,
    a single-element list with the non-adjusting classification (pref_bonus / rights / demerger /
    dividend / other) is returned, so the result is never empty.
    """
    text = _normalize_purpose(purpose)
    if not text:
        return [ParsedAction("other", None)]
    # pref_bonus takes precedence even if a BONUS ratio matches (it's not an equity bonus).
    if _is_pref_bonus(text):
        return [ParsedAction("pref_bonus", None)]
    actions = _adjusting_actions(text)
    return actions if actions else [_non_adjusting_kind(text)]


def parse_purpose(purpose: str) -> ParsedAction:
    """Single-action classification of an NSE purpose text.

    Adjusting actions win over non-adjusting keywords ("BONUS 1:1 AND RIGHTS" is a bonus). When
    a text holds several adjusting actions, the bonus is returned (historical precedence); use
    `parse_purpose_all` to get all of them.
    """
    actions = parse_purpose_all(purpose)
    return next((a for a in actions if a.kind == "bonus"), actions[0])


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


def _read_bc_csv(text: str) -> tuple[pd.DataFrame, int]:
    """Parse bc CSV text; malformed lines (wrong field count) are skipped, not fatal.

    Returns `(frame, n_skipped)`. The fast C parser is tried first; only if it rejects the text
    is it re-read with the python engine and an `on_bad_lines` callback that drops and counts
    each bad line, so one stray comma no longer discards a whole day's actions.
    """
    try:
        return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False), 0
    except pd.errors.ParserError:
        bad: list[list[str]] = []

        def _skip(line: list[str]):
            bad.append(line)
            return None

        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, engine="python", on_bad_lines=_skip)
        return df, len(bad)


def read_bc_member(zf: zipfile.ZipFile) -> pd.DataFrame:
    """The bc CSV member of a PR zip as a string frame (empty if absent). The number of malformed
    lines skipped while parsing is recorded in `frame.attrs["skipped_lines"]`."""
    names = [n for n in zf.namelist() if _BC_MEMBER.match(Path(n).name)]
    if not names:
        return pd.DataFrame()
    text = zf.read(names[0]).decode("utf-8-sig", errors="replace")
    if not text.strip():
        return pd.DataFrame()
    df, skipped = _read_bc_csv(text)
    df.attrs["skipped_lines"] = skipped
    return df


def _warn_skipped_lines(zip_name: str, skipped: int) -> None:
    if skipped:
        print(f"Warning: {zip_name}: skipped {skipped} malformed line{'s' if skipped != 1 else ''} in its bc CSV")


def _action_rows(symbols, ex_dates, purposes, source: str) -> pd.DataFrame:
    """One row per parsed action: a multi-action purpose ("BONUS2:1/FVSPLIT10TO2") expands into
    several rows sharing symbol, ex_date, description and source. Each distinct purpose text is
    parsed once."""
    rows = []
    parsed_cache: dict[str, list[ParsedAction]] = {}
    for sym, ex, purpose in zip(symbols, ex_dates, purposes):
        if not sym or pd.isna(ex):
            continue
        description = str(purpose).strip()
        parsed = parsed_cache.get(description)
        if parsed is None:
            parsed = parsed_cache[description] = parse_purpose_all(description)
        for act in parsed:
            rows.append({"symbol": sym, "ex_date": ex, "kind": act.kind, "factor": act.factor,
                         "description": description, "source": source})
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


# Optional extra column on bc action frames: the date an announcement was published (the trade
# date encoded in its PR zip name). Consumers that only know `ACTION_COLUMNS` may ignore it.
PUBLISHED = "published"
BC_ACTION_COLUMNS = ACTION_COLUMNS + [PUBLISHED]
_PR_ZIP_NAME = re.compile(r"(?i)^PR(\d{2})(\d{2})(\d{2})")


def published_date_from_zip_name(name: str) -> pd.Timestamp:
    """`PRddmmyy.zip` -> that trade date; NaT when the name doesn't follow the pattern."""
    m = _PR_ZIP_NAME.match(Path(str(name)).name)
    if not m:
        return pd.NaT
    dd, mm, yy = m.groups()
    return pd.to_datetime(f"20{yy}-{mm}-{dd}", format="%Y-%m-%d", errors="coerce")


def _dedupe_bc_actions(actions: pd.DataFrame) -> pd.DataFrame:
    """One row per (symbol, ex_date, description, kind), keeping the FIRST-published copy.

    NSE republishes the same announcement in successive daily bc files; the date a version first
    appeared is when it superseded any earlier version, so that is the `published` date kept.
    A missing `published` falls back to the row's ex_date.
    """
    if actions.empty:
        return actions.reset_index(drop=True)
    out = actions.copy()
    if PUBLISHED not in out.columns:
        out[PUBLISHED] = pd.NaT
    out[PUBLISHED] = pd.to_datetime(out[PUBLISHED], errors="coerce").fillna(pd.to_datetime(out["ex_date"], errors="coerce"))
    out = out.sort_values(PUBLISHED, kind="stable", na_position="last")
    out = out.drop_duplicates(["symbol", "ex_date", "description", "kind"])
    return out.sort_index().reset_index(drop=True)


def collect_bc_actions(zip_paths: list[Path]) -> pd.DataFrame:
    """bc actions from every PR zip (`BC_ACTION_COLUMNS`: `ACTION_COLUMNS` + `published`)."""
    frames = []
    for p in zip_paths:
        try:
            with zipfile.ZipFile(p) as zf:
                raw = read_bc_member(zf)
            _warn_skipped_lines(Path(p).name, raw.attrs.get("skipped_lines", 0))
            frames.append(actions_from_bc_frame(raw).assign(**{PUBLISHED: published_date_from_zip_name(Path(p).name)}))
        except (zipfile.BadZipFile, OSError, pd.errors.ParserError) as exc:
            print(f"Skipped {Path(p).name}: {exc}")
    if not frames:
        return pd.DataFrame(columns=BC_ACTION_COLUMNS)
    return _dedupe_bc_actions(pd.concat(frames, ignore_index=True))


def actions_from_corporate_actions_table(df: pd.DataFrame) -> pd.DataFrame:
    """Re-parse the live `corporate_actions` table. It carries no publication date, so each
    row's `published` is its ex_date."""
    if df is None or df.empty:
        return pd.DataFrame(columns=BC_ACTION_COLUMNS)
    ex = pd.to_datetime(df["ex_date"], errors="coerce").dt.normalize()
    syms = df["symbol"].astype(str).str.strip().str.upper().tolist()
    out = _action_rows(syms, ex.tolist(), df["description"].fillna("").tolist(), "bc")
    out[PUBLISHED] = out["ex_date"]
    return out


def find_pr_zips(root: Path) -> list[Path]:
    root = Path(root)
    found = set((root / "Input" / "archive").glob("PR*.zip"))
    found |= set((root / "Input" / "archive" / "backfill" / "pr").glob("PR*.zip"))
    downloads = root / "Input" / "downloads"
    if downloads.exists():
        found |= set(downloads.rglob("PR*.zip"))
    return sorted(found)


CLEAN_BONUS_RATIOS = (1.25, 4 / 3, 1.5, 5 / 3, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 11.0)
MCAP_SOURCES = ("mcap_fv", "mcap_issue")


def _mcap_frame(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), dtype=str, skipinitialspace=True)
    df.columns = [re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_") for c in df.columns]
    fv_col = next((c for c in df.columns if c.startswith("face_value")), None)
    is_col = next((c for c in df.columns if c.startswith("issue_size")), None)
    if not fv_col or not is_col or "symbol" not in df.columns:
        return pd.DataFrame(columns=["file_date", "symbol", "face_value", "issue_size"])
    if "series" in df.columns:
        df = df[df["series"].fillna("").astype(str).str.strip() != ""]
    num = lambda s: pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")
    return pd.DataFrame({
        "file_date": pd.to_datetime(df["trade_date"].astype(str).str.strip(), format="%d %b %Y", errors="coerce"),
        "symbol": df["symbol"].astype(str).str.strip().str.upper(),
        "face_value": num(df[fv_col]),
        "issue_size": num(df[is_col]),
    }).dropna(subset=["file_date"])


def read_mcap_frames(root: Path, zip_paths: list[Path]) -> pd.DataFrame:
    root = Path(root)
    paths = set((root / "Input" / "archive").glob("mcap*.csv")) | set((root / "Input" / "daily").glob("mcap*.csv"))
    downloads = root / "Input" / "downloads"
    if downloads.exists():
        paths |= set(downloads.rglob("mcap*.csv"))
    frames = []
    # Sort paths to prefer canonical names: duplicate copies like "mcap04082026 (2).csv" come before "mcap04082026.csv",
    # so deduplication with keep="last" preserves the canonical file's data
    for p in sorted(paths, key=lambda x: (" (" not in x.name, x.name)):
        try:
            frames.append(_mcap_frame(Path(p).read_text(encoding="utf-8-sig", errors="replace")))
        except Exception as exc:
            print(f"Skipped {Path(p).name}: {exc}")
    for z in zip_paths:
        try:
            with zipfile.ZipFile(z) as zf:
                for n in zf.namelist():
                    if Path(n).name.lower().startswith("mcap") and n.lower().endswith(".csv"):
                        frames.append(_mcap_frame(zf.read(n).decode("utf-8-sig", errors="replace")))
        except (zipfile.BadZipFile, OSError) as exc:
            print(f"Skipped {Path(z).name}: {exc}")
    if not frames:
        return pd.DataFrame(columns=["file_date", "symbol", "face_value", "issue_size"])
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(["file_date", "symbol"], keep="last").sort_values(["symbol", "file_date"]).reset_index(drop=True)


def actions_from_mcap(frames: pd.DataFrame, tol: float = 0.01) -> pd.DataFrame:
    rows = []
    if frames is None or frames.empty:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    f = frames.sort_values(["symbol", "file_date"])
    for sym, g in f.groupby("symbol", sort=False):
        g = g.dropna(subset=["face_value", "issue_size"])
        prev = None
        for cur in g.itertuples(index=False):
            if prev is not None and prev.face_value > 0 and prev.issue_size > 0:
                if cur.face_value != prev.face_value:
                    factor = cur.face_value / prev.face_value
                    kind = "consolidation" if factor > 1 else "split"
                    rows.append({"symbol": sym, "ex_date": cur.file_date, "kind": kind, "factor": factor,
                                 "description": f"FV {prev.face_value}->{cur.face_value}", "source": "mcap_fv"})
                else:
                    r = cur.issue_size / prev.issue_size
                    match = next((c for c in CLEAN_BONUS_RATIOS if abs(r / c - 1) <= tol), None)
                    if match is not None:
                        rows.append({"symbol": sym, "ex_date": cur.file_date, "kind": "bonus", "factor": 1 / match,
                                     "description": f"ISSUE x{match:.2f}", "source": "mcap_issue"})
            prev = cur
    return pd.DataFrame(rows, columns=ACTION_COLUMNS)


# --------------------------------------------------------------------------
# Gap candidates, override loading, and evidence reconciliation
# --------------------------------------------------------------------------

ADJUSTMENT_COLUMNS = ["symbol", "ex_date", "kind", "factor", "source", "confidence", "applied", "description"]
GAP_COLUMNS = ["symbol", "ex_date", "gap_ratio"]
OVERRIDE_COLUMNS = ["symbol", "ex_date", "factor", "note"]
_ADJUSTMENT_DTYPES = {
    "symbol": "object", "ex_date": "datetime64[ns]", "kind": "object", "factor": "float64",
    "source": "object", "confidence": "object", "applied": "bool", "description": "object",
}


def empty_adjustments_frame() -> pd.DataFrame:
    """A zero-row `ADJUSTMENT_COLUMNS` frame with explicit, correct dtypes per column.

    `pd.DataFrame(columns=ADJUSTMENT_COLUMNS)` alone gives every column `object` dtype (there
    is no data to infer from), which duckdb's pandas scanner can resolve to the wrong SQL type
    (observed: INTEGER) for an empty `price_adjustments` table -- breaking later typed queries
    (e.g. `WHERE ex_date >= DATE '...'`) once real rows are appended in a later run. Building
    the frame with real per-column dtypes up front avoids that.
    """
    return pd.DataFrame({col: pd.Series([], dtype=dtype) for col, dtype in _ADJUSTMENT_DTYPES.items()},
                        columns=ADJUSTMENT_COLUMNS)


def gap_candidates(prices: pd.DataFrame, low: float = 0.6, high: float = 1.6) -> pd.DataFrame:
    if prices is None or prices.empty:
        return pd.DataFrame(columns=GAP_COLUMNS)
    df = prices.sort_values(["symbol", "trade_date"]).copy()
    df["prev_close"] = df.groupby("symbol")["close_price"].shift(1)
    df["gap_ratio"] = df["close_price"] / df["prev_close"]
    mask = df["prev_close"].notna() & ((df["gap_ratio"] < low) | (df["gap_ratio"] > high))
    out = df.loc[mask, ["symbol", "trade_date", "gap_ratio"]].rename(columns={"trade_date": "ex_date"})
    return out.reset_index(drop=True)


def load_overrides(path: Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=OVERRIDE_COLUMNS)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    rows = []
    for item in data:
        ex_date = item.get("ex_date")
        rows.append({
            "symbol": str(item.get("symbol", "")).strip().upper(),
            "ex_date": pd.Timestamp(ex_date).normalize() if ex_date is not None else pd.NaT,
            "factor": item.get("factor"),
            "note": item.get("note", ""),
        })
    return pd.DataFrame(rows, columns=OVERRIDE_COLUMNS)


def _empty_or(df: pd.DataFrame | None, cols: list[str]) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=cols)
    return df


def _near(a, b, window_days: int) -> bool:
    if pd.isna(a) or pd.isna(b):
        return False
    return abs((pd.Timestamp(a) - pd.Timestamp(b)).days) <= window_days


def _same_factor(f1, f2, tol: float) -> bool:
    if pd.isna(f1) or pd.isna(f2) or f2 == 0:
        return False
    return abs(f1 / f2 - 1) <= tol


def _gap_agrees(gap_ratio, factor, tol: float) -> bool:
    if pd.isna(gap_ratio) or pd.isna(factor) or factor == 0:
        return False
    return abs(gap_ratio / factor - 1) <= tol


def _row(symbol, ex_date, kind, factor, source, confidence, applied, description) -> dict:
    return {"symbol": symbol, "ex_date": ex_date, "kind": kind, "factor": factor, "source": source,
            "confidence": confidence, "applied": applied, "description": description}


# A bc adjusting kind may only merge with an mcap event derived the same way: a bonus is only
# corroborated by an issue-size jump (mcap_issue); a split/consolidation only by a face-value
# change (mcap_fv). A same-day, same-factor coincidence across incompatible kinds (e.g. a bc
# split and an unrelated mcap_issue bonus) must NOT merge into one row.
_MERGE_SOURCE = {"bonus": "mcap_issue", "split": "mcap_fv", "consolidation": "mcap_fv"}


def _records_by_symbol(df: pd.DataFrame) -> dict:
    """{symbol: [(index label, row dict), ...]} in frame order -- one pass instead of a boolean
    mask over the whole frame per lookup."""
    out: dict = {}
    for idx, rec in zip(df.index, df.to_dict("records")):
        out.setdefault(rec["symbol"], []).append((idx, rec))
    return out


def _find_match(by_symbol: dict, used: set, symbol, ex_date, factor, window_days: float, factor_tol: float,
                allowed_source: str | None = None):
    """Return the index of the first unused candidate row matching symbol/date/factor, else None."""
    for idx, row in by_symbol.get(symbol, ()):
        if idx in used or (allowed_source is not None and row["source"] != allowed_source):
            continue
        if _near(ex_date, row["ex_date"], window_days) and _same_factor(factor, row["factor"], factor_tol):
            return idx
    return None


class _GapMatcher:
    """Consumes price-gap candidates as evidence for adjusting events.

    An event is gap-confirmed by an unused gap near its ex_date whose ratio agrees with the
    event's own factor, or -- failing that -- with the PRODUCT of the factors of every pooled
    (applied-candidate) event of that symbol within `window_days` of the gap. A same-day split +
    bonus (DELPHIFX 2026-02-13: split 0.2 x bonus 1/3, raw gap 0.073) moves the close by the
    combined factor, never by either one alone. A gap matched through the product is consumed
    once and confirms every event in that product.
    """

    def __init__(self, gaps: pd.DataFrame, window_days: float, gap_tol: float):
        self.records = list(zip(gaps.index, gaps.to_dict("records")))
        self.by_symbol: dict = {}
        for idx, rec in self.records:
            self.by_symbol.setdefault(rec["symbol"], []).append((idx, rec))
        self.window_days, self.gap_tol = window_days, gap_tol
        self.used: set = set()
        self.pool: dict = {}  # symbol -> [(key, ex_date, factor)]
        self.group_confirmed: set = set()

    def add_to_pool(self, key, symbol, ex_date, factor) -> None:
        if not pd.isna(factor) and not pd.isna(ex_date):
            self.pool.setdefault(symbol, []).append((key, ex_date, float(factor)))

    def _candidates(self, symbol, ex_date):
        return [(idx, g) for idx, g in self.by_symbol.get(symbol, ())
                if idx not in self.used and _near(ex_date, g["ex_date"], self.window_days)]

    def match_single(self, symbol, ex_date, factor):
        """Consume and return the first unused gap agreeing with `factor` alone, else None."""
        for idx, g in self._candidates(symbol, ex_date):
            if _gap_agrees(g["gap_ratio"], factor, self.gap_tol):
                self.used.add(idx)
                return idx
        return None

    def confirm(self, key, symbol, ex_date, factor) -> bool:
        """True if the event is gap-confirmed (own factor first, then the combined factor)."""
        if key in self.group_confirmed:
            return True
        if self.match_single(symbol, ex_date, factor) is not None:
            return True
        for idx, g in self._candidates(symbol, ex_date):
            group = [p for p in self.pool.get(symbol, ()) if _near(p[1], g["ex_date"], self.window_days)]
            if len(group) < 2 or not any(p[0] == key for p in group):
                continue
            if _gap_agrees(g["gap_ratio"], float(np.prod([p[2] for p in group])), self.gap_tol):
                self.used.add(idx)
                self.group_confirmed.update(p[0] for p in group)
                return True
        return False

    def unused(self):
        """Unconsumed gaps, in the gap frame's order."""
        return [(idx, g) for idx, g in self.records if idx not in self.used]


def _is_override_row(r: dict) -> bool:
    """True if `r` was produced or touched by `_apply_overrides` (replaced-in-place or added new)."""
    return r.get("confidence") in ("override", "suppressed") or "override" in str(r.get("source", ""))


def _dup_wins(candidate: dict, incumbent: dict) -> bool:
    """True if `candidate` should replace `incumbent` when both are applied duplicates of the
    same event (same symbol, within window_days, factors within factor_tol).

    An override (or suppression) always wins over an untouched bc/mcap/gap-derived row, since it
    is the analyst's deliberate correction. Between two override rows, the one applied later in
    the overrides list wins (tracked via `_override_rank`). Between two plain, non-override rows,
    the earlier-dated one wins (duplicate-announcement guard) -- `incumbent` is always the
    earlier-dated of the pair here, since callers process rows in ascending ex_date order.
    """
    cand_override, inc_override = _is_override_row(candidate), _is_override_row(incumbent)
    if cand_override != inc_override:
        return cand_override
    if cand_override and inc_override:
        return candidate.get("_override_rank", -1) >= incumbent.get("_override_rank", -1)
    return False


def _dedupe_duplicates(rows: list[dict], window_days: float, factor_tol: float) -> list[dict]:
    """Collapse applied duplicates of the same symbol/date-window/factor to a single row.

    Plain duplicates (e.g. two bc announcements of the same bonus) keep the earliest. An override
    or suppression always outranks a plain row regardless of date, per `_dup_wins`, so an override
    that lands within window_days/factor_tol of an untouched event isn't silently dropped by the
    "keep the earliest" rule.
    """
    by_symbol: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        if r["applied"]:
            by_symbol.setdefault(r["symbol"], []).append(i)
    drop = set()
    for idxs in by_symbol.values():
        idxs_sorted = sorted(idxs, key=lambda i: rows[i]["ex_date"])
        kept: list[int] = []
        for i in idxs_sorted:
            dup_of = next((j for j in kept if _near(rows[i]["ex_date"], rows[j]["ex_date"], window_days)
                          and _same_factor(rows[i]["factor"], rows[j]["factor"], factor_tol)), None)
            if dup_of is None:
                kept.append(i)
            elif _dup_wins(rows[i], rows[dup_of]):
                kept.remove(dup_of)
                kept.append(i)
                drop.add(dup_of)
                drop.discard(i)
            else:
                drop.add(i)
    return [r for i, r in enumerate(rows) if i not in drop]


def _closest_row(rows: list[dict], claimed: set, symbol, ex_date, window_days: float):
    """Return the index of the nearest-dated row for `symbol` within `window_days`, else None.

    Any row is eligible regardless of its current `applied` state, so an override can replace
    a previously-suppressed or not-applied row too. `claimed` excludes rows another override in
    this same call already replaced, so two overrides never collapse onto one row.
    """
    best_idx, best_delta = None, None
    for i, r in enumerate(rows):
        if i in claimed or r["symbol"] != symbol or pd.isna(r["ex_date"]):
            continue
        if not _near(ex_date, r["ex_date"], window_days):
            continue
        delta = abs((pd.Timestamp(r["ex_date"]) - pd.Timestamp(ex_date)).days)
        if best_delta is None or delta < best_delta:
            best_idx, best_delta = i, delta
    return best_idx


def _apply_overrides(rows: list[dict], overrides: pd.DataFrame, window_days: float) -> list[dict]:
    """Apply manual overrides last.

    Per ruling: an override matches an existing event (applied or not) for the same symbol whose
    ex_date falls within `window_days` -- picking the closest one -- and REPLACES that event's
    ex_date/factor/applied/confidence in place (a null factor suppresses it; otherwise it becomes
    the applied, authoritative row for that date). Only when no such event exists is the override
    appended as a brand-new row. This is what prevents an override keyed to a date that a
    duplicate-announcement guard already dropped from turning into a second, spurious applied row
    (see `reconcile`, which also re-runs the duplicate guard after overrides to guarantee this).
    `source` records provenance as "<old source>+override" when replacing, or "override" when new.

    Each touched row is tagged with `_override_rank` (its position in `overrides`, not a published
    column -- dropped when the final frame is built from `ADJUSTMENT_COLUMNS`). `_dedupe_duplicates`
    uses it to break ties between two override rows that end up within window_days/factor_tol of
    each other: the later-listed override wins.
    """
    if overrides is None or overrides.empty:
        return rows
    claimed: set = set()
    for rank, (_, o) in enumerate(overrides.iterrows()):
        if pd.isna(o["ex_date"]):
            continue
        symbol, ex_date, factor = o["symbol"], o["ex_date"], o["factor"]
        idx = _closest_row(rows, claimed, symbol, ex_date, window_days)
        suppressed = pd.isna(factor)
        if idx is not None:
            claimed.add(idx)
            r = rows[idx]
            r["ex_date"] = ex_date
            r["factor"] = float("nan") if suppressed else factor
            r["applied"] = not suppressed
            r["confidence"] = "suppressed" if suppressed else "override"
            r["source"] = f"{r['source']}+override"
            r["_override_rank"] = rank
        else:
            new_row = _row(symbol, ex_date, "override", float("nan") if suppressed else factor,
                          "override", "suppressed" if suppressed else "override",
                          not suppressed, o.get("note", ""))
            new_row["_override_rank"] = rank
            rows.append(new_row)
    return rows


REVISION_WINDOW_DAYS = 30


def collapse_revisions(bc: pd.DataFrame, window_days: int = REVISION_WINDOW_DAYS) -> pd.DataFrame:
    """Keep only the latest published version of each revised adjusting announcement.

    NSE republishes an action in successive daily bc files and sometimes revises it (GLOBE 2021:
    `BONUS1:2/FVSPLIT10TO2` ex 07-29, then `BONUS2:1/FVSPLIT10TO2` ex 07-29, then the final
    `FVSPLT FRM RS 10 TO RS 2` + `BONUS 2:1` ex 08-03). For each symbol + adjusting kind, actions
    whose ex_dates chain within `window_days` calendar days of each other form one group; only
    the action from the group's latest `published` date survives (ties on that date: the latest
    ex_date). Non-adjusting kinds are untouched. A missing `published` counts as the ex_date.
    Row order of the survivors is preserved.
    """
    if bc is None or bc.empty or PUBLISHED not in bc.columns:
        return bc
    bc = bc.reset_index(drop=True)
    ex_date = pd.to_datetime(bc["ex_date"], errors="coerce")
    published = pd.to_datetime(bc[PUBLISHED], errors="coerce").fillna(ex_date)
    adjusting = bc["kind"].isin(ADJUSTING_KINDS) & ex_date.notna()
    if not adjusting.any():
        return bc
    sub = pd.DataFrame({"symbol": bc["symbol"], "kind": bc["kind"], "ex_date": ex_date,
                        "published": published})[adjusting]
    sub = sub.sort_values(["symbol", "kind", "ex_date"], kind="stable")
    new_group = ((sub["symbol"] != sub["symbol"].shift()) | (sub["kind"] != sub["kind"].shift())
                 | (sub["ex_date"].diff().dt.days > window_days))
    sub["_group"] = new_group.cumsum()
    winners = sub.sort_values(["_group", "published", "ex_date"], kind="stable").groupby("_group").tail(1).index
    keep = ~adjusting
    keep[winners] = True
    return bc[keep]


def reconcile(bc: pd.DataFrame, mcap: pd.DataFrame, gaps: pd.DataFrame, overrides: pd.DataFrame,
             window_days: int = 5, factor_tol: float = 0.02, gap_tol: float = 0.2) -> pd.DataFrame:
    """Reconcile bc / mcap / gap evidence (plus manual overrides) into `ADJUSTMENT_COLUMNS` rows.

    When `bc` carries a `published` column, revised announcements are first collapsed to their
    latest published version (`collapse_revisions`); without it (legacy callers) every bc row is
    taken as-is.
    """
    bc = collapse_revisions(_empty_or(bc, ACTION_COLUMNS))
    bc = _empty_or(bc, ACTION_COLUMNS)
    mcap = _empty_or(mcap, ACTION_COLUMNS)
    gaps = _empty_or(gaps, GAP_COLUMNS)
    overrides = _empty_or(overrides, OVERRIDE_COLUMNS)

    bc_records = bc.to_dict("records")
    mcap_records = list(zip(mcap.index, mcap.to_dict("records")))
    mcap_by_symbol = _records_by_symbol(mcap)
    rights_dates: dict = {}
    for b in bc_records:
        if b["kind"] == "rights":
            rights_dates.setdefault(b["symbol"], []).append(b["ex_date"])
    gap_matcher = _GapMatcher(gaps, window_days, gap_tol)

    def _is_adjusting(b: dict) -> bool:
        return b["kind"] in ADJUSTING_KINDS and not pd.isna(b["factor"])

    # Pass 1: kind-safe bc<->mcap merges (independent of gap evidence), so the pool of distinct
    # applied-candidate events for combined-factor gap matching is known before any gap is used.
    mcap_used: set = set()
    merged_with: dict = {}
    for i, b in enumerate(bc_records):
        if _is_adjusting(b):
            m_idx = _find_match(mcap_by_symbol, mcap_used, b["symbol"], b["ex_date"], b["factor"], window_days,
                                factor_tol, allowed_source=_MERGE_SOURCE.get(b["kind"]))
            if m_idx is not None:
                mcap_used.add(m_idx)
                merged_with[i] = m_idx
            gap_matcher.add_to_pool(("bc", i), b["symbol"], b["ex_date"], b["factor"])
    for idx, m in mcap_records:
        if idx not in mcap_used and m["source"] == "mcap_fv":
            gap_matcher.add_to_pool(("mcap", idx), m["symbol"], m["ex_date"], m["factor"])

    # Pass 2: rows, consuming gaps in the historical order (bc rows first, then unmerged mcap).
    rows: list[dict] = []
    for i, b in enumerate(bc_records):
        symbol, ex_date, kind, factor = b["symbol"], b["ex_date"], b["kind"], b["factor"]
        description = b.get("description", "")
        if not _is_adjusting(b):
            rows.append(_row(symbol, ex_date, kind, float("nan"), "bc", "not_adjusting", False, description))
            continue
        gap_confirmed = gap_matcher.confirm(("bc", i), symbol, ex_date, factor)
        if i in merged_with:
            source = "bc+" + str(mcap.loc[merged_with[i], "source"])
            rows.append(_row(symbol, ex_date, kind, factor, source, "confirmed", True, description))
        else:
            confidence = "confirmed" if gap_confirmed else "single_source"
            rows.append(_row(symbol, ex_date, kind, factor, "bc", confidence, True, description))

    for idx, m in mcap_records:
        if idx in mcap_used:
            continue
        symbol, ex_date, kind, factor, src = m["symbol"], m["ex_date"], m["kind"], m["factor"], m["source"]
        description = m.get("description", "")
        if src == "mcap_fv":
            confidence = "confirmed" if gap_matcher.confirm(("mcap", idx), symbol, ex_date, factor) else "single_source"
            rows.append(_row(symbol, ex_date, kind, factor, "mcap_fv", confidence, True, description))
        else:  # mcap_issue
            rights_conflict = any(_near(ex_date, d, window_days) for d in rights_dates.get(symbol, ()))
            # The gap is explained either way: by the confirmed bonus, or by the conflicting
            # rights issue. Either way it should not also surface as an unexplained_gap.
            g_idx = gap_matcher.match_single(symbol, ex_date, factor)
            if g_idx is not None and not rights_conflict:
                rows.append(_row(symbol, ex_date, kind, factor, "mcap_issue", "confirmed", True, description))
            else:
                confidence = "rights_conflict" if rights_conflict else "unconfirmed"
                rows.append(_row(symbol, ex_date, kind, factor, "mcap_issue", confidence, False, description))

    for _, g in gap_matcher.unused():
        rows.append(_row(g["symbol"], g["ex_date"], "unexplained_gap", g["gap_ratio"], "gap", "unconfirmed", False, ""))

    rows = _dedupe_duplicates(rows, window_days, factor_tol)
    rows = _apply_overrides(rows, overrides, window_days)
    # Re-run the duplicate guard: an override can retarget a row's ex_date onto another applied
    # row's neighborhood, so this is what guarantees no two applied rows for the same symbol end
    # up within window_days/factor_tol of each other after overrides are in play.
    rows = _dedupe_duplicates(rows, window_days, factor_tol)

    if not rows:
        return empty_adjustments_frame()
    out = pd.DataFrame(rows, columns=ADJUSTMENT_COLUMNS)
    return out.sort_values(["symbol", "ex_date"]).reset_index(drop=True)


PRICE_COLS = ["open_price", "high_price", "low_price", "close_price", "last_price", "avg_price"]

_TRUE_STRINGS = frozenset({"true", "1", "yes"})


def _as_bool(series: pd.Series) -> pd.Series:
    """Coerce a mixed bool/str/numeric/nullable-boolean column to strict `bool`, never raising.

    Real `True`/`False` (including numpy/pandas nullable-boolean elements) pass through as-is.
    `NA`/`None`/`NaN` map to `False` (not applied, rather than crashing or silently applying).
    Numbers map via `== 1`. Strings are matched case-insensitively after stripping whitespace
    against {"true", "1", "yes"}; anything else — including the string "False" — is `False`, so
    a stray "False" can never be mistaken for truthy.
    """
    def _one(v):
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        if pd.isna(v):
            return False
        if isinstance(v, (int, float, np.integer, np.floating)):
            return float(v) == 1.0
        return str(v).strip().lower() in _TRUE_STRINGS

    return series.map(_one).astype(bool)


def _adjustment_factor_tables(adjustments: pd.DataFrame) -> dict:
    """Per-symbol (sorted ex_dates, suffix products) built from applied, factor-bearing rows.

    `suffix[i]` is the product of `factor` over events `i..n-1` (sorted by `ex_date`), with a
    trailing 1.0 appended so `suffix[n]` (no remaining events) is the identity factor.

    `applied`, `factor`, and `ex_date` are all coerced defensively (`_as_bool`, `pd.to_numeric`,
    `pd.to_datetime`, all with unparseable values mapping to False/NaN/NaT rather than raising)
    since this reads reconciled data that may carry string/nullable-boolean/non-numeric values.
    """
    applied_mask = _as_bool(adjustments["applied"])
    factor = pd.to_numeric(adjustments["factor"], errors="coerce")
    ex_date = pd.to_datetime(adjustments["ex_date"], errors="coerce")
    usable = adjustments[["symbol"]].assign(applied=applied_mask, factor=factor, ex_date=ex_date)
    usable = usable[usable["applied"] & usable["factor"].notna() & usable["ex_date"].notna()]

    tables: dict = {}
    for symbol, grp in usable.groupby("symbol"):
        grp = grp.sort_values("ex_date")
        ex_dates = grp["ex_date"].to_numpy(dtype="datetime64[ns]")
        factors = grp["factor"].to_numpy(dtype="float64")
        suffix = np.append(np.cumprod(factors[::-1])[::-1], 1.0)
        tables[symbol] = (ex_dates, suffix)
    return tables


def cumulative_price_factor(prices: pd.DataFrame, adjustments: pd.DataFrame) -> pd.Series:
    """Cumulative back-adjustment factor per price row: product of `factor` over applied events
    of that row's symbol with `ex_date > trade_date`; 1.0 when no such events exist.

    Vectorised: grouped once per symbol (via `DataFrame.groupby(...).indices`, O(n)), then a
    `numpy.searchsorted` against that symbol's sorted ex_dates locates each row's suffix-product
    lookup — no per-row Python loop over the (potentially multi-million-row) price table.
    """
    tables = _adjustment_factor_tables(adjustments)
    result = np.ones(len(prices), dtype="float64")
    if tables:
        trade_dates = prices["trade_date"].to_numpy(dtype="datetime64[ns]")
        positions_by_symbol = prices.groupby("symbol").indices
        for symbol, (ex_dates, suffix) in tables.items():
            positions = positions_by_symbol.get(symbol)
            if positions is None or len(positions) == 0:
                continue
            positions = np.asarray(positions)
            idx = np.searchsorted(ex_dates, trade_dates[positions], side="right")
            result[positions] = suffix[idx]
    return pd.Series(result, index=prices.index, name="price_factor")


def drop_stale_adjustment_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop any pre-existing `adj_*`/`price_factor` columns from `df`.

    Shared by `apply_adjustments` (so re-applying is idempotent) and by callers that reload a
    previously-adjusted `prices_daily` frame (e.g. `append_database`, before merging in new
    rows and recomputing adjustments from scratch).
    """
    stale = [c for c in df.columns if c.startswith("adj_") or c == "price_factor"]
    return df.drop(columns=stale) if stale else df


def apply_adjustments(prices: pd.DataFrame, adjustments: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `prices` with cumulative `price_factor`, `adj_<col>` for each present
    column of `PRICE_COLS`, `adj_volume`, `adj_delivery_qty` (when `delivery_qty` is present),
    and `adj_prev_close`.

    `adj_prev_close` is the previous row's `adj_close_price` within the same symbol (rows
    ordered by `trade_date`); the first row per symbol falls back to `prev_close * price_factor`
    when `prev_close` is present, else stays `NaN`. Any pre-existing `adj_*`/`price_factor`
    columns are dropped first so re-applying is idempotent (same output columns, freshly
    recomputed from the raw OHLCV columns).

    `last_price`, `avg_price`, `delivery_qty`, and `prev_close` are optional: columns absent
    from `prices` are simply skipped rather than raising `KeyError`. `prices.index` may contain
    duplicate labels — this works on a positional copy internally and restores the original
    index (including any duplicates) on the returned frame, in the original row order.
    """
    orig_index = prices.index
    df = drop_stale_adjustment_columns(prices).reset_index(drop=True)

    factor = cumulative_price_factor(df, adjustments)
    df["price_factor"] = factor.astype("float64")

    for col in PRICE_COLS:
        if col in df.columns:
            df[f"adj_{col}"] = (df[col].astype("float64") * df["price_factor"]).astype("float64")
    if "volume" in df.columns:
        df["adj_volume"] = (df["volume"].astype("float64") / df["price_factor"]).astype("float64")
    if "delivery_qty" in df.columns:
        df["adj_delivery_qty"] = (df["delivery_qty"].astype("float64") / df["price_factor"]).astype("float64")

    if "adj_close_price" in df.columns:
        ordered = df.sort_values(["symbol", "trade_date"], kind="stable")
        prev_adj_close = ordered.groupby("symbol")["adj_close_price"].shift(1)
        if "prev_close" in df.columns:
            first_row_fill = ordered["prev_close"].astype("float64") * ordered["price_factor"]
            adj_prev_close = prev_adj_close.fillna(first_row_fill)
        else:
            adj_prev_close = prev_adj_close
        df["adj_prev_close"] = adj_prev_close.reindex(df.index).astype("float64")

    df.index = orig_index
    return df


def _rename_symbols(df: pd.DataFrame, changes: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """Rename `df["symbol"]` per the symbol-change history, keyed on `df[date_col]`.

    This deliberately re-implements just the renaming half of `universe.apply_symbol_changes`
    rather than calling it: that helper also drop_duplicates(["symbol", "trade_date"], keep="first")
    to collapse same-day price rows, which is correct for OHLCV rows but would silently discard a
    second, distinct corporate action (or mcap snapshot) landing on the same symbol/date -- these
    frames are keyed on more than just (symbol, date). Renaming here with no merge/dedupe step
    avoids that data loss.

    `date_col` is `"ex_date"` for action frames (bc/mcap-derived events) and `"file_date"` for
    the raw mcap snapshot frame (so a symbol's mcap history stays one continuous series across a
    rename, instead of being split into two unrelated per-symbol groups in `actions_from_mcap`).
    """
    if changes is None or changes.empty or df is None or df.empty:
        return df
    out = df.copy()
    ordered = changes.sort_values("change_date", na_position="last")
    for _, row in ordered.iterrows():
        old, new, change_date = row["old_symbol"], row["new_symbol"], row["change_date"]
        mask = out["symbol"] == old
        if pd.notna(change_date):
            mask &= out[date_col] < change_date
        out.loc[mask, "symbol"] = new
    return out.reset_index(drop=True)


def _suppress_future_ex_dates(adjustments: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Un-apply any applied event dated after its symbol's most recent session in `prices`.

    NSE corporate-action text can be filed with an ex_date that hasn't happened yet as of the
    price history on hand (e.g. announced ahead of time). Applying such an event today would
    back-adjust the *entire* price history for that symbol before the event has actually taken
    effect. Symbols absent from `prices` (no known last session) are left untouched -- there is
    nothing to compare the ex_date against.
    """
    if adjustments is None or adjustments.empty:
        return adjustments
    out = adjustments.copy()
    if prices is None or prices.empty:
        return out
    last_session = prices.groupby("symbol")["trade_date"].max()
    applied = _as_bool(out["applied"])
    ex_date = pd.to_datetime(out["ex_date"], errors="coerce")
    symbol_last_session = out["symbol"].map(last_session)
    future = applied & symbol_last_session.notna() & (ex_date > symbol_last_session)
    out.loc[future, "applied"] = False
    out.loc[future, "confidence"] = "pending_ex_date"
    return out


def adjust_prices(prices: pd.DataFrame, root: Path,
                  extra_actions: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Detect split/bonus/consolidation events from official NSE data under `root`, reconcile
    them against `prices`, and return `(adjusted_prices, adjustments)`.

    `extra_actions` (e.g. the live `corporate_actions` table, re-parsed via
    `actions_from_corporate_actions_table`) is merged into the bc-sourced actions before symbol
    renaming and reconciliation, de-duplicated on `(symbol, ex_date, description)` same as
    `collect_bc_actions`.
    """
    root = Path(root)
    zips = find_pr_zips(root)
    bc = collect_bc_actions(zips)
    if extra_actions is not None and not extra_actions.empty:
        extra = extra_actions[[c for c in BC_ACTION_COLUMNS if c in extra_actions.columns]]
        bc = _dedupe_bc_actions(pd.concat([bc, extra], ignore_index=True))
    mcap_frames = read_mcap_frames(root, zips)

    changes_path = root / "Input" / "reference" / "symbolchange.csv"
    if changes_path.exists():
        from symbol_changes import parse_symbol_changes
        changes = parse_symbol_changes(changes_path)
        bc = _rename_symbols(bc, changes, "ex_date")
        # Rename the raw mcap snapshot rows (keyed on each row's own file_date) *before*
        # actions_from_mcap groups by symbol, so a symbol's mcap history isn't split into two
        # unrelated groups across a rename that straddles it.
        mcap_frames = _rename_symbols(mcap_frames, changes, "file_date")

    mcap = actions_from_mcap(mcap_frames)

    gaps = gap_candidates(prices)
    overrides = load_overrides(root / "Input" / "reference" / "adjustments_override.yaml")
    adjustments = reconcile(bc, mcap, gaps, overrides)
    adjustments = _suppress_future_ex_dates(adjustments, prices)
    return apply_adjustments(prices, adjustments), adjustments


def summarize_adjustments(adjustments: pd.DataFrame) -> str:
    """One-line human summary of a reconciled adjustments frame, printed by both the full build
    and the daily append after `adjust_prices` runs."""
    if adjustments is None or adjustments.empty:
        return "Price adjustments: 0 applied (0 confirmed), 0 unconfirmed gaps, 0 non-adjusting actions"
    applied = _as_bool(adjustments["applied"])
    n_applied = int(applied.sum())
    n_confirmed = int((adjustments["confidence"] == "confirmed").sum())
    n_unconfirmed_gaps = int((adjustments["kind"] == "unexplained_gap").sum())
    n_not_adjusting = int((adjustments["confidence"] == "not_adjusting").sum())
    return (f"Price adjustments: {n_applied} applied ({n_confirmed} confirmed), "
            f"{n_unconfirmed_gaps} unconfirmed gaps, {n_not_adjusting} non-adjusting actions")


def indicator_input(adjusted: pd.DataFrame) -> pd.DataFrame:
    """Copy of `adjusted` where each present column among `PRICE_COLS`, `prev_close`, `volume`,
    `delivery_qty` is replaced by its `adj_` counterpart (columns whose `adj_` counterpart is
    absent are left untouched), and all `adj_*` columns are dropped — giving `calc_indicators`
    a frame with the usual (unprefixed) OHLCV column names.

    `price_factor` is deliberately *kept* (not dropped): `calc_indicators` needs it to rescale
    the raw, NSE-reported 52-week high/low (which are never back-adjusted) onto the same
    adjusted-price scale as the OHLCV columns above, before computing `away_52w_high_pct` and
    everything derived from it.
    """
    df = adjusted.copy()
    swap = {**{col: f"adj_{col}" for col in PRICE_COLS},
            "prev_close": "adj_prev_close",
            "volume": "adj_volume",
            "delivery_qty": "adj_delivery_qty"}
    for target, source in swap.items():
        if source in df.columns:
            df[target] = df[source].astype("float64")

    drop_cols = [c for c in df.columns if c.startswith("adj_")]
    return df.drop(columns=drop_cols)
