# Rebuild Step 2b — Split/Bonus Price Adjustment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every indicator, RS value, Darvas box, VCP pivot and chart uses split/bonus-adjusted prices, with factors taken from official NSE data (corporate-action text + market-cap file), raw prices kept for audit, and nothing adjusted on a guess.

**Architecture:** One new pure module `Scripts/price_adjustment.py` (parse → detect → reconcile → cumulative factors → apply). `build_database.main()` and `append_database` call one entry point, `adjust_prices(prices, root, extra_actions)`, before `calc_indicators`, so indicators are computed on adjusted OHLCV while `prices_daily` stores raw + `adj_*` columns and a new `price_adjustments` table records every event. Readers that compare prices across dates switch to adjusted columns through a runtime-safe helper. The daily downloader starts fetching `ind_close_all`.

**Tech Stack:** Python 3.12, pandas 3.x, numpy, DuckDB, pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-marketpulse-professional-rebuild-design.md` §4.2 (price adjustment), §4.1 (inputs), §11 (golden tests: GOODLUCK has no fake crash).

## Facts this plan relies on (verified 2026-09-26 against local data)

- NSE PR-zip corporate-action member is `Bc240919.csv` in 2019-era zips and `bc18092026.csv` in 2026 zips (case and year width differ). Columns: `SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE`. 2026 dates are ISO (`2026-09-15`); 2019 dates are `DD/MM/YYYY`.
- Real `PURPOSE` strings in the live `corporate_actions` table: `BONUS 2:1` (GOODLUCK, ex 2026-08-21; NSE 52-week high 1672.10 → 557.37 ⇒ price factor 1/3), `BONUS 1:1` (PGIL 2026-09-11, AILIMITED, IDEALTECHO, CHAVDA, AASTHA), `FVSPLT FRM RS 2 TO RE 1` (KIRLPNU 2026-08-18, TDPOWERSYS 2026-08-24), `FVSPLT FRM RS 10 TO RE 1` (CORDELIA), `FVSPLT FRM RS 10 TO RS 2` (TCC, ORIANA, TAALTECH), `SCH AGMT-BONUS NCRPS 4:1` / `NCRPS46:1` (bonus of **preference** shares — must not adjust equity), `RIGHTS 3:8@ PRM RS 14/-` (rights — flag only), `DEMERGER` (flag only), `DIV - RS 1.47 PER SH` (ignore).
- Older NSE wording also seen in the wild (must parse): `FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RS 2/- PER SHARE`, `FV SPLIT RS.10 TO RS.2`, `BONUS 3:2`, `CONSOLIDATION OF SHARES FROM RS 1 TO RS 10`.
- Bonus `a:b` = `a` new shares for every `b` held ⇒ pre-ex price factor `b / (a + b)` (2:1 ⇒ 1/3, 1:1 ⇒ 1/2, 3:2 ⇒ 2/5). Split face value `x → y` ⇒ factor `y / x` (10→2 ⇒ 0.2). Consolidation `x → y` (y > x) ⇒ factor `y / x` (> 1). Volume factor = `1 / price factor`.
- Market-cap files (`mcapDDMMYYYY.csv`, 87 in `Input/archive/`, and `MCAP*.csv` inside PR zips from mid-2024) have `Face Value(Rs.)` and `Issue Size` per symbol.
- `prices_daily.prev_close` is copied from bhavcopy `PREV_CLOSE`, which NSE does **not** adjust on the ex-date (GOODLUCK 21-Aug: PREV_CLOSE 1439.40, CLOSE 490.90).
- The API/UI read OHLC from `indicators_daily` (not `prices_daily`); `calc_indicators(prices, enrichment)` copies the OHLCV columns it receives into `indicators_daily`.
- `append_database` recomputes indicators over the full merged price table on every append, and `write_database` recreates the DB, so after merge the **next EOD append** writes adjusted indicators (recent events from current files); full-history factors arrive once the Step 2a backfill PR zips exist.

## Global Constraints

- Only split, bonus (equity) and consolidation adjust prices. Rights, demergers, preference-share bonuses (`NCRPS`, `PREF`), dividends: recorded with `applied = False`, never adjusted.
- Factors are applied only when they come from NSE data: corporate-action text (`bc`) or market-cap face value / issue size (`mcap`). A price gap alone never adjusts (`confidence = "unconfirmed"`, `applied = False`).
- `Input/reference/adjustments_override.yaml` wins over everything (add, change or suppress an event).
- `prices_daily` keeps raw columns unchanged and adds `adj_open_price, adj_high_price, adj_low_price, adj_close_price, adj_last_price, adj_avg_price, adj_prev_close, adj_volume, adj_delivery_qty, price_factor`. `delivery_pct` and `turnover_cr` are not adjusted.
- `adj_prev_close` = previous row's `adj_close_price` for the same symbol (first row: `prev_close × price_factor`), so the ex-date shows the real day move.
- Tests use fixtures in `tmp_path`; no network, no `Database/`, no DB writers. Stage with plain `git add <paths>`; commit trailer `Co-Authored-By: <implementing model> <noreply@anthropic.com>`.
- Work happens in the worktree `D:\Sid\MarketPulse2.0\.claude\worktrees\rebuild-step2b`; Python is `D:/Sid/MarketPulse2.0/.venv/Scripts/python`. To run tests that read the live DB read-only, set `MP_DB_PATH=D:/Sid/MarketPulse2.0/Database/marketpulse.duckdb` and `MP_USER_DB_PATH=<scratch path>`; `tests/test_stock_drawer_features.py` has two tests with a hard-coded relative `Database/` path that fail in the worktree — ignore those two.

---

### Task 1: Parse NSE corporate-action text into factors

**Files:**
- Create: `Scripts/price_adjustment.py`
- Test: `tests/test_price_adjustment_parse.py`

**Interfaces:**
- Produces:
  - `ADJUSTING_KINDS = frozenset({"split", "bonus", "consolidation"})`
  - `@dataclass(frozen=True) class ParsedAction: kind: str; factor: float | None` where `kind ∈ {"split","bonus","consolidation","rights","demerger","pref_bonus","dividend","other"}` and `factor` is the pre-ex price multiplier (None for non-adjusting kinds).
  - `parse_purpose(purpose: str) -> ParsedAction`

- [ ] **Step 1: Write the failing test** — `tests/test_price_adjustment_parse.py`:

```python
from __future__ import annotations

import math

import pytest

from price_adjustment import ParsedAction, parse_purpose


@pytest.mark.parametrize("text,kind,factor", [
    ("BONUS 2:1", "bonus", 1 / 3),
    ("BONUS 1:1", "bonus", 0.5),
    ("BONUS 3:2", "bonus", 0.4),
    ("Bonus 1 : 2", "bonus", 2 / 3),
    ("FVSPLT FRM RS 2 TO RE 1", "split", 0.5),
    ("FVSPLT FRM RS 10 TO RE 1", "split", 0.1),
    ("FVSPLT FRM RS 10 TO RS 2", "split", 0.2),
    ("FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RS 2/- PER SHARE", "split", 0.2),
    ("FV SPLIT RS.10 TO RS.2", "split", 0.2),
    ("FV SPLIT FROM RS 5/- TO RE 1/-", "split", 0.2),
    ("CONSOLIDATION OF SHARES FROM RS 1 TO RS 10", "consolidation", 10.0),
])
def test_adjusting_actions(text, kind, factor):
    p = parse_purpose(text)
    assert p.kind == kind
    assert math.isclose(p.factor, factor, rel_tol=1e-9)


@pytest.mark.parametrize("text,kind", [
    ("SCH AGMT-BONUS NCRPS 4:1", "pref_bonus"),
    ("SCH AGMT-BONUS NCRPS46:1", "pref_bonus"),
    ("BONUS PREF SHARES 1:1", "pref_bonus"),
    ("RIGHTS 3:8@ PRM RS 14/-", "rights"),
    ("RIGHTS- 7CCPS/ 7WRNTS:40", "rights"),
    ("DEMERGER", "demerger"),
    ("DIV - RS 1.47 PER SH", "dividend"),
    ("AGM/DIV-RS 0.50 PER SH", "dividend"),
    ("ANNUAL GENERAL MEETING", "other"),
    ("", "other"),
])
def test_non_adjusting_actions(text, kind):
    p = parse_purpose(text)
    assert p == ParsedAction(kind, None)


def test_unparseable_split_is_other_not_guessed():
    assert parse_purpose("FV SPLIT") == ParsedAction("other", None)
```

- [ ] **Step 2: Run to verify failure** — `D:/Sid/MarketPulse2.0/.venv/Scripts/python -m pytest tests/test_price_adjustment_parse.py -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** — create `Scripts/price_adjustment.py`:

```python
"""Split / bonus / consolidation price adjustment from official NSE data."""
from __future__ import annotations

import re
from dataclasses import dataclass

ADJUSTING_KINDS = frozenset({"split", "bonus", "consolidation"})

_NUM = r"(\d+(?:\.\d+)?)"
_BONUS_RE = re.compile(rf"BONUS\D*?{_NUM}\s*:\s*{_NUM}")
# "FROM RS 10 ... TO RE 1", "RS.10 TO RS.2", "FRM RS 2 TO RE 1"
_FV_RE = re.compile(rf"(?:FROM|FRM)?\s*R[SE]\.?\s*{_NUM}\D*?\bTO\b\s*R[SE]\.?\s*{_NUM}")


@dataclass(frozen=True)
class ParsedAction:
    kind: str
    factor: float | None


def parse_purpose(purpose: str) -> ParsedAction:
    text = re.sub(r"\s+", " ", str(purpose or "").upper()).strip()
    if not text:
        return ParsedAction("other", None)
    if "RIGHTS" in text:
        return ParsedAction("rights", None)
    if "DEMERGER" in text or "DE-MERGER" in text:
        return ParsedAction("demerger", None)
    if "BONUS" in text and ("NCRPS" in text or "PREF" in text or "DEBENTURE" in text):
        return ParsedAction("pref_bonus", None)
    if "BONUS" in text:
        m = _BONUS_RE.search(text)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if a > 0 and b > 0:
                return ParsedAction("bonus", b / (a + b))
        return ParsedAction("other", None)
    is_split = "SPLIT" in text or "SPLT" in text or "SUB-DIVISION" in text or "SUBDIVISION" in text
    is_consolidation = "CONSOLIDAT" in text
    if is_split or is_consolidation:
        m = _FV_RE.search(text)
        if m:
            old, new = float(m.group(1)), float(m.group(2))
            if old > 0 and new > 0 and old != new:
                return ParsedAction("consolidation" if new > old else "split", new / old)
        return ParsedAction("other", None)
    if "DIV" in text:
        return ParsedAction("dividend", None)
    return ParsedAction("other", None)
```

- [ ] **Step 4: Run tests** → PASS. If a parametrized case fails, fix the regex (not the test) and re-run.
- [ ] **Step 5: Commit** — `git add Scripts/price_adjustment.py tests/test_price_adjustment_parse.py` · `git commit -m "feat(adjust): parse NSE corporate-action purpose into split/bonus factors"`

---

### Task 2: Collect corporate actions from PR zips and the DB table

**Files:**
- Modify: `Scripts/price_adjustment.py`
- Modify: `Scripts/pr_report_ingestion.py` (`_parse_corporate_actions`, `parse_pr_zip` member lookup)
- Test: `tests/test_price_adjustment_sources.py`, extend `tests/test_pr_report_ingestion.py`

**Interfaces:**
- Consumes: `parse_purpose` (Task 1).
- Produces in `price_adjustment.py`:
  - `ACTION_COLUMNS = ["symbol", "ex_date", "kind", "factor", "description", "source"]`
  - `read_bc_member(zf: zipfile.ZipFile) -> pd.DataFrame` — finds the member matching `(?i)^bc\d{6,8}\.csv$`; returns raw rows (all columns as str) or empty frame.
  - `actions_from_bc_frame(raw: pd.DataFrame) -> pd.DataFrame` (`ACTION_COLUMNS`, `source="bc"`) — keeps series `EQ, BE, BZ, SM, ST`; `ex_date` from `EX_DT`, else `RECORD_DT`, else `BC_STRT_DT`, parsed as ISO or `DD/MM/YYYY` or `DD-Mon-YYYY`; symbol upper-cased; kind/factor from `parse_purpose`.
  - `collect_bc_actions(zip_paths: list[Path]) -> pd.DataFrame` — de-duplicated on `(symbol, ex_date, description)`.
  - `actions_from_corporate_actions_table(df: pd.DataFrame) -> pd.DataFrame` — re-parses the stored `description` (`source="bc"`), for the live DB's `corporate_actions` rows.
  - `find_pr_zips(root: Path) -> list[Path]` — `Input/archive/PR*.zip`, `Input/archive/backfill/pr/PR*.zip`, `Input/downloads/**/PR*.zip`.
- `pr_report_ingestion`: `_parse_corporate_actions` stores `ratio_from=1.0, ratio_to=1/factor` for adjusting kinds (so `ratio_from/ratio_to == factor`) and keeps `action_type` from `parse_purpose` kinds mapped as today (`split`, `bonus`, `rights_issue`, `merger_demerger`, `dividend`, `other`, plus `consolidation`, `pref_bonus`); `parse_pr_zip` finds members case-insensitively for both `ddmmyy` and `ddmmyyyy` names.

- [ ] **Step 1: Write the failing tests** — `tests/test_price_adjustment_sources.py`:

```python
from __future__ import annotations

import io
import math
import zipfile

import pandas as pd

from price_adjustment import (actions_from_bc_frame, actions_from_corporate_actions_table,
                              collect_bc_actions, read_bc_member)

BC_2026 = """SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE
EQ,GOODLUCK,Goodluck India Ltd,2026-08-21,,,2026-08-21,,,BONUS 2:1
EQ,KIRLPNU,Kirloskar Pneumatic,2026-08-18,,,2026-08-18,,,FVSPLT FRM RS 2 TO RE 1
BE,SIYSIL,Siyaram Silk Mills Ltd,2026-08-22,,,2026-08-21,,,SCH AGMT-BONUS NCRPS 4:1
N1,SOMEBOND,Bond,2026-08-21,,,2026-08-21,,,BONUS 1:1
"""
BC_2019 = """SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE
EQ,OLDCO,Old Co Ltd, ,24/09/2019,30/09/2019,20/09/2019, , ,FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RS 2/- PER SHARE
"""


def _zip(tmp_path, name, member, text):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr(member, text)
        zf.writestr("Pd240919.csv", "x")
    return p


def test_read_bc_member_handles_both_name_styles(tmp_path):
    z1 = _zip(tmp_path, "PR210826.zip", "bc21082026.csv", BC_2026)
    z2 = _zip(tmp_path, "PR240919.zip", "Bc240919.csv", BC_2019)
    assert len(read_bc_member(zipfile.ZipFile(z1))) == 4
    assert len(read_bc_member(zipfile.ZipFile(z2))) == 1


def test_actions_from_bc_frame_parses_dates_kinds_and_series(tmp_path):
    raw = pd.read_csv(io.StringIO(BC_2026), dtype=str, keep_default_na=False)
    a = actions_from_bc_frame(raw).set_index("symbol")
    assert "SOMEBOND" not in a.index
    assert str(a.loc["GOODLUCK", "ex_date"].date()) == "2026-08-21"
    assert a.loc["GOODLUCK", "kind"] == "bonus" and math.isclose(a.loc["GOODLUCK", "factor"], 1 / 3)
    assert a.loc["KIRLPNU", "kind"] == "split" and math.isclose(a.loc["KIRLPNU", "factor"], 0.5)
    assert a.loc["SIYSIL", "kind"] == "pref_bonus" and pd.isna(a.loc["SIYSIL", "factor"])
    raw19 = pd.read_csv(io.StringIO(BC_2019), dtype=str, keep_default_na=False)
    b = actions_from_bc_frame(raw19).iloc[0]
    assert str(b["ex_date"].date()) == "2019-09-20" and math.isclose(b["factor"], 0.2)


def test_collect_dedupes_across_zips(tmp_path):
    z1 = _zip(tmp_path, "PR210826.zip", "bc21082026.csv", BC_2026)
    z2 = _zip(tmp_path, "PR220826.zip", "bc22082026.csv", BC_2026)
    assert collect_bc_actions([z1, z2])["symbol"].tolist().count("GOODLUCK") == 1


def test_actions_from_db_table():
    df = pd.DataFrame({"symbol": ["TCC"], "ex_date": pd.to_datetime(["2026-09-04"]),
                       "action_type": ["other"], "description": ["FVSPLT FRM RS 10 TO RS 2"]})
    a = actions_from_corporate_actions_table(df).iloc[0]
    assert a["kind"] == "split" and math.isclose(a["factor"], 0.2) and a["source"] == "bc"
```

Add to `tests/test_pr_report_ingestion.py` a test that `_parse_corporate_actions` on the `BC_2026` text (copy it) returns GOODLUCK with `ratio_from / ratio_to ≈ 1/3` and `action_type == "bonus"`, KIRLPNU `action_type == "split"`, SIYSIL `action_type == "pref_bonus"`; and a test that `parse_pr_zip` on a zip whose member is `Bc240919.csv` (with `trade_date=date(2019, 9, 24)`) returns one corporate action.

- [ ] **Step 2: Run to verify failure** → FAIL (ImportError).

- [ ] **Step 3: Implement** — append to `Scripts/price_adjustment.py`:

```python
import zipfile
from pathlib import Path

import pandas as pd

ACTION_COLUMNS = ["symbol", "ex_date", "kind", "factor", "description", "source"]
_BC_MEMBER = re.compile(r"(?i)^bc\d{6,8}\.csv$")
_ACTION_SERIES = {"EQ", "BE", "BZ", "SM", "ST"}


def _parse_date(value) -> pd.Timestamp:
    text = str(value or "").strip()
    if not text:
        return pd.NaT
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%d-%m-%Y"):
        ts = pd.to_datetime(text, format=fmt, errors="coerce")
        if not pd.isna(ts):
            return ts.normalize()
    return pd.NaT


def read_bc_member(zf: zipfile.ZipFile) -> pd.DataFrame:
    names = [n for n in zf.namelist() if _BC_MEMBER.match(Path(n).name)]
    if not names:
        return pd.DataFrame()
    text = zf.read(names[0]).decode("utf-8-sig", errors="replace")
    if not text.strip():
        return pd.DataFrame()
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)


def _action_rows(symbols, ex_dates, purposes, source: str) -> pd.DataFrame:
    rows = []
    for sym, ex, purpose in zip(symbols, ex_dates, purposes):
        if not sym or pd.isna(ex):
            continue
        parsed = parse_purpose(purpose)
        rows.append({"symbol": sym, "ex_date": ex, "kind": parsed.kind, "factor": parsed.factor,
                     "description": str(purpose).strip(), "source": source})
    return pd.DataFrame(rows, columns=ACTION_COLUMNS)


def actions_from_bc_frame(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    df = raw.rename(columns=lambda c: str(c).strip().upper())
    df = df[df.get("SERIES", pd.Series("", index=df.index)).astype(str).str.strip().str.upper().isin(_ACTION_SERIES)]
    ex = [(_parse_date(r.get("EX_DT")) if not pd.isna(_parse_date(r.get("EX_DT")))
           else _parse_date(r.get("RECORD_DT")) if not pd.isna(_parse_date(r.get("RECORD_DT")))
           else _parse_date(r.get("BC_STRT_DT"))) for r in df.to_dict("records")]
    syms = df["SYMBOL"].astype(str).str.strip().str.upper().tolist()
    return _action_rows(syms, ex, df["PURPOSE"].tolist(), "bc")


def collect_bc_actions(zip_paths: list[Path]) -> pd.DataFrame:
    frames = []
    for p in zip_paths:
        try:
            with zipfile.ZipFile(p) as zf:
                frames.append(actions_from_bc_frame(read_bc_member(zf)))
        except (zipfile.BadZipFile, OSError, pd.errors.ParserError) as exc:
            print(f"Skipped {Path(p).name}: {exc}")
    if not frames:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(["symbol", "ex_date", "description"]).reset_index(drop=True)


def actions_from_corporate_actions_table(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    ex = pd.to_datetime(df["ex_date"], errors="coerce").dt.normalize()
    syms = df["symbol"].astype(str).str.strip().str.upper().tolist()
    return _action_rows(syms, ex.tolist(), df["description"].fillna("").tolist(), "bc")


def find_pr_zips(root: Path) -> list[Path]:
    root = Path(root)
    found = set((root / "Input" / "archive").glob("PR*.zip"))
    found |= set((root / "Input" / "archive" / "backfill" / "pr").glob("PR*.zip"))
    downloads = root / "Input" / "downloads"
    if downloads.exists():
        found |= set(downloads.rglob("PR*.zip"))
    return sorted(found)
```

(Add `import io` to the imports at the top of the module; the `ex` list comprehension may be written as a small helper for readability — behaviour must match the tests.)

In `Scripts/pr_report_ingestion.py`:
- in `_parse_corporate_actions`, replace the keyword loop with `from price_adjustment import parse_purpose` + a mapping `{"rights": "rights_issue", "demerger": "merger_demerger"}` (other kinds keep their name); set `ratio_from = 1.0` and `ratio_to = 1.0 / factor` when `factor` is not None, else `1.0/1.0`;
- in `parse_pr_zip`, replace each `_read_member(archive, "bc" + ...)` style call with a case-insensitive lookup that accepts both `trade_date.strftime("%d%m%Y")` and `trade_date.strftime("%d%m%y")` (e.g. a helper `_read_member_any(archive, prefix, trade_date, ext)`), for `an`, `bm`, `bc`, `bh`, `hl`, `tt`.

- [ ] **Step 4: Run tests** — `... -m pytest tests/test_price_adjustment_sources.py tests/test_price_adjustment_parse.py tests/test_pr_report_ingestion.py -v` → PASS.
- [ ] **Step 5: Commit** — `feat(adjust): collect corporate actions from PR zips (both member styles) and store parsed ratios`

---

### Task 3: Detect splits/bonuses from market-cap face value and issue size

**Files:**
- Modify: `Scripts/price_adjustment.py`
- Test: `tests/test_price_adjustment_mcap.py`

**Interfaces:**
- Produces:
  - `CLEAN_BONUS_RATIOS = (1.25, 4/3, 1.5, 5/3, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 11.0)` (issue-size multipliers `(a+b)/b` for common bonuses)
  - `read_mcap_frames(root: Path, zip_paths: list[Path]) -> pd.DataFrame` — columns `file_date, symbol, face_value, issue_size` from `Input/archive/mcap*.csv`, `Input/daily/mcap*.csv`, `Input/downloads/**/mcap*.csv` and `MCAP*.csv` members of PR zips; drops blank-series summary rows (as `build_database.parse_market_cap_frame` does); `file_date` from the `Trade Date` column.
  - `actions_from_mcap(frames: pd.DataFrame, tol: float = 0.01) -> pd.DataFrame` (`ACTION_COLUMNS`, `source="mcap"`) — per symbol, compare consecutive file dates: face value change `fv0 → fv1` ⇒ `kind="split"` (or `"consolidation"` if fv1 > fv0), `factor = fv1 / fv0`; else issue size ratio `r = is1 / is0` within `tol` of a `CLEAN_BONUS_RATIOS` value ⇒ `kind="bonus"`, `factor = 1 / r`; `ex_date` = the later file date; `description` e.g. `"FV 2.0->1.0"` / `"ISSUE x3.00"`.

- [ ] **Step 1: Write the failing test** — `tests/test_price_adjustment_mcap.py`:

```python
from __future__ import annotations

import math

import pandas as pd

from price_adjustment import actions_from_mcap, read_mcap_frames

HDR = "Trade Date,Symbol,Series,Security Name,Category,Last Trade Date,Face Value(Rs.),Issue Size,Close Price/Paid up value(Rs.),Market Cap(Rs.)\n"


def test_detects_split_bonus_and_ignores_small_issuance():
    f = pd.DataFrame({
        "file_date": pd.to_datetime(["2026-08-20", "2026-08-21"] * 3),
        "symbol": ["GOODLUCK", "GOODLUCK", "KIRLPNU", "KIRLPNU", "QIPCO", "QIPCO"],
        "face_value": [2.0, 2.0, 2.0, 1.0, 10.0, 10.0],
        "issue_size": [10_000_000, 30_000_000, 64_000_000, 128_000_000, 1_000_000, 1_060_000],
    })
    a = actions_from_mcap(f).set_index("symbol")
    assert a.loc["GOODLUCK", "kind"] == "bonus" and math.isclose(a.loc["GOODLUCK", "factor"], 1 / 3)
    assert a.loc["KIRLPNU", "kind"] == "split" and math.isclose(a.loc["KIRLPNU", "factor"], 0.5)
    assert str(a.loc["KIRLPNU", "ex_date"].date()) == "2026-08-21"
    assert "QIPCO" not in a.index


def test_read_mcap_frames_from_files(tmp_path):
    d = tmp_path / "Input" / "archive"
    d.mkdir(parents=True)
    (d / "mcap20082026.csv").write_text(HDR + "20 AUG 2026,GOODLUCK,EQ,GOODLUCK INDIA,Listed,20 AUG 2026,2.00,10000000,1439.40,1.0\n"
                                        "20 AUG 2026,Total     ,  ,   ,   ,   ,0.00,0,0.00,9.0\n")
    (d / "mcap21082026.csv").write_text(HDR + "21 AUG 2026,GOODLUCK,EQ,GOODLUCK INDIA,Listed,21 AUG 2026,2.00,30000000,490.90,1.0\n")
    f = read_mcap_frames(tmp_path, [])
    assert set(f["symbol"]) == {"GOODLUCK"} and len(f) == 2
    assert f["issue_size"].max() == 30_000_000
```

- [ ] **Step 2: Run to verify failure** → FAIL.

- [ ] **Step 3: Implement** — append to `Scripts/price_adjustment.py`:

```python
CLEAN_BONUS_RATIOS = (1.25, 4 / 3, 1.5, 5 / 3, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 11.0)


def _mcap_frame(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), dtype=str, skipinitialspace=True)
    df.columns = [re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_") for c in df.columns]
    fv_col = next((c for c in df.columns if c.startswith("face_value")), None)
    is_col = next((c for c in df.columns if c.startswith("issue_size")), None)
    if not fv_col or not is_col or "symbol" not in df.columns:
        return pd.DataFrame(columns=["file_date", "symbol", "face_value", "issue_size"])
    if "series" in df.columns:
        df = df[df["series"].fillna("").astype(str).str.strip() != ""]
    num = lambda s: pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")
    return pd.DataFrame({
        "file_date": pd.to_datetime(df["trade_date"].astype(str).str.strip(), format="%d %b %Y", errors="coerce"),
        "symbol": df["symbol"].astype(str).str.strip().str.upper(),
        "face_value": num(df[fv_col]),
        "issue_size": num(df[is_col]),
    }).dropna(subset=["file_date"])


def read_mcap_frames(root: Path, zip_paths: list[Path]) -> pd.DataFrame:
    root = Path(root)
    paths = set((root / "Input" / "archive").glob("mcap*.csv")) | set((root / "Input" / "daily").glob("mcap*.csv"))
    downloads = root / "Input" / "downloads"
    if downloads.exists():
        paths |= set(downloads.rglob("mcap*.csv"))
    frames = []
    for p in sorted(paths):
        try:
            frames.append(_mcap_frame(Path(p).read_text(encoding="utf-8-sig", errors="replace")))
        except Exception as exc:
            print(f"Skipped {Path(p).name}: {exc}")
    for z in zip_paths:
        try:
            with zipfile.ZipFile(z) as zf:
                for n in zf.namelist():
                    if Path(n).name.lower().startswith("mcap") and n.lower().endswith(".csv"):
                        frames.append(_mcap_frame(zf.read(n).decode("utf-8-sig", errors="replace")))
        except (zipfile.BadZipFile, OSError) as exc:
            print(f"Skipped {Path(z).name}: {exc}")
    if not frames:
        return pd.DataFrame(columns=["file_date", "symbol", "face_value", "issue_size"])
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(["file_date", "symbol"], keep="last").sort_values(["symbol", "file_date"]).reset_index(drop=True)


def actions_from_mcap(frames: pd.DataFrame, tol: float = 0.01) -> pd.DataFrame:
    rows = []
    if frames is None or frames.empty:
        return pd.DataFrame(columns=ACTION_COLUMNS)
    f = frames.sort_values(["symbol", "file_date"])
    for sym, g in f.groupby("symbol", sort=False):
        g = g.dropna(subset=["face_value", "issue_size"])
        prev = None
        for cur in g.itertuples(index=False):
            if prev is not None and prev.face_value > 0 and prev.issue_size > 0:
                if cur.face_value != prev.face_value:
                    factor = cur.face_value / prev.face_value
                    kind = "consolidation" if factor > 1 else "split"
                    rows.append({"symbol": sym, "ex_date": cur.file_date, "kind": kind, "factor": factor,
                                 "description": f"FV {prev.face_value}->{cur.face_value}", "source": "mcap"})
                else:
                    r = cur.issue_size / prev.issue_size
                    match = next((c for c in CLEAN_BONUS_RATIOS if abs(r / c - 1) <= tol), None)
                    if match is not None:
                        rows.append({"symbol": sym, "ex_date": cur.file_date, "kind": "bonus", "factor": 1 / match,
                                     "description": f"ISSUE x{match:.2f}", "source": "mcap"})
            prev = cur
    return pd.DataFrame(rows, columns=ACTION_COLUMNS)
```

- [ ] **Step 4: Run tests** → PASS. **Step 5: Commit** — `feat(adjust): detect splits and bonuses from market-cap face value and issue size`

---

### Task 4: Gap candidates, reconciliation and overrides

**Files:**
- Modify: `Scripts/price_adjustment.py`
- Create: `Input/reference/adjustments_override.yaml` (empty template, committed)
- Test: `tests/test_price_adjustment_reconcile.py`

**Interfaces:**
- Produces:
  - `ADJUSTMENT_COLUMNS = ["symbol", "ex_date", "kind", "factor", "source", "confidence", "applied", "description"]`
  - `gap_candidates(prices: pd.DataFrame, low: float = 0.6, high: float = 1.6) -> pd.DataFrame` — rows where `close_price / previous close_price` (same symbol, previous row) is `< low` or `> high`; columns `symbol, ex_date, gap_ratio`.
  - `load_overrides(path: Path) -> pd.DataFrame` — YAML list of `{symbol, ex_date, factor, note}`; `factor: null` suppresses an event; missing file → empty frame.
  - `reconcile(bc: pd.DataFrame, mcap: pd.DataFrame, gaps: pd.DataFrame, overrides: pd.DataFrame, window_days: int = 5, factor_tol: float = 0.02, gap_tol: float = 0.2) -> pd.DataFrame` (`ADJUSTMENT_COLUMNS`):
    - every bc row becomes an event; adjusting kinds with a factor → `applied=True`; `confidence="confirmed"` when an mcap event (same symbol, |Δdate| ≤ `window_days`, factor within `factor_tol` relative) or a gap (|Δdate| ≤ `window_days`, `abs(gap_ratio/factor − 1) ≤ gap_tol`) agrees, else `"single_source"`; non-adjusting kinds → `applied=False`, `confidence="not_adjusting"`, `factor=NaN`.
    - mcap events not matched to a bc adjusting event → `applied=True`, `source="mcap"`, confidence as above (gap agreement → `"confirmed"`, else `"single_source"`); when a bc event and an mcap event match, keep one row with `source="bc+mcap"`, the bc factor, and the bc `ex_date`.
    - gaps not matched by any applied event → `kind="unexplained_gap"`, `factor=gap_ratio`, `applied=False`, `confidence="unconfirmed"`.
    - overrides applied last: matching `(symbol, ex_date)` replaced (`factor=None` → `applied=False`, `confidence="suppressed"`); non-matching override rows added with `source="override"`, `confidence="override"`, `applied=True`.
    - If two applied events for the same symbol fall within `window_days` and have factors within `factor_tol`, keep only the earliest (duplicate announcement guard).
    - Any of `bc`, `mcap`, `gaps`, `overrides` may be `pd.DataFrame()` with **no columns** (the tests pass that); treat such inputs as empty.

- [ ] **Step 1: Write the failing test** — `tests/test_price_adjustment_reconcile.py`:

```python
from __future__ import annotations

import math

import pandas as pd

from price_adjustment import gap_candidates, load_overrides, reconcile


def _a(sym, d, kind, factor, source):
    return {"symbol": sym, "ex_date": pd.Timestamp(d), "kind": kind, "factor": factor, "description": kind, "source": source}


def test_gap_candidates():
    p = pd.DataFrame({"symbol": ["G"] * 3 + ["X"] * 2,
                      "trade_date": pd.to_datetime(["2026-08-19", "2026-08-20", "2026-08-21", "2026-08-20", "2026-08-21"]),
                      "close_price": [1363.3, 1439.4, 490.9, 100.0, 104.0]})
    g = gap_candidates(p)
    assert g["symbol"].tolist() == ["G"] and math.isclose(g["gap_ratio"].iloc[0], 490.9 / 1439.4)


def test_reconcile_confirms_and_merges_sources():
    bc = pd.DataFrame([_a("GOODLUCK", "2026-08-21", "bonus", 1 / 3, "bc"),
                       _a("SIYSIL", "2026-08-21", "pref_bonus", None, "bc")])
    mcap = pd.DataFrame([_a("GOODLUCK", "2026-08-21", "bonus", 1 / 3, "mcap"),
                         _a("KIRLPNU", "2026-08-18", "split", 0.5, "mcap")])
    gaps = pd.DataFrame({"symbol": ["GOODLUCK", "HEG"], "ex_date": pd.to_datetime(["2026-08-21", "2026-09-01"]),
                         "gap_ratio": [490.9 / 1439.4, 0.33]})
    out = reconcile(bc, mcap, gaps, pd.DataFrame()).set_index("symbol")
    g = out.loc["GOODLUCK"]
    assert g["applied"] and g["confidence"] == "confirmed" and g["source"] == "bc+mcap" and math.isclose(g["factor"], 1 / 3)
    assert out.loc["KIRLPNU", "applied"] and out.loc["KIRLPNU", "source"] == "mcap"
    assert not out.loc["SIYSIL", "applied"] and out.loc["SIYSIL", "confidence"] == "not_adjusting"
    assert out.loc["HEG", "kind"] == "unexplained_gap" and not out.loc["HEG", "applied"]


def test_overrides_suppress_and_add(tmp_path):
    y = tmp_path / "o.yaml"
    y.write_text("- {symbol: KIRLPNU, ex_date: 2026-08-18, factor: null, note: wrong}\n"
                 "- {symbol: NEWCO, ex_date: 2021-01-04, factor: 0.5, note: manual}\n")
    ov = load_overrides(y)
    mcap = pd.DataFrame([_a("KIRLPNU", "2026-08-18", "split", 0.5, "mcap")])
    out = reconcile(pd.DataFrame(), mcap, pd.DataFrame(), ov).set_index("symbol")
    assert not out.loc["KIRLPNU", "applied"] and out.loc["KIRLPNU", "confidence"] == "suppressed"
    assert out.loc["NEWCO", "applied"] and out.loc["NEWCO", "source"] == "override"
    assert load_overrides(tmp_path / "missing.yaml").empty
```

- [ ] **Step 2: Run to verify failure** → FAIL.
- [ ] **Step 3: Implement** `gap_candidates`, `load_overrides` (use `yaml.safe_load`; PyYAML is already in requirements), and `reconcile` exactly per the Interfaces rules above. Keep `reconcile` readable: build a list of dict rows, matching with small helper functions (`_near(a_date, b_date)`, `_same_factor(f1, f2)`); return `pd.DataFrame(rows, columns=ADJUSTMENT_COLUMNS)` sorted by `symbol, ex_date`. Create `Input/reference/adjustments_override.yaml` containing only comment lines explaining the format, e.g.:

```yaml
# Manual split/bonus corrections. Each item: {symbol, ex_date: YYYY-MM-DD, factor: <pre-ex price multiplier> or null to suppress, note}
# Example: - {symbol: ABC, ex_date: 2024-03-15, factor: 0.5, note: "1:1 bonus missing from NSE file"}
[]
```

- [ ] **Step 4: Run tests** → PASS. **Step 5: Commit** — `feat(adjust): reconcile bc/mcap/gap evidence with overrides`

---

### Task 5: Cumulative factors, adjusted columns and indicator input

**Files:**
- Modify: `Scripts/price_adjustment.py`
- Test: `tests/test_price_adjustment_apply.py`

**Interfaces:**
- Consumes: `ADJUSTMENT_COLUMNS` rows (Task 4).
- Produces:
  - `PRICE_COLS = ["open_price", "high_price", "low_price", "close_price", "last_price", "avg_price"]`
  - `cumulative_price_factor(prices: pd.DataFrame, adjustments: pd.DataFrame) -> pd.Series` — aligned to `prices.index`; for each row, product of `factor` over **applied** events of that symbol with `ex_date > trade_date`; 1.0 when none. Vectorised per symbol with `numpy.searchsorted` on sorted ex_dates and a suffix product.
  - `apply_adjustments(prices: pd.DataFrame, adjustments: pd.DataFrame) -> pd.DataFrame` — returns a copy with `price_factor`, `adj_<col>` for `PRICE_COLS`, `adj_volume = volume / price_factor`, `adj_delivery_qty = delivery_qty / price_factor`, and `adj_prev_close` = previous row's `adj_close_price` within symbol (sorted by date), first row `prev_close × price_factor`. Any pre-existing `adj_*`/`price_factor` columns are dropped first.
  - `indicator_input(adjusted: pd.DataFrame) -> pd.DataFrame` — copy where each `PRICE_COLS` column, `prev_close`, `volume`, `delivery_qty` is replaced by its `adj_` value, and all `adj_*` and `price_factor` columns are dropped (so `calc_indicators` sees normal column names).

- [ ] **Step 1: Write the failing test** — `tests/test_price_adjustment_apply.py`:

```python
from __future__ import annotations

import math

import pandas as pd

from price_adjustment import apply_adjustments, cumulative_price_factor, indicator_input

PRICES = pd.DataFrame({
    "symbol": ["GOODLUCK"] * 4 + ["TCC"] * 3,
    "trade_date": pd.to_datetime(["2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24",
                                  "2026-09-02", "2026-09-03", "2026-09-04"]),
    "open_price": [1340.0, 1385.0, 493.2, 486.8, 500.0, 505.0, 102.0],
    "high_price": [1370.0, 1445.0, 494.4, 490.0, 510.0, 512.0, 104.0],
    "low_price": [1330.0, 1380.0, 469.8, 470.0, 495.0, 500.0, 100.0],
    "close_price": [1363.3, 1439.4, 490.9, 477.7, 505.0, 510.0, 103.0],
    "last_price": [1363.0, 1439.0, 490.4, 477.5, 505.0, 510.0, 103.0],
    "avg_price": [1360.0, 1420.0, 483.5, 480.0, 503.0, 508.0, 102.0],
    "prev_close": [1330.0, 1363.3, 1439.4, 490.9, 500.0, 505.0, 510.0],
    "volume": [100.0, 120.0, 646400.0, 300000.0, 10.0, 12.0, 70.0],
    "delivery_qty": [50.0, 60.0, 198936.0, 150000.0, 5.0, 6.0, 35.0],
    "delivery_pct": [50.0, 50.0, 30.78, 50.0, 50.0, 50.0, 50.0],
})
ADJ = pd.DataFrame({"symbol": ["GOODLUCK", "TCC", "TCC"],
                    "ex_date": pd.to_datetime(["2026-08-21", "2026-09-04", "2026-01-01"]),
                    "kind": ["bonus", "split", "rights"], "factor": [1 / 3, 0.2, None],
                    "source": ["bc", "bc", "bc"], "confidence": ["confirmed"] * 3,
                    "applied": [True, True, False], "description": ["", "", ""]})


def test_cumulative_factor_only_before_ex_date_and_only_applied():
    f = cumulative_price_factor(PRICES, ADJ).tolist()
    assert [round(x, 6) for x in f] == [round(1 / 3, 6)] * 2 + [1.0, 1.0] + [0.2, 0.2, 1.0]


def test_adjusted_series_has_no_fake_crash_and_real_ex_date_move():
    a = apply_adjustments(PRICES, ADJ)
    g = a[a.symbol == "GOODLUCK"].set_index("trade_date")
    assert math.isclose(g.loc["2026-08-20", "adj_close_price"], 1439.4 / 3, rel_tol=1e-9)
    ex = g.loc["2026-08-21"]
    day_move = ex["adj_close_price"] / ex["adj_prev_close"] - 1
    assert -0.05 < day_move < 0.05                       # ≈ +2.3%, not -66%
    assert math.isclose(g.loc["2026-08-20", "adj_volume"], 360.0)
    assert g.loc["2026-08-21", "delivery_pct"] == 30.78  # unchanged
    assert g.loc["2026-08-20", "close_price"] == 1439.4  # raw kept


def test_indicator_input_swaps_in_adjusted_values():
    ind = indicator_input(apply_adjustments(PRICES, ADJ))
    assert not any(c.startswith("adj_") for c in ind.columns) and "price_factor" not in ind.columns
    t = ind[ind.symbol == "TCC"].set_index("trade_date")
    assert math.isclose(t.loc["2026-09-03", "close_price"], 102.0)
    assert math.isclose(t.loc["2026-09-04", "prev_close"], 102.0)


def test_reapplying_drops_stale_columns():
    once = apply_adjustments(PRICES, ADJ)
    twice = apply_adjustments(once, ADJ)
    assert list(once.columns) == list(twice.columns)
```

- [ ] **Step 2: Run to verify failure** → FAIL.
- [ ] **Step 3: Implement** per Interfaces (sort by `symbol, trade_date` internally but return rows in the input order with the input index). For `cumulative_price_factor`: build `{symbol: (sorted_ex_dates ndarray, suffix_products ndarray)}` from applied events with non-null factors; for each symbol's rows use `np.searchsorted(ex_dates, trade_dates, side="right")` and index into `suffix = np.append(np.cumprod(factors[::-1])[::-1], 1.0)`.
- [ ] **Step 4: Run tests** → PASS. **Step 5: Commit** — `feat(adjust): cumulative factors, adjusted OHLCV columns and indicator input`

---

### Task 6: One entry point, wired into build and append

**Files:**
- Modify: `Scripts/price_adjustment.py` (entry point)
- Modify: `Scripts/build_database.py` (`main`, `write_database`)
- Modify: `Scripts/append_database.py` (append flow)
- Test: `tests/test_price_adjustment_pipeline.py`

**Interfaces:**
- Consumes: everything above; `universe.apply_symbol_changes(prices, changes)` and `symbol_changes.parse_symbol_changes(path)` (Step 2a).
- Produces:
  - `adjust_prices(prices: pd.DataFrame, root: Path, extra_actions: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]` → `(adjusted_prices, adjustments)`: `zips = find_pr_zips(root)`; `bc = collect_bc_actions(zips)` + `extra_actions` (de-duplicated on symbol, ex_date, description); `mcap = actions_from_mcap(read_mcap_frames(root, zips))`; if `root/Input/reference/symbolchange.csv` exists, rename action symbols to current symbols using `apply_symbol_changes` on a frame with `trade_date = ex_date` (so events keyed on pre-rename symbols still join); `gaps = gap_candidates(prices)`; `overrides = load_overrides(root/Input/reference/adjustments_override.yaml)`; `adjustments = reconcile(bc, mcap, gaps, overrides)`; `return apply_adjustments(prices, adjustments), adjustments`.
  - `build_database.write_database(..., price_adjustments: pd.DataFrame | None = None)` writes a `price_adjustments` table (created even when empty, with `ADJUSTMENT_COLUMNS`).
  - `build_database.main()`: after `prices = build_prices(universe)` → `prices, adjustments = adjust_prices(prices, ROOT_DIR)`; `calc_indicators(indicator_input(prices), ...)`; everything that previously received `prices` for **price-level** use (e.g. `enrich_deals`, `build_master`) keeps receiving the adjusted frame (raw columns are unchanged in it); pass `price_adjustments=adjustments` to `write_database`.
  - `append_database`: after merging `existing_prices` + `new_prices`, drop any `adj_*`/`price_factor` columns, then `prices, adjustments = adjust_prices(prices, ROOT_DIR, extra_actions=actions_from_corporate_actions_table(_load_table("corporate_actions")) if available else None)`; `calc_indicators(indicator_input(prices), ...)`; pass `price_adjustments=adjustments` to `write_database`.
  - Print one summary line in both paths: `Price adjustments: <n applied> applied (<n confirmed> confirmed), <n unconfirmed> unconfirmed gaps, <n not_adjusting> non-adjusting actions`.

- [ ] **Step 1: Write the failing test** — `tests/test_price_adjustment_pipeline.py`: build a `tmp_path` root with `Input/archive/PR210826.zip` containing `bc21082026.csv` (GOODLUCK `BONUS 2:1`, ex 2026-08-21) and two mcap files (issue size 1e7 → 3e7), plus `Input/reference/symbolchange.csv` mapping `GOODLUCKOLD,GOODLUCK,01-JAN-2026`; a price frame (reuse `PRICES` from Task 5's test, GOODLUCK rows only) → `adjust_prices(prices, tmp_path)` returns adjusted rows with `adj_close_price` on 2026-08-20 ≈ 1439.4/3 and an adjustments frame whose GOODLUCK row has `source == "bc+mcap"` and `confidence == "confirmed"`. Second test: an action keyed on `GOODLUCKOLD` dated 2025-06-01 passed via `extra_actions` is renamed to `GOODLUCK`.

- [ ] **Step 2: Run to verify failure** → FAIL.
- [ ] **Step 3: Implement** the entry point and the wiring described above. In `write_database`, register and `CREATE TABLE price_adjustments AS SELECT * FROM price_adjustments_df` (empty frame with `ADJUSTMENT_COLUMNS` when None). Do not add `price_adjustments` to `PRESERVED_TABLES` (it is rebuilt from files every run).
- [ ] **Step 4: Run tests** — `... -m pytest -q tests/test_price_adjustment_pipeline.py tests/test_price_adjustment_*.py tests/test_multi_day_catchup.py tests/test_pipeline_recovery.py tests/test_transactional_append.py tests/test_indicators_golden.py tests/test_universe.py` → PASS.
- [ ] **Step 5: Commit** — `feat(adjust): adjust prices before indicators in build and append; persist price_adjustments`

---

### Task 7: Readers that compare prices across dates use adjusted columns

**Files:**
- Create: `Scripts/price_views.py`
- Modify (audit-driven): `Scripts/minervini_geometry.py`, `Scripts/institutional_attribution.py`, `Scripts/midsml_breadth.py`, `App/pages/sma_template.py`, `App/market_commentary_engine.py`, `App/thematic_engine.py`, `Scripts/materialize_decision_tables.py` — only where a query reads `prices_daily` OHLC/volume across multiple dates.
- Test: `tests/test_price_views.py`

**Interfaces:**
- Produces: `price_views.ohlcv_columns(con, alias: str = "") -> dict[str, str]` returning SQL expressions keyed `open_price, high_price, low_price, close_price, prev_close, volume, delivery_qty` — `COALESCE({a}adj_close_price, {a}close_price)` etc. when `prices_daily` has the `adj_` columns (checked via `PRAGMA table_info('prices_daily')` / `information_schema.columns`), else the raw column names. Works on read-only connections and on today's DB (no adj columns).
- Rule for each reader: if the query compares or aggregates prices/volumes across different dates (returns, highs/lows, swing points, forward returns, moving averages, ranges), use `ohlcv_columns`. Queries that only read the latest single day or only dates/symbols stay as they are. For `institutional_attribution` forward returns from a deal price: divide the later adjusted close by `deal_price × price_factor_on_deal_date` (get `price_factor` via the same helper — add key `price_factor` returning `COALESCE(price_factor, 1.0)` or `1.0`).

- [ ] **Step 1: Write the failing test** — `tests/test_price_views.py`: create a DuckDB in `tmp_path` with a `prices_daily` table without adj columns → `ohlcv_columns(con)["close_price"] == "close_price"`; add `adj_close_price` and `price_factor` columns → expression contains `COALESCE(adj_close_price, close_price)`; with `alias="p."` expressions are prefixed; open the DB `read_only=True` and call it successfully.
- [ ] **Step 2: Run to verify failure** → FAIL. **Step 3: Implement** `price_views.py`.
- [ ] **Step 4: Audit and migrate** — `grep -n "prices_daily" <files above>`; for every multi-date query, switch column references through `ohlcv_columns`. List every query you changed and every one you left (with a one-line reason) in the report. Run each touched module's tests: `tests/test_minervini_geometry.py tests/test_institutional_attribution.py tests/test_midsml_breadth.py tests/test_sma_template.py tests/test_materialize_decisions.py tests/test_thematic_44.py` (plus any other test file importing a touched module).
- [ ] **Step 5: Commit** — `feat(adjust): multi-date price readers use adjusted columns when present`

---

### Task 8: Daily download fetches `ind_close_all`

**Files:**
- Modify: `Scripts/download_nse_reports.py` (`report_specs`, `_write_auxiliary_fallback`)
- Test: extend `tests/test_ingestion_manifest.py` or create `tests/test_download_specs.py`

**Interfaces:**
- Produces: `report_specs(day, discovered)` includes `ReportSpec("all indices", f"ind_close_all_{DDMMYYYY}.csv", (f"{NSE_ARCHIVES}/content/indices/ind_close_all_{DDMMYYYY}.csv",), ("Index Name", "Closing Index Value"))`; `_write_auxiliary_fallback` writes the header line `Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield` for it (so a missing file never blocks the day, and the Step-2a parser yields 0 rows with its warning). The file is archived with the others by the existing flow (check `archive_daily_inputs` / install paths pick it up by pattern; if they use an allow-list, add `ind_close_all_*.csv`).

- [ ] **Step 1: Write the failing test** — assert the spec exists with that output name, URL and required columns for `datetime(2026, 9, 25)`, and that `_write_auxiliary_fallback` for it writes a CSV whose header parses with `index_history.parse_ind_close_all` to 0 rows without raising.
- [ ] **Step 2: Run to verify failure** → FAIL. **Step 3: Implement.** Check `validate_stage`/`prepare_session_manifest`/`archive_daily_inputs` for hard-coded expected file lists and include the new file where needed; run `tests/test_ingestion_manifest.py tests/test_pipeline_recovery.py tests/test_multi_day_catchup.py tests/test_ci_contract.py`.
- [ ] **Step 4: Run tests** → PASS. **Step 5: Commit** — `feat(download): fetch ind_close_all in the daily NSE download`

---

### Task 9: Read-only dry run against the real data

**Files:**
- Create: `Scripts/adjustment_report.py`

**Interfaces:**
- Produces: CLI `python Scripts/adjustment_report.py [--db PATH]` that loads `prices_daily` (read-only) from `--db` (default `config.DB_PATH`), runs `adjust_prices(prices, ROOT_DIR, extra_actions=actions_from_corporate_actions_table(corporate_actions table))`, and prints: counts by `confidence`/`applied`; the applied events table (symbol, ex_date, kind, factor, source, confidence); the 20 largest `unexplained_gap` rows; and for GOODLUCK, PGIL, TDPOWERSYS, KIRLPNU, TCC the raw vs adjusted close on the day before and on the ex-date, plus the adjusted ex-date move. Writes nothing.

- [ ] **Step 1: Implement** the script (no test file needed beyond a smoke test `tests/test_adjustment_report.py` that runs `main(["--db", <tmp DuckDB with a tiny prices_daily + corporate_actions>])` and asserts exit 0).
- [ ] **Step 2: Run against the live DB (read-only)** from the worktree:

```bash
MP_DB_PATH="D:/Sid/MarketPulse2.0/Database/marketpulse.duckdb" D:/Sid/MarketPulse2.0/.venv/Scripts/python Scripts/adjustment_report.py --db "D:/Sid/MarketPulse2.0/Database/marketpulse.duckdb"
```

Note: the worktree's `Input/` only holds tracked files; pass `ROOT_DIR` resolution through `config` — if the report finds no PR zips / mcap files because they live only in the main folder's untracked `Input/archive`, add a `--root D:/Sid/MarketPulse2.0` option and re-run with it. Expected: GOODLUCK bonus (1/3), PGIL bonus (1/2), TDPOWERSYS and KIRLPNU splits (1/2), TCC split (0.2) all `applied`; each ex-date adjusted move within ±20%; the number of `unexplained_gap` rows reported (these are mostly pre-July-2026 events awaiting the Step 2a backfill PR zips).
- [ ] **Step 3: Commit** — `feat(adjust): read-only adjustment dry-run report`
- [ ] **Step 4: Report** the dry-run output (trimmed) in the task report: applied/confirmed/unconfirmed counts, the five named symbols' before/after, and the unexplained-gap count.
