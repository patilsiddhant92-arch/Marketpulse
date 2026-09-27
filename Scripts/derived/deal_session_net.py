"""deal_session_net — bulk/block deal flow per symbol x session (spec §4.5, §7.5).

Prints are first collapsed to one row per (trade_date, symbol, client, side, quantity, price)
(a print reported in both the bulk and block files counts once; its deal types are kept).
Client class comes from deals.clientele when present, else Scripts.institutional_engine.
classify_client (the app's clientele waterfall) — never re-implemented here.

Event classification lives in Scripts/derived/deal_rules.py, shared with the live API fallback
(App/services/deals.py) so the stored labels and the live labels are the same by construction.
A print flagged deals.is_prop is a PROP print whatever its clientele; value_cr = deals.deal_value_cr
(quantity x price / 1e7 when missing) — both exactly as App.services.universe.collapsed_prints_sql.
"""
from __future__ import annotations


import numpy as np
import pandas as pd

from ._common import clean_symbols, normalise_dates, num

from .deal_rules import (  # noqa: F401  (rule constants re-exported)
    CHURN_SHARE_MIN, EVENT_RULES, INSTITUTIONAL, MATCH_SHARE_MIN, PERSISTENCE_SESSIONS, RULE_TEXT,
    TRANSFER_PRICE_TOL, TRANSFER_QTY_TOL, classify_events, client_day_stats, matched_transfers, net_buy_sessions,
    net_sign,
)

CLASSES = ("FII", "DII", "PROP", "CORPORATE", "HNI", "OTHER")
INSTITUTIONAL_ABSORBERS = INSTITUTIONAL


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


def _norm_types(values) -> str:
    """'Bulk', 'Block+Bulk', ... -> sorted unique '+'-joined deal types."""
    if isinstance(values, str):
        values = [values]
    return "+".join(sorted({t for v in values for t in str(v).split("+") if t and t != "nan"}))


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
    cl = cl.where(cl.isin(CLASSES), "OTHER")
    if "is_prop" in d.columns:
        cl = cl.where(~d["is_prop"].astype("boolean").fillna(False).astype(bool), "PROP")
    d["clientele"] = cl.astype(str)
    stated = num(d, "deal_value_cr")
    d["value_cr"] = stated.where(stated.notna(), d["quantity"] * d["price"] / 1e7)
    d["deal_type"] = d.get("deal_type", pd.Series("", index=d.index)).astype("string").fillna("").astype(str)
    key = ["trade_date", "symbol", "client", "side", "quantity", "price"]
    d["deal_types"] = d["deal_type"].map(_norm_types)
    dup = d.duplicated(key, keep=False).to_numpy()
    if dup.any():  # only the (few) prints reported in more than one file need merging
        g = d[dup].groupby(key, sort=False)
        merged = g["deal_type"].agg(_norm_types).rename("_merged").to_frame()
        merged["_prop"] = g["clientele"].agg(lambda v: (v == "PROP").any())  # bool_or(is_prop), as the live SQL
        d = d.merge(merged.reset_index(), on=key, how="left")
        d["deal_types"] = d["_merged"].where(d["_merged"].notna(), d["deal_types"])
        d["clientele"] = d["clientele"].where(~d["_prop"].astype("boolean").fillna(False).astype(bool), "PROP")
    out = d.drop_duplicates(key, keep="first").reset_index(drop=True)
    return out[cols].reset_index(drop=True)


def _session_index(prices: pd.DataFrame | None, deal_dates: pd.Series,
                   indicators: pd.DataFrame | None = None) -> pd.Series:
    """Market session calendar -> 0..n index (indicators/prices dates, plus any deal-only dates)."""
    dates = set(pd.to_datetime(deal_dates).dropna().unique())
    for frame in (prices, indicators):
        if frame is not None and not frame.empty and "trade_date" in frame.columns:
            dates |= set(pd.to_datetime(frame["trade_date"].drop_duplicates(), errors="coerce").dt.normalize().dropna())
    cal = pd.DatetimeIndex(sorted(dates))
    return pd.Series(np.arange(len(cal)), index=cal)


OUTPUT_COLUMNS = [
    "trade_date", "symbol", "n_prints", "n_clients", "deal_types",
    "buy_qty", "sell_qty", "net_qty", "buy_value_cr", "sell_value_cr", "net_value_cr", "gross_value_cr",
    "net_value_cr_ex_prop", *[f"net_value_cr_{c.lower()}" for c in CLASSES],
    "buying_houses", "selling_houses", "buy_vwap", "sell_vwap", "vwap",
    "close_price", "deal_price_vs_close_pct", "buy_vwap_vs_close_pct",
    "adv_cr", "net_vs_adv", "deal_qty_pct_volume",
    "round_trip_value_cr", "round_trip_ex_prop_cr", "gross_ex_prop_cr", "prop_value_cr",
    "matched_value_cr", "matched_buyers_institutional",
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

    # Per client-day (houses, round trips, churn inputs) — shared rules.
    houses = client_day_stats(p)

    p["gross_qty_px"] = p["quantity"] * p["price"]
    s = p.groupby(keys).agg(
        n_prints=("side", "size"), buy_qty=("buy_qty", "sum"), sell_qty=("sell_qty", "sum"),
        buy_value_cr=("buy_val", "sum"), sell_value_cr=("sell_val", "sum"),
        gross_qty=("quantity", "sum"), gross_qty_px=("gross_qty_px", "sum"),
    )
    s["deal_types"] = p.groupby(keys)["deal_types"].agg(_norm_types)
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
    s = s.merge(matched_transfers(p), on=keys, how="left").rename(columns={"matched_inst": "matched_buyers_institutional"})
    s["matched_value_cr"] = pd.to_numeric(s["matched_value_cr"], errors="coerce").fillna(0.0)

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
    sess = _session_index(prices, s["trade_date"], indicators)
    s["_si"] = s["trade_date"].map(sess).astype(int)
    s = s.sort_values(["symbol", "_si"]).reset_index(drop=True)
    s["net_buy_sessions_10"] = net_buy_sessions(s["symbol"], s["_si"], s["net_value_cr_ex_prop"])
    prior_buys = s["net_buy_sessions_10"] - (net_sign(s["net_value_cr_ex_prop"]) > 0).astype(float)

    s["event_type"] = classify_events(
        matched_value_cr=s["matched_value_cr"], buy_value_cr=s["buy_value_cr"],
        matched_inst=s["matched_buyers_institutional"], round_trip_ex_prop_cr=s["round_trip_ex_prop_cr"],
        gross_ex_prop_cr=s["gross_ex_prop_cr"], net_ex_prop_cr=s["net_value_cr_ex_prop"],
        prior_net_buy_sessions=prior_buys)
    s["event_rule"] = s["event_type"].map(RULE_TEXT)
    s = s.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    return s[OUTPUT_COLUMNS]


def event_rules_table() -> pd.DataFrame:
    return pd.DataFrame(EVENT_RULES)
