/**
 * Today (Desk "Today" + Groups "Today" mode) — pure helpers, no React.
 * The server owns every rule (meta.context.*_rules); this file only maps ids to
 * labels / tones and slices rows for display.
 */
import type { TodayBreakoutRow, TodayEvent, TodayGroupRow, TodayMoverRow } from '../api/types';
import type { ChipTone } from '../ui/Chip';

export type { TodayBreakoutRow, TodayContributor, TodayEvent, TodayGroupRow, TodayMarketRow, TodayMoverRow } from '../api/types';

export interface RuleClause {
  field: string;
  op: string;
  value: number | null;
}
export interface QualityRule {
  id: string;
  label: string;
  tone: string;
  why: string;
  when: RuleClause[];
}
export interface EvidenceTrait {
  key: string;
  meaning?: string | null;
  lift_upper_circuit?: number | null;
  lift_test_upper_circuit?: number | null;
  lift_all?: number | null;
}
export interface BreakoutRule {
  id: string;
  label: string;
  rule: string;
}

export const MCAP_FLOORS = [
  { value: '1000', label: '≥ ₹1,000 Cr', title: 'Market cap at least ₹1,000 Cr (default)' },
  { value: '0', label: 'All caps', title: 'Every listed stock, including tiny caps (Operator-ish shows here)' },
] as const;
export type McapFloor = (typeof MCAP_FLOORS)[number]['value'];
export const asMcapFloor = (v: string | null | undefined): McapFloor => (v === '0' ? '0' : '1000');

const TONE: Record<string, ChipTone> = { good: 'positive', bad: 'negative', caution: 'warn', neutral: 'neutral' };
export function qualityTone(tone: string | null | undefined): ChipTone {
  return (tone && TONE[tone]) || 'neutral';
}

/** "Real" on a down day is real selling: the label stays, the tooltip says which side. */
export function qualitySideNote(row: Pick<TodayMoverRow, 'quality_id' | 'change_1d_pct'>): string | null {
  if (row.quality_id !== 'real' || row.change_1d_pct == null) return null;
  return row.change_1d_pct >= 0 ? 'real buying' : 'real selling';
}

export const TRAIT_LABELS: Record<string, { short: string; title: string }> = {
  delivery_spike: { short: 'Deliv spike', title: 'Delivered shares > 2× their 20-day average' },
  rvol_1_5: { short: 'RVOL≥1.5', title: 'Volume at least 1.5× the prior 20-session average' },
  results_5: { short: 'Results ±5', title: 'Results board meeting / financial results within 5 sessions' },
};

/** Tooltip text for a trait chip, with the evidence engine's lift when served. */
export function traitTitle(key: string, evidence: readonly EvidenceTrait[] | undefined): string {
  const base = TRAIT_LABELS[key]?.title ?? key;
  const ev = evidence?.find((e) => e.key === key);
  if (!ev || ev.lift_upper_circuit == null) return base;
  const test = ev.lift_test_upper_circuit != null ? ` (out of sample ${ev.lift_test_upper_circuit.toFixed(2)}×)` : '';
  return `${base}. Evidence: seen ${ev.lift_upper_circuit.toFixed(2)}× more often than in matched controls the session before upper-circuit moves${test}.`;
}

export const KIND_LABELS: Record<string, { label: string; tone: ChipTone }> = {
  new_52w_high: { label: '52W high', tone: 'positive' },
  setup_trigger: { label: 'Setup trigger', tone: 'accent' },
  high_20d_rvol: { label: '20D high + RVOL', tone: 'info' },
  gap_up: { label: 'Gap-up', tone: 'violet' },
  accumulation: { label: 'Accumulation', tone: 'positive' },
  distribution: { label: 'Distribution', tone: 'negative' },
};
export const BREAKOUT_KINDS = ['new_52w_high', 'setup_trigger', 'high_20d_rvol', 'gap_up'] as const;
export const FOOTPRINT_KINDS = ['accumulation', 'distribution'] as const;

export const QUEUE_SHORT: Record<string, string> = { darvas_squeeze: 'Squeeze', darvas_10ema: '10 EMA', vcp: 'VCP' };

export function splitMovers(rows: readonly TodayMoverRow[]): { gainers: TodayMoverRow[]; losers: TodayMoverRow[] } {
  const gainers: TodayMoverRow[] = [];
  const losers: TodayMoverRow[] = [];
  for (const r of rows) (r.side === 'gainer' ? gainers : losers).push(r);
  gainers.sort((a, b) => a.rank - b.rank);
  losers.sort((a, b) => a.rank - b.rank);
  return { gainers, losers };
}

/** Rows having any of `kinds` (all rows when the set is empty), optionally restricted to a kind family. */
export function filterByKinds(rows: readonly TodayBreakoutRow[], family: readonly string[], selected: ReadonlySet<string>): TodayBreakoutRow[] {
  return rows.filter((r) => {
    const ks = (r.kinds ?? []).filter((k) => family.includes(k));
    if (!ks.length) return false;
    return selected.size === 0 || ks.some((k) => selected.has(k));
  });
}

export function kindCounts(rows: readonly TodayBreakoutRow[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of rows) for (const k of r.kinds ?? []) out[k] = (out[k] ?? 0) + 1;
  return out;
}

/** "results today", "results in 3d", "results 2d ago" — calendar days vs as_of. */
export function eventWhen(ev: TodayEvent | null | undefined, asOf: string | null | undefined): string | null {
  if (!ev?.event_date) return null;
  const label = (ev.event_type ?? 'event').replace(/_/g, ' ').replace('financial results', 'results').replace('board meeting', 'results meeting');
  if (!asOf) return label;
  const d = Math.round((Date.parse(ev.event_date) - Date.parse(asOf)) / 86_400_000);
  if (d === 0) return `${label} today`;
  return d > 0 ? `${label} in ${d}d` : `${label} ${-d}d ago`;
}

export const BREADTH_TONE: Record<string, ChipTone> = { broad: 'positive', mixed: 'neutral', 'one-stock': 'warn', flat: 'neutral', thin: 'neutral' };
export const PERSISTENCE_TONE: Record<string, ChipTone> = {
  trend_up: 'positive',
  resume_up: 'positive',
  bounce: 'warn',
  pullback: 'neutral',
  fade: 'neutral',
  trend_down: 'negative',
  flat: 'neutral',
};
export const PARTICIPATION_TONE: Record<string, ChipTone> = { real: 'positive', churn: 'warn', heavy: 'info', light: 'warn', normal: 'neutral' };

/** Strongest and weakest groups (with a return) for the compact Desk panel; thin groups excluded. */
export function topBottomGroups(rows: readonly TodayGroupRow[], n = 5): { up: TodayGroupRow[]; down: TodayGroupRow[] } {
  const ranked = rows.filter((r) => r.return_1d != null && r.breadth_label !== 'thin');
  const up = [...ranked].filter((r) => (r.return_1d ?? 0) > 0).sort((a, b) => (b.return_1d ?? 0) - (a.return_1d ?? 0)).slice(0, n);
  const down = [...ranked].filter((r) => (r.return_1d ?? 0) < 0).sort((a, b) => (a.return_1d ?? 0) - (b.return_1d ?? 0)).slice(0, n);
  return { up, down };
}

/**
 * Default Groups › Today order: broad moves first. |1D| × share of members that moved the group's way
 * (advancers on an up day, decliners on a down day). A +8% one-stock pop scores below a +2% move with
 * 90% of members up. NULL when the return or breadth is unknown.
 */
export function broadMoveScore(r: Pick<TodayGroupRow, 'return_1d' | 'advancers' | 'decliners' | 'stocks_with_return'>): number | null {
  if (r.return_1d == null || !r.stocks_with_return) return null;
  const way = r.return_1d >= 0 ? r.advancers : r.decliners;
  if (way == null) return null;
  return Math.abs(r.return_1d) * (way / r.stocks_with_return);
}

/** Hide thin groups (< 3 members with a return) unless asked. */
export function withoutThinGroups<T extends Pick<TodayGroupRow, 'stocks_with_return' | 'stocks'>>(rows: readonly T[], showThin: boolean): T[] {
  return showThin ? [...rows] : rows.filter((r) => (r.stocks_with_return ?? r.stocks ?? 0) >= 3);
}

export function filterGroupsText(rows: readonly TodayGroupRow[], text: string): TodayGroupRow[] {
  const t = text.trim().toLowerCase();
  if (!t) return [...rows];
  return rows.filter((r) => r.group_name.toLowerCase().includes(t) || (r.symbols ?? []).some((s) => s.toLowerCase() === t));
}

/** Human text for a rule clause list: "rvol ≥ 1.5 and deliv_pct_x ≥ 1.2". */
export function clauseText(when: readonly RuleClause[]): string {
  const OPS: Record<string, string> = { gt: '>', gte: '≥', lt: '<', lte: '≤', is_true: 'is true' };
  const NAMES: Record<string, string> = {
    rvol: 'RVOL',
    deliv_qty_x: 'delivered qty ×20d',
    deliv_pct_x: 'delivery % ×20d',
    market_cap_cr: 'market cap ₹Cr',
    at_circuit: 'closed at price band',
    turnover_vs_20d: 'turnover ×',
    return_1d: '1D',
    return_5d: '5D',
    return_21d: '21D',
    abs_return_1d: '|1D|',
  };
  return when.map((c) => `${NAMES[c.field] ?? c.field} ${OPS[c.op] ?? c.op}${c.value != null ? ` ${c.value}` : ''}`).join(' and ');
}
