# MarketPulse Recovery Baseline

**Branch:** `codex/marketpulse-recovery`  
**Base:** `main` at `c997afd`  
**Audit date:** 2026-08-10  
**Database:** `D:\Sid\MarketPulse2.0\Database\marketpulse.duckdb` (opened read-only)

## Production audit

The audit was run with:

```powershell
& 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' Scripts\recovery_audit.py 'D:\Sid\MarketPulse2.0\Database\marketpulse.duckdb'
```

```json
{
  "database_date": "2026-08-07",
  "candidate_date": "2026-08-07",
  "score_versions": {"focused-v1": 2341},
  "latest_candidate_count": 2341,
  "below_market_cap_count": 916,
  "missing_market_cap_count": 0,
  "portfolio_count": 14,
  "pr_table_counts": {
    "security_events": 0,
    "corporate_actions": 0,
    "security_risk_daily": 0,
    "top_value_daily": 0,
    "ingested_reports": 0
  }
}
```

This confirms that the current decision snapshot is legacy `focused-v1`, that the latest candidate partition contains 916 rows below the ₹1,000 Cr universe gate, and that downloaded PR reports have not reached the decision database. The 14 open legacy portfolio positions are present in the market database and must be migrated before market rebuilds stop preserving manual tables.

## Test baseline

The recovery audit tests and corrected legacy-navigation contract pass with an explicit workspace temp directory:

```powershell
& 'D:\Sid\MarketPulse2.0\.venv\Scripts\python.exe' -m pytest --basetemp .pytest-tmp tests/test_recovery_audit.py tests/test_app_queries.py::test_main_keeps_legacy_navigation_shell -q
```

Result: `3 passed`.

The original full-suite run from this sandbox was not a valid release baseline because pytest could not scan the host temp root (`WinError 5`) and one stale navigation assertion still referenced a removed tab contract. Task 1 corrects the assertion and all subsequent test commands use `.pytest-tmp`.
