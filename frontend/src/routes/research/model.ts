/**
 * Research tab data model (spec 7.6): readers over the FINAL v2 row shapes
 * plus the optional extras the evidence engine may serve.
 *
 * Guaranteed columns come from the generated OpenAPI types. Anything else is
 * read defensively from the open `[key: string]: unknown` part of a row or
 * from `meta.context`, and is only rendered when present — never defaulted.
 *
 * Optional extras this UI understands (all may be absent):
 *   BigMoveRow:  security_name, broad_sector, sector, broad_industry,
 *                verdict_then, catalyst_detail, path_pct (number[]: close vs
 *                T-1 close in %, T-20..T+20)
 *   big-moves meta.context.lift:          LiftRow[]   (out-of-sample lift table)
 *   big-moves meta.context.feature_path:  PathRow[]   (median path movers vs controls)
 *   big-moves/{id} meta.context.features: FeatureRow[] (event fingerprint vs controls)
 *   pre-move meta.context.base_rate:      number (%), rows carry precision_20d / base_rate_20d / n
 *   analogs meta.context.agreement / k
 */
import type { BigMoveRow, EnvelopeMeta, MarketAnalogRow, PreMoveRow, Verdict } from '../../api/types';
import { isNum } from '../../lib/fmt';

// ------------------------------------------------------------------ generic readers

export function str(v: unknown): string | null {
  return typeof v === 'string' && v.trim() !== '' ? v : null;
}

export function num(v: unknown): number | null {
  return isNum(v) ? v : null;
}

export function numArray(v: unknown): (number | null)[] | null {
  if (!Array.isArray(v) || v.length === 0) return null;
  return v.map((x) => (isNum(x) ? x : null));
}

export function ctx(meta: EnvelopeMeta | undefined | null): Record<string, unknown> {
  const c = meta?.context;
  return c && typeof c === 'object' ? (c as Record<string, unknown>) : {};
}

function records(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter((x): x is Record<string, unknown> => !!x && typeof x === 'object') : [];
}

export function median(values: readonly (number | null | undefined)[]): number | null {
  const xs = values.filter(isNum).sort((a, b) => a - b);
  if (!xs.length) return null;
  const mid = Math.floor(xs.length / 2);
  return xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
}

export const VERDICT_ORDER: readonly Verdict[] = ['Favourable', 'Constructive', 'Mixed', 'Weak', 'Danger'];

export function asVerdictWord(v: unknown): Verdict | null {
  const s = str(v);
  if (!s) return null;
  return VERDICT_ORDER.find((x) => x.toLowerCase() === s.toLowerCase()) ?? null;
}

/** Minimum sample for an aggregate number (spec 5). */
export const MIN_SAMPLE = 30;

// ------------------------------------------------------------------ market analogs

export const ANALOG_HORIZONS = [0, 5, 20, 60] as const;

/** One analog's forward path in session offsets: 0, 5, 20, 60 (MidSml400 %). */
export function analogPath(r: MarketAnalogRow): (number | null)[] {
  return [0, num(r.fwd_midsml400_5d_pct), num(r.fwd_midsml400_20d_pct), num(r.fwd_midsml400_60d_pct)];
}

export interface HorizonSummary {
  horizon: 5 | 20 | 60;
  n: number;
  median: number | null;
  min: number | null;
  max: number | null;
  up: number;
  down: number;
}

export interface AnalogSummary {
  k: number;
  horizons: HorizonSummary[];
  /** Share of analogs pointing the same way at 20 sessions (0..1), with n. */
  agreement20: { share: number | null; direction: 'up' | 'down' | null; n: number };
  /** True when analogs split: no direction holds >= 70% at 20 sessions. */
  disagree: boolean;
  medianDistance: number | null;
  followThrough: { median: number | null; n: number };
}

const AGREEMENT_THRESHOLD = 0.7;

export function summarizeAnalogs(rows: readonly MarketAnalogRow[]): AnalogSummary {
  const col = (h: 5 | 20 | 60) =>
    rows.map((r) => (h === 5 ? r.fwd_midsml400_5d_pct : h === 20 ? r.fwd_midsml400_20d_pct : r.fwd_midsml400_60d_pct)).filter(isNum);
  const horizons = ([5, 20, 60] as const).map((h) => {
    const xs = col(h);
    return {
      horizon: h,
      n: xs.length,
      median: median(xs),
      min: xs.length ? Math.min(...xs) : null,
      max: xs.length ? Math.max(...xs) : null,
      up: xs.filter((x) => x > 0).length,
      down: xs.filter((x) => x < 0).length,
    };
  });
  const h20 = horizons[1];
  const direction = h20.n === 0 ? null : h20.up >= h20.down ? 'up' : 'down';
  const share = h20.n === 0 ? null : Math.max(h20.up, h20.down) / h20.n;
  const ft = rows.map((r) => r.next_month_follow_through_pct).filter(isNum);
  return {
    k: rows.length,
    horizons,
    agreement20: { share, direction, n: h20.n },
    disagree: share !== null && share < AGREEMENT_THRESHOLD,
    medianDistance: median(rows.map((r) => r.distance)),
    followThrough: { median: median(ft), n: ft.length },
  };
}

// ------------------------------------------------------------------ big movers

export const TRIGGER_LABEL: Record<string, string> = {
  upper_circuit: 'Upper circuit',
  up30_20d: '+30% in 20 sessions',
  up50_60d: '+50% in 60 sessions',
};

export const CATALYSTS = ['results', 'deal', 'sector', 'corporate_action', 'unexplained'] as const;
export type Catalyst = (typeof CATALYSTS)[number];

export const CATALYST_LABEL: Record<Catalyst, string> = {
  results: 'Results ±3',
  deal: 'Deal ±3',
  sector: 'Sector-wide',
  corporate_action: 'Corporate action',
  unexplained: 'Unexplained',
};

export const CATALYST_TONE: Record<Catalyst, 'info' | 'accent' | 'violet' | 'warn' | 'neutral'> = {
  results: 'info',
  deal: 'accent',
  sector: 'violet',
  corporate_action: 'warn',
  unexplained: 'neutral',
};

export function asCatalyst(v: unknown): Catalyst | null {
  const s = str(v)?.toLowerCase();
  return s && (CATALYSTS as readonly string[]).includes(s) ? (s as Catalyst) : null;
}

export interface CatalystShare {
  catalyst: Catalyst | 'unknown';
  n: number;
  share: number;
}

/** Rolled-up catalyst shares; `total` is every event, unattributed rows count as "unknown". */
export function catalystShares(rows: readonly BigMoveRow[]): { total: number; shares: CatalystShare[] } {
  const counts = new Map<Catalyst | 'unknown', number>();
  for (const r of rows) {
    const c = asCatalyst(r.catalyst) ?? 'unknown';
    counts.set(c, (counts.get(c) ?? 0) + 1);
  }
  const total = rows.length;
  const order: (Catalyst | 'unknown')[] = [...CATALYSTS, 'unknown'];
  return {
    total,
    shares: order.filter((c) => counts.has(c)).map((c) => ({ catalyst: c, n: counts.get(c)!, share: total ? counts.get(c)! / total : 0 })),
  };
}

export const TAXONOMY_LEVELS = [
  { id: 'broad_sector', label: 'Broad Sector' },
  { id: 'sector', label: 'Sector' },
  { id: 'broad_industry', label: 'Broad Industry' },
  { id: 'industry', label: 'Industry' },
] as const;
export type TaxonomyLevel = (typeof TAXONOMY_LEVELS)[number]['id'];

export function isTaxonomyLevel(v: unknown): v is TaxonomyLevel {
  return TAXONOMY_LEVELS.some((l) => l.id === v);
}

export interface GroupStudyRow {
  group: string;
  events: number;
  symbols: number;
  medianMove: number | null;
  sectorWide: number;
  topCatalyst: Catalyst | null;
  topCatalystN: number;
  share: number;
}

/** Big movers rolled up by one taxonomy level. Rows without the level go to "Unclassified". */
export function groupStudy(rows: readonly BigMoveRow[], level: TaxonomyLevel): { rows: GroupStudyRow[]; classified: number; total: number } {
  const by = new Map<string, BigMoveRow[]>();
  let classified = 0;
  for (const r of rows) {
    const g = str((r as Record<string, unknown>)[level]);
    if (g) classified++;
    const key = g ?? 'Unclassified';
    const list = by.get(key);
    if (list) list.push(r);
    else by.set(key, [r]);
  }
  const total = rows.length;
  const out = [...by.entries()].map(([group, list]) => {
    const cats = catalystShares(list).shares.filter((s) => s.catalyst !== 'unknown');
    const top = cats.reduce<CatalystShare | null>((best, s) => (!best || s.n > best.n ? s : best), null);
    return {
      group,
      events: list.length,
      symbols: new Set(list.map((r) => r.symbol).filter(Boolean)).size,
      medianMove: median(list.map((r) => r.move_pct)),
      sectorWide: list.filter((r) => asCatalyst(r.catalyst) === 'sector').length,
      topCatalyst: (top?.catalyst as Catalyst | undefined) ?? null,
      topCatalystN: top?.n ?? 0,
      share: total ? list.length / total : 0,
    };
  });
  out.sort((a, b) => b.events - a.events || a.group.localeCompare(b.group));
  return { rows: out, classified, total };
}

export interface LiftRow {
  feature: string;
  bucket: string | null;
  lift: number | null;
  precision_20d: number | null;
  n_movers: number | null;
  n_controls: number | null;
  oos: boolean | null;
  metric_key: string | null;
}

export function readLift(meta: EnvelopeMeta | undefined): LiftRow[] {
  return records(ctx(meta).lift).flatMap((r) => {
    const feature = str(r.feature) ?? str(r.name);
    if (!feature) return [];
    return [
      {
        feature,
        bucket: str(r.bucket),
        lift: num(r.lift),
        precision_20d: num(r.precision_20d),
        n_movers: num(r.n_movers),
        n_controls: num(r.n_controls),
        oos: typeof r.oos === 'boolean' ? r.oos : typeof r.out_of_sample === 'boolean' ? r.out_of_sample : null,
        metric_key: str(r.metric_key),
      },
    ];
  });
}

export interface PathRow {
  feature: string;
  offset: number;
  movers: number | null;
  controls: number | null;
  n_movers: number | null;
  n_controls: number | null;
}

export function readFeaturePath(meta: EnvelopeMeta | undefined): PathRow[] {
  return records(ctx(meta).feature_path).flatMap((r) => {
    const feature = str(r.feature);
    const offset = num(r.offset);
    if (!feature || offset === null) return [];
    return [{ feature, offset, movers: num(r.movers), controls: num(r.controls), n_movers: num(r.n_movers), n_controls: num(r.n_controls) }];
  });
}

export interface FeatureRow {
  feature: string;
  offset: number | null;
  mover: number | null;
  control_median: number | null;
  n_controls: number | null;
  percentile: number | null;
  metric_key: string | null;
}

export function readFeatures(meta: EnvelopeMeta | undefined): FeatureRow[] {
  return records(ctx(meta).features).flatMap((r) => {
    const feature = str(r.feature) ?? str(r.name);
    if (!feature) return [];
    return [
      {
        feature,
        offset: num(r.offset),
        mover: num(r.mover_value) ?? num(r.value),
        control_median: num(r.control_median) ?? num(r.control_value),
        n_controls: num(r.n_controls) ?? num(r.control_n),
        percentile: num(r.percentile_vs_controls) ?? num(r.percentile),
        metric_key: str(r.metric_key),
      },
    ];
  });
}

/** Pivot event features into feature × offset (T-60, T-20, T-5, T-1). */
export function pivotFeatures(rows: readonly FeatureRow[]): { offsets: number[]; features: { feature: string; metric_key: string | null; cells: Map<number, FeatureRow> }[] } {
  const offsets = [...new Set(rows.map((r) => r.offset).filter(isNum))].sort((a, b) => a - b);
  const map = new Map<string, { feature: string; metric_key: string | null; cells: Map<number, FeatureRow> }>();
  for (const r of rows) {
    const e = map.get(r.feature) ?? { feature: r.feature, metric_key: r.metric_key, cells: new Map() };
    e.cells.set(r.offset ?? 0, r);
    map.set(r.feature, e);
  }
  return { offsets: offsets.length ? offsets : [0], features: [...map.values()] };
}

export function featureLabel(key: string): string {
  const s = key.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function offsetLabel(o: number): string {
  return o === 0 ? 'T' : o < 0 ? `T${o}` : `T+${o}`;
}

export interface BigMoveExtras {
  security_name: string | null;
  verdict_then: Verdict | null;
  catalyst_detail: string | null;
  path_pct: (number | null)[] | null;
}

export function bigMoveExtras(r: BigMoveRow): BigMoveExtras {
  const o = r as Record<string, unknown>;
  return {
    security_name: str(o.security_name),
    verdict_then: asVerdictWord(o.verdict_then ?? o.environment_state),
    catalyst_detail: str(o.catalyst_detail),
    path_pct: numArray(o.path_pct),
  };
}

/** Big-move event id for URLs; null when the server did not supply one. */
export function eventId(r: BigMoveRow): string | null {
  return str(r.event_id);
}

// ------------------------------------------------------------------ pre-move watch

export function preMoveLift(r: PreMoveRow): number | null {
  const p = num(r.precision_20d);
  const b = num(r.base_rate_20d);
  return p !== null && b !== null && b > 0 ? p / b : null;
}

/** Research label: precision must clearly beat the base rate (>= 1.5x) with n >= 30 to be called an edge. */
export function preMoveEdge(r: PreMoveRow): 'edge' | 'weak' | 'insufficient' | 'unknown' {
  const n = num(r.n);
  const lift = preMoveLift(r);
  if (n === null || lift === null) return 'unknown';
  if (n < MIN_SAMPLE) return 'insufficient';
  return lift >= 1.5 ? 'edge' : 'weak';
}

// ------------------------------------------------------------------ bars window for the event chart

/** Slice oldest-first bars to [event - before, event + after] sessions. */
export function eventWindow<T extends { time: string }>(bars: readonly T[], eventDate: string, before = 60, after = 20): T[] {
  if (!bars.length) return [];
  let idx = bars.findIndex((b) => b.time >= eventDate);
  if (idx < 0) idx = bars.length - 1;
  return bars.slice(Math.max(0, idx - before), Math.min(bars.length, idx + after + 1));
}
