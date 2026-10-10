# MarketPulse

MarketPulse is an end-of-day (EOD) swing-trading desk for NSE equities. Every evening a
pipeline downloads the day's NSE reports, appends them to a local DuckDB database and
recomputes indicators, groups, setups and deal flow. A React UI served by FastAPI reads
that database read-only.

- **UI**: React + Vite (`frontend/`), six tabs (Pulse, Setups, Sector Intel, Deals, Charts,
  Research; old `/screener` links redirect to `/setups`) plus a Stock 360 page. Served by `App/api/server.py` from `frontend/dist`;
  data comes from `/api/v2` (`App/api/v2`, `App/services`).
- **Pipeline**: `Scripts/daily_pipeline.py` (download, append, Telegram), full rebuild via
  `Scripts/safe_rebuild.py`.
- **Data**: `Database/marketpulse.duckdb` (market data, written only by the pipeline) and
  `Database/marketpulse_user.duckdb` (watchlist and other user data).

It is research support, not an execution system. Check every candidate on a chart and
apply your own risk limits.

## Quick start (Windows)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r Scripts\requirements.txt
cd frontend; npm ci; npm run build; cd ..
.\Launch_MarketPulse.bat               # UI at http://127.0.0.1:8000
.\Install_MarketPulse_Schedule.bat     # one-time: daily 20:00 pipeline task
```

| Launcher | What it does |
| --- | --- |
| `Launch_MarketPulse.bat` | Starts the FastAPI server (serves the built React app) and opens the browser |
| `Run_MarketPulse_Auto.bat` | EOD pipeline: download + append + Telegram. This is what the 20:00 task runs |
| `Install_MarketPulse_Schedule.bat` | Registers the `MarketPulse_EOD` Task Scheduler job (daily 20:00) |
| `Rebuild_MarketPulse.bat` | Full rebuild from all input history (prefer `Scripts\safe_rebuild.py`, see runbook) |
| `Backfill_Archives.bat` | One-time NSE archive download since 2020 (resumable) |
| `Refresh_Deals.bat` | Fetch the latest bulk/block deals and refresh the DB |
| `Launch_Legacy_UI.bat` | Optional, unsupported: the old NiceGUI UI (`App/app.py`) |

Operations (daily run, safe rebuild, price-gap review, troubleshooting):
[docs/RUNBOOK.md](docs/RUNBOOK.md).

## Security

The server binds to `127.0.0.1` and has **no authentication**. Do not expose it on a network.
Secrets (Telegram token) live in `.env`, which is git-ignored.
