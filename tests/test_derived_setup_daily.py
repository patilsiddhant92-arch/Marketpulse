"""setup_daily: queue membership reuses the desk predicates; geometry, pool, identity, incremental."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from Scripts.darvas_squeeze import classify_darvas_10ema_frame, squeeze_frame
from Scripts.derived import setup_daily as S
from Scripts.minervini_geometry import detect_contractions


def bars(sym, closes, *, rng_pct=0.6, rvol=0.8, start="2025-01-01", vol=200_000.0):
    closes = np.asarray(closes, dtype=float)
    d = pd.bdate_range(start, periods=len(closes))
    cs = pd.Series(closes)
    high = closes * (1 + rng_pct / 200)
    low = closes * (1 - rng_pct / 200)
    return pd.DataFrame({
        "symbol": sym, "trade_date": d, "open_price": closes, "high_price": high, "low_price": low,
        "close_price": closes, "volume": vol, "ema_10": cs.ewm(span=10, adjust=False).mean().to_numpy(),
        "ema_20": cs.ewm(span=20, adjust=False).mean().to_numpy(), "ema_200": np.nan,
        "rvol": rvol, "avg_volume_20d": vol, "avg_traded_value_cr_20d": 50.0, "delivery_pct": 50.0,
        "avg_delivery_pct_20d": 45.0, "rs_percentile": 80.0, "away_52w_high_pct": -3.0, "atr_pct": 2.0,
    })


def squeeze_stock(sym="SQZ", n_up=40, n_flat=15, seed=0):
    rng = np.random.default_rng(seed)
    up = 100 * 1.012 ** np.arange(n_up)
    flat = up[-1] * (1 - 0.004 + rng.normal(0, 0.0015, n_flat))
    return bars(sym, np.r_[up, flat])


def test_darvas_squeeze_matches_squeeze_frame_on_every_date():
    ind = pd.concat([squeeze_stock("A", seed=1), squeeze_stock("B", n_up=35, n_flat=20, seed=2),
                     bars("C", 100 * 0.99 ** np.arange(55))], ignore_index=True)
    out = S.build_setup_daily(ind)
    got = out[out.queue == "darvas_squeeze"]
    assert len(got) > 0, "fixture should produce squeezes"
    dates = sorted(ind.trade_date.unique())
    for t in dates[10:]:
        live = set(ind.loc[ind.trade_date == t, "symbol"])
        ref = squeeze_frame(ind[(ind.trade_date <= t) & ind.symbol.isin(live)], timeframe="D")
        want = set(ref.loc[ref["qualifies"], "symbol"])
        have = set(got.loc[got.trade_date == t, "symbol"])
        assert have == want, t
        for sym in want:
            row = got[(got.trade_date == t) & (got.symbol == sym)].iloc[0]
            r = ref[ref.symbol == sym].iloc[0]
            assert row["signal_date"] == pd.Timestamp(r["signal_date"])
            assert row["trigger_price"] == pytest.approx(r["darvas_top"])
            f = json.loads(row["features"])
            assert f["squeeze_age"] == r["squeeze_age"] and f["box_age_sessions"] == r["box_age_sessions"]


def test_squeeze_geometry_is_desk_contract():
    ind = squeeze_stock("A", seed=1)
    out = S.build_setup_daily(ind)
    row = out[out.queue == "darvas_squeeze"].iloc[-1]
    e10 = ind.set_index("trade_date").loc[row.trade_date, "ema_10"]
    assert row["stop_price"] == pytest.approx(round(e10 * 0.985, 2))
    assert row["risk_pct"] == pytest.approx((row.trigger_price - row.stop_price) / row.trigger_price * 100)
    assert row["distance_to_trigger_pct"] == pytest.approx((row.trigger_price / row.close_price - 1) * 100)


def ema_pullback_stock(sym="PB"):
    # Uptrend, then a dip that tags a rising 10 EMA, then a bounce.
    c = list(100 * 1.01 ** np.arange(40))
    c += [c[-1] * 0.985, c[-1] * 0.975, c[-1] * 0.98, c[-1] * 0.995, c[-1] * 1.01]
    return bars(sym, c, rng_pct=2.0, rvol=0.7)


def test_darvas_10ema_matches_classifier_and_geometry():
    ind = pd.concat([ema_pullback_stock("PB"), squeeze_stock("SQ", seed=3)], ignore_index=True)
    out = S.build_setup_daily(ind)
    got = out[out.queue == "darvas_10ema"]
    sq = out[out.queue == "darvas_squeeze"]
    dates = sorted(ind.trade_date.unique())
    n_checked = 0
    for t in dates[20:]:
        live = set(ind.loc[ind.trade_date == t, "symbol"])  # a row exists only for symbols trading on t
        win = ind[(ind.trade_date <= t) & ind.symbol.isin(live)].groupby("symbol").tail(S.EMA10_WINDOW)
        ref = classify_darvas_10ema_frame(win)
        excl = set(sq.loc[sq.trade_date == t, "symbol"])
        want = set(ref["symbol"]) - excl
        assert set(got.loc[got.trade_date == t, "symbol"]) == want, t
        for _, r in ref[ref.symbol.isin(want)].iterrows():
            row = got[(got.trade_date == t) & (got.symbol == r.symbol)].iloc[0]
            day = ind[(ind.symbol == r.symbol) & (ind.trade_date == t)].iloc[0]
            assert row["trigger_price"] == pytest.approx(day["high_price"])
            if r.flavor == "Catch-up":
                assert pd.isna(row["stop_price"])
            else:
                span = ind[(ind.symbol == r.symbol) & (ind.trade_date >= pd.Timestamp(r.signal_date)) & (ind.trade_date <= t)]
                assert row["stop_price"] == pytest.approx(span["low_price"].min())
            assert json.loads(row["features"])["flavor"] == r.flavor
            n_checked += 1
    assert n_checked > 0


def vcp_stock(sym="VCP"):
    seg = lambda a, b, n: list(np.linspace(a, b, n)[1:])  # noqa: E731
    c = [70.0] + seg(70, 60, 6) + seg(60, 100, 30)  # dip, then +66% advance
    c += seg(100, 85, 10) + seg(85, 98, 10)  # T1 ~15%
    c += seg(98, 90, 8) + seg(90, 97, 8)     # T2 ~8%
    c += seg(97, 93, 6) + seg(93, 96, 6)     # T3 ~4%
    c += seg(96, 95, 3)
    return bars(sym, c, rng_pct=1.0)


def test_vcp_uses_detect_contractions_geometry():
    ind = vcp_stock()
    out = S.build_setup_daily(ind)
    got = out[out.queue == "vcp"]
    assert len(got) > 0
    last = got.iloc[-1]
    win = ind[ind.trade_date <= last.trade_date].tail(S.VCP_WINDOW).reset_index(drop=True)
    seq = detect_contractions(win)
    assert last["trigger_price"] == pytest.approx(seq.pivot)
    assert last["stop_price"] == pytest.approx(seq.stop)
    f = json.loads(last["features"])
    assert f["n_contractions"] == len(seq.contractions) >= 2
    assert f["vdu_ratio"] == pytest.approx(1.0)  # flat synthetic volume


def test_vdu_ratio_matches_analyze_manas_vcp():
    from Scripts.vcp import analyze_manas_vcp
    ind = vcp_stock()
    ind["volume"] = np.linspace(300_000, 100_000, len(ind))
    out = S.build_setup_daily(ind)
    last = out[out.queue == "vcp"].iloc[-1]
    h = ind[ind.trade_date <= last.trade_date]
    ref = analyze_manas_vcp(h.high_price.to_numpy(), h.low_price.to_numpy(), h.close_price.to_numpy(), h.volume.to_numpy())
    assert json.loads(last["features"])["vdu_ratio"] == pytest.approx(ref["vdu_ratio"])


def test_pool_gates():
    ind = pd.concat([squeeze_stock("BIG", seed=1), squeeze_stock("SMALL", seed=1), squeeze_stock("GSM", seed=1),
                     squeeze_stock("WEAK", seed=1)], ignore_index=True)
    ind.loc[ind.symbol == "GSM", "band_remarks"] = "GSM Stage I"
    ind.loc[ind.symbol == "WEAK", "ema_200"] = 1e6  # close below 200 EMA
    last = ind.trade_date.max()
    master = pd.DataFrame({"symbol": ["BIG", "SMALL", "GSM", "WEAK"], "market_cap_cr": [5000.0, 500.0, 5000.0, 5000.0],
                           "market_cap_date": [last] * 4, "band": [20.0] * 4})
    out = S.build_setup_daily(ind, master=master)
    syms = set(out["symbol"])
    assert "BIG" in syms and not ({"SMALL", "GSM", "WEAK"} & syms)
    assert (out["mcap_basis"] == "price_scaled_current").all()


def test_identity_resets_after_five_absent_sessions():
    cal = pd.bdate_range("2025-01-01", periods=30)
    present = [0, 1, 2, 5, 6, 12, 13]  # gap of 2 (returning), then gap of 5 (new identity)
    df = pd.DataFrame({"queue": "vcp", "symbol": "X", "trade_date": cal[present]})
    out = S._identity(df, cal)
    assert list(out["status"]) == ["new", "active", "active", "returning", "active", "new", "active"]
    assert out["first_seen"].iloc[4] == cal[0] and out["setup_age_sessions"].iloc[4] == 7
    assert out["first_seen"].iloc[5] == cal[12]
    assert out["setup_id"].iloc[6] == "vcp:X:" + cal[12].strftime("%Y%m%d")


def test_incremental_equals_full_rebuild():
    ind = pd.concat([squeeze_stock("A", seed=1), ema_pullback_stock("PB"), vcp_stock("V")], ignore_index=True)
    full = S.build_setup_daily(ind)
    since = sorted(ind.trade_date.unique())[-8]
    inc = S.build_setup_daily(ind, since=since, previous=full[full.trade_date < since])
    pd.testing.assert_frame_equal(full.reset_index(drop=True), inc.reset_index(drop=True), check_dtype=False)
    only_new = S.build_setup_daily(ind, since=since)
    assert only_new["trade_date"].min() >= since


def test_empty_and_schema():
    out = S.build_setup_daily(pd.DataFrame(columns=["symbol", "trade_date"]))
    assert list(out.columns) == S.OUTPUT_COLUMNS and out.empty
