"""regime_daily: pillars, verdict rules, point-in-time, NULL semantics (synthetic frames)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from Scripts.derived import regime as R
from Scripts.derived._common import new_high_low_flags, prep_indicators


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2023-01-02", periods=n)


def make_index(dates, name, closes, turnover=None):
    turnover = turnover if turnover is not None else np.full(len(dates), 1000.0)
    return pd.DataFrame({"trade_date": dates, "index_name": name, "close_price": closes,
                         "turnover_cr": turnover, "volume": np.nan})


def make_market(n_days=320, n_sym=30, drift=0.001, seed=0):
    rng = np.random.default_rng(seed)
    dates = _dates(n_days)
    rows = []
    for s in range(n_sym):
        c = 100 * np.cumprod(1 + drift + rng.normal(0, 0.01, n_days))
        h = c * 1.01
        lo = c * 0.99
        cs = pd.Series(c)
        rows.append(pd.DataFrame({
            "symbol": f"S{s:02d}", "trade_date": dates, "close_price": c, "high_price": h, "low_price": lo,
            "prev_close": cs.shift(1).to_numpy(),
            "ema_10": cs.ewm(span=10, adjust=False).mean().to_numpy(),
            "ema_50": cs.ewm(span=50, adjust=False).mean().to_numpy(),
            "ema_200": cs.ewm(span=200, adjust=False).mean().to_numpy(),
            "high_20d": pd.Series(h).rolling(20, min_periods=1).max().to_numpy(),
            "rvol": rng.uniform(0.5, 2.5, n_days),
            "trend_template_pass": rng.uniform(size=n_days) > 0.5,
        }))
    ind = pd.concat(rows, ignore_index=True)
    idx_close = 1000 * np.cumprod(1 + drift + rng.normal(0, 0.005, n_days))
    index_daily = pd.concat([
        make_index(dates, "NIFTY MIDSML 400", idx_close, rng.uniform(900, 1100, n_days)),
        make_index(dates, "Nifty 50", idx_close * 2, rng.uniform(900, 1100, n_days)),
        make_index(dates, "India VIX", np.full(n_days, 14.0) + rng.normal(0, 0.3, n_days)),
    ], ignore_index=True)
    return ind, index_daily


def test_one_row_per_session_and_columns():
    ind, idx = make_market()
    out = R.build_regime_daily(idx, ind)
    assert list(out.columns) == R.OUTPUT_COLUMNS
    assert len(out) == ind["trade_date"].nunique()
    assert out["trade_date"].is_monotonic_increasing


def test_point_in_time_truncation_invariance():
    ind, idx = make_market(n_days=300, n_sym=80)  # >= 30 breakouts so every pillar is known
    full = R.build_regime_daily(idx, ind)
    assert full["verdict"].iloc[270:].notna().all()
    cut = full["trade_date"].iloc[280]
    part = R.build_regime_daily(idx[idx.trade_date <= cut], ind[ind.trade_date <= cut])
    a = full[full.trade_date <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, part.reset_index(drop=True), check_dtype=False)


def test_missing_index_data_gives_null_not_default():
    ind, idx = make_market(n_days=260)
    out = R.build_regime_daily(idx.iloc[0:0], ind)
    assert out["trend_status"].isna().all()
    assert out["stress_status"].isna().all()
    assert out["verdict"].isna().all()
    assert (out["rule_id"] == "R0").all()


def test_early_rows_have_null_trend_until_200_sessions():
    ind, idx = make_market(n_days=260)
    out = R.build_regime_daily(idx, ind)
    assert out["trend_status"].iloc[:199].isna().all()
    assert out["trend_status"].iloc[-1] in R.STATUSES


def test_trend_zones():
    d = pd.DataFrame({
        "midsml_close": [90.0, 110.0, 105.0], "midsml_ema50": [100.0, 100.0, 100.0],
        "midsml_ema200": [95.0, 95.0, 95.0], "midsml_ema50_slope_pct": [0.5, 0.5, -0.2],
        "nifty_close": [10.0, 10.0, 10.0], "nifty_ema200": [9.0, 9.0, 9.0],
    })
    for c in ("above_50ema_pct", "above_200ema_pct", "advancers", "decliners", "new_highs", "new_lows",
              "breakouts_n", "breakouts_holding", "distribution_days_25", "vix_close", "vix_1d_pct", "vix_5d_pct"):
        d[c] = np.nan
    out = R._pillars(d)
    assert list(out["trend_status"]) == ["Weak", "Healthy", "Neutral"]


def test_participation_direction_overrides_one_step():
    n = 20
    d = pd.DataFrame({"above_50ema_pct": np.linspace(50, 58, n), "above_200ema_pct": np.full(n, 52.0),
                      "advancers": np.full(n, 60.0), "decliners": np.full(n, 40.0)})
    for c in ("midsml_close", "midsml_ema50", "midsml_ema200", "midsml_ema50_slope_pct", "nifty_close", "nifty_ema200",
              "new_highs", "new_lows", "breakouts_n", "breakouts_holding", "distribution_days_25", "vix_close",
              "vix_1d_pct", "vix_5d_pct"):
        d[c] = np.nan
    out = R._pillars(d)
    # level ~51-55 (Neutral) but A/D positive and %>50 rising -> Healthy
    assert out["participation_status"].iloc[-1] == "Healthy"
    assert out["participation_status"].iloc[:9].isna().all()  # 10-day A/D not yet available


def test_follow_through_counts_breakouts_t10_to_t3():
    dates = _dates(40)
    rows = []
    for s in range(40):
        c = np.full(40, 100.0)
        c[25] = 110.0  # breakout on day 25 with rvol 2
        c[26:] = 111.0 if s < 30 else 105.0  # 30 of 40 hold above 110
        rv = np.ones(40)
        rv[25] = 2.0
        cs = pd.Series(c)
        rows.append(pd.DataFrame({"symbol": f"X{s}", "trade_date": dates, "close_price": c, "high_price": c,
                                  "low_price": c, "rvol": rv, "high_20d": cs.rolling(20, min_periods=1).max()}))
    ind = pd.concat(rows, ignore_index=True)
    out = R.build_regime_daily(pd.DataFrame(), ind).set_index("trade_date")
    t = dates[25 + 5]  # breakout is t-5, inside t-10..t-3
    assert out.loc[t, "breakouts_n"] == 40
    assert out.loc[t, "breakouts_holding"] == 30
    assert out.loc[t, "follow_through_pct"] == pytest.approx(75.0)
    assert out.loc[t, "follow_through_status"] == "Healthy"
    assert out.loc[dates[25 + 2], "breakouts_n"] == 0  # t-2 is outside the window
    assert pd.isna(out.loc[dates[25 + 2], "follow_through_pct"])  # < 30 breakouts -> NULL
    assert out.loc[dates[25 + 11], "breakouts_n"] == 0


def test_distribution_days_need_drop_and_higher_turnover():
    dates = _dates(40)
    close = np.full(40, 1000.0)
    turnover = np.full(40, 100.0)
    for i in (30, 32, 34, 36, 38):  # five -0.5% days on higher turnover
        close[i:] = close[i - 1] * 0.995
        turnover[i] = 200.0
    close[39] = close[38] * 0.99  # a drop on LOWER turnover (not a distribution day)
    turnover[39] = 150.0
    idx = pd.concat([make_index(dates, "NIFTY MIDSML 400", close, turnover),
                     make_index(dates, "India VIX", np.full(40, 14.0))])
    ind = pd.DataFrame({"symbol": "A", "trade_date": dates, "close_price": 1.0, "high_price": 1.0, "low_price": 1.0})
    out = R.build_regime_daily(idx, ind).set_index("trade_date")
    assert out["distribution_days_25"].iloc[:24].isna().all()
    assert out.loc[dates[38], "distribution_days_25"] == 5
    assert out.loc[dates[39], "distribution_days_25"] == 5
    assert out.loc[dates[38], "stress_status"] == "Weak"
    assert bool(out.loc[dates[38], "alert_distribution_5"]) is True
    assert bool(out.loc[dates[39], "alert_distribution_5"]) is False
    assert out.loc[dates[38], "distribution_source"] == "index turnover_cr"


def _status_frame(rows):
    d = pd.DataFrame(rows)
    verdict, rule_id, _ = R._match_rules(d)
    return pd.DataFrame({"verdict": verdict, "rule_id": rule_id})


def test_verdict_rules_first_match_and_insufficient():
    base = dict(trend_status="Healthy", participation_status="Neutral", leadership_status="Neutral",
                follow_through_status="Healthy", stress_status="Neutral")
    cases = [
        (base, "Favourable", "R6"),
        ({**base, "follow_through_status": "Neutral"}, "Constructive", "R7"),
        ({**base, "trend_status": "Weak", "stress_status": "Weak"}, "Danger", "R1"),
        ({**base, "trend_status": "Weak"}, "Weak", "R3"),
        ({**base, "trend_status": "Neutral"}, "Mixed", "R9"),
        ({**base, "trend_status": "Neutral", "participation_status": "Healthy"}, "Constructive", "R8"),
        ({**base, "participation_status": "Weak", "follow_through_status": "Weak"}, "Weak", "R4"),
        ({**base, "trend_status": None}, None, "R0"),
        ({**base, "leadership_status": None, "stress_status": None}, None, "R0"),
        # Favourable needs Leadership known: a NULL pillar never satisfies a condition -> R7.
        ({**base, "leadership_status": None}, "Constructive", "R7"),
    ]
    out = _status_frame([c[0] for c in cases])
    for i, (_, verdict, rule) in enumerate(cases):
        got = out["verdict"].iloc[i]
        assert (pd.isna(got) if verdict is None else got == verdict), i
        assert out["rule_id"].iloc[i] == rule, i


def test_rules_are_published_as_data():
    t = R.verdict_rules_table()
    assert t["rule_id"].tolist()[0] == "R0"
    assert set(t["verdict"].dropna()) == set(R.VERDICTS)
    assert all(isinstance(json.loads(c), dict) for c in t["conditions"])


def test_verdict_evidence_flag_rides_with_every_verdict():
    """§6.1.5: the study found no out-of-sample separation, so every row with a verdict carries the
    descriptive-only flag and note (NULL where the verdict is NULL); rules stay unchanged."""
    ind, idx = make_market()
    out = R.build_regime_daily(idx, ind)
    has = out["verdict"].notna()
    assert has.any() and (~has).any()
    assert (out.loc[has, "verdict_evidence"] == "descriptive_only").all()
    assert (out.loc[has, "verdict_evidence_note"] == R.VERDICT_EVIDENCE["note"]).all()
    assert out.loc[~has, ["verdict_evidence", "verdict_evidence_note"]].isna().all().all()
    assert "not as a trade filter" in R.VERDICT_EVIDENCE["note"]


def test_days_in_state_previous_state_and_change():
    seq = ["Weak", "Weak", "Mixed", "Mixed", "Mixed", "Constructive"]
    st = {"Weak": dict(trend_status="Weak", participation_status="Neutral", leadership_status="Neutral",
                       follow_through_status="Neutral", stress_status="Neutral"),
          "Mixed": dict(trend_status="Neutral", participation_status="Neutral", leadership_status="Neutral",
                        follow_through_status="Neutral", stress_status="Neutral"),
          "Constructive": dict(trend_status="Healthy", participation_status="Neutral", leadership_status="Neutral",
                               follow_through_status="Neutral", stress_status="Neutral")}
    d = pd.DataFrame([st[s] for s in seq], index=_dates(len(seq)))
    out = R._verdict(d)
    assert list(out["raw_verdict"]) == seq
    # Mixed confirmed on its 2nd session (index 3); Constructive (1 session) is still pending
    assert list(out["verdict"]) == ["Weak", "Weak", "Weak", "Mixed", "Mixed", "Mixed"]
    assert list(out["days_in_state"]) == [1, 2, 3, 1, 2, 3]
    assert out["previous_state"].iloc[3] == "Weak"
    assert out["state_change"].iloc[3] == "improved"
    assert out["state_since"].iloc[4] == _dates(6)[3]
    assert out["candidate_verdict"].iloc[5] == "Constructive" and out["rule_id"].iloc[5] == "RH"
    assert pd.isna(out["previous_state"].iloc[0])


def test_new_high_uses_prior_session_52w_and_validity():
    dates = _dates(5)
    ind = pd.DataFrame({"symbol": "A", "trade_date": dates,
                        "high_price": [10, 11, 12, 11, 13.0], "low_price": [9, 9, 9, 8, 9.0],
                        "high_52w": [12, 12, 12, 12, 13.0], "low_52w": [8.5, 8.5, 8.5, 8.0, 8.0],
                        "high_52w_date": pd.to_datetime(["2022-12-01"] * 5)})
    f = new_high_low_flags(prep_indicators(ind, ind.columns))
    assert np.isnan(f["new_high"].iloc[0])
    assert list(f["new_high"].iloc[1:]) == [0.0, 0.0, 0.0, 1.0]
    assert list(f["new_low"].iloc[1:]) == [0.0, 0.0, 1.0, 0.0]
    ind2 = ind.drop(columns=["high_52w_date"])  # no official snapshot and < 252 sessions -> invalid
    f2 = new_high_low_flags(prep_indicators(ind2, ind2.columns))
    assert f2["new_high"].isna().all()


def test_connected_reading_and_timing_cite_values():
    ind, idx = make_market(n_days=320)
    out = R.build_regime_daily(idx, ind)
    for js in out["connected_readings"]:
        for item in json.loads(js):
            assert item["id"] in {r["id"] for r in R.CONNECTED_READINGS}
            assert any(ch.isdigit() for ch in item["text"])
    d = pd.DataFrame({"above_10ema_pct": [85.0, 15.0, 50.0, np.nan]})
    t = R._timing(d)
    assert list(t["timing_state"].iloc[:3]) == ["stretched", "washed_out", "normal"]
    assert pd.isna(t["timing_state"].iloc[3])
    assert "85%" in t["timing_note"].iloc[0]
    assert pd.isna(t["timing_note"].iloc[2])


def test_vix_spike_alert_and_stress_weak():
    dates = _dates(30)
    vix = np.full(30, 15.0)
    vix[29] = 18.75  # +25% to >= 18
    idx = pd.concat([make_index(dates, "India VIX", vix), make_index(dates, "NIFTY MIDSML 400", np.full(30, 100.0))])
    ind = pd.DataFrame({"symbol": "A", "trade_date": dates, "close_price": 1.0, "high_price": 1.0, "low_price": 1.0})
    out = R.build_regime_daily(idx, ind)
    last = out.iloc[-1]
    assert bool(last["alert_vix_spike"]) and last["stress_status"] == "Weak"
    assert any(a["id"] == "vix_spike" for a in json.loads(last["alerts"]))


def test_breadth_frame_takes_precedence_when_given():
    ind, idx = make_market(n_days=60)
    dates = sorted(ind.trade_date.unique())
    breadth = pd.DataFrame({"trade_date": dates, "above_50ema_pct": 77.0, "above_200ema_pct": 66.0,
                            "above_10ema_pct": 55.0, "advancers": 10.0, "decliners": 5.0})
    out = R.build_regime_daily(idx, ind, breadth=breadth)
    assert (out["above_50ema_pct"] == 77.0).all()
    assert (out["participation_source"] == "breadth_daily").all()


# ---------------------------------------------------------------------------------------------
# Calibration (w6): hysteresis, confirmed verdict changes, immediate Danger, VIX spike level
# ---------------------------------------------------------------------------------------------
_PILLAR_INPUTS = ("midsml_close", "midsml_ema50", "midsml_ema200", "midsml_ema50_slope_pct", "nifty_close",
                  "nifty_ema200", "above_50ema_pct", "above_200ema_pct", "advancers", "decliners", "new_highs",
                  "new_lows", "breakouts_n", "breakouts_holding", "distribution_days_25", "vix_close",
                  "vix_1d_pct", "vix_5d_pct")


def _pillar_frame(n, **cols):
    d = pd.DataFrame(index=_dates(n))
    for c in _PILLAR_INPUTS:
        d[c] = cols[c] if c in cols else np.nan
    return d


def _changes(s: pd.Series) -> int:
    s = pd.Series(s).reset_index(drop=True)
    return int((s.notna() & s.shift().notna() & (s != s.shift())).sum())


def test_participation_hysteresis_stops_single_day_flip_flop():
    # Level sits on the 40 line (39 / 41 alternating); A/D flat so the direction override stays off.
    lvl = [np.nan] * 10 + [39, 41, 39, 41, 39, 41, 39, 41, 45, 45, 41, 38, 38.5, 41, 41]
    n = len(lvl)
    d = _pillar_frame(n, above_50ema_pct=lvl, above_200ema_pct=lvl, advancers=np.full(n, 50.0),
                      decliners=np.full(n, 50.0))
    out = R._pillars(d)
    raw = out["participation_status_raw"].iloc[15:].tolist()
    sm = out["participation_status"].iloc[15:].tolist()
    # before: the unsmoothed status flips every session on the line
    # (first 5 known rows are NULL: the 5-session change in % > 50 EMA needs history)
    assert raw[:3] == ["Neutral", "Weak", "Neutral"] and _changes(out["participation_status_raw"]) == 4
    # after: held at the first known state while inside the +/-2 point band ...
    assert sm[:3] == ["Neutral"] * 3
    # ... then from index 18: 45, 45, 41, 38, 38.5, 41, 41
    assert out["participation_status"].iloc[18:].tolist() == [
        "Neutral", "Neutral",  # 45 decisive (and already Neutral)
        "Neutral", "Neutral",  # 41, then 38 once (inside the band) -> held
        "Weak",                # 38.5 = 2nd session below 40 -> Weak
        "Weak",                # 41 once -> held
        "Neutral",             # 41 again -> Neutral
    ]


def test_participation_hysteresis_margin_crossing_is_immediate():
    lvl = [np.nan] * 10 + [39.0] * 6 + [41.0, 39.0, 41.5, 42.5]
    n = len(lvl)
    d = _pillar_frame(n, above_50ema_pct=lvl, above_200ema_pct=lvl, advancers=np.full(n, 50.0),
                      decliners=np.full(n, 50.0))
    out = R._pillars(d)
    assert out["participation_status"].iloc[15:].tolist() == ["Weak", "Weak", "Weak", "Weak", "Neutral"]


def test_follow_through_hysteresis_margin():
    n = 6
    ft = [60.0, 49.0, 60.0, 49.0, 30.0, 30.0]  # 49 is only 1 pt under 50 -> held Healthy; 30 is decisive
    d = _pillar_frame(n, breakouts_n=np.full(n, 100.0), breakouts_holding=ft)
    out = R._pillars(d)
    assert out["follow_through_status_raw"].tolist() == ["Healthy", "Neutral", "Healthy", "Neutral", "Weak", "Weak"]
    assert out["follow_through_status"].tolist() == ["Healthy", "Healthy", "Healthy", "Healthy", "Weak", "Weak"]


def test_follow_through_requires_minimum_breakouts():
    n = 3
    d = _pillar_frame(n, breakouts_n=[9.0, 29.0, 30.0], breakouts_holding=[5.0, 20.0, 20.0])
    out = R._pillars(d)
    assert R.ZONES["follow_through"]["min_breakouts"] == 30
    assert out["follow_through_pct"].iloc[:2].isna().all()
    assert out["follow_through_status"].iloc[:2].isna().all()
    assert out["follow_through_pct"].iloc[2] == pytest.approx(200 / 3)


_ST = {
    "Weak": dict(trend_status="Weak", participation_status="Neutral", leadership_status="Neutral",
                 follow_through_status="Neutral", stress_status="Neutral"),
    "Mixed": dict(trend_status="Neutral", participation_status="Neutral", leadership_status="Neutral",
                  follow_through_status="Neutral", stress_status="Neutral"),
    "Constructive": dict(trend_status="Healthy", participation_status="Neutral", leadership_status="Neutral",
                         follow_through_status="Neutral", stress_status="Neutral"),
    "Danger": dict(trend_status="Weak", participation_status="Neutral", leadership_status="Neutral",
                   follow_through_status="Neutral", stress_status="Weak"),
}


def _verdict_seq(seq):
    d = pd.DataFrame([_ST[s] for s in seq], index=_dates(len(seq)))
    return R._verdict(d)


def test_verdict_needs_two_sessions_to_change():
    seq = ["Mixed", "Weak", "Mixed", "Weak", "Mixed", "Weak", "Weak", "Weak", "Mixed", "Weak"]
    out = _verdict_seq(seq)
    assert out["raw_verdict"].tolist() == seq  # before: flips every session
    assert _changes(out["raw_verdict"]) == 7
    assert out["verdict"].tolist() == ["Mixed"] * 6 + ["Weak"] * 4  # after: one confirmed change
    assert _changes(out["verdict"]) == 1
    assert out["days_in_state"].tolist() == [1, 2, 3, 4, 5, 6, 1, 2, 3, 4]
    assert out["previous_state"].iloc[6] == "Mixed" and out["state_change"].iloc[6] == "worsened"
    # held sessions say so: the pending verdict and the hold rule
    assert out["rule_id"].iloc[1] == "RH" and out["candidate_verdict"].iloc[1] == "Weak"
    assert "Weak" in out["rule_text"].iloc[1]
    assert out["rule_id"].iloc[6] == "R3"
    assert out["verdict_guidance"].iloc[1] == R.VERDICT_GUIDANCE["Mixed"]


def test_danger_is_immediate_and_leaving_it_needs_confirmation():
    seq = ["Mixed", "Mixed", "Danger", "Mixed", "Danger", "Weak", "Weak", "Weak"]
    out = _verdict_seq(seq)
    assert out["verdict"].tolist() == ["Mixed", "Mixed", "Danger", "Danger", "Danger", "Danger", "Weak", "Weak"]
    assert out["rule_id"].iloc[2] == "R1" and out["days_in_state"].iloc[2] == 1


def test_raw_danger_overrides_smoothed_pillars():
    # Smoothed pillars still say Mixed, but today's unsmoothed statuses say Danger -> Danger now.
    rows = []
    for raw_danger in (False, False, True):
        raw = _ST["Danger" if raw_danger else "Mixed"]
        rows.append({**_ST["Mixed"], **{k.replace("_status", "_status_raw"): v for k, v in raw.items()}})
    out = R._verdict(pd.DataFrame(rows, index=_dates(3)))
    assert out["verdict"].tolist() == ["Mixed", "Mixed", "Danger"]
    assert out["raw_verdict"].iloc[2] == "Danger" and out["candidate_verdict"].iloc[2] == "Mixed"
    assert out["rule_id"].iloc[2] == "R1"


def test_vix_low_level_jump_is_not_a_spike():
    dates = _dates(30)
    vix = np.full(30, 10.0)
    vix[20] = 12.7  # +27% but VIX only 12.7
    vix[21:] = 12.5
    vix[28] = 15.4  # +23% but below 18
    idx = pd.concat([make_index(dates, "India VIX", vix), make_index(dates, "NIFTY MIDSML 400", np.full(30, 100.0))])
    ind = pd.DataFrame({"symbol": "A", "trade_date": dates, "close_price": 1.0, "high_price": 1.0, "low_price": 1.0})
    out = R.build_regime_daily(idx, ind)
    assert not out["alert_vix_spike"].any()
    assert not out["vix_spike"].any()
    assert (out["stress_status"].dropna() != "Weak").all()


def test_vix_five_day_surge_with_level_is_a_spike():
    dates = _dates(30)
    vix = np.full(30, 12.0)
    vix[23:] = [13.0, 14.0, 15.0, 15.5, 16.4, 16.6, 16.8]  # 5D +37% at 16.4 (no single day >= +20%)
    idx = pd.concat([make_index(dates, "India VIX", vix), make_index(dates, "NIFTY MIDSML 400", np.full(30, 100.0))])
    ind = pd.DataFrame({"symbol": "A", "trade_date": dates, "close_price": 1.0, "high_price": 1.0, "low_price": 1.0})
    out = R.build_regime_daily(idx, ind).set_index("trade_date")
    assert bool(out.loc[dates[27], "vix_spike"]) and out.loc[dates[27], "stress_status"] == "Weak"
    assert bool(out.loc[dates[27], "alert_vix_spike"])
    assert not bool(out.loc[dates[28], "alert_vix_spike"])  # alert only on the first day of a spike
    assert not bool(out.loc[dates[26], "vix_spike"])  # 15.5 < 16


def test_end_to_end_verdict_changes_only_when_confirmed_or_danger():
    # MidSml400 and Nifty flat for 260 sessions, then alternating +/-0.3% around their 200 EMA (inside the
    # 0.5% margin): the raw Trend status flips Weak/not-Weak every session. Flat turnover -> no distribution.
    n = 320
    ind, idx = make_market(n_days=n, n_sym=80, seed=3)
    dates = sorted(ind.trade_date.unique())
    close = np.full(n, 1000.0)
    close[260:] = 1000.0 * (1 + 0.003 * np.where(np.arange(260, n) % 2 == 0, 1, -1))
    vix = idx[idx.index_name == "India VIX"]
    idx = pd.concat([make_index(dates, "NIFTY MIDSML 400", close), make_index(dates, "Nifty 50", close * 2), vix],
                    ignore_index=True)
    out = R.build_regime_daily(idx, ind)
    raw_changes, changes = _changes(out["raw_verdict"]), _changes(out["verdict"])
    assert raw_changes >= 20 and changes <= 2, (raw_changes, changes)
    v, c = out["verdict"], out["candidate_verdict"].where(out["raw_verdict"] != "Danger", "Danger")
    for t in range(1, len(out)):
        if pd.notna(v.iloc[t]) and pd.notna(v.iloc[t - 1]) and v.iloc[t] != v.iloc[t - 1] and v.iloc[t] != "Danger":
            assert c.iloc[t - 1] == v.iloc[t], t  # a non-Danger change needs 2 sessions of the new state
