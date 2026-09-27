/**
 * Pure Desk view-model helpers (spec 7.2). Reshape served rows only; no
 * value is ever invented.
 */
import type { DiffRow, EvidenceRow, GroupRow, MarketHealthRow, QueueRow, Verdict } from '../api/types';

export const QUEUES = [
  { id: 'darvas_squeeze', label: 'Darvas Squeeze', short: 'Squeeze', timeframes: ['D', 'W', 'M'] },
  { id: 'darvas_10ema', label: 'Darvas 10 EMA', short: '10 EMA', timeframes: ['D', 'W', 'M'] },
  { id: 'vcp', label: 'VCP', short: 'VCP', timeframes: ['D'] },
] as const;
export type QueueId = (typeof QUEUES)[number]['id'];
export type Tf = 'D' | 'W' | 'M';

export function asQueueId(v: string | null | undefined): QueueId {
  return QUEUES.find((q) => q.id === v)?.id ?? 'darvas_squeeze';
}

export function asTf(v: string | null | undefined, queue: QueueId): Tf {
  const allowed = QUEUES.find((q) => q.id === queue)!.timeframes as readonly string[];
  return v && allowed.includes(v) ? (v as Tf) : 'D';
}

/** Case-insensitive match on symbol, name, industry and sector. */
export function filterQueueRows(rows: readonly QueueRow[], text: string, onlyNew: boolean): QueueRow[] {
  const t = text.trim().toLowerCase();
  return rows.filter((r) => {
    if (onlyNew && r.is_new !== true) return false;
    if (!t) return true;
    return [r.symbol, r.security_name, r.industry, r.sector, r.broad_sector].some((f) => f?.toLowerCase().includes(t));
  });
}

export interface QueueDiff {
  queue: string;
  added: DiffRow[];
  dropped: DiffRow[];
}

/** New / dropped per queue, strongest (strength rank) first; NULL ranks last. */
export function groupDiff(rows: readonly DiffRow[]): Record<string, QueueDiff> {
  const out: Record<string, QueueDiff> = {};
  for (const q of QUEUES) out[q.id] = { queue: q.id, added: [], dropped: [] };
  for (const r of rows) {
    const g = (out[r.queue] ??= { queue: r.queue, added: [], dropped: [] });
    (r.change === 'new' ? g.added : g.dropped).push(r);
  }
  const byRank = (a: DiffRow, b: DiffRow) => (b.rs_percentile ?? -1) - (a.rs_percentile ?? -1) || (a.symbol ?? '').localeCompare(b.symbol ?? '');
  for (const g of Object.values(out)) {
    g.added.sort(byRank);
    g.dropped.sort(byRank);
  }
  return out;
}

export interface BreadthReading {
  key: keyof MarketHealthRow & string;
  value: number | null;
  delta: number | null;
}

const BREADTH_KEYS = [
  'pct_above_50ema',
  'pct_above_200ema',
  'pct_above_10ema',
  'net_new_highs',
  'advance_pct',
  'distribution_days_25',
  'india_vix',
] as const;

/** Latest breadth readings with 1-session change (rows newest first). */
export function breadthSnapshot(rows: readonly MarketHealthRow[]): { date: string | null; state: string | null; readings: BreadthReading[] } {
  const [cur, prev] = rows;
  if (!cur) return { date: null, state: null, readings: [] };
  const num = (r: MarketHealthRow | undefined, k: string): number | null => {
    const v = r ? (r as unknown as Record<string, unknown>)[k] : null;
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
  };
  return {
    date: cur.trade_date ?? null,
    state: (cur as { breadth_state?: string | null }).breadth_state ?? null,
    readings: BREADTH_KEYS.map((k) => {
      const v = num(cur, k);
      const p = num(prev, k);
      return { key: k, value: v, delta: v != null && p != null ? Number((v - p).toFixed(2)) : null };
    }),
  };
}

/** Oldest -> newest series of one breadth field (for sparks). */
export function breadthSeries(rows: readonly MarketHealthRow[], key: string, n = 60): (number | null)[] {
  return rows
    .slice(0, n)
    .map((r) => {
      const v = (r as unknown as Record<string, unknown>)[key];
      return typeof v === 'number' && Number.isFinite(v) ? v : null;
    })
    .reverse();
}

export interface LeadingGroups {
  rows: GroupRow[];
  /** True when RRG quadrants are served (group_daily); false = legacy rank fallback. */
  rrg: boolean;
  minStocks: number;
}

/**
 * Top groups for the Desk strip: RRG "Leading" by rank when quadrants exist;
 * otherwise the best-ranked groups with at least `minStocks` members (a
 * two-stock "industry" is noise).
 */
export function leadingGroups(rows: readonly GroupRow[], n = 5, minStocks = 5): LeadingGroups {
  const rrg = rows.some((r) => r.rrg_quadrant != null);
  const pool = rows.filter((r) => (rrg ? r.rrg_quadrant === 'Leading' : (r.stocks ?? 0) >= minStocks));
  const sorted = [...pool].sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity));
  return { rows: sorted.slice(0, n), rrg, minStocks };
}

/** Evidence line: the all-states row plus the row for the current verdict, when served. */
export function evidenceFor(rows: readonly EvidenceRow[], verdict: Verdict | null): { all: EvidenceRow | null; now: EvidenceRow | null } {
  const all = rows.find((r) => r.bucket === 'all') ?? null;
  const now = verdict ? (rows.find((r) => r.bucket.toLowerCase() === verdict.toLowerCase()) ?? null) : null;
  return { all, now };
}

/** Symbols with a result/board meeting within ~10 sessions, for the warning count. */
export function countFlags(rows: readonly QueueRow[]): { isNew: number; results: number; wideRisk: number; pastTrigger: number } {
  let isNew = 0;
  let results = 0;
  let wideRisk = 0;
  let pastTrigger = 0;
  for (const r of rows) {
    if (r.is_new) isNew++;
    if (r.results_within_10) results++;
    if (r.risk_flag) wideRisk++;
    if (r.distance_to_trigger_pct != null && r.distance_to_trigger_pct < 0) pastTrigger++;
  }
  return { isNew, results, wideRisk, pastTrigger };
}
