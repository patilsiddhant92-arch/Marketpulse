# Data gaps found during design

| # | Gap | Impact | Fix |
|---|---|---|---|
| 1 | `security_events` is empty (local rebuild) | No RES / NEWS chips | Ingest NSE corporate actions, board meetings (results dates) and announcements daily |
| 2 | Committed repo data has no daily files from 2026-08-13 to 2026-10-08 | 1D moves on 2026-10-08 are inflated in a fresh clone; the mockup uses 2026-08-13 as its as-of date | Commit or fetch the missing dailies; the 5-year archive lives only on Siddhant's machine |
| 3 | `index_daily` holds only ~32 sessions locally; 63D returns are null | Index view has no 3M column; History Lab needs index history | Run `Scripts/backfill_index_history.py` for 5 years |
| 4 | `regime_daily` verdict, Trend and Stress pillars null in the local rebuild | Old verdict not usable; Pulse mood replaces it | Check the evidence step (I/O error seen locally) |
| 5 | 52W highs/lows differ between leadership pillar and Today strip | Two numbers for one fact | One source of truth for new highs/lows |
| 6 | `stage2_pct` reads ~11% (94th percentile) | Value looks low in absolute terms | Confirm the definition in `regime_daily` |
| 7 | Market cap is "latest" in `stocks_master` | Replay uses today's cap for past dates | Use `security_reference_daily.market_cap_cr` as of the date |
| 8 | No stored equal-weight market series | Forward returns are computed on the fly | Add `market_ew_daily` in the pipeline |
