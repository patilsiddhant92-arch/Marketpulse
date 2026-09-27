# Handoff: run and verify the Step 2a NSE archive backfill

**For:** a coding agent (Google Antigravity) working in `D:\Sid\MarketPulse2.0`, branch `feat/truth-contract`.
**Context:** MarketPulse is an NSE end-of-day swing-trading app (Python + DuckDB + FastAPI + React). Step 2a code is already built, reviewed and merged (plan: `docs/superpowers/plans/2026-09-26-rebuild-step2a-backfill-ingest.md`). What remains is **running** the one-time download and verifying the result. Another agent (Claude) is building Step 2b in a separate git worktree (`D:\Sid\MarketPulse2.0-wt\step2b` or similar) at the same time.

## Hard rules

- Stay on branch `feat/truth-contract` in `D:\Sid\MarketPulse2.0`. Do not create, switch or delete branches; do not rebase, reset, stash, or push.
- Do not modify any `.py`, `.bat`, `.ts/.tsx`, test, or docs file. If something is broken, stop and write the problem into the report (below) — do not fix code.
- Do not run any database writer: `Append_Daily.bat`, `Run_MarketPulse_Auto.bat`, `Rebuild_MarketPulse.bat`, `Refresh_Deals.bat`, `Scripts/build_database.py`, `Scripts/append_database.py`, `Scripts/refresh_deals.py`, `Scripts/daily_pipeline.py`. Do not open or edit anything under `Database/`.
- Only these paths may change: `Input/archive/backfill/**` (git-ignored downloads), and the three reference files `Input/reference/index_name_map.csv`, `Input/reference/nse_holidays.json`, `Input/reference/symbolchange.csv`.
- The scheduled task `MarketPulse_EOD` runs at 20:00 IST from this folder. The download does not conflict with it, but do not start a second copy of the download while one is running.

## Steps

1. **Preflight:** `git status --short` must be empty (except files under `Input/archive/backfill/`), and `git rev-parse --abbrev-ref HEAD` must print `feat/truth-contract`. If not, stop and report.
2. **Run the download:** double-click or run `Backfill_Archives.bat` from the repo root (it calls `.venv\Scripts\python.exe Scripts\run_archive_backfill.py`, defaults: from `2020-01-01` to today, kinds `bhav,index,pr`). Expected duration 2.5–3 hours; requests are spaced 1.2 s apart.
   - Exit code 0 = done. Exit code 2 = some files failed or NSE throttled (it stops after 25 consecutive errors): wait ~15 minutes and run it again — it resumes and only retries missing/`pending`/`error` items. Repeat up to 3 times.
   - Any other exit code: stop and report the console output.
3. **Read the summary:** `Input/archive/backfill/last_run_summary.json`. Record:
   - `by_kind_status` counts, `first_last_ok` per kind (expected: `bhav` first ok ≈ 2020-01-01, `index` and `pr` also ≈ 2020-01-01; last ok = latest trading day),
   - `calendar_reasons` counts (expected mostly `session`, `weekend`, `holiday`; any `unknown` weekdays must be listed with dates),
   - `name_map` status and the reference-file statuses.
4. **Check the index-name map:** open `Input/reference/index_name_map.csv` and confirm rows exist whose `canonical_name` is each of: `Nifty 50`, `NIFTY MIDSML 400`, `NIFTY MIDCAP 150`, `NIFTY SMLCAP 250`, `India VIX`. List any of these missing. Copy any `WARNING: dropping duplicate mapping` lines from the console into the report.
5. **Check the benchmark history is continuous** (read-only):
   ```powershell
   .venv\Scripts\python.exe -c "import sys; sys.path[:0]=['Scripts']; from config import ROOT_DIR; from index_history import load_all_index_history as L; d=L(ROOT_DIR); [print(n, d[d.index_name==n].trade_date.min(), d[d.index_name==n].trade_date.max(), d[d.index_name==n].trade_date.nunique()) for n in ['Nifty 50','NIFTY MIDSML 400','India VIX']]"
   ```
   Expected: each starts ≈ 2020-01-01 and ends at the latest session, with roughly 250 sessions per year. Report the three lines.
6. **Run the test suite** (read-only; must stay green): `.venv\Scripts\python.exe -m pytest -q` → expect `0 failed`. Report the last line.
7. **Commit only the three reference files** (never the downloads):
   ```powershell
   git add Input/reference/index_name_map.csv Input/reference/nse_holidays.json Input/reference/symbolchange.csv
   git commit -m "data: NSE index-name map, holiday list and symbol-change reference files" -m "Co-Authored-By: Antigravity agent"
   ```
   If a file is missing because its step failed, commit the others and note it.
8. **Write the report** to `docs/superpowers/handoffs/2026-09-26-antigravity-step2a-backfill-REPORT.md` (do **not** commit it): steps 1–7 results, exit codes of each run, total bytes downloaded (sum of `bytes` in `Input/archive/backfill/manifest.jsonl`), and anything unexpected. The user will pass it back to Claude.

## Do not

- Do not run a database rebuild after the download. The rebuild happens once, after Step 2b (price adjustment) and Step 2c (safe rebuild) land.
- Do not delete or move anything in `Input/archive/` other than what the backfill itself writes.
