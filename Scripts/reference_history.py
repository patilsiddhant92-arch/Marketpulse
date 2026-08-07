"""Build and join date-keyed security reference data."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

import pandas as pd


REFERENCE_COLUMNS = [
    "symbol",
    "effective_date",
    "source_date",
    "market_cap_cr",
    "pe",
    "adjusted_pe",
    "price_band",
    "band_remarks",
    "high_52w",
    "high_52w_date",
    "low_52w",
    "low_52w_date",
    "source_checksum",
]


def _date_column(frame: pd.DataFrame, names: Iterable[str], fallback=None) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return pd.to_datetime(frame[name], errors="coerce").dt.normalize()
    return pd.Series(fallback, index=frame.index, dtype="datetime64[ns]")


def _checksum(row: pd.Series) -> str:
    values = "|".join("" if pd.isna(row.get(col)) else str(row.get(col)) for col in REFERENCE_COLUMNS[:-1])
    return hashlib.sha256(values.encode("utf-8")).hexdigest()


def _normalize(frame: pd.DataFrame, source_name: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=REFERENCE_COLUMNS)
    frame = frame.copy()
    aliases = {
        "mcap": "market_cap_cr",
        "market_cap": "market_cap_cr",
        "band": "price_band",
        "high52": "high_52w",
        "low52": "low_52w",
    }
    frame = frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})
    if "symbol" not in frame.columns:
        raise ValueError(f"{source_name} reference data must contain symbol")
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["effective_date"] = _date_column(frame, ("effective_date", "source_date", "trade_date", "date"))
    frame["source_date"] = _date_column(frame, ("source_date", "effective_date", "trade_date", "date"))
    for col in REFERENCE_COLUMNS:
        if col not in frame.columns:
            frame[col] = pd.NA
    numeric = ["market_cap_cr", "pe", "adjusted_pe", "price_band", "high_52w", "low_52w"]
    for col in numeric:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    for col in ("high_52w_date", "low_52w_date"):
        frame[col] = pd.to_datetime(frame[col], errors="coerce").dt.normalize()
    frame["source_checksum"] = frame["source_checksum"].astype("string")
    missing = frame["source_checksum"].isna() | (frame["source_checksum"].str.len() == 0)
    frame.loc[missing, "source_checksum"] = frame.loc[missing].apply(_checksum, axis=1)
    return frame[REFERENCE_COLUMNS]


def build_security_reference_history(
    mcap: pd.DataFrame,
    bands: pd.DataFrame,
    pe: pd.DataFrame,
    high52: pd.DataFrame,
) -> pd.DataFrame:
    """Combine dated snapshots into one effective-date reference table."""

    frames = [_normalize(frame, name) for frame, name in ((mcap, "market cap"), (bands, "price band"), (pe, "PE"), (high52, "52-week"))]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=REFERENCE_COLUMNS)
    combined = pd.concat(frames, ignore_index=True)
    # Preserve source ingestion order for same-day snapshots; the final row is
    # the most recently loaded observation when a file is corrected in place.
    combined = combined.sort_values(["symbol", "effective_date"], kind="stable")
    # Multiple report types can describe one effective date. Merge values across them,
    # while preferring the last non-null value for each field.
    value_columns = [col for col in REFERENCE_COLUMNS if col not in {"symbol", "effective_date", "source_date", "source_checksum"}]
    grouped = []
    for (symbol, effective_date), group in combined.groupby(["symbol", "effective_date"], dropna=False, sort=False):
        row = {"symbol": symbol, "effective_date": effective_date, "source_date": group["source_date"].max()}
        for col in value_columns:
            values = group[col].dropna()
            row[col] = values.iloc[-1] if not values.empty else pd.NA
        row["source_checksum"] = group["source_checksum"].iloc[-1]
        grouped.append(row)
    result = pd.DataFrame(grouped, columns=REFERENCE_COLUMNS)
    return result.sort_values(["symbol", "effective_date"]).reset_index(drop=True)


def _naive_day(series: pd.Series) -> pd.Series:
    """Normalize to timezone-naive midnight timestamps."""
    s = pd.to_datetime(series, errors="coerce")
    try:
        if getattr(s.dt, "tz", None) is not None:
            s = s.dt.tz_convert("UTC").dt.tz_localize(None)
    except (TypeError, AttributeError, ValueError):
        pass
    return s.dt.normalize()


def asof_reference(reference: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """
    Join each row to the latest reference available on or before its date.

    Uses per-symbol merge_asof (reliable). Global merge_asof(by=symbol) raises
    "left keys must be sorted" on large multi-symbol frames — that is what broke
    the first GitHub Actions EOD run.

    Guarantees: same number of output rows as input `rows` (in original order).
    Never uses a future effective_date for a trade_date.
    """
    if rows.empty:
        return rows.copy()

    ref_cols = [c for c in REFERENCE_COLUMNS if c not in {"symbol"}]
    empty_result = rows.copy()
    for col in ref_cols:
        if col not in empty_result.columns:
            empty_result[col] = pd.NA
    if reference.empty:
        return empty_result

    left = rows.copy()
    left["_input_order"] = range(len(left))
    right = reference.copy()
    left["symbol"] = left["symbol"].astype(str).str.strip().str.upper()
    right["symbol"] = right["symbol"].astype(str).str.strip().str.upper()
    left["trade_date"] = _naive_day(left["trade_date"])
    right["effective_date"] = _naive_day(right["effective_date"])
    right = right.dropna(subset=["symbol", "effective_date"])
    # One snapshot per symbol per day (merge_asof right keys must be unique within group)
    right = right.sort_values(["symbol", "effective_date"], kind="mergesort")
    right = right.drop_duplicates(["symbol", "effective_date"], keep="last")
    right_by = {sym: grp.drop(columns=["symbol"]) for sym, grp in right.groupby("symbol", sort=False)}

    pieces: list[pd.DataFrame] = []
    # Keep every left row (even if trade_date is NaT) so length matches caller.
    for symbol, left_g in left.groupby("symbol", sort=False, dropna=False):
        left_g = left_g.sort_values(["trade_date", "_input_order"], kind="mergesort")
        right_g = right_by.get(symbol)
        if right_g is None or right_g.empty or left_g["trade_date"].isna().all():
            empty_refs = left_g.copy()
            for col in ref_cols:
                if col not in empty_refs.columns:
                    empty_refs[col] = pd.NA
            pieces.append(empty_refs)
            continue
        right_g = right_g.sort_values("effective_date", kind="mergesort").reset_index(drop=True)
        # merge_asof cannot take NaT on keys — split valid / invalid trade_dates
        valid = left_g["trade_date"].notna()
        left_ok = left_g.loc[valid].reset_index(drop=True)
        left_bad = left_g.loc[~valid].copy()
        for col in ref_cols:
            if col not in left_bad.columns:
                left_bad[col] = pd.NA
        if left_ok.empty:
            pieces.append(left_bad)
            continue
        left_ok = left_ok.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
        try:
            merged = pd.merge_asof(
                left_ok,
                right_g,
                left_on="trade_date",
                right_on="effective_date",
                direction="backward",
                allow_exact_matches=True,
            )
        except ValueError:
            # Last-resort: numpy searchsorted (no merge_asof)
            import numpy as np

            merged = left_ok.copy()
            eff = pd.to_datetime(right_g["effective_date"]).to_numpy()
            trade = pd.to_datetime(merged["trade_date"]).to_numpy()
            idxs = np.searchsorted(eff, trade, side="right") - 1
            for col in ref_cols:
                if col not in right_g.columns:
                    if col not in merged.columns:
                        merged[col] = pd.NA
                    continue
                vals = right_g[col].to_numpy()
                merged[col] = [
                    vals[i] if 0 <= i < len(vals) else pd.NA for i in idxs
                ]
        if not left_bad.empty:
            pieces.append(pd.concat([merged, left_bad], ignore_index=True))
        else:
            pieces.append(merged)

    if not pieces:
        return empty_result

    joined = pd.concat(pieces, ignore_index=True)
    joined = joined.sort_values("_input_order", kind="mergesort")
    # Restore exact input length / order
    if len(joined) != len(rows):
        # Should not happen; return empty refs rather than crash CI rebuild
        return empty_result
    return joined.drop(columns=["_input_order"], errors="ignore").reset_index(drop=True)


def _file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_date(path: Path):
    """Parse trading date from downloads/DDMMYYYY/ parent or from dated filename."""
    # downloads/05082026/mcap....csv
    try:
        return pd.to_datetime(path.parent.name, format="%d%m%Y").normalize()
    except (TypeError, ValueError):
        pass
    # archive/CM_52_wk_High_low_05082026.csv or daily/mcap05082026.csv
    import re

    name = path.name
    # Prefer 8-digit ddmmyyyy in filename
    match = re.search(r"(?<!\d)(\d{8})(?!\d)", name)
    if match:
        try:
            return pd.to_datetime(match.group(1), format="%d%m%Y").normalize()
        except (TypeError, ValueError):
            pass
    # PE_050826 / MA050826 style (ddmmyy)
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", name)
    if match:
        try:
            return pd.to_datetime(match.group(1), format="%d%m%y").normalize()
        except (TypeError, ValueError):
            pass
    return pd.NaT


def _frame_from_files(paths, reader) -> pd.DataFrame:
    frames = []
    for path in sorted(set(paths)):
        if not path.is_file():
            continue
        source_date = _file_date(path)
        if pd.isna(source_date):
            continue
        try:
            frame = reader(path)
        except (OSError, ValueError, pd.errors.ParserError, TypeError):
            continue
        if frame is None or frame.empty:
            continue
        frame = frame.copy()
        frame["source_date"] = source_date
        frame["effective_date"] = source_date
        frame["source_checksum"] = _file_checksum(path)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_reference_history(root: Path) -> pd.DataFrame:
    """Read every dated reference snapshot from downloads, archive, and daily."""

    root = Path(root)
    downloads = root / "Input" / "downloads"
    archive = root / "Input" / "archive"
    daily = root / "Input" / "daily"

    def read_mcap(path):
        frame = pd.read_csv(path, dtype=str, skipinitialspace=True)
        frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]
        col = next((name for name in frame.columns if name.startswith("market_cap")), None)
        if col is None or "symbol" not in frame.columns:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "symbol": frame["symbol"],
                "market_cap_cr": pd.to_numeric(
                    frame[col].astype(str).str.replace(",", "", regex=False), errors="coerce"
                )
                / 10_000_000,
            }
        )

    def read_band(path):
        frame = pd.read_csv(path, dtype=str, skipinitialspace=True)
        frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]
        if "symbol" not in frame.columns:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "symbol": frame["symbol"],
                "price_band": pd.to_numeric(frame.get("band", ""), errors="coerce"),
                "band_remarks": frame.get("remarks", ""),
            }
        )

    def read_pe_file(path):
        frame = pd.read_csv(path, dtype=str, skipinitialspace=True)
        frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]
        if "symbol" not in frame.columns:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "symbol": frame["symbol"],
                "pe": pd.to_numeric(frame.get("symbol_p/e", ""), errors="coerce"),
                "adjusted_pe": pd.to_numeric(frame.get("adjusted_p/e", ""), errors="coerce"),
            }
        )

    def read_high_file(path):
        # NSE files often have 2 disclaimer rows before header
        frame = pd.read_csv(path, dtype=str, skiprows=2)
        frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]
        if "symbol" not in frame.columns:
            return pd.DataFrame()
        high_s = frame["adjusted_52_week_high"] if "adjusted_52_week_high" in frame.columns else pd.Series(dtype=str)
        low_s = frame["adjusted_52_week_low"] if "adjusted_52_week_low" in frame.columns else pd.Series(dtype=str)
        return pd.DataFrame(
            {
                "symbol": frame["symbol"],
                "high_52w": pd.to_numeric(high_s.astype(str).str.replace(",", "", regex=False), errors="coerce"),
                "high_52w_date": pd.to_datetime(
                    frame["52_week_high_date"] if "52_week_high_date" in frame.columns else pd.Series(dtype=str),
                    format="%d-%b-%Y",
                    errors="coerce",
                ),
                "low_52w": pd.to_numeric(low_s.astype(str).str.replace(",", "", regex=False), errors="coerce"),
                "low_52w_date": pd.to_datetime(
                    frame["52_week_low_dt"] if "52_week_low_dt" in frame.columns else pd.Series(dtype=str),
                    format="%d-%b-%Y",
                    errors="coerce",
                ),
            }
        )

    mcap_paths = []
    band_paths = []
    pe_paths = []
    high_paths = []
    if downloads.exists():
        mcap_paths += list(downloads.glob("*/mcap*.csv"))
        band_paths += list(downloads.glob("*/sec_list_*.csv"))
        pe_paths += list(downloads.glob("*/PE_*.csv"))
        high_paths += list(downloads.glob("*/CM_52_wk_High_low_*.csv"))
    if archive.exists():
        mcap_paths += list(archive.glob("mcap*.csv"))
        band_paths += list(archive.glob("sec_list_*.csv"))
        pe_paths += list(archive.glob("PE_*.csv"))
        high_paths += list(archive.glob("CM_52_wk_High_low_*.csv"))
    if daily.exists():
        mcap_paths += list(daily.glob("mcap*.csv"))
        band_paths += list(daily.glob("sec_list_*.csv"))
        pe_paths += list(daily.glob("PE_*.csv"))
        high_paths += list(daily.glob("CM_52_wk_High_low_*.csv"))

    return build_security_reference_history(
        _frame_from_files(mcap_paths, read_mcap),
        _frame_from_files(band_paths, read_band),
        _frame_from_files(pe_paths, read_pe_file),
        _frame_from_files(high_paths, read_high_file),
    )
