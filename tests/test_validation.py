import pandas as pd


def test_walk_forward_splits_have_disjoint_dates():
    from Scripts.validation import walk_forward_splits

    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"])
    folds = list(walk_forward_splits(dates, min_train_dates=2, test_dates=1))

    assert folds
    for train, test in folds:
        assert set(train).isdisjoint(set(test))


def test_future_high_label_uses_maximum_next_window_high():
    from Scripts.validation import future_high_label

    prices = pd.DataFrame({"high_price": [100, 101, 110, 105], "trade_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"])})

    assert future_high_label(prices, 0, 2, 1.05) is True
