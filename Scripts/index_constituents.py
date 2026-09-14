"""Official CANONICAL_44 index membership + stock→index mapper.

Membership wins over soft INDEX_THEMATIC_MAP. Multi-hit: Sectoral > Thematic,
then specificity (longer clean_name), then mp_index_name.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

# Prefer App import when running from repo root; Scripts path otherwise.
try:
    from thematic_engine import CANONICAL_44_INDICES, INDEX_THEMATIC_MAP
except ImportError:  # pragma: no cover
    from App.thematic_engine import CANONICAL_44_INDICES, INDEX_THEMATIC_MAP  # type: ignore

DEFAULT_MEMBERSHIP_CSV = Path(__file__).resolve().parent.parent / "Input" / "reference" / "mp44_membership.csv"

SECTOR_INDEX_COLUMNS = (
    "sector_index_name",
    "rs_vs_sector_index_21d",
    "rs_vs_sector_index_63d",
)


def load_membership_csv(csv_path: Path | None = None) -> pd.DataFrame:
    path = Path(csv_path or DEFAULT_MEMBERSHIP_CSV)
    frame = pd.read_csv(path)
    required = {"index_name", "mp_index_name", "symbol", "as_of_date"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"membership CSV missing columns: {sorted(missing)}")
    frame = frame.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["mp_index_name"] = frame["mp_index_name"].astype(str).str.strip()
    frame["index_name"] = frame["index_name"].astype(str).str.strip()
    frame["category"] = frame["mp_index_name"].map(
        lambda n: CANONICAL_44_INDICES.get(n, {}).get("category", "Thematic")
    )
    frame["clean_name"] = frame["mp_index_name"].map(
        lambda n: CANONICAL_44_INDICES.get(n, {}).get("clean_name", n)
    )
    return frame.drop_duplicates(["mp_index_name", "symbol"], keep="last").reset_index(drop=True)


def ensure_index_constituents(con, csv_path: Path | None = None) -> int:
    """Create/replace DuckDB table index_constituents from CSV. Returns row count."""
    frame = load_membership_csv(csv_path)
    con.register("index_constituents_df", frame)
    con.execute("DROP TABLE IF EXISTS index_constituents")
    con.execute(
        """
        CREATE TABLE index_constituents AS
        SELECT index_name, mp_index_name, symbol, CAST(as_of_date AS DATE) AS as_of_date,
               category, clean_name
        FROM index_constituents_df
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_index_constituents_symbol ON index_constituents(symbol)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_index_constituents_mp ON index_constituents(mp_index_name)"
    )
    return len(frame)


def _specificity_score(mp_index_name: str, clean_name: str) -> int:
    """Higher = more specific. Prefer longer clean names; boost known narrow banks."""
    boost = 0
    name = mp_index_name.lower()
    if "pvt bank" in name or "private bank" in name or "psu bank" in name:
        boost += 50
    if "exbnk" in name or "ex-bank" in name or "ex bank" in name:
        boost += 40
    if "finsrv" in name.replace(" ", "") or "25" in name:
        boost += 10
    return len(clean_name or mp_index_name) + boost


def resolve_sector_index(
    symbol: str,
    membership: pd.DataFrame,
    master_row: dict[str, Any] | None = None,
    soft_map: dict | None = None,
) -> str | None:
    """Return one mp_index_name for symbol, or None."""
    sym = str(symbol or "").strip().upper()
    if not sym or membership is None or membership.empty:
        return _soft_resolve(master_row, soft_map or INDEX_THEMATIC_MAP)

    hits = membership.loc[membership["symbol"] == sym]
    if hits.empty:
        return _soft_resolve(master_row, soft_map or INDEX_THEMATIC_MAP)
    if len(hits) == 1:
        return str(hits.iloc[0]["mp_index_name"])

    rows = []
    for _, r in hits.iterrows():
        cat = str(r.get("category") or "Thematic")
        cat_rank = 0 if cat == "Sectoral" else 1
        clean = str(r.get("clean_name") or r["mp_index_name"])
        spec = _specificity_score(str(r["mp_index_name"]), clean)
        rows.append((cat_rank, -spec, str(r["mp_index_name"])))
    rows.sort()
    return rows[0][2]


def _soft_resolve(master_row: dict[str, Any] | None, soft_map: dict) -> str | None:
    """Industry → sector → tag soft fallback against INDEX_THEMATIC_MAP."""
    if not master_row or not soft_map:
        return None
    industry = str(master_row.get("industry") or "").strip()
    sector = str(master_row.get("sector") or "").strip()
    tags = master_row.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]

    # Build reverse: prefer industry matches, then sector, then tag.
    industry_hits: list[tuple[int, str, str]] = []
    sector_hits: list[tuple[int, str, str]] = []
    tag_hits: list[tuple[int, str, str]] = []

    for index_name, mapping in soft_map.items():
        meta = CANONICAL_44_INDICES.get(index_name, {})
        cat = meta.get("category", "Thematic")
        cat_rank = 0 if cat == "Sectoral" else 1
        clean = meta.get("clean_name", index_name)
        spec = _specificity_score(index_name, clean)
        inds = mapping.get("industries") or []
        secs = mapping.get("sectors") or []
        tgs = mapping.get("tags") or []
        if industry and industry in inds:
            industry_hits.append((cat_rank, -spec, index_name))
        if sector and sector in secs:
            sector_hits.append((cat_rank, -spec, index_name))
        if tags and any(t in tgs for t in tags):
            tag_hits.append((cat_rank, -spec, index_name))

    for bucket in (industry_hits, sector_hits, tag_hits):
        if bucket:
            bucket.sort()
            return bucket[0][2]
    return None


def map_symbols_to_indices(
    symbols: list[str] | pd.Series,
    membership: pd.DataFrame,
    master: pd.DataFrame | None = None,
) -> pd.Series:
    """Vector-friendly map: returns Series of sector_index_name aligned to symbols index."""
    syms = pd.Series(symbols).astype(str).str.strip().str.upper()
    master_by_sym: dict[str, dict] = {}
    if master is not None and not master.empty and "symbol" in master.columns:
        m = master.copy()
        m["symbol"] = m["symbol"].astype(str).str.strip().str.upper()
        for _, row in m.iterrows():
            master_by_sym[str(row["symbol"])] = row.to_dict()

    # Pre-group membership by symbol for speed
    grouped = {
        sym: grp for sym, grp in membership.groupby("symbol", sort=False)
    }

    out = []
    for sym in syms:
        if sym in grouped:
            out.append(resolve_sector_index(sym, grouped[sym], master_by_sym.get(sym)))
        else:
            out.append(resolve_sector_index(sym, membership.iloc[0:0], master_by_sym.get(sym)))
    return pd.Series(out, index=syms.index, dtype=object)
