"""deal_session_net — bulk/block deal flow per symbol x session (spec §4.5, §7.5).

Prints are first collapsed to one row per (trade_date, symbol, client, side, quantity, price)
(a print reported in both the bulk and block files counts once; its deal types are kept).
Client class comes from deals.clientele when present, else Scripts.institutional_engine.
classify_client (the app's clientele waterfall) — never re-implemented here.

Event classification rules are data (EVENT_RULES) and are evaluated top to bottom.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ._common import clean_symbols, normalise_dates, num

CLASSES = ("FII", "DII", "PROP", "CORPORATE", "HNI", "OTHER")
INSTITUTIONAL_ABSORBERS = ("FII", "DII")

TRANSFER_QTY_TOL = 0.01     # matched BUY/SELL quantities within ±1%
TRANSFER_PRICE_TOL = 0.0025  # and prices within ±0.25%
MATCH_SHARE_MIN = 0.5       # matched pairs must cover >= 50% of the session's buy value
CHURN_SHARE_MIN = 0.5       # round-trip or PROP value >= 50% of gross value
PERSISTENCE_SESSIONS = 10

EVENT_RULES: list[dict[str, str]] = [
    {"event_type": "transfer_interse",
     "rule": "Matched BUY/SELL prints between different clients (qty within ±1%, price within ±0.25%) cover "
             ">= 50% of the session's buy value, and the matched buyers are not all FII/DII."},
    {"event_type": "placement",
     "rule": "Same match condition, but every matched buyer is FII or DII (institutions absorbing a "
             "promoter/corporate block)."},
    {"event_type": "churn",
     "rule": "Same-client round trips (buy and sell the same day) or PROP prints are >= 50% of gross deal "
             "value, or net value excluding PROP is exactly zero."},
    {"event_type": "accumulate",
     "rule": "Net value excluding PROP > 0 and the symbol also had a net-buy (ex-PROP) session in the prior "
             "9 market sessions."},
    {"event_type": "fresh",
     "rule": "Net value excluding PROP > 0 with no net-buy (ex-PROP) session in the prior 9 market sessions."},
    {"event_type": "distribute", "rule": "Net value excluding PROP < 0."},
]


def _classify_names(names: pd.Series) -> pd.Series:
    try:
        from Scripts.institutional_engine import classify_client
    except ImportError:  # pragma: no cover - script-style import
        try:
            from institutional_engine import classify_client  # type: ignore
        except ImportError:
            return pd.Series("OTHER", index=names.index)
    uniq = {n: classify_client(n)["clientele"] for n in names.dropna().unique()}
    return names.map(uniq).fillna("OTHER")


def normalise_deals(deals: pd.DataFrame | None) -> pd.DataFrame:
    """Clean + collapse deal prints. Columns: trade_date, symbol, client, side, quantity, price,
    value_cr, clientele, deal_types."""
    cols = ["trade_date", "symbol", "client", "side", "quantity", "price", "value_cr", "clientele", "deal_types"]
    if deals is None or deals.empty:
        return pd.DataFrame(columns=cols)
    d = clean_symbols(deals.copy())
    d["trade_date"] = normalise_dates(d["trade_date"])
    d["side"] = d["side"].astype("string").str.strip().str.upper()
    d["client"] = d.get("client_name", pd.Series("", index=d.index)).astype("string").str.strip().str.upper().fillna("")
    d["quantity"] = num(d, "quantity")
    d["price"] = num(d, "price")
    d = d[d["side"].isin(["BUY", "SELL"]).to_numpy(dtype=bool) & d["trade_date"].notna().to_numpy()
          & (d["quantity"] > 0).to_numpy() & (d["price"] > 0).to_numpy()].copy()
    if d.empty:
        return pd.DataFrame(columns=cols)
    if "clientele" in d.columns:
        cl = d["clientele"].astype("string").str.strip().str.upper()
        missing = cl.isna() | (cl == "")
        if missing.any():
            cl = cl.where(~missing, _classify_names(d["client"]))
    else:
        cl = _classify_names(d["client"])
    d["clientele"] = cl.where(cl.isin(CLASSES), "OTHER").astype(str)
    d["deal_type"] = d.get("deal_type", pd.Series("", index=d.index)).astype("string").fillna("").astype(str)
    key = ["trade_date", "symbol", "client", "side", "quantity", "price"]
    types = d.groupby(key, sort=False)["deal_type"].agg(lambda s: "+".join(sorted({t for x in s for t in str(x).split("+") if t})))
    first = d.drop_duplicates(key, keep="first").set_index(key)
    first["deal_types"] = types
    out = first.reset_index()
    out["value_cr"] = out["quantity"] * out["price"] / 1e7
    return out[cols].reset_index(drop=True)


def _session_index(prices: pd.DataFrame | None, deal_dates: pd.Series) -> pd.Series:
    """Market session calendar -> 0..n index (prices dates, plus any deal-only dates)."""
    dates = set(pd.to_datetime(deal_dates).dropna().unique())
    if prices is not None and not prices.empty and "trade_date" in prices.columns:
        dates |= set(normalise_dates(prices["trade_date"]).dropna().unique())
    cal = pd.DatetimeIndex(sorted(dates))
    return pd.Series(np.arange(len(cal)), index=cal)


def _matched_transfers(p: pd.DataFrame) -> pd.DataFrame:
    """Per symbol-day: value of BUY prints matched by a SELL print from another client, and whether
    all matched buyers are FII/DII."""
    buys = p[p["side"] == "BUY"][["trade_date", "symbol", "client", "quantity", "price", "value_cr", "clientele"]]
    sells = p[p["side"] == "SELL"][["trade_date", "symbol", "client", "quantity", "price"]]
    empty = pd.DataFrame(columns=["trade_date", "symbol", "matched_value_cr", "matched_buyers_institutional"])
    if buys.empty or sells.empty:
        return empty
    buys = buys.reset_index(names="buy_id")
    m = buys.merge(sells, on=["trade_date", "symbol"], suffixes=("", "_s"))
    ok = (m["client"] != m["client_s"]) \
        & ((m["quantity"] - m["quantity_s"]).abs() <= TRANSFER_QTY_TOL * m[["quantity", "quantity_s"]].max(axis=1)) \
        & ((m["price"] - m["price_s"]).abs() <= TRANSFER_PRICE_TOL * m[["price", "price_s"]].max(axis=1))
    m = m[ok.to_numpy(dtype=bool)].drop_duplicates("buy_id")
    if m.empty:
        return empty
    m["inst"] = m["clientele"].isin(INSTITUTIONAL_ABSORBERS).astype(float)
    agg = m.groupby(["trade_date", "symbol"], as_index=False).agg(matched_value_cr=("value_cr", "sum"), inst=("inst", "min"))
    agg["matched_buyers_institutional"] = agg["inst"] == 1.0
    return agg.drop(columns=["inst"])


OUTPUT_COLUMNS = [
    "trade_date", "symbol", "n_prints", "n_clients", "deal_types",
    "buy_qty", "sell_qty", "net_qty", "buy_value_cr", "sell_value_cr", "net_value_cr", "gross_value_cr",
    "net_value_cr_ex_prop", *[f"net_value_cr_{c.lower()}" for c in CLASSES],
    "buying_houses", "selling_houses", "buy_vwap", "sell_vwap", "vwap",
    "close_price", "deal_price_vs_close_pct", "buy_vwap_vs_close_pct",
    "adv_cr", "net_vs_adv", "deal_qty_pct_volume",
    "round_trip_value_cr", "prop_value_cr", "matched_value_cr", "matched_buyers_institutional",
    "net_buy_sessions_10", "event_type", "event_rule",
]


def build_deal_session_net(
    deals: pd.DataFrame | None,
    prices: pd.DataFrame | None,
    indicators: pd.DataFrame | None = None,
) -> pd.DataFrame:
    p = normalise_deals(deals)
    if p.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    buy = p["side"] == "BUY"
    p["buy_qty"] = np.where(buy, p["quantity"], 0.0)
    p["sell_qty"] = np.where(~buy, p["quantity"], 0.0)
    p["buy_val"] = np.where(buy, p["value_cr"], 0.0)
    p["sell_val"] = np.where(~buy, p["value_cr"], 0.0)
    keys = ["trade_date", "symbol"]

    # Per client-day (for houses and round trips).
    cd = p.groupby([*keys, "client", "clientele"], as_index=False)[["buy_qty", "sell_qty", "buy_val", "sell_val"]].sum()
    cd["client_net_val"] = cd["buy_val"] - cd["sell_val"]
    cd["round_trip"] = np.minimum(cd["buy_val"], cd["sell_val"])
    non_prop = cd["clientele"] != "PROP"
    cd["is_buyer"] = ((cd["client_net_val"] > 0) & non_prop).astype(float)
    cd["is_seller"] = ((cd["client_net_val"] < 0) & non_prop).astype(float)
    houses = cd.groupby(keys).agg(buying_houses=("is_buyer", "sum"), selling_houses=("is_seller", "sum"),
                                  round_trip_value_cr=("round_trip", "sum"), n_clients=("client", "nunique"))

    p["gross_qty_px"] = p["quantity"] * p["price"]
    s = p.groupby(keys).agg(
        n_prints=("side", "size"), buy_qty=("buy_qty", "sum"), sell_qty=("sell_qty", "sum"),
        buy_value_cr=("buy_val", "sum"), sell_value_cr=("sell_val", "sum"),
        gross_qty=("quantity", "sum"), gross_qty_px=("gross_qty_px", "sum"),
        deal_types=("deal_types", lambda x: "+".join(sorted({t for v in x for t in str(v).split("+") if t}))),
    )
    p["net_val"] = p["buy_val"] - p["sell_val"]
    by_class = p.pivot_table(index=keys, columns="clientele", values="net_val", aggfunc="sum", fill_value=0.0)
    for c in CLASSES:
        s[f"net_value_cr_{c.lower()}"] = by_class[c].reindex(s.index).fillna(0.0) if c in by_class.columns else 0.0
    prop_gross = p[p["clientele"] == "PROP"].groupby(keys)["value_cr"].sum()
    s["prop_value_cr"] = prop_gross.reindex(s.index).fillna(0.0)
    s = s.join(houses)
    s["net_qty"] = s["buy_qty"] - s["sell_qty"]
    s["net_value_cr"] = s["buy_value_cr"] - s["sell_value_cr"]
    s["gross_value_cr"] = s["buy_value_cr"] + s["sell_value_cr"]
    s["net_value_cr_ex_prop"] = s["net_value_cr"] - s["net_value_cr_prop"]
    s["buy_vwap"] = (s["buy_value_cr"] * 1e7 / s["buy_qty"]).where(s["buy_qty"] > 0)
    s["sell_vwap"] = (s["sell_value_cr"] * 1e7 / s["sell_qty"]).where(s["sell_qty"] > 0)
    s["vwap"] = (s["gross_qty_px"] / s["gross_qty"]).where(s["gross_qty"] > 0)
    s = s.reset_index()
    s = s.merge(_matched_transfers(p), on=keys, how="left")
    s["matched_value_cr"] = s["matched_value_cr"].fillna(0.0)

    # Prices / ADV (point-in-time: ADV as of the PREVIOUS session, so the deal day is excluded).
    s["close_price"] = np.nan
    s["volume"] = np.nan
    s["adv_cr"] = np.nan
    if prices is not None and not prices.empty:
        px = clean_symbols(prices[[c for c in ("symbol", "trade_date", "close_price", "volume", "turnover_cr") if c in prices.columns]].copy())
        px["trade_date"] = normalise_dates(px["trade_date"])
        px = px.sort_values(["symbol", "trade_date"]).drop_duplicates(["symbol", "trade_date"], keep="last")
        if "turnover_cr" in px.columns:
            px = px.reset_index(drop=True)
            adv = (px.groupby("symbol", sort=False)["turnover_cr"].rolling(20, min_periods=20).mean()
                   .reset_index(level=0, drop=True).sort_index())
            px["adv_px"] = adv.groupby(px["symbol"], sort=False).shift(1)
        s = s.drop(columns=["close_price", "volume"]).merge(
            px[["symbol", "trade_date", "close_price", *(["volume"] if "volume" in px.columns else []),
                *(["adv_px"] if "adv_px" in px.columns else [])]], on=keys, how="left")
        if "volume" not in s.columns:
            s["volume"] = np.nan
        if "adv_px" in s.columns:
            s["adv_cr"] = s["adv_px"]
            s = s.drop(columns=["adv_px"])
    if indicators is not None and not indicators.empty and "avg_traded_value_cr_20d" in indicators.columns:
        ind = clean_symbols(indicators[["symbol", "trade_date", "avg_traded_value_cr_20d"]].copy())
        ind["trade_date"] = normalise_dates(ind["trade_date"])
        ind = ind.sort_values(["symbol", "trade_date"]).drop_duplicates(["symbol", "trade_date"], keep="last")
        ind["adv_prev"] = ind.groupby("symbol", sort=False)["avg_traded_value_cr_20d"].shift(1)
        s = s.merge(ind[["symbol", "trade_date", "adv_prev"]], on=keys, how="left")
        s["adv_cr"] = s["adv_prev"].where(s["adv_prev"].notna(), s["adv_cr"])
        s = s.drop(columns=["adv_prev"])
    s["adv_cr"] = pd.to_numeric(s["adv_cr"], errors="coerce")
    s["net_vs_adv"] = (s["net_value_cr_ex_prop"] / s["adv_cr"]).where(s["adv_cr"] > 0)
    s["deal_price_vs_close_pct"] = ((s["vwap"] / s["close_price"] - 1.0) * 100.0).where(s["close_price"] > 0)
    s["buy_vwap_vs_close_pct"] = ((s["buy_vwap"] / s["close_price"] - 1.0) * 100.0).where(s["close_price"] > 0)
    s["deal_qty_pct_volume"] = (s[["buy_qty", "sell_qty"]].max(axis=1) / s["volume"] * 100.0).where(s["volume"] > 0)

    # Persistence: net-buy (ex-PROP) sessions among the last 10 market sessions (incl. today).
    sess = _session_index(prices, s["trade_date"])
    s["_si"] = s["trade_date"].map(sess).astype(int)
    s = s.sort_values(["symbol", "_si"]).reset_index(drop=True)
    s["_pos"] = (s["net_value_cr_ex_prop"] > 0).astype(float)
    s["_t"] = pd.Timestamp("2000-01-01") + pd.to_timedelta(s["_si"], unit="D")
    roll = (s.set_index("_t").groupby("symbol", sort=False)["_pos"]
            .rolling(f"{PERSISTENCE_SESSIONS}D").sum().reset_index(level=0, drop=True))
    s["net_buy_sessions_10"] = roll.to_numpy()
    prior_buys = s["net_buy_sessions_10"] - s["_pos"]

    s["event_type"] = _classify_events(s, prior_buys)
    rule_text = {r["event_type"]: r["rule"] for r in EVENT_RULES}
    s["event_rule"] = s["event_type"].map(rule_text)
    s = s.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    return s[OUTPUT_COLUMNS]


def _classify_events(s: pd.DataFrame, prior_buys: pd.Series) -> np.ndarray:
    matched = (s["matched_value_cr"] >= MATCH_SHARE_MIN * s["buy_value_cr"]) & (s["matched_value_cr"] > 0)
    inst = s["matched_buyers_institutional"].astype("boolean").fillna(False).astype(bool)
    gross = s["gross_value_cr"].where(s["gross_value_cr"] > 0)
    churn = ((2 * s["round_trip_value_cr"] / gross) >= CHURN_SHARE_MIN) | ((s["prop_value_cr"] / gross) >= CHURN_SHARE_MIN) \
        | (s["net_value_cr_ex_prop"] == 0)
    net = s["net_value_cr_ex_prop"]
    conds: list[tuple[str, Any]] = [
        ("transfer_interse", matched & ~inst),
        ("placement", matched & inst),
        ("churn", churn),
        ("accumulate", (net > 0) & (prior_buys > 0)),
        ("fresh", (net > 0) & (prior_buys <= 0)),
        ("distribute", net < 0),
    ]
    assert [c[0] for c in conds] == [r["event_type"] for r in EVENT_RULES]
    return np.select([c[1].fillna(False).to_numpy(dtype=bool) for c in conds], [c[0] for c in conds], default=None)


def event_rules_table() -> pd.DataFrame:
    return pd.DataFrame(EVENT_RULES)
