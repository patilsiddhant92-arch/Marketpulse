# Darvas Primary Screeners Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Approach A — tighten Darvas Squeeze (dry vol + rising 10EMA + hard tightening), add Darvas 10 EMA (Pullback/Catch-up), demote other AD queues; mcap≥1000 via setup_pool; MAXHEALTH must fail Squeeze.

**Architecture:** Keep squeeze math in `Scripts/darvas_squeeze.py`; AD only assembles queues from `setup_pool`. Promote tightening + rvol into hard gates inside `evaluate_squeeze_bar` / per-symbol frame so all consumers stay honest.

**Tech Stack:** Python, pandas, DuckDB, NiceGUI Action Desk, pytest.

---

### Task 1: Failing tests for Squeeze harden + MAXHEALTH

**Files:**
- Create: `tests/test_darvas_squeeze_dry_volume.py`
- Modify: `Scripts/darvas_squeeze.py` (later)

**Steps:**
1. Write tests that build a tiny OHLC+EMA+rvol frame mimicking MAXHEALTH last bar (rvol 1.31, tightening True, squeeze~2.4%) and assert `qualifies` is **False** once dry-vol gate exists.
2. Write positive case: same geometry but rvol 0.7 + rising ema10 + tightening → qualifies True.
3. Assert tightening False rejects even with dry vol.
4. Run pytest on the new file — expect FAIL before implementation.
5. Commit after green in Task 2.

### Task 2: Implement Squeeze hard gates

**Files:**
- Modify: `Scripts/darvas_squeeze.py`
- Modify: `Scripts/desk_contract.py` (`DARVAS` add `max_rvol: 1.0`)

**Steps:**
1. Thread `rvol` (and prior ema10 for rising check if not already) into `evaluate_squeeze_bar` / `squeeze_frame`.
2. Hard gates: `rvol <= DARVAS["max_rvol"]`, `squeeze_pct < squeeze_pct_5d_ago` when prior finite, `ema_10` rising vs prior bar.
3. Re-run tests → green.
4. Quick DB smoke: load MAXHEALTH latest via duckdb + squeeze_frame → qualifies False.
5. Commit.

### Task 3: Darvas 10 EMA Pullback / Catch-up helpers + tests

**Files:**
- Modify: `Scripts/darvas_squeeze.py` (or new `Scripts/darvas_10ema.py` if cleaner)
- Create: `tests/test_darvas_10ema_flavors.py`

**Steps:**
1. Implement `classify_darvas_10ema_bar(...)` → None | "Pullback" | "Catch-up" with post-thrust + dry vol rules from spec.
2. Tests for each flavor + rejection (no thrust, wet volume).
3. Commit.

### Task 4: Wire Action Desk queues + demote others

**Files:**
- Modify: `Scripts/desk_contract.py` (`QUEUE_META`, caps)
- Modify: `App/pages/action_desk.py`

**Steps:**
1. Add queue key `darvas_10ema` with flavor column/chip.
2. Primary section: Darvas Squeeze + Darvas 10 EMA only.
3. Demote near_pivot, EMA pullbacks, episodic, high52, silent coil, stair-step, spike-pause under More setups.
4. Ensure both queues merge only with `setup_pool` (mcap≥1000).
5. Update any queue-label honesty tests.
6. Commit.

### Task 5: Verify

**Steps:**
1. Run focused pytest suite for darvas + desk contracts.
2. Optional: live AD smoke noting MAXHEALTH absent from Squeeze.
3. Summarize for user with files changed + how to verify.
