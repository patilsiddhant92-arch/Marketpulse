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


def _seed_renamed_split_root(tmp_path):
    """Real-world shape (HEG -> HEGAM, 2026-09-22): a 1:5 split with ex-date 2024-10-18 filed
    under the OLD symbol, and a later rename OLD -> NEW that the daily append never applies to
    the price rows (they stay under OLD)."""
    archive = tmp_path / "Input" / "archive"
    archive.mkdir(parents=True)
    reference = tmp_path / "Input" / "reference"
    reference.mkdir(parents=True)
    with zipfile.ZipFile(archive / "PR141024.zip", "w") as zf:
        zf.writestr(
            "bc14102024.csv",
            "SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE\n"
            "EQ,OLD,Old Co Ltd,2024-10-18,,,2024-10-18,,,FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RS 2/- PER SHARE\n",
        )
    (reference / "symbolchange.csv").write_text("Old Co Ltd,OLD,NEW,22-SEP-2026\n")


def test_adjust_prices_applies_new_symbol_events_to_old_symbol_price_rows(tmp_path):
    _seed_renamed_split_root(tmp_path)
    dates = pd.to_datetime(["2024-10-15", "2024-10-16", "2024-10-17", "2024-10-18", "2024-10-21", "2024-10-22"])
    closes = [2000.0, 2010.0, 2020.0, 405.0, 410.0, 412.0]
    old = pd.DataFrame({
        "symbol": "OLD", "trade_date": dates, "open_price": closes, "high_price": closes,
        "low_price": closes, "close_price": closes, "volume": 1000.0,
    })
    other = pd.DataFrame({
        "symbol": "ZZZ", "trade_date": dates, "open_price": 50.0, "high_price": 50.0,
        "low_price": 50.0, "close_price": 50.0, "volume": 10.0,
    })
    prices = pd.concat([other, old], ignore_index=True)
    prices.index = prices.index + 100  # a non-default index must survive unchanged

    adjusted, adjustments = adjust_prices(prices, tmp_path, cache_dir=None)

    # Returned frame keeps the original symbols, row order and index.
    assert adjusted.index.equals(prices.index)
    assert adjusted["symbol"].tolist() == prices["symbol"].tolist()
    assert "NEW" not in set(adjusted["symbol"])

    o = adjusted[adjusted["symbol"] == "OLD"].set_index("trade_date")
    for day, close in zip(dates[:3], closes[:3]):
        assert math.isclose(o.loc[day, "adj_close_price"], close * 0.2, rel_tol=1e-9)
        assert math.isclose(o.loc[day, "price_factor"], 0.2, rel_tol=1e-9)
        assert math.isclose(o.loc[day, "adj_volume"], 5000.0, rel_tol=1e-9)
    for day, close in zip(dates[3:], closes[3:]):
        assert math.isclose(o.loc[day, "adj_close_price"], close, rel_tol=1e-9)
    assert (adjusted.loc[adjusted["symbol"] == "ZZZ", "price_factor"] == 1.0).all()

    split = adjustments[(adjustments["ex_date"] == pd.Timestamp("2024-10-18")) & (adjustments["kind"] == "split")]
    assert len(split) == 1
    assert split.iloc[0]["symbol"] == "NEW"
    assert bool(split.iloc[0]["applied"])
    assert not (adjustments["kind"] == "unexplained_gap").any()


def test_adjust_prices_bridges_a_consolidation_trading_halt(tmp_path):
    """SHEKHAWATI shape end to end: bc 'CNSLDATN RE 1 TO RS 10' ex 2024-08-28, last session
    08-27, trading resumes 09-10 with the mcap face-value change and the price gap. The factor
    must be applied once (x10), not once per source (x100)."""
    archive = tmp_path / "Input" / "archive"
    archive.mkdir(parents=True)
    with zipfile.ZipFile(archive / "PR220824.zip", "w") as zf:
        zf.writestr(
            "bc22082024.csv",
            "SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE\n"
            "EQ,SHEK,Shek Ltd,2024-08-28,,,2024-08-28,,,CNSLDATN RE 1 TO RS 10\n",
        )
    (archive / "mcap27082024.csv").write_text(
        MCAP_HDR + "27 AUG 2024,SHEK,EQ,SHEK LTD,Listed,27 AUG 2024,1.00,100000000,8.82,1.0\n")
    (archive / "mcap10092024.csv").write_text(
        MCAP_HDR + "10 SEP 2024,SHEK,EQ,SHEK LTD,Listed,10 SEP 2024,10.00,10000000,86.43,1.0\n")
    dates = pd.to_datetime(["2024-08-23", "2024-08-26", "2024-08-27", "2024-09-10", "2024-09-11"])
    closes = [8.89, 9.00, 8.82, 86.43, 84.70]
    prices = pd.DataFrame({"symbol": "SHEK", "trade_date": dates, "open_price": closes, "high_price": closes,
                           "low_price": closes, "close_price": closes, "volume": 1000.0})

    adjusted, adjustments = adjust_prices(prices, tmp_path, cache_dir=None)

    assert adjusted["price_factor"].tolist() == [10.0, 10.0, 10.0, 1.0, 1.0]
    assert math.isclose(adjusted.loc[2, "adj_close_price"], 88.2, rel_tol=1e-9)
    applied = adjustments[adjustments["applied"]]
    assert len(applied) == 1 and applied.iloc[0]["confidence"] == "confirmed"
    assert not (adjustments["kind"] == "unexplained_gap").any()


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
