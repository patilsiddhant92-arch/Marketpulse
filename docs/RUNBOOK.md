# MarketPulse runbook

All commands run from the repo root in PowerShell. `$py` below means
`.\.venv\Scripts\python.exe`.

## First-time setup

1. Python venv and packages:
   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r Scripts\requirements.txt
   ```
   (Every `.bat` launcher also calls `Scripts\_ensure_venv.bat`, which creates the venv and
   installs the requirements if they are missing.)
2. Build the UI once, and again after every frontend change:
   ```powershell
   cd frontend; npm ci; npm run build; cd ..
   ```
   The server serves `frontend\dist`. `Launch_MarketPulse.bat` warns if it is missing.
3. Telegram (optional): put `TELEGRAM_BOT_TOKEN=...` in `.env` at the repo root, send
   `/start` to the bot, then run `$py Scripts\telegram_deals.py --setup` to find
   `TELEGRAM_CHAT_ID` and add it to `.env`. Without them, alerts are only logged.
4. Register the daily task: `.\Install_MarketPulse_Schedule.bat`. The PC timezone must be
   India Standard Time.

## Daily run (20:00)

Task Scheduler job `MarketPulse_EOD` runs `Run_MarketPulse_Auto.bat` at 20:00 local time.
It does **not** catch up if the PC was off at 20:00: run the bat by hand the next day.
The bat runs `Scripts\daily_pipeline.py`, which:

1. finds the latest published NSE session (looks back 7 days) and downloads its reports;
2. takes the DB writer lock and appends every missing session to `Database\marketpulse.duckdb`,
   recomputing indicators and the derived tables;
3. sends the Telegram deals report;
4. writes `Database\status.json` (per-step results) and streams `Logs\pipeline_<stamp>.log`;
5. backs up the user DB after a successful run.

A failed attempt is retried after 10 minutes, up to 3 attempts (`--retries`, `--retry-wait`).
If all fail, a Telegram alert is sent. Useful flags:

```powershell
.\Run_MarketPulse_Auto.bat --date 06082026     # force a session (DDMMYYYY)
.\Run_MarketPulse_Auto.bat --append-only       # files already in Input\daily
.\Run_MarketPulse_Auto.bat --download-only     # download, don't touch the DB
.\Run_MarketPulse_Auto.bat --skip-telegram
```

The UI does not need restarting after a run.

## Start the UI

```powershell
.\Launch_MarketPulse.bat
```

This runs `uvicorn App.api.server:app` on `127.0.0.1:8000` (the next free port if 8000 is
busy) and opens the browser. For frontend development, keep the server running and use
`cd frontend; npm run dev` (Vite on port 5199, proxies `/api` to port 8000).

## Safe full rebuild

Use it when the history needs recomputing (new archive files, adjustment overrides, parser
fixes). It builds into `Database\marketpulse.tmp.duckdb`, validates it against the live DB,
and only then backs up the live DB and swaps the new one in. The writer lock is held for the
whole run, so do not schedule it near 20:00.

```powershell
$py Scripts\safe_rebuild.py --dry-run      # build + validate, never swap (add --keep-temp to inspect)
$py Scripts\safe_rebuild.py                # build, validate, back up, swap
```

- Validation failure: no swap, the temp DB is kept, exit code 2.
- Backups go to `Database\backups\marketpulse_<YYYYmmdd_HHMMSS>.duckdb`. The newest
  `MP_DB_BACKUP_KEEP` copies are kept; the default is `DEFAULT_KEEP` in `Scripts\db_backup.py`.
  To roll back, stop the server and copy a backup over `Database\marketpulse.duckdb`.
- To rehearse on a copy: `$py Scripts\safe_rebuild.py --db C:\tmp\mp\marketpulse.duckdb --dry-run`.

`Rebuild_MarketPulse.bat` runs `Scripts\build_database.py` directly and does not do the
dry-run check.

## Review unexplained price gaps

Splits and bonuses are adjusted from the NSE PR files. A large one-day gap with no matching
corporate action is stored as `unexplained_gap` (confidence `unconfirmed`) and **not**
adjusted. To review them (read-only, writes nothing):

```powershell
$py Scripts\adjustment_overrides_report.py            # recompute against Input\ (slow, reflects the YAML now)
$py Scripts\adjustment_overrides_report.py --from-db  # use the stored table (fast)
```

Each row shows the ratio, the closes around the date and the nearest corporate-action text
(`--window 30` days). The report ends with a commented-out YAML stub. After checking each gap
on a chart, add one entry per gap to `Input\reference\adjustments_override.yaml`:

```yaml
- {symbol: ABC, ex_date: 2024-03-15, factor: 0.5, note: "1:1 bonus missing from NSE file"}  # adjust
- {symbol: ABC, ex_date: 2024-03-15, factor: null, note: "bad factor"}  # suppress an adjustment
- {symbol: XYZ, ex_date: 2024-05-02, kind: ignore, note: "real move, results day"}  # reviewed, no adjustment
- {symbol: PQR, ex_date: 2024-07-01, kind: demerger, note: "demerger, not adjusted"}  # record only
```

`factor` is the multiplier for prices before the ex-date. Only the kinds `ignore` and `demerger`
are allowed (or leave `kind` out). The next daily append or safe rebuild uses the file.

## NSE archive backfill

`.\Backfill_Archives.bat` downloads bhavcopy, all-index close and PR zips since 2020-01-01 into
`Input\archive\backfill\`. It takes about 3 hours, can be resumed (just run it again), and
does not touch the DB. Exit code 2 means some files failed; re-run to fetch only those.
Summary: `Input\archive\backfill\last_run_summary.json`. Options for
`Scripts\run_archive_backfill.py`: `--from`, `--to`, `--kinds bhav,index,pr`,
`--skip-reference`, `--skip-name-map`. Run a safe rebuild afterwards to load the history.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| UI shows "locked" / `503` with `Retry-After` from `/api/v2/*` | A writer (the 20:00 pipeline or a rebuild) holds the DB. Wait for it to finish. |
| Pipeline or rebuild waits and then fails with `WriterLockTimeout` | Another writer holds `Database\marketpulse.duckdb.write.lock`. A lock whose process is dead, or older than 6 h, is removed automatically. Otherwise find the other run (Task Manager, `python.exe`) and let it finish; delete the lock file only if no MarketPulse process is running. Timeout: `MP_DB_LOCK_TIMEOUT_S` (default 900 s). |
| `/api/v2/health` returns `503` | The body says why: `status` is `stale` (latest session older than expected), `degraded`, or `unavailable` (DB missing or locked). Its `checks` list names missing tables. `stale` usually means the 20:00 run was missed or failed. |
| Data is stale | Check `Database\status.json` and the newest `Logs\pipeline_*.log`. NSE sometimes publishes late: run `.\Run_MarketPulse_Auto.bat` again, or with `--date DDMMYYYY`. |
| Blank page at `127.0.0.1:8000` | `frontend\dist` is missing: `cd frontend; npm ci; npm run build`. |
| Telegram silent | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` missing in `.env`; check with `$py Scripts\telegram_deals.py --dry-run`. |
