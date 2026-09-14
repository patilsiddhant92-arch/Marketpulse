# Manas Focus — Third Action Desk Primary

**Date:** 2026-09-14  
**Branch:** feat/truth-contract (PR #2)  
**Queue key:** `manas` · Title: `3. Manas Focus` · `PRIMARY_QUEUES = (darvas, darvas_10ema, manas)`

## Hard gates
1. `setup_pool` (mcap ≥ ₹1000 Cr, band > 5, ADV floor)
2. `close` / `cmp` ≥ ₹30
3. `ema_shakeout` True (persisted)
4. Raw **ret_63d ≥ +30%** (fail closed if hist short — no `rs_3m_percentile` soft gate)
5. Purple density ≥ 3 in 63d: `|ret|≥5%` and `volume≥1_000_000` (500k soft alt only later)
6. `avg_volume_20d ≥ 200k` when column present

## Soft rank
`ema_10` rising (not hard) → purple_n DESC → ret_3m DESC → away_52w_high ASC

## Evidence
`purple_n`, `ret_3m_pct`, `close_location_pct`; `setup_type`/`tv_key` = Manas Focus / manas

## Out of scope
Strong Start, sizing, free float, falling-knife sleeve
