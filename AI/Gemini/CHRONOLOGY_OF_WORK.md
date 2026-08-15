# MarketPulse 2.0 — Chronology of Work, Decisions & Evolution

This document maintains a chronological record of all user requests, technical decisions, code implementations, bug fixes, and milestones across the **MarketPulse 2.0** lifecycle.

---

## Chronological Work Log

### Phase 1: Institutional Intelligence Engine & Stock 360° Drawer
* **User Directive**: *"Build institutional intelligence engine with Super Investors, DII/FII tracking, cluster buying radar, and a universal Stock 360 drawer modal across the app."*
* **Implementations**:
  - Created [`Scripts/institutional_engine.py`](file:///d:/Sid/MarketPulse2.0/Scripts/institutional_engine.py) implementing a 5-tier entity resolution engine (`DII`, `FII`, `Super Investor`, `Promoter`, `HFT / Arbitrage`).
  - Added intraday deal netting, institutional cost basis calculation, and cluster buying detection.
  - Built the universal 4-tab slide-over modal [`App/ui/stock_drawer.py`](file:///d:/Sid/MarketPulse2.0/App/ui/stock_drawer.py) and connected it across all UI tables.
  - Pushed to GitHub: `commit 0b812fb`.

---

### Phase 2: Index History Resilience & Prop Desk Clarification
* **User Question**: *"why was prop firm data was removed ? is that not usable ? or does not make any diffenrce ?"*
* **Resolution**: Clarified that proprietary trading desks (e.g. Gravity, Graviton, NK Securities) execute high-frequency intraday arbitrage rather than fundamental accumulation. Preserved 100% of prop firm data in the database with an interactive toggle on the Deals Desk to filter or include HFT data.
* **Pipeline Fix**:
  - Fixed date parsing issues across 68 `MA*.csv` index history files (`Scripts/index_history.py`), successfully loading 4,309 records across 139 indices into `index_daily`.
  - Pushed to GitHub: `commit ed2d6ce`.

---

### Phase 3: Sector Intel Redesign (Sector & Industry Leadership Desk)
* **User Directive**: *"Sector Intel 2.0 is worst solution cant see anything in the screen need a better view where I can understand which sector / industry to focus and why?"*
* **Root Problem**: The previous view was an unreadable dense heat-grid with tiny cells, lacking clarity on which sectors had actionable institutional momentum.
* **Implementations**:
  - Replaced the old view with a single, full-width **Sector & Industry Leadership Desk** in [`App/pages/research/sector_intel.py`](file:///d:/Sid/MarketPulse2.0/App/pages/research/sector_intel.py) and [`App/sector_read_model.py`](file:///d:/Sid/MarketPulse2.0/App/sector_read_model.py).
  - **High-Conviction Focus Cards**: Renders top actionable sectors with plain-English "WHY FOCUS" theses (e.g., *"Surging Rank (+9 in 5D) • High RS (67) • Strong Breadth (82% > 50EMA)"*) and clickable top stock leader chips.
  - **Master Leaderboard Table**: Clean, sortable table across all 22 Sectors, 59 Broad Industries, and 160+ Granular Industries with $\Delta \text{rank}$, RS percentile, multi-timeframe returns, and volume share.
  - **Sector Breakout Radar**: Dynamic table of Stage-2 breakout leaders for any selected sector with $R:R$ geometry, Trigger Price, Stop Loss, and Stock 360° Drawer integration.

---

### Phase 4: Next-Gen Tech Thematic Megatrend Tracker (AI, Data Centers, Semi & Ancillaries)
* **User Directive**: *"I want you to add one more custom category. You're allowed to search for web. I want all stock directly falling under Semiconductor, Data Centers, AI category and their ancillaries in NSE india market. what about ancilliary? batteries, lithium, pipes? oil? do depth analysis."*
* **Implementations**:
  - Researched and structured the complete 70-stock Indian value-chain across 8 distinct physical and software pillars:
    1. Silicon & Chip Design (11 stocks)
    2. Compute & AI Servers (9 stocks)
    3. Heavy Power & Transformers (8 stocks)
    4. Cables & Optical Fiber (8 stocks)
    5. Cooling & Precision HVAC (4 stocks)
    6. Batteries & Backup Power (5 stocks)
    7. Pipes, Pumps & Water Treatment ZLD (11 stocks)
    8. Transformer Oils, BMS & AI Software (14 stocks)
  - Built [`App/thematic_read_model.py`](file:///d:/Sid/MarketPulse2.0/App/thematic_read_model.py) providing aggregate momentum, breadth, and constituent setup queries.
  - Upgraded [`App/pages/research/sector_intel.py`](file:///d:/Sid/MarketPulse2.0/App/pages/research/sector_intel.py) with a top toggle between **`⚡ Next-Gen Tech (AI / DC / Semi)`** and **`📊 Standard NSE Taxonomy`**.
  - Added 8 Sub-Pillar Action Cards, constituent tables with exact role descriptions, and 1-click TradingView export buttons.
  - Pushed to GitHub: `commit d77907f`.

---

### Phase 5: UI Callback Scope Resolution & Stabilization
* **Bug Encountered**: `UnboundLocalError: cannot access local variable 'render_deep_dive' where it is not associated with a value` when switching taxonomy levels.
* **Root Cause**: In [`App/pages/research/sector_intel.py`](file:///d:/Sid/MarketPulse2.0/App/pages/research/sector_intel.py), the callback function was referenced inside the card rendering loop prior to its `def render_deep_dive()` definition in the scope.
* **Fix**: Restructured the container and callback declarations at the beginning of the function scope for both Taxonomy and Thematic modes.
* **Validation**: Full test suite passed (78 / 78 tests, 100% green).
* **Pushed to GitHub**: `commit addf304`.

---

## 3. Git Commit History

| Commit Hash | Message / Summary |
| :--- | :--- |
| `addf304` | `fix(sector_intel): resolve UnboundLocalError by declaring update handlers before component callbacks` |
| `d77907f` | `feat: Next-Gen Tech Thematic Megatrend Tracker (AI, Data Centers, Semiconductors, and Ancillaries)` |
| `ed2d6ce` | `feat: 10/10 Sector & Industry Leadership Desk with High-Conviction Focus Cards and Breakout Radar` |
| `0b812fb` | `feat: Institutional Engine, Entity Resolution, Cluster Radar, and Universal Stock 360 Drawer` |
