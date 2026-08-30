# MarketPulse 2.0 — Master AI Handoff & Architecture Guide

> **Target Audience**: Any AI agent or developer taking over or continuing development on the **MarketPulse 2.0** repository.
> **Date**: August 2026
> **Repository**: [patilsiddhant92-arch/Marketpulse](https://github.com/patilsiddhant92-arch/Marketpulse)
> **Branch**: `main`
> **Current Test Status**: **78 / 78 Passed (100% Green)**

---

## 1. Executive Summary & Project Purpose

**MarketPulse 2.0** is an institutional-grade, end-of-day (EOD) Indian equities (NSE) intelligence, sector rotation, and swing-trading candidate discovery platform. 

It ingests official daily NSE data files (Bhavcopy, Delivery Position, 52-Week High/Low, Market Capitalization, PE Ratios, Bulk/Block Deals, and Index History), stores them in an embedded, ultra-fast **DuckDB** database, computes technical indicators, relative strength scores, Volatility Contraction Patterns (VCP), and institutional accumulation metrics, and renders them in a responsive **NiceGUI** web application.

---

## 2. Core Directory Layout

```
MarketPulse2.0/
├── Database/
│   └── marketpulse.duckdb         # Single source of truth DuckDB embedded database
├── Input/
│   ├── daily/                     # Staging folder for latest raw NSE daily CSVs & PR archives
│   ├── archive/                   # Permanent historical raw NSE daily files
│   ├── static/                    # Reference data (sectors, holidays, index constituents)
│   └── downloads/                 # Download staging by date
├── Scripts/                       # Pipeline ingestion, calculations, and analytical engines
│   ├── run_all.py                 # Master orchestrator for daily EOD pipeline
│   ├── ingest_pipeline.py         # Ingestion of bhavcopy, mcap, PE, 52W, deals
│   ├── index_history.py           # Ingestion and normalization of 139+ NSE indices
│   ├── pr_report_ingestion.py     # PR archive parser (announcements, risk, corporate actions)
│   ├── calculate_indicators.py    # EMAs, ATR, RVOL, Delivery %, RS Percentile, VCP
│   ├── candidate_engine.py        # Stage-2 setup scoring, trigger/invalidation/target prices
│   ├── institutional_engine.py    # 5-tier entity resolution, cluster buying, netting
│   ├── daily_recovery.py          # Pipeline integrity verification and self-healing
│   └── watchlist_service.py       # User watchlists and portfolio tracking
├── App/                           # NiceGUI Web Application Layer
│   ├── app.py                     # NiceGUI main entrypoint, navigation, and top layout
│   ├── query_service.py           # DuckDB query layer for screens and candidates
│   ├── sector_read_model.py       # Sector rotation overview, leaderboard, and deep-dive
│   ├── thematic_read_model.py     # Next-Gen Tech Thematic Megatrend read model
│   ├── deals_read_model.py        # Institutional bulk/block deals analytics
│   ├── decision_read_model.py     # Candidate decision and risk/reward read model
│   ├── pages/                     # Sub-pages and research desks
│   │   ├── research/
│   │   │   ├── sector_intel.py    # Sector & Thematic Leadership Desk UI
│   │   │   └── __init__.py
│   │   └── ...
│   └── ui/                        # Shared UI components
│       └── stock_drawer.py        # Universal 4-Tab Stock 360° Slide-Over Modal
├── tests/                         # Pytest test suite (78 automated tests)
│   ├── test_thematic_tracker.py
│   ├── test_sector_intel.py
│   ├── test_institutional_engine.py
│   └── ...
└── AI/
    └── Gemini/                    # Complete AI documentation & handoff knowledge base
        ├── README.md              # (This file) Master Handoff & Quick Start
        ├── SYSTEM_ARCHITECTURE.md # Detailed database schemas, pipelines, and algorithms
        ├── CHRONOLOGY_OF_WORK.md  # Detailed changelog and history of all user requests
        └── THEMATIC_ECOSYSTEM.md  # 70-Stock AI, Data Center, Semi & Ancillary deep-dive
```

---

## 3. Key Operating Commands

### Running the App
```bash
# From workspace root
python -m App.app
# OR
python App/app.py
```
*Web server starts on `http://localhost:8080`.*

### Running the Automated Test Suite
```bash
python -m pytest tests/
```
*(All 78 unit & integration tests must pass before pushing code).*

### Running the Daily Data Ingestion Pipeline
```bash
python Scripts/run_all.py
```

---

## 4. Key Architectural Pillars & Engines

### A. The DuckDB Database (`Database/marketpulse.duckdb`)
* **`stocks_master`**: Master table of all active NSE equity symbols, security names, market cap (Cr), industry, broad industry, sector, broad sector, PE, adjusted PE, and price band.
* **`bhav_daily` / `indicators_daily`**: Daily OHLCV, 10/20/50/100/200 EMAs, ATR, 20D RVOL, Delivery %, Relative Strength (RS) Percentile (0–100), and VCP pattern metrics.
* **`candidate_daily`**: Filtered swing-trading candidates with Stage-2 status, candidate state (`Ready`, `Focus`, `Prepare`, `Monitor`), `trigger_price`, `invalidation_price` (Stop Loss), `first_resistance` (Target), `reward_to_risk` ratio, and plain-English `why_now` thesis.
* **`deals_daily` & `institutional_holdings`**: Bulk and block deals enriched with 5-tier entity resolution (`DII`, `FII`, `Super Investor`, `Promoter`, `HFT / Arbitrage`).
* **`index_daily`**: Historical index performance across 139+ sectoral and thematic benchmarks.

### B. The Universal Stock 360° Slide-Over Drawer (`App/ui/stock_drawer.py`)
* Slide-over modal available anywhere a stock ticker appears in the app.
* **4 Tabs**:
  1. **Institutional Footprint**: Super investor buying, net DII/FII flows, block/bulk deals with price paid vs CMP.
  2. **Technical Geometry**: Price vs 10/20/50/200 EMAs, 52W High distance, VCP contraction levels, Trigger/SL geometry.
  3. **Volume & Liquidity**: RVOL, delivery % trend, volume share.
  4. **Company & Sector**: Sector/Industry categorization, Market Cap, PE, and direct TradingView chart launch.

### C. Sector & Thematic Leadership Desk (`App/pages/research/sector_intel.py`)
* Two primary modes toggled at the top:
  1. **`⚡ Next-Gen Tech (AI / DC / Semi)`**: Tracks 70 verified NSE stocks across 8 physical value-chain pillars (Silicon Design, AI Compute, Heavy Power & Transformers, EHV Cables & Optical Fiber, Precision Cooling HVAC, Batteries & Lithium UPS, Liquid Piping/Pumps/ZLD, and Transformer Oils & BMS).
  2. **`📊 Standard NSE Taxonomy`**: Tracks 22 Sectors, 59 Broad Industries, and 160+ Industries with rank momentum ($\Delta \text{rank}$), % > 50EMA breadth, and breakout candidate leaderboards.

---

## 5. Critical Development Guidelines for Future AI Agents

1. **Path-Agnostic Python Module Resolution**:
   Always use resilient import patterns in UI files to support execution from both the workspace root (`python -m App.app`) and subdirectories:
   ```python
   try:
       from App.sector_read_model import ...
       from App.ui.stock_drawer import ...
   except ModuleNotFoundError:
       from sector_read_model import ...  # type: ignore
       from ui.stock_drawer import ...    # type: ignore
   ```

2. **Database Concurrency & Read-Only Locks**:
   When reading from DuckDB in UI routes or read models, always pass `read_only=True`:
   ```python
   with duckdb.connect(str(db_path), read_only=True) as db:
       df = db.execute(query, params).fetchdf()
   ```

3. **Function Scope & Callback Ordering**:
   In NiceGUI/Python UI builders, define all dynamic container refresh handlers (e.g. `def render_deep_dive(): ...`) **before** passing them as callbacks to loops or child components to avoid `UnboundLocalError`.

4. **Preserve Database Schema Integrity**:
   Do not introduce raw schema mutations to `indicators_daily` or `stocks_master` without migrating through `Scripts/` pipeline scripts and verifying with `tests/`.
