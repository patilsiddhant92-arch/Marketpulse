import argparse
import concurrent.futures
import gc
import os
import re
import time
import warnings
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning

from config import (
    ARCHIVE_DIR,
    DAILY_DIR,
    DATABASE_DIR,
    DB_PATH,
    EMA_WINDOWS,
    EQUITY_LIST_FILE,
    EXPORTS_DIR,
    INPUT_DIR,
    LOGS_DIR,
    ROOT_DIR,
    RETURN_WINDOWS,
    SECTOR_FILE,
    WATCHLIST_BUCKETS,
)
from index_history import build_index_features, load_all_index_history
from price_adjustment import adjust_prices, empty_adjustments_frame, indicator_input, summarize_adjustments
from true_rs import attach_true_rs_columns, TRUE_RS_COLUMNS
from sector_index_rs import attach_sector_index_rs, compute_index_bench_rs
from streaming_build import StagedTable, connect_build_db
from index_constituents import load_membership_csv, ensure_index_constituents
from reference_history import asof_reference, load_reference_history
try:
    from Scripts.indicators import (
        adr_pct,
        atr_sma,
        atr_wilder,
        distance_below_high,
        ema,
        rsi_wilder,
        rvol,
        rs_adaptive_mix,
        session_lag,
        setup_class,
        sma,
        true_range,
    )
except (ModuleNotFoundError, ImportError):
    from indicators import (  # type: ignore
        adr_pct,
        atr_sma,
        atr_wilder,
        distance_below_high,
        ema,
        rsi_wilder,
        rvol,
        rs_adaptive_mix,
        session_lag,
        setup_class,
        sma,
        true_range,
    )
try:
    from darvas_squeeze import weekly_ohlc
except (ModuleNotFoundError, ImportError):
    from Scripts.darvas_squeeze import weekly_ohlc  # type: ignore
try:
    from institutional_engine import enrich_deals_with_tiers
except ModuleNotFoundError:
    from Scripts.institutional_engine import enrich_deals_with_tiers  # type: ignore
try:
    from sector_metrics import compute_sector_metrics
except ModuleNotFoundError:
    from Scripts.sector_metrics import compute_sector_metrics  # type: ignore


warnings.simplefilter("ignore", PerformanceWarning)
warnings.simplefilter("ignore", FutureWarning)


def ensure_folders() -> None:
    for folder in [DATABASE_DIR, EXPORTS_DIR, LOGS_DIR]:
        folder.mkdir(parents=True, exist_ok=True)


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]
    return df


def to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.strip().replace({"": np.nan, "-": np.nan}),
        errors="coerce",
    )


def parse_file_date(path: Path) -> pd.Timestamp | None:
    match = re.search(r"(\d{8})", path.name)
    if not match:
        return None
    try:
        return pd.to_datetime(match.group(1), format="%d%m%Y")
    except ValueError:
        return None


def latest_file(folder: Path, pattern: str) -> Path | None:
    files = sorted(folder.glob(pattern), key=lambda p: (parse_file_date(p) or pd.Timestamp.min, p.stat().st_mtime))
    return files[-1] if files else None


def read_equity_symbols() -> pd.DataFrame:
    df = pd.read_csv(EQUITY_LIST_FILE, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    renames = {"SYMBOL": "symbol"}
    for c in df.columns:
        if c.upper() == "DATE OF LISTING":
            renames[c] = "date_of_listing"
        elif c.upper() == "ISIN NUMBER":
            renames[c] = "isin"
        elif c.upper() == "NAME OF COMPANY":
            renames[c] = "security_name"
    df = df.rename(columns=renames)
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df = df[(df["symbol"] != "") & (df["symbol"].str.lower() != "nan")].copy()
    if "date_of_listing" in df.columns:
        df["listing_date"] = pd.to_datetime(df["date_of_listing"], format="%d-%b-%Y", errors="coerce").dt.date
    else:
        df["listing_date"] = None
    if "isin" in df.columns:
        df["isin"] = df["isin"].astype(str).str.strip()
    return df.drop_duplicates("symbol")


def read_sector() -> pd.DataFrame:
    df = pd.read_csv(
        SECTOR_FILE,
        header=None,
        names=["symbol", "broad_sector", "sector", "broad_industry", "industry"],
        dtype=str,
    )
    for col in df.columns:
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["symbol"] = df["symbol"].str.upper()
    df = df[(df["symbol"] != "") & (df["symbol"] != "0")]
    return df.drop_duplicates("symbol", keep="last")


_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def _xlsx_col_index(ref: str) -> int:
    idx = 0
    for ch in ref:
        if not ch.isalpha():
            break
        idx = idx * 26 + (ord(ch.upper()) - 64)
    return idx - 1


def _xlsx_text(elem) -> str:
    """Concatenated text of all <t> descendants (handles rich-text runs)."""
    return "".join(t.text or "" for t in elem.iter(f"{_XLSX_NS}t"))


def read_xlsx_first_sheet(path: Path) -> pd.DataFrame:
    """First worksheet of an .xlsx as an all-string frame (row 1 = header), stdlib only.

    NSE occasionally serves a bhavcopy as an Excel workbook under a ``.csv`` name; openpyxl is
    not a dependency, so the sharedStrings + sheet XML is read directly with zipfile/ElementTree.
    """
    import zipfile
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            with zf.open("xl/sharedStrings.xml") as fh:
                for _, elem in ET.iterparse(fh):
                    if elem.tag == f"{_XLSX_NS}si":
                        shared.append(_xlsx_text(elem))
                        elem.clear()
        sheets = sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
        if not sheets:
            raise ValueError(f"{Path(path).name}: workbook has no worksheets")
        sheet = "xl/worksheets/sheet1.xml" if "xl/worksheets/sheet1.xml" in sheets else sheets[0]
        rows: list[dict[int, str]] = []
        with zf.open(sheet) as fh:
            for _, elem in ET.iterparse(fh):
                if elem.tag != f"{_XLSX_NS}row":
                    continue
                cells: dict[int, str] = {}
                for pos, c in enumerate(elem.iter(f"{_XLSX_NS}c")):
                    ref = c.get("r")
                    col = _xlsx_col_index(ref) if ref else pos
                    kind = c.get("t")
                    if kind == "inlineStr":
                        value = _xlsx_text(c)
                    else:
                        v = c.find(f"{_XLSX_NS}v")
                        value = v.text if v is not None and v.text is not None else ""
                        if kind == "s" and value != "":
                            value = shared[int(value)]
                    cells[col] = value
                rows.append(cells)
                elem.clear()
    if not rows:
        return pd.DataFrame()
    width = max((max(r) + 1 for r in rows if r), default=0)
    header = [str(rows[0].get(i, "")).strip() or f"col_{i}" for i in range(width)]
    body = [[r.get(i) for i in range(width)] for r in rows[1:] if r]
    return pd.DataFrame(body, columns=header, dtype=object)


def _read_bhav_raw(path: Path) -> pd.DataFrame:
    """Raw all-string bhavcopy frame from a CSV, or from an XLSX saved under a .csv name."""
    with open(path, "rb") as fh:
        magic = fh.read(2)
    if magic != b"PK":
        return pd.read_csv(path, dtype=str, skipinitialspace=True)
    df = read_xlsx_first_sheet(path)
    for col in df.columns:
        df[col] = df[col].map(lambda v: v.lstrip() if isinstance(v, str) else v)
    # Excel may store DATE1 as a serial number instead of text.
    date_col = next((c for c in df.columns if str(c).strip().upper() == "DATE1"), None)
    if date_col is not None:
        serial = pd.to_numeric(df[date_col], errors="coerce")
        is_serial = serial.notna()
        if is_serial.any():
            converted = (_EXCEL_EPOCH + pd.to_timedelta(serial[is_serial], unit="D")).dt.strftime("%d-%b-%Y")
            df[date_col] = df[date_col].where(~is_serial, converted)
    return df


def read_bhavcopy(path: Path, universe: set[str] | None = None) -> pd.DataFrame:
    df = _read_bhav_raw(path)
    df = clean_columns(df)
    rename = {
        "date1": "trade_date",
        "open_price": "open_price",
        "high_price": "high_price",
        "low_price": "low_price",
        "close_price": "close_price",
        "ttl_trd_qnty": "volume",
        "turnover_lacs": "turnover_lacs",
        "no_of_trades": "trades",
        "deliv_qty": "delivery_qty",
        "deliv_per": "delivery_pct",
    }
    df = df.rename(columns=rename)
    needed = [
        "symbol",
        "series",
        "trade_date",
        "prev_close",
        "open_price",
        "high_price",
        "low_price",
        "last_price",
        "close_price",
        "avg_price",
        "volume",
        "turnover_lacs",
        "trades",
        "delivery_qty",
        "delivery_pct",
    ]
    df = df[[col for col in needed if col in df.columns]].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["series"] = df["series"].astype(str).str.strip().str.upper()
    if universe is None:
        from universe import SERIES_WHITELIST
        df = df[df["series"].isin(SERIES_WHITELIST)]
    else:
        df = df[df["symbol"].isin(universe)]
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str).str.strip(), format="%d-%b-%Y", errors="coerce")
    for col in ["prev_close", "open_price", "high_price", "low_price", "last_price", "close_price", "avg_price", "volume", "turnover_lacs", "trades", "delivery_qty", "delivery_pct"]:
        if col in df.columns:
            df[col] = to_number(df[col])
    df["turnover_cr"] = df["turnover_lacs"] / 100.0
    df["series_priority"] = np.where(df["series"] == "EQ", 0, 1)
    df = df.sort_values(["symbol", "trade_date", "series_priority"]).drop_duplicates(["symbol", "trade_date"], keep="first")
    return df.drop(columns=["series_priority"], errors="ignore")


# Files read between duplicate-collapsing passes in build_prices.
BHAV_DEDUPE_BATCH = 100


def build_prices(universe: set[str] | None = None) -> pd.DataFrame:
    # Include downloads/ so a session that never made it to archive/daily is still rebuilt.
    downloads = INPUT_DIR / "downloads"
    files = set(ARCHIVE_DIR.glob("sec_bhavdata_full_*.csv")) | set(DAILY_DIR.glob("sec_bhavdata_full_*.csv"))
    files |= set((ARCHIVE_DIR / "backfill" / "bhav").glob("sec_bhavdata_full_*.csv"))
    if downloads.exists():
        files |= set(downloads.rglob("sec_bhavdata_full_*.csv"))
    files = sorted(files)
    # The same session usually exists in several folders (archive, backfill, downloads), so the
    # raw rows are several times the final table. Collapse duplicates every BHAV_DEDUPE_BATCH
    # files instead of concatenating everything first: the (symbol, trade_date) row that wins is
    # still the one from the last file in sorted order (stable sort, keep="last"), but peak
    # memory is bounded by the de-duplicated table instead of every file's rows at once.
    batches: list[pd.DataFrame] = []
    frames: list[pd.DataFrame] = []

    def _collapse(parts: list[pd.DataFrame]) -> pd.DataFrame:
        out = pd.concat(parts, ignore_index=True)
        out = out.dropna(subset=["symbol", "trade_date", "close_price"])
        return out.sort_values(["symbol", "trade_date"], kind="stable").drop_duplicates(["symbol", "trade_date"], keep="last")

    for path in files:
        try:
            frame = read_bhavcopy(path, universe)
            if not frame.empty:
                frames.append(frame)
        except Exception as exc:
            print(f"Skipped {path.name}: {exc}")
        if len(frames) >= BHAV_DEDUPE_BATCH:
            batches.append(_collapse(frames))
            frames = []
            if len(batches) > 1:
                batches = [_collapse(batches)]
    if frames:
        batches.append(_collapse(frames))
    if not batches:
        raise RuntimeError("No bhavcopy files could be loaded.")
    prices = pd.concat(batches, ignore_index=True)
    del batches, frames
    prices = prices.dropna(subset=["symbol", "trade_date", "close_price"])
    prices = prices.sort_values(["symbol", "trade_date"], kind="stable").drop_duplicates(["symbol", "trade_date"], keep="last")
    if universe is None:
        prices = apply_reference_symbol_changes(prices)
    return prices


def load_symbol_changes() -> pd.DataFrame | None:
    """Parsed Input/reference/symbolchange.csv, or None when the file is absent."""
    changes_path = INPUT_DIR / "reference" / "symbolchange.csv"
    if not changes_path.exists() or changes_path.stat().st_size == 0:
        return None
    from symbol_changes import parse_symbol_changes

    return parse_symbol_changes(changes_path)


def apply_reference_symbol_changes(prices: pd.DataFrame) -> pd.DataFrame:
    """Move every old-symbol row dated before its change onto the new symbol (HEG -> HEGAM),
    so a renamed security is one continuous series. Shared by the full build and the append."""
    changes = load_symbol_changes()
    if changes is None or changes.empty:
        return prices
    from universe import apply_symbol_changes

    return apply_symbol_changes(prices, changes)


MCAP_COLUMNS = ["symbol", "security_name", "market_cap_cr", "market_cap_date", "issue_size"]


def parse_market_cap_frame(df: pd.DataFrame) -> pd.DataFrame:
    market_cap_col = next((c for c in df.columns if c.startswith("market_cap")), None)
    if not market_cap_col or "symbol" not in df.columns:
        return pd.DataFrame(columns=MCAP_COLUMNS)
    if "series" in df.columns:
        # NSE appends Listed / Permitted / Total summary rows with a blank series.
        df = df[df["series"].fillna("").astype(str).str.strip() != ""]
    out = pd.DataFrame()
    out["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    out["security_name"] = df.get("security_name", pd.Series("", index=df.index)).astype(str).str.strip()
    out["market_cap_cr"] = to_number(df[market_cap_col]) / 10_000_000
    out["market_cap_date"] = pd.to_datetime(df.get("trade_date", ""), format="%d %b %Y", errors="coerce")
    issue_size_col = next((c for c in df.columns if c.startswith("issue_size")), None)
    out["issue_size"] = to_number(df[issue_size_col]) if issue_size_col else np.nan
    return out.drop_duplicates("symbol", keep="last").reset_index(drop=True)


def read_market_cap() -> pd.DataFrame:
    path = latest_file(DAILY_DIR, "mcap*.csv")
    if not path:
        return pd.DataFrame(columns=MCAP_COLUMNS)
    return parse_market_cap_frame(clean_columns(pd.read_csv(path, dtype=str, skipinitialspace=True)))


def read_price_band() -> pd.DataFrame:
    path = latest_file(DAILY_DIR, "sec_list_*.csv")
    if not path:
        return pd.DataFrame(columns=["symbol", "band", "band_remarks"])
    df = clean_columns(pd.read_csv(path, dtype=str))
    return pd.DataFrame(
        {
            "symbol": df["symbol"].astype(str).str.strip().str.upper(),
            "band": to_number(df.get("band", pd.Series(dtype=str))),
            "band_remarks": df.get("remarks", "").astype(str).str.strip(),
        }
    ).drop_duplicates("symbol", keep="last")


def read_pe() -> pd.DataFrame:
    path = latest_file(DAILY_DIR, "PE_*.csv")
    if not path:
        return pd.DataFrame(columns=["symbol", "pe", "adjusted_pe"])
    df = clean_columns(pd.read_csv(path, dtype=str))
    return pd.DataFrame(
        {
            "symbol": df["symbol"].astype(str).str.strip().str.upper(),
            "pe": to_number(df.get("symbol_p/e", pd.Series(dtype=str))),
            "adjusted_pe": to_number(df.get("adjusted_p/e", pd.Series(dtype=str))),
        }
    ).drop_duplicates("symbol", keep="last")


def read_52_week() -> pd.DataFrame:
    path = latest_file(DAILY_DIR, "CM_52_wk_High_low_*.csv")
    if not path:
        return pd.DataFrame(columns=["symbol", "high_52w", "low_52w"])
    df = clean_columns(pd.read_csv(path, dtype=str, skiprows=2))
    return pd.DataFrame(
        {
            "symbol": df["symbol"].astype(str).str.strip().str.upper(),
            "series": df["series"].astype(str).str.strip().str.upper(),
            "high_52w": to_number(df.get("adjusted_52_week_high", pd.Series(dtype=str))),
            "high_52w_date": pd.to_datetime(df.get("52_week_high_date", ""), format="%d-%b-%Y", errors="coerce"),
            "low_52w": to_number(df.get("adjusted_52_week_low", pd.Series(dtype=str))),
            "low_52w_date": pd.to_datetime(df.get("52_week_low_dt", ""), format="%d-%b-%Y", errors="coerce"),
        }
    ).drop_duplicates("symbol", keep="last")


def _empty_deals_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["deal_type", "trade_date", "symbol", "security_name", "client_name", "side", "quantity", "price", "source_file"]
    )


def _series_col(df: pd.DataFrame, *candidates: str) -> pd.Series:
    """Return the first matching column as a Series; never a bare default string."""
    for name in candidates:
        if name in df.columns:
            return df[name]
    return pd.Series([pd.NA] * len(df), index=df.index, dtype="object")


def read_deals(path: Path, deal_type: str) -> pd.DataFrame:
    """Parse NSE bulk/block CSV (daily archive format or historical range export)."""
    if not path.exists():
        return _empty_deals_frame()
    try:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", skipinitialspace=True)
    except Exception:
        try:
            df = pd.read_csv(path, dtype=str, encoding="cp1252", skipinitialspace=True)
        except Exception as exc:
            print(f"Skipped deals file {path.name}: {exc}")
            return _empty_deals_frame()
    df = clean_columns(df)
    if df.empty:
        return _empty_deals_frame()
    # Historical exports clean to buy_/_sell; daily files clean to buy/sell.
    date_s = _series_col(df, "date", "bd_dt_date", "timestamp")
    if date_s.astype(str).str.strip().str.upper().eq("NO RECORDS").any() and len(df) <= 2:
        return _empty_deals_frame()
    first_date = str(date_s.iloc[0]).strip().upper() if len(date_s) else ""
    if first_date in {"NO RECORDS", "NAN", ""}:
        # Single NO RECORDS row, or unusable file
        non_empty = date_s.astype(str).str.strip().str.upper().replace({"NAN": "", "NONE": ""})
        if non_empty.eq("").all() or non_empty.eq("NO RECORDS").all():
            return _empty_deals_frame()

    side_s = _series_col(df, "buy/sell", "buy_/_sell", "buy_sell", "bd_buy_sell")
    qty_s = _series_col(df, "quantity_traded", "quantity", "bd_qty_trd")
    price_s = _series_col(
        df,
        "trade_price_/_wght._avg._price",
        "trade_price_/_wght_avg_price",
        "trade_price",
        "bd_tp_watp",
        "price",
    )
    symbol_s = _series_col(df, "symbol", "bd_symbol")
    security_s = _series_col(df, "security_name", "bd_scrip_name")
    client_s = _series_col(df, "client_name", "bd_client_name")

    trade_date = pd.to_datetime(date_s.astype(str).str.strip(), format="%d-%b-%Y", errors="coerce")
    if trade_date.isna().all():
        trade_date = pd.to_datetime(date_s.astype(str).str.strip(), dayfirst=True, errors="coerce")

    out = pd.DataFrame(
        {
            "deal_type": deal_type,
            "trade_date": trade_date,
            "symbol": symbol_s.astype(str).str.strip().str.upper(),
            "security_name": security_s.astype(str).str.strip(),
            "client_name": client_s.astype(str).str.strip(),
            "side": side_s.astype(str).str.strip().str.upper().str.replace(r"\s+", "", regex=True),
            "quantity": to_number(qty_s),
            "price": to_number(price_s),
            "source_file": path.name,
        }
    )
    # Drop junk rows (NO RECORDS, blank symbols)
    out = out[~out["symbol"].isin({"", "NAN", "NONE", "NO RECORDS", "SYMBOL"})]
    out = out[out["side"].isin({"BUY", "SELL"})]
    return out.reset_index(drop=True)


def _deal_file_sort_key(path: Path) -> tuple:
    """Process single-day files first; multi-day range exports last so they win on dedupe."""
    name = path.name.lower()
    is_range = ("-to-" in name) or name.startswith("bulk-deals") or name.startswith("block-deals")
    return (1 if is_range else 0, name)


def _iter_deal_paths(folder: Path, kind: str) -> list[Path]:
    """kind is 'bulk' or 'block'. Collect daily and historical range filenames."""
    if not folder.exists():
        return []
    patterns = (
        f"{kind}*.csv",
        f"{kind.capitalize()}*.csv",
        f"{kind.capitalize()}-Deals*.csv",
        f"{kind.upper()}-Deals*.csv",
    )
    found: dict[str, Path] = {}
    for pattern in patterns:
        for path in folder.glob(pattern):
            # Avoid treating non-deal CSVs; require name stem to start with bulk/block
            stem = path.name.lower()
            if not stem.startswith(kind):
                continue
            found[str(path.resolve()).lower()] = path
    return sorted(found.values(), key=_deal_file_sort_key)


PRINT_KEY = ["trade_date", "symbol", "client_name", "side", "quantity", "price"]


def collapse_cross_listed_prints(deals: pd.DataFrame) -> pd.DataFrame:
    """A block deal above 0.5% of equity also appears in the bulk file; keep one row per print."""
    if deals.empty:
        return deals
    types = deals.groupby(PRINT_KEY, dropna=False)["deal_type"].transform(lambda s: "+".join(sorted(set(s.astype(str)))))
    out = deals.assign(deal_type=types)
    return out.drop_duplicates(PRINT_KEY, keep="last").reset_index(drop=True)


def read_all_deals() -> pd.DataFrame:
    """Load bulk/block from archive, daily, and downloads/DDMMYYYY/ (dated sessions)."""
    from config import INPUT_DIR

    frames = []
    folders = [ARCHIVE_DIR, DAILY_DIR]
    downloads = Path(INPUT_DIR) / "downloads"
    if downloads.exists():
        # Each session folder may hold bulk.csv / block.csv for that day
        folders.extend(sorted(p for p in downloads.iterdir() if p.is_dir() and p.name != "_probe"))
    for folder in folders:
        for path in _iter_deal_paths(folder, "bulk"):
            frames.append(read_deals(path, "Bulk"))
        for path in _iter_deal_paths(folder, "block"):
            frames.append(read_deals(path, "Block"))
    if not frames:
        return _empty_deals_frame()
    deals = pd.concat(frames, ignore_index=True)
    if deals.empty:
        return _empty_deals_frame()
    deals["trade_date"] = pd.to_datetime(deals["trade_date"], errors="coerce")
    deals = deals.dropna(subset=["trade_date", "symbol", "side", "quantity", "price"])
    deals["symbol"] = deals["symbol"].astype(str).str.strip().str.upper()
    deals["client_name"] = deals["client_name"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    deals["side"] = deals["side"].astype(str).str.strip().str.upper()
    # Range files sorted last → keep="last" prefers the historical export on conflicts.
    deals = deals.drop_duplicates(
        ["deal_type", "trade_date", "symbol", "client_name", "side", "quantity", "price"],
        keep="last",
    )
    deals = collapse_cross_listed_prints(deals)
    deals["deal_value_cr"] = deals["quantity"] * deals["price"] / 10_000_000
    return deals.sort_values(["trade_date", "deal_type", "symbol", "side", "client_name"]).reset_index(drop=True)


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    return rsi_wilder(close, period=period)


def rsi_divergence_flags(price: pd.Series, rsi: pd.Series) -> tuple[pd.Series, pd.Series]:
    swing_low = (price < price.shift(1)) & (price <= price.shift(-1))
    swing_high = (price > price.shift(1)) & (price >= price.shift(-1))
    low_price = price.where(swing_low)
    low_rsi = rsi.where(swing_low)
    high_price = price.where(swing_high)
    high_rsi = rsi.where(swing_high)
    prev_low_price = low_price.ffill().shift(1)
    prev_low_rsi = low_rsi.ffill().shift(1)
    prev_high_price = high_price.ffill().shift(1)
    prev_high_rsi = high_rsi.ffill().shift(1)
    bullish = swing_low & (price < prev_low_price) & (rsi > prev_low_rsi)
    bearish = swing_high & (price > prev_high_price) & (rsi < prev_high_rsi)
    return bullish.fillna(False), bearish.fillna(False)


def candle_features(bars: pd.DataFrame) -> pd.DataFrame:
    bars = bars.copy()
    day_range = (bars["high_price"] - bars["low_price"]).replace(0, np.nan)
    bars["body_pct"] = (bars["close_price"] - bars["open_price"]).abs() / day_range * 100
    bars["upper_wick_pct"] = (bars["high_price"] - pd.concat([bars["close_price"], bars["open_price"]], axis=1).max(axis=1)) / day_range * 100
    bars["lower_wick_pct"] = (pd.concat([bars["close_price"], bars["open_price"]], axis=1).min(axis=1) - bars["low_price"]) / day_range * 100
    bars["close_location_pct"] = (bars["close_price"] - bars["low_price"]) / day_range * 100
    small_body = bars["body_pct"] <= 35
    bars["confirmed_morning_star"] = (
        (bars["close_price"].shift(2) < bars["open_price"].shift(2))
        & small_body.shift(1)
        & (bars["close_price"] > bars["open_price"])
        & (bars["close_price"] > ((bars["open_price"].shift(2) + bars["close_price"].shift(2)) / 2))
        & (bars["close_price"].shift(2) < bars["close_price"].shift(7))
        & (bars["close_location_pct"] >= 60)
    )
    bars["confirmed_shooting_star"] = (
        (bars["upper_wick_pct"] >= 50)
        & (bars["lower_wick_pct"] <= 20)
        & (bars["close_location_pct"] <= 40)
        & (bars["close_price"] > bars["close_price"].shift(10))
    )
    return bars


def resampled_timeframe_features(g: pd.DataFrame, rule: str) -> pd.DataFrame:
    bars = (
        g.set_index("trade_date")
        .resample(rule)
        .agg(
            open_price=("open_price", "first"),
            high_price=("high_price", "max"),
            low_price=("low_price", "min"),
            close_price=("close_price", "last"),
            volume=("volume", "sum"),
        )
        .dropna(subset=["open_price", "high_price", "low_price", "close_price"])
    )
    if bars.empty:
        return bars
    bars = candle_features(bars)
    bars["rsi_14"] = rsi_wilder(bars["close_price"])
    bars["bullish_rsi_divergence"], bars["bearish_rsi_divergence"] = rsi_divergence_flags(bars["close_price"], bars["rsi_14"])
    return bars


def _calc_single_symbol_indicators(group: pd.DataFrame) -> pd.DataFrame:
    """Every per-symbol indicator column for one symbol's full history (rows by trade_date)."""
    return _higher_timeframe_features(_daily_symbol_features(group))


# Rows of trailing history the incremental append loads per symbol for the RS rank inputs
# (the 40/20/20/20 quarterly mix looks back 252 rows) - with margin.
DAILY_LOOKBACK_ROWS = 300


def _daily_symbol_features(group: pd.DataFrame) -> pd.DataFrame:
    """Daily-bar indicator columns of one symbol (first half of the per-symbol pass)."""
    g = group.copy().sort_values("trade_date")
    close = g["close_price"]
    high = g["high_price"]
    low = g["low_price"]
    prev_close = close.shift(1)
    for window in EMA_WINDOWS:
        g[f"ema_{window}"] = ema(close, span=window)
    g["sma_50"] = sma(close, 50)
    g["sma_150"] = sma(close, 150)
    g["sma_200"] = sma(close, 200)
    g["sma_200_rising"] = g["sma_200"] > g["sma_200"].shift(20)
    for name, window in RETURN_WINDOWS.items():
        g[name] = (close / close.shift(window) - 1) * 100
    g["rsi_14"] = rsi_wilder(close)
    g["bullish_rsi_divergence"], g["bearish_rsi_divergence"] = rsi_divergence_flags(close, g["rsi_14"])
    g["avg_volume_5d"] = g["volume"].rolling(5, min_periods=3).mean()
    g["avg_volume_10d"] = g["volume"].rolling(10, min_periods=3).mean()
    g["avg_volume_20d"] = g["volume"].rolling(20, min_periods=5).mean()
    g["avg_volume_50d"] = g["volume"].rolling(50, min_periods=10).mean()
    g["avg_traded_value_cr_20d"] = g["turnover_cr"].rolling(20, min_periods=5).mean()
    g["avg_traded_value_cr_50d"] = g["turnover_cr"].rolling(50, min_periods=10).mean()
    g["rvol"] = rvol(g["volume"], window=20)
    g["avg_delivery_qty_20d"] = g["delivery_qty"].rolling(20, min_periods=5).mean()
    g["avg_delivery_pct_20d"] = g["delivery_pct"].rolling(20, min_periods=5).mean()
    g["delivery_spike"] = g["delivery_qty"] > (2 * g["avg_delivery_qty_20d"])
    g["true_range"] = true_range(high, low, close)
    g["atr_14"] = atr_sma(high, low, close, period=14)
    g["atr_pct"] = g["atr_14"] / close * 100
    g["adr_20_pct"] = adr_pct(high, low, window=20)
    g["atr_14_wilder"] = atr_wilder(high, low, close, period=14)
    g["atr_pct_wilder"] = g["atr_14_wilder"] / close * 100
    # Primary risk volatility uses the standard Wilder smoothing. Keep
    # legacy ``atr_pct`` intact for compatibility with older snapshots.
    g["atr_pct_primary"] = g["atr_pct_wilder"]
    g["atr_pct_avg_5d"] = g["atr_pct"].rolling(5, min_periods=3).mean()
    g["atr_pct_avg_20d"] = g["atr_pct"].rolling(20, min_periods=5).mean()
    g["atr_pct_avg_50d"] = g["atr_pct"].rolling(50, min_periods=10).mean()
    day_range = (high - low).replace(0, np.nan)
    g["body_pct"] = (close - g["open_price"]).abs() / day_range * 100
    g["upper_wick_pct"] = (high - pd.concat([close, g["open_price"]], axis=1).max(axis=1)) / day_range * 100
    g["lower_wick_pct"] = (pd.concat([close, g["open_price"]], axis=1).min(axis=1) - low) / day_range * 100
    g["close_location_pct"] = (close - low) / day_range * 100
    if "trades" in g.columns:
        g["avg_trade_size"] = g["volume"] / g["trades"].replace(0, np.nan)
        g["avg_trade_size_20d"] = g["avg_trade_size"].rolling(20, min_periods=5).mean()
    if "avg_price" in g.columns:
        g["vwap_distance_pct"] = (close / g["avg_price"].replace(0, np.nan) - 1) * 100
    for window in [5, 10, 20, 50, 100, 252]:
        g[f"high_{window}d"] = high.rolling(window, min_periods=3).max()
        g[f"low_{window}d"] = low.rolling(window, min_periods=3).min()
        g[f"range_{window}d_pct"] = (g[f"high_{window}d"] - g[f"low_{window}d"]) / close * 100
    g["database_high"] = high.cummax()
    g["ema_200_rising"] = g["ema_200"] > g["ema_200"].shift(20)
    g["away_10ema_pct"] = (close / g["ema_10"] - 1) * 100
    g["away_20ema_pct"] = (close / g["ema_20"] - 1) * 100
    g["away_50ema_pct"] = (close / g["ema_50"] - 1) * 100
    g["away_database_high_pct"] = (close / g["database_high"] - 1) * 100
    g["price_up_delivery_up"] = (close > prev_close) & (g["delivery_qty"] > g["avg_delivery_qty_20d"])
    g["fresh_200ema_reclaim"] = (prev_close <= g["ema_200"].shift(1)) & (close > g["ema_200"])
    g["ema_10_cross_200"] = (g["ema_10"] > g["ema_200"]) & (g["ema_10"].shift(1) <= g["ema_200"].shift(1))
    g["ema_stack_bullish"] = (g["ema_10"] > g["ema_20"]) & (g["ema_20"] > g["ema_50"]) & (g["ema_50"] > g["ema_100"]) & (g["ema_100"] > g["ema_200"])
    g["new_20d_high"] = close >= g["high_20d"].shift(1)
    g["new_50d_high"] = close >= g["high_50d"].shift(1)
    g["new_100d_high"] = close >= g["high_100d"].shift(1)
    g["ema_shakeout"] = ((low < g["ema_10"]) | (low < g["ema_20"])) & (close > g["ema_10"]) & (g["close_location_pct"] >= 60)
    g["shakeout"] = (low < g["low_10d"].shift(1)) & (close > g["low_10d"].shift(1)) & (g["close_location_pct"] >= 60)
    g["hammer"] = (g["lower_wick_pct"] >= 50) & (g["upper_wick_pct"] <= 20) & (g["close_location_pct"] >= 60)
    g["shooting_star"] = (g["upper_wick_pct"] >= 50) & (g["lower_wick_pct"] <= 20) & (g["close_location_pct"] <= 40) & (close > close.shift(10))
    g["bullish_engulfing"] = (close > g["open_price"]) & (prev_close < g["open_price"].shift(1)) & (close >= g["open_price"].shift(1)) & (g["open_price"] <= prev_close)
    g["inside_bar"] = (high < high.shift(1)) & (low > low.shift(1))
    g["nr7"] = day_range == day_range.rolling(7, min_periods=7).min()
    small_body = g["body_pct"] <= 35
    g["morning_star"] = (
        (close.shift(2) < g["open_price"].shift(2))
        & small_body.shift(1)
        & (close > g["open_price"])
        & (close > ((g["open_price"].shift(2) + close.shift(2)) / 2))
    )
    g["confirmed_morning_star"] = g["morning_star"] & (close.shift(2) < close.shift(7)) & (g["close_location_pct"] >= 60)
    g["confirmed_hammer"] = g["hammer"] & (close < close.shift(5)) & (g["close_location_pct"] >= 60)
    g["confirmed_bullish_engulfing"] = g["bullish_engulfing"] & (close.shift(1) < close.shift(6))
    g["confirmed_shooting_star"] = g["shooting_star"] & (close > close.shift(10)) & (g["away_database_high_pct"] >= -15)
    return g.copy()


def _higher_timeframe_features(g: pd.DataFrame) -> pd.DataFrame:
    """Weekly / monthly columns for the rows of ``g`` (second half of the per-symbol pass)."""
    bars = g
    close = g["close_price"]
    weekly_features = resampled_timeframe_features(bars, "W-FRI")
    monthly_features = resampled_timeframe_features(bars, "ME")
    if not weekly_features.empty:
        weekly = weekly_features["close_price"]
        weekly_ema = weekly.ewm(span=10, adjust=False, min_periods=10).mean()
        weekly_ema_200 = weekly.ewm(span=200, adjust=False, min_periods=10).mean()
        weekly_ma30 = weekly.rolling(30, min_periods=10).mean()
        weekly_10_cross_200 = (weekly_ema > weekly_ema_200) & (weekly_ema.shift(1) <= weekly_ema_200.shift(1))
        g["wema_10"] = weekly_ema.reindex(g["trade_date"], method="ffill").to_numpy()
        g["wema_200"] = weekly_ema_200.reindex(g["trade_date"], method="ffill").to_numpy()
        g["wema_10_cross_200"] = weekly_10_cross_200.reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
        weekly_completed = weekly_ohlc(bars, as_of=bars["trade_date"].max())
        if not weekly_completed.empty:
            w20_close = weekly_completed.set_index(pd.to_datetime(weekly_completed["trade_date"]))["close_price"]
            weekly_ema_20 = w20_close.ewm(span=20, adjust=False, min_periods=20).mean()
            g["wema_20"] = weekly_ema_20.reindex(
                pd.DatetimeIndex(pd.to_datetime(g["trade_date"])), method="ffill"
            ).to_numpy()
        else:
            g["wema_20"] = np.nan
        g["wma_30"] = weekly_ma30.reindex(g["trade_date"], method="ffill").to_numpy()
        g["rsi_14_w"] = weekly_features["rsi_14"].reindex(g["trade_date"], method="ffill").to_numpy()
        g["confirmed_morning_star_w"] = weekly_features["confirmed_morning_star"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
        g["confirmed_shooting_star_w"] = weekly_features["confirmed_shooting_star"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
        g["bullish_rsi_divergence_w"] = weekly_features["bullish_rsi_divergence"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
        g["bearish_rsi_divergence_w"] = weekly_features["bearish_rsi_divergence"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
    else:
        g["wema_10"] = np.nan
        g["wema_200"] = np.nan
        g["wema_20"] = np.nan
        g["wema_10_cross_200"] = False
        g["wma_30"] = np.nan
        g["rsi_14_w"] = np.nan
        g["confirmed_morning_star_w"] = False
        g["confirmed_shooting_star_w"] = False
        g["bullish_rsi_divergence_w"] = False
        g["bearish_rsi_divergence_w"] = False
    if not monthly_features.empty:
        monthly = monthly_features["close_price"]
        monthly_ema = monthly.ewm(span=10, adjust=False, min_periods=10).mean()
        monthly_ema_200 = monthly.ewm(span=200, adjust=False, min_periods=10).mean()
        monthly_10_cross_200 = (monthly_ema > monthly_ema_200) & (monthly_ema.shift(1) <= monthly_ema_200.shift(1))
        g["mema_10"] = monthly_ema.reindex(g["trade_date"], method="ffill").to_numpy()
        g["mema_200"] = monthly_ema_200.reindex(g["trade_date"], method="ffill").to_numpy()
        g["mema_10_cross_200"] = monthly_10_cross_200.reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
        g["rsi_14_m"] = monthly_features["rsi_14"].reindex(g["trade_date"], method="ffill").to_numpy()
        g["confirmed_morning_star_m"] = monthly_features["confirmed_morning_star"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
        g["confirmed_shooting_star_m"] = monthly_features["confirmed_shooting_star"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
        g["bullish_rsi_divergence_m"] = monthly_features["bullish_rsi_divergence"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
        g["bearish_rsi_divergence_m"] = monthly_features["bearish_rsi_divergence"].reindex(g["trade_date"], method="ffill").fillna(False).to_numpy()
    else:
        g["mema_10"] = np.nan
        g["mema_200"] = np.nan
        g["mema_10_cross_200"] = False
        g["rsi_14_m"] = np.nan
        g["confirmed_morning_star_m"] = False
        g["confirmed_shooting_star_m"] = False
        g["bullish_rsi_divergence_m"] = False
        g["bearish_rsi_divergence_m"] = False
    g["away_10wema_pct"] = (close / g["wema_10"] - 1) * 100
    g["away_10mema_pct"] = (close / g["mema_10"] - 1) * 100
    return g.copy()


def _calc_symbol_indicators_chunk(groups: list[pd.DataFrame]) -> list[pd.DataFrame]:
    """Worker task processing a batch of symbol groups in parallel."""
    return [_calc_single_symbol_indicators(group) for group in groups]


def multiprocessing_settings() -> tuple[bool, int]:
    """(use a process pool?, worker count) - MP_DISABLE_MULTIPROCESSING=1 forces sequential."""
    disable_mp = os.environ.get("MP_DISABLE_MULTIPROCESSING", "").strip().lower() in {"1", "true", "yes", "on"}
    num_cores = max(1, min(os.cpu_count() or 4, 10))
    return (not disable_mp and num_cores > 1), num_cores


def per_symbol_indicators(prices: pd.DataFrame) -> pd.DataFrame:
    """Step 5a: `_calc_single_symbol_indicators` for every symbol, rows in (symbol, trade_date) order."""
    df = prices.sort_values(["symbol", "trade_date"]).copy()
    parts: list[pd.DataFrame] = []
    groups = [group for _, group in df.groupby("symbol", sort=False)]
    total_symbols = len(groups)
    t_start = time.time()

    use_mp, num_cores = multiprocessing_settings()

    if use_mp and total_symbols > 50:
        chunk_size = max(10, total_symbols // (num_cores * 4))
        chunks = [groups[i : i + chunk_size] for i in range(0, total_symbols, chunk_size)]
        completed_symbols = 0
        try:
            with concurrent.futures.ProcessPoolExecutor(max_workers=num_cores) as executor:
                for chunk_res in executor.map(_calc_symbol_indicators_chunk, chunks):
                    parts.extend(chunk_res)
                    completed_symbols += len(chunk_res)
                    pct = (completed_symbols / total_symbols) * 100
                    elapsed = time.time() - t_start
                    if completed_symbols % 200 < chunk_size or completed_symbols == total_symbols:
                        print(
                            f"  5a/8: Calculating stock indicators ({num_cores} cores): {completed_symbols:,}/{total_symbols:,} stocks ({pct:.1f}%) [{elapsed:.0f}s elapsed]...",
                            flush=True,
                        )
        except Exception as exc:
            print(f"Warning: Multiprocessing encountered an issue ({exc}); falling back to sequential execution.", flush=True)
            parts.clear()
            for idx, group in enumerate(groups, start=1):
                if idx == 1 or idx % 200 == 0 or idx == total_symbols:
                    elapsed = time.time() - t_start
                    pct = (idx / total_symbols) * 100
                    print(f"  5a/8: Calculating stock indicators (sequential fallback): {idx:,}/{total_symbols:,} stocks ({pct:.1f}%) [{elapsed:.0f}s elapsed]...", flush=True)
                parts.append(_calc_single_symbol_indicators(group))
    else:
        for idx, group in enumerate(groups, start=1):
            if idx == 1 or idx % 200 == 0 or idx == total_symbols:
                elapsed = time.time() - t_start
                pct = (idx / total_symbols) * 100
                print(f"  5a/8: Calculating stock indicators: {idx:,}/{total_symbols:,} stocks ({pct:.1f}%) [{elapsed:.0f}s elapsed]...", flush=True)
            parts.append(_calc_single_symbol_indicators(group))

    return pd.concat(parts, ignore_index=True)


def attach_52w_reference(indicators: pd.DataFrame, enrichment: pd.DataFrame) -> pd.DataFrame:
    """Step 5b: point-in-time NSE 52-week high/low (as-of join) + the row-wise columns built on it.

    Every value is per row (as-of by the row's own symbol and date), so any subset of rows gives
    the same values as the whole table.
    """
    # Point-in-time 52W: as-of join when enrichment has effective_date history.
    # Never paint a future 52W onto older rows. If NSE snapshot missing, fall back
    # to rolling 252-session high/low already on the row (leak-free).
    if "effective_date" in enrichment.columns:
        try:
            keys = indicators[["symbol", "trade_date"]].copy()
            keys["_row"] = np.arange(len(keys))
            reference_rows = asof_reference(enrichment, keys[["symbol", "trade_date", "_row"]])
            # Restore original indicator row order via _row if present, else _input_order
            order_col = "_row" if "_row" in reference_rows.columns else None
            if order_col:
                reference_rows = reference_rows.sort_values(order_col)
            if len(reference_rows) != len(indicators):
                raise ValueError(
                    f"as-of join length mismatch: {len(reference_rows)} vs {len(indicators)}"
                )
            nse_high = pd.to_numeric(reference_rows["high_52w"], errors="coerce")
            nse_low = pd.to_numeric(reference_rows["low_52w"], errors="coerce")
            if "high_52w_date" in reference_rows.columns:
                indicators["high_52w_date"] = pd.to_datetime(reference_rows["high_52w_date"], errors="coerce").dt.normalize().to_numpy()
            if "band_remarks" in reference_rows.columns:
                indicators["band_remarks"] = reference_rows["band_remarks"].fillna("").astype(str).to_numpy()
        except MemoryError:
            raise  # out of memory is a failed build, never a silent 252d fallback
        except Exception as exc:
            print(f"Warning: as-of 52W join failed ({exc}); using only row-level 252d fallback.")
            nse_high = pd.to_numeric(indicators.get("high_252d"), errors="coerce")
            nse_low = pd.to_numeric(indicators.get("low_252d"), errors="coerce")
        if "high_52w" in indicators.columns:
            indicators = indicators.drop(columns=["high_52w"], errors="ignore")
        if "low_52w" in indicators.columns:
            indicators = indicators.drop(columns=["low_52w"], errors="ignore")
        indicators["high_52w"] = nse_high.to_numpy()
        indicators["low_52w"] = nse_low.to_numpy()
    else:
        high52 = enrichment[["symbol", "high_52w"]].dropna().drop_duplicates("symbol", keep="last")
        indicators = indicators.drop(columns=["high_52w"], errors="ignore").merge(high52, on="symbol", how="left")
        low52 = enrichment[["symbol", "low_52w"]].dropna().drop_duplicates("symbol", keep="last")
        indicators = indicators.drop(columns=["low_52w"], errors="ignore").merge(low52, on="symbol", how="left")
    # NSE's reported 52-week high/low (joined as-of each row's date) are adjusted by NSE only
    # up to that file's date: they sit on the price scale of the file date, i.e. the raw scale
    # of that row. `close_price` etc. here are back-adjusted to today's scale (calc_indicators
    # receives `indicator_input(prices)`, i.e. split/bonus-adjusted OHLCV). Multiplying by each
    # row's cumulative price_factor (product of the events after that row) moves the NSE values
    # onto today's scale too, so away_52w_high_pct/away_52w_low_pct (and everything derived
    # from them: near_52w_high, trend_template's tt_off_low/tt_near_high, pivot_proximity_score,
    # vcp_score/vcp_state) compare like-for-like scales. high_252d/low_252d below are already
    # computed from the adjusted OHLCV, so they need no rescaling.
    if "price_factor" in indicators.columns:
        _price_factor_52w = pd.to_numeric(indicators["price_factor"], errors="coerce").fillna(1.0)
        indicators["high_52w"] = indicators["high_52w"] * _price_factor_52w
        indicators["low_52w"] = indicators["low_52w"] * _price_factor_52w
    # Fallback: use computed 252d range when official 52W missing (older history)
    if "high_252d" in indicators.columns:
        indicators["high_52w"] = indicators["high_52w"].fillna(indicators["high_252d"])
    if "low_252d" in indicators.columns:
        indicators["low_52w"] = indicators["low_52w"].fillna(indicators["low_252d"])
    indicators["away_52w_high_pct"] = (indicators["close_price"] / indicators["high_52w"] - 1) * 100
    indicators["away_52w_low_pct"] = (indicators["close_price"] / indicators["low_52w"] - 1) * 100
    indicators["distance_below_52w"] = distance_below_high(indicators["close_price"], indicators["high_52w"])
    if "high_52w_date" in indicators.columns:
        indicators["is_fresh_52w_high"] = indicators["trade_date"] == indicators["high_52w_date"]
    return indicators


# Cross-sectional RS columns, in table order.
RANK_COLUMNS = (
    "rs_percentile_primary",
    "rs_percentile",
    "rs_percentile_no_fill",
    "rs_score_adaptive",
    "rs_percentile_ipo",
    "rs_rank_t5",
    "rs_rank_t15",
    "rs_rank_t30",
    "rs_1y_percentile",
    "rs_3m_percentile",
)
RS_LAGS = {"rs_rank_t5": 5, "rs_rank_t15": 15, "rs_rank_t30": 30}
# Rows of a symbol's own history the RS inputs look back over (252-session quarterly mix).
RS_LOOKBACK_ROWS = 252


def rs_rank_inputs(frame: pd.DataFrame) -> pd.DataFrame:
    """Per-row raw RS scores from each symbol's own close history (rows in (symbol, trade_date)
    order): the 40/20/20/20 quarterly mix, the adaptive IPO mix, 252d and 63d returns."""
    close_by_symbol = frame.groupby("symbol", sort=False)["close_price"]
    rs_latest_q = (frame["close_price"] / close_by_symbol.shift(63) - 1) * 100
    rs_prior_q2 = (close_by_symbol.shift(63) / close_by_symbol.shift(126) - 1) * 100
    rs_prior_q3 = (close_by_symbol.shift(126) / close_by_symbol.shift(189) - 1) * 100
    rs_prior_q4 = (close_by_symbol.shift(189) / close_by_symbol.shift(252) - 1) * 100
    rs_components = pd.concat([rs_latest_q, rs_prior_q2, rs_prior_q3, rs_prior_q4], axis=1)
    rs_score_no_fill = rs_components.mul([0.40, 0.20, 0.20, 0.20], axis=1).sum(axis=1, min_count=4)
    return pd.DataFrame(
        {
            "symbol": frame["symbol"],
            "trade_date": frame["trade_date"],
            "rs_score_no_fill": rs_score_no_fill,
            "rs_score_adaptive": close_by_symbol.transform(rs_adaptive_mix),
            # rs_1y = pure 252-day return (classic 1-year relative strength); rs_3m = 63-day return.
            "rs_1y": (frame["close_price"] / close_by_symbol.shift(252) - 1) * 100,
            "rs_3m": (frame["close_price"] / close_by_symbol.shift(63) - 1) * 100,
        },
        index=frame.index,
    )


def rs_percentiles(inputs: pd.DataFrame) -> pd.DataFrame:
    """Daily cross-sectional ranks (0-100, higher = stronger vs every stock that day) of
    `rs_rank_inputs`; every symbol trading on a ranked date must be present."""
    by_date = inputs["trade_date"]
    out = pd.DataFrame(index=inputs.index)
    # Production ladder is min_count=4 only. Adaptive IPO scores stay on side columns.
    out["rs_percentile_primary"] = inputs["rs_score_no_fill"].groupby(by_date).rank(pct=True) * 100
    out["rs_percentile_ipo"] = inputs["rs_score_adaptive"].groupby(by_date).rank(pct=True) * 100
    out["rs_1y_percentile"] = inputs["rs_1y"].groupby(by_date).rank(pct=True) * 100
    out["rs_3m_percentile"] = inputs["rs_3m"].groupby(by_date).rank(pct=True) * 100
    return out


def rs_rank_columns(inputs: pd.DataFrame, percentiles: pd.DataFrame | None = None) -> pd.DataFrame:
    """Step 5c: every RANK_COLUMNS column for `inputs` (rows in (symbol, trade_date) order).

    NOTE on RS: all are cross-sectional daily ranks (0-100). The rs_rank_t* columns are session
    lags of rs_percentile within each symbol, so the 30 rows before any row kept must be present.
    """
    pct = rs_percentiles(inputs) if percentiles is None else percentiles
    out = pd.DataFrame(index=inputs.index)
    out["rs_percentile_primary"] = pct["rs_percentile_primary"]
    out["rs_percentile"] = out["rs_percentile_primary"]
    out["rs_percentile_no_fill"] = out["rs_percentile_primary"]
    out["rs_score_adaptive"] = inputs["rs_score_adaptive"]
    out["rs_percentile_ipo"] = pct["rs_percentile_ipo"]
    for col, lag in RS_LAGS.items():
        out[col] = session_lag(out["rs_percentile"], inputs["symbol"], lag)
    out["rs_1y_percentile"] = pct["rs_1y_percentile"]
    out["rs_3m_percentile"] = pct["rs_3m_percentile"]
    return out[list(RANK_COLUMNS)]


def attach_benchmark_rs(
    indicators: pd.DataFrame,
    index_raw: pd.DataFrame | None = None,
    membership: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Steps 5c+/5c++: true RS vs Nifty 50 / MidSml 400 and RS vs the mapped sector index.

    Both are per-row excess returns over each symbol's own history, so symbol batches give the
    same values as the whole table. `index_raw` / `membership` default to loading from disk.
    """
    # True RS vs Nifty 50 / MidSml 400 (excess return, fail-closed). Peer rs_percentile stays primary.
    try:
        if isinstance(index_raw, BaseException):
            raise index_raw
        idx = load_all_index_history(ROOT_DIR) if index_raw is None else index_raw
        if idx is not None and not idx.empty:
            indicators = attach_true_rs_columns(indicators, idx)
        else:
            for _col in TRUE_RS_COLUMNS:
                if _col not in indicators.columns:
                    indicators[_col] = np.nan
    except MemoryError:
        raise  # out of memory is a failed build, never silently-NaN true RS
    except Exception as exc:
        print(f"  Warning: true RS skipped ({exc})", flush=True)
        for _col in TRUE_RS_COLUMNS:
            if _col not in indicators.columns:
                indicators[_col] = np.nan

    try:
        for failed in (index_raw, membership):
            if isinstance(failed, BaseException):
                raise failed
        _idx = load_all_index_history(ROOT_DIR) if index_raw is None else index_raw
        _mem = load_membership_csv() if membership is None else membership
        indicators = attach_sector_index_rs(indicators, _idx, _mem, None)
    except MemoryError:
        raise  # out of memory is a failed build, never silently-missing sector RS
    except Exception as exc:
        print(f"  Warning: sector-index RS skipped ({exc})", flush=True)
    return indicators


def calc_indicators(
    prices: pd.DataFrame | None,
    enrichment: pd.DataFrame,
    *,
    per_symbol: pd.DataFrame | None = None,
    rank_columns: pd.DataFrame | None = None,
    index_raw: pd.DataFrame | None = None,
    membership: pd.DataFrame | None = None,
    benchmark_columns: pd.DataFrame | None = None,
    quiet: bool = False,
) -> pd.DataFrame:
    """Every indicators_daily column for `prices` (indicator input, i.e. adjusted OHLCV).

    The streaming full build / incremental append call this per symbol batch with
    `per_symbol` (step 5a already done), `rank_columns` (the cross-sectional RS columns computed
    over all symbols, aligned to `per_symbol` rows) and preloaded `index_raw` / `membership`.
    The incremental append also passes `benchmark_columns` (steps 5c+/5c++ computed over each
    symbol's full history, aligned to the kept rows).
    """
    indicators = per_symbol_indicators(prices) if per_symbol is None else per_symbol
    if not quiet:
        print("  5b/8: Merging historical 52-week & reference snapshots (as-of join)...", flush=True)
    indicators = attach_52w_reference(indicators, enrichment)

    if not quiet:
        print("  5c/8: Computing cross-sectional relative strength percentiles...", flush=True)
    ranks = rs_rank_columns(rs_rank_inputs(indicators)) if rank_columns is None else rank_columns
    if len(ranks) != len(indicators):
        raise ValueError(f"rank columns have {len(ranks):,} rows for {len(indicators):,} indicator rows")
    for col in RANK_COLUMNS:
        indicators[col] = ranks[col].to_numpy()

    if not quiet:
        print("  5c+/8: Computing true RS vs index benches and mapped sector-index RS...", flush=True)
    if benchmark_columns is None:
        indicators = attach_benchmark_rs(indicators, index_raw, membership)
    else:
        for col in benchmark_columns.columns:
            indicators[col] = benchmark_columns[col].to_numpy()

    if not quiet:
        print("  5d/8: Evaluating trend templates, Darvas & VCP scoring...", flush=True)
    return finalize_indicator_scores(indicators)


def finalize_indicator_scores(indicators: pd.DataFrame) -> pd.DataFrame:
    """Step 5d: trend template, Darvas/VCP scores and setup flags - all row-wise."""
    close = indicators["close_price"]
    sma50 = indicators["sma_50"]
    sma150 = indicators["sma_150"]
    sma200 = indicators["sma_200"]
    tt_price_long = (close > sma150) & (close > sma200)
    tt_150_over_200 = sma150 > sma200
    tt_200_rising = indicators["sma_200_rising"].fillna(False)
    tt_50_stack = (sma50 > sma150) & (sma50 > sma200)
    tt_price_50 = close > sma50
    tt_off_low = indicators["away_52w_low_pct"] >= 30
    tt_near_high = indicators["distance_below_52w"] <= 25
    tt_rs = indicators["rs_percentile"] >= 70
    indicators["trend_template_pass_n"] = (
        tt_price_long.astype(int)
        + tt_150_over_200.astype(int)
        + tt_200_rising.astype(int)
        + tt_50_stack.astype(int)
        + tt_price_50.astype(int)
        + tt_off_low.astype(int)
        + tt_near_high.astype(int)
        + tt_rs.astype(int)
    )
    indicators["trend_template_pass"] = indicators["trend_template_pass_n"] == 8
    indicators["distance_to_high_pct_corrected"] = distance_below_high(indicators["close_price"], indicators["high_52w"])
    indicators["distance_to_high_pct"] = indicators["distance_to_high_pct_corrected"]
    indicators["trend_score"] = (
        (indicators["close_price"] > indicators["ema_50"]).astype(float) * 20
        + (indicators["close_price"] > indicators["ema_150"]).astype(float) * 20
        + (indicators["close_price"] > indicators["ema_200"]).astype(float) * 20
        + indicators["ema_200_rising"].fillna(False).astype(float) * 20
        + (indicators["rs_percentile"] >= 70).astype(float) * 20
    )
    indicators["contraction_score"] = (
        (indicators["range_5d_pct"] < indicators["range_10d_pct"]).astype(float) * 25
        + (indicators["range_10d_pct"] < indicators["range_20d_pct"]).astype(float) * 25
        + (indicators["atr_pct_avg_5d"] < indicators["atr_pct_avg_20d"]).astype(float) * 25
        + (indicators["atr_pct_avg_20d"] < indicators["atr_pct_avg_50d"]).astype(float) * 25
    )
    indicators["volume_dryup_pct"] = (1 - (indicators["avg_volume_5d"] / indicators["avg_volume_50d"])) * 100
    indicators["volume_dryup_score"] = (
        (indicators["avg_volume_5d"] < indicators["avg_volume_20d"]).astype(float) * 25
        + (indicators["avg_volume_5d"] < indicators["avg_volume_50d"]).astype(float) * 25
        + (indicators["rvol"] < 1).astype(float) * 25
        + (indicators["volume_dryup_pct"] > 20).astype(float) * 25
    )
    indicators["pivot_proximity_score"] = (100 - indicators["distance_to_high_pct"].clip(lower=0, upper=20) * 5).clip(lower=0, upper=100)
    indicators["vcp_score"] = (
        indicators["trend_score"] * 0.30
        + indicators["contraction_score"] * 0.30
        + indicators["volume_dryup_score"] * 0.25
        + indicators["pivot_proximity_score"] * 0.15
    )
    indicators["base_quality_score"] = indicators["vcp_score"]
    indicators["setup_class"] = setup_class(indicators)
    indicators["vcp_state"] = np.select(
        [
            indicators["close_price"] < indicators["ema_50"],
            (indicators["new_20d_high"]) & (indicators["rvol"] >= 1.5) & (indicators["trend_score"] >= 70),
            (indicators["vcp_score"] >= 70) & (indicators["distance_to_high_pct"] <= 5),
            indicators["vcp_score"] >= 55,
        ],
        ["Failed Breakout", "Breakout", "Near Pivot", "Building Base"],
        default="",
    )
    indicators["is_vcp"] = indicators["vcp_state"].isin(["Building Base", "Near Pivot", "Breakout"]) & (indicators["trend_score"] >= 60)
    indicators["near_52w_high"] = indicators["away_52w_high_pct"].between(-10, 0, inclusive="both")
    indicators["near_database_high"] = indicators["away_database_high_pct"].between(-10, 0, inclusive="both")
    indicators["near_high_tight"] = indicators["distance_to_high_pct"].le(5) & indicators["range_10d_pct"].le(indicators["range_50d_pct"] * 0.65)
    indicators["low_volatility_near_high"] = indicators["distance_to_high_pct"].le(10) & (indicators["atr_pct_avg_5d"] < indicators["atr_pct_avg_50d"])
    return indicators


def build_master(equity: pd.DataFrame, sector: pd.DataFrame, prices: pd.DataFrame, mcap: pd.DataFrame, bands: pd.DataFrame, pe: pd.DataFrame) -> pd.DataFrame:
    """One row per EQUITY_L symbol plus every symbol that traded in the latest session (renamed
    or BE/BZ-only listings EQUITY_L may lack). ``is_active`` marks symbols present in the latest
    session; delisted symbols that exist only in price history are not added."""
    latest_price = prices.sort_values("trade_date").drop_duplicates("symbol", keep="last")
    latest_date = latest_price["trade_date"].max() if not latest_price.empty else None
    active = set(latest_price.loc[latest_price["trade_date"] == latest_date, "symbol"]) if latest_date is not None else set()
    missing = sorted(active - set(equity["symbol"]))
    if missing:
        equity = pd.concat([equity, pd.DataFrame({"symbol": missing})], ignore_index=True)
    master = equity.merge(sector, on="symbol", how="left")
    master = master.merge(latest_price[["symbol", "series", "trade_date", "close_price"]], on="symbol", how="left")
    master = master.rename(columns={"series": "latest_series", "trade_date": "latest_price_date", "close_price": "latest_close"})
    mcap_join = mcap.drop(columns=["security_name"], errors="ignore")
    master = master.merge(mcap_join, on="symbol", how="left")
    master = master.merge(bands, on="symbol", how="left")
    master = master.merge(pe, on="symbol", how="left")
    if "security_name_x" in master.columns or "security_name_y" in master.columns:
        left = master["security_name_x"] if "security_name_x" in master.columns else master.get("security_name")
        right = master["security_name_y"] if "security_name_y" in master.columns else None
        if left is not None and right is not None:
            left_s = left.astype("string").str.strip().replace("", pd.NA)
            master["security_name"] = left_s.fillna(right)
        elif left is not None:
            master["security_name"] = left
        elif right is not None:
            master["security_name"] = right
        master = master.drop(columns=[c for c in ("security_name_x", "security_name_y") if c in master.columns])
    if missing and "security_name" in mcap.columns:
        names = mcap.dropna(subset=["security_name"]).drop_duplicates("symbol", keep="last").set_index("symbol")["security_name"]
        if "security_name" not in master.columns:
            master["security_name"] = pd.NA
        master["security_name"] = master["security_name"].fillna(master["symbol"].map(names))
    master["is_active"] = master["symbol"].isin(active)
    if "listing_date" in master.columns and "latest_price_date" in master.columns:
        l_dt = pd.to_datetime(master["listing_date"], errors="coerce")
        p_dt = pd.to_datetime(master["latest_price_date"], errors="coerce")
        master["ipo_age_days"] = (p_dt - l_dt).dt.days
    else:
        master["ipo_age_days"] = np.nan
    return master


def build_enrichment(mcap: pd.DataFrame, bands: pd.DataFrame, pe: pd.DataFrame, high52: pd.DataFrame, bulk: pd.DataFrame, block: pd.DataFrame) -> pd.DataFrame:
    symbols = set(mcap.get("symbol", [])) | set(bands.get("symbol", [])) | set(pe.get("symbol", [])) | set(high52.get("symbol", []))
    enrichment = pd.DataFrame({"symbol": sorted(symbols)})
    for frame in [mcap, bands, pe, high52]:
        enrichment = enrichment.merge(frame, on="symbol", how="left")
    deal_flags = pd.concat([bulk, block], ignore_index=True)
    if not deal_flags.empty:
        flags = deal_flags.assign(has_deal=True).groupby("symbol", as_index=False)["has_deal"].max()
        enrichment = enrichment.merge(flags, on="symbol", how="left")
    if "has_deal" not in enrichment.columns:
        enrichment["has_deal"] = False
    else:
        enrichment["has_deal"] = enrichment["has_deal"].fillna(False)
    return enrichment


def compute_repeated_client_count(deals: pd.DataFrame) -> pd.Series:
    """Count of distinct trade dates a client has hit the same symbol/side.

    Keyed by symbol|client_name|side only -- deliberately excluding deal_type.
    Prints reported in both the bulk and block files get collapsed into a
    single "Block+Bulk" deal_type (see collapse_cross_listed_prints); if
    deal_type were part of the repeat key, the same buyer trading "Bulk" on
    one day and "Block+Bulk" (post-collapse) on another day would be treated
    as two different clients, silently undercounting repeat_client_count.
    """
    key = client_repeat_key(deals)
    return deals.groupby(key)["trade_date"].transform("nunique")


def client_repeat_key(deals: pd.DataFrame) -> pd.Series:
    """Pure key builder shared by compute_repeated_client_count (and tests)."""
    return deals["symbol"].astype(str) + "|" + deals["client_name"].astype(str) + "|" + deals["side"].astype(str)


def enrich_deals(deals: pd.DataFrame, prices: pd.DataFrame, indicators: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    if deals.empty:
        return deals
    price_cols = ["symbol", "trade_date", "close_price", "volume", "turnover_cr"]
    indicator_cols = ["symbol", "trade_date", "rs_percentile", "vcp_score", "vcp_state", "is_vcp", "near_52w_high", "near_database_high", "ema_stack_bullish", "away_10ema_pct", "away_52w_high_pct"]
    master_cols = ["symbol", "broad_sector", "sector", "broad_industry", "industry", "market_cap_cr", "band"]
    out = deals.merge(prices[price_cols], on=["symbol", "trade_date"], how="left")
    out = out.merge(indicators[indicator_cols], on=["symbol", "trade_date"], how="left")
    out = out.merge(master[master_cols], on="symbol", how="left")
    out["deal_pct_volume"] = out["quantity"] / out["volume"] * 100
    out["deal_price_vs_close_pct"] = (out["price"] / out["close_price"] - 1) * 100
    out["repeated_client_count"] = compute_repeated_client_count(out)
    return enrich_deals_with_tiers(out)


def build_breadth_daily(indicators: pd.DataFrame) -> pd.DataFrame:
    df = indicators.copy()
    df["adv_volume"] = np.where(df["close_price"] > df["prev_close"], df["volume"], 0)
    df["decl_volume"] = np.where(df["close_price"] < df["prev_close"], df["volume"], 0)
    grouped = df.groupby("trade_date").apply(
        lambda g: pd.Series(
            {
                "stocks": g["symbol"].nunique(),
                "advancers": (g["close_price"] > g["prev_close"]).sum(),
                "decliners": (g["close_price"] < g["prev_close"]).sum(),
                "unchanged": (g["close_price"] == g["prev_close"]).sum(),
                "advance_pct": (g["close_price"] > g["prev_close"]).mean() * 100,
                "advance_volume_pct": g["adv_volume"].sum() / max((g["adv_volume"].sum() + g["decl_volume"].sum()), 1) * 100,
                "above_10ema_pct": (g["close_price"] > g["ema_10"]).mean() * 100,
                "above_20ema_pct": (g["close_price"] > g["ema_20"]).mean() * 100,
                "above_50ema_pct": (g["close_price"] > g["ema_50"]).mean() * 100,
                "above_100ema_pct": (g["close_price"] > g["ema_100"]).mean() * 100,
                "above_200ema_pct": (g["close_price"] > g["ema_200"]).mean() * 100,
                "new_20d_highs": g["new_20d_high"].sum(),
                "new_50d_highs": g["new_50d_high"].sum(),
                "new_100d_highs": g["new_100d_high"].sum(),
                "near_52w_highs": g["near_52w_high"].sum(),
                "vcp_candidates": g["is_vcp"].sum(),
            }
        ),
        include_groups=False,
    ).reset_index()
    grouped = grouped.sort_values("trade_date")
    grouped["advance_pct_5d_avg"] = grouped["advance_pct"].rolling(5, min_periods=3).mean()
    grouped["advance_pct_20d_avg"] = grouped["advance_pct"].rolling(20, min_periods=5).mean()
    grouped["above_50ema_5d_change"] = grouped["above_50ema_pct"] - grouped["above_50ema_pct"].shift(5)
    grouped["above_200ema_20d_change"] = grouped["above_200ema_pct"] - grouped["above_200ema_pct"].shift(20)
    grouped["breadth_state"] = np.select(
        [
            (grouped["advance_pct_5d_avg"] >= 55) & (grouped["above_50ema_5d_change"] > 3),
            (grouped["advance_pct_5d_avg"] <= 45) & (grouped["above_50ema_5d_change"] < -3),
            (grouped["above_50ema_pct"] >= 60) & (grouped["above_200ema_pct"] >= 45),
            (grouped["advance_pct"] > 55) & (grouped["above_50ema_5d_change"] < 0),
        ],
        ["Improving", "Weakening", "Broad Participation", "Diverging"],
        default="Neutral",
    )
    return grouped


def _aggregate_rotation_groups(d: pd.DataFrame, col: str, has_prev_close: bool) -> pd.DataFrame:
    """Per (trade_date, group) breadth/return aggregates, vectorised.

    Matches the former per-group apply exactly: NaN-skipping means, EMA comparisons that
    count NaN as "not above", and every output column as float64.
    """
    close = pd.to_numeric(d["close_price"], errors="coerce")
    work = pd.DataFrame(
        {
            "trade_date": d["trade_date"],
            col: d[col],
            "symbol": d["symbol"],
            "return_5d_pct": d["return_5d_pct"],
            "return_1m_pct": d["return_1m_pct"],
            "return_3m_pct": d["return_3m_pct"],
            "rs_percentile": d["rs_percentile"],
            "above_10": (close > d["ema_10"]).astype(float),
            "above_50": (close > d["ema_50"]).astype(float),
            "above_200": (close > d["ema_200"]).astype(float),
            "near_52w_highs": d["near_52w_high"].astype(float),
            "vcp_candidates": d["is_vcp"].astype(float),
            "turnover_cr": d["turnover_cr"],
            "adv": (close > d["prev_close"]).astype(float) if has_prev_close else 0.0,
        },
        index=d.index,
    )
    g = work.groupby(["trade_date", col])
    out = g.agg(
        stocks=("symbol", "nunique"),
        return_5d_pct=("return_5d_pct", "mean"),
        return_1m_pct=("return_1m_pct", "mean"),
        return_3m_pct=("return_3m_pct", "mean"),
        rs_percentile=("rs_percentile", "mean"),
        above_10ema_pct=("above_10", "mean"),
        above_50ema_pct=("above_50", "mean"),
        above_200ema_pct=("above_200", "mean"),
        near_52w_highs=("near_52w_highs", "sum"),
        vcp_candidates=("vcp_candidates", "sum"),
        turnover_cr=("turnover_cr", "sum"),
        adv=("adv", "sum"),
    )
    for pct in ("above_10ema_pct", "above_50ema_pct", "above_200ema_pct"):
        out[pct] = out[pct] * 100
    stocks = out["stocks"].astype(float)
    out["adv_pct"] = np.where(stocks > 0, out["adv"] / stocks.where(stocks > 0) * 100, 0.0) if has_prev_close else 0.0
    out = out.drop(columns="adv").astype(float)
    return out.reset_index()


def leader_symbols_map(d: pd.DataFrame, col: str) -> pd.Series | None:
    """Top-3 symbols by rs_percentile among members with market_cap_cr >= 1000, per
    (trade_date, group) of level column ``col``, as "A,B,C"; None when nobody is eligible."""
    cap = pd.to_numeric(d["market_cap_cr"], errors="coerce").fillna(0.0)
    eligible = d.loc[cap >= 1000.0, ["trade_date", col, "symbol", "rs_percentile"]].copy()
    if eligible.empty:
        return None
    eligible["rs_percentile"] = pd.to_numeric(eligible["rs_percentile"], errors="coerce")
    eligible["symbol"] = eligible["symbol"].astype(str)
    eligible = eligible.sort_values(
        ["trade_date", col, "rs_percentile", "symbol"],
        ascending=[True, True, False, True],
        na_position="last",
    )
    top3 = eligible.groupby(["trade_date", col], sort=False).head(3)
    leader_map = top3.groupby(["trade_date", col], sort=False)["symbol"].agg(
        lambda s: ",".join(s.tolist())
    )
    leader_map.name = "leader_symbols"
    return leader_map


def build_sector_rotation(indicators: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    master_cols = ["symbol", "broad_sector", "sector", "broad_industry", "industry"]
    if "market_cap_cr" in master.columns:
        master_cols.append("market_cap_cr")
    base = indicators.merge(master[master_cols], on="symbol", how="left")
    frames = []
    levels = {
        "Broad Sector": "broad_sector",
        "Sector": "sector",
        "Broad Industry": "broad_industry",
        "Industry": "industry",
    }
    has_prev_close = "prev_close" in base.columns
    for level_name, col in levels.items():
        d = base.dropna(subset=[col]).copy()
        d = d[d[col].astype(str).str.strip() != ""]
        if d.empty:
            continue
        grouped = _aggregate_rotation_groups(d, col, has_prev_close).rename(columns={col: "group_name"})
        grouped["level"] = level_name
        grouped["rotation_score"] = (
            grouped["rs_percentile"].fillna(0) * 0.40
            + grouped["above_50ema_pct"].fillna(0) * 0.25
            + grouped["above_200ema_pct"].fillna(0) * 0.20
            + grouped["return_1m_pct"].fillna(0).clip(-20, 20) * 0.75
        )
        grouped["rotation_rank"] = grouped.groupby("trade_date")["rotation_score"].rank(ascending=False, method="min")
        grouped = grouped.sort_values(["group_name", "trade_date"])
        grouped["rank_change_5d"] = session_lag(grouped["rotation_rank"], grouped["group_name"], 5) - grouped["rotation_rank"]
        grouped["rank_change_20d"] = session_lag(grouped["rotation_rank"], grouped["group_name"], 20) - grouped["rotation_rank"]
        grouped["score_change_5d"] = grouped.groupby("group_name")["rotation_score"].diff(5)
        grouped["turnover_1d_cr"] = grouped["turnover_cr"]
        grouped["turnover_5d_cr"] = grouped.groupby("group_name")["turnover_cr"].transform(lambda s: s.rolling(5, min_periods=1).sum())
        grouped["turnover_20d_cr"] = grouped.groupby("group_name")["turnover_cr"].transform(lambda s: s.rolling(20, min_periods=1).sum())
        date_to = grouped.groupby("trade_date")["turnover_1d_cr"].transform("sum")
        grouped["turnover_share_pct"] = np.where(date_to > 0, grouped["turnover_1d_cr"] / date_to * 100.0, 0.0)
        grouped["turnover_share_delta_1d"] = grouped.groupby("group_name")["turnover_share_pct"].diff(1)
        grouped["turnover_share_delta_5d"] = grouped.groupby("group_name")["turnover_share_pct"].diff(5)
        grouped["rotation_state"] = np.select(
            [
                (grouped["rotation_rank"] <= 5) & (grouped["score_change_5d"] >= 0),
                (grouped["rank_change_5d"] >= 5) & (grouped["score_change_5d"] > 0),
                (grouped["rank_change_5d"] >= 2) & (grouped["score_change_5d"] > 0),
                (grouped["rotation_rank"] <= 8) & (grouped["score_change_5d"] < 0),
                (grouped["rotation_rank"] > 8) & (grouped["score_change_5d"] <= 0),
            ],
            ["Leading", "Emerging", "Improving", "Weakening", "Lagging"],
            default="Neutral",
        )
        grouped["leader_symbols"] = ""
        if "market_cap_cr" in d.columns:
            leader_map = leader_symbols_map(d, col)
            if leader_map is not None:
                grouped = grouped.drop(columns=["leader_symbols"]).merge(
                    leader_map,
                    left_on=["trade_date", "group_name"],
                    right_index=True,
                    how="left",
                )
                grouped["leader_symbols"] = grouped["leader_symbols"].fillna("")
        frames.append(grouped)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def make_screener_results(indicators: pd.DataFrame, master: pd.DataFrame, deals: pd.DataFrame | None = None, sector_rotation: pd.DataFrame | None = None) -> pd.DataFrame:
    latest_date = indicators["trade_date"].max()
    latest = indicators[indicators["trade_date"] == latest_date].merge(
        master[["symbol", "market_cap_cr", "band", "broad_sector", "sector", "broad_industry", "industry"]],
        on="symbol",
        how="left",
    )
    latest_deals = pd.DataFrame(columns=["symbol", "latest_buy_deal_value_cr", "latest_sell_deal_value_cr", "latest_deal_date"])
    if deals is not None and not deals.empty:
        latest_deals = deals[deals["trade_date"] >= latest_date - pd.Timedelta(days=20)].groupby("symbol").apply(
            lambda g: pd.Series(
                {
                    "latest_buy_deal_value_cr": g.loc[g["side"] == "BUY", "deal_value_cr"].sum(),
                    "latest_sell_deal_value_cr": g.loc[g["side"] == "SELL", "deal_value_cr"].sum(),
                    "latest_deal_date": g["trade_date"].max(),
                    "repeated_client_count": g["repeated_client_count"].max() if "repeated_client_count" in g.columns else 1,
                }
            ),
            include_groups=False,
        ).reset_index()
    latest = latest.merge(latest_deals, on="symbol", how="left")
    for col in ["latest_buy_deal_value_cr", "latest_sell_deal_value_cr", "repeated_client_count"]:
        latest[col] = latest[col].fillna(0)
    rows = []
    definitions = {
        "Near 10 EMA": ("% Away from 10 EMA between 0% and 2%", latest["away_10ema_pct"].between(0, 2, inclusive="both")),
        "Near 10 WEMA": ("OHLC above 10 WEMA and close 0%-5% above 10 WEMA", (latest["low_price"] >= latest["wema_10"]) & latest["away_10wema_pct"].between(0, 5, inclusive="both")),
        "Near 10 MEMA": ("OHLC above 10 MEMA and close 0%-5% above 10 MEMA", (latest["low_price"] >= latest["mema_10"]) & latest["away_10mema_pct"].between(0, 5, inclusive="both")),
        "Near 52W High": ("Within 10% of adjusted 52W high", latest["near_52w_high"].fillna(False)),
        "Near Database High": ("Within 10% of highest price in loaded database", latest["near_database_high"].fillna(False)),
        "Near High + Low Volatility": ("Within 10% of high and short ATR below long ATR", latest["low_volatility_near_high"].fillna(False)),
        "Fresh 200 EMA Reclaim": ("Previous close below 200 EMA and latest close above 200 EMA", latest["fresh_200ema_reclaim"].fillna(False)),
        "EMA Stack Bullish": ("10 EMA > 20 EMA > 50 EMA > 100 EMA > 200 EMA", latest["ema_stack_bullish"].fillna(False)),
        "New 20D High": ("Close at or above prior 20D high", latest["new_20d_high"].fillna(False)),
        "New 50D High": ("Close at or above prior 50D high", latest["new_50d_high"].fillna(False)),
        "New 100D High": ("Close at or above prior 100D high", latest["new_100d_high"].fillna(False)),
        "10 EMA Cross 200 EMA - Today": ("10 EMA crossed above 200 EMA on the latest trading day", latest["ema_10_cross_200"].fillna(False)),
        "10 WEMA Cross 200 WEMA - Today": ("10 WEMA crossed above 200 WEMA on the latest weekly update", latest["wema_10_cross_200"].fillna(False)),
        "10 MEMA Cross 200 MEMA - Today": ("10 MEMA crossed above 200 MEMA on the latest monthly update", latest["mema_10_cross_200"].fillna(False)),
        "Shakeout": ("Low breaks 10D support but closes back strong", latest["shakeout"].fillna(False)),
        "EMA Shakeout": ("Low dips below 10/20 EMA and closes back above 10 EMA", latest["ema_shakeout"].fillna(False)),
        "Morning Star D": ("Confirmed daily morning-star style reversal after weakness", latest["confirmed_morning_star"].fillna(False)),
        "Morning Star W": ("Confirmed weekly morning-star style reversal after weakness", latest["confirmed_morning_star_w"].fillna(False)),
        "Morning Star M": ("Confirmed monthly morning-star style reversal; lower confidence with short history", latest["confirmed_morning_star_m"].fillna(False)),
        "Shooting Star D": ("Daily long upper wick after uptrend", latest["confirmed_shooting_star"].fillna(False)),
        "Shooting Star W": ("Weekly long upper wick after uptrend", latest["confirmed_shooting_star_w"].fillna(False)),
        "Shooting Star M": ("Monthly long upper wick after uptrend; lower confidence with short history", latest["confirmed_shooting_star_m"].fillna(False)),
        "Bull RSI Div D": ("Daily price lower low with RSI higher low candidate", latest["bullish_rsi_divergence"].fillna(False)),
        "Bear RSI Div D": ("Daily price higher high with RSI lower high candidate", latest["bearish_rsi_divergence"].fillna(False)),
        "Bull RSI Div W": ("Weekly price lower low with RSI higher low candidate", latest["bullish_rsi_divergence_w"].fillna(False)),
        "Bear RSI Div W": ("Weekly price higher high with RSI lower high candidate", latest["bearish_rsi_divergence_w"].fillna(False)),
        "Bull RSI Div M": ("Monthly price lower low with RSI higher low candidate", latest["bullish_rsi_divergence_m"].fillna(False)),
        "Bear RSI Div M": ("Monthly price higher high with RSI lower high candidate", latest["bearish_rsi_divergence_m"].fillna(False)),
        "Hammer": ("Confirmed hammer after pullback", latest["confirmed_hammer"].fillna(False)),
        "Bullish Engulfing": ("Bullish engulfing after short weakness", latest["confirmed_bullish_engulfing"].fillna(False)),
        "Inside Bar": ("Inside bar compression", latest["inside_bar"].fillna(False)),
        "NR7": ("Narrowest range in 7 sessions", latest["nr7"].fillna(False)),
        "RVOL Spike": ("RVOL >= 2", latest["rvol"] >= 2),
        "Delivery Spike": ("Delivery quantity > 2x 20D average", latest["delivery_spike"].fillna(False)),
        "Price Up + Delivery Up": ("Price up with delivery quantity above 20D average", latest["price_up_delivery_up"].fillna(False)),
        "Top RS Stocks": ("RS percentile >= 90", latest["rs_percentile"] >= 90),
        "Strong Sector + Strong Stock": ("RS percentile >= 85 and bullish EMA stack", (latest["rs_percentile"] >= 85) & latest["ema_stack_bullish"].fillna(False)),
        "BUY Deal + Near High": ("Recent BUY deal and near 52W/database high", (latest["latest_buy_deal_value_cr"] > 0) & (latest["near_52w_high"].fillna(False) | latest["near_database_high"].fillna(False))),
        "SELL Deal + Weak Setup": ("Recent SELL deal while below 50 EMA or RS < 40", (latest["latest_sell_deal_value_cr"] > 0) & ((latest["close_price"] < latest["ema_50"]) | (latest["rs_percentile"] < 40))),
        "Repeated Buyer + Accumulation": ("Repeated buyer plus price/delivery accumulation", (latest["repeated_client_count"] >= 2) & (latest["latest_buy_deal_value_cr"] > 0) & latest["price_up_delivery_up"].fillna(False)),
    }
    cols = [
        "symbol", "trade_date", "close_price", "volume", "turnover_cr", "market_cap_cr", "band",
        "avg_volume_20d", "ema_10_cross_200", "rsi_14", "rsi_14_w", "rsi_14_m",
        "away_10ema_pct", "away_10wema_pct", "away_10mema_pct", "away_52w_high_pct",
        "away_52w_low_pct", "away_database_high_pct", "distance_to_high_pct", "rvol", "rs_percentile",
        "vcp_score", "trend_score", "contraction_score", "volume_dryup_score",
        "pivot_proximity_score", "vcp_state", "latest_buy_deal_value_cr", "latest_sell_deal_value_cr",
        "broad_sector", "sector", "broad_industry", "industry",
    ]
    for name, (rule_summary, mask) in definitions.items():
        frame = latest.loc[mask, cols].copy()
        frame.insert(0, "screener_name", name)
        frame.insert(1, "rule_summary", rule_summary)
        rows.append(frame)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["screener_name", *cols])


# User-owned and auxiliary tables: must survive append / deals refresh / rebuild.
PRESERVED_TABLES = (
    "trade_journal",
    "watchlist_candidates",
    "security_events",
    "corporate_actions",
    "security_risk_daily",
    "top_value_daily",
    "security_reference_daily",
    "ingested_reports",
    "ingestion_batches",
    "candidate_daily",
    "signal_ledger",
    "signal_outcomes",
    "schema_migrations",
)
# Scripts/derived tables: carried over from the live DB like preserved tables (so a rebuild that
# does not recompute them - refresh_deals, or a derived-step failure - keeps the last copy), then
# replaced when the derived step runs. Not row-count validated: a rebuild may shrink them.
CARRIED_TABLES = ("regime_daily", "group_daily", "setup_daily", "deal_session_net")

# os.replace onto a DB file another process (the app) has open fails on Windows; retry a few
# times before giving up with the live DB intact and the new DB kept for a manual swap.
SWAP_RETRIES = 5
SWAP_RETRY_WAIT_S = 3.0
_os_replace = os.replace  # indirection so tests can simulate a locked live DB


class PreservationError(RuntimeError):
    """A preserved table could not be carried over from the live DB; the swap is aborted."""


class DatabaseSwapError(RuntimeError):
    """The new DB could not be installed over the live DB; the live DB is untouched."""


def temp_db_path(db_path: Path) -> Path:
    return Path(db_path).with_suffix(".tmp.duckdb")


def _copy_preserved_table(con, old_con, table: str, reference_history: pd.DataFrame | None) -> int:
    """Copy one preserved table from the live DB into the temp DB; returns the expected row count."""
    user_rows = old_con.execute(f'SELECT * FROM "{table}"').fetchdf()
    if table == "security_reference_daily" and reference_history is not None and not reference_history.empty:
        if not user_rows.empty:
            user_rows = pd.concat([user_rows, reference_history], ignore_index=True)
            if "symbol" in user_rows.columns and "effective_date" in user_rows.columns:
                user_rows = user_rows.drop_duplicates(subset=["symbol", "effective_date"], keep="last")
        else:
            user_rows = reference_history
    con.register(f"{table}_df", user_rows)
    con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM "{table}_df"')
    con.unregister(f"{table}_df")
    if table == "security_reference_daily":
        con.execute("CREATE INDEX IF NOT EXISTS idx_reference_symbol_date ON security_reference_daily(symbol, effective_date)")
    return len(user_rows)


def _preserve_tables(con, live_db: Path, reference_history: pd.DataFrame | None) -> dict[str, int]:
    """Carry every PRESERVED_TABLES table from the live DB into ``con``.

    Any failure (read, write, or a row-count mismatch) raises PreservationError naming the
    table; the live DB handle is always closed.
    """
    preserved: dict[str, int] = {}
    if not live_db.exists():
        return preserved
    try:
        old_con = duckdb.connect(str(live_db), read_only=True)
    except Exception as exc:
        raise PreservationError(f"could not open live DB {live_db} to preserve tables: {exc}") from exc
    try:
        existing = {row[0] for row in old_con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        for table in (*PRESERVED_TABLES, *CARRIED_TABLES):
            if table not in existing:
                continue
            try:
                expected = _copy_preserved_table(con, old_con, table, reference_history)
                got = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            except Exception as exc:
                raise PreservationError(f"could not preserve table {table}: {exc}") from exc
            if got != expected:
                raise PreservationError(f"could not preserve table {table}: wrote {got:,} rows, expected {expected:,}")
            preserved[table] = int(got)
            print(f"Preserved table {table}: {got:,} rows")
    finally:
        old_con.close()
    return preserved


def build_temp_database(
    prices: pd.DataFrame,
    master: pd.DataFrame,
    enrichment: pd.DataFrame,
    indicators: pd.DataFrame,
    deals: pd.DataFrame,
    breadth_daily: pd.DataFrame,
    sector_rotation: pd.DataFrame,
    screener_results: pd.DataFrame,
    sector_metrics_daily: pd.DataFrame | None = None,
    reference_history: pd.DataFrame | None = None,
    price_adjustments: pd.DataFrame | None = None,
    *,
    db_path: Path | None = None,
    with_derived: bool = False,
) -> Path:
    """Write every table into ``<db>.tmp.duckdb`` (preserving user tables from the live DB),
    CHECKPOINT and close it. On any failure the temp file is removed and the error re-raised;
    the live DB is never touched here.

    ``with_derived`` also rebuilds the Scripts/derived tables from the finished temp tables
    (fail-soft: a failure is reported and the carried-over copies are kept)."""
    db_path = Path(db_path) if db_path else DB_PATH
    if price_adjustments is None:
        price_adjustments = empty_adjustments_frame()
    if sector_metrics_daily is None or sector_metrics_daily.empty and len(sector_metrics_daily.columns) == 0:
        sector_metrics_daily = pd.DataFrame(
            columns=[
                "trade_date", "level", "group_name", "stock_count", "rs_vs_nifty_21d", "rs_vs_nifty_63d",
                "breadth_50", "breadth_200", "adv_concentration_top3", "near_52w_pct",
                "adv_total_cr", "tech_pass_n", "funda_pass_n", "deal_net_10s_cr", "deal_prop_10s_cr", "rotation_state",
            ]
        )
    tables = {
        "prices_daily": prices,
        "stocks_master": master,
        "daily_enrichment": enrichment,
        "indicators_daily": indicators,
        "deals": deals,
        "breadth_daily": breadth_daily,
        "sector_rotation": sector_rotation,
        "screener_results": screener_results,
        "sector_metrics_daily": sector_metrics_daily if sector_metrics_daily is not None else pd.DataFrame(),
        "price_adjustments": price_adjustments,
    }
    # Tables the streaming full build already wrote into its staging DuckDB file: that file
    # becomes the temp DB (moved, not copied) and only the remaining tables are added to it.
    staged = {name: frame for name, frame in tables.items() if isinstance(frame, StagedTable)}
    temp_db = temp_db_path(db_path)
    for leftover in (temp_db, temp_db.with_name(temp_db.name + ".wal")):
        if leftover.exists():
            leftover.unlink()
    if staged:
        stage_files = {Path(t.path) for t in staged.values()}
        if len(stage_files) != 1:
            raise ValueError(f"staged tables live in more than one file: {sorted(map(str, stage_files))}")
        stage_file = stage_files.pop()
        if not stage_file.exists():
            raise FileNotFoundError(f"staging DB {stage_file} is missing")
        os.replace(stage_file, temp_db)
        stage_wal = stage_file.with_name(stage_file.name + ".wal")
        if stage_wal.exists():
            os.replace(stage_wal, temp_db.with_name(temp_db.name + ".wal"))
    con = connect_build_db(temp_db)
    try:
        for name, frame in tables.items():
            if name in staged:
                if staged[name].table != name:
                    con.execute(f'ALTER TABLE "{staged[name].table}" RENAME TO "{name}"')
                continue
            con.register(f"{name}_df", frame)
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM {name}_df")
            con.unregister(f"{name}_df")
        con.execute("CREATE INDEX idx_prices_symbol_date ON prices_daily(symbol, trade_date)")
        con.execute("CREATE INDEX idx_indicators_symbol_date ON indicators_daily(symbol, trade_date)")
        con.execute("CREATE INDEX idx_indicators_date_symbol ON indicators_daily(trade_date, symbol)")
        con.execute("CREATE INDEX idx_deals_symbol_date ON deals(symbol, trade_date)")
        con.execute("CREATE INDEX idx_breadth_date ON breadth_daily(trade_date)")
        con.execute("CREATE INDEX idx_sector_rotation ON sector_rotation(level, group_name, trade_date)")
        con.execute("CREATE INDEX idx_sector_metrics ON sector_metrics_daily(level, group_name, trade_date)")
        con.execute("CREATE INDEX idx_screener_name ON screener_results(screener_name)")

        # 1. Ingest index_daily from all MA files
        try:
            index_raw = load_all_index_history(ROOT_DIR)
            if not index_raw.empty:
                index_features = build_index_features(index_raw)
                con.register("index_daily_df", index_features)
                con.execute("CREATE TABLE index_daily AS SELECT * FROM index_daily_df")
                con.execute("CREATE INDEX idx_index_daily_date_name ON index_daily(trade_date, index_name)")
                print(f"Ingested index_daily (ind_close_all + MA fallback): {len(index_features):,} rows across {index_features['index_name'].nunique()} indices")
        except Exception as exc:
            print(f"Warning: index_daily ingestion skipped ({exc})")

        _preserve_tables(con, db_path, reference_history)

        # If security_reference_daily wasn't preserved, create directly from reference_history
        has_ref = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'security_reference_daily'").fetchone()[0]
        if not has_ref:
            if reference_history is None or reference_history.empty:
                try:
                    reference_history = load_reference_history(ROOT_DIR)
                except Exception:
                    reference_history = pd.DataFrame()
            if reference_history is not None and not reference_history.empty:
                con.register("security_reference_daily_df", reference_history)
                con.execute("CREATE TABLE security_reference_daily AS SELECT * FROM security_reference_daily_df")
                con.execute("CREATE INDEX IF NOT EXISTS idx_reference_symbol_date ON security_reference_daily(symbol, effective_date)")
                print(f"Created table security_reference_daily: {len(reference_history):,} rows")

        if with_derived:
            import derived_tables_step

            derived_tables_step.rebuild_in_place(con, incremental=False, own_transaction=False)

        from migrations import _apply_always_on_repairs

        _apply_always_on_repairs(con)
        con.execute("CHECKPOINT")
    except BaseException:
        con.close()
        for leftover in (temp_db, temp_db.with_name(temp_db.name + ".wal")):
            try:
                leftover.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                print(f"Warning: could not remove temp DB {leftover}: {exc}")
        raise
    con.close()
    return temp_db


def install_database(temp_db: Path, db_path: Path | None = None, *, backup: bool = True) -> Path | None:
    """Swap ``temp_db`` over ``db_path`` with os.replace after a dated backup of the live DB.

    Returns the backup path (None when there was no live DB or ``backup`` is False). If the
    backup cannot be taken, or the live DB stays locked by a reader after SWAP_RETRIES tries,
    raises DatabaseSwapError with the live DB untouched and ``temp_db`` kept for a manual swap.
    """
    temp_db = Path(temp_db)
    db_path = Path(db_path) if db_path else DB_PATH
    backup_path = None
    if backup and db_path.exists():
        import db_backup

        try:
            backup_path = db_backup.backup_database(db_path)
        except Exception as exc:
            raise DatabaseSwapError(
                f"Could not back up live DB {db_path} before swap ({exc}); live DB untouched. "
                f"New DB kept at {temp_db}."
            ) from exc
    # A WAL left beside the live DB would be replayed onto the NEW file; park it until the swap lands.
    live_wal = db_path.with_name(db_path.name + ".wal")
    parked_wal = live_wal.with_name(live_wal.name + ".pre-swap")
    if live_wal.exists():
        os.replace(live_wal, parked_wal)
    last_exc: Exception | None = None
    for attempt in range(1, SWAP_RETRIES + 1):
        try:
            _os_replace(temp_db, db_path)
            last_exc = None
            break
        except OSError as exc:
            last_exc = exc
            if attempt < SWAP_RETRIES:
                print(f"Live DB busy (attempt {attempt}/{SWAP_RETRIES}): {exc}; retrying in {SWAP_RETRY_WAIT_S:g}s...")
                time.sleep(SWAP_RETRY_WAIT_S)
    if last_exc is not None:
        if parked_wal.exists() and not live_wal.exists():
            os.replace(parked_wal, live_wal)
        msg = (
            f"Could not replace live DB {db_path} after {SWAP_RETRIES} attempts ({last_exc}). "
            f"It is probably open in the MarketPulse app. Live DB left intact. New DB kept at {temp_db} - "
            f"close the app and move it over {db_path} to finish the swap."
        )
        print(msg)
        raise DatabaseSwapError(msg) from last_exc
    parked_wal.unlink(missing_ok=True)
    return backup_path


def write_database(
    prices: pd.DataFrame,
    master: pd.DataFrame,
    enrichment: pd.DataFrame,
    indicators: pd.DataFrame,
    deals: pd.DataFrame,
    breadth_daily: pd.DataFrame,
    sector_rotation: pd.DataFrame,
    screener_results: pd.DataFrame,
    sector_metrics_daily: pd.DataFrame | None = None,
    reference_history: pd.DataFrame | None = None,
    price_adjustments: pd.DataFrame | None = None,
    *,
    db_path: Path | None = None,
    materialize: bool = True,
    with_derived: bool = False,
) -> Path | None:
    """Build a temp DB, then back up and atomically swap it over the live DB, under the writer
    lock. Returns the dated backup path (None for a first build)."""
    from db_lock import writer_lock

    db_path = Path(db_path) if db_path else DB_PATH
    with writer_lock(db_path, owner="write_database"):
        temp_db = build_temp_database(
            prices, master, enrichment, indicators, deals, breadth_daily, sector_rotation, screener_results,
            sector_metrics_daily, reference_history=reference_history, price_adjustments=price_adjustments,
            db_path=db_path, with_derived=with_derived,
        )
        backup_path = install_database(temp_db, db_path)
        if materialize:
            # Decision tables are explicit runtime migrations and materialized only after
            # the accepted replacement database has been atomically installed.
            try:
                from materialize_decision_tables import materialize_decision_tables

                materialize_decision_tables(db_path)
            except Exception as exc:
                print(f"Warning: decision tables were not materialized: {exc}")
    return backup_path


BUILD_FRAME_KEYS = (
    "prices", "master", "enrichment", "indicators", "deals", "breadth_daily", "sector_rotation",
    "screener_results", "sector_metrics_daily", "reference_history", "price_adjustments",
)


def load_benchmark_inputs() -> tuple[object, object]:
    """(index history, sector-index membership) for the RS steps, loaded once per build.

    A load failure is returned as the exception object; `attach_benchmark_rs` re-raises it
    inside its own try blocks, so a batch behaves exactly like the in-memory build did when the
    load failed there (warning + NaN true RS, sector-index RS skipped).
    """
    try:
        index_raw = load_all_index_history(ROOT_DIR)
    except Exception as exc:  # noqa: BLE001 - handed to attach_benchmark_rs
        index_raw = exc
    try:
        membership = load_membership_csv()
    except Exception as exc:  # noqa: BLE001
        membership = exc
    return index_raw, membership


def enrich_deals_from_db(con, deals_raw: pd.DataFrame, master: pd.DataFrame, date_dtype=None) -> pd.DataFrame:
    """`enrich_deals` with the prices / indicators rows it joins read from DuckDB - only the
    (symbol, trade_date) keys that have a deal, only the columns it uses."""
    from streaming_build import DEAL_INDICATOR_COLUMNS, DEAL_PRICE_COLUMNS, read_slim

    if deals_raw.empty:
        return enrich_deals(deals_raw, pd.DataFrame(), pd.DataFrame(), master)
    keys = deals_raw[["symbol", "trade_date"]].drop_duplicates().reset_index(drop=True)
    con.register("_deal_keys", keys)
    try:
        def has_deal(table: str) -> str:
            return f"EXISTS (SELECT 1 FROM _deal_keys k WHERE k.symbol = {table}.symbol AND k.trade_date = {table}.trade_date)"

        price_rows = read_slim(con, "prices_daily", DEAL_PRICE_COLUMNS, where=has_deal("prices_daily"), date_dtype=date_dtype)
        indicator_rows = read_slim(con, "indicators_daily", DEAL_INDICATOR_COLUMNS, where=has_deal("indicators_daily"), date_dtype=date_dtype)
    finally:
        con.unregister("_deal_keys")
    return enrich_deals(deals_raw, price_rows, indicator_rows, master)


def derived_tables_from_db(
    con,
    *,
    master: pd.DataFrame,
    deals: pd.DataFrame,
    reference_history: pd.DataFrame,
    date_dtype=None,
    quiet: bool = False,
    metric_reference: pd.DataFrame | None = None,
    metric_index: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """breadth_daily, sector_rotation, sector_metrics_daily and screener_results from the
    indicators_daily table in ``con``, each builder fed only the columns it reads."""
    from streaming_build import BREADTH_COLUMNS, METRICS_COLUMNS, ROTATION_COLUMNS, read_slim, table_columns

    if not quiet:
        print("  7a/8: Calculating market breadth...")
    breadth_daily = build_breadth_daily(read_slim(con, "indicators_daily", BREADTH_COLUMNS, date_dtype=date_dtype))
    if not quiet:
        print("  7b/8: Calculating sector rotation...")
    sector_rotation = build_sector_rotation(read_slim(con, "indicators_daily", ROTATION_COLUMNS, date_dtype=date_dtype), master)
    gc.collect()
    index_features, metric_reference = _metric_inputs(reference_history, master, metric_reference, metric_index, quiet=quiet)
    if not quiet:
        print("  7d/8: Computing taxonomy metrics...")
    sector_metrics_daily = compute_sector_metrics(
        read_slim(con, "indicators_daily", METRICS_COLUMNS, date_dtype=date_dtype), master, metric_reference, index_features, deals
    )
    gc.collect()
    if not quiet:
        print(f"  7d/8: Taxonomy metrics ready ({len(sector_metrics_daily):,} rows).")
        print("  7e/8: Building screener results...")
    latest = read_slim(
        con,
        "indicators_daily",
        table_columns(con, "indicators_daily"),
        where="trade_date = (SELECT max(trade_date) FROM indicators_daily)",
        date_dtype=date_dtype,
    )
    screener_results = make_screener_results(latest, master, deals, sector_rotation)
    return {
        "breadth_daily": breadth_daily,
        "sector_rotation": sector_rotation,
        "sector_metrics_daily": sector_metrics_daily,
        "screener_results": screener_results,
    }


def compute_full_build(
    quiet: bool = False,
    *,
    db_path: Path | None = None,
    streaming: bool = True,
    raw_prices: pd.DataFrame | None = None,
    extra_actions: pd.DataFrame | None = None,
    metric_reference: pd.DataFrame | None = None,
    metric_index: pd.DataFrame | None = None,
) -> dict:
    """Every table of a FULL rebuild. Returns keyword arguments for ``write_database`` /
    ``build_temp_database``.

    The universe is the bhavcopies themselves (series EQ/BE/BZ, symbol changes applied), not
    today's EQUITY_L, so delisted history stays and renamed symbols stay continuous.

    ``streaming=True`` (default) keeps memory bounded for multi-year history: prices_daily and
    indicators_daily are written into ``<db>.stage.duckdb`` (indicators in symbol batches, see
    streaming_build) and returned as ``StagedTable`` handles, which ``build_temp_database``
    adopts as its temp DB; the other tables are built from slim column reads. The values are
    the same as ``streaming=False``, which computes everything in pandas like before.

    The full-recompute fallback of the append passes ``raw_prices`` (stored history + new
    sessions, symbol changes applied), ``extra_actions`` (the corporate_actions table) and its
    own ``metric_reference`` / ``metric_index`` for sector metrics, as the old append did.
    """
    from streaming_build import connect_build_db, remove_db_file, stage_db_path, stream_full_indicators

    ensure_folders()
    if not quiet:
        print("1/8: Loading equity list and sector mapping...")
    equity = read_equity_symbols()
    sector = read_sector()
    if not quiet:
        print("2/8: Reading historical price files (archive + daily)...")
    prices = build_prices(None) if raw_prices is None else raw_prices
    del raw_prices
    prices, price_adjustments = adjust_prices(prices, ROOT_DIR, extra_actions=extra_actions)
    print(summarize_adjustments(price_adjustments))
    if not quiet:
        print("3/8: Reading market cap, price band, PE, and 52-week reference files...")
    mcap = read_market_cap()
    bands = read_price_band()
    pe = read_pe()
    high52 = read_52_week()
    if not quiet:
        print("4/8: Building enrichment tables and stock master list...")
    enrichment = build_enrichment(mcap, bands, pe, high52, pd.DataFrame(), pd.DataFrame())
    master = build_master(equity, sector, prices, mcap, bands, pe)
    reference_history = load_reference_history(ROOT_DIR)
    if not streaming:
        return _compute_full_build_in_memory(
            prices, price_adjustments, master, enrichment, reference_history, mcap, bands, pe, high52, quiet=quiet,
            metric_reference=metric_reference, metric_index=metric_index,
        )

    stage_path = stage_db_path(Path(db_path) if db_path else DB_PATH)
    stage_path.parent.mkdir(parents=True, exist_ok=True)
    remove_db_file(stage_path)
    date_dtype = prices["trade_date"].dtype
    price_info = {
        "min_date": prices["trade_date"].min(),
        "max_date": prices["trade_date"].max(),
    }
    n_prices = len(prices)
    con = connect_build_db(stage_path)
    try:
        if not quiet:
            print(f"  Staging prices_daily ({n_prices:,} rows) in {stage_path.name}...")
        con.register("prices_daily_df", prices)
        con.execute("CREATE TABLE prices_daily AS SELECT * FROM prices_daily_df")
        con.unregister("prices_daily_df")
        del prices
        gc.collect()
        if not quiet:
            print("5/8: Calculating indicators (symbol batches, streamed to DuckDB)...")
        index_raw, membership = load_benchmark_inputs()
        n_indicators = stream_full_indicators(
            con,
            reference=reference_history if not reference_history.empty else None,
            enrichment=enrichment,
            index_raw=index_raw,
            membership=membership,
            date_dtype=date_dtype,
        )
        if not quiet:
            print("6/8: Reading and enriching deal flow...")
        deals = enrich_deals_from_db(con, read_all_deals(), master, date_dtype)
        latest_deals = deals[deals["trade_date"] == deals["trade_date"].max()] if not deals.empty else deals
        if not quiet:
            print("7/8: Building breadth and sector rotation metrics...")
        enrichment = build_enrichment(mcap, bands, pe, high52, latest_deals, pd.DataFrame())
        derived = derived_tables_from_db(
            con, master=master, deals=deals, reference_history=reference_history, date_dtype=date_dtype, quiet=quiet,
            metric_reference=metric_reference, metric_index=metric_index,
        )
        con.execute("CHECKPOINT")
    except BaseException:
        con.close()
        remove_db_file(stage_path)
        raise
    con.close()
    return {
        "prices": StagedTable(stage_path, "prices_daily", n_prices, price_info),
        "master": master,
        "enrichment": enrichment,
        "indicators": StagedTable(stage_path, "indicators_daily", n_indicators),
        "deals": deals,
        **derived,
        "reference_history": reference_history,
        "price_adjustments": price_adjustments,
    }


def _metric_inputs(reference_history, master, metric_reference=None, metric_index=None, *, quiet: bool = False):
    """(index features, as-of reference) for compute_sector_metrics: the full build loads the
    MA index history and falls back to the latest market cap in master; the append passes its own."""
    if metric_index is not None:
        index_features = metric_index
    else:
        try:
            if not quiet:
                print("  7c/8: Loading market-index history...")
            index_raw = load_all_index_history(ROOT_DIR)
            index_features = build_index_features(index_raw)
        except Exception:
            index_features = pd.DataFrame()
    if metric_reference is None:
        metric_reference = reference_history
        if metric_reference.empty and {"symbol", "latest_price_date", "market_cap_cr"}.issubset(master.columns):
            metric_reference = master[["symbol", "latest_price_date", "market_cap_cr"]].rename(
                columns={"latest_price_date": "effective_date"}
            )
    return index_features, metric_reference


def _compute_full_build_in_memory(
    prices, price_adjustments, master, enrichment, reference_history, mcap, bands, pe, high52, *, quiet: bool = False,
    metric_reference: pd.DataFrame | None = None, metric_index: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """The pre-streaming full build: every table computed in pandas (needs RAM for the whole
    indicators frame; kept for small DBs and as the reference implementation)."""
    if not quiet:
        print("5/8: Calculating indicators...")
    indicators = calc_indicators(indicator_input(prices), reference_history if not reference_history.empty else enrichment)
    if not quiet:
        print("6/8: Reading and enriching deal flow...")
    deals_raw = read_all_deals()
    deals = enrich_deals(deals_raw, prices, indicators, master)
    latest_deals = deals[deals["trade_date"] == deals["trade_date"].max()] if not deals.empty else deals
    if not quiet:
        print("7/8: Building breadth and sector rotation metrics...")
    enrichment = build_enrichment(mcap, bands, pe, high52, latest_deals, pd.DataFrame())
    if not quiet:
        print("  7a/8: Calculating market breadth...")
    breadth_daily = build_breadth_daily(indicators)
    if not quiet:
        print("  7b/8: Calculating sector rotation...")
    sector_rotation = build_sector_rotation(indicators, master)
    index_features, metric_reference = _metric_inputs(reference_history, master, metric_reference, metric_index, quiet=quiet)
    if not quiet:
        print("  7d/8: Computing taxonomy metrics...")
    sector_metrics_daily = compute_sector_metrics(indicators, master, metric_reference, index_features, deals)
    if not quiet:
        print(f"  7d/8: Taxonomy metrics ready ({len(sector_metrics_daily):,} rows).")
        print("  7e/8: Building screener results...")
    screener_results = make_screener_results(indicators, master, deals, sector_rotation)
    return {
        "prices": prices,
        "master": master,
        "enrichment": enrichment,
        "indicators": indicators,
        "deals": deals,
        "breadth_daily": breadth_daily,
        "sector_rotation": sector_rotation,
        "screener_results": screener_results,
        "sector_metrics_daily": sector_metrics_daily,
        "reference_history": reference_history,
        "price_adjustments": price_adjustments,
    }


def discard_staged(frames: dict) -> None:
    """Remove the staging DB behind any StagedTable in ``frames`` (e.g. a build that is not
    going to be installed)."""
    from streaming_build import remove_db_file

    for frame in frames.values():
        if isinstance(frame, StagedTable):
            remove_db_file(frame.path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the MarketPulse DuckDB database. This ALWAYS performs a FULL rebuild from ALL available price history (archive + daily). Use this directly for catch-up after missed daily uploads: drop any missed bhavcopy / deal / reference files into Input/daily/ (even older dated ones) then run this script. The normal daily_update.bat is stricter for day-to-day use. For a validated rebuild with a dry-run option use Scripts/safe_rebuild.py.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if not args.quiet:
        print("Starting full database rebuild. This may take 5-10 minutes depending on archive size.")
    frames = compute_full_build(quiet=args.quiet, db_path=DB_PATH)
    if not args.quiet:
        print("8/8: Writing database file...")
    try:
        write_database(**frames, with_derived=True)
    except BaseException:
        discard_staged(frames)
        raise
    if not args.quiet:
        prices, master, deals = frames["prices"], frames["master"], frames["deals"]
        if isinstance(prices, StagedTable):
            lo, hi = prices.info.get("min_date"), prices.info.get("max_date")
        else:
            lo, hi = prices["trade_date"].min(), prices["trade_date"].max()
        print("MarketPulse database built successfully (FULL history rebuild).")
        print(f"Database: {DB_PATH}")
        print(f"Stocks in master list: {len(master):,} ({int(master['is_active'].sum()):,} active in latest session)")
        print(f"Price rows: {len(prices):,}")
        print(f"Deal rows: {len(deals):,}")
        print(f"Date range: {pd.Timestamp(lo).date()} to {pd.Timestamp(hi).date()}")
        print("Tip: For normal daily use prefer Update_MarketPulse.bat. For catch-up after missed uploads, place missed files in Input/daily/ and run this script (or python -m Scripts.build_database).")

if __name__ == "__main__":
    main()
