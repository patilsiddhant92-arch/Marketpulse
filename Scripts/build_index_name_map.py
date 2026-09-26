"""Derive ind_close_all → canonical (MA) index names by matching closing values on common dates."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from config import ROOT_DIR
from index_history import load_all_market_activity_history, parse_ind_close_all

MAP_PATH = ROOT_DIR / "Input" / "reference" / "index_name_map.csv"


def _norm_name(name: str) -> str:
    return str(name).strip().lower().replace(" ", "")


def derive_name_map(close_all: pd.DataFrame, ma: pd.DataFrame, min_overlap: int = 5, tol: float = 0.01) -> pd.DataFrame:
    a = close_all[["trade_date", "index_name", "close_price"]].rename(columns={"index_name": "source_name", "close_price": "c1"})
    b = ma[["trade_date", "index_name", "close_price"]].rename(columns={"index_name": "canonical_name", "close_price": "c2"})
    j = a.merge(b, on="trade_date")
    j = j[(j["c1"] - j["c2"]).abs() <= tol]
    counts = j.groupby(["source_name", "canonical_name"]).size().rename("overlap_days").reset_index()
    counts = counts[counts["overlap_days"] >= min_overlap]
    best = counts.sort_values(["source_name", "overlap_days"], ascending=[True, False]).drop_duplicates("source_name")

    # Enforce one-to-one: keep only the best source per canonical_name too, so two different
    # ind_close_all names never collapse onto the same canonical index downstream.
    best = best.copy()
    best["_exact"] = best.apply(
        lambda r: 0 if _norm_name(r["source_name"]) == _norm_name(r["canonical_name"]) else 1, axis=1
    )
    best = best.sort_values(
        ["canonical_name", "overlap_days", "_exact", "source_name"],
        ascending=[True, False, True, True],
    )
    deduped = best.drop_duplicates("canonical_name", keep="first")
    dropped = best.drop(deduped.index)
    for _, row in dropped.iterrows():
        print(
            f"WARNING: dropping duplicate mapping source={row['source_name']!r} -> "
            f"canonical={row['canonical_name']!r} (overlap_days={row['overlap_days']}); "
            f"canonical already claimed by a source with equal or better overlap"
        )
    deduped = deduped.drop(columns="_exact").sort_values("source_name")
    return deduped[["source_name", "canonical_name", "overlap_days"]].reset_index(drop=True)


def main() -> int:
    folders = [ROOT_DIR / "Input" / "archive", ROOT_DIR / "Input" / "archive" / "backfill" / "index", ROOT_DIR / "Input" / "daily"]
    frames = [parse_ind_close_all(p) for f in folders if f.exists() for p in sorted(f.glob("ind_close_all_*.csv"))]
    if not frames:
        print("No ind_close_all files found; run the backfill first.")
        return 1
    m = derive_name_map(pd.concat(frames, ignore_index=True), load_all_market_activity_history(ROOT_DIR))
    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    m.to_csv(MAP_PATH, index=False)
    print(f"Wrote {len(m)} mappings to {MAP_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
