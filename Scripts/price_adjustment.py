"""Split / bonus / consolidation price adjustment from official NSE data."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

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


def _find_match(candidates: pd.DataFrame, used: set, symbol, ex_date, factor, window_days: float, factor_tol: float,
                allowed_source: str | None = None):
    """Return the index of the first unused candidate row matching symbol/date/factor, else None."""
    pool = candidates[candidates["symbol"] == symbol]
    if allowed_source is not None:
        pool = pool[pool["source"] == allowed_source]
    for idx, row in pool.iterrows():
        if idx in used:
            continue
        if _near(ex_date, row["ex_date"], window_days) and _same_factor(factor, row["factor"], factor_tol):
            return idx
    return None


def _find_gap_match(gaps: pd.DataFrame, used: set, symbol, ex_date, factor, window_days: float, gap_tol: float):
    for idx, row in gaps[gaps["symbol"] == symbol].iterrows():
        if idx in used:
            continue
        if _near(ex_date, row["ex_date"], window_days) and _gap_agrees(row["gap_ratio"], factor, gap_tol):
            return idx
    return None


def _has_bc_rights(bc: pd.DataFrame, symbol, ex_date, window_days: float) -> bool:
    rights = bc[(bc["symbol"] == symbol) & (bc["kind"] == "rights")]
    return any(_near(ex_date, r["ex_date"], window_days) for _, r in rights.iterrows())


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


def reconcile(bc: pd.DataFrame, mcap: pd.DataFrame, gaps: pd.DataFrame, overrides: pd.DataFrame,
             window_days: int = 5, factor_tol: float = 0.02, gap_tol: float = 0.2) -> pd.DataFrame:
    bc = _empty_or(bc, ACTION_COLUMNS)
    mcap = _empty_or(mcap, ACTION_COLUMNS)
    gaps = _empty_or(gaps, GAP_COLUMNS)
    overrides = _empty_or(overrides, OVERRIDE_COLUMNS)

    mcap_used: set = set()
    gap_used: set = set()
    rows: list[dict] = []

    for _, b in bc.iterrows():
        symbol, ex_date, kind, factor = b["symbol"], b["ex_date"], b["kind"], b["factor"]
        description = b.get("description", "")
        if kind in ADJUSTING_KINDS and not pd.isna(factor):
            m_idx = _find_match(mcap, mcap_used, symbol, ex_date, factor, window_days, factor_tol,
                                allowed_source=_MERGE_SOURCE.get(kind))
            if m_idx is not None:
                mcap_used.add(m_idx)
                source = "bc+" + str(mcap.loc[m_idx, "source"])
                g_idx = _find_gap_match(gaps, gap_used, symbol, ex_date, factor, window_days, gap_tol)
                if g_idx is not None:
                    gap_used.add(g_idx)
                rows.append(_row(symbol, ex_date, kind, factor, source, "confirmed", True, description))
            else:
                g_idx = _find_gap_match(gaps, gap_used, symbol, ex_date, factor, window_days, gap_tol)
                if g_idx is not None:
                    gap_used.add(g_idx)
                    confidence = "confirmed"
                else:
                    confidence = "single_source"
                rows.append(_row(symbol, ex_date, kind, factor, "bc", confidence, True, description))
        else:
            rows.append(_row(symbol, ex_date, kind, float("nan"), "bc", "not_adjusting", False, description))

    for idx, m in mcap.iterrows():
        if idx in mcap_used:
            continue
        symbol, ex_date, kind, factor, src = m["symbol"], m["ex_date"], m["kind"], m["factor"], m["source"]
        description = m.get("description", "")
        if src == "mcap_fv":
            g_idx = _find_gap_match(gaps, gap_used, symbol, ex_date, factor, window_days, gap_tol)
            if g_idx is not None:
                gap_used.add(g_idx)
                confidence = "confirmed"
            else:
                confidence = "single_source"
            rows.append(_row(symbol, ex_date, kind, factor, "mcap_fv", confidence, True, description))
        else:  # mcap_issue
            rights_conflict = _has_bc_rights(bc, symbol, ex_date, window_days)
            g_idx = _find_gap_match(gaps, gap_used, symbol, ex_date, factor, window_days, gap_tol)
            if g_idx is not None:
                # The gap is explained either way: by the confirmed bonus, or by the conflicting
                # rights issue. Either way it should not also surface as an unexplained_gap.
                gap_used.add(g_idx)
            if g_idx is not None and not rights_conflict:
                rows.append(_row(symbol, ex_date, kind, factor, "mcap_issue", "confirmed", True, description))
            else:
                confidence = "rights_conflict" if rights_conflict else "unconfirmed"
                rows.append(_row(symbol, ex_date, kind, factor, "mcap_issue", confidence, False, description))

    for idx, g in gaps.iterrows():
        if idx in gap_used:
            continue
        rows.append(_row(g["symbol"], g["ex_date"], "unexplained_gap", g["gap_ratio"], "gap", "unconfirmed", False, ""))

    rows = _dedupe_duplicates(rows, window_days, factor_tol)
    rows = _apply_overrides(rows, overrides, window_days)
    # Re-run the duplicate guard: an override can retarget a row's ex_date onto another applied
    # row's neighborhood, so this is what guarantees no two applied rows for the same symbol end
    # up within window_days/factor_tol of each other after overrides are in play.
    rows = _dedupe_duplicates(rows, window_days, factor_tol)

    out = pd.DataFrame(rows, columns=ADJUSTMENT_COLUMNS)
    return out.sort_values(["symbol", "ex_date"]).reset_index(drop=True)
