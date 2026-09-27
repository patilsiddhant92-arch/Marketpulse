/**
 * Realistic fixture envelopes for the Research tab. Used by Vitest and by the
 * dev-only "Fixtures" toggle while the evidence tables are being built.
 * Never imported in production code paths (the loader sits behind
 * import.meta.env.DEV so Rollup drops this chunk from the build).
 *
 * Shapes match the FINAL v2 row models (frontend/openapi.json) plus the
 * optional extras documented in ./model.ts.
 */
import type { BigMoveRow, EvidenceRow, MarketAnalogRow, PreMoveRow, StockAnalogRow } from '../../api/types';

const AS_OF = '2026-09-25';
const FRESH = { status: 'fresh', latest_session: AS_OF, expected_session: AS_OF, sessions_behind: 0, history_mode: false };

export function fixtureEnvelope<R>(
  rows: R[],
  context: Record<string, unknown> = {},
  asOf: string | null = null,
  extra: Record<string, unknown> = {},
) {
  return {
    as_of: asOf ?? AS_OF,
    freshness: asOf && asOf !== AS_OF ? { ...FRESH, history_mode: true } : FRESH,
    total: rows.length,
    returned: rows.length,
    rows,
    meta: {
      status: 'ok' as const,
      reason: null,
      sources: ['fixture'],
      notes: [],
      offset: 0,
      limit: 500,
      metric_keys: [],
      context,
      ...extra,
    },
  };
}

// ------------------------------------------------------------------ market analogs

export const ANALOG_ROWS: MarketAnalogRow[] = [
  {
    analog_date: '2023-11-03',
    distance: 0.62,
    fwd_midsml400_5d_pct: 2.1,
    fwd_midsml400_20d_pct: 6.8,
    fwd_midsml400_60d_pct: 14.2,
    next_month_follow_through_pct: 58,
    verdict_then: 'Constructive',
  },
  {
    analog_date: '2021-06-18',
    distance: 0.71,
    fwd_midsml400_5d_pct: 1.4,
    fwd_midsml400_20d_pct: 4.9,
    fwd_midsml400_60d_pct: 9.7,
    next_month_follow_through_pct: 55,
    verdict_then: 'Constructive',
  },
  {
    analog_date: '2019-02-22',
    distance: 0.84,
    fwd_midsml400_5d_pct: -0.6,
    fwd_midsml400_20d_pct: 3.2,
    fwd_midsml400_60d_pct: 6.1,
    next_month_follow_through_pct: 47,
    verdict_then: 'Mixed',
  },
  {
    analog_date: '2024-06-07',
    distance: 0.88,
    fwd_midsml400_5d_pct: 3.3,
    fwd_midsml400_20d_pct: 7.5,
    fwd_midsml400_60d_pct: 11.0,
    next_month_follow_through_pct: 61,
    verdict_then: 'Favourable',
  },
  {
    analog_date: '2017-08-25',
    distance: 0.97,
    fwd_midsml400_5d_pct: 0.8,
    fwd_midsml400_20d_pct: 2.6,
    fwd_midsml400_60d_pct: 8.4,
    next_month_follow_through_pct: 52,
    verdict_then: 'Constructive',
  },
  {
    analog_date: '2022-03-11',
    distance: 1.05,
    fwd_midsml400_5d_pct: -1.9,
    fwd_midsml400_20d_pct: -3.4,
    fwd_midsml400_60d_pct: -9.8,
    next_month_follow_through_pct: 31,
    verdict_then: 'Mixed',
  },
  {
    analog_date: '2020-09-04',
    distance: 1.12,
    fwd_midsml400_5d_pct: 1.1,
    fwd_midsml400_20d_pct: 5.6,
    fwd_midsml400_60d_pct: 19.3,
    next_month_follow_through_pct: 57,
    verdict_then: 'Constructive',
  },
  {
    analog_date: '2018-04-13',
    distance: 1.21,
    fwd_midsml400_5d_pct: 0.4,
    fwd_midsml400_20d_pct: -1.2,
    fwd_midsml400_60d_pct: -7.5,
    next_month_follow_through_pct: 38,
    verdict_then: 'Mixed',
  },
  {
    analog_date: '2015-12-18',
    distance: 1.34,
    fwd_midsml400_5d_pct: 1.7,
    fwd_midsml400_20d_pct: -4.1,
    fwd_midsml400_60d_pct: -6.3,
    next_month_follow_through_pct: 29,
    verdict_then: 'Weak',
  },
  {
    analog_date: '2016-07-01',
    distance: 1.46,
    fwd_midsml400_5d_pct: 2.4,
    fwd_midsml400_20d_pct: 4.3,
    fwd_midsml400_60d_pct: 10.8,
    next_month_follow_through_pct: 54,
    verdict_then: 'Constructive',
  },
];

// ------------------------------------------------------------------ big movers

type Tax = [broadSector: string, sector: string, broadIndustry: string, industry: string];
const TAX: Record<string, Tax> = {
  capgoods: ['Industrials', 'Capital Goods', 'Electrical Equipment', 'Heavy Electrical Equipment'],
  defence: ['Industrials', 'Capital Goods', 'Aerospace & Defense', 'Aerospace & Defense'],
  pharma: ['Healthcare', 'Healthcare', 'Pharmaceuticals & Biotechnology', 'Pharmaceuticals'],
  cdmo: ['Healthcare', 'Healthcare', 'Pharmaceuticals & Biotechnology', 'Biotechnology'],
  chem: ['Commodities', 'Chemicals', 'Chemicals & Petrochemicals', 'Specialty Chemicals'],
  auto: ['Consumer Discretionary', 'Automobile and Auto Components', 'Auto Components', 'Auto Components & Equipments'],
  it: ['Information Technology', 'Information Technology', 'IT - Software', 'Computers - Software & Consulting'],
  realty: ['Consumer Discretionary', 'Realty', 'Realty', 'Residential, Commercial Projects'],
  fin: ['Financial Services', 'Financial Services', 'Finance', 'Non Banking Financial Company (NBFC)'],
  power: ['Utilities', 'Power', 'Power', 'Power Generation'],
};

function pathFor(move: number, seed: number): number[] {
  // Close vs T-1 close (%), T-20..T+20: a quiet base, the event jump, then drift.
  const out: number[] = [];
  for (let i = -20; i <= 20; i++) {
    const wobble = Math.sin((i + seed) * 1.7) * 1.2;
    if (i < 0) out.push(Number((wobble - (i < -10 ? 2 : 0)).toFixed(2)));
    else if (i === 0) out.push(Number((move * 0.35).toFixed(2)));
    else out.push(Number((move * (0.35 + 0.65 * Math.min(1, i / 12)) + wobble).toFixed(2)));
  }
  return out;
}

const ev = (
  id: number,
  symbol: string,
  security_name: string,
  event_date: string,
  trigger: string,
  move_pct: number,
  mcap: number,
  catalyst: string,
  tax: keyof typeof TAX,
  verdict_then: string,
  catalyst_detail: string,
): BigMoveRow => {
  const [broad_sector, sector, broad_industry, industry] = TAX[tax];
  return {
    event_id: `BM-${String(id).padStart(5, '0')}`,
    symbol,
    event_date,
    trigger,
    mcap_cr_at_event: mcap,
    move_pct,
    catalyst,
    industry,
    security_name,
    broad_sector,
    sector,
    broad_industry,
    verdict_then,
    catalyst_detail,
    path_pct: pathFor(move_pct, id),
  };
};

export const BIG_MOVE_ROWS: BigMoveRow[] = [
  ev(
    1,
    'APARINDS',
    'Apar Industries',
    '2026-09-18',
    'up30_20d',
    34.6,
    28450,
    'results',
    'capgoods',
    'Constructive',
    'Q1 results on 16-Sep (+2 sessions)',
  ),
  ev(
    2,
    'DATAPATTNS',
    'Data Patterns (India)',
    '2026-09-15',
    'upper_circuit',
    20.0,
    14320,
    'deal',
    'defence',
    'Constructive',
    'Block buy by a domestic MF on 12-Sep',
  ),
  ev(
    3,
    'SHILPAMED',
    'Shilpa Medicare',
    '2026-09-11',
    'up30_20d',
    38.2,
    6120,
    'unexplained',
    'pharma',
    'Mixed',
    'No result, deal or group move in window',
  ),
  ev(
    4,
    'TRITURBINE',
    'Triveni Turbine',
    '2026-09-09',
    'up30_20d',
    31.4,
    21880,
    'sector',
    'capgoods',
    'Mixed',
    '58% of Heavy Electrical Equipment moved in window',
  ),
  ev(5, 'BEML', 'BEML', '2026-09-04', 'up50_60d', 57.9, 18950, 'sector', 'defence', 'Mixed', '64% of Aerospace & Defense moved in window'),
  ev(
    6,
    'NEULANDLAB',
    'Neuland Laboratories',
    '2026-08-28',
    'up50_60d',
    62.3,
    17410,
    'results',
    'cdmo',
    'Mixed',
    'Q1 results on 26-Aug (+2 sessions)',
  ),
  ev(
    7,
    'CLEAN',
    'Clean Science and Technology',
    '2026-08-26',
    'upper_circuit',
    10.0,
    15720,
    'corporate_action',
    'chem',
    'Weak',
    'Buyback record date 27-Aug',
  ),
  ev(
    8,
    'SONACOMS',
    'Sona BLW Precision Forgings',
    '2026-08-21',
    'up30_20d',
    30.8,
    41200,
    'results',
    'auto',
    'Weak',
    'Q1 results on 19-Aug (+2 sessions)',
  ),
  ev(9, 'KPITTECH', 'KPIT Technologies', '2026-08-14', 'up30_20d', 32.1, 44830, 'deal', 'it', 'Weak', 'Bulk buy by an FPI on 13-Aug'),
  ev(
    10,
    'SOBHA',
    'Sobha',
    '2026-08-07',
    'up30_20d',
    36.5,
    13880,
    'unexplained',
    'realty',
    'Weak',
    'No result, deal or group move in window',
  ),
  ev(
    11,
    'POONAWALLA',
    'Poonawalla Fincorp',
    '2026-07-31',
    'up30_20d',
    30.3,
    27640,
    'results',
    'fin',
    'Mixed',
    'Q1 results on 29-Jul (+2 sessions)',
  ),
  ev(
    12,
    'JPPOWER',
    'Jaiprakash Power Ventures',
    '2026-07-24',
    'upper_circuit',
    20.0,
    12310,
    'unexplained',
    'power',
    'Mixed',
    'No result, deal or group move in window',
  ),
  ev(
    13,
    'GRSE',
    'Garden Reach Shipbuilders',
    '2026-07-17',
    'up50_60d',
    71.4,
    24160,
    'sector',
    'defence',
    'Constructive',
    '71% of Aerospace & Defense moved in window',
  ),
  ev(
    14,
    'SUVENPHAR',
    'Suven Pharmaceuticals',
    '2026-07-10',
    'up30_20d',
    33.7,
    22950,
    'deal',
    'cdmo',
    'Constructive',
    'Block buy by a PE fund on 09-Jul',
  ),
  ev(
    15,
    'CGPOWER',
    'CG Power and Industrial Solutions',
    '2026-07-03',
    'up30_20d',
    30.9,
    98420,
    'sector',
    'capgoods',
    'Constructive',
    '55% of Heavy Electrical Equipment moved in window',
  ),
  ev(
    16,
    'NAVINFLUOR',
    'Navin Fluorine International',
    '2026-06-26',
    'up30_20d',
    31.2,
    19760,
    'results',
    'chem',
    'Favourable',
    'Q4 results on 24-Jun (+2 sessions)',
  ),
  ev(
    17,
    'ZENTEC',
    'Zen Technologies',
    '2026-06-19',
    'upper_circuit',
    5.0,
    11240,
    'unexplained',
    'defence',
    'Favourable',
    'No result, deal or group move in window',
  ),
  ev(18, 'CYIENT', 'Cyient', '2026-06-12', 'up30_20d', 30.4, 21470, 'results', 'it', 'Favourable', 'Q4 results on 10-Jun (+2 sessions)'),
];

export const LIFT_ROWS = [
  {
    feature: 'rs_percentile',
    bucket: '≥ 85 at T-1',
    lift: 2.4,
    precision_20d: 7.9,
    n_movers: 412,
    n_controls: 4120,
    oos: true,
    metric_key: 'rs_percentile',
  },
  {
    feature: 'range_contraction',
    bucket: '20d range in lowest 20% of 1y',
    lift: 1.9,
    precision_20d: 6.3,
    n_movers: 355,
    n_controls: 3550,
    oos: true,
    metric_key: null,
  },
  {
    feature: 'volume_dry_up',
    bucket: 'VDU then RVOL ≥ 1.5',
    lift: 1.7,
    precision_20d: 5.6,
    n_movers: 298,
    n_controls: 2980,
    oos: true,
    metric_key: 'vdu_ratio',
  },
  {
    feature: 'delivery_trend',
    bucket: 'Delivery % rising 10d',
    lift: 1.4,
    precision_20d: 4.6,
    n_movers: 377,
    n_controls: 3770,
    oos: true,
    metric_key: 'deliv_pct_x',
  },
  {
    feature: 'away_52w_high_pct',
    bucket: 'Within 10% of 52W high',
    lift: 1.6,
    precision_20d: 5.3,
    n_movers: 486,
    n_controls: 4860,
    oos: true,
    metric_key: 'away_52w_high_pct',
  },
  {
    feature: 'group_quadrant',
    bucket: 'Industry Leading',
    lift: 1.3,
    precision_20d: 4.3,
    n_movers: 264,
    n_controls: 2640,
    oos: false,
    metric_key: 'rrg_quadrant',
  },
  {
    feature: 'deal_buy_10s',
    bucket: 'Institutional buy deal in 10 sessions',
    lift: 1.8,
    precision_20d: 5.9,
    n_movers: 22,
    n_controls: 220,
    oos: true,
    metric_key: null,
  },
];

const OFFSETS = [-60, -40, -20, -10, -5, -1, 0, 5, 10, 20];
export const FEATURE_PATH_ROWS = OFFSETS.flatMap((o) => [
  {
    feature: 'rs_percentile',
    offset: o,
    movers: Math.round(62 + (o + 60) * (o <= 0 ? 0.4 : 0.1)),
    controls: 58,
    n_movers: 540,
    n_controls: 5400,
  },
  {
    feature: 'rvol',
    offset: o,
    movers: Number((o < -10 ? 0.8 : o < 0 ? 0.7 : o === 0 ? 3.4 : 1.6).toFixed(2)),
    controls: 1.0,
    n_movers: 540,
    n_controls: 5400,
  },
]);

function featuresFor(row: BigMoveRow): Record<string, unknown>[] {
  const seed = Number(String(row.event_id).slice(-2));
  const feats: { feature: string; metric_key: string | null; base: number; ctrl: number; step: number }[] = [
    { feature: 'rs_percentile', metric_key: 'rs_percentile', base: 70 + (seed % 9), ctrl: 61, step: 4 },
    { feature: 'rs_delta_5', metric_key: 'rs_delta_5', base: 3 + (seed % 4), ctrl: 0, step: 1 },
    { feature: 'base_length_sessions', metric_key: null, base: 38 + seed, ctrl: 22, step: 0 },
    { feature: 'base_depth_pct', metric_key: null, base: 18 - (seed % 5), ctrl: 24, step: 0 },
    { feature: 'range_contraction_pct', metric_key: null, base: 42, ctrl: 61, step: -6 },
    { feature: 'rvol', metric_key: 'rvol', base: 0.7, ctrl: 1.0, step: 0.2 },
    { feature: 'deliv_pct_x', metric_key: 'deliv_pct_x', base: 4 + (seed % 3), ctrl: 0.5, step: 2 },
    { feature: 'away_52w_high_pct', metric_key: 'away_52w_high_pct', base: -14, ctrl: -22, step: 3 },
  ];
  return feats.flatMap((f) =>
    [-60, -20, -5, -1].map((offset, i) => ({
      feature: f.feature,
      metric_key: f.metric_key,
      offset,
      mover_value: Number((f.base + f.step * i).toFixed(2)),
      control_median: f.ctrl,
      n_controls: 10,
      percentile_vs_controls: Math.min(99, 55 + i * 10 + (seed % 7)),
    })),
  );
}

// ------------------------------------------------------------------ pre-move watch

export const PRE_MOVE_ROWS: PreMoveRow[] = [
  {
    symbol: 'JYOTICNC',
    trade_date: AS_OF,
    matched_traits: ['RS ≥ 85', 'Range contraction', 'VDU then RVOL ≥ 1.5', 'Industry Leading'],
    precision_20d: 9.4,
    base_rate_20d: 3.3,
    n: 212,
    security_name: 'Jyoti CNC Automation',
    industry: 'Industrial Machinery',
  },
  {
    symbol: 'AZAD',
    trade_date: AS_OF,
    matched_traits: ['RS ≥ 85', 'Within 10% of 52W high', 'Delivery rising'],
    precision_20d: 7.1,
    base_rate_20d: 3.3,
    n: 486,
    security_name: 'Azad Engineering',
    industry: 'Aerospace & Defense',
  },
  {
    symbol: 'ANANTRAJ',
    trade_date: AS_OF,
    matched_traits: ['Range contraction', 'Delivery rising', 'Institutional buy deal'],
    precision_20d: 8.6,
    base_rate_20d: 3.3,
    n: 22,
    security_name: 'Anant Raj',
    industry: 'Residential, Commercial Projects',
  },
  {
    symbol: 'KAYNES',
    trade_date: AS_OF,
    matched_traits: ['RS ≥ 85', 'Range contraction'],
    precision_20d: 6.2,
    base_rate_20d: 3.3,
    n: 355,
    security_name: 'Kaynes Technology India',
    industry: 'Industrial Products',
  },
  {
    symbol: 'TDPOWERSYS',
    trade_date: AS_OF,
    matched_traits: ['Within 10% of 52W high', 'Industry Leading'],
    precision_20d: 4.4,
    base_rate_20d: 3.3,
    n: 264,
    security_name: 'TD Power Systems',
    industry: 'Heavy Electrical Equipment',
  },
  {
    symbol: 'PGEL',
    trade_date: AS_OF,
    matched_traits: ['VDU then RVOL ≥ 1.5'],
    precision_20d: 5.6,
    base_rate_20d: 3.3,
    n: 298,
    security_name: 'PG Electroplast',
    industry: 'Consumer Electronics',
  },
  {
    symbol: 'SAILIFE',
    trade_date: AS_OF,
    matched_traits: ['RS ≥ 85', 'Delivery rising'],
    precision_20d: null,
    base_rate_20d: 3.3,
    n: 8,
    security_name: 'Sai Life Sciences',
    industry: 'Biotechnology',
  },
];

// ------------------------------------------------------------------ setup evidence

const EVIDENCE: Record<string, Record<string, [n: number, hit: number, avg: number, med: number, mae: number, mfe: number]>> = {
  darvas_squeeze: {
    Favourable: [212, 41.5, 0.92, 0.6, -4.1, 12.8],
    Constructive: [388, 36.1, 0.64, 0.4, -4.6, 10.9],
    Mixed: [301, 27.9, 0.21, -0.1, -5.3, 8.2],
    Weak: [96, 18.8, -0.34, -1.0, -6.2, 5.1],
    Danger: [17, 11.8, -0.61, -1.0, -7.4, 3.9],
  },
  darvas_10ema: {
    Favourable: [168, 38.7, 0.71, 0.5, -3.8, 10.4],
    Constructive: [297, 33.3, 0.52, 0.3, -4.2, 9.3],
    Mixed: [241, 25.3, 0.09, -0.2, -4.9, 7.0],
    Weak: [58, 15.5, -0.41, -1.0, -5.8, 4.4],
    Danger: [9, 11.1, -0.72, -1.0, -6.9, 3.2],
  },
  vcp: {
    Favourable: [74, 44.6, 1.08, 0.8, -3.9, 14.1],
    Constructive: [131, 39.7, 0.81, 0.5, -4.3, 12.2],
    Mixed: [88, 29.5, 0.27, 0.0, -5.0, 8.8],
    Weak: [26, 19.2, -0.22, -0.9, -5.7, 5.6],
    Danger: [4, 0, -1.0, -1.0, -7.0, 2.0],
  },
};

const QUADRANT_SPLIT: Record<string, number> = { Leading: 0.42, Improving: 0.24, Weakening: 0.2, Lagging: 0.14 };
const QUADRANT_EDGE: Record<string, number> = { Leading: 1.25, Improving: 1.05, Weakening: 0.8, Lagging: 0.5 };

function evidenceRow(bucket: string, n: number, hit: number, avg: number, med: number, mae: number, mfe: number): EvidenceRow {
  const ok = n >= 30;
  return {
    bucket,
    n,
    insufficient_sample: !ok,
    label: ok ? null : 'insufficient sample',
    hit_rate_2r: ok ? hit : null,
    avg_r: ok ? avg : null,
    median_r: ok ? med : null,
    mae_pct: ok ? mae : null,
    mfe_pct: ok ? mfe : null,
  };
}

export function evidenceRows(setup: string, by: string): EvidenceRow[] | null {
  const table = EVIDENCE[setup];
  if (!table) return null;
  const buckets = Object.entries(table);
  const allN = buckets.reduce((s, [, v]) => s + v[0], 0);
  const w = (i: number) => buckets.reduce((s, [, v]) => s + v[i] * v[0], 0) / allN;
  const all = evidenceRow(
    'all',
    allN,
    Number(w(1).toFixed(1)),
    Number(w(2).toFixed(2)),
    Number(w(3).toFixed(2)),
    Number(w(4).toFixed(2)),
    Number(w(5).toFixed(2)),
  );
  if (by === 'all') return [all];
  if (by === 'quadrant') {
    return [
      all,
      ...Object.entries(QUADRANT_SPLIT).map(([q, share]) => {
        const e = QUADRANT_EDGE[q];
        return evidenceRow(
          q,
          Math.round(allN * share),
          Number((w(1) * e).toFixed(1)),
          Number((w(2) * e - (1 - e) * 0.4).toFixed(2)),
          Number((w(3) * e).toFixed(2)),
          Number(w(4).toFixed(2)),
          Number((w(5) * e).toFixed(2)),
        );
      }),
    ];
  }
  return [all, ...buckets.map(([b, v]) => evidenceRow(b, ...v))];
}

// ------------------------------------------------------------------ stock analogs

export function stockAnalogRows(sym: string): StockAnalogRow[] {
  const peers = ['HAL', 'BEL', 'CUMMINSIND', 'POLYCAB', 'DIXON', 'PERSISTENT', 'TRENT', 'ABB', 'SIEMENS', 'KEI'];
  const outcomes: [number, boolean, number][] = [
    [2.4, true, 14],
    [-1.0, false, 4],
    [1.1, false, 20],
    [3.2, true, 18],
    [-1.0, false, 6],
    [2.1, true, 11],
    [0.4, false, 20],
    [-0.6, false, 9],
    [2.8, true, 16],
    [-1.0, false, 3],
  ];
  return peers.map((p, i) => ({
    trade_date: `202${3 + (i % 3)}-0${1 + (i % 9)}-1${i % 9}`,
    symbol: p === sym ? 'LT' : p,
    queue: 'vcp',
    distance: Number((0.55 + i * 0.13).toFixed(2)),
    features: { base_depth_pct: 12 + i, rs_percentile: 88 - i, rvol: Number((1.8 - i * 0.07).toFixed(2)) },
    r_multiple: outcomes[i][0],
    hit_2r: outcomes[i][1],
    days_held: outcomes[i][2],
  }));
}

// ------------------------------------------------------------------ router

export interface FixtureRequest {
  endpoint: string;
  params?: Record<string, string>;
  query?: Record<string, unknown>;
  asOf: string | null;
}

/** Fixture envelope for a Research endpoint (as_of bounds dated rows: no look-ahead). */
export function fixtureFor({ endpoint, params, query, asOf }: FixtureRequest) {
  const cutoff = asOf ?? AS_OF;
  switch (endpoint) {
    case 'research/analogs':
      return fixtureEnvelope(ANALOG_ROWS, { k: 10, agreement: null, excluded_recent_sessions: 60 }, asOf, {
        metric_keys: ['analog_distance', 'forward_return_20d'],
      });
    case 'research/big-moves': {
      const min = typeof query?.min_mcap_cr === 'number' ? query.min_mcap_cr : 1000;
      const rows = BIG_MOVE_ROWS.filter((r) => (r.event_date ?? '') <= cutoff && (r.mcap_cr_at_event ?? 0) >= min);
      return fixtureEnvelope(rows, { min_mcap_cr: min, lift: LIFT_ROWS, feature_path: FEATURE_PATH_ROWS, base_rate_20d: 3.3 }, asOf, {
        metric_keys: ['precision_20d', 'lift'],
      });
    }
    case 'research/big-moves/{event_id}': {
      const row = BIG_MOVE_ROWS.find((r) => r.event_id === params?.event_id && (r.event_date ?? '') <= cutoff);
      if (!row)
        return fixtureEnvelope([], {}, asOf, {
          status: 'unavailable',
          reason: `no big-move event '${params?.event_id}' on or before as_of`,
        });
      return fixtureEnvelope([row], { event_id: row.event_id, features: featuresFor(row) }, asOf);
    }
    case 'research/pre-move':
      return fixtureEnvelope(PRE_MOVE_ROWS, { label: 'research', base_rate: 3.3 }, asOf, {
        notes: ['Research list: precision is printed per row; not a trade signal until it beats the base rate out of sample.'],
        metric_keys: ['precision_20d', 'lift'],
      });
    case 'evidence/{setup}': {
      const setup = params?.setup ?? '';
      const by = typeof query?.by === 'string' ? query.by : 'environment';
      const rows = evidenceRows(setup, by);
      if (!rows)
        return fixtureEnvelope([], { setup, by, min_sample: 30 }, asOf, {
          status: 'unavailable',
          reason: `no fixture outcomes for ${setup}`,
        });
      return fixtureEnvelope(rows, { setup, by, min_sample: 30 }, asOf);
    }
    case 'stock/{sym}/analogs':
      return fixtureEnvelope(stockAnalogRows(params?.sym ?? ''), {}, asOf);
    default:
      return fixtureEnvelope([], {}, asOf, { status: 'unavailable', reason: `no fixture for ${endpoint}` });
  }
}
