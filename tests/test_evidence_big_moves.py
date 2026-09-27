"""Big movers: event definition, point-in-time mcap eligibility, matched controls, lift with n, purged split."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from Scripts.evidence.big_moves import FEATURES, build_big_moves, label_events, stock_day_frame
from Scripts.evidence.common import LEVELS, environment_states, group_states, pit_mcap, purged_split
from tests import evidence_fixture as fx


@pytest.fixture(scope="module")
def built():
    ind = fx.indicators().sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    master = fx.master()
    mc = pit_mcap(ind, master=master)
    ind["mcap_cr"] = mc["mcap_cr"].to_numpy()
    env = environment_states(fx.regime(ind), None)
    gl = {lv: group_states(None, None, lv) for lv in LEVELS}
    sd = stock_day_frame(ind, mcap=mc, master=master, reference=None, env=env, group_levels=gl, deals=None, pr=None,
                         events_tbl=None, corp_actions=None)
    out = build_big_moves(sd, pr=None, events_tbl=None, corp_actions=None, deals=None, group_levels=gl,
                          index_daily=fx.index_daily(), sessions=pd.Series(fx.SESSIONS))
    return sd, out


def test_upper_circuit_event_starts_on_the_circuit_day(built):
    sd, out = built
    ev = out["_all_events"].set_index("event_id")
    jump = ev.loc[f"JUMPA:{fx.SESSIONS[200]:%Y%m%d}"]
    assert jump["trigger"] == "upper_circuit" and jump["uc_streak"] == 3
    assert jump["confirmed_date"] == fx.SESSIONS[200]
    assert jump["move_pct"] > 30 and bool(jump["eligible"])
    assert jump["band_basis"] == "current_master" and jump["mcap_basis"] == "price_scaled_current"


def test_small_cap_moves_are_not_eligible(built):
    _sd, out = built
    ev = out["_all_events"]
    tiny = ev.loc[ev["symbol"] == "TINY"]
    assert len(tiny) >= 1 and not tiny["eligible"].any()
    assert (out["big_move_events"]["mcap_cr_at_event"] >= 1000).all()
    assert "TINY" not in set(out["big_move_events"]["symbol"])


def test_fwd_return_events_start_after_the_trough_and_confirm_later():
    dates = pd.bdate_range("2024-01-01", periods=120)
    close = np.r_[np.full(70, 100.0), np.linspace(98, 97, 5), np.linspace(100, 135, 10), np.full(35, 135.0)]
    sd = pd.DataFrame({"symbol": "RUN", "series": "EQ", "trade_date": dates, "close_price": close, "high_price": close,
                       "prev_close": np.r_[close[0], close[:-1]], "band": np.nan, "band_basis": None,
                       "row_in_symbol": np.arange(120.0), "mcap_cr": 5000.0, "mcap_basis": "reference_asof", "adv_cr": 5.0})
    ev, flags = label_events(sd)
    assert len(ev) == 1
    e = ev.iloc[0]
    assert e["trigger"] == "up30_20d"
    assert e["event_date"] == dates[75]  # session after the lowest close (97 on day 74)
    assert e["confirmed_date"] > e["event_date"]
    assert bool(e["eligible"])


def test_controls_match_date_industry_and_are_clean(built):
    sd, out = built
    ctrl = out["big_move_controls"]
    ev = out["big_move_events"].set_index("event_id")
    assert not ctrl.empty
    for r in ctrl.itertuples():
        e = ev.loc[r.event_id]
        row = sd.iloc[r.control_pos_t1]
        assert row["trade_date"] == sd["trade_date"].iloc[int(out["_all_events"].set_index("event_id").loc[r.event_id, "_pos"]) - 1]
        assert row["industry"] == e["industry"] and r.control_symbol != e["symbol"]
        assert r.match_level.startswith("industry+mcap_quintile")
    assert (ctrl.groupby("event_id").size() <= 3).all()


def test_lift_table_prints_n_and_uses_purged_split(built):
    _sd, out = built
    lift = out["big_move_lift"]
    assert set(FEATURES) == set(lift.loc[lift["subset"] == "all", "feature"])
    for col in ("n_events", "n_controls", "k_events", "n_events_train", "n_events_test", "lift_train", "lift_test"):
        assert col in lift.columns
    assert lift["label"].eq("insufficient sample").all()  # a handful of synthetic events: never a number without n
    feats = out["big_move_features"]
    assert set(feats["offset"]) == {1, 5, 20, 60} and set(feats["role"]) <= {"event", "control"}
    paths = out["big_move_paths"]
    assert set(paths["offset"]) == set(range(-60, 21))
    ev = out["big_move_events"]
    assert all(len(p) == 81 for p in ev["path_pct"])
    assert ev["path_pct"].iloc[0][59] == pytest.approx(0.0)  # T-1 vs itself


def test_purged_split_leaves_an_embargo_gap():
    sess = pd.Series(pd.bdate_range("2024-01-01", periods=400))
    dates = sess.sample(300, random_state=1, replace=True).reset_index(drop=True)
    train, test, test_start = purged_split(dates, sessions=sess)
    assert train.any() and test.any()
    last_train = dates[train].max()
    gap = (sess >= last_train).sum() - (sess >= test_start).sum()
    assert gap >= 60
    assert (dates[test] >= test_start).all()


def test_stock_day_features_are_point_in_time():
    ind = fx.indicators().sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    master = fx.master()

    def frame(src: pd.DataFrame) -> pd.DataFrame:
        src = src.reset_index(drop=True)
        mc = pit_mcap(src, reference=pd.DataFrame({"symbol": src["symbol"], "effective_date": src["trade_date"],
                                                   "market_cap_cr": 5000.0}))
        return stock_day_frame(src, mcap=mc, master=master, reference=None, env=pd.DataFrame(), group_levels={},
                               deals=None, pr=None, events_tbl=None, corp_actions=None)

    full = frame(ind)
    cut = fx.SESSIONS[240]
    part = frame(ind.loc[ind["trade_date"] <= cut])
    a = full.loc[full["trade_date"] <= cut, ["symbol", "trade_date", *FEATURES]].reset_index(drop=True)
    b = part[["symbol", "trade_date", *FEATURES]].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
