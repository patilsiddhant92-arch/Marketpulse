"""Market analogs and stock analogs: k, exclusion window, point-in-time standardisation (spec §5)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from Scripts.evidence.analogs import (ENV_FEATURES, analog_summary, environment_vectors, market_analogs,
                                      stock_analogs)
from tests import evidence_fixture as fx


def _env(n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"trade_date": pd.bdate_range("2022-01-03", periods=n)})
    for f in ENV_FEATURES:
        df[f] = np.cumsum(rng.normal(0, 1, n))
    for h in (5, 20, 60):
        df[f"fwd_midsml400_{h}d_pct"] = rng.normal(0, 3, n)
    df["next_month_follow_through_pct"] = rng.uniform(20, 70, n)
    return df


def test_k10_and_recent_60_sessions_excluded():
    env = _env()
    out = market_analogs(env)
    assert not out.empty
    assert (out.groupby("as_of_date").size() == 10).all()
    pos = pd.Series(np.arange(len(env)), index=env["trade_date"])
    gap = pos.reindex(out["as_of_date"]).to_numpy() - pos.reindex(out["analog_date"]).to_numpy()
    assert gap.min() >= 60
    first_query = pos[out["as_of_date"].min()]
    assert first_query >= 60  # needs 60 sessions of standardisation history and 60 excluded


def test_analogs_do_not_change_when_future_rows_are_appended():
    env = _env()
    q = env["trade_date"].iloc[200]
    full = market_analogs(env, query_dates=[q])
    trunc = market_analogs(env.iloc[:201].copy(), query_dates=[q])
    pd.testing.assert_frame_equal(full.reset_index(drop=True), trunc.reset_index(drop=True))


def test_environment_vector_is_point_in_time():
    ind = fx.indicators()
    idx = fx.index_daily()
    b = fx.breadth(ind)
    sess = pd.Series(fx.SESSIONS)
    full = environment_vectors(ind, b, idx, sess)
    cut = fx.SESSIONS[250]
    part = environment_vectors(ind.loc[ind["trade_date"] <= cut], b.loc[b["trade_date"] <= cut],
                               idx.loc[idx["trade_date"] <= cut], sess[sess <= cut])
    cols = ENV_FEATURES
    a = full.loc[full["trade_date"] <= cut, cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, part[cols].reset_index(drop=True))
    # forward returns are outcomes (future) and are only ever read for analog dates >= 60 sessions back
    assert full["fwd_midsml400_60d_pct"].iloc[-1:].isna().all()


def test_analog_summary_flags_disagreement():
    rows = [{"fwd_midsml400_20d_pct": v} for v in (3, -2, 1, -4, 2, -1, 5, -3, 1, -2)]
    s = analog_summary(rows)
    assert s["n"] == 10 and s["agreement"] is False and s["warning"]
    assert analog_summary([{"fwd_midsml400_20d_pct": v} for v in range(1, 11)])["agreement"] is True


def test_stock_analogs_nearest_same_queue_with_distribution():
    rng = np.random.default_rng(3)
    pool = pd.DataFrame({"queue": "vcp", "symbol": [f"S{i}" for i in range(60)],
                         "signal_date": pd.bdate_range("2024-01-01", periods=60),
                         "base_depth_pct": rng.uniform(5, 30, 60), "rs_percentile": rng.uniform(40, 99, 60),
                         "rvol": rng.uniform(0.5, 2, 60), "group_quadrant_ord": rng.integers(0, 4, 60).astype(float),
                         "environment_ord": rng.integers(0, 5, 60).astype(float),
                         "r_multiple": rng.normal(0.2, 1, 60), "hit_2r": rng.uniform(0, 1, 60) > 0.7, "days_held": 10})
    query = pool.iloc[5].to_dict()
    near, dist = stock_analogs(pool, query, k=30)
    assert len(near) == 30 and dist["n"] == 30 and not dist["insufficient_sample"]
    assert near.iloc[0]["symbol"] == "S5" and near.iloc[0]["distance"] == pytest.approx(0.0)
    near, dist = stock_analogs(pool.head(10), query, k=30)
    assert dist["n"] == 10 and dist["insufficient_sample"] and dist["avg_r"] is None


def test_analogs_are_distinct_episodes():
    out = market_analogs(_env(), query_dates=[_env()["trade_date"].iloc[250]])
    pos = pd.Series(np.arange(300), index=_env()["trade_date"])
    p = np.sort(pos.reindex(out["analog_date"]).to_numpy())
    assert len(p) == 10 and np.diff(p).min() >= 10
