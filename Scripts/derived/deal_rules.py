"""Deal event classification rules — ONE implementation shared by the nightly builder
(Scripts/derived/deal_session_net.py) and the live API fallback (App/services/deals.py),
so the stored table and the live frame can never label a session differently.

Input to the helpers is a frame of collapsed prints (one row per trade_date, symbol, client,
side, quantity, price) with columns: trade_date, symbol, client, side ('BUY'/'SELL'), quantity,
price, value_cr, clientele (PROP already resolved: clientele == 'PROP' for prop desks).

Rules (first match wins, EVENT_RULES):
  transfer_interse · placement — matched BUY/SELL between different clients covers >= 50% of the
      buy value; matching is print-by-print (qty ±1%, price ±0.25%) OR in aggregate (non-PROP buy
      and sell quantities within ±1%, VWAPs within ±0.25%, no client on both sides) so a promoter
      transfer split over several prints/entities is still a transfer (ADANIENT, DALBHARAT 2026-09-25).
  churn — PROP desks are removed FIRST; then same-client round trips >= 50% of the remaining gross,
      or nothing is left (PROP-only day / buys and sells cancel). A PROP desk churning beside a real
      fund sale no longer hides it (POLICYBZR 2026-09-25 is distribute).
  accumulate · fresh · distribute — sign of the net ex-PROP and prior net-buy sessions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRANSFER_QTY_TOL = 0.01      # matched BUY/SELL quantities within ±1%
TRANSFER_PRICE_TOL = 0.0025  # and prices (or VWAPs) within ±0.25%
MATCH_SHARE_MIN = 0.5        # matched value must cover >= 50% of the session's buy value
CHURN_SHARE_MIN = 0.5        # non-PROP round trips >= 50% of non-PROP gross value
PERSISTENCE_SESSIONS = 10
INSTITUTIONAL = ("FII", "DII")
KEYS = ["trade_date", "symbol"]
NET_DECIMALS = 6             # nets are compared after rounding to 1e-6 Cr (₹10): float noise is not a buy/sell


def net_sign(net_ex_prop: pd.Series) -> pd.Series:
    """+1 / 0 / -1 of the net ex-PROP after rounding (NaN stays NaN)."""
    return np.sign(pd.to_numeric(net_ex_prop, errors="coerce").round(NET_DECIMALS))

EVENT_RULES: list[dict[str, str]] = [
    {"event_type": "transfer_interse",
     "rule": "Matched BUY/SELL prints between different clients (qty within ±1%, price within ±0.25% — print by print, "
             "or in aggregate when one seller is split across several buyers) cover ≥ 50% of the session's buy value, "
             "and the matched buyers are not all FII/DII."},
    {"event_type": "placement",
     "rule": "Same match, but every matched buyer is FII or DII (institutions absorbing a promoter/corporate block)."},
    {"event_type": "churn",
     "rule": "After removing PROP desks: same-client round trips are ≥ 50% of the remaining deal value, or nothing is left "
             "(PROP-only day, or buys and sells cancel exactly)."},
    {"event_type": "accumulate",
     "rule": "Net value excluding PROP > 0 and another net-buy session in the prior 9 market sessions."},
    {"event_type": "fresh", "rule": "Net value excluding PROP > 0 with no net-buy session in the prior 9 market sessions."},
    {"event_type": "distribute", "rule": "Net value excluding PROP < 0."},
]
EVENT_TYPES = [r["event_type"] for r in EVENT_RULES]
RULE_TEXT = {r["event_type"]: r["rule"] for r in EVENT_RULES}


def matched_transfers(p: pd.DataFrame) -> pd.DataFrame:
    """Per symbol-day: matched_value_cr (BUY value matched by SELLs from other clients) and matched_inst
    (every matched buyer is FII/DII). Best of the print-by-print and the aggregate match."""
    empty = pd.DataFrame(columns=[*KEYS, "matched_value_cr", "matched_inst"])
    buys = p[p["side"] == "BUY"].reset_index(drop=True).reset_index(names="buy_id")
    sells = p[p["side"] == "SELL"][[*KEYS, "client", "quantity", "price"]]
    if buys.empty or sells.empty:
        return empty
    m = buys.merge(sells, on=KEYS, suffixes=("", "_s"))
    ok = ((m["client"] != m["client_s"])
          & ((m["quantity"] - m["quantity_s"]).abs() <= TRANSFER_QTY_TOL * m[["quantity", "quantity_s"]].max(axis=1))
          & ((m["price"] - m["price_s"]).abs() <= TRANSFER_PRICE_TOL * m[["price", "price_s"]].max(axis=1)))
    m = m[ok.to_numpy(dtype=bool)].drop_duplicates("buy_id")
    m["inst"] = m["clientele"].isin(INSTITUTIONAL).astype(float)
    one = m.groupby(KEYS, as_index=False).agg(matched_value_cr=("value_cr", "sum"), inst=("inst", "min"))
    # Aggregate match (one seller -> several buyers, or the reverse): non-PROP buy and sell quantities agree
    # within ±1% and their VWAPs within ±0.25%, with no client on both sides.
    q = p[p["clientele"] != "PROP"].copy()
    isb = q["side"] == "BUY"
    q["bq"] = np.where(isb, q["quantity"], 0.0)
    q["sq"] = np.where(~isb, q["quantity"], 0.0)
    q["bpx"] = q["bq"] * q["price"]
    q["spx"] = q["sq"] * q["price"]
    q["bv"] = np.where(isb, q["value_cr"], 0.0)
    q["binst"] = np.where(isb, q["clientele"].isin(INSTITUTIONAL).astype(float), np.nan)
    both = q.groupby([*KEYS, "client"])["side"].nunique().groupby(level=[0, 1]).max()
    g = q.groupby(KEYS).agg(bq=("bq", "sum"), sq=("sq", "sum"), bpx=("bpx", "sum"),
                            spx=("spx", "sum"), bv=("bv", "sum"), binst=("binst", "min"))
    g["two_sided_client"] = both.reindex(g.index).fillna(1) > 1
    bvw, svw = g["bpx"] / g["bq"].where(g["bq"] > 0), g["spx"] / g["sq"].where(g["sq"] > 0)
    agg_ok = ((g["bq"] > 0) & (g["sq"] > 0) & ~g["two_sided_client"]
              & ((g["bq"] - g["sq"]).abs() <= TRANSFER_QTY_TOL * g[["bq", "sq"]].max(axis=1))
              & ((bvw - svw).abs() <= TRANSFER_PRICE_TOL * pd.concat([bvw, svw], axis=1).max(axis=1)))
    ag = g[agg_ok.fillna(False)].reset_index()
    ag = pd.DataFrame({"trade_date": ag["trade_date"], "symbol": ag["symbol"], "matched_value_cr": ag["bv"],
                       "inst": ag["binst"]})
    parts = [x for x in (one, ag) if not x.empty]
    if not parts:
        return empty
    a = pd.concat(parts, ignore_index=True)
    a = a.sort_values("matched_value_cr", ascending=False).drop_duplicates(KEYS)
    a["matched_inst"] = a["inst"] == 1.0
    return a.drop(columns=["inst"]).reset_index(drop=True)


def client_day_stats(p: pd.DataFrame) -> pd.DataFrame:
    """Per symbol-day (index trade_date, symbol): buying_houses / selling_houses (non-PROP net buyers /
    sellers), round_trip_value_cr (all clients), round_trip_ex_prop_cr and gross_ex_prop_cr (churn inputs),
    n_clients."""
    buy = p["side"] == "BUY"
    q = pd.DataFrame({"trade_date": p["trade_date"], "symbol": p["symbol"], "client": p["client"],
                      "clientele": p["clientele"], "buy_val": np.where(buy, p["value_cr"], 0.0),
                      "sell_val": np.where(~buy, p["value_cr"], 0.0)})
    cd = q.groupby([*KEYS, "client", "clientele"], as_index=False)[["buy_val", "sell_val"]].sum()
    cnet = cd["buy_val"] - cd["sell_val"]
    nonprop = cd["clientele"] != "PROP"
    cd["is_buyer"] = ((cnet > 0) & nonprop).astype(float)
    cd["is_seller"] = ((cnet < 0) & nonprop).astype(float)
    cd["rt"] = np.minimum(cd["buy_val"], cd["sell_val"])
    cd["rt_np"] = cd["rt"].where(nonprop, 0.0)
    cd["gross_np"] = (cd["buy_val"] + cd["sell_val"]).where(nonprop, 0.0)
    return cd.groupby(KEYS).agg(buying_houses=("is_buyer", "sum"), selling_houses=("is_seller", "sum"),
                                round_trip_value_cr=("rt", "sum"), round_trip_ex_prop_cr=("rt_np", "sum"),
                                gross_ex_prop_cr=("gross_np", "sum"), n_clients=("client", "nunique"))


def net_buy_sessions(symbol: pd.Series, session_idx: pd.Series, net_ex_prop: pd.Series) -> np.ndarray:
    """Sessions with net ex-PROP > 0 among the last PERSISTENCE_SESSIONS market sessions incl. t.
    Rows must be sorted by (symbol, session_idx); session_idx = position in the market calendar."""
    pos = (net_sign(net_ex_prop) > 0).to_numpy(dtype=float)
    si_all = session_idx.to_numpy(dtype=np.int64)
    out = np.zeros(len(pos))
    for ix in pd.Series(np.arange(len(pos))).groupby(symbol.to_numpy(), sort=False).indices.values():
        si = si_all[ix]
        cs = np.concatenate([[0.0], np.cumsum(pos[ix])])
        left = np.searchsorted(si, si - (PERSISTENCE_SESSIONS - 1), side="left")
        out[ix] = cs[np.arange(1, len(ix) + 1)] - cs[left]
    return out


def classify_events(*, matched_value_cr: pd.Series, buy_value_cr: pd.Series, matched_inst: pd.Series,
                    round_trip_ex_prop_cr: pd.Series, gross_ex_prop_cr: pd.Series, net_ex_prop_cr: pd.Series,
                    prior_net_buy_sessions: pd.Series) -> np.ndarray:
    """Event type per row (object array; None when no rule matches, e.g. unknown net)."""
    mv = pd.to_numeric(matched_value_cr, errors="coerce").fillna(0.0)
    matched = (mv >= MATCH_SHARE_MIN * buy_value_cr) & (mv > 0)
    inst = pd.Series(matched_inst, index=mv.index).astype("boolean").fillna(False).astype(bool)
    gross_np = gross_ex_prop_cr.where(gross_ex_prop_cr > 0)
    net = net_sign(net_ex_prop_cr)
    churn = ((2 * round_trip_ex_prop_cr / gross_np) >= CHURN_SHARE_MIN) | (net == 0)
    prior = prior_net_buy_sessions
    conds = [matched & ~inst, matched & inst, churn, (net > 0) & (prior > 0), (net > 0) & (prior <= 0), net < 0]
    return np.select([c.fillna(False).to_numpy(dtype=bool) for c in conds], EVENT_TYPES, default=None)
