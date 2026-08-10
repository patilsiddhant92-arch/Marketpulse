# MarketPulse EOD runbook

## Before the run

1. Keep the previous `Database/marketpulse.duckdb` and `Database/marketpulse_user.duckdb` available for rollback.
2. Confirm the workstation clock is in Asia/Kolkata and that no other append job is running.
3. Do not delete or overwrite the previous accepted database until the new session passes health checks.

## Run and accept one session

```powershell
.\Run_MarketPulse_Auto.bat
```

For a specific session:

```powershell
.\Run_MarketPulse_Auto.bat --date DDMMYYYY
```

The downloader stages NSE files and the PR ZIP, validates the manifest, appends the accepted market session transactionally, ingests PR events/risk reports, and materializes one `focused-v2` decision partition. A duplicate accepted session is a no-op.

## Verify

Open the UI and inspect **Data Health**. Confirm:

- the market date equals the focused-v2 decision date;
- the manifest and pipeline steps are successful;
- PR row counts are non-zero when the NSE ZIP contains those reports;
- no decision row in the eligible queue has market cap below ₹1,000 Cr;
- the user-data migration state is complete.

For a read-only command-line check:

```powershell
& .\.venv\Scripts\python.exe Scripts\recovery_audit.py --db Database\marketpulse.duckdb
& .\.venv\Scripts\python.exe Scripts\compare_score_versions.py --db Database\marketpulse.duckdb
```

## Failure handling

- **Missing or partial manifest**: do not append; repair the staged download and rerun.
- **Checksum changed**: preserve the accepted database and investigate the source file before retrying.
- **Decision snapshot stale/missing**: treat the session as failed even if prices appended; rerun materialization only after the accepted inputs are verified.
- **PR parser error**: preserve the ZIP and log; do not infer event sentiment or silently discard the report.

The prior database remains the rollback point. Restore it, keep the user database, and rerun the session after correcting the input or code issue.
