"""Input loading for the evidence engine.

`load_frames(con, derived_con=None, pr_dir=None)` reads everything the builders need from a
(read-only) DuckDB connection into pandas frames. Adjusted OHLC (`prices_daily.adj_*`) is used
when present, raw prices otherwise (the frames carry ``price_basis`` in ``frames['meta']``).

PR archive (`Input/archive/backfill/pr/PRddmmyy.zip`) gives point-in-time market cap (MCAP file),
board meetings (Bm, results dates) and corporate actions (Bc) across the full backfill; it is
optional and cached as a pickle next to the output DB.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .common import to_ts_col

log = logging.getLogger(__name__)

IND_COLS = [
    "symbol", "series", "trade_date", "prev_close", "open_price", "high_price", "low_price", "close_price", "volume",
    "delivery_pct", "avg_delivery_pct_20d", "delivery_spike", "ema_10", "ema_20", "ema_50", "ema_200",
    "rvol", "avg_volume_10d", "avg_volume_20d", "avg_volume_50d", "avg_traded_value_cr_20d", "turnover_cr",
    "atr_pct", "atr_pct_avg_50d", "range_10d_pct", "range_20d_pct", "range_50d_pct", "high_20d", "low_10d",
    "high_252d", "low_252d", "away_52w_high_pct", "rs_percentile", "trend_template_pass", "return_1m_pct",
    "return_3m_pct",
]
INDEX_NAMES = {"midsml": "NIFTY MIDSML 400", "nifty": "Nifty 50", "vix": "India VIX"}
SERIES_OK = ("EQ", "BE", "BZ")


def _exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]).fetchone()[0])


def _cols(con: duckdb.DuckDBPyConnection, name: str) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position", [name]).fetchall()]


def _df(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
    return con.execute(sql, params or []).fetchdf()


def load_indicators(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, str]:
    have = set(_cols(con, "indicators_daily"))
    keep64 = {"symbol", "series", "trade_date", "delivery_spike", "trend_template_pass", "prev_close", "open_price",
              "high_price", "low_price", "close_price", "volume"}
    sel = [(f"i.{c}" if c in keep64 else f"CAST(i.{c} AS FLOAT) AS {c}") if c in have else
           (f"NULL AS {c}" if c in keep64 else f"CAST(NULL AS FLOAT) AS {c}") for c in IND_COLS]
    pcols = set(_cols(con, "prices_daily")) if _exists(con, "prices_daily") else set()
    basis = "raw"
    join = ""
    for c in ("open_price", "high_price", "low_price", "close_price", "volume"):
        short = c.replace("_price", "")
        for cand in (f"adj_{c}", f"adj_{short}"):
            if cand in pcols:
                sel[IND_COLS.index(c)] = f"COALESCE(p.{cand}, i.{c}) AS {c}"
                join = "LEFT JOIN prices_daily p ON p.symbol = i.symbol AND p.trade_date = i.trade_date"
                basis = "adjusted"
                break
    frame = _df(con, f"""
        SELECT {', '.join(sel)} FROM indicators_daily i {join}
        WHERE i.symbol <> 'TOTAL' AND i.series IN ('EQ', 'BE', 'BZ')
        ORDER BY i.symbol, i.trade_date""")
    frame = to_ts_col(frame, "trade_date")
    for c in frame.columns:
        if c in ("symbol", "series", "trade_date"):
            continue
        if frame[c].dtype == bool or str(frame[c].dtype) == "boolean":
            continue
        if c in ("delivery_spike", "trend_template_pass"):
            continue
        frame[c] = pd.to_numeric(frame[c], errors="coerce").astype("float32" if c not in (
            "open_price", "high_price", "low_price", "close_price", "prev_close") else "float64")
    frame["symbol"] = frame["symbol"].astype(str)
    frame["series"] = frame["series"].astype(str)
    return frame.reset_index(drop=True), basis


def load_frames(con: duckdb.DuckDBPyConnection, derived_con: duckdb.DuckDBPyConnection | None = None,
                pr_dir: Path | None = None, cache_dir: Path | None = None) -> dict[str, Any]:
    """All inputs as frames. `derived_con` (optional) supplies regime_daily / group_daily / setup_daily
    when the market DB does not carry them yet."""
    frames: dict[str, Any] = {}
    ind, basis = load_indicators(con)
    frames["indicators"] = ind
    frames["meta"] = {"price_basis": basis}

    names = list(INDEX_NAMES.values())
    idx = _df(con, f"SELECT trade_date, index_name, close_price, turnover_cr FROM index_daily "
                   f"WHERE index_name IN ({', '.join('?' * len(names))}) ORDER BY trade_date", names)
    frames["index_daily"] = to_ts_col(idx, "trade_date")

    for name in ("breadth_daily", "stocks_master", "security_reference_daily", "deals", "security_events",
                 "corporate_actions", "sector_rotation"):
        frames[name] = None
    if _exists(con, "breadth_daily"):
        frames["breadth_daily"] = to_ts_col(_df(con, "SELECT * FROM breadth_daily ORDER BY trade_date"), "trade_date")
    if _exists(con, "stocks_master"):
        mc = set(_cols(con, "stocks_master"))
        want = [c for c in ("symbol", "security_name", "broad_sector", "sector", "broad_industry", "industry", "market_cap_cr",
                            "market_cap_date", "band", "band_remarks", "latest_close") if c in mc]
        frames["stocks_master"] = _df(con, f"SELECT {', '.join(want)} FROM stocks_master")
    if _exists(con, "security_reference_daily"):
        frames["security_reference_daily"] = to_ts_col(_df(con, """
            SELECT symbol, effective_date, market_cap_cr, price_band FROM security_reference_daily
            WHERE market_cap_cr IS NOT NULL OR price_band IS NOT NULL"""), "effective_date")
    if _exists(con, "deals"):
        dc = set(_cols(con, "deals"))
        cl = "clientele" if "clientele" in dc else "NULL AS clientele"
        frames["deals"] = to_ts_col(_df(con, f"""
            SELECT trade_date, symbol, client_name, upper(side) AS side, quantity, price,
                   quantity * price / 1e7 AS value_cr, {cl}
            FROM deals WHERE symbol IS NOT NULL"""), "trade_date")
    if _exists(con, "security_events"):
        frames["security_events"] = to_ts_col(_df(con, "SELECT symbol, event_date, event_type, headline FROM security_events"),
                                              "event_date")
    if _exists(con, "corporate_actions"):
        frames["corporate_actions"] = to_ts_col(_df(con, "SELECT symbol, ex_date, action_type, description FROM corporate_actions"),
                                                "ex_date")
    if _exists(con, "sector_rotation"):
        frames["sector_rotation"] = to_ts_col(_df(con, """
            SELECT trade_date, level, group_name, rotation_state, rs_percentile FROM sector_rotation"""), "trade_date")

    for name in ("regime_daily", "group_daily", "setup_daily"):
        frames[name] = None
        src = con if _exists(con, name) else (derived_con if derived_con is not None and _exists(derived_con, name) else None)
        if src is None:
            continue
        if name == "group_daily":
            gc = set(_cols(src, name))
            want = [c for c in ("trade_date", "level", "floor", "group_name", "rrg_quadrant", "rank", "rank_n",
                                "excess_midsml_21d", "members") if c in gc]
            frames[name] = to_ts_col(_df(src, f"SELECT {', '.join(want)} FROM group_daily"), "trade_date")
        else:
            frames[name] = to_ts_col(_df(src, f"SELECT * FROM {name}"), "trade_date")
        frames["meta"][f"{name}_source"] = "market_db" if src is con else "derived_db"

    frames["pr"] = load_pr_archive(pr_dir, ind["trade_date"].min(), ind["trade_date"].max(), cache_dir) if pr_dir else None
    return frames


# --------------------------------------------------------------------------
# PR archive (point-in-time mcap, board meetings, corporate actions)
# --------------------------------------------------------------------------
_PR_NAME = re.compile(r"PR(\d{2})(\d{2})(\d{2})\.zip$", re.I)
_BM_LINE = re.compile(r"^(?P<company>.*?)\s+(?P<symbol>[A-Z0-9&-]+)\s*:\s*(?P<d>\d{1,2}-[A-Z]{3}-\d{4})\s*:\s*(?P<purpose>.*)$")


def _pr_date(path: Path) -> pd.Timestamp | None:
    m = _PR_NAME.search(path.name)
    if not m:
        return None
    try:
        return pd.Timestamp(datetime.strptime("".join(m.groups()), "%d%m%y"))
    except ValueError:
        return None


def _parse_zip(path: Path, d: pd.Timestamp) -> tuple[pd.DataFrame | None, list[dict], pd.DataFrame | None]:
    mcap = bc = None
    bm: list[dict] = []
    with zipfile.ZipFile(path) as z:
        for nm in z.namelist():
            low = Path(nm).name.lower()
            if low.startswith("mcap") and low.endswith(".csv"):
                raw = pd.read_csv(io.BytesIO(z.read(nm)), dtype=str, keep_default_na=False)
                raw.columns = [c.strip() for c in raw.columns]
                sym = next((c for c in raw.columns if c.lower() == "symbol"), None)
                ser = next((c for c in raw.columns if c.lower() == "series"), None)
                cap = next((c for c in raw.columns if c.lower().startswith("market cap")), None)
                if sym and cap:
                    mcap = pd.DataFrame({
                        "symbol": raw[sym].str.strip().str.upper(),
                        "series": raw[ser].str.strip().str.upper() if ser else "",
                        "mcap_cr": pd.to_numeric(raw[cap].str.strip(), errors="coerce") / 1e7,
                    })
                    mcap = mcap.loc[mcap["series"].isin(["EQ", "BE", "BZ", ""])].drop(columns=["series"])
                    mcap["trade_date"] = d
            elif low.startswith("bm") and low.endswith(".txt"):
                for line in z.read(nm).decode("utf-8", "replace").splitlines():
                    m = _BM_LINE.match(line.strip())
                    if not m:
                        continue
                    try:
                        md = pd.Timestamp(datetime.strptime(m.group("d").upper(), "%d-%b-%Y"))
                    except ValueError:
                        continue
                    bm.append({"symbol": m.group("symbol").upper(), "meeting_date": md, "known_date": d,
                               "purpose": m.group("purpose").strip()[:160]})
            elif low.startswith("bc") and low.endswith(".csv"):
                raw = pd.read_csv(io.BytesIO(z.read(nm)), dtype=str, keep_default_na=False)
                if {"SERIES", "SYMBOL", "PURPOSE"}.issubset(raw.columns):
                    raw = raw.loc[raw["SERIES"].str.strip().isin(["EQ", "BE", "BZ"])]
                    ex = raw["EX_DT"] if "EX_DT" in raw.columns else raw.get("RECORD_DT")
                    bc = pd.DataFrame({"symbol": raw["SYMBOL"].str.strip().str.upper(),
                                       "ex_date": pd.to_datetime(ex, errors="coerce", format="mixed", dayfirst=False),
                                       "purpose": raw["PURPOSE"].str.strip().str[:120], "known_date": d})
    return mcap, bm, bc


def load_pr_archive(pr_dir: Path | None, start: Any, end: Any, cache_dir: Path | None = None) -> dict[str, pd.DataFrame] | None:
    """{'mcap': (symbol, trade_date, mcap_cr), 'board_meetings': (...), 'corp_actions': (...)} or None."""
    if pr_dir is None or not Path(pr_dir).exists():
        return None
    lo = pd.Timestamp(start) - pd.Timedelta(days=15)
    hi = pd.Timestamp(end) + pd.Timedelta(days=1)
    files = []
    for p in sorted(Path(pr_dir).glob("PR*.zip")):
        d = _pr_date(p)
        if d is not None and lo <= d <= hi:
            files.append((d, p))
    if not files:
        return None
    sig = hashlib.sha1("|".join(f"{p.name}:{p.stat().st_size}" for _, p in files).encode()).hexdigest()[:16]
    cache = Path(cache_dir) / f"pr_archive_{sig}.pkl" if cache_dir else None
    if cache is not None and cache.exists():
        try:
            return pd.read_pickle(cache)
        except Exception:  # pragma: no cover - stale/corrupt cache
            pass
    mcaps, bms, bcs = [], [], []
    for d, p in sorted(files):
        try:
            mcap, bm, bc = _parse_zip(p, d)
        except (zipfile.BadZipFile, OSError, ValueError) as exc:
            log.warning("PR zip %s unreadable: %s", p.name, exc)
            continue
        if mcap is not None:
            mcaps.append(mcap)
        bms.extend(bm)
        if bc is not None:
            bcs.append(bc)
    out = {
        "mcap": pd.concat(mcaps, ignore_index=True).dropna(subset=["mcap_cr"]) if mcaps else pd.DataFrame(
            columns=["symbol", "mcap_cr", "trade_date"]),
        "board_meetings": pd.DataFrame(bms, columns=["symbol", "meeting_date", "known_date", "purpose"]),
        "corp_actions": pd.concat(bcs, ignore_index=True) if bcs else pd.DataFrame(
            columns=["symbol", "ex_date", "purpose", "known_date"]),
        "files": pd.DataFrame({"trade_date": [d for d, _ in files]}),
    }
    bm = out["board_meetings"]
    if not bm.empty:
        out["board_meetings"] = bm.sort_values("known_date").drop_duplicates(["symbol", "meeting_date"], keep="first")
    ca = out["corp_actions"]
    if not ca.empty:
        out["corp_actions"] = ca.dropna(subset=["ex_date"]).sort_values("known_date").drop_duplicates(
            ["symbol", "ex_date", "purpose"], keep="first")
    if cache is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            pd.to_pickle(out, cache)
        except OSError:  # pragma: no cover
            pass
    return out
