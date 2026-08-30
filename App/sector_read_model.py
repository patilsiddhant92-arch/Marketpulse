"""Sector Intel 2.0 Read Model — Clear Sector Leadership, 'Why Focus' Rationale, and Stage-2 Radar."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
import duckdb
import numpy as np
import pandas as pd


LEVEL_COLUMNS = {
    "Sector": "sector",
    "Broad Sector": "broad_sector",
    "Broad Industry": "broad_industry",
    "Industry": "industry",
}

TAXONOMY_LEVELS: tuple[tuple[str, str], ...] = (
    ("Broad Sector", "broad_sector"),
    ("Sector", "sector"),
    ("Broad Industry", "broad_industry"),
    ("Industry", "industry"),
)


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _copy_tree_node(node: dict[str, Any]) -> dict[str, Any]:
    copy = {key: value for key, value in node.items() if key != "children"}
    copy["children"] = [_copy_tree_node(child) for child in node.get("children", [])]
    return copy


def build_taxonomy_tree(
    paths: pd.DataFrame,
    metrics: pd.DataFrame,
    *,
    min_stock_mcap: float = 0.0,
) -> list[dict[str, Any]]:
    """Build the strict NSE taxonomy hierarchy with stock leaves.

    The hierarchy is intentionally fixed to Broad Sector → Sector → Broad
    Industry → Industry → Stock. Group metrics are attached by level/name so
    the UI can render status and relative-strength context without more reads.
    """
    if paths.empty:
        return []

    required = [column for _, column in TAXONOMY_LEVELS]
    if any(column not in paths.columns for column in required):
        return []

    frame = paths.copy()
    for column in (*required, "symbol"):
        if column not in frame.columns:
            frame[column] = ""
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    frame = frame[(frame[required] != "").all(axis=1) & frame["symbol"].ne("")].copy()
    if frame.empty:
        return []

    metric_map: dict[tuple[str, str], dict[str, Any]] = {}
    if not metrics.empty and {"level", "group_name"}.issubset(metrics.columns):
        for _, row in metrics.iterrows():
            level = str(row.get("level") or "").strip()
            name = str(row.get("group_name") or "").strip()
            if level and name:
                metric_map[(level, name)] = row.to_dict()

    def eligible_stocks(group: pd.DataFrame) -> pd.DataFrame:
        market_caps = pd.to_numeric(group.get("market_cap_cr"), errors="coerce").fillna(0.0)
        return group[market_caps >= float(min_stock_mcap)]

    def stock_nodes(group: pd.DataFrame, parent_name: str) -> list[dict[str, Any]]:
        stocks: list[dict[str, Any]] = []
        candidates = eligible_stocks(group)
        for _, row in candidates.sort_values("symbol").drop_duplicates("symbol").iterrows():
            symbol = str(row["symbol"])
            security_name = str(row.get("security_name") or symbol)
            market_cap = _safe_number(row.get("market_cap_cr"))
            stocks.append(
                {
                    "id": f"Stock|{symbol}",
                    "level": "Stock",
                    "name": symbol,
                    "label": f"{symbol} · {security_name}",
                    "parent_name": parent_name,
                    "rotation_state": "",
                    "rs_percentile": 0.0,
                    "rotation_rank": 0,
                    "stock_count": 1,
                    "market_cap_cr": market_cap,
                    "security_name": security_name,
                    "children": [],
                }
            )
        return stocks

    def group_nodes(group: pd.DataFrame, depth: int, parent_name: str = "") -> list[dict[str, Any]]:
        level, column = TAXONOMY_LEVELS[depth]
        nodes: list[dict[str, Any]] = []
        for name in sorted(group[column].dropna().astype(str).unique(), key=str.casefold):
            child_frame = group[group[column] == name]
            metric = metric_map.get((level, name), {})
            if depth + 1 < len(TAXONOMY_LEVELS):
                children = group_nodes(child_frame, depth + 1, name)
            else:
                children = stock_nodes(child_frame, name)
            nodes.append(
                {
                    "id": f"{level}|{name}",
                    "level": level,
                    "name": name,
                    "label": name,
                    "parent_name": parent_name,
                    "rotation_state": str(metric.get("rotation_state") or "Neutral"),
                    "rs_percentile": _safe_number(metric.get("rs_percentile")),
                    "rotation_rank": int(_safe_number(metric.get("rotation_rank"))),
                    "stock_count": int(child_frame["symbol"].nunique()),
                    "eligible_stock_count": int(eligible_stocks(child_frame)["symbol"].nunique()),
                    "children": children,
                }
            )
        return nodes

    return group_nodes(frame, 0)


def filter_taxonomy_tree(
    nodes: list[dict[str, Any]],
    *,
    statuses: set[str] | None = None,
    search: str = "",
    level: str | None = None,
    status_mode: str = "branch",
) -> list[dict[str, Any]]:
    """Filter a taxonomy tree while preserving the path to every match.

    ``status_mode='branch'`` matches a status at any non-stock level and keeps
    that complete subtree. ``status_mode='strict'`` evaluates only the
    selected level, so a Broad Sector match cannot make unrelated Sector
    statuses appear to match.
    """
    clean_statuses = {str(value).strip() for value in (statuses or set()) if str(value).strip()}
    mode = str(status_mode or "branch").strip().lower()
    strict = mode == "strict"

    def by_status(node: dict[str, Any]) -> dict[str, Any] | None:
        if not clean_statuses:
            return _copy_tree_node(node)
        level_matches = level is None or node.get("level") == level
        node_matches = node.get("level") != "Stock" and node.get("rotation_state") in clean_statuses
        if node_matches and (level_matches or not strict):
            return _copy_tree_node(node)
        children = [child for item in node.get("children", []) if (child := by_status(item)) is not None]
        if not children:
            return None
        copy = {key: value for key, value in node.items() if key != "children"}
        copy["children"] = children
        return copy

    status_filtered = [copy for node in nodes if (copy := by_status(node)) is not None]
    query = search.strip().casefold()
    if not query:
        return status_filtered

    def by_search(node: dict[str, Any]) -> dict[str, Any] | None:
        searchable = " ".join(
            str(node.get(key) or "") for key in ("name", "label", "security_name")
        ).casefold()
        if query in searchable:
            return _copy_tree_node(node)
        children = [child for item in node.get("children", []) if (child := by_search(item)) is not None]
        if not children:
            return None
        copy = {key: value for key, value in node.items() if key != "children"}
        copy["children"] = children
        return copy

    return [copy for node in status_filtered if (copy := by_search(node)) is not None]


def query_sector_data_contract(db_path: Path) -> dict[str, Any]:
    """Report whether the computed taxonomy metrics contract is materialized."""

    result: dict[str, Any] = {
        "metrics_available": False,
        "metrics_table_exists": False,
        "rotation_available": False,
        "metrics_date": None,
        "rotation_date": None,
        "degraded": True,
    }
    db_path = Path(db_path)
    if not db_path.exists():
        return result
    try:
        with duckdb.connect(str(db_path), read_only=True) as db:
            tables = {str(row[0]) for row in db.execute("SHOW TABLES").fetchall()}
            result["metrics_table_exists"] = "sector_metrics_daily" in tables
            result["rotation_available"] = "sector_rotation" in tables
            if result["metrics_table_exists"]:
                result["metrics_date"] = db.execute("SELECT max(trade_date) FROM sector_metrics_daily").fetchone()[0]
            if result["rotation_available"]:
                result["rotation_date"] = db.execute("SELECT max(trade_date) FROM sector_rotation").fetchone()[0]
            result["metrics_available"] = bool(result["metrics_table_exists"] and result["metrics_date"] is not None)
            result["degraded"] = not result["metrics_available"]
    except duckdb.Error:
        result["degraded"] = True
    return result


def query_taxonomy_hierarchy(db_path: Path, min_mcap: float = 1_000.0) -> list[dict[str, Any]]:
    """Read the current NSE hierarchy and attach the latest rotation metrics."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []

    with duckdb.connect(str(db_path), read_only=True) as db:
        master_exists = db.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'stocks_master'"
        ).fetchone()[0]
        if not master_exists:
            return []
        paths = db.execute(
            """
            SELECT symbol, security_name, market_cap_cr,
                   broad_sector, sector, broad_industry, industry
            FROM stocks_master
            WHERE nullif(trim(broad_sector), '') IS NOT NULL
              AND nullif(trim(sector), '') IS NOT NULL
              AND nullif(trim(broad_industry), '') IS NOT NULL
              AND nullif(trim(industry), '') IS NOT NULL
            """
        ).fetchdf()

        computed_table_exists = db.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'sector_metrics_daily'"
        ).fetchone()[0]
        computed_exists = bool(
            computed_table_exists
            and db.execute("SELECT max(trade_date) FROM sector_metrics_daily").fetchone()[0] is not None
        )
        rotation_exists = db.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'sector_rotation'"
        ).fetchone()[0]
        metric_frames: list[pd.DataFrame] = []
        if computed_exists:
            for level, _ in TAXONOMY_LEVELS:
                overview = _computed_sector_overview(db, level)
                if overview is not None and not overview["leaderboard"].empty:
                    metric_frames.append(overview["leaderboard"])
        elif rotation_exists:
            latest = db.execute("SELECT max(trade_date) FROM sector_rotation").fetchone()[0]
            if latest is not None:
                metric_frames.append(
                    db.execute("SELECT * FROM sector_rotation WHERE trade_date = ?", [latest]).fetchdf()
                )

    metrics = pd.concat(metric_frames, ignore_index=True) if metric_frames else pd.DataFrame()
    return build_taxonomy_tree(paths, metrics, min_stock_mcap=float(min_mcap))


def _build_why_focus(row: pd.Series | dict[str, Any]) -> str:
    """Generate a crisp, plain-English rationale for why a sector is actionable."""
    reasons = []
    rank_chg = float(row.get("rank_change_5d") or 0.0)
    rs = float(row.get("rs_percentile") or 0.0)
    ret_1m = float(row.get("return_1m_pct") or 0.0)
    above_50 = float(row.get("above_50ema_pct") or 0.0)
    turnover_exp = float(row.get("turnover_expansion") or 1.0)
    highs = int(row.get("near_52w_highs") or 0)
    vcps = int(row.get("vcp_candidates") or 0)

    if rank_chg >= 3:
        reasons.append(f"Surging Rank (+{int(rank_chg)} in 5D)")
    elif rank_chg > 0:
        reasons.append(f"Rank +{int(rank_chg)}")

    if rs >= 60:
        reasons.append(f"High RS ({rs:.0f})")
    elif rs >= 50:
        reasons.append(f"RS {rs:.0f}")

    if ret_1m >= 4.0:
        reasons.append(f"1M Gain +{ret_1m:.1f}%")
    elif ret_1m > 0:
        reasons.append(f"1M +{ret_1m:.1f}%")
    elif ret_1m < -3.0:
        reasons.append(f"1M Lag {ret_1m:.1f}%")

    if above_50 >= 70:
        reasons.append(f"Strong Breadth ({above_50:.0f}% > 50EMA)")

    if turnover_exp >= 1.2:
        reasons.append(f"Vol Expansion {turnover_exp:.1f}x")

    if highs >= 3:
        reasons.append(f"{highs} Stocks @ 52W High")

    if vcps >= 3:
        reasons.append(f"{vcps} VCP Setups")

    return " • ".join(reasons[:4]) or "Consolidating in base"


def _computed_sector_overview(
    db: duckdb.DuckDBPyConnection,
    level: str,
    as_of: date | None = None,
) -> dict[str, Any] | None:
    """Read the new computed taxonomy metrics, with the old UI shape."""
    exists = db.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'sector_metrics_daily'"
    ).fetchone()[0]
    if not exists:
        return None

    params: list[Any] = [level]
    date_filter = ""
    if as_of is not None:
        date_filter = " AND trade_date = ?"
        params.append(as_of)
    else:
        latest = db.execute("SELECT max(trade_date) FROM sector_metrics_daily WHERE level = ?", [level]).fetchone()[0]
        if latest is None:
            return None
        date_filter = " AND trade_date = ?"
        params.append(latest)
    frame = db.execute(
        f"SELECT * FROM sector_metrics_daily WHERE level = ?{date_filter} ORDER BY group_name",
        params,
    ).fetchdf()
    if frame.empty:
        return None

    frame["rs_percentile"] = frame["rs_vs_nifty_63d"].rank(pct=True) * 100
    frame["return_5d_pct"] = 0.0
    frame["return_1m_pct"] = frame["rs_vs_nifty_21d"]
    frame["return_3m_pct"] = frame["rs_vs_nifty_63d"]
    frame["above_50ema_pct"] = frame["breadth_50"]
    frame["above_200ema_pct"] = frame["breadth_200"]
    frame["near_52w_highs"] = (frame["near_52w_pct"] * frame["stock_count"] / 100).round().fillna(0).astype(int)
    frame["vcp_candidates"] = frame["tech_pass_n"].fillna(0).astype(int)
    frame["turnover_1d_cr"] = frame["adv_total_cr"].fillna(0)
    frame["turnover_5d_cr"] = frame["turnover_1d_cr"]
    frame["turnover_20d_cr"] = frame["turnover_1d_cr"]
    frame["turnover_expansion"] = 1.0
    frame["rotation_score"] = (
        frame["rs_percentile"].fillna(0) * 0.40
        + frame["breadth_50"].fillna(0) * 0.30
        + frame["breadth_200"].fillna(0) * 0.20
        + frame["rs_vs_nifty_21d"].fillna(0).clip(-20, 20) * 0.50
    )
    frame["rotation_rank"] = frame["rotation_score"].rank(ascending=False, method="min")
    frame["rank_change_5d"] = 0
    frame["score_change_5d"] = 0.0
    frame["rotation_state"] = np.select(
        [frame["rotation_rank"] <= 5, frame["rotation_rank"] <= 10],
        ["Leading", "Improving"],
        default="Lagging",
    )
    frame["near_52w_highs"] = frame["near_52w_highs"].fillna(0).astype(int)
    frame["why_focus"] = frame.apply(_build_why_focus, axis=1)
    total_adv = frame["turnover_1d_cr"].sum()
    frame["turnover_share_pct"] = np.where(total_adv > 0, frame["turnover_1d_cr"] / total_adv * 100, 0)
    frame["top_leaders"] = ""
    frame["leader_symbols"] = ""

    quadrants: dict[str, list[dict[str, Any]]] = {"Leading": [], "Improving": [], "Weakening": [], "Lagging": []}
    top_focus: list[dict[str, Any]] = []
    for _, row in frame.sort_values("rotation_rank").iterrows():
        state = str(row["rotation_state"])
        item = row.to_dict()
        item.update({"status_badge": state.upper(), "status_color": "emerald" if state == "Leading" else "blue" if state == "Improving" else "slate"})
        quadrants["Leading" if state == "Leading" else "Improving" if state == "Improving" else "Lagging"].append(item)
        if len(top_focus) < 4:
            top_focus.append(item)

    return {
        "as_of": str(pd.to_datetime(frame["trade_date"].iloc[0]).date()),
        "top_focus": top_focus,
        "leaderboard": frame,
        "heatmap": frame,
        "quadrants": quadrants,
        "total": len(frame),
    }


def query_sector_rotation_overview(
    db_path: Path,
    level: str = "Sector",
    as_of: date | None = None,
) -> dict[str, Any]:
    """Fetch high-performance sector rotation overview, actionable focus cards, and full leaderboard."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {
            "as_of": None,
            "top_focus": [],
            "leaderboard": pd.DataFrame(),
            "heatmap": pd.DataFrame(),
            "quadrants": {"Leading": [], "Improving": [], "Weakening": [], "Lagging": []},
            "total": 0,
        }

    col = LEVEL_COLUMNS.get(level, "sector")

    with duckdb.connect(str(db_path), read_only=True) as db:
        computed = _computed_sector_overview(db, level, as_of)
        if computed is not None:
            return computed

        # Check if table exists
        exists = db.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'sector_rotation'").fetchone()[0]
        if not exists:
            return {
                "as_of": None,
                "top_focus": [],
                "leaderboard": pd.DataFrame(),
                "heatmap": pd.DataFrame(),
                "quadrants": {"Leading": [], "Improving": [], "Weakening": [], "Lagging": []},
                "total": 0,
            }

        # 1. Latest trade date
        if as_of:
            target_date_sql = "SELECT ?"
            params = [as_of]
        else:
            target_date_sql = "SELECT max(trade_date) FROM sector_rotation WHERE level = ?"
            params = [level]

        latest_d = db.execute(target_date_sql, params).fetchone()[0]
        if latest_d is None:
            return {
                "as_of": None,
                "top_focus": [],
                "leaderboard": pd.DataFrame(),
                "heatmap": pd.DataFrame(),
                "quadrants": {"Leading": [], "Improving": [], "Weakening": [], "Lagging": []},
                "total": 0,
            }


        as_of_str = str(pd.to_datetime(latest_d).date())

        # 2. Sector rotation records for latest date
        rot_sql = """
        SELECT r.*,
               coalesce(r.turnover_5d_cr / NULLIF(r.turnover_20d_cr / 4, 0), 1.0) AS turnover_expansion
        FROM sector_rotation r
        WHERE r.level = ? AND r.trade_date = ?
        ORDER BY r.rotation_rank ASC NULLS LAST, r.rotation_score DESC NULLS LAST
        """
        rot_df = db.execute(rot_sql, [level, latest_d]).fetchdf()

        if rot_df.empty:
            return {
                "as_of": as_of_str,
                "top_focus": [],
                "leaderboard": pd.DataFrame(),
                "quadrants": {"Leading": [], "Improving": [], "Weakening": [], "Lagging": []},
                "total": 0,
            }

        # 3. Top 3 leader stocks per group
        leaders_sql = f"""
        WITH top_stocks AS (
            SELECT m.{col} AS group_name, i.symbol, i.rs_percentile, i.close_price, i.return_1m_pct,
                   ROW_NUMBER() OVER (PARTITION BY m.{col} ORDER BY i.rs_percentile DESC NULLS LAST, i.turnover_cr DESC NULLS LAST) AS rn
            FROM indicators_daily i
            JOIN stocks_master m ON m.symbol = i.symbol
            WHERE i.trade_date = ? AND m.{col} IS NOT NULL AND m.{col} <> ''
        )
        SELECT group_name,
               string_agg(symbol, ', ') AS top_leaders,
               string_agg(symbol, ' ') AS leader_symbols
        FROM top_stocks
        WHERE rn <= 3
        GROUP BY group_name
        """
        try:
            leaders_df = db.execute(leaders_sql, [latest_d]).fetchdf()
        except duckdb.Error:
            leaders_df = pd.DataFrame(columns=["group_name", "top_leaders", "leader_symbols"])

    # Merge top leaders onto rot_df
    if not leaders_df.empty:
        rot_df = rot_df.merge(leaders_df, on="group_name", how="left")
    else:
        rot_df["top_leaders"] = ""
        rot_df["leader_symbols"] = ""

    # Calculate turnover share %
    total_turnover = rot_df["turnover_1d_cr"].sum()
    if total_turnover > 0:
        rot_df["turnover_share_pct"] = (rot_df["turnover_1d_cr"] / total_turnover) * 100.0
    else:
        rot_df["turnover_share_pct"] = 0.0

    # Build 'why_focus' column
    rot_df["why_focus"] = rot_df.apply(_build_why_focus, axis=1)

    # Classify Actionable Status & Quadrants
    quadrants: dict[str, list[dict[str, Any]]] = {
        "Leading": [],
        "Improving": [],
        "Weakening": [],
        "Lagging": [],
    }

    top_focus_list: list[dict[str, Any]] = []

    for _, row in rot_df.iterrows():
        state = str(row.get("rotation_state") or "Neutral")
        rank = int(row.get("rotation_rank") or 99)
        rank_chg = float(row.get("rank_change_5d") or 0.0)
        rs = float(row.get("rs_percentile") or 0.0)
        score_chg = float(row.get("score_change_5d") or 0.0)

        # Status Badge determination
        if rank_chg >= 3 and rank <= 12:
            status_badge = "MOMENTUM SURGE"
            status_color = "blue"
        elif rank <= 4 and rs >= 55:
            status_badge = "TOP FOCUS"
            status_color = "emerald"
        elif state in ("Leading", "Emerging", "Improving"):
            status_badge = state.upper()
            status_color = "emerald" if state == "Leading" else "blue"
        elif state == "Weakening" or (rank <= 8 and score_chg < 0):
            status_badge = "WEAKENING"
            status_color = "amber"
        else:
            status_badge = "LAGGING"
            status_color = "slate"

        item = {
            "group_name": str(row["group_name"]),
            "status_badge": status_badge,
            "status_color": status_color,
            "rotation_state": state,
            "rotation_rank": rank,
            "rank_change_5d": rank_chg,
            "rotation_score": float(row.get("rotation_score") or 0.0),
            "score_change_5d": score_chg,
            "rs_percentile": rs,
            "return_1d_pct": float(row.get("return_1d_pct") or 0.0) if "return_1d_pct" in row else 0.0,
            "return_5d_pct": float(row.get("return_5d_pct") or 0.0),
            "return_1m_pct": float(row.get("return_1m_pct") or 0.0),
            "return_3m_pct": float(row.get("return_3m_pct") or 0.0),
            "above_50ema_pct": float(row.get("above_50ema_pct") or 0.0),
            "above_200ema_pct": float(row.get("above_200ema_pct") or 0.0),
            "near_52w_highs": int(row.get("near_52w_highs") or 0),
            "vcp_candidates": int(row.get("vcp_candidates") or 0),
            "turnover_1d_cr": float(row.get("turnover_1d_cr") or 0.0),
            "turnover_share_pct": float(row.get("turnover_share_pct") or 0.0),
            "turnover_expansion": float(row.get("turnover_expansion") or 1.0),
            "top_leaders": str(row.get("top_leaders") or ""),
            "leader_symbols": str(row.get("leader_symbols") or ""),
            "stocks_count": int(row.get("stocks") or 0),
            "why_focus": str(row.get("why_focus") or ""),
        }

        # Quadrant placement
        if state == "Leading" or (rank <= 5 and rs >= 55):
            quadrants["Leading"].append(item)
        elif state in ("Emerging", "Improving") or (rank_chg >= 3 and rank > 5):
            quadrants["Improving"].append(item)
        elif state == "Weakening" or (rank <= 8 and score_chg < 0):
            quadrants["Weakening"].append(item)
        else:
            quadrants["Lagging"].append(item)

        # High-Conviction Top Focus Cards (Top 4 ranked or surging)
        if len(top_focus_list) < 4 and (rank <= 4 or rank_chg >= 4):
            top_focus_list.append(item)

    # If top_focus_list has fewer than 3, fill from top ranked
    if len(top_focus_list) < 3:
        for item in quadrants["Leading"] + quadrants["Improving"] + quadrants["Weakening"]:
            if item not in top_focus_list:
                top_focus_list.append(item)
            if len(top_focus_list) >= 4:
                break

    return {
        "as_of": as_of_str,
        "top_focus": top_focus_list,
        "leaderboard": rot_df,
        "heatmap": rot_df,
        "quadrants": quadrants,
        "total": len(rot_df),
    }



def query_sector_deep_dive(
    db_path: Path,
    level: str,
    group_name: str,
    min_mcap: float = 1000.0,
    limit: int = 25,
) -> dict[str, Any]:
    """Fetch top Stage-2 breakout leader stocks, candidate setups, and sub-industry breakdown for a sector."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"group_stats": {}, "stocks": pd.DataFrame(), "sub_industries": pd.DataFrame()}

    col = LEVEL_COLUMNS.get(level, "sector")
    clean_group = str(group_name).strip()

    with duckdb.connect(str(db_path), read_only=True) as db:
        # 1. Latest trade date
        max_d = db.execute("SELECT max(trade_date) FROM indicators_daily").fetchone()[0]
        if max_d is None:
            return {"group_stats": {}, "stocks": pd.DataFrame(), "sub_industries": pd.DataFrame()}

        # 2. Sector summary record
        stat_row = db.execute(
            """
            SELECT * FROM sector_rotation
            WHERE level = ? AND group_name = ? AND trade_date = (SELECT max(trade_date) FROM sector_rotation WHERE level = ?)
            LIMIT 1
            """,
            [level, clean_group, level],
        ).fetchdf()
        group_stats = stat_row.iloc[0].to_dict() if not stat_row.empty else {"group_name": clean_group}

        # 3. Top Stage-2 Breakout Leaders
        stocks_sql = f"""
        WITH latest AS (
            SELECT max(trade_date) AS d FROM indicators_daily
        ),
        cand AS (
            SELECT symbol, candidate_state, total_score, trigger_price, invalidation_price, first_resistance, reward_to_risk, why_now
            FROM candidate_daily
            WHERE trade_date = (SELECT max(trade_date) FROM candidate_daily)
        )
        SELECT i.symbol,
               coalesce(m.security_name, i.symbol) AS security_name,
               m.industry,
               m.broad_industry,
               coalesce(m.market_cap_cr, 0) AS market_cap_cr,
               i.close_price,
               i.return_5d_pct,
               i.return_1m_pct,
               i.return_3m_pct,
               i.rs_percentile,
               coalesce(i.rvol, 1.0) AS rvol,
               i.delivery_pct,
               i.is_vcp,
               i.vcp_score,
               i.vcp_state,
               i.away_52w_high_pct,
               i.turnover_cr,
               c.candidate_state,
               c.total_score AS candidate_score,
               c.trigger_price,
               c.invalidation_price AS stop_loss,
               c.first_resistance AS target_price,
               c.reward_to_risk,
               c.why_now
        FROM indicators_daily i
        JOIN latest l ON i.trade_date = l.d
        JOIN stocks_master m ON m.symbol = i.symbol
        LEFT JOIN cand c ON c.symbol = i.symbol
        WHERE m.{col} = ?
          AND coalesce(m.market_cap_cr, 0) >= ?
        ORDER BY i.rs_percentile DESC NULLS LAST, i.turnover_cr DESC NULLS LAST
        LIMIT ?
        """

        try:
            stocks_df = db.execute(stocks_sql, [clean_group, float(min_mcap), int(limit)]).fetchdf()
        except duckdb.Error:
            stocks_df = pd.DataFrame()

        # 4. Sub-industry distribution if at Sector / Broad Sector level
        if level in ("Broad Sector", "Sector"):
            child_col = "industry" if level == "Sector" else "sector"
            sub_sql = f"""
            WITH latest AS (SELECT max(trade_date) d FROM indicators_daily)
            SELECT m.{child_col} AS sub_group,
                   count(DISTINCT i.symbol) AS stock_count,
                   avg(i.rs_percentile) AS avg_rs,
                   avg(i.return_1m_pct) AS avg_1m_ret,
                   sum(i.turnover_cr) AS total_turnover_cr
            FROM indicators_daily i
            JOIN latest l ON i.trade_date = l.d
            JOIN stocks_master m ON m.symbol = i.symbol
            WHERE m.{col} = ?
            GROUP BY 1
            ORDER BY avg_rs DESC NULLS LAST
            """
            try:
                sub_df = db.execute(sub_sql, [clean_group]).fetchdf()
            except duckdb.Error:
                sub_df = pd.DataFrame()
        else:
            sub_df = pd.DataFrame()

    return {
        "group_stats": group_stats,
        "stocks": stocks_df,
        "sub_industries": sub_df,
    }
