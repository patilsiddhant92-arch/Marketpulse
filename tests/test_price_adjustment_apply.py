from __future__ import annotations

import math

import pandas as pd

from price_adjustment import apply_adjustments, cumulative_price_factor, indicator_input

PRICES = pd.DataFrame({
    "symbol": ["GOODLUCK"] * 4 + ["TCC"] * 3,
    "trade_date": pd.to_datetime(["2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24",
                                  "2026-09-02", "2026-09-03", "2026-09-04"]),
    "open_price": [1340.0, 1385.0, 493.2, 486.8, 500.0, 505.0, 102.0],
    "high_price": [1370.0, 1445.0, 494.4, 490.0, 510.0, 512.0, 104.0],
    "low_price": [1330.0, 1380.0, 469.8, 470.0, 495.0, 500.0, 100.0],
    "close_price": [1363.3, 1439.4, 490.9, 477.7, 505.0, 510.0, 103.0],
    "last_price": [1363.0, 1439.0, 490.4, 477.5, 505.0, 510.0, 103.0],
    "avg_price": [1360.0, 1420.0, 483.5, 480.0, 503.0, 508.0, 102.0],
    "prev_close": [1330.0, 1363.3, 1439.4, 490.9, 500.0, 505.0, 510.0],
    "volume": [100.0, 120.0, 646400.0, 300000.0, 10.0, 12.0, 70.0],
    "delivery_qty": [50.0, 60.0, 198936.0, 150000.0, 5.0, 6.0, 35.0],
    "delivery_pct": [50.0, 50.0, 30.78, 50.0, 50.0, 50.0, 50.0],
})
ADJ = pd.DataFrame({"symbol": ["GOODLUCK", "TCC", "TCC"],
                    "ex_date": pd.to_datetime(["2026-08-21", "2026-09-04", "2026-01-01"]),
                    "kind": ["bonus", "split", "rights"], "factor": [1 / 3, 0.2, None],
                    "source": ["bc", "bc", "bc"], "confidence": ["confirmed"] * 3,
                    "applied": [True, True, False], "description": ["", "", ""]})


def test_cumulative_factor_only_before_ex_date_and_only_applied():
    f = cumulative_price_factor(PRICES, ADJ).tolist()
    assert [round(x, 6) for x in f] == [round(1 / 3, 6)] * 2 + [1.0, 1.0] + [0.2, 0.2, 1.0]


def test_adjusted_series_has_no_fake_crash_and_real_ex_date_move():
    a = apply_adjustments(PRICES, ADJ)
    g = a[a.symbol == "GOODLUCK"].set_index("trade_date")
    assert math.isclose(g.loc["2026-08-20", "adj_close_price"], 1439.4 / 3, rel_tol=1e-9)
    ex = g.loc["2026-08-21"]
    day_move = ex["adj_close_price"] / ex["adj_prev_close"] - 1
    assert -0.05 < day_move < 0.05                       # ≈ +2.3%, not -66%
    assert math.isclose(g.loc["2026-08-20", "adj_volume"], 360.0)
    assert g.loc["2026-08-21", "delivery_pct"] == 30.78  # unchanged
    assert g.loc["2026-08-20", "close_price"] == 1439.4  # raw kept


def test_indicator_input_swaps_in_adjusted_values():
    ind = indicator_input(apply_adjustments(PRICES, ADJ))
    # adj_* are dropped (already swapped in under their unprefixed names), but price_factor is
    # kept: calc_indicators needs it to rescale the raw NSE 52-week high/low onto adjusted scale.
    assert not any(c.startswith("adj_") for c in ind.columns) and "price_factor" in ind.columns
    t = ind[ind.symbol == "TCC"].set_index("trade_date")
    assert math.isclose(t.loc["2026-09-03", "close_price"], 102.0)
    assert math.isclose(t.loc["2026-09-04", "prev_close"], 102.0)


def test_reapplying_drops_stale_columns():
    once = apply_adjustments(PRICES, ADJ)
    twice = apply_adjustments(once, ADJ)
    assert list(once.columns) == list(twice.columns)


def test_applied_as_strings_matches_bool_and_ignores_false_string():
    # The ignored (applied=False) row is given a real, non-null factor with an ex_date after
    # every TCC price row, so a "False" string wrongly parsed as truthy (Python's bool("False")
    # is True) would visibly change the cumulative factor rather than being masked by a null
    # factor or a too-early ex_date.
    adj_bool = ADJ.copy()
    adj_bool["factor"] = [1 / 3, 0.2, 0.5]
    adj_bool["ex_date"] = pd.to_datetime(["2026-08-21", "2026-09-04", "2026-09-05"])
    adj_bool["applied"] = [True, True, False]

    adj_str = adj_bool.copy()
    adj_str["applied"] = ["True", "True", "False"]

    bool_result = cumulative_price_factor(PRICES, adj_bool).tolist()
    str_result = cumulative_price_factor(PRICES, adj_str).tolist()
    assert str_result == bool_result
    # sanity: the False-string row's factor must really be excluded, not just coincidentally equal
    assert [round(x, 6) for x in bool_result] == [round(1 / 3, 6)] * 2 + [1.0, 1.0] + [0.2, 0.2, 1.0]


def test_applied_as_nullable_boolean_with_na_is_not_applied():
    adj_na = ADJ.copy()
    adj_na["applied"] = pd.array([True, True, pd.NA], dtype="boolean")
    result = cumulative_price_factor(PRICES, adj_na).tolist()
    expected = cumulative_price_factor(PRICES, ADJ).tolist()
    assert result == expected


def test_duplicate_index_label_preserved():
    # Reverse the row order (interleaving symbols) so the internal symbol/trade_date sort used
    # for adj_prev_close actually permutes rows relative to the input order/index — on
    # already-sorted input the sort would be a no-op and wouldn't exercise the reindex-with-
    # duplicate-labels path at all.
    shuffled = PRICES.iloc[::-1].reset_index(drop=True)
    baseline = apply_adjustments(shuffled, ADJ)

    dup_index = pd.Index([0, 1, 2, 3, 4, 5, 5])
    prices_dup = shuffled.copy()
    prices_dup.index = dup_index

    result = apply_adjustments(prices_dup, ADJ)

    assert list(result.index) == list(dup_index)
    assert result["adj_close_price"].tolist() == baseline["adj_close_price"].tolist()
    assert result["adj_prev_close"].tolist() == baseline["adj_prev_close"].tolist()


def test_missing_optional_columns_do_not_crash():
    prices_min = PRICES.drop(columns=["last_price", "avg_price", "delivery_qty"])

    result = apply_adjustments(prices_min, ADJ)

    assert "adj_last_price" not in result.columns
    assert "adj_avg_price" not in result.columns
    assert "adj_delivery_qty" not in result.columns

    baseline = apply_adjustments(PRICES, ADJ)
    assert result["adj_close_price"].tolist() == baseline["adj_close_price"].tolist()

    ind = indicator_input(result)
    assert not any(c.startswith("adj_") for c in ind.columns)
