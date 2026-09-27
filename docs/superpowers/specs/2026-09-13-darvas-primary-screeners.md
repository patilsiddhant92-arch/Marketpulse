# Darvas Primary Screeners (Approach A) — Design Spec

**Date:** 2026-09-13  
**Status:** Approved (Approach A + mcap ≥ ₹1000 Cr)  
**Repo:** MarketPulse2.0 @ `D:\Sid\MarketPulse2.0`  
**Branch:** continue from `feat/truth-contract` (or cut `feat/darvas-primary` if cleaner)

## Goal

Make Action Desk primary setups **honest Darvas coils**:

1. **Darvas Squeeze** (tighten existing) — price coiling under TopBox into a **rising** 10 EMA, dry/shallow volume.
2. **Darvas 10 EMA** (new sibling) — post-thrust setups with flavor chips **Pullback** | **Catch-up**.

Demote all other AD queues to **More setups** (do not delete this cut).

Out of scope: morning playbook strip, deleting demoted queues, UC predictor.

## Shared gates (both queues)

- Universe: Action Desk `setup_pool` with `POOL["min_mcap"] >= 1000` (₹ Cr) — already in `Scripts/desk_contract.py`. **Assert both queues only merge through `setup_pool`** (no bypass).
- Band / ADV gates remain as today via pool.
- No RS gate on these two (keep Darvas decoupled from RS).

## Why MAXHEALTH is wrong today (bug / honesty)

As of 2026-09-11, MAXHEALTH **qualifies** under current `squeeze_frame` / `evaluate_squeeze_bar`:

| Check | Value | Current rule |
|---|---|---|
| mcap | ~₹100,994 Cr | Passes ≥1000 |
| TopBox | 1042.1 | |
| Close | 1037.7 under top | Passes |
| 10 EMA | 1017.2 rising | Passes trend_ok |
| squeeze_pct (Top↔EMA10) | ~2.39% | ≤5% passes |
| candle_range_pct | ~1.81% | ≤4% passes |
| tightening vs 5d ago | True (3.67→2.39) | Soft rank only, not hard gate |
| **rvol** | **1.31** | **Not checked** |
| Context | Sep 9 thrust day rvol~2.29, close jumped ~993→1037 | Post-thrust hold near ceiling, not a dry coil |

**Root cause:** squeeze has no **dry/shallow volume** hard gate, and close-near-ceiling after a thrust still looks like a “tight Top↔EMA gap.”

**Regression target:** with new rules, MAXHEALTH **must not** appear in Darvas Squeeze on that session (and similar post-thrust / elevated-rvol names must fail).

## Queue 1 — Darvas Squeeze (tighten)

Hard gates on the **last session** (daily path; weekly remains behind `MP_DARVAS_WEEKLY`):

1. Close **strictly under** TopBox (`close < darvas_top`; keep existing ceiling_tol only if needed for float noise — prefer strict).
2. **10 EMA rising** vs prior session (`ema_10[t] > ema_10[t-1]`). Prefer this over 10≥20 stack-with-tol alone; keep 10 vs 20 as soft/secondary if useful.
3. Gap (TopBox − 10 EMA) / TopBox within `max_squeeze_pct` (keep 5.0 unless tests show too loose).
4. Candle range (H−L)/C within `max_range_pct` (keep 4.0).
5. **Tightening hard gate:** `squeeze_pct < squeeze_pct_5d_ago` (was soft rank only — promote).
6. **Dry / shallow volume hard gate (kills MAXHEALTH):** `rvol <= 1.0` on the signal bar (use `indicators_daily.rvol`). Optional secondary: last-3-session mean rvol ≤ 1.1 — implement if single-bar alone still lets thrust-holds through; document choice in code comment.
7. OHLC / floor rules: keep existing failed_low / wick / close floor protections from `evaluate_squeeze_bar` unless they conflict.

Display: keep setup_type `Darvas Squeeze`; why_now must mention squeeze %, range %, TopBox, and dry vol (e.g. rvol).

## Queue 2 — Darvas 10 EMA (new)

Sibling queue on Action Desk. Shared: mcap≥1000 via pool; **post-thrust** context; **dry/shallow volume** on the signal bar (`rvol <= 1.0`).

### Flavor: Pullback
- Prior thrust: within lookback (e.g. 5–10 sessions) a session with strong upside (define concretely: e.g. close up ≥3% **or** rvol≥1.5 with close > prior high), then
- Price pulls back **to** rising 10 EMA: close within a small band of EMA10 (e.g. |away_10ema_pct| ≤ 1.5, prefer close ≥ ema10 * 0.99), and
- Dry volume on pullback bar.

### Flavor: Catch-up
- Price held near recent highs / TopBox (shallow under highs), while **10 EMA rises into** the held zone (EMA catching up to price), and
- Dry volume on signal bar.
- Not the same as Squeeze: Catch-up allows price already near highs; Squeeze requires tightening Top↔EMA coil.

UI: one queue **Darvas 10 EMA** with flavor chip column / badge: `Pullback` | `Catch-up`.  
Internal key: `darvas_10ema` (or similar) in `QUEUE_META`.

## Demotions (Approach A)

Move to **More setups** (collapsed / secondary on AD or Lab — match existing “more” pattern if any; else a secondary section below primary):

- Near 20D Pivot (`near_pivot`)
- EMA Pullbacks
- Episodic
- 52W High Breakout
- Silent Coil
- Stair-Step
- Spike-Pause

Primary AD matrix shows only: **Darvas Squeeze** + **Darvas 10 EMA**.

## Files likely touched

- `Scripts/darvas_squeeze.py` — harden `evaluate_squeeze_bar` / `squeeze_frame` (tightening + rvol gates); add helpers for 10 EMA Pullback/Catch-up.
- `Scripts/desk_contract.py` — DARVAS constants (e.g. `max_rvol`), new queue meta, display caps.
- `App/pages/action_desk.py` — assemble new queue; demote others; wire why_now / chips.
- Tests: new/updated under `tests/` — MAXHEALTH regression fixture (synthetic or taped last bar), mcap gate, flavor classification, demotion visibility contract if cheap.

## Success criteria

1. Contract tests green for new squeeze gates + MAXHEALTH-style fixture **fails** squeeze.
2. Both queues only emit symbols from `setup_pool` (mcap≥1000).
3. AD primary shows Squeeze + Darvas 10 EMA; others under More setups.
4. Live/smoke: MAXHEALTH not in Darvas Squeeze on current DB as-of latest session (or documented if data changes).
