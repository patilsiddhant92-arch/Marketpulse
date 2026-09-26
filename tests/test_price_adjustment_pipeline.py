from __future__ import annotations

import math
import zipfile

import numpy as np
import pandas as pd

from price_adjustment import ACTION_COLUMNS, actions_from_mcap, adjust_prices, read_mcap_frames
from price_adjustment import _rename_symbols  # noqa: PLC2701 -- exercised directly, see test below
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


def test_adjust_prices_suppresses_events_with_future_ex_date(tmp_path):
    # Real-world case: AASTHA's "BONUS 1:1" bc row carries ex_date 2026-09-28, filed ahead of
    # time, while the last available trading session is 2026-09-25. Applying it today would
    # back-adjust the symbol's *entire* history before the event has actually happened.
    _seed_root(tmp_path)
    prices = PRICES[PRICES["symbol"] == "GOODLUCK"].reset_index(drop=True)
    last_session = prices["trade_date"].max()
    future_ex_date = last_session + pd.Timedelta(days=10)

    extra_actions = pd.DataFrame([{
        "symbol": "GOODLUCK",
        "ex_date": future_ex_date,
        "kind": "bonus",
        "factor": 0.5,
        "description": "BONUS 1:1",
        "source": "bc",
    }], columns=ACTION_COLUMNS)

    _, adjustments = adjust_prices(prices, tmp_path, extra_actions=extra_actions)

    future_row = adjustments[adjustments["ex_date"] == future_ex_date].iloc[0]
    assert not future_row["applied"]
    assert future_row["confidence"] == "pending_ex_date"

    # The already-confirmed, in-range bc+mcap GOODLUCK event from _seed_root is untouched.
    confirmed_row = adjustments[adjustments["ex_date"] == pd.Timestamp("2026-08-21")].iloc[0]
    assert confirmed_row["applied"]
    assert confirmed_row["confidence"] == "confirmed"


def test_mcap_rename_keeps_symbol_history_continuous_across_rename(tmp_path):
    # A face-value/issue-size change spanning a symbol rename must be attributed to ONE
    # continuous symbol history, not silently split into two unrelated per-symbol groups in
    # actions_from_mcap (which would drop the event entirely, since each half looks like a
    # single, unremarkable snapshot on its own).
    archive = tmp_path / "Input" / "archive"
    archive.mkdir(parents=True)
    (archive / "mcap15122025.csv").write_text(
        MCAP_HDR + "15 DEC 2025,RENAMECO_OLD,EQ,RENAMECO LTD,Listed,15 DEC 2025,2.00,10000000,1000.00,1.0\n"
    )
    (archive / "mcap15012026.csv").write_text(
        MCAP_HDR + "15 JAN 2026,RENAMECO_NEW,EQ,RENAMECO LTD,Listed,15 JAN 2026,2.00,30000000,1000.00,1.0\n"
    )
    changes = pd.DataFrame({
        "old_symbol": ["RENAMECO_OLD"],
        "new_symbol": ["RENAMECO_NEW"],
        "change_date": [pd.Timestamp("2026-01-01")],
    })

    frames = read_mcap_frames(tmp_path, [])

    # Without the pre-rename, the jump straddles two distinct symbols and is invisible.
    assert actions_from_mcap(frames).empty

    renamed = _rename_symbols(frames, changes, "file_date")
    actions = actions_from_mcap(renamed)

    row = actions[actions["symbol"] == "RENAMECO_NEW"]
    assert len(row) == 1
    assert row.iloc[0]["kind"] == "bonus"
    assert math.isclose(row.iloc[0]["factor"], 1 / 3)


def test_calc_indicators_rescales_nse_52w_by_price_factor():
    # Reproduces the GOODLUCK scale-mismatch bug: calc_indicators receives already-adjusted
    # OHLCV (via indicator_input) plus price_factor, but the NSE-reported 52w high/low in
    # `enrichment` are never back-adjusted. Without rescaling, away_52w_high_pct compares an
    # adjusted close against a raw-scale high and comes out wildly wrong (~-71% instead of the
    # real, scale-invariant distance).
    from build_database import calc_indicators

    factor = 1 / 3
    raw_close = [1350.0, 1363.3, 1439.4]
    prices = pd.DataFrame({
        "symbol": ["GOODLUCK"] * 3,
        "trade_date": pd.to_datetime(["2026-08-18", "2026-08-19", "2026-08-20"]),
        "open_price": [c * factor for c in [1330.0, 1340.0, 1385.0]],
        "high_price": [c * factor for c in [1360.0, 1370.0, 1445.0]],
        "low_price": [c * factor for c in [1320.0, 1330.0, 1380.0]],
        "close_price": [c * factor for c in raw_close],
        "volume": [100.0, 100.0, 120.0],
        "turnover_cr": [1.0, 1.0, 1.0],
        "delivery_qty": [50.0, 50.0, 60.0],
        "delivery_pct": [50.0, 50.0, 50.0],
        "prev_close": [np.nan] + [c * factor for c in raw_close[:-1]],
        "price_factor": [factor] * 3,
    })
    enrichment = pd.DataFrame({"symbol": ["GOODLUCK"], "high_52w": [1672.10], "low_52w": [400.0]})

    result = calc_indicators(prices, enrichment)
    row = result[result["trade_date"] == "2026-08-20"].iloc[0]

    expected_high_52w = 1672.10 * factor
    assert math.isclose(row["high_52w"], expected_high_52w, rel_tol=1e-9)
    # Scale-invariant sanity check: since close and high_52w are scaled by the same factor, the
    # % distance must equal what it would have been comparing the raw (unadjusted) numbers.
    expected_away_pct = (raw_close[-1] / 1672.10 - 1) * 100
    assert math.isclose(row["away_52w_high_pct"], expected_away_pct, rel_tol=1e-6)
    assert expected_away_pct > -20  # sanity: nowhere near the ~-71% scale-mismatch bug value
