# Handoff — Market Environment verdict calibration (§6.1.5 ship gate)

Date: 2026-09-27 · Branch `feat/w11-verdict-calibration` · Script `python -m Scripts.evidence.verdict_study --out FILE.json`
(read-only on `Database/marketpulse.duckdb`; ~3 s, < 400 MB).

## Decision

**No verdict design separates setup outcomes out-of-sample. The ship gate is not forced.** The rule table (R0–R9),
zones and hysteresis are unchanged. The honest fallback is implemented instead:

- `regime_daily.verdict_evidence = 'descriptive_only'` and `regime_daily.verdict_evidence_note` = "Verdict does not predict
  setup outcomes out-of-sample; use it to size risk and describe conditions, not as a trade filter." on every row with a
  verdict (NULL where the verdict is NULL). Source of truth: `Scripts/derived/regime.py::VERDICT_EVIDENCE`.
- `evidence_meta.verdict_evidence` = the same status/note/study path plus this run's in-sample ship gate (plain Welch,
  pooled) for reference. The in-sample gate passing would NOT lift the flag; only a re-run of this study can.
- **For the controller (API/UI, not touched here):** `App/services/market.py` reads `SELECT * FROM regime_daily`; map
  `verdict_evidence` + `verdict_evidence_note` into the v2 regime response and show the note next to the verdict
  (e.g. an info chip under the verdict / in the proof table), and stop presenting the verdict as a filter on queues.

The columns appear after the next EOD derived step (regime_daily) and evidence step (evidence_meta); the live DB was not
written.

## Method

- **Unit:** closed setups (`setup_outcomes.status` in horizon/stopped, `r_multiple` known), 4 queues. The environment is
  read on the **signal date** (known at that EOD; fills happen later), from `regime_daily`.
- **Sample:** sessions with a published verdict only (pillars warmed up), so every design is compared on the same days.
  2020 is mostly warm-up (verdict on 53 sessions). Found in passing: `stage2_pct` is **0, not NULL**, through 2020 because
  `trend_template_pass` is False during its warm-up; the study treats 0 as unknown (it never occurs later, min 1.97).
- **Split:** train = signal dates 2020-01-01 … 2024-05-30 (the 20 sessions 2024-05-31 … 2024-06-28 are **purged** because
  their 20-session holding periods run into test); test = 2024-07-01 … 2026-09-25. Quintile/tercile cut points and every
  design parameter come from **train days**; test was evaluated once with the rules untouched.
  Train: 39,959 setups on 898 days · Test: 25,725 setups on 556 days.
- **Statistics:** means are per setup; standard errors are **cluster-robust by signal day** (`t_day`, the gate's t) and,
  more strictly, by **20-session block** (`t_blk`), because holding periods and regimes overlap across neighbouring days.
  The existing `environment_calibration` Welch t treats the 30–60 setups of one day as independent and overstates
  significance.
- **Gate:** gap = avg R(good) − avg R(bad) ≥ 0.15R, `t_day` ≥ 2, n ≥ 30 both sides, **on test**.
- **Designs (all fixed in code before the test run; all reported):** A current published verdict · A_raw same rules on raw
  statuses · B Trend status alone · C best single input on train (by |t_day| of top-vs-bottom tercile, sign from train) ·
  D equal-weight signed z-composite of inputs with train |t_day| ≥ 1 · E depth-2 split tree on the inputs (≤ 4 leaf rules,
  ≥ 120 train days per leaf, leaves labelled good/bad by train mean ± 0.1R). "good" plays the role of
  Favourable+Constructive, "bad" of Weak+Danger.

## Results in one screen

| design | train gap R (t_day / t_blk) | test gap R (t_day / t_blk) | test gate |
| :--- | :--- | :--- | :--- |
| A published verdict | −0.076 (−0.92 / −0.40) | −0.128 (−1.92 / −0.79) | fail |
| A_raw (no hysteresis) | −0.127 (−1.41 / −0.63) | −0.092 (−1.32 / −0.52) | fail |
| B Trend alone | −0.102 (−0.95 / −0.39) | −0.062 (−0.55 / −0.18) | fail |
| C best single (% > 200 EMA, low = good) | +0.138 (+2.22 / +0.81) | +0.088 (+1.57 / +0.82), only 34 bad days | fail |
| D composite (5d return, Δ% > 50 EMA, follow-through, −VIX) | +0.152 (+2.26 / +1.15), passes train | **−0.256 (−3.62 / −1.73)** | fail (sign flips) |
| E split tree (Δ net new highs × VIX ≈ 13.5) | +0.412 (+7.87 / +2.88), passes train | **−0.276 (−5.32 / −2.19)** | fail (sign flips) |

Reading:

1. **The current verdict is, if anything, backwards**: Weak/Danger days were followed by slightly *better* setup R than
   Favourable/Constructive days in both periods (train −0.08R, test −0.13R), not significant once clustered by block.
   Stress Weak was the best pillar bucket in train (+0.41R vs +0.25R Healthy); Danger was the best state in test
   (+0.04R vs −0.20R Favourable). Setups that do trigger after sell-offs tend to catch the rebound; setups in extended,
   calm markets get stopped more.
2. **What worked in train reversed in test.** Momentum/confirmation inputs (5-day MidSml400 return, 5-session change in
   % > 50 EMA, follow-through %, A/D) had a positive Q5−Q1 gap in train (t_day ≈ 1.0–1.2) and a negative one in test.
   Low VIX was good in train, high VIX in test. The two designs that passed on train (D, E) are built from exactly these
   and fail with the opposite sign out-of-sample: the textbook overfit / regime-shift signature.
3. **The periods differ in level more than in ordering:** avg R +0.25 (train) vs −0.12 (test). The whole 2024-07 … 2026-09
   window was poor for breakout setups, which no state rule on these inputs anticipated.

### Single inputs with out-of-sample value

Criterion (fixed before looking at test): same sign of the Q5−Q1 gap in train and test, test `t_day` ≥ 2, train
`|t_day|` ≥ 1. **No input meets it.** Near misses, for completeness (none should be surfaced as predictive):

| input | train Q5−Q1 (t_day) | test Q5−Q1 (t_day / t_blk) | note |
| :--- | :--- | :--- | :--- |
| % passing trend template (stage2_pct) | −0.04 (−0.45) | −0.25 (−4.08 / −2.66) | same sign, no train evidence |
| Nifty 50 % vs 200 EMA | −0.08 (−0.79) | −0.34 (−3.16 / −1.03) | same sign, weak train, block t < 2 |
| VIX 1-day change % | −0.01 (−0.14) | −0.17 (−2.04 / −1.27) | no train evidence |
| India VIX > 20.6 (train Q5) vs rest, **post hoc** | +0.19 (+2.26 / +0.97) | +1.44 (+6.35 / +4.39), 21 days, 414 setups | chosen after seeing the test quintiles; 2 episodes (Apr–May 2025, Mar–Apr 2026) |

The one pattern present in both periods is "contrarian": **high fear / low breadth was not bad for setups that actually
triggered** (VIX top quintile, low % > 200 EMA, Stress Weak / Danger). It is not validated (post hoc, few episodes), so it
is not wired into the verdict. If surfaced at all it should be a descriptive connected reading ("high-fear session:
setups that triggered in past high-fear sessions did not do worse; n, dates"), not a signal.

### What to tell the user in the UI

The verdict describes conditions (trend, breadth, leadership, follow-through, stress) and is fine for **risk sizing and
context**; the evidence does not support using it to **skip or take** setups. Keep the per-state proof table (§6.1.5);
it now honestly shows no separation.

### Caveats

- Setup R is the only target tested (20-session horizon, fill-based entry). The verdict might still help through fewer
  signals / fewer fills in bad regimes (exposure) or portfolio drawdown; not tested here.
- Test covers essentially one regime (the late-2024 / early-2025 mid/small-cap decline and its recoveries); train
  2021–2024 was a strong mid/small-cap bull. Re-run with more history using the same script and split rules.
- Momentum starts 2021-01; VCP is small (1.7k train / 1.1k test setups), so its per-queue rows are noisy.

## Tables

All numbers from `verdict_study` (JSON output). R = r_multiple; hit 2R = % reaching +2R before the stop.

### Overall (train)

| queue | n setups | days | avg R | hit 2R % |
| :--- | ---: | ---: | ---: | ---: |
| all | 39959 | 898 | +0.249 | 28.1 |
| darvas_10ema | 22852 | 892 | +0.229 | 28.4 |
| darvas_squeeze | 9951 | 861 | +0.286 | 32.0 |
| momentum | 5407 | 807 | +0.268 | 20.3 |
| vcp | 1749 | 705 | +0.257 | 25.7 |

### Overall (test)

| queue | n setups | days | avg R | hit 2R % |
| :--- | ---: | ---: | ---: | ---: |
| all | 25725 | 556 | -0.119 | 21.6 |
| darvas_10ema | 15335 | 555 | -0.137 | 22.6 |
| darvas_squeeze | 6025 | 539 | -0.133 | 24.1 |
| momentum | 3274 | 513 | -0.024 | 13.8 |
| vcp | 1091 | 414 | -0.083 | 17.5 |

### Published verdict by state (train) — avg R (n setups / days)

| state | all | darvas_10ema | darvas_squeeze | momentum | vcp |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Favourable | +0.201 (14493/285) | +0.147 (7488/284) | +0.242 (4345/284) | +0.294 (2036/280) | +0.255 (624/243) |
| Constructive | +0.297 (7723/162) | +0.270 (4353/162) | +0.321 (2057/162) | +0.293 (981/122) | +0.504 (332/124) |
| Mixed | +0.245 (11370/261) | +0.259 (6695/260) | +0.257 (2562/249) | +0.206 (1575/242) | +0.121 (538/206) |
| Weak | +0.356 (3670/87) | +0.339 (2542/85) | +0.516 (521/77) | +0.297 (465/76) | +0.269 (142/66) |
| Danger | +0.247 (2703/103) | +0.195 (1774/101) | +0.435 (466/89) | +0.284 (350/87) | +0.174 (113/66) |

### Published verdict by state (test) — avg R (n setups / days)

| state | all | darvas_10ema | darvas_squeeze | momentum | vcp |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Favourable | -0.203 (4348/79) | -0.227 (2342/79) | -0.224 (1314/79) | -0.085 (500/76) | -0.076 (192/69) |
| Constructive | -0.089 (4366/75) | -0.112 (2452/75) | -0.100 (1146/75) | +0.018 (578/72) | -0.045 (190/63) |
| Mixed | -0.197 (8375/176) | -0.238 (4772/175) | -0.181 (2080/171) | -0.079 (1142/164) | -0.117 (381/136) |
| Weak | -0.056 (5353/113) | -0.067 (3401/113) | -0.074 (990/113) | +0.023 (742/108) | -0.061 (220/84) |
| Danger | +0.045 (3283/113) | +0.031 (2368/113) | +0.115 (495/101) | +0.082 (312/93) | -0.082 (108/62) |

### Pillar status, pooled (train) — avg R · hit 2R % · n setups / days

| pillar | Healthy | Neutral | Weak |
| :--- | ---: | ---: | ---: |
| trend | +0.254 · 28.2 · 32340/668 | +0.162 · 27.2 · 4873/129 | +0.356 · 28.5 · 2746/101 |
| participation | +0.264 · 28.2 · 22673/422 | +0.277 · 29.5 · 10389/232 | +0.161 · 25.8 · 6897/244 |
| leadership | +0.227 · 26.6 · 19198/403 | +0.232 · 28.8 · 16010/355 | +0.289 · 28.0 · 2497/73 |
| follow_through | +0.288 · 28.5 · 22519/418 | +0.224 · 27.9 · 12863/312 | +0.134 · 26.9 · 4577/168 |
| stress | +0.251 · 27.5 · 15339/283 | +0.114 · 27.4 · 13613/318 | +0.415 · 29.9 · 11007/297 |

Per queue, avg R Healthy / Neutral / Weak (train):

| pillar | darvas_10ema | darvas_squeeze | momentum | vcp |
| :--- | :--- | :--- | :--- | :--- |
| trend | +0.23 / +0.20 / +0.28 | +0.29 / +0.01 / +0.63 | +0.27 / +0.17 / +0.36 | +0.28 / +0.17 / +0.21 |
| participation | +0.21 / +0.29 / +0.18 | +0.32 / +0.28 / +0.11 | +0.33 / +0.23 / +0.14 | +0.29 / +0.29 / +0.14 |
| leadership | +0.18 / +0.22 / +0.31 | +0.26 / +0.28 / +0.23 | +0.30 / +0.21 / +0.29 | +0.28 / +0.16 / +0.08 |
| follow_through | +0.25 / +0.24 / +0.11 | +0.34 / +0.19 / +0.18 | +0.33 / +0.20 / +0.20 | +0.33 / +0.27 / +0.09 |
| stress | +0.21 / +0.07 / +0.43 | +0.28 / +0.18 / +0.46 | +0.33 / +0.12 / +0.34 | +0.31 / +0.26 / +0.20 |

### Pillar status, pooled (test) — avg R · hit 2R % · n setups / days

| pillar | Healthy | Neutral | Weak |
| :--- | ---: | ---: | ---: |
| trend | -0.139 · 21.0 · 11955/216 | -0.110 · 21.9 · 10586/223 | -0.077 · 22.9 · 3184/117 |
| participation | -0.186 · 20.3 · 7824/127 | -0.130 · 21.9 · 7895/135 | -0.059 · 22.4 · 10006/294 |
| leadership | -0.154 · 20.7 · 9107/180 | -0.135 · 21.9 · 11934/245 | -0.014 · 22.6 · 4684/131 |
| follow_through | -0.136 · 21.6 · 10852/177 | -0.147 · 21.2 · 10566/236 | -0.009 · 22.6 · 4307/143 |
| stress | -0.148 · 20.9 · 10424/190 | -0.052 · 22.3 · 6733/141 | -0.138 · 22.0 · 8568/225 |

Per queue, avg R Healthy / Neutral / Weak (test):

| pillar | darvas_10ema | darvas_squeeze | momentum | vcp |
| :--- | :--- | :--- | :--- | :--- |
| trend | -0.15 / -0.13 / -0.12 | -0.18 / -0.10 / +0.04 | -0.05 / -0.02 / +0.06 | -0.08 / -0.08 / -0.10 |
| participation | -0.22 / -0.16 / -0.06 | -0.19 / -0.13 / -0.07 | -0.06 / +0.03 / -0.04 | -0.07 / -0.14 / -0.06 |
| leadership | -0.20 / -0.15 / -0.02 | -0.16 / -0.14 / -0.03 | -0.01 / -0.07 / +0.08 | -0.01 / -0.14 / -0.10 |
| follow_through | -0.14 / -0.18 / -0.03 | -0.17 / -0.14 / +0.05 | -0.05 / -0.01 / -0.01 | -0.05 / -0.18 / +0.04 |
| stress | -0.18 / -0.07 / -0.14 | -0.13 / -0.06 / -0.20 | -0.05 / +0.04 / -0.05 | -0.12 / +0.01 / -0.10 |

### Raw inputs by train-quintile of the entry-day value, pooled (train)

Q1 = lowest. Cells: avg R (days). Gap = Q5 − Q1 avg R; t_day = clustered by signal day, t_blk = by 20-session block. Per-queue column: Q5−Q1 gap / t_day.

| input | train edges | Q1 | Q2 | Q3 | Q4 | Q5 | gap | t_day | t_blk | darvas_10ema | darvas_squeeze | momentum | vcp |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- | :--- | :--- |
| MidSml400 % vs 50 EMA | -0.36, 2.59, 4.6, 6.2 | +0.23 (180) | +0.22 (179) | +0.12 (180) | +0.41 (179) | +0.24 (180) | +0.01 | +0.13 | +0.06 | -0.07 / -0.6 | +0.12 / +1.1 | +0.18 / +2.1 | +0.22 / +1.5 |
| MidSml400 % vs 200 EMA | 3.45, 9.38, 15.41, 19.97 | +0.21 (180) | +0.10 (179) | +0.45 (180) | +0.17 (179) | +0.23 (180) | +0.02 | +0.29 | +0.11 | +0.06 / +0.6 | -0.17 / -1.6 | +0.17 / +1.9 | +0.04 / +0.3 |
| MidSml400 50 EMA 5-session slope % | -0.07, 0.52, 0.95, 1.26 | +0.22 (180) | +0.24 (179) | +0.13 (180) | +0.41 (179) | +0.22 (180) | +0.00 | +0.03 | +0.01 | -0.07 / -0.6 | +0.03 / +0.3 | +0.15 / +1.8 | +0.23 / +1.5 |
| Nifty 50 % vs 200 EMA | 2.5, 5.49, 8.32, 12.29 | +0.35 (180) | +0.28 (179) | +0.13 (180) | +0.27 (179) | +0.27 (180) | -0.08 | -0.79 | -0.32 | -0.07 / -0.6 | -0.20 / -1.8 | +0.05 / +0.5 | +0.06 / +0.4 |
| MidSml400 5-session return % | -1.22, 0.35, 1.53, 2.73 | +0.12 (180) | +0.16 (179) | +0.33 (180) | +0.32 (179) | +0.22 (180) | +0.09 | +1.05 | +0.62 | +0.05 / +0.5 | +0.22 / +1.9 | +0.08 / +0.9 | +0.14 / +1.1 |
| % stocks > 50 EMA | 39.12, 52.68, 65.5, 74.31 | +0.27 (180) | +0.22 (179) | +0.14 (180) | +0.36 (179) | +0.24 (180) | -0.03 | -0.33 | -0.14 | -0.10 / -0.9 | +0.00 / +0.0 | +0.11 / +1.3 | +0.27 / +1.8 |
| % stocks > 200 EMA | 48.53, 61.73, 71.78, 79.67 | +0.31 (180) | +0.25 (179) | +0.28 (180) | +0.17 (179) | +0.26 (180) | -0.05 | -0.58 | -0.23 | -0.01 / -0.1 | -0.24 / -2.5 | +0.13 / +1.6 | -0.02 / -0.2 |
| % stocks > 10 EMA | 32.46, 47.82, 59.2, 68.95 | +0.25 (180) | +0.06 (179) | +0.32 (180) | +0.34 (179) | +0.23 (180) | -0.02 | -0.24 | -0.13 | -0.11 / -1.0 | +0.10 / +0.8 | +0.09 / +1.1 | +0.15 / +1.1 |
| % > 50 EMA, 5-session change | -8.68, -1.7, 2.92, 9.32 | +0.10 (180) | +0.21 (179) | +0.32 (180) | +0.34 (179) | +0.19 (180) | +0.10 | +1.16 | +0.63 | +0.05 / +0.4 | +0.25 / +2.3 | +0.15 / +1.9 | +0.09 / +0.7 |
| 10-session A/D sum | -2414.8, -865.2, 406.2, 1506.2 | +0.22 (180) | +0.17 (179) | +0.24 (180) | +0.29 (179) | +0.30 (180) | +0.08 | +0.84 | +0.43 | -0.02 / -0.2 | +0.28 / +2.5 | +0.14 / +1.7 | +0.36 / +2.4 |
| Net new highs, 10-session avg | 13.7, 51.0, 84.8, 126.9 | +0.27 (167) | +0.20 (167) | +0.15 (167) | +0.25 (167) | +0.29 (168) | +0.02 | +0.25 | +0.10 | +0.00 / +0.0 | -0.01 / -0.1 | +0.05 / +0.6 | +0.15 / +1.1 |
| Net new highs avg, 5-session change | -25.7, -3.3, 8.3, 22.6 | +0.24 (166) | +0.23 (166) | +0.27 (166) | +0.17 (166) | +0.26 (167) | +0.03 | +0.25 | +0.12 | -0.04 / -0.4 | +0.15 / +1.3 | +0.01 / +0.1 | +0.23 / +1.5 |
| % passing trend template | 10.01, 13.95, 17.7, 20.47 | +0.29 (169) | +0.11 (169) | +0.30 (169) | +0.20 (169) | +0.25 (169) | -0.04 | -0.45 | -0.17 | -0.05 / -0.5 | -0.05 / -0.5 | -0.05 / -0.6 | -0.04 / -0.2 |
| Follow-through % | 36.24, 45.62, 52.63, 59.04 | +0.11 (180) | +0.13 (179) | +0.33 (180) | +0.37 (179) | +0.21 (180) | +0.10 | +1.12 | +0.59 | +0.06 / +0.6 | +0.13 / +1.2 | +0.15 / +1.9 | +0.13 / +1.0 |
| Distribution days (25) | 2.0, 3.0, 4.0, 5.0 | +0.57 (137) | +0.07 (141) | +0.01 (180) | +0.07 (179) | +0.46 (261) | -0.11 | -1.44 | -0.59 | -0.10 / -1.0 | -0.07 / -0.7 | -0.12 / -1.6 | -0.45 / -3.0 |
| India VIX level | 12.49, 14.75, 17.68, 20.63 | +0.51 (180) | +0.27 (179) | -0.09 (178) | +0.05 (181) | +0.41 (180) | -0.09 | -1.03 | -0.46 | -0.10 / -0.9 | -0.08 / -0.7 | -0.12 / -1.4 | -0.06 / -0.4 |
| VIX 1-day change % | -3.27, -1.32, 0.74, 3.2 | +0.22 (180) | +0.29 (179) | +0.18 (180) | +0.34 (179) | +0.21 (180) | -0.01 | -0.14 | -0.09 | -0.03 / -0.2 | +0.02 / +0.2 | +0.06 / +0.8 | -0.12 / -0.9 |
| VIX 5-session change % | -7.53, -2.55, 1.59, 7.94 | +0.25 (180) | +0.30 (179) | +0.20 (180) | +0.30 (179) | +0.18 (180) | -0.07 | -0.82 | -0.50 | -0.07 / -0.7 | -0.06 / -0.5 | -0.14 / -1.9 | +0.05 / +0.4 |

### Raw inputs by train-quintile of the entry-day value, pooled (test)

Q1 = lowest. Cells: avg R (days). Gap = Q5 − Q1 avg R; t_day = clustered by signal day, t_blk = by 20-session block. Per-queue column: Q5−Q1 gap / t_day.

| input | train edges | Q1 | Q2 | Q3 | Q4 | Q5 | gap | t_day | t_blk | darvas_10ema | darvas_squeeze | momentum | vcp |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- | :--- | :--- |
| MidSml400 % vs 50 EMA | -0.36, 2.59, 4.6, 6.2 | -0.10 (185) | -0.20 (190) | -0.07 (114) | +0.00 (47) | -0.20 (20) | -0.09 | -1.11 | -0.56 | -0.12 / -1.1 | -0.18 / -1.8 | +0.07 / +0.5 | +0.58 / +2.0 |
| MidSml400 % vs 200 EMA | 3.45, 9.38, 15.41, 19.97 | -0.04 (240) | -0.16 (237) | -0.08 (32) | -0.16 (37) | -0.20 (10) | -0.17 | -1.68 | -0.97 | -0.21 / -1.5 | -0.27 / -2.6 | -0.01 / -0.0 | +0.72 / +2.0 |
| MidSml400 50 EMA 5-session slope % | -0.07, 0.52, 0.95, 1.26 | -0.11 (186) | -0.14 (181) | -0.12 (128) | -0.03 (43) | -0.18 (18) | -0.07 | -0.75 | -0.37 | -0.10 / -0.8 | -0.18 / -1.7 | +0.15 / +0.9 | +0.47 / +1.9 |
| Nifty 50 % vs 200 EMA | 2.5, 5.49, 8.32, 12.29 | -0.09 (292) | -0.19 (158) | -0.06 (45) | -0.04 (49) | -0.43 (12) | -0.34 | -3.16 | -1.03 | -0.45 / -4.3 | -0.38 / -2.5 | -0.01 / -0.0 | +0.42 / +0.5 |
| MidSml400 5-session return % | -1.22, 0.35, 1.53, 2.73 | +0.01 (149) | -0.15 (141) | -0.13 (120) | -0.20 (78) | -0.10 (68) | -0.11 | -1.14 | -0.73 | -0.16 / -1.4 | -0.02 / -0.2 | +0.01 / +0.1 | +0.06 / +0.2 |
| % stocks > 50 EMA | 39.12, 52.68, 65.5, 74.31 | -0.21 (234) | -0.08 (126) | -0.06 (97) | -0.08 (57) | -0.12 (42) | +0.09 | +1.37 | +0.62 | +0.03 / +0.4 | +0.10 / +1.2 | +0.24 / +2.1 | +0.86 / +2.4 |
| % stocks > 200 EMA | 48.53, 61.73, 71.78, 79.67 | -0.06 (404) | -0.29 (69) | -0.07 (30) | -0.21 (53) | — | — | — | — | — / — | — / — | — / — | — / — |
| % stocks > 10 EMA | 32.46, 47.82, 59.2, 68.95 | -0.00 (171) | -0.14 (150) | -0.18 (94) | -0.21 (58) | -0.05 (83) | -0.05 | -0.58 | -0.30 | -0.03 / -0.3 | -0.15 / -1.4 | -0.00 / -0.0 | +0.15 / +0.7 |
| % > 50 EMA, 5-session change | -8.68, -1.7, 2.92, 9.32 | -0.03 (126) | -0.08 (146) | -0.25 (93) | -0.10 (79) | -0.13 (112) | -0.10 | -1.36 | -0.80 | -0.13 / -1.4 | -0.11 / -1.1 | +0.01 / +0.1 | -0.03 / -0.2 |
| 10-session A/D sum | -2414.8, -865.2, 406.2, 1506.2 | -0.09 (226) | -0.14 (108) | -0.02 (76) | -0.30 (58) | -0.11 (88) | -0.02 | -0.34 | -0.17 | +0.00 / +0.0 | -0.09 / -1.1 | -0.00 / -0.0 | +0.05 / +0.3 |
| Net new highs, 10-session avg | 13.7, 51.0, 84.8, 126.9 | -0.14 (241) | -0.08 (154) | -0.09 (86) | -0.20 (52) | -0.13 (23) | +0.01 | +0.13 | +0.07 | -0.03 / -0.3 | -0.07 / -0.8 | +0.10 / +1.0 | +0.43 / +2.1 |
| Net new highs avg, 5-session change | -25.7, -3.3, 8.3, 22.6 | -0.03 (117) | -0.04 (164) | -0.18 (86) | -0.17 (88) | -0.25 (101) | -0.21 | -2.16 | -1.10 | -0.19 / -1.6 | -0.27 / -2.5 | -0.18 / -1.9 | -0.26 / -1.6 |
| % passing trend template | 10.01, 13.95, 17.7, 20.47 | -0.01 (328) | -0.24 (124) | -0.50 (57) | +0.08 (32) | -0.26 (15) | -0.25 | -4.08 | -2.66 | -0.39 / -4.8 | -0.24 / -2.7 | +0.02 / +0.1 | +1.15 / +1.5 |
| Follow-through % | 36.24, 45.62, 52.63, 59.04 | +0.01 (159) | -0.11 (120) | -0.20 (138) | -0.12 (69) | -0.12 (70) | -0.13 | -1.38 | -0.76 | -0.12 / -1.1 | -0.21 / -2.0 | -0.08 / -0.8 | +0.08 / +0.4 |
| Distribution days (25) | 2.0, 3.0, 4.0, 5.0 | -0.14 (26) | -0.10 (103) | -0.07 (115) | -0.19 (108) | -0.13 (204) | +0.01 | +0.07 | +0.04 | +0.04 / +0.4 | -0.10 / -0.7 | +0.11 / +0.8 | -0.29 / -0.8 |
| India VIX level | 12.49, 14.75, 17.68, 20.63 | -0.27 (189) | -0.22 (204) | +0.04 (95) | +0.40 (47) | +1.29 (21) | +1.56 | +6.90 | +4.79 | +1.68 / +6.7 | +1.75 / +4.2 | +1.12 / +7.9 | +0.47 / +1.2 |
| VIX 1-day change % | -3.27, -1.32, 0.74, 3.2 | +0.02 (118) | -0.21 (107) | -0.18 (125) | -0.11 (87) | -0.15 (119) | -0.17 | -2.04 | -1.27 | -0.25 / -2.5 | -0.04 / -0.4 | -0.12 / -1.3 | -0.05 / -0.3 |
| VIX 5-session change % | -7.53, -2.55, 1.59, 7.94 | -0.01 (111) | -0.20 (130) | -0.12 (84) | -0.16 (128) | -0.09 (103) | -0.07 | -0.80 | -0.51 | -0.10 / -0.9 | -0.07 / -0.6 | -0.07 / -0.7 | +0.07 / +0.4 |

### Candidate designs — good (Fav+Con equivalent) vs bad (Weak+Danger equivalent)

| design | split | n good / bad | days good / bad | avg R good | avg R bad | gap R | t_day | t_blk | gate |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| A_published | train | 22216 / 6373 | 447 / 190 | +0.234 | +0.310 | **-0.076** | -0.92 | -0.40 | fail |
| A_published | test | 8714 / 8636 | 154 / 226 | -0.146 | -0.018 | **-0.128** | -1.92 | -0.79 | fail |
| A_raw | train | 24689 / 4914 | 466 / 180 | +0.219 | +0.346 | **-0.127** | -1.41 | -0.63 | fail |
| A_raw | test | 9757 / 6951 | 155 / 224 | -0.122 | -0.029 | **-0.092** | -1.32 | -0.52 | fail |
| B_trend_only | train | 32340 / 2746 | 668 / 101 | +0.254 | +0.356 | **-0.102** | -0.95 | -0.39 | fail |
| B_trend_only | test | 11955 / 3184 | 216 / 117 | -0.139 | -0.077 | **-0.062** | -0.55 | -0.18 | fail |
| C_best_single | train | 10161 / 15196 | 299 / 299 | +0.312 | +0.175 | **+0.138** | +2.22 | +0.81 | fail |
| C_best_single | test | 19480 / 2377 | 457 / 34 | -0.090 | -0.178 | **+0.088** | +1.57 | +0.82 | fail |
| D_composite | train | 18256 / 8124 | 299 / 299 | +0.270 | +0.117 | **+0.152** | +2.26 | +1.15 | PASS |
| D_composite | test | 10296 / 5459 | 161 / 200 | -0.193 | +0.063 | **-0.256** | -3.62 | -1.73 | fail |
| E_tree | train | 16229 / 21476 | 277 / 554 | +0.468 | +0.056 | **+0.412** | +7.87 | +2.88 | PASS |
| E_tree | test | 13874 / 11851 | 281 / 275 | -0.247 | +0.030 | **-0.276** | -5.32 | -2.19 | fail |

Per queue gap R / t_day:

| design | split | darvas_10ema | darvas_squeeze | momentum | vcp |
| :--- | :--- | :--- | :--- | :--- | :--- |
| A_published | train | -0.09 / -0.9 | -0.21 / -2.1 | +0.00 / +0.0 | +0.11 / +0.8 |
| A_published | test | -0.14 / -1.7 | -0.16 / -2.0 | -0.07 / -1.0 | +0.01 / +0.1 |
| A_raw | train | -0.16 / -1.4 | -0.24 / -2.1 | -0.01 / -0.1 | +0.16 / +1.2 |
| A_raw | test | -0.10 / -1.1 | -0.16 / -1.9 | +0.01 / +0.1 | -0.01 / -0.1 |
| B_trend_only | train | -0.05 / -0.4 | -0.34 / -2.5 | -0.09 / -0.9 | +0.06 / +0.4 |
| B_trend_only | test | -0.03 / -0.2 | -0.22 / -1.4 | -0.11 / -1.0 | +0.02 / +0.1 |
| C_best_single | train | +0.15 / +1.9 | +0.22 / +2.9 | -0.04 / -0.6 | +0.12 / +1.0 |
| C_best_single | test | +0.13 / +1.8 | +0.13 / +1.6 | -0.01 / -0.1 | -0.43 / -1.4 |
| D_composite | train | +0.10 / +1.2 | +0.27 / +3.4 | +0.20 / +3.2 | +0.10 / +0.9 |
| D_composite | test | -0.30 / -3.3 | -0.24 / -2.9 | -0.13 / -1.7 | -0.13 / -0.9 |
| E_tree | train | +0.46 / +6.9 | +0.37 / +5.8 | +0.31 / +6.4 | +0.30 / +3.0 |
| E_tree | test | -0.29 / -4.5 | -0.25 / -4.3 | -0.26 / -4.8 | -0.23 / -2.4 |

Design parameters (fitted on train):

- **A_published** — Current published verdict (hysteresis), Fav+Con vs Weak+Danger. `{}`
- **A_raw** — Current rules on raw (unsmoothed) statuses. `{}`
- **B_trend_only** — Trend status alone: Healthy=good, Weak=bad. `{}`
- **C_best_single** — Best single train input (above_200ema_pct, sign -1), train terciles. `{"input": "above_200ema_pct", "sign": -1, "lo": 55.8722, "hi": 74.8256}`
- **D_composite** — Equal-weight signed z-composite of train-significant inputs, train terciles. `{"signs": {"midsml_ret_5d_pct": 1.0, "above_50ema_chg_5d": 1.0, "follow_through_pct": 1.0, "vix_close": -1.0}, "lo": -0.2102, "hi": 0.4377}`
- **E_tree** — Depth-2 split tree on inputs (<=4 leaf rules), leaves labelled on train. `{"leaves": [{"conds": [["net_new_highs_10d_chg_5d", "<=", 3.9], ["vix_close", "<=", 13.743]], "train_mean": 0.5221, "train_days": 139, "label": "good"}, {"conds": [["net_new_highs_10d_chg_5d", "<=", 3.9], ["vix_close", ">", 13.743]], "train_mean": 0.0443, "train_days": 276, "label": "bad"}, {"conds": [["net_new_highs_10d_chg_5d", ">", 3.9], ["vix_close", "<=", 13.347]], "train_mean": 0.4152, "train_days": 138, "label": "good"}, {"conds": [["net_new_highs_10d_chg_5d", ">", 3.9], ["vix_close", ">", 13.347]], "train_mean": 0.0671, "train_days": 278, "label": "bad"}]}`

## Commits

- `evidence: verdict calibration study (purged train/test, day-clustered t, 6 designs)`: `Scripts/evidence/verdict_study.py`
- `regime: verdict_evidence flag (descriptive_only) on regime_daily and evidence_meta`: `Scripts/derived/regime.py`,
  `Scripts/evidence/__init__.py`, `Scripts/derived/SCHEMA.md`, `tests/test_derived_regime.py`, `tests/test_evidence_build.py`
- this handoff
