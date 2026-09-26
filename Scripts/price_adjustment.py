"""Split / bonus / consolidation price adjustment from official NSE data."""
from __future__ import annotations

import csv
import io
import os
import pickle
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
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


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%d-%m-%Y")


def _parse_dates(values: pd.Series) -> pd.Series:
    """Parse bc date strings (any of `_DATE_FORMATS`, surrounding whitespace ignored).

    Vectorised: each format is tried column-wise (`errors="coerce"`) and the results combined
    with `combine_first`, over the distinct strings only (bc dates repeat a lot) -- replacing a
    per-row, per-format `pd.to_datetime` loop that took ~2.5 minutes on the real bc history.
    Returns a `datetime64[ns]` series aligned with `values` (NaT where nothing parses)."""
    text = values.fillna("").astype(str).str.strip()
    uniq = pd.Series(pd.unique(text.to_numpy(dtype=object)), dtype=object)
    parsed = pd.Series(pd.NaT, index=uniq.index, dtype="datetime64[ns]")
    for fmt in _DATE_FORMATS:
        missing = parsed.isna()
        if not missing.any():
            break
        attempt = pd.to_datetime(uniq[missing], format=fmt, errors="coerce").astype("datetime64[ns]")
        parsed = parsed.combine_first(attempt)
    lookup = pd.Series(parsed.dt.normalize().to_numpy(), index=uniq.to_numpy())
    return pd.Series(lookup.reindex(text.to_numpy()).to_numpy(), index=values.index, dtype="datetime64[ns]")


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


def _expand_actions(events: pd.DataFrame, source: str) -> pd.DataFrame:
    """`events` (symbol, ex_date, description[, extra columns]) -> one row per parsed action.

    A multi-action purpose ("BONUS2:1/FVSPLIT10TO2") expands into several rows sharing symbol,
    ex_date, description, source and any extra column (e.g. `published`). Rows without a symbol
    or ex_date are dropped. Each distinct description is parsed once.
    """
    extra = [c for c in events.columns if c not in ("symbol", "ex_date", "description")]
    columns = ACTION_COLUMNS + extra
    events = events[events["symbol"].fillna("").astype(str).ne("") & events["ex_date"].notna()]
    if events.empty:
        return pd.DataFrame(columns=columns)
    descriptions = pd.unique(events["description"].to_numpy(dtype=object))
    parsed = [(d, i, act.kind, act.factor) for d in descriptions for i, act in enumerate(parse_purpose_all(d))]
    table = pd.DataFrame(parsed, columns=["description", "_order", "kind", "factor"])
    table["factor"] = table["factor"].astype("float64")
    out = events.reset_index(drop=True).reset_index(names="_row").merge(table, on="description", how="left")
    out = out.sort_values(["_row", "_order"], kind="stable")
    out["source"] = source
    return out[columns].reset_index(drop=True)


def _action_rows(symbols, ex_dates, purposes, source: str) -> pd.DataFrame:
    """One row per parsed action: a multi-action purpose ("BONUS2:1/FVSPLIT10TO2") expands into
    several rows sharing symbol, ex_date, description and source."""
    events = pd.DataFrame({"symbol": list(symbols), "ex_date": pd.to_datetime(pd.Series(list(ex_dates), dtype=object)),
                           "description": [str(p).strip() for p in purposes]})
    return _expand_actions(events, source)


_BC_DATE_KEYS = ("EX_DT", "RECORD_DT", "BC_STRT_DT")
_BC_RAW_COLUMNS = ["SYMBOL", *_BC_DATE_KEYS, "PURPOSE"]


def _bc_raw_rows(raw: pd.DataFrame) -> pd.DataFrame:
    """Series-filtered bc rows, still as strings (`_BC_RAW_COLUMNS`; absent columns -> "").

    This cheap per-file step is what the parse cache stores; date parsing and purpose parsing run
    once over all files' rows together (`_bc_events`), so neither pays per-file pandas overhead
    and purpose-parsing changes never need a cache rebuild.
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=_BC_RAW_COLUMNS)
    df = raw.rename(columns=lambda c: str(c).strip().upper())
    df = df[df.get("SERIES", pd.Series("", index=df.index)).astype(str).str.strip().str.upper().isin(_ACTION_SERIES)]
    if df.empty or "SYMBOL" not in df.columns or "PURPOSE" not in df.columns:
        return pd.DataFrame(columns=_BC_RAW_COLUMNS)
    return pd.DataFrame({c: (df[c].fillna("").astype(str) if c in df.columns else "") for c in _BC_RAW_COLUMNS},
                        index=df.index).reset_index(drop=True)


def _bc_events(rows: pd.DataFrame) -> pd.DataFrame:
    """`_bc_raw_rows` output -> (symbol, ex_date, description[, extra columns]); ex_date is the
    first of EX_DT / RECORD_DT / BC_STRT_DT that parses. Rows without symbol or date are dropped."""
    extra = [c for c in rows.columns if c not in _BC_RAW_COLUMNS]
    if rows.empty:
        return pd.DataFrame(columns=["symbol", "ex_date", "description", *extra])
    ex = pd.Series(pd.NaT, index=rows.index, dtype="datetime64[ns]")
    for key in _BC_DATE_KEYS:
        missing = ex.isna()
        if missing.any():
            ex = ex.combine_first(_parse_dates(rows.loc[missing, key]))
    out = pd.DataFrame({"symbol": rows["SYMBOL"].astype(str).str.strip().str.upper(), "ex_date": ex,
                        "description": rows["PURPOSE"].astype(str).str.strip()})
    for c in extra:
        out[c] = rows[c]
    out = out[out["symbol"].ne("") & out["ex_date"].notna()]
    return out.reset_index(drop=True)


def actions_from_bc_frame(raw: pd.DataFrame) -> pd.DataFrame:
    return _expand_actions(_bc_events(_bc_raw_rows(raw)), "bc")


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


def _first_published(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """One row per `keys`, keeping the FIRST-published copy (missing `published` -> ex_date).

    NSE republishes the same announcement in successive daily bc files; the date a version first
    appeared is when it superseded any earlier version, so that is the `published` date kept.
    Survivors keep their original relative order.
    """
    if frame.empty:
        return frame.reset_index(drop=True)
    out = frame.copy()
    if PUBLISHED not in out.columns:
        out[PUBLISHED] = pd.NaT
    ex_date = pd.to_datetime(out["ex_date"], errors="coerce")
    out[PUBLISHED] = pd.to_datetime(out[PUBLISHED], errors="coerce").fillna(ex_date).astype("datetime64[ns]")
    out = out.sort_values(PUBLISHED, kind="stable", na_position="last").drop_duplicates(keys)
    return out.sort_index().reset_index(drop=True)


def _dedupe_bc_actions(actions: pd.DataFrame) -> pd.DataFrame:
    """One row per (symbol, ex_date, description, kind), keeping the first-published copy."""
    return _first_published(actions, ["symbol", "ex_date", "description", "kind"])


# --------------------------------------------------------------------------
# Per-file source parsing with an optional on-disk cache
# --------------------------------------------------------------------------

_MCAP_COLUMNS = ["file_date", "symbol", "face_value", "issue_size"]
# Bump whenever the per-file parse output (`_parse_pr_zip` / `_parse_mcap_csv`) changes shape
# or meaning: every existing cache entry then reads as stale and is rebuilt.
_CACHE_VERSION = 1


class _DefaultCacheDir:
    """Sentinel for `adjust_prices(cache_dir=...)`: use `default_cache_dir(root)`."""

    def __repr__(self) -> str:
        return "<root>/Input/archive/.adjust_cache"


DEFAULT_CACHE_DIR = _DefaultCacheDir()


def default_cache_dir(root: Path) -> Path:
    """Where `adjust_prices` caches per-file parses by default (git-ignored with Input/archive/)."""
    return Path(root) / "Input" / "archive" / ".adjust_cache"


def _parse_pr_zip(path: Path) -> dict:
    """Open a PR zip ONCE and parse both its bc member (as `_bc_events` rows) and any mcap
    member(s). `skipped` counts malformed bc lines dropped while parsing."""
    with zipfile.ZipFile(path) as zf:
        raw = read_bc_member(zf)
        mcap = [_mcap_frame(zf.read(n).decode("utf-8-sig", errors="replace")) for n in zf.namelist()
                if Path(n).name.lower().startswith("mcap") and n.lower().endswith(".csv")]
    return {"bc": _bc_raw_rows(raw), "skipped": int(raw.attrs.get("skipped_lines", 0)),
            "mcap": pd.concat(mcap, ignore_index=True) if mcap else pd.DataFrame(columns=_MCAP_COLUMNS)}


def _parse_mcap_csv(path: Path) -> dict:
    return {"mcap": _mcap_frame(Path(path).read_text(encoding="utf-8-sig", errors="replace"))}


_CACHE_STORE = "parse_cache.pkl"
_PARSE_WORKERS = min(8, os.cpu_count() or 1)


def _read_cache_entry(store_file: Path):
    with open(store_file, "rb") as fh:
        return pickle.load(fh)


def _write_cache_entry(store_file: Path, store) -> None:
    store_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = store_file.with_name(store_file.name + f".{os.getpid()}.tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(store, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, store_file)  # atomic: readers never see a half-written store


class _ParseCache:
    """Per-file parse cache: one entry per source file, keyed by file name + size + mtime.

    All entries live in ONE pickle (`<cache_dir>/parse_cache.pkl`) rather than one file per
    source: on this Windows box the first open of each freshly written file costs ~20 ms
    (on-access scanning), so 1,900 small entry files made the first warm run ~100 s, while one
    ~95 MB store reads in ~2 s. Semantics are still per file: a missing or stale entry (size /
    mtime / cache-version mismatch) is re-parsed on its own; an unreadable or corrupt store is
    ignored and rebuilt. `cache_dir=None` disables caching entirely -- no reads, no writes.
    Entries whose source file no longer exists are dropped when the store is rewritten.
    """

    def __init__(self, cache_dir: Path | None):
        self.store_file = None if cache_dir is None else Path(cache_dir) / _CACHE_STORE
        self.entries: dict = {}
        self.dirty = False
        if self.store_file is None:
            return
        try:
            store = _read_cache_entry(self.store_file)
            if isinstance(store, dict) and store.get("version") == _CACHE_VERSION and isinstance(store.get("entries"), dict):
                self.entries = store["entries"]
        except Exception:  # noqa: BLE001 - missing/corrupt/incompatible store: start empty
            self.entries = {}

    @staticmethod
    def _entry_key(path: Path) -> str:
        # The same file name can live in several input dirs (archive, backfill, downloads/...).
        return os.path.normcase(os.path.abspath(path))

    def load_many(self, paths: list[Path], parser) -> list:
        """`[parser(p) or its cached result, ...]` in `paths` order; a failure is returned as the
        exception object (for the caller to report or re-raise) instead of being raised.

        Cache misses are parsed on a small thread pool. The first open of a file that on-access
        scanning hasn't seen yet costs ~36 ms per PR zip here when done one at a time vs ~3 ms
        with 8 threads (measured on 250 fresh copies of real zips), and a cold run opens 1,749
        of them. Cache bookkeeping stays on the calling thread.
        """
        results: list = [None] * len(paths)
        misses: list[tuple[int, tuple | None]] = []
        for i, p in enumerate(paths):
            if self.store_file is None:
                misses.append((i, None))
                continue
            try:
                st = Path(p).stat()
            except OSError as exc:
                results[i] = exc
                continue
            key = (_CACHE_VERSION, Path(p).name, st.st_size, st.st_mtime_ns)
            entry = self.entries.get(self._entry_key(p))
            if isinstance(entry, dict) and entry.get("key") == key and isinstance(entry.get("data"), dict):
                results[i] = entry["data"]
            else:
                misses.append((i, key))
        if not misses:
            return results

        def _run(p):
            try:
                return parser(p)
            except Exception as exc:  # noqa: BLE001 - handed back to the caller
                return exc

        miss_paths = [paths[i] for i, _ in misses]
        workers = min(_PARSE_WORKERS, len(misses))
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                parsed = list(pool.map(_run, miss_paths))
        else:
            parsed = [_run(p) for p in miss_paths]
        for (i, key), data in zip(misses, parsed):
            results[i] = data
            if key is not None and isinstance(data, dict):
                self.entries[self._entry_key(paths[i])] = {"key": key, "data": data}
                self.dirty = True
        return results

    def save(self) -> None:
        if self.store_file is None or not self.dirty:
            return
        self.entries = {k: v for k, v in self.entries.items() if os.path.exists(k)}
        try:
            _write_cache_entry(self.store_file, {"version": _CACHE_VERSION, "entries": self.entries})
            self.dirty = False
        except OSError as exc:  # a cache write failure never fails the run
            print(f"Warning: could not write price-adjustment parse cache {self.store_file}: {exc}")


def _load_pr_zips(zip_paths: list[Path], cache: _ParseCache) -> list[tuple[Path, dict]]:
    """Parse (or load from cache) every PR zip once; unreadable zips are reported and skipped."""
    paths = [Path(p) for p in zip_paths]
    entries = []
    for p, result in zip(paths, cache.load_many(paths, _parse_pr_zip)):
        if isinstance(result, (zipfile.BadZipFile, OSError, pd.errors.ParserError)):
            print(f"Skipped {p.name}: {result}")
        elif isinstance(result, Exception):
            # One line the EOD status log can show, before the traceback.
            print(f"PRICE ADJUSTMENT FAILED: {p.name}: {type(result).__name__}: {result}", flush=True)
            raise result
        else:
            entries.append((p, result))
    return entries


def _bc_actions_from_entries(entries: list[tuple[Path, dict]]) -> pd.DataFrame:
    frames, published = [], []
    for path, data in entries:
        _warn_skipped_lines(path.name, data.get("skipped", 0))
        bc = data.get("bc")
        if bc is not None and not bc.empty:
            frames.append(bc)
            published.append(np.repeat(published_date_from_zip_name(path.name).to_datetime64(), len(bc)))
    if not frames:
        return pd.DataFrame(columns=BC_ACTION_COLUMNS)
    rows = pd.concat(frames, ignore_index=True)
    rows[PUBLISHED] = np.concatenate(published).astype("datetime64[ns]")
    events = _first_published(_bc_events(rows), ["symbol", "ex_date", "description"])
    return _expand_actions(events, "bc")


def collect_bc_actions(zip_paths: list[Path], cache_dir: Path | None = None) -> pd.DataFrame:
    """bc actions from every PR zip (`BC_ACTION_COLUMNS`: `ACTION_COLUMNS` + `published`), one
    row per (symbol, ex_date, description, kind) with its first-published date."""
    cache = _ParseCache(cache_dir)
    try:
        return _bc_actions_from_entries(_load_pr_zips(zip_paths, cache))
    finally:
        cache.save()


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


def _norm_col(c) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_")


def _mcap_frame(text: str) -> pd.DataFrame:
    """One mcap CSV -> (file_date, symbol, face_value, issue_size), summary rows (blank series)
    dropped. Only the needed columns are read; numbers are parsed by the C reader (falling back
    to a coercing string parse if a numeric column holds junk); the trade date -- one value per
    file -- is parsed over its distinct strings only."""
    header = next(csv.reader(io.StringIO(text.split("\n", 1)[0])), [])
    want: dict[str, int] = {}
    for i, name in enumerate(_norm_col(c) for c in header):
        key = ("face_value" if name.startswith("face_value") else "issue_size" if name.startswith("issue_size")
               else name if name in ("trade_date", "symbol", "series") else None)
        if key is not None:
            want.setdefault(key, i)
    if not {"trade_date", "symbol", "face_value", "issue_size"} <= want.keys():
        return pd.DataFrame(columns=_MCAP_COLUMNS)
    names = {i: k for k, i in want.items()}
    usecols = sorted(names)
    text_cols = {want[k]: str for k in ("trade_date", "symbol", "series") if k in want}
    try:
        df = pd.read_csv(io.StringIO(text), usecols=usecols, skipinitialspace=True, thousands=",",
                         dtype={**text_cols, want["face_value"]: "float64", want["issue_size"]: "float64"})
        df.columns = [names[i] for i in usecols]
    except ValueError:
        df = pd.read_csv(io.StringIO(text), usecols=usecols, skipinitialspace=True, dtype=str)
        df.columns = [names[i] for i in usecols]
        for col in ("face_value", "issue_size"):
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "").str.strip(), errors="coerce")
    if "series" in df.columns:
        df = df[df["series"].fillna("").astype(str).str.strip() != ""]
    dates = df["trade_date"].fillna("").astype(str).str.strip()
    uniq = pd.unique(dates.to_numpy(dtype=object))
    parsed = pd.Series(pd.to_datetime(pd.Series(uniq, dtype=object), format="%d %b %Y", errors="coerce")
                       .astype("datetime64[ns]").to_numpy(), index=uniq)
    return pd.DataFrame({
        "file_date": parsed.reindex(dates.to_numpy()).to_numpy(),
        "symbol": df["symbol"].astype(str).str.strip().str.upper().to_numpy(),
        "face_value": df["face_value"].astype("float64").to_numpy(),
        "issue_size": df["issue_size"].astype("float64").to_numpy(),
    }).dropna(subset=["file_date"]).reset_index(drop=True)


def _mcap_csv_paths(root: Path) -> list[Path]:
    """Loose mcap CSVs, ordered so duplicate copies like "mcap04082026 (2).csv" come before the
    canonical "mcap04082026.csv" (de-duplication with keep="last" then keeps the canonical)."""
    root = Path(root)
    paths = set((root / "Input" / "archive").glob("mcap*.csv")) | set((root / "Input" / "daily").glob("mcap*.csv"))
    downloads = root / "Input" / "downloads"
    if downloads.exists():
        paths |= set(downloads.rglob("mcap*.csv"))
    return sorted(paths, key=lambda x: (" (" not in x.name, x.name))


def _mcap_frames_from(root: Path, zip_entries: list[tuple[Path, dict]], cache: _ParseCache) -> pd.DataFrame:
    frames = []
    csv_paths = _mcap_csv_paths(root)
    for p, result in zip(csv_paths, cache.load_many(csv_paths, _parse_mcap_csv)):
        if isinstance(result, Exception):  # one bad loose CSV must not stop the run
            print(f"Skipped {Path(p).name}: {result}")
        else:
            frames.append(result["mcap"])
    frames.extend(data["mcap"] for _, data in zip_entries if data.get("mcap") is not None and not data["mcap"].empty)
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=_MCAP_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(["file_date", "symbol"], keep="last")
    return out.sort_values(["symbol", "file_date"], kind="stable").reset_index(drop=True)


def read_mcap_frames(root: Path, zip_paths: list[Path], cache_dir: Path | None = None) -> pd.DataFrame:
    """Every mcap snapshot row (loose CSVs + PR-zip members), one per (file_date, symbol)."""
    cache = _ParseCache(cache_dir)
    try:
        return _mcap_frames_from(root, _load_pr_zips(zip_paths, cache), cache)
    finally:
        cache.save()


def actions_from_mcap(frames: pd.DataFrame, tol: float = 0.01) -> pd.DataFrame:
    """Face-value changes (mcap_fv) and clean issue-size multiples (mcap_issue) between each
    symbol's consecutive valid snapshots (rows with a NaN face value / issue size are skipped;
    a snapshot is only compared with a predecessor that has a positive face value and issue size).

    Vectorised: sort + `groupby.shift` instead of a per-row loop.
    """
    if frames is None or frames.empty:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    f = frames.dropna(subset=["face_value", "issue_size"]).sort_values(["symbol", "file_date"], kind="stable")
    if f.empty:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    grouped = f.groupby("symbol", sort=False)
    prev_fv = grouped["face_value"].shift(1).to_numpy(dtype="float64")
    prev_is = grouped["issue_size"].shift(1).to_numpy(dtype="float64")
    cur_fv = f["face_value"].to_numpy(dtype="float64")
    cur_is = f["issue_size"].to_numpy(dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        valid = (prev_fv > 0) & (prev_is > 0)  # NaN (no predecessor) compares False
        fv_change = valid & (cur_fv != prev_fv)
        ratio = cur_is / prev_is
        match = np.full(len(f), np.nan)
        for c in reversed(CLEAN_BONUS_RATIOS):  # reversed: the first ratio in tuple order wins
            match = np.where(np.abs(ratio / c - 1) <= tol, c, match)
    bonus = valid & ~fv_change & ~np.isnan(match)
    event = fv_change | bonus
    if not event.any():
        return pd.DataFrame(columns=ACTION_COLUMNS)
    idx = np.flatnonzero(event)
    fv_factor = cur_fv[idx] / prev_fv[idx]
    is_fv = fv_change[idx]
    factor = np.where(is_fv, fv_factor, 1 / match[idx])
    kind = np.where(is_fv, np.where(fv_factor > 1, "consolidation", "split"), "bonus")
    description = [f"FV {p}->{c}" if fv else f"ISSUE x{m:.2f}"
                   for fv, p, c, m in zip(is_fv, prev_fv[idx], cur_fv[idx], match[idx])]
    return pd.DataFrame({
        "symbol": f["symbol"].to_numpy()[idx],
        "ex_date": f["file_date"].to_numpy()[idx],
        "kind": kind.astype(object),
        "factor": factor.astype("float64"),
        "description": description,
        "source": np.where(is_fv, "mcap_fv", "mcap_issue").astype(object),
    }, columns=ACTION_COLUMNS)


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


_KIND_FAMILY = {"bonus": "bonus", "split": "face_value", "consolidation": "face_value"}


def _kinds_compatible(k1, k2) -> bool:
    """Two applied rows can only be duplicates of one event if they're the same kind of event: a
    same-day split and bonus with coinciding factors (CGCL 2024-03-05: FV 2 -> 1 and BONUS 1:1,
    both 0.5) are two real events. A brand-new override row (kind "override") matches any kind."""
    f1, f2 = _KIND_FAMILY.get(k1), _KIND_FAMILY.get(k2)
    return f1 is None or f2 is None or f1 == f2


def _dedupe_duplicates(rows: list[dict], window_days: float, factor_tol: float) -> list[dict]:
    """Collapse applied duplicates of the same symbol/date-window/factor/kind family to a single row.

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
                          and _same_factor(rows[i]["factor"], rows[j]["factor"], factor_tol)
                          and _kinds_compatible(rows[i]["kind"], rows[j]["kind"])), None)
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
    # Share counts: rounded to whole shares (1000 / (1/3) is 3000.0000000000005, not 3000) but
    # kept float64 so NaN survives; they become indicators_daily.volume downstream.
    if "volume" in df.columns:
        df["adj_volume"] = (df["volume"].astype("float64") / df["price_factor"]).round().astype("float64")
    if "delivery_qty" in df.columns:
        df["adj_delivery_qty"] = (df["delivery_qty"].astype("float64") / df["price_factor"]).round().astype("float64")

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
    out = df.reset_index(drop=True)
    symbols = out["symbol"].to_numpy(dtype=object).copy()
    dates = pd.to_datetime(out[date_col], errors="coerce").to_numpy(dtype="datetime64[ns]")
    ordered = changes.sort_values("change_date", na_position="last", kind="stable")
    involved = set(ordered["old_symbol"]) | set(ordered["new_symbol"])
    # Vectorised: instead of one full-frame comparison per change (O(changes x rows), ~6 minutes
    # on the real mcap history), track the row positions currently holding each involved symbol
    # and move them between symbols in change_date order -- same sequential semantics, so a
    # chain A->B->C still lands on C.
    candidates = np.flatnonzero(pd.Series(symbols).isin(involved).to_numpy())
    positions: dict = {}
    if len(candidates):
        for sym, pos in pd.Series(candidates).groupby(symbols[candidates], sort=False):
            positions[sym] = pos.to_numpy()
    empty = np.array([], dtype=np.int64)
    for old, new, change_date in zip(ordered["old_symbol"], ordered["new_symbol"], ordered["change_date"]):
        pos = positions.get(old)
        if pos is None or len(pos) == 0:
            continue
        if pd.notna(change_date):
            move = dates[pos] < pd.Timestamp(change_date).to_datetime64().astype("datetime64[ns]")
        else:
            move = np.ones(len(pos), dtype=bool)
        if not move.any():
            continue
        positions[old] = pos[~move]
        positions[new] = np.concatenate([positions.get(new, empty), pos[move]])
    for sym, pos in positions.items():
        symbols[pos] = sym
    out = out.copy()
    out["symbol"] = symbols
    return out


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


def adjust_prices(prices: pd.DataFrame, root: Path, extra_actions: pd.DataFrame | None = None,
                  cache_dir: Path | None | _DefaultCacheDir = DEFAULT_CACHE_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Detect split/bonus/consolidation events from official NSE data under `root`, reconcile
    them against `prices`, and return `(adjusted_prices, adjustments)`.

    `extra_actions` (e.g. the live `corporate_actions` table, re-parsed via
    `actions_from_corporate_actions_table`) is merged into the bc-sourced actions before symbol
    renaming and reconciliation, de-duplicated on `(symbol, ex_date, description, kind)` same as
    `collect_bc_actions` (first-published copy kept; a missing `published` counts as ex_date).

    `cache_dir` holds per-file parses of the PR zips / mcap CSVs, keyed by file name + size +
    mtime (stale or corrupt entries are rebuilt). By default it is `default_cache_dir(root)`
    (`<root>/Input/archive/.adjust_cache`); pass `None` to disable caching entirely -- no reads,
    no writes -- e.g. for strictly read-only callers.
    """
    root = Path(root)
    if isinstance(cache_dir, _DefaultCacheDir):
        cache_dir = default_cache_dir(root)
    zips = find_pr_zips(root)
    cache = _ParseCache(cache_dir)
    zip_entries = _load_pr_zips(zips, cache)  # each PR zip is opened (or cache-loaded) once
    mcap_frames = _mcap_frames_from(root, zip_entries, cache)
    cache.save()
    bc = _bc_actions_from_entries(zip_entries)
    if extra_actions is not None and not extra_actions.empty:
        extra = extra_actions[[c for c in BC_ACTION_COLUMNS if c in extra_actions.columns]]
        bc = _dedupe_bc_actions(pd.concat([bc, extra], ignore_index=True))

    changes_path = root / "Input" / "reference" / "symbolchange.csv"
    changes = None
    if changes_path.exists():
        from symbol_changes import parse_symbol_changes
        changes = parse_symbol_changes(changes_path)
        bc = _rename_symbols(bc, changes, "ex_date")
        # Rename the raw mcap snapshot rows (keyed on each row's own file_date) *before*
        # actions_from_mcap groups by symbol, so a symbol's mcap history isn't split into two
        # unrelated groups across a rename that straddles it.
        mcap_frames = _rename_symbols(mcap_frames, changes, "file_date")

    mcap = actions_from_mcap(mcap_frames)

    # Events are keyed on the *current* symbol (renamed above), but price rows may still carry
    # an old one: the full build renames them via universe.apply_symbol_changes, the daily
    # append does not, so a rename between full builds (e.g. HEG -> HEGAM) would otherwise
    # leave the old rows unadjusted and the event matched against no prices at all. Gap
    # detection, future-ex-date suppression and the cumulative factor therefore run on a
    # canonical symbol per row (same rule: rows dated before change_date take the new symbol);
    # the returned frame keeps the original symbol values, row order and index.
    canonical = _canonical_price_symbols(prices, changes)
    keyed = prices if canonical is None else prices.assign(symbol=canonical)

    gaps = gap_candidates(keyed)
    overrides = load_overrides(root / "Input" / "reference" / "adjustments_override.yaml")
    adjustments = reconcile(bc, mcap, gaps, overrides)
    adjustments = _suppress_future_ex_dates(adjustments, keyed)
    adjusted = apply_adjustments(keyed, adjustments)
    if canonical is not None:
        adjusted["symbol"] = prices["symbol"].array  # positional: same row order as `prices`
    return adjusted, adjustments


def _canonical_price_symbols(prices: pd.DataFrame, changes: pd.DataFrame | None) -> np.ndarray | None:
    """Per-row current symbol for `prices` under the symbol-change history, or None when no
    row's symbol changes (so callers can keep using `prices` as-is)."""
    if changes is None or changes.empty or prices is None or prices.empty:
        return None
    renamed = _rename_symbols(prices[["symbol", "trade_date"]], changes, "trade_date")["symbol"].to_numpy(dtype=object)
    if (renamed == prices["symbol"].to_numpy(dtype=object)).all():
        return None
    return renamed


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
    the NSE-reported 52-week high/low (adjusted by NSE only up to each file's date, so on that
    row's raw scale) onto today's adjusted-price scale used by the OHLCV columns above, before
    computing `away_52w_high_pct` and everything derived from it.
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
