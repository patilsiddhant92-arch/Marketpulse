"""Restored Deals desk rules (App/services/deals.py): window tiers, catalyst score, fund tiers."""
from __future__ import annotations

from App.services.deals import catalyst_score, desk_tier, fund_tier


def _row(**kw):
    base = {"circuit_band": 20.0, "deal_days": 1, "transfer_days": 0, "churn_days": 0, "flow_net_cr": 1.0,
            "flow_buy_cr": 1.0, "net_vs_adv": 0.01, "repeat_house": False, "net_buy_days": 1, "n_buy_houses": 1}
    base.update(kw)
    return base


def test_desk_tiers_mutually_exclusive_and_corrected():
    assert desk_tier(_row(circuit_band=5.0)) == ("quarantined", None)
    assert desk_tier(_row(transfer_days=1)) == ("transfer", "Transfer")        # only transfer sessions
    assert desk_tier(_row(churn_days=1)) == ("churn", None)                    # only PROP / round-trip sessions
    assert desk_tier(_row()) == ("fresh", "Single")
    assert desk_tier(_row(net_buy_days=2, deal_days=2)) == ("conviction", "Repeat")
    assert desk_tier(_row(repeat_house=True)) == ("conviction", "Repeat")
    assert desk_tier(_row(n_buy_houses=2)) == ("conviction", "Cluster")
    assert desk_tier(_row(flow_net_cr=20.0)) == ("conviction", "Size")
    assert desk_tier(_row(net_vs_adv=0.5)) == ("conviction", "Size")
    # Old desk put any stock with buy value > 0 in Play; a net seller is distribution now.
    assert desk_tier(_row(flow_net_cr=-3.0, flow_buy_cr=40.0)) == ("distribution", None)
    # NULL circuit band is not quarantined (unknown is not a 5 % band).
    assert desk_tier(_row(circuit_band=None))[0] == "fresh"


def test_catalyst_score_matches_old_formula():
    # 40 % win + 30 % runup/50 + 15 % (ret20+10)/30 + 15 % velocity(100 - 2*dtp)
    assert catalyst_score(100.0, 50.0, 20.0, 5.0) == 98.5  # velocity caps at 90 for a 5-session peak
    assert catalyst_score(50.0, 10.0, 0.0, 20.0) == round(50 * .4 + 20 * .3 + (10 / 30 * 100) * .15 + 60 * .15, 1)
    assert catalyst_score(None, None, None, None) is None


def test_fund_tier_needs_sample():
    assert fund_tier(90.0, 100.0, 30.0, enough=False) == "Insufficient sample"
    assert fund_tier(80.0, 80.0, 20.0, enough=True) == "Star Catalyst"
    assert fund_tier(62.0, 50.0, 12.0, enough=True) == "Strong Accumulator"
    assert fund_tier(46.0, 30.0, 5.0, enough=True) == "Steady Value"
    assert fund_tier(20.0, 20.0, 5.0, enough=True) == "Low Alpha / Laggard"
