/** Pure helpers for the Groups tab (tested in groupsModel.test.ts). */
import type { GroupRow, RrgRow } from '../../api/types';
import { isQuadrant, type Quadrant } from './kit';

export type Level = 'broad_sector' | 'sector' | 'broad_industry' | 'industry';
export type Floor = '1000' | 'all' | 'watch';

export const LEVELS: { value: Level; label: string; short: string }[] = [
  { value: 'broad_sector', label: 'Broad Sector', short: 'Broad Sector' },
  { value: 'sector', label: 'Sector', short: 'Sector' },
  { value: 'broad_industry', label: 'Broad Industry', short: 'Broad Ind.' },
  { value: 'industry', label: 'Industry', short: 'Industry' },
];

export const FLOORS: { value: Floor; label: string; title: string }[] = [
  { value: '1000', label: '≥ ₹1,000 Cr', title: 'Members with market cap ≥ ₹1,000 Cr (default)' },
  { value: 'all', label: 'All', title: 'Every listed member' },
  { value: 'watch', label: 'Watch ₹300–1,000 Cr', title: 'Smaller companies only: market cap ₹300–1,000 Cr' },
];

export function asLevel(v: string | null | undefined): Level {
  return LEVELS.some((l) => l.value === v) ? (v as Level) : 'industry';
}

export function asFloor(v: string | null | undefined): Floor {
  return v === 'all' || v === 'watch' ? v : '1000';
}

export function levelLabel(level: string | null | undefined): string {
  return LEVELS.find((l) => l.value === level)?.label ?? String(level ?? '');
}

/** Level of a group id "<level>:<name>". */
export function parseGroupId(id: string | null | undefined): { level: Level; name: string } | null {
  if (!id) return null;
  const i = id.indexOf(':');
  if (i <= 0) return null;
  const level = id.slice(0, i);
  const name = id.slice(i + 1).trim();
  if (!LEVELS.some((l) => l.value === level) || !name) return null;
  return { level: level as Level, name };
}

/** Groups with fewer members than this are "thin": listed on request, never ranked or counted. */
export const MIN_MEMBERS = 3;
export const isThinGroup = (r: { stocks?: number | null }): boolean => (r.stocks ?? 0) < MIN_MEMBERS;

/** Quadrant counts over ranked groups only (≥ MIN_MEMBERS members), matching the header / glance line. */
export function quadrantCounts(
  rows: readonly Pick<GroupRow, 'rrg_quadrant' | 'stocks'>[],
  minMembers = MIN_MEMBERS,
): Record<Quadrant, number> & { none: number } {
  const out = { Leading: 0, Improving: 0, Weakening: 0, Lagging: 0, none: 0 };
  for (const r of rows) {
    if ((r.stocks ?? 0) < minMembers) continue;
    if (isQuadrant(r.rrg_quadrant)) out[r.rrg_quadrant] += 1;
    else out.none += 1;
  }
  return out;
}

/** Board filter: free text on the group name + quadrant set (empty set = all). */
export function filterGroups<T extends Pick<GroupRow, 'group_name' | 'rrg_quadrant'>>(
  rows: readonly T[],
  text: string,
  quadrants: ReadonlySet<string>,
): T[] {
  const q = text.trim().toLowerCase();
  return rows.filter(
    (r) =>
      (!q || (r.group_name ?? '').toLowerCase().includes(q)) &&
      (quadrants.size === 0 || (r.rrg_quadrant != null && quadrants.has(r.rrg_quadrant))),
  );
}

export interface FlowItem {
  row: GroupRow;
  delta: number;
}

/**
 * Top inflow / outflow groups by smoothed turnover-share change (5d − 20d avg).
 * Groups with fewer than `minStocks` members are skipped: one stock's news is not a flow.
 */
export function flowLeaders(rows: readonly GroupRow[], n = 5, minStocks = 3): { inflow: FlowItem[]; outflow: FlowItem[] } {
  const items = rows
    .filter((r) => typeof r.turnover_share_delta === 'number' && (r.stocks ?? 0) >= minStocks)
    .map((r) => ({ row: r, delta: r.turnover_share_delta as number }));
  const inflow = items
    .filter((i) => i.delta > 0)
    .sort((a, b) => b.delta - a.delta)
    .slice(0, n);
  const outflow = items
    .filter((i) => i.delta < 0)
    .sort((a, b) => a.delta - b.delta)
    .slice(0, n);
  return { inflow, outflow };
}

/** RRG axis domain covering every head and tail point and the 100 centre lines (+ padding). */
export function rrgDomain(rows: readonly RrgRow[], pad = 0.08): { x: [number, number]; y: [number, number] } {
  let x0 = 99.5;
  let x1 = 100.5;
  let y0 = 99.5;
  let y1 = 100.5;
  for (const r of rows) {
    for (const p of [...r.tail, { rs_ratio: r.rs_ratio, rs_momentum: r.rs_momentum }]) {
      if (typeof p.rs_ratio === 'number') {
        x0 = Math.min(x0, p.rs_ratio);
        x1 = Math.max(x1, p.rs_ratio);
      }
      if (typeof p.rs_momentum === 'number') {
        y0 = Math.min(y0, p.rs_momentum);
        y1 = Math.max(y1, p.rs_momentum);
      }
    }
  }
  const px = (x1 - x0) * pad;
  const py = (y1 - y0) * pad;
  return { x: [x0 - px, x1 + px], y: [y0 - py, y1 + py] };
}

/**
 * Which RRG rows to draw. With a cap, keep the healthiest `perQuadrant` groups of
 * EACH quadrant, so Improving groups (the next leaders) are never crowded out by the
 * top of the board. Returns the shown rows and the true total (never a silent cap).
 */
export function rrgVisible(
  rows: readonly RrgRow[],
  allowed: ReadonlySet<string> | null,
  perQuadrant: number | null,
): { shown: RrgRow[]; total: number } {
  const pool = allowed ? rows.filter((r) => allowed.has(r.id)) : [...rows];
  const sorted = [...pool].sort((a, b) => (a.health_rank ?? 1e9) - (b.health_rank ?? 1e9) || (a.rank ?? 1e9) - (b.rank ?? 1e9));
  if (perQuadrant == null) return { shown: sorted, total: pool.length };
  const taken = new Map<string, number>();
  const shown = sorted.filter((r) => {
    const q = r.rrg_quadrant ?? 'none';
    const n = taken.get(q) ?? 0;
    if (n >= perQuadrant) return false;
    taken.set(q, n + 1);
    return true;
  });
  return { shown, total: pool.length };
}

/** Rank spark is drawn as −rank so "up" means improving. */
export function rankSparkValues(ranks: readonly (number | null)[] | null | undefined): (number | null)[] {
  return (ranks ?? []).map((r) => (typeof r === 'number' ? -r : null));
}

/** Charts-tab source param for a group (read by the Charts source picker). */
export function chartsSourceHref(groupId: string, symbols: readonly string[], asOf: string | null): string {
  const p = new URLSearchParams();
  p.set('source', `group:${groupId}`);
  if (symbols.length) p.set('syms', symbols.slice(0, 60).join(','));
  if (asOf) p.set('as_of', asOf);
  return `/charts?${p.toString()}`;
}

// ------------------------------------------------------------------ Health, market context, drill helpers

export type HealthZone = 'Healthy' | 'Mixed' | 'Weak';

/** metric_dictionary.yaml group_health: >= 65 Healthy, 45-65 Mixed, < 45 Weak. */
export function healthZone(v: number | null | undefined): HealthZone | null {
  if (typeof v !== 'number' || !Number.isFinite(v)) return null;
  return v >= 65 ? 'Healthy' : v >= 45 ? 'Mixed' : 'Weak';
}

/** Board context from the API (meta.context.market). */
export interface MarketContext {
  verdict?: string | null;
  midsml400_ret_21d?: number | null;
  nifty50_ret_21d?: number | null;
  groups?: number;
  quadrants?: Partial<Record<Quadrant, number>>;
  leading_falling?: number;
  leading_narrow?: number;
  falling_21d?: number;
  trend?: { Up?: number; Flat?: number; Down?: number };
  health_median?: number | null;
  health_zones?: Partial<Record<HealthZone, number>>;
}

function signedPct(v: number | null | undefined): string {
  if (typeof v !== 'number') return '—';
  const s = v.toFixed(1).replace('-', '−');
  return `${v > 0 ? '+' : ''}${s}%`;
}

/**
 * One sentence tying the board to the Desk verdict and the absolute tape, e.g.
 * "Market Mixed — MidSml400 −3.6% (21d). 'Leading' = strongest vs peers; 1 of 14 is falling in absolute terms."
 */
export function marketContextLine(m: MarketContext | null | undefined): string | null {
  if (!m) return null;
  const parts: string[] = [];
  const head = m.verdict ? `Market ${m.verdict}` : 'Market';
  parts.push(typeof m.midsml400_ret_21d === 'number' ? `${head} — MidSml400 ${signedPct(m.midsml400_ret_21d)} (21d).` : `${head}.`);
  const lead = m.quadrants?.Leading;
  if (typeof lead === 'number') {
    const falling = m.leading_falling ?? 0;
    parts.push(
      lead === 0
        ? "No group is 'Leading' (strongest vs peers)."
        : `'Leading' = strongest vs peers; ${falling} of ${lead} ${falling === 1 ? 'is' : 'are'} falling in absolute terms.`,
    );
  }
  if (typeof m.groups === 'number' && typeof m.falling_21d === 'number' && m.groups > 0) {
    parts.push(`${m.falling_21d} of ${m.groups} groups are down over 21 sessions.`);
  }
  return parts.join(' ');
}

export type Trend = 'Up' | 'Flat' | 'Down';
export function asTrend(v: string | null | undefined): Trend | null {
  return v === 'Up' || v === 'Flat' || v === 'Down' ? v : null;
}

/** Top gainers / losers among members with a value for `key` (null-safe, stable). */
export function topMovers<T extends Record<string, unknown>>(rows: readonly T[], key: keyof T, n = 5): { up: T[]; down: T[] } {
  const withVal = rows.filter((r) => typeof r[key] === 'number' && Number.isFinite(r[key] as number));
  const sorted = [...withVal].sort((a, b) => (b[key] as number) - (a[key] as number));
  return {
    up: sorted.filter((r) => (r[key] as number) > 0).slice(0, n),
    down: [...sorted].reverse().filter((r) => (r[key] as number) < 0).slice(0, n),
  };
}

/** Members grouped by the Desk queue they are in today (from active_setups). */
export function setupsByQueue<T extends { symbol?: string | null; active_setups?: string[] | null }>(rows: readonly T[]): { queue: string; symbols: string[] }[] {
  const map = new Map<string, string[]>();
  for (const r of rows) {
    for (const q of r.active_setups ?? []) {
      if (!r.symbol) continue;
      const list = map.get(q) ?? [];
      list.push(r.symbol);
      map.set(q, list);
    }
  }
  return [...map.entries()].map(([queue, symbols]) => ({ queue, symbols })).sort((a, b) => a.queue.localeCompare(b.queue));
}

/** Desk queue id -> short label. */
export function queueLabel(q: string): string {
  return ({ vcp: 'VCP', darvas_10ema: 'Darvas 10EMA', darvas_squeeze: 'Darvas squeeze' } as Record<string, string>)[q] ?? q.replace(/_/g, ' ');
}

// ------------------------------------------------------------------ treemap (squarified)

export interface TreeTile<T> {
  item: T;
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Squarified treemap (Bruls et al.) of `items` sized by `size` into the rectangle
 * (x, y, w, h). Non-positive sizes are dropped. Pure; order = descending size.
 */
export function squarify<T>(items: readonly T[], size: (t: T) => number, x: number, y: number, w: number, h: number): TreeTile<T>[] {
  const data = items
    .map((item) => ({ item, v: size(item) }))
    .filter((d) => Number.isFinite(d.v) && d.v > 0)
    .sort((a, b) => b.v - a.v);
  const total = data.reduce((s, d) => s + d.v, 0);
  const out: TreeTile<T>[] = [];
  if (!data.length || w <= 0 || h <= 0 || total <= 0) return out;
  const scale = (w * h) / total;
  let rect = { x, y, w, h };
  let i = 0;
  const worst = (row: number[], side: number) => {
    const s = row.reduce((a, b) => a + b, 0);
    const mx = Math.max(...row);
    const mn = Math.min(...row);
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
  };
  while (i < data.length) {
    const side = Math.min(rect.w, rect.h);
    const row: number[] = [data[i].v * scale];
    let j = i + 1;
    while (j < data.length) {
      const next = [...row, data[j].v * scale];
      if (worst(next, side) > worst(row, side)) break;
      row.push(data[j].v * scale);
      j += 1;
    }
    const sum = row.reduce((a, b) => a + b, 0);
    if (rect.w >= rect.h) {
      const cw = sum / rect.h;
      let cy = rect.y;
      for (let k = 0; k < row.length; k += 1) {
        const ch = row[k] / cw;
        out.push({ item: data[i + k].item, x: rect.x, y: cy, w: cw, h: ch });
        cy += ch;
      }
      rect = { x: rect.x + cw, y: rect.y, w: rect.w - cw, h: rect.h };
    } else {
      const ch = sum / rect.w;
      let cx = rect.x;
      for (let k = 0; k < row.length; k += 1) {
        const cw = row[k] / ch;
        out.push({ item: data[i + k].item, x: cx, y: rect.y, w: cw, h: ch });
        cx += cw;
      }
      rect = { x: rect.x, y: rect.y + ch, w: rect.w, h: rect.h - ch };
    }
    i = j;
  }
  return out;
}
