from __future__ import annotations

import math
import zipfile

import pandas as pd

from price_adjustment import ACTION_COLUMNS, adjust_prices
from test_price_adjustment_apply import PRICES

MCAP_HDR = ("Trade Date,Symbol,Series,Security Name,Category,Last Trade Date,"
            "Face Value(Rs.),Issue Size,Close Price/Paid up value(Rs.),Market Cap(Rs.)\n")


def _seed_root(tmp_path):
    archive = tmp_path / "Input" / "archive"
    archive.mkdir(parents=True)
    reference = tmp_path / "Input" / "reference"
    reference.mkdir(parents=True)

    zip_path = archive / "PR210826.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "bc21082026.csv",
            "SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE\n"
            "EQ,GOODLUCK,Goodluck India Ltd,2026-08-21,,,2026-08-21,,,BONUS 2:1\n",
        )

    (archive / "mcap20082026.csv").write_text(
        MCAP_HDR + "20 AUG 2026,GOODLUCK,EQ,GOODLUCK INDIA,Listed,20 AUG 2026,2.00,10000000,1439.40,1.0\n"
    )
    (archive / "mcap21082026.csv").write_text(
        MCAP_HDR + "21 AUG 2026,GOODLUCK,EQ,GOODLUCK INDIA,Listed,21 AUG 2026,2.00,30000000,490.90,1.0\n"
    )

    (reference / "symbolchange.csv").write_text(
        "Goodluck India Ltd,GOODLUCKOLD,GOODLUCK,01-JAN-2026\n"
    )
    return zip_path


def test_adjust_prices_reconciles_bc_and_mcap_and_applies(tmp_path):
    _seed_root(tmp_path)
    prices = PRICES[PRICES["symbol"] == "GOODLUCK"].reset_index(drop=True)

    adjusted, adjustments = adjust_prices(prices, tmp_path)

    g = adjusted.set_index("trade_date")
    assert math.isclose(g.loc["2026-08-20", "adj_close_price"], 1439.4 / 3, rel_tol=1e-9)

    row = adjustments[adjustments["symbol"] == "GOODLUCK"].iloc[0]
    assert row["source"] == "bc+mcap_issue"
    assert row["confidence"] == "confirmed"
    assert row["applied"]


def test_adjust_prices_renames_extra_actions_via_symbolchange(tmp_path):
    _seed_root(tmp_path)
    prices = PRICES[PRICES["symbol"] == "GOODLUCK"].reset_index(drop=True)

    extra_actions = pd.DataFrame([{
        "symbol": "GOODLUCKOLD",
        "ex_date": pd.Timestamp("2025-06-01"),
        "kind": "bonus",
        "factor": 0.5,
        "description": "BONUS 1:1",
        "source": "bc",
    }], columns=ACTION_COLUMNS)

    _, adjustments = adjust_prices(prices, tmp_path, extra_actions=extra_actions)

    renamed = adjustments[adjustments["ex_date"] == pd.Timestamp("2025-06-01")]
    assert len(renamed) == 1
    assert renamed.iloc[0]["symbol"] == "GOODLUCK"
