"""Parse and derive point-in-time features from NSE Market Activity index files."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


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


def parse_market_activity(path: Path, trade_date: date | pd.Timestamp) -> pd.DataFrame:
    rows = []
    with Path(path).open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for raw in reader:
            values = [str(value).strip() for value in raw]
            if len(values) < 8 or values[1].strip().upper() in {"INDEX", ""}:
                continue
            previous, opening, high, low, close, change = (_number(value) for value in values[2:8])
            if not values[1] or any(value is None for value in (previous, opening, high, low, close, change)):
                continue
            rows.append(
                {
                    "trade_date": pd.Timestamp(trade_date).normalize(),
                    "index_name": values[1],
                    "previous_close": previous,
                    "open_price": opening,
                    "high_price": high,
                    "low_price": low,
                    "close_price": close,
                    "change_value": change,
                    "return_1d_pct": round((close / previous - 1.0) * 100, 10) if previous else None,
                }
            )
    return pd.DataFrame(rows, columns=INDEX_COLUMNS)


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
    frames = []
    for path in sorted(set(paths)):
        trade_day = _parse_ma_date(Path(path))
        if trade_day is None:
            continue
        frame = parse_market_activity(path, trade_day)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=INDEX_COLUMNS)
    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(["trade_date", "index_name"], keep="last")
        .sort_values(["trade_date", "index_name"])
        .reset_index(drop=True)
    )


def load_all_market_activity_history(root: Path) -> pd.DataFrame:
    """Find and parse all MA files from downloads, archive, and daily."""
    root = Path(root)
    paths = []
    downloads = root / "Input" / "downloads"
    archive = root / "Input" / "archive"
    daily = root / "Input" / "daily"
    if downloads.exists():
        paths.extend(downloads.glob("*/MA*.csv"))
    if archive.exists():
        paths.extend(archive.glob("MA*.csv"))
    if daily.exists():
        paths.extend(daily.glob("MA*.csv"))
    return parse_market_activity_history(paths)



EXTRA_INDEX_COLUMNS = ["volume", "turnover_cr", "pe", "pb", "div_yield"]


def parse_ind_close_all(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    raw.columns = [str(c).strip() for c in raw.columns]

    def num(col):
        if col not in raw.columns:
            return pd.Series(np.nan, index=raw.index, dtype="float64")
        return pd.to_numeric(raw[col].astype(str).str.replace(",", "").str.strip().replace({"-": None}), errors="coerce")

    out = pd.DataFrame({
        "trade_date": pd.to_datetime(raw["Index Date"].str.strip(), format="%d-%m-%Y", errors="coerce"),
        "index_name": raw["Index Name"].astype(str).str.strip(),
        "open_price": num("Open Index Value"),
        "high_price": num("High Index Value"),
        "low_price": num("Low Index Value"),
        "close_price": num("Closing Index Value"),
        "change_value": num("Points Change"),
        "return_1d_pct": num("Change(%)"),
        "volume": num("Volume"),
        "turnover_cr": num("Turnover (Rs. Cr.)"),
        "pe": num("P/E"),
        "pb": num("P/B"),
        "div_yield": num("Div Yield"),
    })
    out["previous_close"] = out["close_price"] - out["change_value"]
    out = out.dropna(subset=["trade_date", "close_price"])
    if out.empty:
        print(f"WARNING: {Path(path).name} yielded 0 rows")
    return out[INDEX_COLUMNS + EXTRA_INDEX_COLUMNS]


def load_index_name_map(path: Path) -> dict[str, str]:
    if path is None or not Path(path).exists():
        return {}
    m = pd.read_csv(path, dtype=str)
    return dict(zip(m["source_name"].str.strip(), m["canonical_name"].str.strip()))


def load_all_index_history(root: Path, name_map_path: Path | None = None) -> pd.DataFrame:
    root = Path(root)
    name_map_path = name_map_path or (root / "Input" / "reference" / "index_name_map.csv")
    folders = [root / "Input" / "archive", root / "Input" / "archive" / "backfill" / "index", root / "Input" / "daily"]
    frames = []
    for folder in folders:
        if folder.exists():
            for p in sorted(folder.glob("ind_close_all_*.csv")):
                try:
                    frames.append(parse_ind_close_all(p))
                except Exception as exc:
                    print(f"Skipped {p.name}: {exc}")
    ma = load_all_market_activity_history(root)
    if frames:
        close_all = pd.concat(frames, ignore_index=True)
        name_map = load_index_name_map(name_map_path)
        close_all["index_name"] = close_all["index_name"].map(lambda n: name_map.get(n, n))
        close_all = close_all.drop_duplicates(["trade_date", "index_name"], keep="last")
        if ma is not None and not ma.empty:
            ma = ma.copy()
            ma["trade_date"] = pd.to_datetime(ma["trade_date"]).dt.normalize()
            have = set(zip(close_all["trade_date"], close_all["index_name"]))
            ma = ma[[(d, n) not in have for d, n in zip(ma["trade_date"], ma["index_name"])]]
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
