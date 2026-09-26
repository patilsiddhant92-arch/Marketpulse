# Step 2a NSE Archive Backfill — Execution & Verification Report

**Date:** 2026-09-26  
**Agent:** Google Antigravity  
**Repo / Branch:** `D:\Sid\MarketPulse2.0` (`feat/truth-contract`)  
**Handoff Spec:** `docs/superpowers/handoffs/2026-09-26-antigravity-step2a-backfill-run.md`

---

## 1. Preflight Check

- **Command:** `git rev-parse --abbrev-ref HEAD; git status --short`
- **Exit Code:** `0`
- **Branch:** `feat/truth-contract`
- **Working Tree Status:** Clean (empty output).

---

## 2. Backfill Execution

- **Command:** `.\.venv\Scripts\python.exe -u Scripts\run_archive_backfill.py`
- **Runs Required:** `1` (completed on first pass with `0` errors and `0` aborts)
- **Exit Code:** `0`
- **Console Output:**
  ```json
  {"reference": {"holidays": "ok", "symbolchange": "ok"}}
  {"backfill": {"ok": 5448, "not_published": 1935, "pending": 0, "error": 0, "skipped": 0, "aborted": 0}}
  Wrote 134 mappings to D:\Sid\MarketPulse2.0\Input\reference\index_name_map.csv
  ```
- **Total Bytes Downloaded** (sum of `bytes` in `Input/archive/backfill/manifest.jsonl`):
  - **`1,263,761,311` bytes** (~1.26 GB / 1,205.22 MiB) across `5,448` `ok` archive files (`7,383` total manifest entries).

---

## 3. Summary (`Input/archive/backfill/last_run_summary.json`)

```json
{
 "by_kind_status": {
  "bhav:ok": 2099,
  "index:ok": 1674,
  "pr:ok": 1675,
  "bhav:not_published": 362,
  "index:not_published": 787,
  "pr:not_published": 786
 },
 "first_last_ok": {
  "bhav": [
   "2020-01-01",
   "2026-09-25"
  ],
  "index": [
   "2020-01-01",
   "2026-09-25"
  ],
  "pr": [
   "2020-01-01",
   "2026-09-25"
  ]
 },
 "calendar_reasons": {
  "session": 1746,
  "special_session": 353,
  "weekend": 348,
  "unknown": 12,
  "holiday": 2
 },
 "name_map": "ok"
}
```

### Reference-File Statuses
- `holidays` (`Input/reference/nse_holidays.json`): `"ok"`
- `symbolchange` (`Input/reference/symbolchange.csv`): `"ok"`
- `name_map` (`Input/reference/index_name_map.csv`): `"ok"` (134 mappings written)

### Listed `unknown` Weekdays (12 total)
All 12 `unknown` dates are real historical NSE weekday holidays (mostly in 2025, plus one in 2020 and one in 2022) where `bhav` returned HTTP 404 and `nse_holidays.json` only covers 2026:
1. `2020-04-14` (Tuesday — Dr. Baba Saheb Ambedkar Jayanti)
2. `2022-08-09` (Tuesday — Muharram)
3. `2025-02-26` (Wednesday — Mahashivratri)
4. `2025-03-14` (Friday — Holi)
5. `2025-03-31` (Monday — Id-Ul-Fitr / Ramadan Eid)
6. `2025-04-10` (Thursday — Shri Mahavir Jayanti)
7. `2025-04-14` (Monday — Dr. Baba Saheb Ambedkar Jayanti)
8. `2025-04-18` (Friday — Good Friday)
9. `2025-05-01` (Thursday — Maharashtra Day)
10. `2025-08-15` (Friday — Independence Day)
11. `2025-08-27` (Wednesday — Ganesh Chaturthi)
12. `2025-10-02` (Thursday — Mahatma Gandhi Jayanti / Dussehra)

*(See Section 8 below for why 2020–2024 weekday holidays and 352 weekends were classified as `session` / `special_session`.)*

---

## 4. Index-Name Map Verification (`Input/reference/index_name_map.csv`)

- **Total Mappings:** `134`
- **`WARNING: dropping duplicate mapping` Console Lines:** None (`0` warnings emitted).
- **Required Benchmark Canonical Names:** All 5 present (`0` missing):

| `source_name` | `canonical_name` | `overlap_days` |
|---|---|---|
| `Nifty 50` | `Nifty 50` | 429 |
| `Nifty MidSmallcap 400` | `NIFTY MIDSML 400` | 429 |
| `Nifty Midcap 150` | `NIFTY MIDCAP 150` | 429 |
| `Nifty Smallcap 250` | `NIFTY SMLCAP 250` | 429 |
| `India VIX` | `India VIX` | 429 |

- **Additional Check:** All 44 canonical indices in `CANONICAL_44_INDICES` (`thematic_engine.py` / `sector_index_rs.py`) are also present in `Input/reference/index_name_map.csv` (`0` missing).

---

## 5. Benchmark History Continuity Check (Read-Only)

- **Command:**
  ```powershell
  .venv\Scripts\python.exe -c "import sys; sys.path[:0]=['Scripts']; from config import ROOT_DIR; from index_history import load_all_index_history as L; d=L(ROOT_DIR); [print(n, d[d.index_name==n].trade_date.min(), d[d.index_name==n].trade_date.max(), d[d.index_name==n].trade_date.nunique()) for n in ['Nifty 50','NIFTY MIDSML 400','India VIX']]"
  ```
- **Exit Code:** `0`
- **Output:**
  ```text
  Nifty 50 2020-01-01 00:00:00 2026-09-25 00:00:00 1673
  NIFTY MIDSML 400 2020-01-01 00:00:00 2026-09-25 00:00:00 1673
  India VIX 2020-01-01 00:00:00 2026-09-25 00:00:00 1673
  ```

---

## 6. Test Suite Verification (Read-Only)

- **Command:** `.venv\Scripts\python.exe -m pytest -q`
- **Exit Code:** `0`
- **Last Line:**
  ```text
  572 passed, 3 skipped, 5 deselected, 4 warnings in 374.06s (0:06:14)
  ```

---

## 7. Reference Files Commit

- **Command:**
  ```powershell
  git add Input/reference/index_name_map.csv Input/reference/nse_holidays.json Input/reference/symbolchange.csv
  git commit -m "data: NSE index-name map, holiday list and symbol-change reference files" -m "Co-Authored-By: Antigravity agent"
  ```
- **Exit Code:** `0`
- **Commit Hash:** `6b9723d` (`3 files changed, 3138 insertions(+)`)

---

## 8. Unexpected Findings (For Claude Before Step 2c Rebuild)

Per the hard rules, no code was modified. Two upstream NSE archive quirks were uncovered during verification:

### Finding A: NSE CDN Serves Duplicate Prior-Session `sec_bhavdata_full_DDMMYYYY.csv` on 425 Non-Trading Days (2020–2024)
- **Symptom:** `bhav:ok` is `2,099` while `index:ok` is `1,674` (`2099 - 1674 = 425`), and `calendar_reasons` reports `special_session: 353` and `session: 1746`.
- **Root Cause:** Across the `2,099` `bhav:ok` files, there are exactly **`1,674` unique `sha256` digests** and **`425` byte-for-byte duplicate `sha256` files**. From 2020 through late 2024, requesting `sec_bhavdata_full_DDMMYYYY.csv` for a Sunday or weekday holiday returned `HTTP 200` with a copy of the prior trading day's CSV (whose internal `DATE1` column still has the prior trading day's date — e.g., `sec_bhavdata_full_05012020.csv` on Sunday `2020-01-05` has `DATE1 = 03-Jan-2020`, and `sec_bhavdata_full_21022020.csv` on Mahashivratri `2020-02-21` has `DATE1 = 20-Feb-2020`).
- **Diwali 2021 Edge Case:** On Thursday `2021-11-04` (Diwali Muhurat trading), `sec_bhavdata_full_04112021.csv` is a byte-for-byte duplicate of `03-Nov-2021`, while `sec_bhavdata_full_05112021.csv` (dated Friday `2021-11-05`) contains the `DATE1 = 04-Nov-2021` Muhurat session rows.
- **Impact:**
  - `build_database.read_bhavcopy` / `build_prices` is **unaffected** because it parses `DATE1` from inside the CSV and deduplicates on `(symbol, trade_date)`, yielding the exact 1,674 real sessions.
  - `trading_calendar.observed_sessions` trusts `(d, "bhav") == "ok"` in `manifest.jsonl` and `sec_bhavdata_full_DDMMYYYY.csv` filenames on disk without checking internal `DATE1` or deduplicating `sha256`, causing 352 non-trading weekends to be marked `special_session` and 73 pre-2025 weekday holidays to be marked `session`.

### Finding B: Three April 2023 `ind_close_all_*.csv` Files Have `MM-DD-YYYY` in `Index Date` (`1,674` Files $\rightarrow$ `1,673` Unique `trade_date`s)
- **Symptom:** `index:ok` downloaded `1,674` distinct trading-day files, but `load_all_index_history` returned `1,673` unique `trade_date` values for `Nifty 50`, `NIFTY MIDSML 400`, and `India VIX`.
- **Root Cause:** Comparing the filename date (`ind_close_all_DDMMYYYY.csv`) against `parse_ind_close_all(p)["trade_date"]` across all 1,674 files revealed exactly **3 mismatches**, all in April 2023, where NSE formatted the internal `Index Date` column as `MM-DD-YYYY` instead of `DD-MM-YYYY`:
  1. `ind_close_all_06042023.csv` (`2023-04-06`) has `Index Date = 04-06-2023` $\rightarrow$ parsed with `%d-%m-%Y` as `2023-06-04` (Sunday).
  2. `ind_close_all_10042023.csv` (`2023-04-10`) has `Index Date = 04-10-2023` $\rightarrow$ parsed with `%d-%m-%Y` as `2023-10-04` (collides with `ind_close_all_04102023.csv` and overwrites real `2023-10-04` because `10042023` sorts after `04102023` and `drop_duplicates` uses `keep="last"`).
  3. `ind_close_all_11042023.csv` (`2023-04-11`) has `Index Date = 04-11-2023` $\rightarrow$ parsed with `%d-%m-%Y` as `2023-11-04` (Saturday).
- **Suggested Fix for Claude in Step 2c:** In `index_history.parse_ind_close_all`, derive `trade_date` from the `ind_close_all_DDMMYYYY.csv` filename when available (or fall back to filename date when `Index Date` disagrees with `DDMMYYYY`). That restores `2023-04-06`, `2023-04-10`, and `2023-04-11` and prevents overwriting `2023-10-04`.

### Finding C: Extra `pr:ok` on Saturday `2024-04-06` (`1,675` vs `1,674`)
- On Saturday `2024-04-06`, `PR060424.zip` returned `HTTP 200` (`ok`), whereas both `bhav` and `index` returned `HTTP 404` (`not_published`).
