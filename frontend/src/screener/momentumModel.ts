/**
 * Momentum scanner model (Screener → Momentum): URL state, the query sent to
 * /api/v2/screener/momentum, the old workspace's preset buttons (same
 * semantics: they set some filters and leave the rest), and the TradingView /
 * Charts helpers. Pure — no React.
 *
 * Defaults are exactly the old MomentumWorkspace defaults: lookback 20D,
 * min mcap 1000 Cr, day-volume gate 10L (1M), within 25% of the 52W high,
 * ≥ 50% above the 52W low, CMP > 10 EMA, CMP > 200 EMA, EMA stack on.
 */
import { formatTradingViewList } from '../lib/tradingview';

export const LOOKBACKS = [1, 3, 5, 10, 20, 30] as const;
export const VOLUME_PRESETS = [
  { label: '5L', value: 500_000 },
  { label: '10L (1M)', value: 1_000_000 },
  { label: '25L', value: 2_500_000 },
  { label: '50L', value: 5_000_000 },
] as const;
export const BUCKETS = ['0_2%', '2_5%', '5_10%', '10%+', 'Below 10EMA'] as const;
export type Bucket = (typeof BUCKETS)[number];

/** Toggle flags held in the `mf` URL param (comma list). */
export const FLAGS = {
  c10: 'CMP > 10 EMA',
  c200: 'CMP > 200 EMA',
  o10: 'OHLC > 10 EMA',
  o20: 'OHLC > 20 EMA',
  ema: 'EMA stack (10>20>50>100>200)',
  sma: 'SMA template (50>150>200)',
  dt: 'Delivery thrust',
  nr7: 'NR7 / Inside bar',
  rsi: 'Weekly RSI ≥ 60',
} as const;
export type Flag = keyof typeof FLAGS;

export const MOMENTUM_DEFAULTS = {
  mlb: '20',
  mmcap: '1000',
  /** Volume gate: day | avg20d | off (mutually exclusive, as before). */
  mvg: 'day',
  mvol: '1000000',
  mhigh: '25',
  mlow: '50',
  mf: 'c10,c200,ema',
  /** Quick filters on the loaded list (sector / industry chips). */
  msec: '',
  mind: '',
  /** Group rows by coil bucket (1) or a flat list (0). */
  mgrp: '1',
  /** Filter panel shown (1) / hidden (0). */
  mpanel: '1',
};
export type MomentumState = typeof MOMENTUM_DEFAULTS;
export type MomentumPatch = Partial<Record<keyof MomentumState, string | null>>;

export function parseFlags(raw: string): Set<Flag> {
  const out = new Set<Flag>();
  for (const f of raw.split(',')) {
    const k = f.trim();
    if (k in FLAGS) out.add(k as Flag);
  }
  return out;
}

export function encodeFlags(flags: ReadonlySet<Flag>): string {
  return (Object.keys(FLAGS) as Flag[]).filter((f) => flags.has(f)).join(',');
}

/** Toggle one flag; EMA stack and SMA template exclude each other (old behaviour). */
export function toggleFlag(raw: string, flag: Flag, on: boolean): string {
  const flags = parseFlags(raw);
  if (on) {
    flags.add(flag);
    if (flag === 'ema') flags.delete('sma');
    if (flag === 'sma') flags.delete('ema');
  } else flags.delete(flag);
  return encodeFlags(flags);
}

function num(s: string, fallback: number): number {
  const n = Number(s);
  return s.trim() !== '' && Number.isFinite(n) && n >= 0 ? n : fallback;
}

export function lookback(s: MomentumState): number {
  const n = Math.round(num(s.mlb, 20));
  return Math.min(90, Math.max(1, n));
}

export type VolumeMode = 'day' | 'avg20d' | 'off';
export function volumeMode(s: MomentumState): VolumeMode {
  return s.mvg === 'avg20d' || s.mvg === 'off' ? s.mvg : 'day';
}

/** Query for /api/v2/screener/momentum — the same parameters the old UI sent. */
export function momentumQuery(s: MomentumState, debugSymbol?: string | null) {
  const f = parseFlags(s.mf);
  const mode = volumeMode(s);
  const vol = num(s.mvol, 1_000_000);
  const ema = f.has('ema');
  const sma = f.has('sma');
  return {
    lookback_days: lookback(s),
    min_mcap_cr: num(s.mmcap, 0),
    min_volume: mode === 'day' ? vol : 0,
    min_avg_volume_20d: mode === 'avg20d' ? vol : 0,
    max_52w_away_pct: num(s.mhigh, 99),
    min_52w_low_pct: num(s.mlow, 0),
    cmp_gt_10: f.has('c10'),
    cmp_gt_200: f.has('c200'),
    ohlc_gt_10: f.has('o10'),
    ohlc_gt_20: f.has('o20'),
    ema10_gt_20: ema,
    ema20_gt_50: ema,
    ema50_gt_100: ema,
    ema100_gt_200: ema,
    sma50_gt_150: sma,
    sma150_gt_200: sma,
    sma_cmp_gt_50: sma,
    sma_cmp_gt_150_200: sma,
    sma200_rising: sma,
    delivery_thrust: f.has('dt'),
    coiling_nr7: f.has('nr7'),
    weekly_rsi_60: f.has('rsi'),
    ...(debugSymbol ? { debug_symbol: debugSymbol } : {}),
    limit: 5000,
  };
}

export function isDefaultState(s: MomentumState): boolean {
  return (['mlb', 'mmcap', 'mvg', 'mvol', 'mhigh', 'mlow', 'mf'] as const).every((k) => s[k] === MOMENTUM_DEFAULTS[k]);
}

// ------------------------------------------------------------------ preset buttons (old applyPreset)

export const PRESETS = [
  { id: 'stage2', label: 'Stage 2 Template' },
  { id: 'sma_template', label: 'SMA Template' },
  { id: 'breakouts', label: 'Near 52W High (≤5%)' },
  { id: 'delivery', label: 'Delivery Thrust' },
  { id: 'coiling', label: 'NR7 Coiling' },
  { id: 'mtf', label: 'Weekly RSI ≥ 60' },
] as const;
export type PresetId = (typeof PRESETS)[number]['id'] | 'clear' | 'defaults';

/** Patch for a preset button: same fields as the old workspace; untouched filters keep their values. */
export function presetPatch(s: MomentumState, id: PresetId): MomentumPatch {
  const f = parseFlags(s.mf);
  const set = (on: Flag[], off: Flag[] = []) => {
    for (const x of on) f.add(x);
    for (const x of off) f.delete(x);
    return encodeFlags(f);
  };
  switch (id) {
    case 'stage2':
      return { mf: set(['c200', 'c10', 'ema'], ['sma', 'dt', 'nr7']), mhigh: '25', mlow: '50', mmcap: '1000' };
    case 'breakouts':
      return { mf: set(['c10', 'c200'], ['ema']), mhigh: '5', mlow: '50', mmcap: '1000' };
    case 'sma_template':
      return { mf: set(['sma'], ['ema']), mhigh: '25', mlow: '50', mmcap: '1000' };
    case 'delivery':
      return { mf: set(['dt', 'c200']), mmcap: '1000' };
    case 'coiling':
      return { mf: set(['nr7']), mhigh: '15', mlow: '50', mmcap: '1000' };
    case 'mtf':
      return { mf: set(['rsi', 'c10', 'c200']), mmcap: '1000' };
    case 'clear':
      return { mf: '', mhigh: '99', mlow: '0', mmcap: '0', mvg: 'off' };
    case 'defaults':
      return { mlb: null, mmcap: null, mvg: null, mvol: null, mhigh: null, mlow: null, mf: null, msec: null, mind: null };
  }
}

// ------------------------------------------------------------------ server context (meta.context)

export interface GroupCtx {
  id: string;
  group_name?: string | null;
  level: string;
  stocks?: number | null;
  thin: boolean;
  health?: number | null;
  health_zone?: 'Healthy' | 'Mixed' | 'Weak' | null;
  health_rank?: number | null;
  rrg_quadrant?: string | null;
  quadrant_note?: string | null;
  abs_trend?: string | null;
  return_ew_21d?: number | null;
  health_spark_21?: (number | null)[] | null;
}

export interface Leader {
  sector: string;
  industry?: string;
  stock_count: number;
  avg_rs: number | null;
  symbols: string[];
  tv_str: string;
  new_count: number;
  group: GroupCtx | null;
}

export interface BucketSummary {
  bucket: Bucket;
  count: number;
  symbols: string[];
  tv_str: string;
  new_count: number;
}

export interface DebugCheck {
  stage: 'trigger' | 'current';
  label: string;
  passed: boolean;
  detail: string | null;
}

export interface MomentumContext {
  is_default?: boolean;
  buckets?: BucketSummary[];
  buckets_tv?: string;
  top_sectors?: Leader[];
  top_industries?: Leader[];
  sector_distribution?: Leader[];
  industry_distribution?: Leader[];
  previous_session?: string | null;
  new_count?: number;
  dropped?: { symbol: string | null; bucket: string | null; industry: string | null; close: number | null; rs_percentile: number | null }[];
  debug?: { symbol: string; checks: DebugCheck[]; in_list: boolean } | null;
}

// ------------------------------------------------------------------ TradingView / Charts

/** Several TV strings ("NSE:A,NSE:B") joined — the old "Copy Top Sectors / Industries". */
export function joinTv(parts: readonly (string | null | undefined)[]): string {
  return parts.filter((p): p is string => !!p).join(',');
}

/** "###0_2%,NSE:A,NSE:B,###2_5%,…" from rows (fallback when the server string is absent). */
export function bucketsTvFromRows(rows: readonly { symbol?: string | null; bucket?: string | null }[]): string {
  return formatTradingViewList(
    BUCKETS.slice(0, 4).map((b) => ({ title: b, symbols: rows.filter((r) => r.bucket === b).map((r) => r.symbol) })),
  ).text;
}

/** Charts deep link for one bucket: /charts?source=momentum:<bucket>&syms=…(&as_of). */
export function bucketChartsHref(bucket: string, symbols: readonly (string | null | undefined)[], asOf: string | null): string {
  const p = new URLSearchParams();
  p.set('source', `momentum:${bucket}`);
  const syms = symbols.filter((s): s is string => !!s).slice(0, 200);
  if (syms.length) p.set('syms', syms.join(','));
  if (asOf) p.set('as_of', asOf);
  return `/charts?${p.toString()}`;
}

/** Tone for the coil distance chip (old colours: 0-2 green, 2-5 blue, 5-10 grey, >10 red). */
export function coilTone(bucket: string | null | undefined): 'positive' | 'info' | 'neutral' | 'negative' {
  switch (bucket) {
    case '0_2%':
      return 'positive';
    case '2_5%':
      return 'info';
    case '5_10%':
      return 'neutral';
    default:
      return 'negative';
  }
}

export const BUCKET_LABEL: Record<Bucket, string> = {
  '0_2%': '0–2% above 10 EMA',
  '2_5%': '2–5% above 10 EMA',
  '5_10%': '5–10% above 10 EMA',
  '10%+': 'More than 10% above 10 EMA',
  'Below 10EMA': 'Below the 10 EMA',
};
