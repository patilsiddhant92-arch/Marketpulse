"""Parse and derive point-in-time features from NSE Market Activity index files."""

from __future__ import annotations

import csv
import fnmatch
import io
import os
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

_IND_CLOSE_ALL_RE = re.compile(r"ind_close_all_(\d{2})(\d{2})(\d{4})\.csv$", re.IGNORECASE)


INDEX_COLUMNS = [
    "trade_date",
    "index_name",
    "previous_close",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "change_value",
    "return_1d_pct",
]


def _number(value):
    text = str(value or "").replace(",", "").strip()
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _market_activity_records(path: Path, trade_date: date | pd.Timestamp) -> list[tuple]:
    """Index rows of one MA file as INDEX_COLUMNS-ordered tuples.

    Hot loop (MA files are ~3k csv rows, of which only the index block qualifies): only
    the eight fields that matter are touched, so non-index rows cost a single len() check.
    Semantics match the original per-field ``str(v).strip()`` + ``_number`` parse exactly
    (``_number`` strips again after dropping commas, so pre-stripping is redundant).

    When the file has no quote characters (true for every NSE MA file seen), a csv record
    cannot span lines and has at most ``commas + 1`` fields, so lines with fewer than 7
    commas can never yield the >= 8 fields needed and are dropped before csv parsing.
    The kept lines are re-parsed through the same newline="" csv path, so stray ``\\r``
    record breaks behave exactly as before.
    """
    trade_ts = pd.Timestamp(trade_date).normalize()
    records = []
    with Path(path).open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        text = handle.read()
    if '"' not in text:
        text = "\n".join(line for line in text.split("\n") if line.count(",") >= 7)
    with io.StringIO(text, newline="") as handle:
        for raw in csv.reader(handle):
            if len(raw) < 8:
                continue
            name = raw[1].strip()
            if name.upper() in {"INDEX", ""}:
                continue
            try:
                previous, opening, high, low, close, change = (float(value.replace(",", "").strip()) for value in raw[2:8])
            except ValueError:
                continue
            records.append(
                (
                    trade_ts,
                    name,
                    previous,
                    opening,
                    high,
                    low,
                    close,
                    change,
                    round((close / previous - 1.0) * 100, 10) if previous else None,
                )
            )
    return records


def parse_market_activity(path: Path, trade_date: date | pd.Timestamp) -> pd.DataFrame:
    return pd.DataFrame(_market_activity_records(path, trade_date), columns=INDEX_COLUMNS)


def parse_market_macro(path: Path, trade_date: date | pd.Timestamp) -> dict[str, Any]:
    """Parse exchange-level macro summary from NSE MA file header."""
    macro: dict[str, Any] = {
        "trade_date": pd.Timestamp(trade_date).normalize(),
        "traded_value_cr": None,
        "traded_quantity_lakhs": None,
        "number_of_trades": None,
        "total_market_cap_cr": None,
    }
    try:
        with Path(path).open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            for raw in reader:
                values = [str(v).strip() for v in raw if str(v).strip()]
                if len(values) >= 2:
                    label = values[0].lower()
                    val = _number(values[1])
                    if "traded value" in label:
                        macro["traded_value_cr"] = val
                    elif "traded quantity" in label:
                        macro["traded_quantity_lakhs"] = val
                    elif "number of trades" in label:
                        macro["number_of_trades"] = int(val) if val is not None else None
                    elif "total market capitalisation" in label or "total market cap" in label:
                        macro["total_market_cap_cr"] = val
                if len(values) >= 5 and any(str(v).upper() == "INDEX" for v in values):
                    break
    except Exception:
        pass
    return macro


def build_index_features(index_daily: pd.DataFrame) -> pd.DataFrame:
    if index_daily is None or index_daily.empty:
        return pd.DataFrame(columns=INDEX_COLUMNS + ["return_5d_pct", "return_20d_pct", "return_63d_pct", "return_126d_pct", "return_252d_pct", "ema_20", "ema_50", "ema_200", "distance_ema_20_pct", "distance_ema_50_pct", "distance_ema_200_pct", "new_20d_high", "new_52w_high", "volatility_20d", "trend_state"])
    result = index_daily.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.normalize()
    result = result.sort_values(["index_name", "trade_date"]).reset_index(drop=True)
    if "return_1d_pct" not in result.columns:
        if "previous_close" in result.columns:
            result["return_1d_pct"] = (pd.to_numeric(result["close_price"], errors="coerce") / pd.to_numeric(result["previous_close"], errors="coerce") - 1.0) * 100
        else:
            result["return_1d_pct"] = result.groupby("index_name")["close_price"].pct_change() * 100
    groups = result.groupby("index_name", group_keys=False)
    for window in (5, 20, 63, 126, 252):
        result[f"return_{window}d_pct"] = groups["close_price"].transform(lambda s, n=window: (s / s.shift(n) - 1.0) * 100)
    for window in (20, 50, 200):
        result[f"ema_{window}"] = groups["close_price"].transform(lambda s, n=window: s.ewm(span=n, adjust=False, min_periods=1).mean())
        result[f"distance_ema_{window}_pct"] = (result["close_price"] / result[f"ema_{window}"] - 1.0) * 100
    result["new_20d_high"] = result["close_price"] >= groups["close_price"].transform(lambda s: s.rolling(20, min_periods=1).max())
    result["new_52w_high"] = result["close_price"] >= groups["close_price"].transform(lambda s: s.rolling(252, min_periods=1).max())
    result["volatility_20d"] = groups["return_1d_pct"].transform(lambda s: s.rolling(20, min_periods=2).std())
    result["trend_state"] = "Neutral"
    constructive = (result["close_price"] >= result["ema_20"]) & (result["ema_20"] >= result["ema_50"]) & (result["ema_50"] >= result["ema_200"])
    defensive = (result["close_price"] < result["ema_20"]) & (result["ema_20"] < result["ema_50"])
    result.loc[constructive, "trend_state"] = "Constructive"
    result.loc[defensive, "trend_state"] = "Defensive"
    return result


def _parse_ma_date(path: Path) -> date | None:
    p = Path(path)
    try:
        d = pd.to_datetime(p.parent.name, format="%d%m%Y")
        if pd.notna(d):
            return d.date()
    except (TypeError, ValueError):
        pass
    import re
    m8 = re.search(r"(?<!\d)(\d{8})(?!\d)", p.name)
    if m8:
        try:
            return pd.to_datetime(m8.group(1), format="%d%m%Y").date()
        except ValueError:
            pass
    m6 = re.search(r"MA(\d{6})", p.name, re.IGNORECASE)
    if m6:
        try:
            return pd.to_datetime(m6.group(1), format="%d%m%y").date()
        except ValueError:
            pass
    return None


def parse_market_activity_history(paths) -> pd.DataFrame:
    # All files' rows go into ONE DataFrame (the old per-file frame + concat cost more
    # than the parsing itself); row order, dedup and sort are unchanged.
    records = []
    for path in sorted(set(paths)):
        trade_day = _parse_ma_date(Path(path))
        if trade_day is None:
            continue
        records.extend(_market_activity_records(path, trade_day))
    if not records:
        return pd.DataFrame(columns=INDEX_COLUMNS)
    return (
        pd.DataFrame(records, columns=INDEX_COLUMNS)
        .drop_duplicates(["trade_date", "index_name"], keep="last")
        .sort_values(["trade_date", "index_name"])
        .reset_index(drop=True)
    )


_GLOB_FLAGS = re.IGNORECASE if os.name == "nt" else 0  # pathlib glob is case-insensitive on Windows
_MA_GLOB = re.compile(fnmatch.translate("MA*.csv"), _GLOB_FLAGS)
_IND_CLOSE_ALL_GLOB = re.compile(fnmatch.translate("ind_close_all_*.csv"), _GLOB_FLAGS)


def _list_matching(folder: Path | str, pattern: re.Pattern) -> list[tuple[str, int, int]]:
    """``folder.glob(<single-level pattern>)`` as (path str, size, mtime_ns) tuples.

    os.scandir hands back stat data without an extra syscall on Windows and plain strings
    avoid pathlib overhead, keeping the memo's file-set signature cheap (~2k files).
    """
    listed = []
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if pattern.match(entry.name):
                    try:
                        st = entry.stat()
                    except OSError:
                        continue
                    listed.append((entry.path, st.st_size, st.st_mtime_ns))
    except OSError:
        return []
    return listed


def _market_activity_entries(root: Path) -> list[tuple[str, int, int]]:
    root = Path(root)
    entries: list[tuple[str, int, int]] = []
    downloads = root / "Input" / "downloads"
    archive = root / "Input" / "archive"
    daily = root / "Input" / "daily"
    if downloads.exists():  # downloads/*/MA*.csv
        try:
            with os.scandir(downloads) as it:
                subdirs = [entry.path for entry in it if entry.is_dir()]
        except OSError:
            subdirs = []
        for sub in subdirs:
            entries.extend(_list_matching(sub, _MA_GLOB))
    if archive.exists():
        entries.extend(_list_matching(archive, _MA_GLOB))
    if daily.exists():
        entries.extend(_list_matching(daily, _MA_GLOB))
    return entries


def _market_activity_paths(root: Path) -> list[Path]:
    return [Path(path) for path, _size, _mtime in _market_activity_entries(root)]


def load_all_market_activity_history(root: Path) -> pd.DataFrame:
    """Find and parse all MA files from downloads, archive, and daily."""
    return parse_market_activity_history(_market_activity_paths(root))



EXTRA_INDEX_COLUMNS = ["volume", "turnover_cr", "pe", "pb", "div_yield"]
_IND_CLOSE_ALL_NUMERIC = {
    "open_price": "Open Index Value",
    "high_price": "High Index Value",
    "low_price": "Low Index Value",
    "close_price": "Closing Index Value",
    "change_value": "Points Change",
    "return_1d_pct": "Change(%)",
    "volume": "Volume",
    "turnover_cr": "Turnover (Rs. Cr.)",
    "pe": "P/E",
    "pb": "P/B",
    "div_yield": "Div Yield",
}


def _read_ind_close_all_raw(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    raw.columns = [str(c).strip() for c in raw.columns]
    return raw


def _ind_close_all_frames_to_rows(paths: list[Path], raws: list[pd.DataFrame], emit) -> pd.DataFrame:
    """Vectorised ind_close_all parse over one or many already-read files.

    Every step is element-wise (strip / comma-drop / to_numeric / to_datetime), so running
    it once over the concatenated raw rows gives exactly the per-file result; the only
    per-file logic (filename-authoritative date, 0-row warning) is applied by file id.
    ``emit(file_index, message)`` receives the warnings in per-file order.
    """
    if len(raws) == 1:
        raw = raws[0]
        file_id = np.zeros(len(raw), dtype=np.int64)
    else:
        raw = pd.concat(raws, ignore_index=True)
        file_id = np.repeat(np.arange(len(raws), dtype=np.int64), [len(r) for r in raws])

    def num(col):
        if col not in raw.columns:
            return pd.Series(np.nan, index=raw.index, dtype="float64")
        return pd.to_numeric(raw[col].astype(str).str.replace(",", "").str.strip().replace({"-": None}), errors="coerce")

    trade_date = pd.to_datetime(raw["Index Date"].str.strip(), format="%d-%m-%Y", errors="coerce")
    first_parsed = trade_date.groupby(file_id).first() if len(trade_date) else pd.Series(dtype="datetime64[ns]")
    for i, path in enumerate(paths):
        name_match = _IND_CLOSE_ALL_RE.search(Path(path).name)
        if not name_match or i not in first_parsed.index or pd.isna(first_parsed.loc[i]):
            continue
        dd, mm, yyyy = name_match.groups()
        filename_date = pd.Timestamp(year=int(yyyy), month=int(mm), day=int(dd))
        parsed_first = pd.Timestamp(first_parsed.loc[i])
        if parsed_first != filename_date:
            # NSE occasionally writes "Index Date" as MM-DD-YYYY instead of this file's
            # usual DD-MM-YYYY (all three known cases are April 2023). The filename date
            # is authoritative -- trusting the column would misdate every row and, worse,
            # can silently collide with (and overwrite) a genuinely different session.
            emit(
                i,
                f"WARNING: {Path(path).name} Index Date parsed as "
                f"{parsed_first.date().isoformat()} but the filename implies "
                f"{filename_date.date().isoformat()}; using the filename date for all rows",
            )
            if len(raws) == 1:
                trade_date = pd.Series(filename_date, index=raw.index)
            else:
                trade_date = trade_date.mask(file_id == i, filename_date)

    columns = {"trade_date": trade_date, "index_name": raw["Index Name"].astype(str).str.strip()}
    columns.update({out_col: num(src_col) for out_col, src_col in _IND_CLOSE_ALL_NUMERIC.items()})
    out = pd.DataFrame(columns)
    out["previous_close"] = out["close_price"] - out["change_value"]
    keep = (out["trade_date"].notna() & out["close_price"].notna()).to_numpy()
    out = out[keep]
    kept_per_file = np.bincount(file_id[keep], minlength=len(raws))
    for i, path in enumerate(paths):
        if kept_per_file[i] == 0:
            emit(i, f"WARNING: {Path(path).name} yielded 0 rows")
    return out[INDEX_COLUMNS + EXTRA_INDEX_COLUMNS]


def parse_ind_close_all(path: Path) -> pd.DataFrame:
    raw = _read_ind_close_all_raw(path)
    return _ind_close_all_frames_to_rows([Path(path)], [raw], lambda _i, message: print(message))


def _ind_close_all_listing(root: Path) -> list[list[tuple[str, int, int]]]:
    """Per-folder (archive, archive/backfill/index, daily) ind_close_all entries."""
    root = Path(root)
    folders = [root / "Input" / "archive", root / "Input" / "archive" / "backfill" / "index", root / "Input" / "daily"]
    return [_list_matching(folder, _IND_CLOSE_ALL_GLOB) for folder in folders if folder.exists()]


def _ind_close_all_paths_from_listing(listing: list[list[tuple[str, int, int]]]) -> list[Path]:
    # Same order as the original ``sorted(folder.glob(...))`` per folder.
    return [path for folder_entries in listing for path in sorted(Path(entry[0]) for entry in folder_entries)]


def _ind_close_all_entries(root: Path) -> list[tuple[Path, int, int]]:
    listing = _ind_close_all_listing(root)
    stats = {Path(entry[0]): entry for folder_entries in listing for entry in folder_entries}
    return [(path, stats[path][1], stats[path][2]) for path in _ind_close_all_paths_from_listing(listing)]


def _load_ind_close_all_files(paths: list[Path]) -> list[pd.DataFrame]:
    """Read + parse every ind_close_all file; warnings/skips print in file order."""
    messages: list[tuple[int, int, str]] = []

    def emit(i: int, message: str) -> None:
        messages.append((i, len(messages), message))

    ok_paths: list[Path] = []
    ok_order: list[int] = []
    raws: list[pd.DataFrame] = []
    for i, p in enumerate(paths):
        try:
            raw = _read_ind_close_all_raw(p)
            for required in ("Index Date", "Index Name"):
                if required not in raw.columns:
                    raise KeyError(required)
            # Filename-authoritative date must itself be a real calendar date -- an
            # impossible one (e.g. ind_close_all_31022026.csv) would blow up the
            # filename_date Timestamp construction inside the batched parse below and,
            # unguarded, take down the fast path for every file in the batch just to
            # skip this one row source.
            name_match = _IND_CLOSE_ALL_RE.search(p.name)
            if name_match:
                dd, mm, yyyy = name_match.groups()
                pd.Timestamp(year=int(yyyy), month=int(mm), day=int(dd))
        except Exception as exc:
            emit(i, f"Skipped {p.name}: {exc}")
            continue
        ok_paths.append(p)
        ok_order.append(i)
        raws.append(raw)

    frames: list[pd.DataFrame] = []
    if raws:
        try:
            frames = [_ind_close_all_frames_to_rows(ok_paths, raws, lambda j, message: emit(ok_order[j], message))]
        except Exception as exc:
            print(f"index_history: batched parse failed ({exc}); falling back to per-file parsing")
            # Heterogeneous files (e.g. duplicate headers) that can't be batched: fall back
            # to the original one-file-at-a-time parse.
            messages[:] = [m for m in messages if m[2].startswith("Skipped ")]
            frames = []
            for j, (p, raw) in enumerate(zip(ok_paths, raws)):
                try:
                    frames.append(_ind_close_all_frames_to_rows([p], [raw], lambda _k, message, j=j: emit(ok_order[j], message)))
                except Exception as exc:
                    emit(ok_order[j], f"Skipped {p.name}: {exc}")
    for _i, _seq, message in sorted(messages):
        print(message)
    return frames


def load_index_name_map(path: Path) -> dict[str, str]:
    if path is None or not Path(path).exists():
        return {}
    m = pd.read_csv(path, dtype=str)
    return dict(zip(m["source_name"].str.strip(), m["canonical_name"].str.strip()))


# In-process memo: build_database / append_database / materialize call
# load_all_index_history several times per run over ~2k unchanged files.
_INDEX_HISTORY_CACHE: dict[tuple[str, str], tuple[tuple, pd.DataFrame]] = {}


def clear_index_history_cache() -> None:
    _INDEX_HISTORY_CACHE.clear()


def _stat_signature(path: Path) -> tuple:
    try:
        st = os.stat(path)
    except OSError:
        return (str(path), None, None)
    return (str(path), st.st_size, st.st_mtime_ns)


def load_all_index_history(root: Path, name_map_path: Path | None = None) -> pd.DataFrame:
    """ind_close_all history (+ MA fallback rows), memoised per process.

    Repeated calls with the same root/name map and an unchanged input file set (names,
    sizes, mtimes of every ind_close_all / MA file and the name map) return a copy of the
    cached frame instead of re-parsing ~2k CSVs.
    """
    root = Path(root)
    name_map_path = Path(name_map_path or (root / "Input" / "reference" / "index_name_map.csv"))
    listing = _ind_close_all_listing(root)
    ma_loader = load_all_market_activity_history
    signature = (
        tuple(tuple(sorted(folder_entries)) for folder_entries in listing),
        tuple(sorted(_market_activity_entries(root))),
        _stat_signature(name_map_path),
        ma_loader,
    )
    key = (str(root.resolve()), str(name_map_path.resolve()))
    cached = _INDEX_HISTORY_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1].copy()
    close_all_paths = _ind_close_all_paths_from_listing(listing)
    result = _load_all_index_history_uncached(close_all_paths, name_map_path, lambda: ma_loader(root))
    _INDEX_HISTORY_CACHE[key] = (signature, result.copy())
    return result


def _load_all_index_history_uncached(close_all_paths: list[Path], name_map_path: Path, load_ma) -> pd.DataFrame:
    frames = _load_ind_close_all_files(close_all_paths)
    ma = load_ma()
    if frames:
        close_all = pd.concat(frames, ignore_index=True)
        name_map = load_index_name_map(name_map_path)
        close_all["index_name"] = close_all["index_name"].map(lambda n: name_map.get(n, n))
        close_all = close_all.drop_duplicates(["trade_date", "index_name"], keep="last")
        if ma is not None and not ma.empty:
            ma = ma.copy()
            ma["trade_date"] = pd.to_datetime(ma["trade_date"]).dt.normalize()
            have = pd.MultiIndex.from_arrays([close_all["trade_date"], close_all["index_name"]])
            wanted = pd.MultiIndex.from_arrays([ma["trade_date"], ma["index_name"]])
            ma = ma[~wanted.isin(have)]
            close_all = pd.concat([close_all, ma], ignore_index=True)
    else:
        # No ind_close_all archive files at all: start straight from the MA fallback
        # frame instead of concatenating it onto an empty, object-dtype placeholder
        # (that promoted every numeric column to object and broke downstream math).
        close_all = ma if ma is not None and not ma.empty else pd.DataFrame(columns=INDEX_COLUMNS)

    close_all["trade_date"] = pd.to_datetime(close_all["trade_date"], errors="coerce").dt.normalize()
    numeric_columns = [c for c in INDEX_COLUMNS if c not in ("trade_date", "index_name")] + EXTRA_INDEX_COLUMNS
    for col in numeric_columns:
        if col in close_all.columns:
            close_all[col] = pd.to_numeric(close_all[col], errors="coerce")
    return close_all.sort_values(["trade_date", "index_name"]).reset_index(drop=True)
