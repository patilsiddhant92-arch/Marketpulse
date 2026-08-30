"""Versioned eligibility rules for the swing-trader decision snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping


@dataclass(frozen=True)
class DecisionPolicy:
    score_version: str = "focused-v2"
    min_market_cap_cr: float = 1000.0
    min_avg_traded_value_cr_20d: float = 10.0
    min_price_band_pct: float = 10.0
    min_prepare_score: float = 60.0
    max_distance_to_trigger_pct: float = 5.0
    min_distance_to_trigger_pct: float = -2.0
    max_initial_risk_pct: float = 8.0
    min_reward_to_risk: float = 1.5
    expiry_sessions: int = 20
    block_prepare_in_risk_off: bool = True


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    blocking_reasons: tuple[str, ...] = ()
    warning_reasons: tuple[str, ...] = ()


def _number(row: Mapping[str, Any], key: str) -> float | None:
    try:
        value = float(row.get(key))
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def evaluate_candidate_eligibility(row: Mapping[str, Any], policy: DecisionPolicy | None = None) -> EligibilityResult:
    policy = policy or DecisionPolicy()
    blocking: list[str] = []
    warnings: list[str] = []

    market_cap = _number(row, "market_cap_cr")
    if market_cap is None:
        blocking.append("market_cap_missing")
    elif market_cap < policy.min_market_cap_cr:
        blocking.append("market_cap_below_minimum")

    traded_value = _number(row, "avg_traded_value_cr_20d")
    if traded_value is None:
        blocking.append("liquidity_missing")
    elif traded_value < policy.min_avg_traded_value_cr_20d:
        blocking.append("liquidity_below_minimum")

    band = _number(row, "band")
    if band is None:
        blocking.append("price_band_missing")
    elif band < policy.min_price_band_pct:
        blocking.append("price_band_too_restrictive")

    risk = _number(row, "initial_risk_pct")
    if risk is None:
        blocking.append("risk_geometry_missing")
    elif risk <= 0 or risk > policy.max_initial_risk_pct:
        blocking.append("initial_risk_too_wide")

    reward_to_risk = _number(row, "reward_to_risk")
    if reward_to_risk is None:
        blocking.append("reward_to_risk_below_minimum")
    elif reward_to_risk < policy.min_reward_to_risk:
        blocking.append("reward_to_risk_below_minimum")

    distance = _number(row, "distance_to_trigger_pct")
    if distance is None:
        blocking.append("trigger_distance_missing")
    elif distance > policy.max_distance_to_trigger_pct or distance < policy.min_distance_to_trigger_pct:
        blocking.append("trigger_too_far")

    band_remarks = str(row.get("band_remarks") or "").upper()
    if any(k in band_remarks for k in ("GSM", "STAGE 2", "STAGE 3", "STAGE 4", "ESM STAGE 2")):
        blocking.append("surveillance_gsm_asm_high")
    elif any(k in band_remarks for k in ("ASM", "ESM", "T2T", "STAGE 1")):
        warnings.append("surveillance_asm_stage1")

    event_risk = str(row.get("event_risk") or "none").lower()
    if event_risk == "high":
        warnings.append("high_event_risk")
    elif event_risk == "warn":
        warnings.append("event_risk_warning")

    return EligibilityResult(not blocking, tuple(dict.fromkeys(blocking)), tuple(dict.fromkeys(warnings)))



__all__ = ["DecisionPolicy", "EligibilityResult", "evaluate_candidate_eligibility"]
