"""Canonical, explainable focused-candidate scoring."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

import numpy as np
import pandas as pd

try:
    from events import event_risk_for_date
    from decision_policy import DecisionPolicy, EligibilityResult, evaluate_candidate_eligibility
except ModuleNotFoundError:
    from Scripts.events import event_risk_for_date
    from Scripts.decision_policy import DecisionPolicy, EligibilityResult, evaluate_candidate_eligibility


SCORE_VERSION = "focused-v2"
MAX_REWARD_TO_RISK = 10.0
PILLAR_WEIGHTS = {"leadership": 0.30, "setup": 0.25, "participation": 0.20, "context": 0.15, "risk": 0.10}
OUTPUT_COLUMNS = [
    "trade_date", "symbol", "score_version", "candidate_state", "leadership_score", "setup_score", "participation_score", "context_score", "risk_score", "total_score", "rank_overall", "rank_in_sector", "why_now", "latest_change", "risk_summary", "trigger_price", "invalidation_price", "first_resistance", "distance_to_trigger_pct", "initial_risk_pct", "reward_to_risk", "setup_first_seen", "setup_age_sessions", "event_risk", "data_quality_flags", "trigger_type", "invalidation_type", "market_regime", "sector_state", "industry_state", "market_cap_cr", "avg_traded_value_cr_20d", "sector", "industry", "eligibility_status", "blocking_reasons", "warning_reasons", "geometry_valid", "geometry_warning"
]


def _num(row: Mapping[str, Any], name: str, default=np.nan) -> float:
    value = row.get(name, default)
    try:
        return float(value) if pd.notna(value) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _score(value: Any, default=50.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return float(np.clip(value, 0, 100)) if np.isfinite(value) else default


def _mean_scores(values, default=50.0) -> float:
    clean = [_score(value, np.nan) for value in values]
    clean = [value for value in clean if np.isfinite(value)]
    return round(float(np.mean(clean)) if clean else default, 6)


def calculate_risk_geometry(row: Mapping[str, Any]) -> dict:
    close = _num(row, "close_price")
    if not np.isfinite(close) or close <= 0:
        return {key: np.nan for key in ("trigger_price", "invalidation_price", "first_resistance", "distance_to_trigger_pct", "initial_risk_pct", "reward_to_risk")} | {"geometry_valid": False, "geometry_warning": "close_missing"}
    pivot = _num(row, "pivot_price", np.nan)
    if not np.isfinite(pivot):
        pivot = _num(row, "high_20d", np.nan)
    if not np.isfinite(pivot) or pivot <= close:
        return {key: np.nan for key in ("trigger_price", "invalidation_price", "first_resistance", "distance_to_trigger_pct", "initial_risk_pct", "reward_to_risk")} | {"geometry_valid": False, "geometry_warning": "pivot_missing"}
    support_candidates = [_num(row, name, np.nan) for name in ("ema_20", "ema_50", "low_10d", "low_20d")]
    support_candidates = [value for value in support_candidates if np.isfinite(value) and value > 0]
    if not support_candidates:
        return {key: np.nan for key in ("trigger_price", "invalidation_price", "first_resistance", "distance_to_trigger_pct", "initial_risk_pct", "reward_to_risk")} | {"geometry_valid": False, "geometry_warning": "support_missing"}
    invalidation = max(support_candidates)
    if invalidation >= pivot:
        invalidation = min(close * 0.98, pivot * 0.98)
    resistance_candidates = [_num(row, name, np.nan) for name in ("first_resistance", "high_50d", "high_100d", "high_252d")]
    resistance_candidates = [value for value in resistance_candidates if np.isfinite(value) and value > pivot]
    if not resistance_candidates:
        return {key: np.nan for key in ("trigger_price", "invalidation_price", "first_resistance", "distance_to_trigger_pct", "initial_risk_pct", "reward_to_risk")} | {"geometry_valid": False, "geometry_warning": "resistance_missing"}
    resistance = min(resistance_candidates)
    distance = (pivot / close - 1.0) * 100
    initial_risk = (pivot / invalidation - 1.0) * 100 if invalidation > 0 else np.nan
    reward_to_risk = (resistance - pivot) / (pivot - invalidation) if pivot > invalidation else np.nan
    reward_to_risk_outlier = bool(np.isfinite(reward_to_risk) and reward_to_risk > MAX_REWARD_TO_RISK)
    return {
        "trigger_price": round(pivot, 6),
        "invalidation_price": round(invalidation, 6),
        "first_resistance": round(resistance, 6),
        "distance_to_trigger_pct": round(distance, 6),
        "initial_risk_pct": round(initial_risk, 6) if np.isfinite(initial_risk) else np.nan,
        "reward_to_risk": np.nan if reward_to_risk_outlier else (round(reward_to_risk, 6) if np.isfinite(reward_to_risk) else np.nan),
        "geometry_valid": bool(
            np.isfinite(initial_risk)
            and np.isfinite(reward_to_risk)
            and pivot > invalidation
            and not reward_to_risk_outlier
        ),
        "geometry_warning": "reward_to_risk_outlier" if reward_to_risk_outlier else "",
    }


def classify_market_gate(breadth_row: Mapping[str, Any] | pd.Series, index_rows: pd.DataFrame, rotation_rows: pd.DataFrame) -> str:
    state = str(breadth_row.get("breadth_state", "")).lower()
    advance = _num(breadth_row, "advance_pct", 50)
    above50 = _num(breadth_row, "above_50ema_pct", 50)
    above200 = _num(breadth_row, "above_200ema_pct", 50)
    trend_states = {str(value).lower() for value in (index_rows.get("trend_state", pd.Series(dtype=str)).dropna().tolist() if index_rows is not None and not index_rows.empty else [])}
    rotation_states = {str(value).lower() for value in (rotation_rows.get("rotation_state", pd.Series(dtype=str)).dropna().tolist() if rotation_rows is not None and not rotation_rows.empty else [])}
    if "risk" in state or (advance < 35 and above200 < 35) or "defensive" in trend_states and advance < 45:
        return "Risk-Off"
    if ("broad" in state or "improving" in state or advance >= 58) and above50 >= 55 and above200 >= 45 and (not trend_states or "constructive" in trend_states or "neutral" in trend_states):
        return "Constructive"
    if advance < 45 or above50 < 45 or above200 < 40:
        return "Defensive"
    if "lagging" in rotation_states and advance < 50:
        return "Defensive"
    return "Selective"


def _merge_latest(base: pd.DataFrame, other: pd.DataFrame, keys: list[str], suffix: str = "") -> pd.DataFrame:
    if other is None or other.empty:
        return base
    available = [key for key in keys if key in other.columns and key in base.columns]
    if not available:
        return base
    other = other.copy()
    other = other.drop_duplicates(available, keep="last")
    new_columns = [col for col in other.columns if col not in available and col not in base.columns]
    return base.merge(other[available + new_columns], on=available, how="left")


def _row_event(events: pd.DataFrame, row: pd.Series, as_of: pd.Timestamp, sessions) -> dict:
    try:
        return event_risk_for_date(events, row["symbol"], as_of.date(), sessions)
    except (KeyError, ValueError, TypeError):
        return {"event_risk": "none"}


def explain_candidate(row: Mapping[str, Any]) -> tuple[str, str, str]:
    reasons = []
    if _num(row, "rs_percentile", 0) >= 80:
        reasons.append("relative strength leader")
    if bool(row.get("ema_stack_bullish", False)):
        reasons.append("bullish EMA stack")
    if bool(row.get("near_52w_high", False)):
        reasons.append("near 52-week high")
    if _num(row, "rvol", 0) >= 1.5:
        reasons.append("volume confirmation")
    why_now = ", ".join(reasons[:3]) or "developing leadership/setup evidence"
    changes = []
    if bool(row.get("new_20d_high", False)):
        changes.append("new 20-day high")
    if bool(row.get("delivery_spike", False)):
        changes.append("delivery expansion")
    latest_change = ", ".join(changes) or "no major one-session change"
    risks = []
    if _num(row, "atr_pct_primary", _num(row, "atr_pct", 0)) >= 8:
        risks.append("high ATR")
    if row.get("event_risk") in {"high", "warn"}:
        risks.append(f"{row['event_risk']} event risk")
    if not np.isfinite(_num(row, "reward_to_risk", np.nan)) or _num(row, "reward_to_risk", 0) <= 1:
        risks.append("limited reward-to-risk")
    return why_now, latest_change, ", ".join(risks) or "no elevated risk flags"


def score_candidates(indicators: pd.DataFrame, breadth: pd.DataFrame, rotations: pd.DataFrame, deals: pd.DataFrame, index_features: pd.DataFrame, events: pd.DataFrame, master: pd.DataFrame, as_of: date | pd.Timestamp, policy: DecisionPolicy | None = None) -> pd.DataFrame:
    policy = policy or DecisionPolicy()
    if indicators is None or indicators.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    as_of = pd.Timestamp(as_of).normalize()
    rows = indicators[pd.to_datetime(indicators["trade_date"]).dt.normalize() == as_of].copy()
    if rows.empty:
        rows = indicators[pd.to_datetime(indicators["trade_date"]).dt.normalize() <= as_of].sort_values("trade_date").groupby("symbol", as_index=False).tail(1).copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.normalize()
    if master is not None and not master.empty:
        master_cols = [col for col in ["symbol", "market_cap_cr", "sector", "industry", "broad_sector", "broad_industry", "band"] if col in master.columns]
        rows = rows.merge(master[master_cols].drop_duplicates("symbol"), on="symbol", how="left", suffixes=("", "_master"))
        for col in ("sector", "industry", "market_cap_cr", "band"):
            if f"{col}_master" in rows.columns:
                rows[col] = rows[col].fillna(rows[f"{col}_master"])
    try:
        from institutional_engine import compute_stock_deal_metrics
    except ModuleNotFoundError:
        from Scripts.institutional_engine import compute_stock_deal_metrics

    # Compute actual normalized deal activity if deals exist
    if deals is not None and not deals.empty:
        deal_metrics = compute_stock_deal_metrics(deals, rows, as_of=as_of)
        if not deal_metrics.empty and "normalized_deal_activity" in deal_metrics.columns:
            deal_cols = [c for c in ["symbol", "normalized_deal_activity", "is_cluster_buy"] if c in deal_metrics.columns]
            rows = rows.merge(deal_metrics[deal_cols].drop_duplicates("symbol"), on="symbol", how="left")

    breadth_row = breadth[pd.to_datetime(breadth["trade_date"]).dt.normalize() <= as_of].sort_values("trade_date").tail(1).iloc[0] if breadth is not None and not breadth.empty else pd.Series()
    index_today = index_features[pd.to_datetime(index_features["trade_date"]).dt.normalize() <= as_of].sort_values("trade_date").groupby("index_name", as_index=False).tail(1) if index_features is not None and not index_features.empty else pd.DataFrame()
    rotation_today = rotations[pd.to_datetime(rotations["trade_date"]).dt.normalize() <= as_of].sort_values("trade_date").groupby([col for col in ["level", "group_name"] if col in rotations.columns], as_index=False).tail(1) if rotations is not None and not rotations.empty else pd.DataFrame()
    market_regime = classify_market_gate(breadth_row, index_today, rotation_today)
    gate_score = {"Constructive": 90, "Selective": 65, "Defensive": 35, "Risk-Off": 15}[market_regime]

    # Benchmark return (Nifty 50)
    nifty_3m_ret = 0.0
    if not index_today.empty:
        nifty_match = index_today[index_today["index_name"].astype(str).str.upper().str.contains("NIFTY 50")]
        if not nifty_match.empty and "return_63d_pct" in nifty_match.columns:
            nifty_3m_ret = _num(nifty_match.iloc[0], "return_63d_pct", 0.0)

    sessions = pd.to_datetime(indicators["trade_date"], errors="coerce").dropna().drop_duplicates().sort_values().tolist()
    output = []
    for _, source in rows.iterrows():
        row = source.to_dict()
        sector = str(row.get("sector") or "")
        sector_rotation = rotation_today[(rotation_today.get("group_name", pd.Series(dtype=str)).astype(str) == sector)] if not rotation_today.empty and "group_name" in rotation_today.columns else pd.DataFrame()
        sector_state = str(sector_rotation.iloc[0].get("rotation_state", "Unknown")) if not sector_rotation.empty else "Unknown"
        sector_score = _score(sector_rotation.iloc[0].get("rotation_score", 50)) if not sector_rotation.empty else 50

        # Calculate relative strength vs benchmark and sector
        stock_3m_ret = _num(row, "return_63d_pct", _num(row, "return_3m_pct", 0.0))
        sector_3m_ret = _num(sector_rotation.iloc[0], "return_63d_pct", nifty_3m_ret) if not sector_rotation.empty else nifty_3m_ret
        benchmark_rs = stock_3m_ret - nifty_3m_ret
        sector_rs = stock_3m_ret - sector_3m_ret

        leadership = _mean_scores([
            row.get("rs_percentile"),
            row.get("rs_1y_percentile"),
            row.get("rs_3m_percentile"),
            _score(50 + benchmark_rs * 2),
            _score(50 + sector_rs * 2),
            50 + _num(row, "rank_acceleration", 0) * 2,
        ])
        setup = _mean_scores([row.get("trend_score"), row.get("contraction_score"), row.get("volume_dryup_score"), row.get("pivot_proximity_score"), 100 if bool(row.get("ema_stack_bullish", False)) else 40, 100 if bool(row.get("near_high_tight", False)) else 50])
        turnover_z = (_num(row, "turnover_cr", np.nan) / _num(row, "avg_traded_value_cr_20d", np.nan) - 1) * 20 if _num(row, "avg_traded_value_cr_20d", np.nan) > 0 else np.nan
        delivery_z = (_num(row, "delivery_pct", np.nan) - _num(row, "avg_delivery_pct_20d", np.nan)) / 5 if np.isfinite(_num(row, "avg_delivery_pct_20d", np.nan)) else np.nan
        deal_activity = _num(row, "normalized_deal_activity", 50.0)
        participation = _mean_scores([
            50 + turnover_z * 15 if np.isfinite(turnover_z) else np.nan,
            50 + delivery_z * 15 if np.isfinite(delivery_z) else np.nan,
            row.get("close_location_pct"),
            50 + (_num(row, "rvol", 1) - 1) * 25,
            deal_activity,
        ])

        context = _mean_scores([gate_score, sector_score, 70 if sector_state.lower() in {"leading", "improving"} else 40 if sector_state.lower() == "lagging" else 55])
        risk_penalty = 0
        if _num(row, "avg_traded_value_cr_20d", 100) < 10:
            risk_penalty += 20
        if _num(row, "atr_pct_primary", _num(row, "atr_pct", 0)) > 8:
            risk_penalty += 20
        geometry = calculate_risk_geometry(row)
        event = _row_event(events, pd.Series({**row, "symbol": row.get("symbol")}), as_of, sessions)
        if event.get("event_risk") == "high":
            risk_penalty += 20
        elif event.get("event_risk") == "warn":
            risk_penalty += 10
        risk_score = _score(100 - risk_penalty)
        total = round(sum(PILLAR_WEIGHTS[name] * value for name, value in (("leadership", leadership), ("setup", setup), ("participation", participation), ("context", context), ("risk", risk_score))), 6)
        row.update(geometry)
        row["event_risk"] = event.get("event_risk", "none")
        why_now, latest_change, risk_summary = explain_candidate(row)
        eligibility = evaluate_candidate_eligibility({**row, **geometry}, policy)
        valid_geometry = bool(geometry.get("geometry_valid", False))
        if not valid_geometry and "risk_geometry_missing" not in eligibility.blocking_reasons:
            eligibility = EligibilityResult(False, tuple(dict.fromkeys(("risk_geometry_missing", *eligibility.blocking_reasons))), eligibility.warning_reasons)
        if eligibility.eligible and total >= policy.min_prepare_score:
            candidate_state = "Prepare"
        elif eligibility.eligible:
            candidate_state = "Observe"
        else:
            candidate_state = "Blocked"
        if candidate_state == "Prepare" and market_regime == "Risk-Off":
            candidate_state = "Observe"
            eligibility = EligibilityResult(
                eligibility.eligible,
                eligibility.blocking_reasons,
                tuple(dict.fromkeys((*eligibility.warning_reasons, "market_regime_risk_off"))),
            )
        output.append({
            # setup_first_seen / setup_age_sessions: leave null/1 provisional.
            # Ledger + materialize apply stable identity (do not force as_of daily).
            "trade_date": as_of.date(), "symbol": row.get("symbol"), "score_version": policy.score_version, "candidate_state": candidate_state, "leadership_score": leadership, "setup_score": setup, "participation_score": participation, "context_score": context, "risk_score": risk_score, "total_score": total, "rank_overall": None, "rank_in_sector": None, "why_now": why_now, "latest_change": latest_change, "risk_summary": risk_summary, **geometry, "setup_first_seen": None, "setup_age_sessions": 1, "event_risk": row["event_risk"], "data_quality_flags": ";".join((*eligibility.blocking_reasons, *eligibility.warning_reasons)), "trigger_type": "break_above_pivot", "invalidation_type": "close_below_support", "market_regime": market_regime, "sector_state": sector_state, "industry_state": "Unknown", "market_cap_cr": row.get("market_cap_cr"), "avg_traded_value_cr_20d": row.get("avg_traded_value_cr_20d"), "sector": sector, "industry": str(row.get("industry") or ""), "eligibility_status": "eligible" if eligibility.eligible else "blocked", "blocking_reasons": ";".join(eligibility.blocking_reasons), "warning_reasons": ";".join(eligibility.warning_reasons)
        })
    result = pd.DataFrame(output, columns=OUTPUT_COLUMNS)
    if result.empty:
        return result
    result = result.sort_values(["total_score", "symbol"], ascending=[False, True]).reset_index(drop=True)
    result["rank_overall"] = range(1, len(result) + 1)
    result["rank_in_sector"] = result.groupby("sector", dropna=False)["total_score"].rank(method="first", ascending=False).astype(int)
    return result
