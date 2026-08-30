"""Cross-table flags: leading/improving groups, deal presence, deal timing."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

try:
    from App.market_summary import group_tape
except ModuleNotFoundError:
    from market_summary import group_tape  # type: ignore


def _ago_label(delta_days: int) -> str:
    if delta_days <= 0:
        return "today"
    if delta_days == 1:
        return "1d ago"
    return f"{delta_days}d ago"


def deal_when_map(db_path: Path, lookback_days: int = 30) -> dict[str, str]:
    """symbol -> 'today · 2d ago · 10d ago' from BUY session dates."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {}
    lookback_days = max(1, min(90, int(lookback_days)))
    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            frame = db.execute(
                f"""
                WITH latest AS (SELECT max(trade_date) d FROM deals)
                SELECT d.symbol, d.trade_date
                FROM deals d, latest
                WHERE d.side = 'BUY'
                  AND d.trade_date >= latest.d - INTERVAL {lookback_days} DAY
                GROUP BY 1, 2
                """
            ).fetchdf()
            as_of_row = db.execute("SELECT max(trade_date) d FROM deals").fetchone()
    except Exception:
        return {}
    if frame.empty or not as_of_row or as_of_row[0] is None:
        return {}
    as_of = pd.Timestamp(as_of_row[0]).normalize()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    out: dict[str, str] = {}
    for sym, chunk in frame.groupby(frame["symbol"].astype(str).str.upper()):
        dates = sorted(chunk["trade_date"].unique(), reverse=True)
        labels = [_ago_label(int((as_of - pd.Timestamp(d)).days)) for d in dates]
        out[str(sym)] = " · ".join(labels)
    return out


def leadership_sets(db_path: Path) -> dict[str, set[str]]:
    """Leading = best RS. Improving = not leading, week return > 0."""
    empty = {
        "lead_sectors": set(),
        "impr_sectors": set(),
        "lead_industries": set(),
        "impr_industries": set(),
    }
    try:
        sec = group_tape(db_path, "sector")
        ind = group_tape(db_path, "industry")
    except Exception:
        return empty
    out = dict(empty)

    def split(frame: pd.DataFrame) -> tuple[set[str], set[str]]:
        if frame.empty or "grp" not in frame.columns:
            return set(), set()
        ranked = frame.copy()
        if "rs" in ranked.columns:
            ranked = ranked.sort_values("rs", ascending=False, na_position="last")
        n = max(1, min(5, len(ranked)))
        lead = set(ranked.head(n)["grp"].astype(str))
        week = pd.to_numeric(ranked.get("week_pct"), errors="coerce") if "week_pct" in ranked.columns else pd.Series(dtype=float)
        impr = set()
        if not week.empty:
            for name, w in zip(ranked["grp"].astype(str), week):
                if name not in lead and pd.notna(w) and w > 0:
                    impr.add(name)
        return lead, impr

    out["lead_sectors"], out["impr_sectors"] = split(sec)
    out["lead_industries"], out["impr_industries"] = split(ind)
    return out


def annotate(
    df: pd.DataFrame,
    db_path: Path,
    *,
    flags: dict[str, set[str]] | None = None,
    when: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Add leader/deal flags used by the symbol badge slot. Does not drop columns."""
    if df is None or df.empty or "symbol" not in df.columns:
        return df
    out = df.copy()
    flags = flags if flags is not None else leadership_sets(db_path)
    when = when if when is not None else deal_when_map(db_path)
    sym = out["symbol"].astype(str).str.upper()
    if "sector" in out.columns:
        sec = out["sector"].astype(str)
        out["is_top_sector"] = sec.isin(flags["lead_sectors"]).map({True: True, False: False})
        out["is_improving_sector"] = sec.isin(flags["impr_sectors"]).map({True: True, False: False})
    else:
        out["is_top_sector"] = False
        out["is_improving_sector"] = False
    if "industry" in out.columns:
        ind = out["industry"].astype(str)
        out["is_top_industry"] = ind.isin(flags["lead_industries"]).map({True: True, False: False})
        out["is_improving_industry"] = ind.isin(flags["impr_industries"]).map({True: True, False: False})
    else:
        out["is_top_industry"] = False
        out["is_improving_industry"] = False
    out["deal_when"] = sym.map(when)
    has = out["deal_when"].notna() & ~out["deal_when"].astype(str).isin({"", "nan", "None"})
    out["has_deal"] = has.map({True: "Yes", False: "No"})
    return out


__all__ = ["annotate", "deal_when_map", "leadership_sets"]
