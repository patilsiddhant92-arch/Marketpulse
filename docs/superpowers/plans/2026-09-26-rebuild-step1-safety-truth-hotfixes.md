# Rebuild Step 1 — Safety & Truth Hotfixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current React/FastAPI app stop showing fabricated or wrong numbers, close the SQL-injection hole, fix three warehouse data bugs, and get the test suite green — before the larger rebuild starts.

**Architecture:** Surgical changes to existing files only. Server row-shaping logic is pulled into small pure functions so it can be unit-tested without the 1.1 GB DB. Frontend changes are limited to rendering `null` as "—" and relabelling; no redesign (that is Step 5/6 of the spec).

**Tech Stack:** Python 3.12, FastAPI, DuckDB, pandas, pytest; React 18 + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-09-26-marketpulse-professional-rebuild-design.md` (§10 step 1, §6.3 honesty rules, Appendix A).

## Global Constraints

- NULL stays NULL: the API never substitutes 50 / 45 / 0 / 2.0 / 3.5 / CMP×k for a missing value; the UI renders `null` as `—` (spec §6.3).
- All SQL values are bound parameters or validated against `^[A-Z0-9&\-_.]{1,20}$` (spec §8).
- Tests must never open `Database/marketpulse_user.duckdb` for writing; use `tmp_path` (spec §11).
- Tests that depend on live market data carry `@pytest.mark.realdb` and are deselected by default (spec §11).
- Working directory for all commands: `D:\Sid\MarketPulse2.0`. Python: `.venv/Scripts/python`. Use the Bash tool.
- The branch `feat/truth-contract` has pre-existing uncommitted edits in many of these files. **Stage only the hunks you changed** (`git add -p <file>`), never `git add -A`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Do not run any DB **writer** (append/refresh/build) unless the task says so and the user has confirmed; writers need the UI closed.

---

### Task 1: Green, isolated test suite

**Files:**
- Create: `pytest.ini`
- Modify: `tests/test_stock_drawer_features.py` (user-DB tests → `tmp_path`)
- Modify: `tests/test_ui_recovery_contracts.py` (delete 2 stale tests, update launcher assertion)
- Delete: `tests/test_score_comparison.py` (module `Scripts/compare_score_versions.py` was removed in `bbe8ef4`)
- Modify: `tests/test_audit_health_check.py:215`, `tests/test_midsml_breadth.py:109` (negative-zero regex)
- Modify: `tests/test_momentum_contract.py:41` (label assertion)
- Modify: `tests/test_action_desk.py` (mark 3 live-data tests `realdb`)
- Modify: `Scripts/requirements.txt`, `Scripts/_ensure_venv.bat`

**Interfaces:**
- Produces: pytest marker `realdb`; default run excludes it (`-m "not realdb"`). Later tasks use `@pytest.mark.realdb` for live-DB behaviour tests.

- [ ] **Step 1: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
markers =
    realdb: needs the live Database/marketpulse.duckdb and asserts on live market data; run with -m realdb
addopts = -m "not realdb"
```

- [ ] **Step 2: Isolate the user-DB tests** — in `tests/test_stock_drawer_features.py` replace `test_user_notes_roundtrip` and `test_user_watchlist_toggle` with:

```python
def test_user_notes_roundtrip(tmp_path):
    user_db = tmp_path / "user.duckdb"
    test_symbol = "TEST_STOCK"
    test_note = "Testing local setup breakout thesis at 1450"
    save_stock_note(user_db, test_symbol, test_note)
    assert load_stock_note(user_db, test_symbol) == test_note


def test_user_watchlist_toggle(tmp_path):
    user_db = tmp_path / "user.duckdb"
    test_symbol = "TEST_WL_STOCK"
    assert is_in_watchlist(user_db, 1, test_symbol) is False
    assert toggle_watchlist_symbol(user_db, 1, test_symbol) is True
    assert is_in_watchlist(user_db, 1, test_symbol) is True
    assert toggle_watchlist_symbol(user_db, 1, test_symbol) is False
    assert is_in_watchlist(user_db, 1, test_symbol) is False
```

Then delete the now-unused module constant `USER_DB = Path("Database/marketpulse_user.duckdb")`.

- [ ] **Step 3: Run the two tests**

Run: `.venv/Scripts/python -m pytest tests/test_stock_drawer_features.py -k "notes_roundtrip or watchlist_toggle" -v`
Expected: PASS. If `save_stock_note` / `toggle_watchlist_symbol` fail on a fresh file because the settings table does not exist, open `App/ui/stock_drawer.py`, find those functions, and make them create `portfolio_settings(setting_key VARCHAR PRIMARY KEY, setting_value VARCHAR, updated_at TIMESTAMP)` with `CREATE TABLE IF NOT EXISTS` before writing; re-run until PASS.

- [ ] **Step 4: Remove stale tests** — in `tests/test_ui_recovery_contracts.py` delete the functions `test_production_today_uses_decision_panel_not_stub_snapshot` and `test_screener_page_reads_focused_v2_without_fundamentals` (their target files `App/pages/today.py` and `App/pages/screener.py` were deleted in `bbe8ef4`). In `test_launch_batch_selects_a_free_port_for_repeatable_startups` change the last assertion to:

```python
    assert 'set "URL=http://127.0.0.1:%PORT%"' in launch
```

Delete the file: `git rm tests/test_score_comparison.py`

- [ ] **Step 5: Fix the negative-zero assertions** — the substring `"-0.0"` wrongly matches legitimate text such as `-0.09%`. At the top of both `tests/test_audit_health_check.py` and `tests/test_midsml_breadth.py` add `import re` (if absent) and:

```python
NEG_ZERO = re.compile(r"-0\.0(?![0-9])")
```

In `tests/test_audit_health_check.py` replace `assert "-0.0" not in full_text, ...` with:

```python
    assert not NEG_ZERO.search(full_text), f"Found negative zero in Telegram deals message: {NEG_ZERO.search(full_text)}"
```

In `tests/test_midsml_breadth.py` replace `assert "-0.0" not in m, ...` with:

```python
        assert not NEG_ZERO.search(m), f"Message {i} contained negative zero: {m}"
```

- [ ] **Step 6: Fix the label assertion** — in `tests/test_momentum_contract.py` replace `assert "RELIANCE INDUSTRIES" in opts["RELIANCE"]` with:

```python
    assert "reliance industries" in opts["RELIANCE"].lower()
```

- [ ] **Step 7: Mark live-data action-desk tests** — in `tests/test_action_desk.py` add `import pytest` if absent and put `@pytest.mark.realdb` directly above each of: `test_action_desk_enforces_strict_swing_quality_rules`, `test_action_desk_darvas_squeeze_queue`, `test_queue_and_drawer_same_predicate` (they assert specific symbols such as RHIM/JNPR on whatever session the live DB holds).

- [ ] **Step 8: Declare API dependencies** — append to `Scripts/requirements.txt`:

```
fastapi>=0.110
uvicorn>=0.29
httpx>=0.27
```

In `Scripts/_ensure_venv.bat`, find the line that checks/installs `duckdb nicegui pandas numpy curl_cffi` and add `fastapi uvicorn httpx` to the same package list (both the import check and the `pip install` line). Then run: `.venv/Scripts/python -m pip install -r Scripts/requirements.txt`

- [ ] **Step 9: Run the whole default suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `0 failed`. If anything else fails, read the failure; fix only if it is caused by Steps 1–8, otherwise record it in the task report and stop for review.

- [ ] **Step 10: Commit**

```bash
git add pytest.ini tests/test_stock_drawer_features.py tests/test_ui_recovery_contracts.py tests/test_audit_health_check.py tests/test_midsml_breadth.py tests/test_momentum_contract.py Scripts/requirements.txt Scripts/_ensure_venv.bat
git add -p tests/test_action_desk.py App/ui/stock_drawer.py
git commit -m "test: isolate user-DB tests, drop stale tests, add realdb marker

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Close SQL injection and CORS

**Files:**
- Modify: `App/api/server.py` (CORS block ~line 61; momentum `debug_symbol` ~lines 492-493, 548-549, 616-617)
- Create: `tests/test_api_security.py`

**Interfaces:**
- Produces: `validate_symbol(raw: str) -> str` in `App/api/server.py` — returns the upper-cased stripped symbol or raises `HTTPException(422)`. Reused by later rebuild steps.

- [ ] **Step 1: Write failing tests** — create `tests/test_api_security.py`:

```python
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from App.api import server
from App.api.server import app, validate_symbol


@pytest.mark.parametrize("raw,expected", [("reliance", "RELIANCE"), (" M&M ", "M&M"), ("BAJAJ-AUTO", "BAJAJ-AUTO")])
def test_validate_symbol_accepts_nse_symbols(raw, expected):
    assert validate_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["X'; COPY (SELECT 1) TO 'C:/x.csv'; --", "A B", "", "A" * 21, "SYM;"])
def test_validate_symbol_rejects_injection(raw):
    with pytest.raises(HTTPException) as exc:
        validate_symbol(raw)
    assert exc.value.status_code == 422


def test_momentum_debug_symbol_injection_is_rejected():
    client = TestClient(app)
    resp = client.get("/api/screener/momentum", params={"debug_symbol": "X' OR '1'='1"})
    assert resp.status_code == 422


def _preflight(origin: str):
    # Preflight is answered by the CORS middleware itself, so no DB access is needed (safe in CI).
    return TestClient(app).options(
        "/api/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )


def test_cors_does_not_allow_arbitrary_origins():
    assert _preflight("http://evil.example").headers.get("access-control-allow-origin") is None


def test_cors_allows_vite_dev_origin():
    resp = _preflight("http://127.0.0.1:5173")
    assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_api_security.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_symbol'`.

- [ ] **Step 3: Implement** — in `App/api/server.py`:

(a) add `import re` to the imports and, after the `app = FastAPI(...)` block, replace the whole `app.add_middleware(CORSMiddleware, ...)` call with:

```python
# Same-origin in production (FastAPI serves frontend/dist). Only the Vite dev server needs CORS.
DEV_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "PUT"],
    allow_headers=["*"],
)

_SYMBOL_RE = re.compile(r"^[A-Z0-9&\-_.]{1,20}$")


def validate_symbol(raw: str) -> str:
    """Upper-case and validate an NSE symbol; raise 422 for anything else."""
    sym = str(raw or "").strip().upper()
    if not _SYMBOL_RE.fullmatch(sym):
        raise HTTPException(status_code=422, detail=f"Invalid symbol: {raw!r}")
    return sym
```

(b) In `get_momentum_screener`, right after the line `debug_symbol = _arg_val(debug_symbol, None)` add:

```python
    debug_params: list[str] = []
    if debug_symbol:
        debug_symbol = validate_symbol(debug_symbol)
```

(c) Replace `trigger_where.append(f"i.symbol = '{debug_symbol.strip().upper()}'")` with:

```python
        trigger_where.append("i.symbol = ?")
        debug_params.append(debug_symbol)
```

and replace `current_where.append(f"c.symbol = '{debug_symbol.strip().upper()}'")` with:

```python
        current_where.append("c.symbol = ?")
        debug_params.append(debug_symbol)
```

(d) Replace `df = con.execute(sql).fetchdf()` inside `get_momentum_screener` with:

```python
        assert sql.count("?") == len(debug_params), "momentum SQL placeholders out of sync"
        df = con.execute(sql, debug_params).fetchdf()
```

(The `trigger_where` CTE precedes `current_where` in the SQL text, so the two `?` bind in append order.)

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_api_security.py tests/test_momentum_screener_api.py -v`
Expected: PASS (momentum API tests skip or pass depending on DB presence).

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_security.py
git add -p App/api/server.py
git commit -m "fix(api): parameterize debug_symbol, validate symbols, restrict CORS to dev origin

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Honest exposure gate in the header

**Files:**
- Modify: `App/api/server.py` (`get_market_regime`, lines ~112-330)
- Modify: `frontend/src/types.ts` (`ExposureGate`, `setups_summary`)
- Modify: `frontend/src/components/ExposureGateHeader.tsx` (~lines 29-60 and the setups chip)
- Create: `tests/test_regime_band.py`

**Interfaces:**
- Produces in `App/api/server.py`:
  - `parse_exposure_band(pct: Any) -> tuple[float | None, float | None]`
  - `playbook_for_band(band_low: float | None, ab50_pct: float | None) -> dict[str, str]` with keys `execution_playbook, action_bias, max_position_size, risk_per_trade`
- Regime JSON `exposure_gate` gains `band` (str, e.g. `"50% - 75%"`), `band_low`, `band_high` (float|null); `recommended_pct` becomes `band_low` (float|null). `setups_summary` becomes `{"stage2_pool_count": int}`.

- [ ] **Step 1: Write failing tests** — create `tests/test_regime_band.py`:

```python
from __future__ import annotations

import pytest

from App.api.server import parse_exposure_band, playbook_for_band


@pytest.mark.parametrize("raw,expected", [
    ("75% - 100%", (75.0, 100.0)),
    ("50% - 75%", (50.0, 75.0)),
    ("0% - 15%", (0.0, 15.0)),
    ("25%", (25.0, 25.0)),
    ("", (None, None)),
    (None, (None, None)),
    ("n/a", (None, None)),
])
def test_parse_exposure_band(raw, expected):
    assert parse_exposure_band(raw) == expected


def test_playbook_tiers_follow_band_low():
    assert playbook_for_band(75.0, 60.0)["action_bias"].startswith("Bullish")
    assert playbook_for_band(50.0, 45.0)["action_bias"].startswith("Selective")
    assert playbook_for_band(25.0, 30.0)["action_bias"].startswith("Defensive")
    assert playbook_for_band(0.0, 20.0)["action_bias"].startswith("Defensive")
    assert playbook_for_band(None, None)["action_bias"] == "Unknown — exposure inputs missing"


def test_selective_playbook_quotes_real_breadth_not_hardcoded_threshold():
    text = playbook_for_band(50.0, 45.3)["execution_playbook"]
    assert "45.3%" in text
    assert "sub-40%" not in text


@pytest.mark.realdb
def test_regime_band_matches_gate_and_sees_52w_lows():
    from fastapi.testclient import TestClient
    from App.api.server import app
    body = TestClient(app).get("/api/market/regime").json()
    gate = body["exposure_gate"]
    assert gate["band"] and "%" in gate["band"]
    assert gate["recommended_pct"] == gate["band_low"]
    assert "stage2_pool_count" in body["setups_summary"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_regime_band.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_exposure_band'`.

- [ ] **Step 3: Add the helpers** — in `App/api/server.py`, below `validate_symbol`:

```python
_BAND_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_exposure_band(pct: Any) -> tuple[float | None, float | None]:
    """'50% - 75%' -> (50.0, 75.0); '25%' -> (25.0, 25.0); junk -> (None, None)."""
    nums = [float(n) for n in _BAND_NUM_RE.findall(str(pct or ""))]
    if not nums:
        return (None, None)
    return (min(nums), max(nums))


def playbook_for_band(band_low: float | None, ab50_pct: float | None) -> dict[str, str]:
    if band_low is None:
        return {
            "execution_playbook": "Exposure inputs are missing for this session; do not size new positions until Data Health is green.",
            "action_bias": "Unknown — exposure inputs missing",
            "max_position_size": "—",
            "risk_per_trade": "—",
        }
    breadth = f"{ab50_pct:.1f}%" if ab50_pct is not None else "n/a"
    if band_low >= 75.0:
        return {
            "execution_playbook": f"Risk-on: {breadth} of stocks above their 50 EMA. Trade clean Stage 2 pivots and breakouts at standard size; trail stops below the 10/20 EMA.",
            "action_bias": "Bullish / Trend Following",
            "max_position_size": "15%–20%",
            "risk_per_trade": "1.0%",
        }
    if band_low >= 50.0:
        return {
            "execution_playbook": f"Selective: {breadth} of stocks above their 50 EMA. Prefer tight Darvas/VCP setups near pivot; avoid extended chases.",
            "action_bias": "Selective / Coiled Setups Only",
            "max_position_size": "8%–10%",
            "risk_per_trade": "0.5%–0.75%",
        }
    return {
        "execution_playbook": f"Defensive: {breadth} of stocks above their 50 EMA. Mostly cash; only the strongest leaders, and protect open winners with trailing stops.",
        "action_bias": "Defensive / Heavy Cash",
        "max_position_size": "5%–7%",
        "risk_per_trade": "0.25%–0.5%",
    }
```

- [ ] **Step 4: Use the same gate inputs as the Action Desk and the new helpers** — in `get_market_regime`:

(a) change the import line to `from App.ui.market_health import load_exposure_gate_args, resolve_india_vix` and replace `exp_inputs = load_exposure_inputs(con, trade_date=trade_date)` with `exp_inputs = load_exposure_gate_args(con, trade_date=trade_date)` (this adds real `count_52w_highs/lows` and `net_lows_expanding`; the Action Desk already uses it).

(b) replace the lines `c_52w_h = int(exp_inputs.get("count_52w_highs") or near_52_cnt)` / `c_52w_l = ...` with:

```python
        c_52w_h = int(exp_inputs.get("count_52w_highs") or 0)
        c_52w_l = int(exp_inputs.get("count_52w_lows") or 0)
```

(c) replace everything from `raw_pct = gate.get("pct", 50.0)` down to (and including) the final `risk_per_trade = "0.25%–0.5%"` of the old if/elif/else with:

```python
    band = str(gate.get("pct") or "")
    band_low, band_high = parse_exposure_band(band)
    playbook = playbook_for_band(band_low, ab50_pct if not b_df.empty else None)
```

(d) replace the darvas count query block (the `SELECT count(DISTINCT symbol) ... close_price > ema_200 AND abs(away_52w_high_pct) <= 25.0` assignment to `darvas_sq_count`) variable name with `stage2_pool_count` (same SQL, honest name).

(e) in the returned dict replace the `"exposure_gate": {...}` and `"setups_summary": {...}` entries with:

```python
        "exposure_gate": {
            "band": band or None,
            "band_low": band_low,
            "band_high": band_high,
            "recommended_pct": band_low,
            "state": gate.get("state"),
            "badge": gate.get("badge"),
            "guidance": gate.get("guidance"),
            "is_actionable": bool(band_low and band_low > 0),
            **playbook,
        },
```

```python
        "setups_summary": {
            "stage2_pool_count": stage2_pool_count,
        },
```

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_regime_band.py -v` then `.venv/Scripts/python -m pytest tests/test_regime_band.py -m realdb -v`
Expected: PASS both (realdb only if the live DB exists).

- [ ] **Step 6: Frontend** — in `frontend/src/types.ts` change `ExposureGate` to:

```ts
export interface ExposureGate {
  band: string | null;
  band_low: number | null;
  band_high: number | null;
  recommended_pct: number | null;
  state: string | null;
  badge: string | null;
  guidance: string | null;
  is_actionable: boolean;
  execution_playbook?: string;
  action_bias?: string;
  max_position_size?: string;
  risk_per_trade?: string;
}
```

and change the `setups_summary` field of `MarketRegimeResponse` to `setups_summary: { stage2_pool_count: number };`.

In `frontend/src/components/ExposureGateHeader.tsx`: replace the `exposureTone` expression with

```tsx
  const low = exposure_gate.band_low;
  const exposureTone =
    low == null
      ? 'text-[#94a3b8] border-[#263447] bg-[#151f2b]/60'
      : low >= 75
      ? 'text-[#45d483] border-[#163526] bg-[#163526]/60'
      : low >= 50
      ? 'text-[#f0be58] border-[#3a2f18] bg-[#3a2f18]/60'
      : 'text-[#f27c84] border-[#3a2027] bg-[#3a2027]/60';
```

replace `{exposure_gate.state} Regime ({exposure_gate.recommended_pct}% Max Exposure)` with

```tsx
                {exposure_gate.state ?? 'Unknown'} · Exposure {exposure_gate.band ?? '—'}
```

and replace every use of `setups_summary.darvas_count` / `setups_summary.vcp_count` in the setups chip with a single item rendering `Stage-2 pool: {setups_summary.stage2_pool_count}` and `title="Stocks above their 200 EMA and within 25% of the 52-week high"`. Run `cd frontend && npx tsc --noEmit` and fix any remaining references it reports to the removed fields.

- [ ] **Step 7: Build check**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add tests/test_regime_band.py
git add -p App/api/server.py frontend/src/types.ts frontend/src/components/ExposureGateHeader.tsx
git commit -m "fix(regime): show the real exposure band and use the Action Desk gate inputs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Honest Action Desk (Cockpit) rows

**Files:**
- Modify: `App/api/server.py` (`get_cockpit_candidates`, lines ~236-370)
- Modify: `frontend/src/types.ts` (`CandidateSetup`)
- Modify: `frontend/src/components/CockpitWorkspace.tsx` (row key, nullable cells, remove R:R column)
- Create: `tests/test_cockpit_rows.py`

**Interfaces:**
- Produces in `App/api/server.py`:
  - `_opt_float(val: Any, ndigits: int = 2) -> float | None` — NaN/None/non-numeric → `None`, else rounded float (no zero dead-band).
  - `cockpit_row(row: Mapping[str, Any], queue: str) -> dict[str, Any] | None`
- Row JSON: `change_1d_pct` = `day_pct` (vs previous close); `dist_to_pivot_pct` = `(trigger/cmp − 1)×100` or `null`; `risk_pct` real or `null`; `trigger_price`/`invalidation_price` real or `null`; `reward_to_risk` **removed**; for queue `darvas_10ema` trigger/invalidation/risk/distance are `null` (geometry is redefined in Step 6 of the spec). Response `as_of` = the desk's `trade_date`.

- [ ] **Step 1: Write failing tests** — create `tests/test_cockpit_rows.py`:

```python
from __future__ import annotations

import math

from App.api.server import _opt_float, cockpit_row


BASE = {
    "symbol": "lloydsme", "sector": "Metals", "cmp": 1838.3, "open_price": 1800.0,
    "day_pct": 0.88, "trigger_price": 1859.4, "stop_loss": 1805.55, "risk_pct": 2.98,
    "rvol": 0.7, "rs_percentile": float("nan"), "delivery_pct": 41.2, "why_now": "box",
    "squeeze_pct": 1.2, "market_cap_cr": 9000.0,
}


def test_opt_float_keeps_missing_as_none():
    assert _opt_float(None) is None
    assert _opt_float(float("nan")) is None
    assert _opt_float("x") is None
    assert _opt_float(0.00001, 4) == 0.0
    assert _opt_float(2.345) == 2.35


def test_change_is_vs_previous_close_not_intraday():
    row = cockpit_row(BASE, "darvas_squeeze")
    assert row["change_1d_pct"] == 0.88


def test_distance_is_derived_from_trigger_and_close():
    row = cockpit_row(BASE, "darvas_squeeze")
    assert math.isclose(row["dist_to_pivot_pct"], (1859.4 / 1838.3 - 1) * 100, abs_tol=0.01)
    assert row["symbol"] == "LLOYDSME"


def test_no_fabricated_defaults():
    row = cockpit_row({**BASE, "risk_pct": None, "trigger_price": None, "stop_loss": None, "rvol": None}, "vcp")
    assert row["risk_pct"] is None
    assert row["trigger_price"] is None
    assert row["dist_to_pivot_pct"] is None
    assert row["rvol"] is None
    assert row["rs_percentile"] is None
    assert "reward_to_risk" not in row


def test_darvas_10ema_geometry_is_null_until_redefined():
    row = cockpit_row(BASE, "darvas_10ema")
    assert row["trigger_price"] is None
    assert row["invalidation_price"] is None
    assert row["risk_pct"] is None
    assert row["dist_to_pivot_pct"] is None


def test_blank_symbol_is_skipped():
    assert cockpit_row({**BASE, "symbol": " "}, "vcp") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_cockpit_rows.py -v`
Expected: FAIL — `ImportError: cannot import name '_opt_float'`.

- [ ] **Step 3: Implement** — in `App/api/server.py` add `from collections.abc import Mapping` to imports and, above `get_cockpit_candidates`:

```python
def _opt_float(val: Any, ndigits: int = 2) -> float | None:
    """Missing stays missing: None/NaN/inf/non-numeric -> None."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, ndigits)


def cockpit_row(row: Mapping[str, Any], queue: str) -> dict[str, Any] | None:
    sym = str(row.get("symbol") or "").strip().upper()
    if not sym:
        return None
    cmp_val = _opt_float(row.get("cmp") if row.get("cmp") is not None else row.get("close_price"))
    trigger = _opt_float(row.get("trigger_price"))
    stop = _opt_float(row.get("stop_loss"))
    risk = _opt_float(row.get("risk_pct"))
    if queue == "darvas_10ema":
        # Current trigger = EMA10 (below price) and stop = EMA10*0.985 carry no information.
        trigger = stop = risk = None
    dist = round((trigger / cmp_val - 1.0) * 100.0, 2) if trigger and cmp_val else None
    return {
        "symbol": sym,
        "sector": str(row.get("sector") or "") or None,
        "queue": queue,
        "cmp": cmp_val,
        "change_1d_pct": _opt_float(row.get("day_pct")),
        "pattern_state": str(row.get("setup_type") or queue),
        "rvol": _opt_float(row.get("rvol")),
        "dist_to_pivot_pct": dist,
        "risk_pct": risk if (risk is not None and risk > 0) else None,
        "trigger_price": trigger,
        "invalidation_price": stop,
        "mcap_cr": _opt_float(row.get("market_cap_cr")),
        "why_now": str(row.get("why_now") or ""),
        "rs_percentile": _opt_float(row.get("rs_percentile"), 1),
        "delivery_pct": _opt_float(row.get("delivery_pct"), 1),
        "theme": str(row.get("theme") or "") or None,
        "deal_flow": str(row.get("deal_flow") or "") or None,
        "squeeze_pct": _opt_float(row.get("squeeze_pct")),
    }
```

Add `import math` to the imports if absent. Then in `get_cockpit_candidates` replace the whole inner function `_extract_rows` with:

```python
    def _extract_rows(df: pd.DataFrame, q_name: str):
        if df.empty:
            return
        for rec in df.to_dict("records"):
            shaped = cockpit_row(rec, q_name)
            if shaped is not None:
                records.append(shaped)
```

Replace the non-squeeze sort key with:

```python
        records.sort(key=lambda x: (
            abs(x["dist_to_pivot_pct"]) if x.get("dist_to_pivot_pct") is not None else 9999.0,
            -(x.get("rvol") or 0.0),
        ))
```

(the squeeze sort already tolerates `None`). Replace `"as_of": data.get("as_of"),` with `"as_of": str(pd.to_datetime(data["trade_date"]).date()) if data.get("trade_date") is not None else None,`.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_cockpit_rows.py tests/test_action_desk.py -v`
Expected: PASS (`test_cockpit_candidates_api_darvas_squeeze_sorting` still passes — squeeze rows keep numeric `squeeze_pct`, others `None`).

- [ ] **Step 5: Frontend** — in `frontend/src/types.ts` replace `CandidateSetup` with:

```ts
export interface CandidateSetup {
  symbol: string;
  sector: string | null;
  queue: string;
  cmp: number | null;
  change_1d_pct: number | null;
  pattern_state: string;
  rvol: number | null;
  dist_to_pivot_pct: number | null;
  risk_pct: number | null;
  trigger_price: number | null;
  invalidation_price: number | null;
  mcap_cr: number | null;
  why_now: string;
  rs_percentile: number | null;
  delivery_pct: number | null;
  theme?: string | null;
  deal_flow?: string | null;
  squeeze_pct?: number | null;
  trigger_date?: string;
}
```

Add `frontend/src/utils/nullable.ts`:

```ts
export const DASH = '—';

export function signedPct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return v.toFixed(digits);
}
```

In `frontend/src/components/CockpitWorkspace.tsx`:
- import `{ DASH, signedPct, num }` from `'../utils/nullable'`;
- change the row element's `key={c.symbol}` to `key={`${c.queue}-${c.symbol}`}`;
- 1D % cell: class `c.change_1d_pct == null ? 'text-[#94a3b8]' : c.change_1d_pct >= 0 ? 'text-[#10b981]' : 'text-[#f43f5e]'`, text `{signedPct(c.change_1d_pct)}`;
- Dist cell text `{signedPct(c.dist_to_pivot_pct, 1)}`, and guard its colour expression with `c.dist_to_pivot_pct == null ? 'text-[#94a3b8]' : …existing…`;
- Risk cell text `{c.risk_pct == null ? DASH : `${num(c.risk_pct, 1)}%`}`, colour guarded the same way;
- delete the `R:R` `<th>` (the one calling `handleSort('reward_to_risk')`) and its `<td>`;
- delete the canned fallback "why now" sentence (~line 277) so an empty `why_now` renders `DASH`;
- wherever `c.cmp.toFixed(` / `c.trigger_price.toFixed(` / `c.invalidation_price.toFixed(` appear, use `num(c.cmp)` etc.
Then run `cd frontend && npx tsc --noEmit` and fix each reported null-safety error in this file with `num`/`signedPct`/`DASH`.

- [ ] **Step 6: Build check**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add tests/test_cockpit_rows.py frontend/src/utils/nullable.ts
git add -p App/api/server.py frontend/src/types.ts frontend/src/components/CockpitWorkspace.tsx
git commit -m "fix(desk): real 1D%, derived distance, no fabricated R:R/risk defaults

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Honest VCP Workbench

**Files:**
- Modify: `App/api/server.py` (`get_vcp_screener`, lines ~709-810)
- Modify: `frontend/src/types.ts` (`VcpCandidate`)
- Modify: `frontend/src/components/VcpWorkbenchWorkspace.tsx` (nullable cells, empty state, sizer)
- Create: `tests/test_vcp_rows.py`

**Interfaces:**
- Consumes: `_opt_float` from Task 4.
- Produces: `vcp_row(r: Mapping[str, Any]) -> dict[str, Any] | None` in `App/api/server.py`. VCP JSON uses the desk's validated `trigger_price` / `stop_loss` / `risk_pct`, the real `vdu_ratio`, and `null` share suggestions when geometry is missing. The indicators_daily fallback path is deleted: an empty queue returns `candidates: []`.

- [ ] **Step 1: Write failing tests** — create `tests/test_vcp_rows.py`:

```python
from __future__ import annotations

import inspect

from App.api import server
from App.api.server import vcp_row

ROW = {
    "symbol": "gcsl", "cmp": 656.3, "trigger_price": 655.0, "stop_loss": 557.2,
    "pivot_price": 655.0, "stop_price": 560.0, "vdu_ratio": 0.55, "vdu_active": True,
    "risk_pct": 17.55, "pivot_distance_pct": -0.2, "rs_percentile": 88.0, "sector": "Chemicals",
    "why_now": "3T VCP (16.7% → 13.1% → 3.1% → 9.2%) · VDU ✓ · Pivot -0.2%",
}


def test_vcp_row_uses_real_vdu_and_desk_geometry():
    r = vcp_row(ROW)
    assert r["symbol"] == "GCSL"
    assert r["vdu_ratio"] == 0.55
    assert r["vdu_confirmed"] is True
    assert r["pivot_entry"] == 655.0
    assert r["stop_loss"] == 557.2
    assert r["risk_pct"] == 17.55
    assert r["dist_to_pivot_pct"] == -0.2
    assert r["wave_sequence"] == "3T VCP (16.7% → 13.1% → 3.1% → 9.2%)"
    assert r["suggested_shares_for_10k_risk"] == int(10000 / (655.0 - 557.2))


def test_vcp_row_missing_values_stay_null():
    r = vcp_row({"symbol": "abc", "cmp": 100.0, "why_now": ""})
    for key in ("vdu_ratio", "pivot_entry", "stop_loss", "risk_pct", "dist_to_pivot_pct",
                "wave_sequence", "suggested_shares_for_10k_risk"):
        assert r[key] is None, key
    assert r["vdu_confirmed"] is False


def test_no_fabricated_fallback_remains():
    src = inspect.getsource(server.get_vcp_screener)
    for banned in ("15% → 7% → 3%", "0.72", "cmp_val * 1.025", "cmp_val * 1.02", "0.65 if", "cmp_val * 0.96"):
        assert banned not in src, banned
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_vcp_rows.py -v`
Expected: FAIL — `ImportError: cannot import name 'vcp_row'`.

- [ ] **Step 3: Implement** — in `App/api/server.py` add above `get_vcp_screener`:

```python
def vcp_row(r: Mapping[str, Any]) -> dict[str, Any] | None:
    sym = str(r.get("symbol") or "").strip().upper()
    if not sym:
        return None
    entry = _opt_float(r.get("trigger_price"))
    stop = _opt_float(r.get("stop_loss"))
    vdu = _opt_float(r.get("vdu_ratio"))
    vdu_active = r.get("vdu_active")
    why = str(r.get("why_now") or "")
    per_share = (entry - stop) if (entry is not None and stop is not None and entry > stop) else None

    def shares(risk_rupees: float) -> int | None:
        return int(risk_rupees / per_share) if per_share else None

    return {
        "symbol": sym,
        "cmp": _opt_float(r.get("cmp")),
        "wave_sequence": why.split("·")[0].strip() or None,
        "vdu_ratio": vdu,
        "vdu_confirmed": bool(vdu_active) if (vdu_active is not None and not pd.isna(vdu_active)) else bool(vdu is not None and vdu <= 0.80),
        "pivot_entry": entry,
        "stop_loss": stop,
        "risk_pct": _opt_float(r.get("risk_pct")),
        "dist_to_pivot_pct": _opt_float(r.get("pivot_distance_pct"), 1),
        "suggested_shares_for_10k_risk": shares(10_000),
        "suggested_shares_for_25k_risk": shares(25_000),
        "suggested_shares_for_50k_risk": shares(50_000),
        "rs_percentile": _opt_float(r.get("rs_percentile"), 1),
        "sector": str(r.get("sector") or "") or None,
    }
```

Then replace the body of `get_vcp_screener` after the `try/except` that loads `vcp_df` (i.e. from `vcp_results = []` through the final `return`) with:

```python
    vcp_results = [row for row in (vcp_row(rec) for rec in vcp_df.to_dict("records")) if row is not None] if not vcp_df.empty else []
    vcp_results.sort(key=lambda x: (
        abs(x["dist_to_pivot_pct"]) if x["dist_to_pivot_pct"] is not None else 9999.0,
        x["risk_pct"] if x["risk_pct"] is not None else 9999.0,
    ))
    trade_date = data.get("trade_date")
    return {
        "as_of": str(pd.to_datetime(trade_date).date()) if trade_date is not None else None,
        "total_count": len(vcp_results),
        "candidates": vcp_results,
    }
```

(This deletes the `if not vcp_results:` indicators_daily fallback block entirely.)

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_vcp_rows.py -v`
Expected: PASS.

- [ ] **Step 5: Frontend** — in `frontend/src/types.ts` make every numeric field of `VcpCandidate` `number | null`, `wave_sequence: string | null`, and add `as_of?: string | null` to the VCP response type if one exists. In `frontend/src/components/VcpWorkbenchWorkspace.tsx`:
- import `{ DASH, num }` from `'../utils/nullable'`;
- change the fetch URL `'http://127.0.0.1:8000/api/screener/vcp'` to `'/api/screener/vcp'`;
- render `{c.wave_sequence ?? DASH}`, `{c.vdu_ratio == null ? DASH : `${num(c.vdu_ratio)} ${c.vdu_confirmed ? '✓' : ''}`}`, and `num(...)` for pivot/stop/risk/distance cells, guarding each colour expression with `== null ? 'text-[#94a3b8]' :`;
- in the position sizer (~lines 276-282) replace `Math.max(1, pivot - stop)` with a guard: if `pivot == null || stop == null || pivot <= stop` render `DASH` for quantity; otherwise `Math.floor(riskAmount / (pivot - stop))`, and format numbers with `toLocaleString('en-IN')`;
- the empty-table message becomes `No VCP setups in the pool today.`
Run `cd frontend && npx tsc --noEmit` and fix remaining null-safety errors in this file the same way.

- [ ] **Step 6: Build check**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add tests/test_vcp_rows.py
git add -p App/api/server.py frontend/src/types.ts frontend/src/components/VcpWorkbenchWorkspace.tsx
git commit -m "fix(vcp): real VDU and desk geometry, delete fabricated fallback queue

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Momentum stops inventing RS / delivery / 10-EMA distance

**Files:**
- Modify: `App/api/server.py` (momentum SELECT ~lines 579-593 and row mapping ~lines 620-640)
- Modify: `frontend/src/types.ts` (momentum candidate type), `frontend/src/components/MomentumWorkspace.tsx` (~lines 745-800)
- Create: `tests/test_momentum_nulls.py`

**Interfaces:**
- Consumes: `_opt_float` (Task 4), `DASH`/`signedPct` (Task 4 frontend util).
- Produces: momentum JSON `rs_percentile`, `delivery_pct`, `away_10ema_pct` are `number | null`.

- [ ] **Step 1: Write failing tests** — create `tests/test_momentum_nulls.py`:

```python
from __future__ import annotations

import inspect

import pytest

from App.api import server


def test_momentum_sql_has_no_fabricated_coalesce():
    src = inspect.getsource(server.get_momentum_screener)
    assert "COALESCE(c.rs_percentile, 50)" not in src
    assert "COALESCE(c.delivery_pct, 45" not in src
    assert "COALESCE(c.away_10ema_pct, 0" not in src


@pytest.mark.realdb
def test_momentum_rs_matches_db_including_nulls():
    import duckdb
    from fastapi.testclient import TestClient
    body = TestClient(server.app).get("/api/screener/momentum", params={"cmp_gt_200": "false", "limit": 2000}).json()
    api_rs = {c["symbol"]: c["rs_percentile"] for c in body["candidates"]}
    assert api_rs, "momentum returned no rows"
    with duckdb.connect(str(server.DB_PATH), read_only=True) as con:
        db_rs = dict(con.execute(
            "SELECT symbol, rs_percentile FROM indicators_daily WHERE trade_date = (SELECT max(trade_date) FROM indicators_daily)"
        ).fetchall())
    for sym, rs in api_rs.items():
        expected = db_rs.get(sym)
        if expected is None:
            assert rs is None, f"{sym}: DB rs is NULL but API returned {rs}"
        else:
            assert rs == round(float(expected), 1), f"{sym}: {rs} != {expected}"
```

(The source guard runs in CI; the realdb test checks API values equal the DB, NULLs included.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_momentum_nulls.py -v`
Expected: FAIL on `test_momentum_sql_has_no_fabricated_coalesce`.

- [ ] **Step 3: Implement** — in the momentum SELECT replace:
- `COALESCE(c.rs_percentile, 50) AS rs_percentile,` → `c.rs_percentile AS rs_percentile,`
- `ROUND(COALESCE(c.away_10ema_pct, 0.0), 2) AS away_10ema_pct,` → `ROUND(c.away_10ema_pct, 2) AS away_10ema_pct,`
- `COALESCE(c.delivery_pct, 45.0) AS delivery_pct,` → `c.delivery_pct AS delivery_pct,`

In the row mapping replace the three entries with:

```python
            "rs_percentile": _opt_float(r["rs_percentile"], 1),
            "away_10ema_pct": _opt_float(r["away_10ema_pct"]),
            "delivery_pct": _opt_float(r["delivery_pct"], 1),
```

Check the `ORDER BY ... c.away_10ema_pct ASC` still works with NULLs (DuckDB puts NULLs last by default — acceptable).

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_momentum_nulls.py tests/test_momentum_screener_api.py -v`
Expected: PASS.

- [ ] **Step 5: Frontend** — in `frontend/src/types.ts` set `rs_percentile`, `delivery_pct`, `away_10ema_pct` to `number | null` in the momentum candidate interface. In `frontend/src/components/MomentumWorkspace.tsx`:
- import `{ DASH, signedPct }` from `'../utils/nullable'`;
- the vs-10EMA cell: wrap the colour expression with `c.away_10ema_pct == null ? 'text-[#94a3b8]' : …`, text `{signedPct(c.away_10ema_pct)}`, and render the 🎯/⚠️ badges only when `c.away_10ema_pct != null`;
- RS cell: `{c.rs_percentile == null ? DASH : renderRsBadge(c.rs_percentile)}`;
- Delivery cell: `{c.delivery_pct == null ? DASH : renderDeliveryBadge(c.delivery_pct, undefined, c.delivery_spike)}`.
Run `cd frontend && npx tsc --noEmit` and fix any remaining errors (e.g. sort comparators) by treating `null` as last.

- [ ] **Step 6: Build check**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add tests/test_momentum_nulls.py
git add -p App/api/server.py frontend/src/types.ts frontend/src/components/MomentumWorkspace.tsx
git commit -m "fix(momentum): missing RS/delivery/10EMA distance stay null instead of 50/45/0

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: One row per deal print (bulk ∩ block)

**Files:**
- Modify: `Scripts/build_database.py` (`read_all_deals`, ~lines 395-426)
- Create: `tests/test_deal_print_collapse.py`

**Interfaces:**
- Produces: `collapse_cross_listed_prints(deals: pd.DataFrame) -> pd.DataFrame` in `Scripts/build_database.py`. A print reported in both files becomes one row with `deal_type == "Block+Bulk"`.

- [ ] **Step 1: Write failing test** — create `tests/test_deal_print_collapse.py`:

```python
from __future__ import annotations

import pandas as pd

from build_database import collapse_cross_listed_prints


def _deal(deal_type, client="INFINITE TRADE", qty=8_600_000, price=2905.0, side="SELL"):
    return {"deal_type": deal_type, "trade_date": pd.Timestamp("2026-09-25"), "symbol": "ADANIENT",
            "security_name": "Adani Ent", "client_name": client, "side": side,
            "quantity": qty, "price": price, "source_file": f"{deal_type}.csv"}


def test_same_print_in_bulk_and_block_collapses_to_one_row():
    df = pd.DataFrame([_deal("Bulk"), _deal("Block"), _deal("Bulk", client="OTHER", qty=100)])
    out = collapse_cross_listed_prints(df)
    assert len(out) == 2
    adani = out[out["client_name"] == "INFINITE TRADE"].iloc[0]
    assert adani["deal_type"] == "Block+Bulk"
    assert (out["client_name"] == "OTHER").sum() == 1


def test_distinct_prints_are_untouched():
    df = pd.DataFrame([_deal("Bulk"), _deal("Bulk", price=2906.0)])
    assert len(collapse_cross_listed_prints(df)) == 2


def test_empty_frame_passes_through():
    empty = pd.DataFrame(columns=["deal_type", "trade_date", "symbol", "client_name", "side", "quantity", "price"])
    assert collapse_cross_listed_prints(empty).empty
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_deal_print_collapse.py -v`
Expected: FAIL — `ImportError: cannot import name 'collapse_cross_listed_prints'`.

- [ ] **Step 3: Implement** — in `Scripts/build_database.py` add above `read_all_deals`:

```python
PRINT_KEY = ["trade_date", "symbol", "client_name", "side", "quantity", "price"]


def collapse_cross_listed_prints(deals: pd.DataFrame) -> pd.DataFrame:
    """A block deal above 0.5% of equity also appears in the bulk file; keep one row per print."""
    if deals.empty:
        return deals
    types = deals.groupby(PRINT_KEY, dropna=False)["deal_type"].transform(lambda s: "+".join(sorted(set(s.astype(str)))))
    out = deals.assign(deal_type=types)
    return out.drop_duplicates(PRINT_KEY, keep="last").reset_index(drop=True)
```

In `read_all_deals`, immediately after the existing `deals = deals.drop_duplicates([...], keep="last")` statement and before `deals["deal_value_cr"] = ...`, add:

```python
    deals = collapse_cross_listed_prints(deals)
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_deal_print_collapse.py tests/test_deals_desk.py tests/test_institutional_engine.py tests/test_institutional_attribution.py -v`
Expected: PASS. If a deals test asserts `deal_type` ∈ {"Bulk","Block"}, extend that assertion to allow `"Block+Bulk"`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_deal_print_collapse.py
git add -p Scripts/build_database.py tests/
git commit -m "fix(deals): collapse prints reported in both bulk and block files

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Refresh the live deals table (writer — ask the user first)** — tell the user: "Task 7 needs one run of the deals refresh to rewrite the `deals` table. Close the MarketPulse UI/Legacy UI, then confirm." After confirmation run `.venv/Scripts/python Scripts/refresh_deals.py` and verify:

```bash
.venv/Scripts/python -c "import duckdb;c=duckdb.connect('Database/marketpulse.duckdb',read_only=True);print(c.execute(\"select count(*) from (select 1 from deals group by trade_date,symbol,client_name,side,quantity,price having count(*)>1)\").fetchone())"
```

Expected: `(0,)`. If the user declines, record that the fix takes effect on the next EOD append.

---

### Task 8: Market-cap summary rows never become a stock

**Files:**
- Modify: `Scripts/build_database.py` (`read_market_cap`, ~lines 224-243)
- Create: `tests/test_market_cap_summary_rows.py`

**Interfaces:**
- Produces: `parse_market_cap_frame(df: pd.DataFrame) -> pd.DataFrame` (takes the raw CSV frame, returns `symbol, security_name, market_cap_cr, market_cap_date, issue_size`); `read_market_cap()` delegates to it.

Root cause: the NSE mcap CSV ends with summary rows whose *Symbol* column holds `Listed`, `Permitted`, `Total` and whose *Series* is blank. `Total` upper-cases to `TOTAL`, collides with the real BE stock TOTAL (Total Transport Systems), and `drop_duplicates(keep="last")` keeps the summary row (mcap ≈ 4.77e7 Cr).

- [ ] **Step 1: Write failing test** — create `tests/test_market_cap_summary_rows.py`:

```python
from __future__ import annotations

import io

import pandas as pd

from build_database import clean_columns, parse_market_cap_frame

CSV = """Trade Date,Symbol,Series,Security Name,Category,Last Trade Date,Face Value(Rs.),Issue Size,Close Price/Paid up value(Rs.),Market Cap(Rs.)
25 SEP 2026,TOTAL,BE,TOTAL TRANSPORT SYS LTD  ,Listed    ,25 SEP 2026,  10.00,  16126973,  70.85,  1142757306.80
25 SEP 2026,ATGL,EQ,ADANI TOTAL GAS LIMITED  ,Listed    ,25 SEP 2026,   1.00,1099810083, 611.65,672698837266.95
25 SEP 2026,Listed    ,  ,                         ,          ,           ,   0.00,         0,   0.00,473225303955365.40
25 SEP 2026,Permitted ,  ,                         ,          ,           ,   0.00,         0,   0.00,  3821649856571.00
25 SEP 2026,Total     ,  ,                         ,          ,           ,   0.00,         0,   0.00,477046953811936.40
"""


def test_summary_rows_are_dropped_and_real_total_kept():
    raw = clean_columns(pd.read_csv(io.StringIO(CSV), dtype=str, skipinitialspace=True))
    out = parse_market_cap_frame(raw)
    assert set(out["symbol"]) == {"TOTAL", "ATGL"}
    total = out.set_index("symbol").loc["TOTAL", "market_cap_cr"]
    assert 100 < total < 200  # ~114.3 Cr, not 4.77e7
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_market_cap_summary_rows.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_market_cap_frame'`.

- [ ] **Step 3: Implement** — replace `read_market_cap` in `Scripts/build_database.py` with:

```python
MCAP_COLUMNS = ["symbol", "security_name", "market_cap_cr", "market_cap_date", "issue_size"]


def parse_market_cap_frame(df: pd.DataFrame) -> pd.DataFrame:
    market_cap_col = next((c for c in df.columns if c.startswith("market_cap")), None)
    if not market_cap_col or "symbol" not in df.columns:
        return pd.DataFrame(columns=MCAP_COLUMNS)
    if "series" in df.columns:
        # NSE appends Listed / Permitted / Total summary rows with a blank series.
        df = df[df["series"].fillna("").astype(str).str.strip() != ""]
    out = pd.DataFrame()
    out["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    out["security_name"] = df.get("security_name", pd.Series("", index=df.index)).astype(str).str.strip()
    out["market_cap_cr"] = to_number(df[market_cap_col]) / 10_000_000
    out["market_cap_date"] = pd.to_datetime(df.get("trade_date", ""), format="%d %b %Y", errors="coerce")
    issue_size_col = next((c for c in df.columns if c.startswith("issue_size")), None)
    out["issue_size"] = to_number(df[issue_size_col]) if issue_size_col else np.nan
    return out.drop_duplicates("symbol", keep="last").reset_index(drop=True)


def read_market_cap() -> pd.DataFrame:
    path = latest_file(DAILY_DIR, "mcap*.csv")
    if not path:
        return pd.DataFrame(columns=MCAP_COLUMNS)
    return parse_market_cap_frame(clean_columns(pd.read_csv(path, dtype=str, skipinitialspace=True)))
```

Confirm `clean_columns` turns `Series` into `series` (open its definition in the same file; if it produces a different name, use that name in the filter and in the test).

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_market_cap_summary_rows.py -v`
Expected: PASS.

- [ ] **Step 5: Check other mcap readers** — run `grep -rn "Market Cap\|mcap.*read_csv\|market_cap(rs" Scripts/*.py` and for every other loader of the mcap CSV (e.g. `Scripts/reference_history.py`, `Scripts/pr_report_ingestion.py`) apply the same blank-series filter before upper-casing symbols; add one assertion per loader to the test file using the same `CSV` fixture if the loader accepts a frame or path (write the CSV to `tmp_path` for path-based loaders). Re-run the test file until PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_market_cap_summary_rows.py
git add -p Scripts/build_database.py Scripts/reference_history.py Scripts/pr_report_ingestion.py
git commit -m "fix(mcap): drop NSE summary rows so 'Total' no longer overwrites the stock TOTAL

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Sector vs-Nifty filled on the latest session

**Files:**
- Modify: `Scripts/append_database.py` (~lines 145-157)
- Create: `tests/test_append_index_order.py`

**Interfaces:**
- Produces: `load_index_for_metrics(root_dir: Path, table_loader: Callable[[str], pd.DataFrame]) -> pd.DataFrame` in `Scripts/append_database.py` — returns index features built from the MA files on disk (which already include today's session), falling back to the stored `index_daily` table only if the MA build is empty or fails.

Root cause: `append_database` computes `sector_metrics_daily` from the *stored* `index_daily`, which does not yet contain the new session; `write_database` re-ingests the MA files afterwards. So vs-Nifty is NULL for the newest date (0/280 rows on 2026-09-25).

- [ ] **Step 1: Write failing test** — create `tests/test_append_index_order.py`:

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd

import append_database


def test_prefers_fresh_ma_history_over_stale_table(monkeypatch, tmp_path):
    fresh = pd.DataFrame({"trade_date": pd.to_datetime(["2026-09-24", "2026-09-25"]),
                          "index_name": ["Nifty 50", "Nifty 50"], "close": [1.0, 2.0]})
    stale = fresh.iloc[:1].copy()
    monkeypatch.setattr(append_database, "load_all_market_activity_history", lambda root: fresh)
    monkeypatch.setattr(append_database, "build_index_features", lambda raw: raw)
    out = append_database.load_index_for_metrics(tmp_path, lambda name: stale)
    assert out["trade_date"].max() == pd.Timestamp("2026-09-25")


def test_falls_back_to_table_when_ma_build_fails(monkeypatch, tmp_path):
    stale = pd.DataFrame({"trade_date": pd.to_datetime(["2026-09-24"]), "index_name": ["Nifty 50"], "close": [1.0]})

    def boom(root):
        raise RuntimeError("no MA files")

    monkeypatch.setattr(append_database, "load_all_market_activity_history", boom)
    out = append_database.load_index_for_metrics(tmp_path, lambda name: stale)
    assert len(out) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_append_index_order.py -v`
Expected: FAIL — `AttributeError: module 'append_database' has no attribute 'load_index_for_metrics'`.

- [ ] **Step 3: Implement** — in `Scripts/append_database.py` add to the imports:

```python
from typing import Callable

from index_history import build_index_features, load_all_market_activity_history
```

Add this function above the function that contains the `index_for_metrics = _load_table("index_daily")` block:

```python
def load_index_for_metrics(root_dir: Path, table_loader: Callable[[str], pd.DataFrame]) -> pd.DataFrame:
    """Index features for sector metrics, including the session being appended.

    The stored index_daily is rewritten from MA files only inside write_database, i.e. after
    sector metrics are computed, so it lacks the newest session.
    """
    try:
        raw = load_all_market_activity_history(root_dir)
        if raw is not None and not raw.empty:
            return build_index_features(raw)
    except Exception as exc:
        print(f"Warning: MA-based index features unavailable ({exc}); using stored index_daily")
    try:
        return table_loader("index_daily")
    except Exception:
        return pd.DataFrame()
```

Replace the block

```python
    try:
        index_for_metrics = _load_table("index_daily")
    except Exception:
        index_for_metrics = pd.DataFrame()
```

with

```python
    index_for_metrics = load_index_for_metrics(ROOT_DIR, _load_table)
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_append_index_order.py tests/test_multi_day_catchup.py tests/test_pipeline_recovery.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_append_index_order.py
git add -p Scripts/append_database.py
git commit -m "fix(append): compute sector vs-index metrics with the new session's index rows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Note for verification** — the live table is corrected on the next EOD append (sector metrics are recomputed over full history each append). After the next run, verify:

```bash
.venv/Scripts/python -c "import duckdb;c=duckdb.connect('Database/marketpulse.duckdb',read_only=True);print(c.execute(\"select trade_date,count(*),count(rs_vs_nifty_63d) from sector_metrics_daily where trade_date>=(select max(trade_date)-interval 3 day from sector_metrics_daily) group by 1 order by 1\").fetchall())"
```

Expected: the latest date's non-null count ≈ row count (≈279/280).

---

### Task 10: End-to-end verification

**Files:** none (verification only), plus `docs/superpowers/specs/2026-09-26-marketpulse-professional-rebuild-design.md` §14 update.

- [ ] **Step 1: Full default suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `0 failed`.

- [ ] **Step 2: Live-DB suite (manual, informational)**

Run: `.venv/Scripts/python -m pytest -q -m realdb`
Expected: record pass/fail counts in the report; failures here are live-data assertions to be rewritten on the fixture DB in Step 2 of the rebuild, not blockers.

- [ ] **Step 3: Frontend**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: exit 0.

- [ ] **Step 4: API smoke against the live DB (read-only)**

```bash
.venv/Scripts/python - <<'EOF'
from fastapi.testclient import TestClient
from App.api.server import app
c = TestClient(app)
g = c.get("/api/market/regime").json()["exposure_gate"]
print("band", g["band"], "low", g["band_low"])
d = c.get("/api/candidates/cockpit", params={"queue": "primary"}).json()
print("as_of", d["as_of"], "rows", d["total_count"], "rr_present", any("reward_to_risk" in r for r in d["candidates"]))
v = c.get("/api/screener/vcp").json()
print("vcp", v["total_count"], "vdu_values", sorted({r["vdu_ratio"] for r in v["candidates"]} - {None})[:5])
print("injection", c.get("/api/screener/momentum", params={"debug_symbol": "X' OR 1=1 --"}).status_code)
EOF
```

Expected: band like `50% - 75%` with matching `low`; `as_of` a real date; `rr_present False`; VDU values varied (not only 0.65/0.85); injection `422`.

- [ ] **Step 5: Record accepted open items in the spec** — in `docs/superpowers/specs/2026-09-26-marketpulse-professional-rebuild-design.md` replace the §14 heading and list with:

```markdown
## 14. Resolved items (user accepted 2026-09-26)

1. Darvas 10 EMA geometry: trigger = prior session high, stop = pullback low (min low since the 10 EMA touch). Implemented with the Desk rebuild; until then the hotfix shows "—".
2. Taxonomy display names: Broad Sector › Sector › Broad Industry › Industry, NSE official names in tooltips.
3. Environment zones in §6.1.2 are starting points, calibrated in the evidence engine before release.
```

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-09-26-marketpulse-professional-rebuild-design.md
git commit -m "docs: record accepted open items for the rebuild spec

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Report to the user** — summarize: tests (default + realdb counts), what changed on screen (exposure band, no R:R, real 1D%, VCP real VDU, nulls as "—"), whether the deals refresh ran, that vs-Nifty fixes on the next EOD run, and the stray `note_TEST_STOCK` row left in the user DB by the earlier test run (ask whether to delete it; do not delete without a yes).
