"""Institutional Deals 2.0 Engine — Entity Resolution, Netting, Cluster Buying, and Cost-Basis Tracking."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import yaml


# -------------------------------------------------------------------------
# Entity Classification Keywords
# -------------------------------------------------------------------------

HFT_KEYWORDS = (
    "GRAVITON",
    "HRTI",
    "MICROCURVES",
    "JUNOMONETA",
    "QE SECURITIES",
    "NK SECURITIES",
    "JUMP TRADING",
    "IRAGE",
    "ELIXIR WEALTH",
    "YOKE SECURITIES",
    "TOWER RESEARCH",
    "CITADEL",
    "JANE STREET",
    "SHARE INDIA",
    "BLUEROCK",
    "ALPHA ALTERNATIVES",
    "RURBAN",
    "OPTIONSTOWN",
    "ESTEE ADVISORS",
    "QUANTUM TRADING",
    "DYNAMIC EQUITIES",
    "MANOJ KUMAR JAIN",
    "R K CHOTEWALA",
    "MILLENNIUM",
    "TWO SIGMA",
    "SUSQUEHANNA",
    "ALGO TRADING",
)

DII_MUTUAL_FUNDS = (
    "MUTUAL FUND",
    "TRUSTEE",
    "ASSET MANAGEMENT",
    "SBI MUTUAL",
    "HDFC MUTUAL",
    "ICICI PRUDENTIAL",
    "NIPPON INDIA",
    "KOTAK MAHINDRA MUTUAL",
    "AXIS MUTUAL",
    "UTI MUTUAL",
    "TATA MUTUAL",
    "ADITYA BIRLA SUN LIFE",
    "MIRAE ASSET",
    "BANDHAN MUTUAL",
    "CANARA ROBECO",
    "DSP MUTUAL",
    "EDELWEISS MUTUAL",
    "FRANKLIN TEMPLETON",
    "INVESCO MUTUAL",
    "SUNDARAM MUTUAL",
    "MOTILAL OSWAL MUTUAL",
    "UNION MUTUAL",
    "BARODA BNP",
    "QUANT MUTUAL",
    "PGIM INDIA",
    "MAHINDRA MANULIFE",
    "GROWW MUTUAL",
    "360 ONE MUTUAL",
    "WHITE OAK",
    "PPFAS",
    "PARAG PARIKH",
    "HSBC MUTUAL",
    "TRUST MUTUAL",
    "TAURUS MUTUAL",
    "SAMCO MUTUAL",
    "NAVI MUTUAL",
    "NJ MUTUAL",
    "HELIOS MUTUAL",
    "ZERODHA MUTUAL",
    "OLD BRIDGE",
)

DII_INSURANCE_PENSION = (
    "LIFE INSURANCE",
    "GENERAL INSURANCE",
    "LIC OF INDIA",
    "HDFC LIFE",
    "ICICI PRU LIFE",
    "SBI LIFE",
    "MAX LIFE",
    "BAJAJ ALLIANZ",
    "TATA AIA",
    "KOTAK LIFE",
    "ADITYA BIRLA SUN LIFE INSURANCE",
    "STAR HEALTH",
    "NEW INDIA ASSURANCE",
    "GIC OF INDIA",
    "EMPLOYEES PROVIDENT",
    "PENSION FUND",
    "NPS TRUST",
)

FII_GLOBAL_FUNDS = (
    "GOVERNMENT OF SINGAPORE",
    "GIC PRIVATE",
    "NORGES BANK",
    "ABU DHABI INVESTMENT",
    "ADIA",
    "VANGUARD",
    "BLACKROCK",
    "FIDELITY",
    "GQG PARTNERS",
    "GOLDMAN SACHS",
    "MORGAN STANLEY",
    "SOCIETE GENERALE",
    "BNP PARIBAS",
    "CITIGROUP",
    "JPMORGAN",
    "J.P. MORGAN",
    "UBS",
    "NOMURA",
    "CREDIT SUISSE",
    "BARCLAYS",
    "HSBC",
    "MACQUARIE",
    "CAPITAL GROUP",
    "TEMASEK",
    "CDPQ",
    "CPP INVESTMENT",
    "CPPIB",
    "MONETARY AUTHORITY OF SINGAPORE",
    "EMERGING MARKETS",
    "OFFSHORE",
    "MAURITIUS",
    "CAYMAN",
    "FII",
    "FPI",
    "MARSHALL WACE",
    "MILLENNIUM",
    "POINT72",
    "BAILLIE GIFFORD",
    "WELLINGTON",
    "T. ROWE PRICE",
    "SCHRODERS",
    "ALLIANCEBERNSTEIN",
    "KUWAIT INVESTMENT",
    "QATAR INVESTMENT",
)

SUPER_INVESTORS = (
    "JHUNJHUNWALA",
    "RAKESH JHUNJHUNWALA",
    "REKHA JHUNJHUNWALA",
    "RARE ENTERPRISES",
    "VIJAY KEDIA",
    "KEDIA SECURITIES",
    "ASHISH KACHOLIA",
    "RADHAKISHAN DAMANI",
    "BRIGHT STAR",
    "DERIVE INVESTMENTS",
    "MUKUL AGRAWAL",
    "DOLLY KHANNA",
    "PORINJU VELIYATH",
    "EQUITY INTELLIGENCE",
    "NEMISH SHAH",
    "SUNIL SINGHANIA",
    "ABAKKUS",
    "MADHULIKA",
    "KENIN BHARAT",
    "SANJAY DANGI",
    "ANIL KUMAR GOEL",
    "SEEMA GOEL",
    "SHIVANI TEJAS TRIVEDI",
)


_KEYWORD_FILE = Path(__file__).with_name("data") / "clientele_keywords.yaml"
_KEYWORD_DATA = yaml.safe_load(_KEYWORD_FILE.read_text(encoding="utf-8"))
HFT_KEYWORDS = tuple(_KEYWORD_DATA["hft_keywords"])
DII_MUTUAL_FUNDS = tuple(_KEYWORD_DATA["dii_mutual_funds"])
DII_INSURANCE_PENSION = tuple(_KEYWORD_DATA["dii_insurance_pension"])
FII_GLOBAL_FUNDS = tuple(_KEYWORD_DATA["fii_global_funds"])
SUPER_INVESTORS = tuple(_KEYWORD_DATA["super_investors"])
CORPORATE_BLOCK_TOKENS = tuple(_KEYWORD_DATA["corporate_block_tokens"])
REVIEW_TOKENS = tuple(_KEYWORD_DATA["review_tokens"])


def _classification(
    *,
    raw: str,
    clientele: str,
    clientele_sub: str | None,
    is_prop: bool,
    is_institutional: bool,
    tier: str,
    category: str,
    needs_review: bool = False,
) -> dict[str, Any]:
    return {
        "clientele": clientele,
        "clientele_sub": clientele_sub,
        "is_prop": is_prop,
        "needs_review": needs_review,
        "tier": tier,
        "category": category,
        "is_hft": is_prop,
        "is_institutional": is_institutional,
        "clean_name": raw,
    }


def classify_client(client_name: str | None) -> dict[str, Any]:
    """Classify a raw client name using the persisted clientele waterfall."""
    if not client_name or pd.isna(client_name):
        return _classification(
            raw="",
            clientele="OTHER",
            clientele_sub=None,
            is_prop=False,
            is_institutional=False,
            tier="Other",
            category="Unclassified",
        )

    raw = str(client_name).strip()
    name_upper = raw.upper()
    prop_hit = any(k in name_upper for k in HFT_KEYWORDS)
    fii_hit = any(k in name_upper for k in FII_GLOBAL_FUNDS)
    needs_review = any(k in name_upper for k in REVIEW_TOKENS) or (prop_hit and fii_hit)

    # 1. PROP wins over every other list; v1 does not infer a microstructure split.
    if prop_hit:
        return _classification(
            raw=raw,
            clientele="PROP",
            clientele_sub="PROP_HFT",
            is_prop=True,
            is_institutional=False,
            tier="HFT / Arbitrage",
            category="Algorithmic Arbitrage",
            needs_review=needs_review,
        )

    # 2. DII mutual funds, excluding brokers and capital-market businesses.
    if any(k in name_upper for k in DII_MUTUAL_FUNDS):
        if not any(k in name_upper for k in CORPORATE_BLOCK_TOKENS):
            return _classification(
                raw=raw,
                clientele="DII",
                clientele_sub="MF",
                is_prop=False,
                is_institutional=True,
                tier="DII (Domestic Institutional)",
                category="Mutual Fund",
            )

    # 3. DII insurance and pension.
    if any(k in name_upper for k in DII_INSURANCE_PENSION):
        return _classification(
            raw=raw,
            clientele="DII",
            clientele_sub="INSURANCE_PENSION",
            is_prop=False,
            is_institutional=True,
            tier="DII (Domestic Institutional)",
            category="Insurance / Pension",
        )

    # 4. FII / global asset managers / sovereign funds.
    if fii_hit:
        cat = "Sovereign Wealth Fund" if any(k in name_upper for k in ("GOVERNMENT", "NORGES", "GIC", "ABU DHABI", "TEMASEK", "KUWAIT", "QATAR")) else "Foreign Portfolio Investor"
        return _classification(
            raw=raw,
            clientele="FII",
            clientele_sub="SWF" if cat == "Sovereign Wealth Fund" else "FPI",
            is_prop=False,
            is_institutional=True,
            tier="FII (Foreign Institutional)",
            category=cat,
            needs_review=needs_review,
        )

    # 5. Super investors are tagged HNI, not elevated to a skill tier.
    if any(k in name_upper for k in SUPER_INVESTORS):
        return _classification(
            raw=raw,
            clientele="HNI",
            clientele_sub=None,
            is_prop=False,
            is_institutional=True,
            tier="Super Investor / HNI",
            category="Super Investor",
        )

    # 6. Corporate only when the name is not a broker/research business.
    corporate_tokens = ("LIMITED", "LTD", "PVT", "PRIVATE", "VENTURES", "HOLDINGS", "TRUST", "INVESTMENTS", "PARTNERS")
    if any(k in name_upper for k in corporate_tokens) and not any(k in name_upper for k in CORPORATE_BLOCK_TOKENS):
        return _classification(
            raw=raw,
            clientele="CORPORATE",
            clientele_sub=None,
            is_prop=False,
            is_institutional=True,
            tier="Corporate / Promoter / PE",
            category="Corporate / Strategic",
        )

    return _classification(
        raw=raw,
        clientele="OTHER",
        clientele_sub=None,
        is_prop=False,
        is_institutional=False,
        tier="Other / Individual",
        category="Individual / Non-Inst",
    )


def enrich_deals_with_tiers(deals_df: pd.DataFrame) -> pd.DataFrame:
    """Enrich deals frame with classification tiers and flags."""
    if deals_df is None or deals_df.empty:
        return pd.DataFrame()

    out = deals_df.copy()
    classifications = [classify_client(c) for c in out["client_name"]]
    out["tier"] = [c["tier"] for c in classifications]
    out["category"] = [c["category"] for c in classifications]
    out["is_hft"] = [c["is_hft"] for c in classifications]
    out["is_institutional"] = [c["is_institutional"] for c in classifications]
    out["clientele"] = [c["clientele"] for c in classifications]
    out["clientele_sub"] = [c["clientele_sub"] for c in classifications]
    out["is_prop"] = [c["is_prop"] for c in classifications]
    out["needs_review"] = [c["needs_review"] for c in classifications]
    return out


def _ensure_clientele(deals_df: pd.DataFrame) -> pd.DataFrame:
    required = {
        "tier",
        "category",
        "is_hft",
        "is_institutional",
        "clientele",
        "clientele_sub",
        "is_prop",
        "needs_review",
    }
    if not required.issubset(deals_df.columns):
        return enrich_deals_with_tiers(deals_df)
    return deals_df.copy()


def _filter_clientele(
    deals_df: pd.DataFrame,
    *,
    clientele: tuple[str, ...] | None = None,
    exclude_hft: bool | None = None,
) -> pd.DataFrame:
    df = _ensure_clientele(deals_df)
    if clientele is not None:
        allowed = {str(value).upper() for value in clientele}
        return df[df["clientele"].isin(allowed)].copy()
    if exclude_hft is True:
        return df[~df["is_prop"]].copy()
    return df


def net_deals_daily(
    deals_df: pd.DataFrame,
    exclude_hft: bool | None = None,
    clientele: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Group deals by symbol, client, and trade_date to compute net flow.

    PROP is included by default. ``exclude_hft=True`` remains a deprecated
    compatibility alias for one release.
    """
    if deals_df is None or deals_df.empty:
        return pd.DataFrame()

    df = _filter_clientele(deals_df, clientele=clientele, exclude_hft=exclude_hft)

    if df.empty:
        return pd.DataFrame()

    grouped = (
        df.groupby(["trade_date", "symbol", "client_name", "tier", "category", "is_institutional"], as_index=False)
        .agg(
            buy_qty=("quantity", lambda q: q[df.loc[q.index, "side"] == "BUY"].sum()),
            sell_qty=("quantity", lambda q: q[df.loc[q.index, "side"] == "SELL"].sum()),
            buy_value_cr=("deal_value_cr", lambda v: v[df.loc[v.index, "side"] == "BUY"].sum()),
            sell_value_cr=("deal_value_cr", lambda v: v[df.loc[v.index, "side"] == "SELL"].sum()),
            buy_vwap=("price", lambda p: (p[df.loc[p.index, "side"] == "BUY"] * df.loc[p.index, "quantity"][df.loc[p.index, "side"] == "BUY"]).sum() / max(df.loc[p.index, "quantity"][df.loc[p.index, "side"] == "BUY"].sum(), 1)),
            sell_vwap=("price", lambda p: (p[df.loc[p.index, "side"] == "SELL"] * df.loc[p.index, "quantity"][df.loc[p.index, "side"] == "SELL"]).sum() / max(df.loc[p.index, "quantity"][df.loc[p.index, "side"] == "SELL"].sum(), 1)),
        )
    )
    grouped["net_qty"] = grouped["buy_qty"] - grouped["sell_qty"]
    grouped["net_value_cr"] = grouped["buy_value_cr"] - grouped["sell_value_cr"]
    grouped["effective_side"] = np.where(grouped["net_value_cr"] > 0, "BUY", np.where(grouped["net_value_cr"] < 0, "SELL", "NEUTRAL"))
    return grouped.sort_values(["trade_date", "symbol", "net_value_cr"], ascending=[False, True, False]).reset_index(drop=True)


def get_cluster_buys(
    deals_df: pd.DataFrame,
    lookback_days: int = 10,
    min_institutions: int = 2,
    exclude_hft: bool | None = None,
    clientele: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Detect cluster buying across institutional and PROP clientele."""
    if deals_df is None or deals_df.empty:
        return pd.DataFrame()

    df = _filter_clientele(deals_df, clientele=clientele, exclude_hft=exclude_hft)
    inst_buys = df[(df["is_institutional"] | df["is_prop"]) & (df["side"] == "BUY")].copy()

    if inst_buys.empty:
        return pd.DataFrame()

    latest_date = inst_buys["trade_date"].max()
    cutoff_date = latest_date - pd.Timedelta(days=lookback_days)
    window = inst_buys[inst_buys["trade_date"] >= cutoff_date].copy()

    if window.empty:
        return pd.DataFrame()

    if "price" not in window.columns:
        window["price"] = 0.0
    if "quantity" not in window.columns:
        window["quantity"] = 1.0


    summary = (
        window.groupby("symbol", as_index=False)
        .agg(
            institutions_count=("client_name", "nunique"),
            total_buy_cr=("deal_value_cr", "sum"),
            avg_buy_price=("price", lambda p: (p * window.loc[p.index, "quantity"]).sum() / max(window.loc[p.index, "quantity"].sum(), 1)),
            latest_deal_date=("trade_date", "max"),
            institutions_list=("client_name", lambda c: "; ".join(sorted(set(c)))),
            tiers_list=("tier", lambda t: ", ".join(sorted(set(t)))),
        )
    )
    cluster = summary[summary["institutions_count"] >= min_institutions].copy()
    return cluster.sort_values(["institutions_count", "total_buy_cr"], ascending=[False, False]).reset_index(drop=True)


def compute_stock_deal_metrics(
    deals_df: pd.DataFrame,
    latest_indicators_df: pd.DataFrame,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Compute institutional metrics per stock (net flow, cost basis vs CMP, cluster flags, normalized score)."""
    if deals_df is None or deals_df.empty:
        return pd.DataFrame()

    clean_deals = _ensure_clientele(deals_df)

    as_of = pd.Timestamp(as_of or clean_deals["trade_date"].max()).normalize()
    clean_deals["trade_date"] = pd.to_datetime(clean_deals["trade_date"]).dt.normalize()

    # Split windows
    d_today = clean_deals[clean_deals["trade_date"] == as_of]
    d_10d = clean_deals[clean_deals["trade_date"] >= as_of - pd.Timedelta(days=10)]
    d_30d = clean_deals[clean_deals["trade_date"] >= as_of - pd.Timedelta(days=30)]

    def calc_net(d):
        if d.empty:
            return pd.DataFrame(columns=["symbol", "buy_cr", "sell_cr", "net_cr", "inst_count", "buy_vwap"])
        return (
            d.groupby("symbol", as_index=False)
            .agg(
                buy_cr=("deal_value_cr", lambda v: v[d.loc[v.index, "side"] == "BUY"].sum()),
                sell_cr=("deal_value_cr", lambda v: v[d.loc[v.index, "side"] == "SELL"].sum()),
                inst_count=("client_name", lambda c: c[(d.loc[c.index, "is_institutional"] | d.loc[c.index, "is_prop"]) & (d.loc[c.index, "side"] == "BUY")].nunique()),
                buy_vwap=("price", lambda p: (p[d.loc[p.index, "side"] == "BUY"] * d.loc[p.index, "quantity"][d.loc[p.index, "side"] == "BUY"]).sum() / max(d.loc[p.index, "quantity"][d.loc[p.index, "side"] == "BUY"].sum(), 1)),
            )
        )

    net_today = calc_net(d_today).rename(columns={"buy_cr": "inst_buy_cr_today", "sell_cr": "inst_sell_cr_today", "inst_count": "inst_count_today", "buy_vwap": "inst_vwap_today"})
    net_10d = calc_net(d_10d).rename(columns={"buy_cr": "inst_buy_cr_10d", "sell_cr": "inst_sell_cr_10d", "inst_count": "inst_count_10d", "buy_vwap": "inst_vwap_10d"})
    net_30d = calc_net(d_30d).rename(columns={"buy_cr": "inst_buy_cr_30d", "sell_cr": "inst_sell_cr_30d", "inst_count": "inst_count_30d", "buy_vwap": "inst_vwap_30d"})

    merged = net_30d.merge(net_10d, on="symbol", how="left").merge(net_today, on="symbol", how="left")
    merged["inst_net_cr_30d"] = merged["inst_buy_cr_30d"].fillna(0) - merged["inst_sell_cr_30d"].fillna(0)
    merged["inst_net_cr_10d"] = merged["inst_buy_cr_10d"].fillna(0) - merged["inst_sell_cr_10d"].fillna(0)
    merged["inst_net_cr_today"] = merged["inst_buy_cr_today"].fillna(0) - merged["inst_sell_cr_today"].fillna(0)

    # Attach CMP from latest indicators
    if latest_indicators_df is not None and not latest_indicators_df.empty:
        ind_cols = [c for c in ["symbol", "close_price", "avg_traded_value_cr_20d", "rs_percentile", "vcp_score", "vcp_state", "away_52w_high_pct"] if c in latest_indicators_df.columns]
        merged = merged.merge(latest_indicators_df[ind_cols].drop_duplicates("symbol"), on="symbol", how="left")
        merged["cmp"] = pd.to_numeric(merged["close_price"], errors="coerce")
        inst_px = merged["inst_vwap_10d"].fillna(merged["inst_vwap_30d"])
        merged["inst_entry_vwap"] = inst_px
        merged["cmp_vs_inst_entry_pct"] = np.where(inst_px > 0, ((merged["cmp"] / inst_px) - 1) * 100, np.nan)

        # Normalized deal activity score (0-100)
        turnover_20d = pd.to_numeric(merged["avg_traded_value_cr_20d"], errors="coerce").fillna(10)
        flow_ratio = (merged["inst_net_cr_10d"].fillna(0) / turnover_20d.clip(lower=1)).clip(lower=-2, upper=5)
        merged["normalized_deal_activity"] = np.clip(50 + flow_ratio * 25, 0, 100).round(2)
        merged["is_cluster_buy"] = (merged["inst_count_10d"].fillna(0) >= 2) & (merged["inst_net_cr_10d"].fillna(0) > 0)
    else:
        merged["normalized_deal_activity"] = 50.0
        merged["is_cluster_buy"] = False

    return merged
