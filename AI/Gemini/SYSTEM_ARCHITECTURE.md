# MarketPulse 2.0 — System Architecture & Technical Blueprint

---

## 1. High-Level System Architecture

```
[Raw NSE Daily Files & PR Archives] 
   ├── Bhavcopy (sec_bhavdata_full_*.csv)
   ├── 52-Week High / Low (CM_52_wk_High_low_*.csv)
   ├── Market Cap & PE (mcap*.csv, PE_*.csv)
   ├── Bulk & Block Deals (bulk.csv, block.csv)
   ├── Index History (MA*.csv)
   └── PR Archive Bundle (PR*.zip)
             │
             ▼
[Scripts/ Pipeline & Ingestion Layer]
   ├── ingest_pipeline.py       --> Ingests core market data into DuckDB tables
   ├── index_history.py         --> Normalizes and stores 139+ index series
   ├── pr_report_ingestion.py   --> Extracts corporate actions & risk files
   ├── calculate_indicators.py  --> Calculates EMAs, ATR, RVOL, RS Percentile, VCP
   ├── candidate_engine.py      --> Evaluates Stage-2 setups, stops, targets, R:R
   └── institutional_engine.py  --> 5-tier entity resolution, netting, cluster radar
             │
             ▼
[Embedded DuckDB Database (`Database/marketpulse.duckdb`)]
   ├── stocks_master            --> Symbols, Sectors, Industries, MCap, PE, Bands
   ├── bhav_daily               --> Raw daily OHLCV and trades
   ├── indicators_daily         --> Technical indicators, RS, RVOL, EMAs, 52W Dist
   ├── candidate_daily          --> Stage-2 setups, candidate state, R:R, why_now
   ├── deals_daily              --> Block & bulk deals with institutional entity tags
   ├── index_daily              --> Daily index closes and returns
   └── ingestion_manifest       --> Daily pipeline run status and checksums
             │
             ▼
[App/ Read Models & Query Layer]
   ├── query_service.py         --> Screeners, candidate filters, symbol searches
   ├── sector_read_model.py     --> Sector rotation overview, momentum, leadership
   ├── thematic_read_model.py   --> 8-Pillar Next-Gen Tech Thematic Engine
   └── deals_read_model.py      --> Net institutional flows & cluster buying
             │
             ▼
[App/ NiceGUI Web Application Layer (`localhost:8080`)]
   ├── Today Desk               --> Market pulse, breadth, leading sectors
   ├── Candidates Desk          --> Actionable Stage-2 setups (Ready, Focus, Prepare)
   ├── Sector Intel Desk        --> Thematic Megatrends (70 stocks) & Standard Taxonomy
   ├── Momentum Scanner         --> Custom technical screening and trend templates
   ├── Deals Desk               --> Institutional accumulation & Super Investor radar
   ├── Portfolio Desk           --> User watchlist and trade management
   ├── Data Health Desk         --> Pipeline status, audit logs, and self-healing
   └── Stock 360° Drawer        --> Universal 4-tab slide-over modal for any ticker
```

---

## 2. DuckDB Schema Definitions

### A. `stocks_master`
| Column | Type | Description |
| :--- | :--- | :--- |
| `symbol` | `VARCHAR PRIMARY KEY` | NSE ticker symbol (e.g. `NETWEB`, `RELIANCE`) |
| `security_name` | `VARCHAR` | Full corporate name |
| `latest_series` | `VARCHAR` | Primary series (`EQ`, `BE`, `SM`) |
| `latest_price_date` | `DATE` | Date of latest ingested price |
| `latest_close` | `DOUBLE` | Most recent closing price in ₹ |
| `market_cap_cr` | `DOUBLE` | Total market capitalization in ₹ Crores |
| `broad_sector` | `VARCHAR` | NSE Broad Sector (e.g. `Information Technology`, `Capital Goods`) |
| `sector` | `VARCHAR` | NSE Sector classification |
| `broad_industry` | `VARCHAR` | NSE Broad Industry classification |
| `industry` | `VARCHAR` | NSE Granular Industry classification |
| `band` | `VARCHAR` | Daily price circuit band (% or `No Band`) |
| `band_remarks` | `VARCHAR` | Circuit limit notes |
| `pe` | `DOUBLE` | Trailing twelve months Price-to-Earnings |
| `adjusted_pe` | `DOUBLE` | Adjusted PE excluding non-recurring items |

---

### B. `indicators_daily`
| Column | Type | Description |
| :--- | :--- | :--- |
| `trade_date` | `TIMESTAMP` | Trading session date |
| `symbol` | `VARCHAR` | Stock symbol |
| `close_price` | `DOUBLE` | Closing price (₹) |
| `ema_10`, `ema_20`, `ema_50`, `ema_100`, `ema_200` | `DOUBLE` | Exponential Moving Averages |
| `atr_14` | `DOUBLE` | 14-period Average True Range |
| `rvol` | `DOUBLE` | Relative Volume vs 20-day Average Volume ($> 1.0\times = \text{volume surge}$) |
| `delivery_pct` | `DOUBLE` | % of daily traded volume taken as delivery |
| `delivery_qty` | `BIGINT` | Total quantity delivered |
| `turnover_cr` | `DOUBLE` | Traded value in ₹ Crores |
| `return_5d_pct`, `return_1m_pct`, `return_3m_pct` | `DOUBLE` | Multi-timeframe percentage price returns |
| `rs_percentile` | `DOUBLE` | **Relative Strength Percentile (0 to 100)** vs entire NSE universe |
| `is_vcp` | `BOOLEAN` | Whether price is undergoing Volatility Contraction |
| `vcp_score` | `DOUBLE` | Quantitative quality score of the VCP setup |
| `vcp_state` | `VARCHAR` | Contraction stage (e.g. `Tighter (3T)`, `Forming`) |
| `away_52w_high_pct` | `DOUBLE` | Percentage distance below the 52-week high |
| `above_52w_low_pct` | `DOUBLE` | Percentage distance above the 52-week low |

---

### C. `candidate_daily`
| Column | Type | Description |
| :--- | :--- | :--- |
| `trade_date` | `TIMESTAMP` | Trading session date |
| `symbol` | `VARCHAR` | Stock symbol |
| `candidate_state` | `VARCHAR` | Setup conviction status (`Ready`, `Focus`, `Prepare`, `Observe`, `Monitor`) |
| `total_score` | `DOUBLE` | Composite technical, RS, and liquidity setup score (0–100) |
| `trigger_price` | `DOUBLE` | Buy pivot / breakout price level (₹) |
| `invalidation_price` | `DOUBLE` | Stop Loss level based on technical support / ATR (₹) |
| `first_resistance` | `DOUBLE` | Minimum target / initial take-profit level (₹) |
| `reward_to_risk` | `DOUBLE` | Reward-to-Risk Ratio ($R:R = \frac{\text{Target} - \text{Trigger}}{\text{Trigger} - \text{Stop Loss}}$) |
| `why_now` | `VARCHAR` | Plain-English rationale for why this setup is actionable |

---

### D. `deals_daily`
| Column | Type | Description |
| :--- | :--- | :--- |
| `trade_date` | `TIMESTAMP` | Trading date |
| `symbol` | `VARCHAR` | Stock symbol |
| `client_name` | `VARCHAR` | Exact entity name from NSE deal report |
| `deal_type` | `VARCHAR` | `BULK` or `BLOCK` |
| `buy_sell` | `VARCHAR` | `BUY` or `SELL` |
| `quantity` | `BIGINT` | Number of shares transacted |
| `trade_price` | `DOUBLE` | Weighted execution price (₹) |
| `deal_value_cr` | `DOUBLE` | Total value of transaction in ₹ Crores |
| `entity_type` | `VARCHAR` | Resolved Category (`DII`, `FII`, `Super Investor`, `Promoter`, `HFT / Arbitrage`) |

---

## 3. Mathematical Calculations & Formulas

### 1. Relative Strength (RS) Percentile (0 to 100)
MarketPulse computes Relative Strength using a weighted multi-timeframe formula benchmarked against the broad market:

$$\text{Raw RS Score} = 0.40 \cdot R_{3\text{M}} + 0.30 \cdot R_{6\text{M}} + 0.20 \cdot R_{9\text{M}} + 0.10 \cdot R_{12\text{M}}$$

The Raw RS Score is ranked across the entire NSE universe ($N \approx 2,400$ active stocks) to generate a percentile rank:

$$\text{RS Percentile} = \left( \frac{\text{Rank}(\text{Raw RS})}{N} \right) \times 100$$

*A score $\ge 80$ indicates the stock is outperforming $80\%$ of all listed Indian equities.*

### 2. Relative Volume (RVOL)
$$\text{RVOL} = \frac{\text{Volume}_{\text{Today}}}{\text{SMA}_{20}(\text{Volume})}$$

### 3. Volatility Contraction Pattern (VCP) Detection
VCP identifies cyclical volatility drying up as institutional supply gets absorbed:
* Contraction 1 ($C_1$): Price range contraction between $15\%$ and $30\%$.
* Contraction 2 ($C_2$): Price range contraction between $8\%$ and $15\%$.
* Contraction 3 ($C_3$): Price range contraction $< 8\%$ with volume declining $< 0.70\times$ 20D SMA.

### 4. Reward-to-Risk Ratio ($R:R$)
$$\text{Risk (₹)} = \text{Trigger Price} - \text{Invalidation Price (Stop Loss)}$$
$$\text{Reward (₹)} = \text{First Resistance (Target)} - \text{Trigger Price}$$
$$R:R = \frac{\text{Reward}}{\text{Risk}}$$
*MarketPulse filters require $R:R \ge 2.0\times$ for `Ready` and `Focus` candidates.*
