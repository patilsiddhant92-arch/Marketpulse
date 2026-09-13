# UC run-start feature lift (master-band exploratory)

**DB:** `D:\Sid\MarketPulse2.0\Database\marketpulse.duckdb` (read-only)  
**Generated:** 2026-09-13 02:17:47.785054  
**UC eps:** high >= prev_close*(1+band/100)*0.9995  
**Liquidity:** ADV20 >= 1.0 at T-1; controls: industry+band+ADV quintile; up to 3/event; seed 42

## Event counts (band 10/20, EQ, ADV filter)

| Metric | Value |
|---|---|
| Events after ADV>=1 | 1777 |
| Events mcap>=500 | 1542 |
| Match rate >=1 control | 68.9% (1224) |
| Match rate >=3 controls | 43.7% (776) |
| Orphans | 553 |
| Control rows sampled | 2917 |

### mcap>=500 cut

| Metric | Value |
|---|---|
| Events | 1542 |
| Match >=1 | 69.9% |
| Match >=3 | 44.0% |

### Optional 5% appendix: {'events_adv_ge1': 4655}

## Coverage
- prices EQ: 2024-05-06 → 2026-09-11; rows=1086132; symbols=2373
- security_reference_daily.price_band: None
- sector join: master.`None` → sector_rotation.`None`; feats=['turnover_share_delta_5d', 'rotation_state']
- indicator features used: ['rvol', 'delivery_pct', 'avg_delivery_pct_20d', 'delivery_spike', 'atr_pct', 'range_10d_pct', 'range_20d_pct', 'ema_stack_bullish', 'away_52w_high_pct', 'near_52w_high', 'rs_percentile', 'rs_rank_t5', 'contraction_score', 'volume_dryup_pct', 'avg_traded_value_cr_20d']
- time split: train T < 2025-07-01; test T >= 2025-07-01
- train events: 793; test events: 984

## T-1 lift (all events, band 10/20)

| feature | type | thr | ev_mean | ctrl_mean | ev_med | ctrl_med | ev_rate | ctrl_rate | lift | n_ev | n_ctrl |
|---|---|---|---|---|---|---|---|---|---|---|---|
| deals_5d_t1 | continuous | >=1.0 | 0.2594 | 0.134 | 0.0 | 0.0 | 0.0298 | 0.0082 | 3.625 | 1777 | 2917 |
| delivery_spike_t1 | bool | true | 0.1795 | 0.1011 | nan | nan | 0.1795 | 0.1011 | 1.775 | 1777 | 2917 |
| range_20d_pct_t1 | continuous | >=25.0 | 29.2054 | 22.3789 | 24.1703 | 19.2159 | 0.4693 | 0.2677 | 1.753 | 1777 | 2917 |
| range_10d_pct_t1 | continuous | >=15.0 | 21.105 | 16.153 | 17.2376 | 13.3998 | 0.619 | 0.3997 | 1.549 | 1777 | 2917 |
| rvol_t1 | continuous | >=1.5 | 1.4514 | 1.0841 | 0.883 | 0.7274 | 0.2617 | 0.1704 | 1.536 | 1777 | 2917 |
| ema_stack_bullish_t1 | bool | true | 0.099 | 0.0737 | nan | nan | 0.099 | 0.0737 | 1.344 | 1777 | 2917 |
| away_52w_high_pct_t1 | continuous | >-10.0 | -29.0458 | -26.1069 | -26.5659 | -23.5712 | 0.2454 | 0.206 | 1.191 | 1777 | 2917 |
| near_52w_high_t1 | bool | true | 0.2425 | 0.2053 | nan | nan | 0.2425 | 0.2053 | 1.181 | 1777 | 2917 |
| rs_percentile_t1 | continuous | >=70.0 | 52.5007 | 53.2909 | 53.0026 | 54.3155 | 0.184 | 0.1618 | 1.137 | 873 | 1437 |
| atr_pct_t1 | continuous | >=3.0 | 5.6219 | 4.5679 | 5.1223 | 4.2689 | 0.9584 | 0.8474 | 1.131 | 1777 | 2917 |
| avg_traded_value_cr_20d_t1 | continuous | >=5.0 | 30.8631 | 17.4585 | 7.3755 | 6.39 | 0.5926 | 0.5643 | 1.05 | 1777 | 2917 |
| contraction_score_t1 | continuous | >=0.5 | 63.8576 | 68.2122 | 75.0 | 75.0 | 0.9893 | 0.9931 | 0.996 | 1777 | 2917 |
| avg_delivery_pct_20d_t1 | continuous | >=40.0 | 46.7545 | 49.5715 | 47.9289 | 50.247 | 0.7591 | 0.8636 | 0.879 | 1762 | 2905 |
| delivery_pct_t1 | continuous | >=50.0 | 45.7147 | 49.0778 | 46.65 | 49.66 | 0.408 | 0.4889 | 0.835 | 1777 | 2917 |
| volume_dryup_pct_t1 | continuous | >=0.3 | -44.6074 | -11.9416 | -2.4141 | 16.2635 | 0.4834 | 0.6061 | 0.798 | 1753 | 2893 |
| feat_t1 | continuous | None | nan | nan | nan | nan | nan | nan | nan | 1777 | 2917 |
| rs_rank_t5_t1 | continuous | None | 51.3338 | 53.4198 | 52.1466 | 55.1043 | nan | nan | nan | 851 | 1416 |

## Top features by lift

- **deals_5d_t1**: lift=3.625 (ev_rate=0.0298 / ctrl_rate=0.0082, thr=>=1.0)
- **delivery_spike_t1**: lift=1.775 (ev_rate=0.1795 / ctrl_rate=0.1011, thr=true)
- **range_20d_pct_t1**: lift=1.753 (ev_rate=0.4693 / ctrl_rate=0.2677, thr=>=25.0)
- **range_10d_pct_t1**: lift=1.549 (ev_rate=0.619 / ctrl_rate=0.3997, thr=>=15.0)
- **rvol_t1**: lift=1.536 (ev_rate=0.2617 / ctrl_rate=0.1704, thr=>=1.5)
- **ema_stack_bullish_t1**: lift=1.344 (ev_rate=0.099 / ctrl_rate=0.0737, thr=true)
- **away_52w_high_pct_t1**: lift=1.191 (ev_rate=0.2454 / ctrl_rate=0.206, thr=>-10.0)
- **near_52w_high_t1**: lift=1.181 (ev_rate=0.2425 / ctrl_rate=0.2053, thr=true)
- **rs_percentile_t1**: lift=1.137 (ev_rate=0.184 / ctrl_rate=0.1618, thr=>=70.0)
- **atr_pct_t1**: lift=1.131 (ev_rate=0.9584 / ctrl_rate=0.8474, thr=>=3.0)

## Train vs Test lift (strong features)

### Train
- delivery_spike_t1: lift=1.841
- range_20d_pct_t1: lift=1.626
- rvol_t1: lift=1.551
- range_10d_pct_t1: lift=1.437
- atr_pct_t1: lift=1.086
- away_52w_high_pct_t1: lift=1.03
- near_52w_high_t1: lift=1.03
- avg_traded_value_cr_20d_t1: lift=1.026
### Test
- deals_5d_t1: lift=3.355
- range_20d_pct_t1: lift=1.939
- delivery_spike_t1: lift=1.729
- range_10d_pct_t1: lift=1.719
- away_52w_high_pct_t1: lift=1.647
- near_52w_high_t1: lift=1.623
- rvol_t1: lift=1.546
- ema_stack_bullish_t1: lift=1.34

## False-positive framing

Among random eligible non-event symbol-days (ADV>=1, band 10/20) passing the top 2 lift rules, how often is there a UC run-start in the next 5 sessions (incl. T)?

```json
{
  "rules": [
    {
      "feature": "delivery_spike_t1",
      "threshold": "true",
      "lift": 1.775,
      "event_rate": 0.1795,
      "control_rate": 0.1011
    },
    {
      "feature": "range_20d_pct_t1",
      "threshold": ">=25.0",
      "lift": 1.753,
      "event_rate": 0.4693,
      "control_rate": 0.2677
    }
  ],
  "eligible_passing": 162,
  "uc_runstart_next5": 4,
  "rate": 0.0247
}
```

## Recommendation

**GRADUATE-CANDIDATE (lab only — still master-band leakage risk)** — stable OOS strong lifts: ['range_10d_pct_t1', 'range_20d_pct_t1', 'rvol_t1']

## Honesty / do-not-ship notes

1. **Master band ≠ historical band.** `stocks_master.band` is current; `security_reference_daily.price_band` only covers ~Jul–Aug 2026. Labels can be wrong for names that changed bands.
2. **Price history only ~2024-05 to 2026-09** — short sample; OOS split is fragile.
3. **5% names are GSM/illiquid-heavy** — primary table is band 10/20 only; 5% is appendix counts only.
4. **No Darvas in DB** — cannot use Darvas/squeeze persistence; range/contraction proxies only.
5. **Control construction** excludes UC run-starts in T..T+4 for controls; match on broad_industry + band + ADV quintile.
6. **Thresholds** are researcher-chosen (documented in script THRESHOLDS); lift is sensitive to cutoff.
7. Default stance: **do not ship** a pre-limit screener unless OOS lift is stable for ≥2 independent rules.

## Outputs
- `C:\Users\SIDDHA~1\AppData\Local\Temp\uc_lift_summary.md`
- `C:\Users\SIDDHA~1\AppData\Local\Temp\uc_lift_features.csv`
- `C:\Users\SIDDHA~1\AppData\Local\Temp\uc_lift_meta.json`