# Prepare threshold calibration (PR-PREP)

**Date:** 2026-08-10  
**Score version:** `focused-v2`  
**Change:** `DecisionPolicy.min_prepare_score` **65.0 → 60.0**

## Why

Live audit (2026-08-07 session):

| Fact | Value |
|------|--------|
| Eligible focused-v2 rows | 65 |
| Max total_score on eligible | ≈ **64.58** |
| Previous min_prepare_score | **65** |
| Prepare count | **0** |

With threshold 65, **no** focused-v2 name entered Prepare, so the signal ledger (which historically only ingested Prepare+) never received v2 rows, and outcomes could not resolve for the UI score version.

## Decision

Lower interim Prepare gate to **60.0** so eligible names can enter Prepare / ledger while keeping hard gates (mcap, liquidity, band, risk geometry, R:R, trigger distance) unchanged.

## Rollback

Restore `min_prepare_score = 65.0` in `Scripts/decision_policy.py` and rematerialize.

## Follow-ups

1. After multi-session backfill (`Scripts/backfill_decisions.py`) and resolved outcomes, review score distribution and consider raising threshold back toward 65.
2. Do not claim recovery release complete solely because UI defaults to focused-v2 — still require checklist gates and evidence.
