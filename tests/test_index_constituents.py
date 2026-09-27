"""Tests for index_constituents load + resolve_sector_index."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from Scripts.index_constituents import (
    ensure_index_constituents,
    load_membership_csv,
    resolve_sector_index,
)


CSV = Path("Input/reference/mp44_membership.csv")


@pytest.fixture(scope="module")
def membership():
    assert CSV.exists(), "mp44_membership.csv seed missing"
    return load_membership_csv(CSV)


def test_membership_seed_has_44_and_1200_plus(membership):
    assert membership["mp_index_name"].nunique() == 44
    assert len(membership) >= 1200


def test_ensure_index_constituents_table(tmp_path, membership):
    db = tmp_path / "t.duckdb"
    with duckdb.connect(str(db)) as con:
        n = ensure_index_constituents(con, CSV)
        assert n == len(membership)
        got = con.execute(
            "select count(distinct mp_index_name), count(*) from index_constituents"
        ).fetchone()
        assert got == (44, len(membership))


def test_single_membership_resolves(membership):
    # Pick a symbol that appears exactly once if possible
    counts = membership.groupby("symbol").size()
    singles = counts[counts == 1]
    assert not singles.empty
    sym = singles.index[0]
    expected = membership.loc[membership["symbol"] == sym, "mp_index_name"].iloc[0]
    assert resolve_sector_index(sym, membership) == expected


def test_multi_prefers_sectoral_over_thematic(membership):
    # HDFCBANK typically in Bank + Pvt Bank + Fin Service etc.
    hits = membership.loc[membership["symbol"] == "HDFCBANK"]
    if hits.empty:
        pytest.skip("HDFCBANK not in snapshot")
    chosen = resolve_sector_index("HDFCBANK", membership)
    assert chosen is not None
    # Should be Sectoral
    from thematic_engine import CANONICAL_44_INDICES

    assert CANONICAL_44_INDICES[chosen]["category"] == "Sectoral"
    # Prefer Pvt Bank over Bank when both present
    names = set(hits["mp_index_name"])
    if "Nifty Pvt Bank" in names and "Nifty Bank" in names:
        assert chosen == "Nifty Pvt Bank"


def test_none_returns_none_without_soft():
    empty = pd.DataFrame(columns=["index_name", "mp_index_name", "symbol", "as_of_date", "category", "clean_name"])
    assert resolve_sector_index("ZZZNONE", empty, None, soft_map={}) is None


def test_soft_fallback_industry():
    empty = pd.DataFrame(columns=["index_name", "mp_index_name", "symbol", "as_of_date", "category", "clean_name"])
    master = {"industry": "Private Sector Bank", "sector": "", "tags": []}
    got = resolve_sector_index("NOSUCH", empty, master)
    assert got in {"Nifty Bank", "Nifty Pvt Bank"}
