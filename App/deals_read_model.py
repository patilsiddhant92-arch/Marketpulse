"""Read-only Deal Flow Desk queries (PR-DEALS 2.0).

Open path budget: ≤2 DuckDB executes.
- Query 1: latest-session BUY universe with clientele classification + cost-basis
- Query 2: flow spark lookback
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import duckdb
import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parent.parent / "Scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

try:
    from institutional_engine import (
        classify_client,
        enrich_deals_with_tiers,
        get_cluster_buys,
    )
    from telegram_deals import to_tv_list
except ModuleNotFoundError:
    from Scripts.institutional_engine import (  # type: ignore
        classify_client,
        enrich_deals_with_tiers,
        get_cluster_buys,
    )
    from Scripts.telegram_deals import to_tv_list  # type: ignore



@dataclass(frozen=True)
class DealsDeskDefault:
    as_of: str | None
    buy_tv: str
    symbols_for_tv: tuple[str, ...]
    buy_count: int
    cards: pd.DataFrame
    flow: pd.DataFrame
    query_count: int
    cluster_buys: pd.DataFrame = None  # type: ignore
    universe_label: str = "₹1,000 Cr+ and CMP > 200 EMA"
    filter_notes: str = ""


def _empty(as_of: str | None = None) -> DealsDeskDefault:
    return DealsDeskDefault(
        as_of=as_of,
        buy_tv="",
        symbols_for_tv=(),
        buy_count=0,
        cards=pd.DataFrame(),
        flow=pd.DataFrame(),
        query_count=0,
        cluster_buys=pd.DataFrame(),
        universe_label="₹1,000 Cr+ and CMP > 200 EMA",
        filter_notes="No deal rows passed the latest-session universe gates.",
    )


def query_deals_desk_default(
    db_path: Path,
    *,
    min_mcap_cr: float = 1000.0,
    card_limit: int = 12,
    flow_lookback_days: int = 10,
    exclude_hft: bool | None = None,
    clientele: tuple[str, ...] | None = None,
) -> DealsDeskDefault:
    """Default open-path for Deal Flow Desk with Institutional intelligence (≤2 RO queries)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return _empty()

    card_limit = max(1, min(50, int(card_limit)))
    flow_lookback_days = max(1, min(60, int(flow_lookback_days)))
    min_mcap_cr = float(min_mcap_cr)
    query_count = 0

    with duckdb.connect(str(db_path), read_only=True) as db:
        session_sql = """
        WITH latest_deal AS (
            SELECT max(trade_date) AS d FROM deals
        )
        SELECT d.*,
               m.market_cap_cr, m.sector, m.industry,
               i.rs_percentile, i.away_52w_high_pct, i.close_price, i.ema_200
        FROM deals d
        JOIN latest_deal ld ON d.trade_date = ld.d
        LEFT JOIN stocks_master m ON m.symbol = d.symbol
        LEFT JOIN indicators_daily i ON i.symbol = d.symbol AND i.trade_date = ld.d
        """
        try:
            raw_session = db.execute(session_sql).fetchdf()
        except duckdb.Error:
            return _empty()

        # Query B: flow spark (lookback)
        flow_sql = f"""
        WITH latest AS (SELECT max(trade_date) d FROM deals),
        eligible AS (
            SELECT m.symbol
            FROM stocks_master m
            JOIN indicators_daily i ON i.symbol = m.symbol AND i.trade_date = (SELECT d FROM latest)
            WHERE m.market_cap_cr IS NOT NULL
              AND m.market_cap_cr >= {min_mcap_cr}
              AND i.ema_200 IS NOT NULL
              AND i.close_price IS NOT NULL
              AND i.close_price > i.ema_200
        )
        SELECT d.trade_date,
               sum(CASE WHEN d.side='BUY' THEN d.deal_value_cr ELSE 0 END) AS buy_cr,
               sum(CASE WHEN d.side='SELL' THEN d.deal_value_cr ELSE 0 END) AS sell_cr
        FROM deals d
        JOIN eligible e ON e.symbol = d.symbol
        CROSS JOIN latest
        WHERE d.trade_date >= (SELECT d FROM latest) - INTERVAL {int(flow_lookback_days)} DAY
        GROUP BY d.trade_date
        ORDER BY d.trade_date
        """
        flow = db.execute(flow_sql).fetchdf()
        query_count = 2

    as_of = None
    if not raw_session.empty and "trade_date" in raw_session.columns:
        as_of = str(pd.to_datetime(raw_session["trade_date"].iloc[0]).date())
    elif not flow.empty:
        as_of = str(pd.to_datetime(flow["trade_date"].max()).date())

    if raw_session.empty:
        return _empty(as_of)

    # Ensure optional columns exist
    for col, default_val in [
        ("price", 0.0),
        ("quantity", 1.0),
        ("deal_value_cr", 0.0),
        ("client_name", ""),
        ("rs_percentile", np.nan),
        ("away_52w_high_pct", np.nan),
        ("close_price", np.nan),
        ("ema_200", np.nan),
        ("vcp_score", np.nan),
        ("vcp_state", "None"),
        ("market_cap_cr", np.nan),
        ("sector", "Unclassified"),
        ("industry", "Unclassified"),
    ]:
        if col not in raw_session.columns:
            raw_session[col] = default_val

    # Classify entities
    enriched = enrich_deals_with_tiers(raw_session)


    # PROP is included by default. The old exclude_hft flag is an explicit
    # compatibility alias; new callers should use clientele.
    if clientele is not None:
        allowed = {str(value).upper() for value in clientele}
        enriched = enriched[enriched["clientele"].isin(allowed)].copy()
    elif exclude_hft is True:
        enriched = enriched[~enriched["is_prop"]].copy()


    # Filter to BUY side
    buys = enriched[enriched["side"] == "BUY"].copy()
    if buys.empty:
        return DealsDeskDefault(
            as_of=as_of,
            buy_tv="",
            symbols_for_tv=(),
            buy_count=0,
            cards=pd.DataFrame(),
            flow=flow if flow is not None else pd.DataFrame(),
            query_count=query_count,
            cluster_buys=pd.DataFrame(),
        )

    # Aggregate by symbol
    aggregated = (
        buys.groupby("symbol", as_index=False)
        .agg(
            latest_deal_date=("trade_date", "max"),
            buy_value_cr=("deal_value_cr", "sum"),
            buy_client_count=("client_name", "nunique"),
            inst_clients=("client_name", lambda c: ", ".join(sorted(set(c))[:3])),
            tiers=("tier", lambda t: ", ".join(sorted(set(t)))),
            clientele=("clientele", lambda c: ", ".join(sorted(set(c)))),
            inst_vwap=("price", lambda p: (p * buys.loc[p.index, "quantity"]).sum() / max(buys.loc[p.index, "quantity"].sum(), 1)),
            rs_percentile=("rs_percentile", "first"),
            away_52w_high_pct=("away_52w_high_pct", "first"),
            close_price=("close_price", "first"),
            ema_200=("ema_200", "first"),
            vcp_score=("vcp_score", "first"),
            vcp_state=("vcp_state", "first"),
            market_cap_cr=("market_cap_cr", "first"),
            sector=("sector", "first"),
            industry=("industry", "first"),
        )
    )

    aggregated["market_cap_cr"] = pd.to_numeric(aggregated["market_cap_cr"], errors="coerce")
    aggregated["close_price"] = pd.to_numeric(aggregated["close_price"], errors="coerce")
    aggregated["ema_200"] = pd.to_numeric(aggregated["ema_200"], errors="coerce")
    aggregated["buy_value_cr"] = pd.to_numeric(aggregated["buy_value_cr"], errors="coerce").fillna(0)
    sell_summary = (
        enriched[enriched["side"] == "SELL"]
        .groupby("symbol", as_index=False)["deal_value_cr"]
        .sum()
        .rename(columns={"deal_value_cr": "sell_value_cr"})
    )
    aggregated = aggregated.merge(sell_summary, on="symbol", how="left")
    aggregated["sell_value_cr"] = pd.to_numeric(aggregated["sell_value_cr"], errors="coerce").fillna(0)
    aggregated["net_value_cr"] = aggregated["buy_value_cr"] - aggregated["sell_value_cr"]

    # Cost-basis comparison (% distance from institutional buy price)
    aggregated["cmp_vs_inst_entry_pct"] = np.where(
        aggregated["inst_vwap"] > 0,
        ((aggregated["close_price"] / aggregated["inst_vwap"]) - 1) * 100,
        np.nan,
    )

    # Apply market cap and 200 EMA structure gates
    filtered = aggregated[aggregated["market_cap_cr"].notna() & (aggregated["market_cap_cr"] >= min_mcap_cr)].copy()
    filtered = filtered[
        filtered["ema_200"].notna()
        & filtered["close_price"].notna()
        & (filtered["close_price"] > filtered["ema_200"])
    ]
    filtered = filtered.sort_values(["buy_value_cr", "symbol"], ascending=[False, True])

    symbols = filtered["symbol"].dropna().astype(str).str.upper().drop_duplicates().tolist()
    buy_tv = to_tv_list(symbols)
    cards = filtered.head(card_limit).copy()
    try:
        from App.market_flags import annotate, deal_when_map
    except ModuleNotFoundError:
        from market_flags import annotate, deal_when_map  # type: ignore
    when = deal_when_map(db_path)
    if not cards.empty:
        cards = annotate(cards, db_path)
        cards["deal_when"] = cards["symbol"].astype(str).str.upper().map(when)
    filtered["deal_when"] = filtered["symbol"].astype(str).str.upper().map(when)

    return DealsDeskDefault(
        as_of=as_of,
        buy_tv=buy_tv,
        symbols_for_tv=tuple(symbols),
        buy_count=len(symbols),
        cards=cards,
        flow=flow if flow is not None else pd.DataFrame(),
        query_count=query_count,
        cluster_buys=pd.DataFrame(),
        universe_label=f"₹{min_mcap_cr:,.0f} Cr+ and CMP > 200 EMA",
        filter_notes=(
            "Cards and flow use the same latest-session universe: known market cap at or above the floor, known CMP/200 EMA, and CMP above 200 EMA. "
            "Rows with missing market cap or structure values are excluded."
            if not filtered.empty
            else "No rows passed the latest-session universe gates; missing market cap or structure values are excluded."
        ),
    )


def query_deals_advanced(
    db_path: Path,
    *,
    side: str = "BUY",
    min_value_cr: float = 5.0,
    lookback_days: int = 10,
    min_mcap_cr: float = 1000.0,
    client_name: str | None = None,
    tier_filter: str | None = None,
    exclude_hft: bool | None = None,
    clientele: tuple[str, ...] | None = None,
) -> dict[str, pd.DataFrame]:
    """On-demand Advanced research queries with Institutional classification and cluster radar."""
    db_path = Path(db_path)
    lookback_days = max(1, min(60, int(lookback_days)))
    where = ["coalesce(m.market_cap_cr, 0) >= ?"]
    params: list = [min_mcap_cr]
    if side and side != "BOTH":
        where.append("d.side = ?")
        params.append(side)
    where_sql = " AND ".join(where)
    client_filter = ""
    stock_params = list(params)
    if client_name:
        client_filter = "AND d.client_name ILIKE ?"
        stock_params.append(f"%{client_name}%")

    with duckdb.connect(str(db_path), read_only=True) as db:
        raw_deals = db.execute(
            f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
            SELECT d.*, m.market_cap_cr, m.sector, m.industry
            FROM deals d
            LEFT JOIN stocks_master m USING(symbol)
            WHERE {where_sql} AND d.trade_date >= (SELECT d FROM latest) - INTERVAL {lookback_days} DAY
              {client_filter}
            ORDER BY d.trade_date DESC
            """,
            stock_params,
        ).fetchdf()

        latest_ind = db.execute(
            """
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
            SELECT symbol, close_price, ema_200, rs_percentile, vcp_score, vcp_state, away_52w_high_pct
            FROM indicators_daily, latest
            WHERE trade_date = latest.d
            """
        ).fetchdf()

    if raw_deals.empty:
        return {"clients": pd.DataFrame(), "stocks": pd.DataFrame(), "cluster": pd.DataFrame()}

    # Ensure optional columns exist
    if "price" not in raw_deals.columns:
        raw_deals["price"] = 0.0
    if "quantity" not in raw_deals.columns:
        raw_deals["quantity"] = 1.0
    if "deal_value_cr" not in raw_deals.columns:
        raw_deals["deal_value_cr"] = 0.0
    if "client_name" not in raw_deals.columns:
        raw_deals["client_name"] = ""

    # Classify all deals
    deals_classified = enrich_deals_with_tiers(raw_deals)


    if clientele is not None:
        allowed = {str(value).upper() for value in clientele}
        deals_classified = deals_classified[deals_classified["clientele"].isin(allowed)].copy()
    elif exclude_hft is True:
        deals_classified = deals_classified[~deals_classified["is_prop"]].copy()

    if tier_filter and tier_filter != "ALL":
        deals_classified = deals_classified[deals_classified["tier"].str.contains(tier_filter, case=False, na=False)].copy()

    if deals_classified.empty:
        return {"clients": pd.DataFrame(), "stocks": pd.DataFrame(), "cluster": pd.DataFrame()}

    # 1. Institutions Leaderboard
    client_symbol_dates = (
        deals_classified.groupby(["client_name", "symbol"], as_index=False)["trade_date"]
        .max()
        .rename(columns={"trade_date": "latest_symbol_date"})
    )
    symbol_lists = (
        client_symbol_dates.groupby("client_name")
        .apply(
            lambda g: ",".join(
                f"NSE:{s.replace('-', '_')}"
                for s in g.sort_values("latest_symbol_date", ascending=False)["symbol"]
            ),
            include_groups=False,
        )
        .reset_index(name="symbol_list")
    )

    clients = (
        deals_classified.groupby(["client_name", "tier", "category", "clientele"], as_index=False)
        .agg(
            deal_rows=("symbol", "count"),
            symbols=("symbol", "nunique"),
            active_days=("trade_date", "nunique"),
            latest_deal_date=("trade_date", "max"),
            buy_value_cr=("deal_value_cr", lambda v: v[deals_classified.loc[v.index, "side"] == "BUY"].sum()),
            sell_value_cr=("deal_value_cr", lambda v: v[deals_classified.loc[v.index, "side"] == "SELL"].sum()),
        )
        .merge(symbol_lists, on="client_name", how="left")
    )
    clients["net_value_cr"] = clients["buy_value_cr"] - clients["sell_value_cr"]
    clients = clients[clients["buy_value_cr"] + clients["sell_value_cr"] >= float(min_value_cr)]
    clients = clients.sort_values(["latest_deal_date", "buy_value_cr"], ascending=[False, False]).head(200).reset_index(drop=True)

    # 2. Stock Deals Grid with Cost-Basis
    stocks = (
        deals_classified.groupby("symbol", as_index=False)
        .agg(
            latest_deal_date=("trade_date", "max"),
            buy_value_cr=("deal_value_cr", lambda v: v[deals_classified.loc[v.index, "side"] == "BUY"].sum()),
            sell_value_cr=("deal_value_cr", lambda v: v[deals_classified.loc[v.index, "side"] == "SELL"].sum()),
            buy_client_count=("client_name", lambda c: c[deals_classified.loc[c.index, "side"] == "BUY"].nunique()),
            inst_vwap=("price", lambda p: (p[deals_classified.loc[p.index, "side"] == "BUY"] * deals_classified.loc[p.index, "quantity"][deals_classified.loc[p.index, "side"] == "BUY"]).sum() / max(deals_classified.loc[p.index, "quantity"][deals_classified.loc[p.index, "side"] == "BUY"].sum(), 1)),
            market_cap_cr=("market_cap_cr", "first"),
            industry=("industry", "first"),
            sector=("sector", "first"),
        )
    )
    stocks["net_value_cr"] = stocks["buy_value_cr"] - stocks["sell_value_cr"]
    stocks = stocks.merge(latest_ind, on="symbol", how="left")
    stocks["close_price"] = pd.to_numeric(stocks["close_price"], errors="coerce")
    stocks["cmp_vs_inst_entry_pct"] = np.where(
        stocks["inst_vwap"] > 0,
        ((stocks["close_price"] / stocks["inst_vwap"]) - 1) * 100,
        np.nan,
    )
    stocks = stocks[stocks["buy_value_cr"].abs() + stocks["sell_value_cr"].abs() >= float(min_value_cr)]
    stocks = stocks.sort_values(["latest_deal_date", "buy_value_cr"], ascending=[False, False]).head(200).reset_index(drop=True)
    try:
        from App.market_flags import annotate, deal_when_map
    except ModuleNotFoundError:
        from market_flags import annotate, deal_when_map  # type: ignore
    when = deal_when_map(db_path, lookback_days=max(lookback_days, 30))
    if not stocks.empty:
        stocks = annotate(stocks, db_path)
        stocks["deal_when"] = stocks["symbol"].astype(str).str.upper().map(when)

    # 3. Cluster Buying Radar
    cluster = get_cluster_buys(deals_classified, lookback_days=lookback_days, min_institutions=2)
    try:
        from App.market_flags import annotate, deal_when_map
    except ModuleNotFoundError:
        from market_flags import annotate, deal_when_map  # type: ignore
    when = deal_when_map(db_path, lookback_days=max(lookback_days, 30))
    if not cluster.empty:
        cluster = cluster.merge(latest_ind, on="symbol", how="left")
        cluster = annotate(cluster, db_path)
        cluster["deal_when"] = cluster["symbol"].astype(str).str.upper().map(when)
        cluster["close_price"] = pd.to_numeric(cluster["close_price"], errors="coerce")
        cluster["cmp_vs_inst_entry_pct"] = np.where(
            cluster["avg_buy_price"] > 0,
            ((cluster["close_price"] / cluster["avg_buy_price"]) - 1) * 100,
            np.nan,
        )

    return {"clients": clients, "stocks": stocks, "cluster": cluster}


__all__ = ["DealsDeskDefault", "query_deals_advanced", "query_deals_desk_default"]
