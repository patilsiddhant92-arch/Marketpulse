# VCP — Third Action Desk Primary (only three queues)

**Date:** 2026-09-14  
**Branch:** feat/truth-contract (PR #2)  
**Queue key:** `vcp` · Title: `3. VCP` · `PRIMARY_QUEUES = (darvas, darvas_10ema, vcp)`  
**MORE_QUEUES:** empty — all other AD screeners deleted (not demoted).

## Hard gates (v1 = former Manas Focus; fine-tune later)
1. `setup_pool` (mcap >= 1000 Cr, band > 5, ADV floor)
2. `close` / `cmp` >= 30
3. `ema_shakeout` True (persisted)
4. Raw **ret_63d >= +30%** (fail closed if hist short — no `rs_3m_percentile` soft gate)
5. Purple density >= 3 in 63d: `|ret|>=5%` and `volume>=1_000_000` (500k soft alt only later)
6. `avg_volume_20d >= 200k` when column present

## Soft rank
`ema_10` rising (not hard) → purple_n DESC → ret_3m DESC → away_52w_high ASC

## Evidence
`purple_n`, `ret_3m_pct`, `close_location_pct`; `setup_type`/`tv_key` = VCP / vcp

## Retired (deleted)
near_pivot, pullback, episodic, high52, silent_coil, stair_step, spike_pause, manas key

## Out of scope
Classic Minervini successive-contraction geometry (later), Strong Start, sizing, morning IA strip
