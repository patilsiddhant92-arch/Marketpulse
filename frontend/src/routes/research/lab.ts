/**
 * Research lab model (HarkPro/10-tab-research.md §§3-13): typed readers over the
 * /api/v2/research/{regime, days-like-today, scorecard, case-study, before-moves,
 * index-study} envelopes. Rows are typed from the generated OpenAPI schema; the
 * study context lives in meta.context and is read here with explicit shapes.
 * Pure functions only (unit-tested in lab.test.ts).
 */
import type { components } from '../../api/types.gen';
import type { EnvelopeMeta } from '../../api/types';
import { isNum } from '../../lib/fmt';

type S = components['schemas'];
export type RegimeDayRow = S['RegimeDayRow'];
export type AnalogDayRow = S['AnalogDayRow'];
export type ScorecardRow = S['ScorecardRow'];
export type CaseMoverRow = S['CaseMoverRow'];
export type CaseBarRow = S['CaseBarRow'];
export type EarlyLiftRow = S['EarlyLiftRow'];
export type DrawdownRow = S['DrawdownRow'];

export const CAVEAT_FALLBACK =
  'Retrospective research, not advice. These studies use the local archive (about two years). Re-run them on the 5-year archive before you trust a threshold.';

export type QuadrantKey = 'press' | 'narrow' | 'picker' | 'chop';
export const QUADRANT_ORDER: readonly QuadrantKey[] = ['press', 'narrow', 'picker', 'chop'];
export const QUADRANT_LABEL: Record<QuadrantKey, string> = {
  press: 'Press',
  narrow: 'Narrow',
  picker: "Stock-picker's",
  chop: 'Chop',
};
/** Tailwind token classes per quadrant (fill for SVG, bg/text for chips). */
export const QUADRANT_TONE: Record<QuadrantKey, { fill: string; chip: 'positive' | 'info' | 'warn' | 'negative' }> = {
  press: { fill: 'fill-up', chip: 'positive' },
  narrow: { fill: 'fill-info', chip: 'info' },
  picker: { fill: 'fill-warn', chip: 'warn' },
  chop: { fill: 'fill-down', chip: 'negative' },
};

export function isQuadrant(v: unknown): v is QuadrantKey {
  return typeof v === 'string' && (QUADRANT_ORDER as readonly string[]).includes(v);
}

export function context<T>(meta: EnvelopeMeta | undefined | null): Partial<T> {
  const c = meta?.context;
  return (c && typeof c === 'object' ? c : {}) as Partial<T>;
}

export function caveatOf(meta: EnvelopeMeta | undefined | null): string {
  const c = (meta?.context as Record<string, unknown> | undefined)?.caveat;
  return typeof c === 'string' && c ? c : CAVEAT_FALLBACK;
}

// ------------------------------------------------------------------ regime

export interface QuadrantRecord {
  quadrant: QuadrantKey | 'all';
  label: string;
  axes: string | null;
  advice: string | null;
  days: number;
  days_graded: number;
  next10_ft_pct: number | null;
  ew_fwd20_pct: number | null;
  ew_fwd20_up_pct: number | null;
}

export interface Episode {
  quadrant: QuadrantKey;
  start: string;
  end: string;
  sessions: number;
  ew_move_pct: number | null;
  next_quadrant: QuadrantKey | null;
  ew_next20_pct: number | null;
  open: boolean;
}

export interface RegimeContext {
  caveat: string;
  study_end: string;
  dropped_sessions: string[];
  today: {
    trade_date: string;
    quadrant: QuadrantKey | null;
    label: string | null;
    advice: string | null;
    index_axis: string | null;
    breakout_axis: string | null;
    chop: number | null;
    er: number | null;
    adx: number | null;
    ft_pct: number | null;
    ft_n: number | null;
    chop_pctile: number | null;
    er_pctile: number | null;
    ft_pctile: number | null;
    drawdown_pct: number | null;
    sessions_in_phase: number;
    phase_start: string | null;
  };
  record: QuadrantRecord[];
  duration: {
    quadrant: QuadrantKey;
    past_episodes: number;
    episodes_3plus: number;
    median_sessions: number | null;
    min_sessions: number | null;
    max_sessions: number | null;
    exits: { to: QuadrantKey; label: string; n: number }[];
  };
  episodes: Episode[];
  summary: string[];
  definition: string;
  sample: { from: string; to: string; sessions: number; classified: number };
}

/** Runs of one quadrant for the ribbon: [startIndex, endIndex, quadrant]. */
export function ribbonRuns(rows: readonly { quadrant?: string | null }[]): { from: number; to: number; q: QuadrantKey | null }[] {
  const out: { from: number; to: number; q: QuadrantKey | null }[] = [];
  rows.forEach((r, i) => {
    const q = isQuadrant(r.quadrant) ? r.quadrant : null;
    const last = out[out.length - 1];
    if (last && last.q === q) last.to = i;
    else out.push({ from: i, to: i, q });
  });
  return out;
}

export interface AnalogHorizon {
  horizon: number;
  n: number;
  median: number | null;
  mean: number | null;
  min: number | null;
  max: number | null;
  up_pct: number | null;
  base_median: number | null;
  base_up_pct: number | null;
  base_n: number;
}

export interface AnalogContext {
  caveat: string;
  study_end: string;
  k: number;
  features: { key: string; label: string; today: number | null }[];
  horizons: AnalogHorizon[];
  summary: string[];
  method: string;
}

/** Edge of the analog median over the all-days median, in points (null when either is missing). */
export function analogEdge(h: AnalogHorizon): number | null {
  return isNum(h.median) && isNum(h.base_median) ? h.median - h.base_median : null;
}

// ------------------------------------------------------------------ scorecard / case study

export interface PrecisionRow {
  preset_id: string;
  preset: string;
  letter: string | null;
  fires: number;
  hit_pct: number | null;
  fires_rs80: number | null;
  hit_rs80_pct: number | null;
}

export interface PrecisionContext {
  base_hit_pct: number | null;
  base_n: number | null;
  window_from: string | null;
  window_to: string | null;
  rows: PrecisionRow[];
  definition: string;
}

export interface ScorecardContext {
  caveat: string;
  study_end: string;
  window_from: string;
  window_to: string;
  movers: number;
  precision: PrecisionContext;
  ladder: { median_pct: number | null; median_move_pct: number | null; median_trades: number | null };
  summary: string[];
  definition: string;
}

export interface FirstFire {
  preset_id: string;
  preset: string;
  letter: string;
  early: boolean;
  first_fire: string | null;
  entry: number | null;
  entry_vs_low_pct: number | null;
  to_peak_pct: number | null;
  trail20_pct: number | null;
  trail20_exit: string | null;
  trail20_open: boolean | null;
  fresh_fires: number;
}

export interface LadderLeg {
  entry_date: string;
  signal_id: string;
  signal: string;
  letter: string;
  entry: number;
  exit_date: string;
  exit: number;
  pnl_pct: number;
  open: boolean;
}

export interface Fire {
  date: string;
  preset_id: string;
  preset: string;
  letter: string;
  close: number;
  in_move: boolean;
}

export interface CaseContext {
  caveat: string;
  study_end: string;
  window_from: string;
  window_to: string;
  symbol: string;
  security_name: string | null;
  industry: string | null;
  mcap_cr: number | null;
  below_floor: boolean;
  move: { low_date: string; low: number; peak_date: string; peak: number; gain_pct: number; sessions: number };
  big_mover: boolean;
  first_fires: FirstFire[];
  ladder: { legs: LadderLeg[]; compounded_pct: number; trades: number; entry_presets: string[]; rule: string };
  fires: Fire[];
  presets: { id: string; name: string; letter: string; category: string | null; early: boolean; description: string }[];
  precision: PrecisionContext;
  summary: string[];
}

/** Fires grouped per date (one marker per session, letters joined: "DC"). */
export function fireMarkers(fires: readonly Fire[], onlyInMove: boolean, hidden: ReadonlySet<string> = new Set()) {
  const by = new Map<string, { time: string; letters: string[]; inMove: boolean }>();
  for (const f of fires) {
    if (onlyInMove && !f.in_move) continue;
    if (hidden.has(f.preset_id)) continue;
    const m = by.get(f.date) ?? { time: f.date, letters: [], inMove: f.in_move };
    if (!m.letters.includes(f.letter)) m.letters.push(f.letter);
    by.set(f.date, m);
  }
  return [...by.values()].sort((a, b) => a.time.localeCompare(b.time)).map((m) => ({ ...m, text: m.letters.join('') }));
}

/** Compounded return of ladder legs in % (0 when none). */
export function compound(legs: readonly { pnl_pct: number }[]): number {
  return legs.length ? (legs.reduce((acc, l) => acc * (1 + l.pnl_pct / 100), 1) - 1) * 100 : 0;
}

/** Precision of one preset vs the base rate, or null. */
export function precisionLift(row: { hit_pct: number | null }, base: number | null): number | null {
  return isNum(row.hit_pct) && isNum(base) && base > 0 ? row.hit_pct / base : null;
}

// ------------------------------------------------------------------ before the big moves

export type Family = 'trend' | 'turnaround';

export interface TraitProfile {
  trait: string;
  label: string;
  group: string;
  n: number;
  runner_median: number | null;
  fizzle_median: number | null;
  low_third_pct: number;
  high_third_pct: number;
  better_when: 'high' | 'low';
  lift: number;
  cut_low: number | null;
  cut_high: number | null;
}

export interface Bucket {
  bucket: string;
  events: number;
  runner_pct: number | null;
}

export interface BeforeMovesContext {
  caveat: string;
  study_end: string;
  family: Family;
  families: Record<Family, { label: string; rule: string }>;
  family_counts: Record<Family, { events: number; base_runner_pct: number | null }>;
  counts: { events: number; runners: number; fizzles: number; base_runner_pct: number | null; from: string | null; to: string | null; middle_excluded: number };
  profile: TraitProfile[];
  score_traits: { trait: string; label: string; side: 'high' | 'low'; cut: number; lift: number }[];
  score_buckets: Bucket[];
  oos: { train_events: number; test_events: number; train_to?: string; test_from?: string; test_base_pct: number | null; traits?: string[]; buckets: Bucket[] };
  regime: { quadrant: QuadrantKey; label: string; events: number; runner_pct: number | null; multiplier: number | null }[];
  regime_now: QuadrantKey | null;
  regime_now_label: string | null;
  today_sessions: number;
  summary: string[];
  definition: string;
  score_note: string;
}

/** Strip the "D: " group prefix from a trait label. */
export function traitName(label: string): string {
  return label.replace(/^[A-Z]: /, '');
}

export const TRAIT_GROUPS: Record<string, string> = {
  D: 'Daily',
  W: 'Weekly',
  M: 'Monthly',
  A: 'Accumulation',
  I: 'Improvement',
  B: 'Base',
};

// ------------------------------------------------------------------ index study

export interface IndexContext {
  caveat: string;
  study_end: string;
  today_drawdown_pct: number;
  series: { trade_date: string; ew_index: number; drawdown_pct: number; ew_large?: number; ew_mid?: number; ew_small?: number }[];
  leadership: {
    horizon: number;
    large_pct?: number | null;
    mid_pct?: number | null;
    small_pct?: number | null;
    leader_now: string | null;
    large_led_share_pct?: number | null;
    mid_led_share_pct?: number | null;
    small_led_share_pct?: number | null;
    n: number;
  }[];
  index_history_sessions: number;
  notes: string[];
}

/** Rebase a series to 0% at its first finite value. */
export function rebasePct(values: readonly (number | null | undefined)[]): (number | null)[] {
  const first = values.find(isNum);
  return values.map((v) => (isNum(v) && isNum(first) && first !== 0 ? (v / first - 1) * 100 : null));
}

/** Sparse date ticks for an index-based x axis. */
export function dateTicks(dates: readonly string[], count = 5): { x: number; label: string }[] {
  if (!dates.length) return [];
  const step = Math.max(1, Math.floor((dates.length - 1) / Math.max(1, count - 1)));
  const out: { x: number; label: string }[] = [];
  for (let i = 0; i < dates.length; i += step) out.push({ x: i, label: dates[i].slice(2, 7) });
  return out;
}
