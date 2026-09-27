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

export function quadrantCounts(rows: readonly Pick<GroupRow, 'rrg_quadrant'>[]): Record<Quadrant, number> & { none: number } {
  const out = { Leading: 0, Improving: 0, Weakening: 0, Lagging: 0, none: 0 };
  for (const r of rows) {
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
 * Which RRG rows to draw. With a cap, keep the best-ranked `perQuadrant` groups of
 * EACH quadrant, so Improving groups (the next leaders) are never crowded out by the
 * top of the board. Returns the shown rows and the true total (never a silent cap).
 */
export function rrgVisible(
  rows: readonly RrgRow[],
  allowed: ReadonlySet<string> | null,
  perQuadrant: number | null,
): { shown: RrgRow[]; total: number } {
  const pool = allowed ? rows.filter((r) => allowed.has(r.id)) : [...rows];
  const sorted = [...pool].sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9));
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
