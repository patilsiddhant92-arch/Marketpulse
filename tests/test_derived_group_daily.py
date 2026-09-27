"""group_daily: returns, floors, excess, RRG, rank, breadth, flow, deals (synthetic)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from Scripts.derived.group_daily import OUTPUT_COLUMNS, build_group_daily

N = 120
D = pd.bdate_range("2025-01-01", periods=N)


def stock(sym, daily_ret, turnover=10.0, deliv=None):
    c = 100 * np.cumprod(np.full(N, 1 + daily_ret))
    cs = pd.Series(c)
    return pd.DataFrame({
        "symbol": sym, "trade_date": D, "close_price": c, "high_price": c, "low_price": c,
        "turnover_cr": turnover, "ema_50": cs.ewm(span=50, adjust=False).mean().to_numpy(),
        "ema_200": cs.ewm(span=200, adjust=False).mean().to_numpy(), "trend_template_pass": daily_ret > 0,
        "delivery_qty": 1000.0 if deliv is None else deliv, "delivery_pct": 60.0, "avg_delivery_pct_20d": 50.0,
    })


def universe():
    ind = pd.concat([
        stock("UP1", 0.004, turnover=30), stock("UP2", 0.002, turnover=10), stock("UP3", 0.003, turnover=10),
        stock("DN1", -0.001, turnover=20), stock("DN2", -0.002, turnover=20), stock("DN3", -0.003, turnover=10),
        stock("TOTAL", 0.05),
    ], ignore_index=True)
    master = pd.DataFrame({
        "symbol": ["UP1", "UP2", "UP3", "DN1", "DN2", "DN3", "TOTAL"],
        "broad_sector": ["BS"] * 6 + ["X"], "sector": ["S1"] * 3 + ["S2"] * 3 + ["X"],
        "broad_industry": ["BI1"] * 3 + ["BI2"] * 3 + ["X"], "industry": ["UpInd"] * 3 + ["DnInd"] * 3 + ["X"],
        "market_cap_cr": [5000.0, 500.0, 2000.0, 3000.0, 800.0, 1500.0, 4.7e7],
        "market_cap_date": [D[-1]] * 7,
    })
    idx = pd.DataFrame({"trade_date": D, "index_name": "NIFTY MIDSML 400", "close_price": 1000.0 * 1.001 ** np.arange(N)})
    idx2 = idx.assign(index_name="Nifty 50", close_price=2000.0)
    return ind, master, pd.concat([idx, idx2], ignore_index=True)


def test_columns_levels_floors_and_total_excluded():
    ind, master, idx = universe()
    out = build_group_daily(ind, master, idx)
    assert list(out.columns) == OUTPUT_COLUMNS
    assert set(out["level"]) == {"Broad Sector", "Sector", "Broad Industry", "Industry"}
    assert set(out["floor"]) == {"all", "1000cr", "watch"}
    assert "X" not in set(out["group_name"])
    last = out[(out.trade_date == D[-1]) & (out.level == "Industry")].set_index(["floor", "group_name"])
    assert last.loc[("all", "UpInd"), "members"] == 3
    assert last.loc[("1000cr", "UpInd"), "members"] == 2  # UP2 (500 Cr) below floor
    # watch band = ₹300–1,000 Cr (same as the API): UP2 (500) in UpInd, DN2 (800) in DnInd.
    assert last.loc[("watch", "UpInd"), "members"] == 1 and last.loc[("watch", "DnInd"), "members"] == 1
    assert pd.isna(last.loc[("watch", "UpInd"), "rank"])  # < 3 members: listed, not ranked
    assert (last["mcap_basis"] == "price_scaled_current").all()


def test_equal_and_cap_weighted_returns():
    ind, master, idx = universe()
    out = build_group_daily(ind, master, idx)
    row = out[(out.trade_date == D[-1]) & (out.level == "Industry") & (out.floor == "all") & (out.group_name == "UpInd")].iloc[0]
    rets = {s: (1 + r) ** 5 - 1 for s, r in {"UP1": 0.004, "UP2": 0.002, "UP3": 0.003}.items()}
    assert row["ret_ew_5d"] == pytest.approx(np.mean(list(rets.values())) * 100)
    # cap weights at start of window = mcap_t * c_{t-5}/c_t
    caps = {"UP1": 5000.0, "UP2": 500.0, "UP3": 2000.0}
    w = {s: caps[s] / (1 + rets[s]) for s in caps}
    cw = sum(w[s] * rets[s] for s in caps) / sum(w.values())
    assert row["ret_cw_5d"] == pytest.approx(cw * 100)
    ms21 = 1.001 ** 21 - 1
    assert row["excess_midsml_21d"] == pytest.approx(row["ret_ew_21d"] - ms21 * 100)
    assert row["excess_nifty_21d"] == pytest.approx(row["ret_ew_21d"])  # flat Nifty
    assert np.isnan(out[(out.trade_date == D[10]) & (out.group_name == "UpInd")]["ret_ew_21d"]).all()


def test_rank_rrg_breadth_and_flow():
    ind, master, idx = universe()
    out = build_group_daily(ind, master, idx)
    last = out[(out.trade_date == D[-1]) & (out.level == "Industry") & (out.floor == "all")].set_index("group_name")
    assert last.loc["UpInd", "rank"] == 1 and last.loc["DnInd", "rank"] == 2 and last.loc["UpInd", "rank_n"] == 2
    assert last.loc["UpInd", "rank_chg_5d"] == 0
    assert last.loc["UpInd", "pct_trend_template"] == 100 and last.loc["DnInd", "pct_trend_template"] == 0
    assert last.loc["UpInd", "pct_above_50ema"] == 100
    assert last["turnover_share_pct"].sum() == pytest.approx(100.0)
    assert last.loc["UpInd", "turnover_share_pct"] == pytest.approx(50.0)
    assert last.loc["UpInd", "top1_turnover_share_pct"] == pytest.approx(60.0)
    assert bool(last.loc["UpInd", "concentration_flag"]) is True
    assert last.loc["UpInd", "deliv_acc_10d_pct"] == pytest.approx(100.0)
    assert last.loc["DnInd", "deliv_acc_10d_pct"] == pytest.approx(-100.0)
    assert last.loc["UpInd", "acc_day_members_pct"] == 100
    # Self-normalised RS trend: the up group's relative line rises, the down group's falls.
    assert last.loc["UpInd", "rs_ratio_self"] > 100 and last.loc["DnInd", "rs_ratio_self"] < 100
    # Only 2 groups: < PEER_MIN peers, so the peer-relative RRG stays NULL (never defaulted).
    assert last["rs_ratio"].isna().all() and last["rrg_quadrant"].isna().all()
    assert last.loc["UpInd", "abs_trend"] == "Up" and last.loc["DnInd", "abs_trend"] == "Down"
    assert last["health"].isna().all()  # needs the relative leg
    early = out[(out.trade_date == D[20]) & (out.group_name == "UpInd")]
    assert early["rs_ratio_self"].isna().all()  # EMA50 not yet formed


def falling_market():
    """Six 3-member industries in a falling market (benchmark -0.5 %/day); every group falls, g5 least and accelerating."""
    frames, rows = [], []
    for k in range(6):
        base = -0.004 + 0.0006 * k
        for j in range(3):
            r = np.full(N, base + 0.0001 * j)
            r[-30:] += 0.0001 * k
            c = 100 * np.cumprod(1 + r)
            cs = pd.Series(c)
            sym = f"G{k}S{j}"
            frames.append(pd.DataFrame({
                "symbol": sym, "trade_date": D, "close_price": c, "high_price": c, "low_price": c, "turnover_cr": 10.0 + k,
                "ema_50": cs.ewm(span=50, adjust=False).mean().to_numpy(), "ema_200": cs.ewm(span=200, adjust=False).mean().to_numpy(),
                "trend_template_pass": False, "delivery_qty": 1000.0, "delivery_pct": 50.0, "avg_delivery_pct_20d": 50.0}))
            rows.append({"symbol": sym, "broad_sector": "BS", "sector": f"S{k % 2}", "broad_industry": f"BI{k % 3}",
                         "industry": f"g{k}", "market_cap_cr": 5000.0, "market_cap_date": D[-1]})
    idx = pd.DataFrame({"trade_date": D, "index_name": "NIFTY MIDSML 400", "close_price": 1000.0 * 0.995 ** np.arange(N)})
    return pd.concat(frames, ignore_index=True), pd.DataFrame(rows), idx


def test_peer_relative_rrg_health_and_notes_in_a_falling_market():
    ind, master, idx = falling_market()
    out = build_group_daily(ind, master, idx)
    last = out[(out.trade_date == D[-1]) & (out.level == "Industry") & (out.floor == "all")].set_index("group_name")
    # Every group beats the falling benchmark, so the old self-normalised ratio is > 100 for all of them ...
    assert (last["rs_ratio_self"] > 100).all()
    # ... but the peer-relative RS-Ratio is a cross-sectional z-score: mean 100, sd 10, about half above 100.
    assert last["rs_ratio"].mean() == pytest.approx(100.0, abs=1e-9)
    assert last["rs_ratio"].std() == pytest.approx(10.0, abs=1e-9)
    assert (last["rs_ratio"] > 100).sum() == 3
    assert list(last["rs_ratio"].sort_values().index) == list(last["rs_ratio_self"].sort_values().index)
    assert last.loc["g5", "rrg_quadrant"] == "Leading" and last.loc["g0", "rrg_quadrant"] == "Lagging"
    # Leading vs peers but falling in absolute terms: flagged, absolute trend Down.
    assert last.loc["g5", "ret_ew_21d"] < 0
    assert last.loc["g5", "quadrant_note"] == "Leading but falling"
    assert (last["abs_trend"] == "Down").all()
    assert last["health"].between(0, 100).all()
    assert last.loc["g5", "health_rank"] == 1 and last["health"].idxmax() == "g5"
    assert last["health"].max() < 60  # a falling market cannot score as healthy
    assert last.loc["g5", "ew_index"] < 100 and last.loc["g5", "ew_index_ema50"] > last.loc["g5", "ew_index"]


def test_deal_net_10_sessions_null_before_coverage():
    ind, master, idx = universe()
    deals = pd.DataFrame([
        dict(trade_date=D[100], symbol="UP1", client_name="F", side="BUY", quantity=100_000, price=100.0, clientele="FII"),
        dict(trade_date=D[112], symbol="UP3", client_name="G", side="SELL", quantity=50_000, price=100.0, clientele="DII"),
        dict(trade_date=D[112], symbol="UP3", client_name="H", side="BUY", quantity=999_999, price=100.0, clientele="PROP"),
    ])
    out = build_group_daily(ind, master, idx, deals=deals)
    s = out[(out.level == "Industry") & (out.floor == "all") & (out.group_name == "UpInd")].set_index("trade_date")
    assert s.loc[D[105], "deal_net_10s_cr"] != s.loc[D[105], "deal_net_10s_cr"]  # NaN: window starts before D100
    assert s.loc[D[109], "deal_net_10s_cr"] == pytest.approx(1.0)
    assert s.loc[D[112], "deal_net_10s_cr"] == pytest.approx(-0.5)  # D100 out of window, PROP excluded
    no_deals = build_group_daily(ind, master, idx)
    assert no_deals["deal_net_10s_cr"].isna().all()


def test_reference_mcap_basis_and_floor():
    ind, master, idx = universe()
    ref = pd.DataFrame({"symbol": ["UP2"], "effective_date": [D[-3]], "market_cap_cr": [1200.0]})
    out = build_group_daily(ind, master, idx, reference=ref)
    last = out[(out.trade_date == D[-1]) & (out.level == "Industry") & (out.floor == "1000cr")].set_index("group_name")
    assert last.loc["UpInd", "members"] == 3  # UP2 now 1,200 Cr as of reference
    early = out[(out.trade_date == D[50]) & (out.level == "Industry") & (out.floor == "1000cr")].set_index("group_name")
    assert early.loc["UpInd", "members"] == 2  # reference not valid before its effective date


def test_point_in_time_truncation_invariance():
    ind, master, idx = universe()
    full = build_group_daily(ind, master, idx)
    cut = D[90]
    part = build_group_daily(ind[ind.trade_date <= cut], master, idx[idx.trade_date <= cut])
    # mcap basis is anchored on master's market_cap_date (D[-1], after the cut): compare mcap-free columns.
    cols = [c for c in OUTPUT_COLUMNS if not c.startswith(("mcap", "ret_cw", "excess_cw"))]
    a = full[(full.trade_date <= cut) & (full.floor == "all")][cols].sort_values(["level", "group_name", "trade_date"]).reset_index(drop=True)
    b = part[part.floor == "all"][cols].sort_values(["level", "group_name", "trade_date"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_dtype=False)


def test_unadjusted_split_excluded_like_live_api():
    # UP1 halves overnight on D[-10] (unadjusted 1:1 bonus): windows containing that day are excluded, as
    # App/services/groups.py does, so the group return is not dragged down by a fake -50 %.
    ind, master, idx = universe()
    m = (ind.symbol == "UP1") & (ind.trade_date >= D[-10])
    ind.loc[m, ["close_price", "high_price", "low_price"]] /= 2.0
    out = build_group_daily(ind, master, idx)
    row = out[(out.trade_date == D[-1]) & (out.level == "Industry") & (out.floor == "all") & (out.group_name == "UpInd")].iloc[0]
    expected = np.mean([(1.002 ** 21 - 1) * 100, (1.003 ** 21 - 1) * 100])  # UP2, UP3 only
    assert row["ret_ew_21d"] == pytest.approx(expected)
    from App.services import groups as live
    from Scripts.derived import group_daily as gd
    assert (live.SPLIT_DOWN, live.SPLIT_UP) == (gd.SPLIT_DOWN, gd.SPLIT_UP)


def test_api_reads_the_builder_column_names():
    # Every field the API reads from group_daily / deal_session_net resolves to its first (SCHEMA.md) name.
    from App.services import deals, groups
    from Scripts.derived import deal_session_net as dsn

    assert [k for k, v in groups._GD_FIELDS.items() if v[0] not in OUTPUT_COLUMNS] == []
    assert [k for k, v in deals._DSN_FIELDS.items() if v[0] not in dsn.OUTPUT_COLUMNS] == []
    assert set(groups._gd_floor_values("watch")) & {"watch"} and "1000cr" in groups._gd_floor_values("1000")
