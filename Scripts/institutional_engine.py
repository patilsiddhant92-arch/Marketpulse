"""Institutional Deals 2.0 Engine — Entity Resolution, Netting, Cluster Buying, and Cost-Basis Tracking."""

from __future__ import annotations

import re
from typing import Any
import numpy as np
import pandas as pd


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


def classify_client(client_name: str | None) -> dict[str, Any]:
    """Classify a raw client name into Tier, Category, and institutional flags."""
    if not client_name or pd.isna(client_name):
        return {
            "tier": "Other",
            "category": "Unclassified",
            "is_hft": False,
            "is_institutional": False,
            "clean_name": "",
        }

    raw = str(client_name).strip()
    name_upper = raw.upper()

    # 1. Check HFT / Arbitrage / Prop first
    if any(k in name_upper for k in HFT_KEYWORDS):
        return {
            "tier": "HFT / Arbitrage",
            "category": "Algorithmic Arbitrage",
            "is_hft": True,
            "is_institutional": False,
            "clean_name": raw,
        }

    # 2. Check DII: Mutual Funds
    if any(k in name_upper for k in DII_MUTUAL_FUNDS):
        # Exclude broking/securities firms that contain MF names
        if not any(k in name_upper for k in ("BROKING", "CAPITAL MARKETS", "SHARE BROKERS", "LLP")):
            return {
                "tier": "DII (Domestic Institutional)",
                "category": "Mutual Fund",
                "is_hft": False,
                "is_institutional": True,
                "clean_name": raw,
            }

    # 3. Check DII: Insurance & Pension
    if any(k in name_upper for k in DII_INSURANCE_PENSION):
        return {
            "tier": "DII (Domestic Institutional)",
            "category": "Insurance / Pension",
            "is_hft": False,
            "is_institutional": True,
            "clean_name": raw,
        }

    # 4. Check FII / Global Asset Managers / Sovereign Funds
    if any(k in name_upper for k in FII_GLOBAL_FUNDS):
        cat = "Sovereign Wealth Fund" if any(k in name_upper for k in ("GOVERNMENT", "NORGES", "GIC", "ABU DHABI", "TEMASEK", "KUWAIT", "QATAR")) else "Foreign Portfolio Investor"
        return {
            "tier": "FII (Foreign Institutional)",
            "category": cat,
            "is_hft": False,
            "is_institutional": True,
            "clean_name": raw,
        }

    # 5. Check Super Investors / Celebrity HNIs
    if any(k in name_upper for k in SUPER_INVESTORS):
        return {
            "tier": "Super Investor / HNI",
            "category": "Super Investor",
            "is_hft": False,
            "is_institutional": True,
            "clean_name": raw,
        }

    # 6. Check Corporate / PE / Promoter
    if any(k in name_upper for k in ("LIMITED", "LTD", "PVT", "PRIVATE", "VENTURES", "HOLDINGS", "TRUST", "INVESTMENTS", "PARTNERS")):
        return {
            "tier": "Corporate / Promoter / PE",
            "category": "Corporate / Strategic",
            "is_hft": False,
            "is_institutional": True,
            "clean_name": raw,
        }

    return {
        "tier": "Other / Individual",
        "category": "Individual / Non-Inst",
        "is_hft": False,
        "is_institutional": False,
        "clean_name": raw,
    }


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
    return out


def net_deals_daily(deals_df: pd.DataFrame, exclude_hft: bool = True) -> pd.DataFrame:
    """Group deals by symbol, client, and trade_date to compute net directional flow."""
    if deals_df is None or deals_df.empty:
        return pd.DataFrame()

    df = enrich_deals_with_tiers(deals_df) if "is_hft" not in deals_df.columns else deals_df.copy()
    if exclude_hft:
        df = df[~df["is_hft"]].copy()

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


def get_cluster_buys(deals_df: pd.DataFrame, lookback_days: int = 10, min_institutions: int = 2) -> pd.DataFrame:
    """Detect cluster buying where multiple distinct institutional funds accumulate within a lookback window."""
    if deals_df is None or deals_df.empty:
        return pd.DataFrame()

    df = enrich_deals_with_tiers(deals_df) if "is_institutional" not in deals_df.columns else deals_df.copy()
    inst_buys = df[df["is_institutional"] & (df["side"] == "BUY") & (~df["is_hft"])].copy()

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

    df = enrich_deals_with_tiers(deals_df) if "is_institutional" not in deals_df.columns else deals_df.copy()
    # Filter out HFT arbitrage
    clean_deals = df[~df["is_hft"]].copy()

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
                inst_count=("client_name", lambda c: c[d.loc[c.index, "is_institutional"] & (d.loc[c.index, "side"] == "BUY")].nunique()),
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
