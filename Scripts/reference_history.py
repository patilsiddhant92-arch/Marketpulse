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


def asof_reference(reference: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """Join each row to the latest reference available on or before its date."""

    if rows.empty:
        return rows.copy()
    if reference.empty:
        result = rows.copy()
        for col in REFERENCE_COLUMNS:
            if col not in result.columns:
                result[col] = pd.NA
        return result
    left = rows.copy().reset_index(drop=False).rename(columns={"index": "_input_order"})
    right = reference.copy()
    left["symbol"] = left["symbol"].astype(str).str.strip().str.upper()
    right["symbol"] = right["symbol"].astype(str).str.strip().str.upper()
    left["trade_date"] = pd.to_datetime(left["trade_date"], errors="coerce").dt.normalize()
    right["effective_date"] = pd.to_datetime(right["effective_date"], errors="coerce").dt.normalize()
    left = left.sort_values(["symbol", "trade_date"])
    right = right.sort_values(["symbol", "effective_date"])
    joined = pd.merge_asof(
        left,
        right,
        left_on="trade_date",
        right_on="effective_date",
        by="symbol",
        direction="backward",
        allow_exact_matches=True,
        suffixes=("", "_reference"),
    )
    return joined.sort_values("_input_order").drop(columns=["_input_order"]).reset_index(drop=True)


def _file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_date(path: Path):
    try:
        return pd.to_datetime(path.parent.name, format="%d%m%Y").normalize()
    except (TypeError, ValueError):
        return pd.NaT


def _frame_from_files(paths, reader) -> pd.DataFrame:
    frames = []
    for path in sorted(paths):
        source_date = _file_date(path)
        if pd.isna(source_date):
            continue
        try:
            frame = reader(path)
        except (OSError, ValueError, pd.errors.ParserError):
            continue
        if frame.empty:
            continue
        frame["source_date"] = source_date
        frame["effective_date"] = source_date
        frame["source_checksum"] = _file_checksum(path)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_reference_history(root: Path) -> pd.DataFrame:
    """Read every dated reference snapshot available in Input/downloads."""

    downloads = Path(root) / "Input" / "downloads"
    if not downloads.exists():
        return pd.DataFrame(columns=REFERENCE_COLUMNS)

    def read_mcap(path):
        frame = pd.read_csv(path, dtype=str, skipinitialspace=True)
        frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]
        col = next((name for name in frame.columns if name.startswith("market_cap")), None)
        if col is None or "symbol" not in frame.columns:
            return pd.DataFrame()
        return pd.DataFrame({"symbol": frame["symbol"], "market_cap_cr": pd.to_numeric(frame[col].astype(str).str.replace(",", "", regex=False), errors="coerce") / 10_000_000})

    def read_band(path):
        frame = pd.read_csv(path, dtype=str, skipinitialspace=True)
        frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]
        if "symbol" not in frame.columns:
            return pd.DataFrame()
        return pd.DataFrame({"symbol": frame["symbol"], "price_band": pd.to_numeric(frame.get("band", ""), errors="coerce"), "band_remarks": frame.get("remarks", "")})

    def read_pe_file(path):
        frame = pd.read_csv(path, dtype=str, skipinitialspace=True)
        frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]
        if "symbol" not in frame.columns:
            return pd.DataFrame()
        return pd.DataFrame({"symbol": frame["symbol"], "pe": pd.to_numeric(frame.get("symbol_p/e", ""), errors="coerce"), "adjusted_pe": pd.to_numeric(frame.get("adjusted_p/e", ""), errors="coerce")})

    def read_high_file(path):
        frame = pd.read_csv(path, dtype=str, skiprows=2)
        frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]
        if "symbol" not in frame.columns:
            return pd.DataFrame()
        return pd.DataFrame({"symbol": frame["symbol"], "high_52w": pd.to_numeric(frame.get("adjusted_52_week_high", ""), errors="coerce"), "high_52w_date": pd.to_datetime(frame.get("52_week_high_date", ""), format="%d-%b-%Y", errors="coerce"), "low_52w": pd.to_numeric(frame.get("adjusted_52_week_low", ""), errors="coerce"), "low_52w_date": pd.to_datetime(frame.get("52_week_low_dt", ""), format="%d-%b-%Y", errors="coerce")})

    return build_security_reference_history(
        _frame_from_files(downloads.glob("*/mcap*.csv"), read_mcap),
        _frame_from_files(downloads.glob("*/sec_list_*.csv"), read_band),
        _frame_from_files(downloads.glob("*/PE_*.csv"), read_pe_file),
        _frame_from_files(downloads.glob("*/CM_52_wk_High_low_*.csv"), read_high_file),
    )
