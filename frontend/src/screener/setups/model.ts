/**
 * Setups board (HarkPro/06-tab2-setups.md, locked 2026-10-09): pure helpers.
 * The server owns every calculation; this file filters, groups and formats.
 */
import type { SetupBoardRow } from '../../api/types';
import type { ChipTone } from '../../ui/Chip';
import { formatTradingViewList, type TvSection } from '../../lib/tradingview';
import { DIVERGENCE_DEFAULTS } from './divergenceModel';

export type ScreenerId = 'darvas_squeeze' | 'darvas_10ema' | 'vcp' | 'momentum';
export type GroupState = 'Favour' | 'Neutral' | 'Caution';
export type TvGroupBy = 'screener' | 'sector' | 'industry' | 'bucket';
export type SetupsView = 'board' | 'grid' | 'near' | 'dropped' | 'div';

export const SCREENERS: { id: ScreenerId; label: string; short: string }[] = [
  { id: 'darvas_squeeze', label: 'Darvas Squeeze', short: 'SQZ' },
  { id: 'darvas_10ema', label: 'Darvas 10 EMA', short: '10E' },
  { id: 'vcp', label: 'VCP', short: 'VCP' },
  { id: 'momentum', label: 'Momentum', short: 'MOM' },
];
export const STATES: GroupState[] = ['Favour', 'Neutral', 'Caution'];

/** URL state (useTabUrlState): all strings. */
export const SETUPS_DEFAULTS = {
  sv: 'board', // view
  sq: '', // screener filter (comma list of ScreenerId; '' = all)
  sg: '', // group-state filter (comma list; '' = all)
  tpl: 'ema', // momentum template: ema | sma
  vg: 'day', // momentum volume gate: day | avg20d
  rn: '10', // results within N sessions
  tvg: 'screener', // Copy for TradingView sections
  ...DIVERGENCE_DEFAULTS, // Divergences view: dtf / dside / dtypes / dwin
};
export type SetupsState = typeof SETUPS_DEFAULTS;

export interface CountInfo {
  today: number;
  median_20: number | null;
  percentile: number | null;
  series: [string, number][];
  history_sessions: number;
  gap?: string;
}
export interface BaseRateInfo {
  n: number;
  win: number | null;
  median: number | null;
}
export interface BoardContext {
  previous_session?: string | null;
  session_gap_days?: number | null;
  counts?: Record<ScreenerId, CountInfo>;
  group_split?: Record<GroupState, number>;
  confluence?: number;
  groups?: { favour: number; caution: number; total: number };
  base_rates?: Record<string, BaseRateInfo>;
  readout?: { lines: string[]; what_to_do: string[] };
  excluded_5pct_band?: string[];
  data_gaps?: string[];
  params?: { template: string; volume_mode: string; min_volume: number; results_n: number };
}

export interface PeerRow {
  symbol: string;
  rs_percentile: number | null;
  away_52w_high_pct: number | null;
  away_10ema_pct: number | null;
  tags: string[];
}
export interface DetailContext {
  symbol?: string;
  industry?: string | null;
  on_board?: boolean;
  peers?: PeerRow[];
  deal_markers?: { time: string; kind: string; value_cr: number | null }[];
  rsi_divergences?: { time: string; kind: string; type?: string | null }[];
  data_gaps?: string[];
}

export function parseList<T extends string>(raw: string, allowed: readonly T[]): T[] {
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter((s): s is T => (allowed as readonly string[]).includes(s));
}

export function toggleInList(raw: string, id: string): string {
  const set = new Set(raw.split(',').filter(Boolean));
  if (set.has(id)) set.delete(id);
  else set.add(id);
  return [...set].join(',');
}

/** Board filter: screener (any of), group state (any of), free-text search. */
export function filterRows(rows: readonly SetupBoardRow[], screeners: ScreenerId[], states: GroupState[], search = ''): SetupBoardRow[] {
  const q = search.trim().toLowerCase();
  return rows.filter(
    (r) =>
      (screeners.length === 0 || r.screeners.some((s) => (screeners as string[]).includes(s))) &&
      (states.length === 0 || (states as string[]).includes(r.group_state)) &&
      (!q ||
        r.symbol.toLowerCase().includes(q) ||
        (r.name ?? '').toLowerCase().includes(q) ||
        (r.industry ?? '').toLowerCase().includes(q)),
  );
}

export function momentumBucket(r: SetupBoardRow): string | null {
  const t = r.tags.find((x) => x.startsWith('MOM '));
  return t ? t.slice(4) : null;
}

/** Copy for TradingView: `###Section,NSE:A,NSE:B` with sections by screener, sector, industry or momentum bucket. */
export function tvSections(rows: readonly SetupBoardRow[], by: TvGroupBy): TvSection[] {
  const order: string[] = [];
  const map = new Map<string, string[]>();
  const add = (key: string, sym: string) => {
    if (!map.has(key)) {
      map.set(key, []);
      order.push(key);
    }
    map.get(key)!.push(sym);
  };
  if (by === 'screener') {
    for (const s of SCREENERS) for (const r of rows) if (r.screeners.includes(s.id)) add(s.label, r.symbol);
  } else if (by === 'bucket') {
    const rank = ['0–2%', '2–5%', '5–10%', '10%+'];
    for (const b of rank) for (const r of rows) if (momentumBucket(r) === b) add(`MOM ${b}`, r.symbol);
  } else {
    for (const r of rows) add((by === 'sector' ? r.sector : r.industry) ?? 'Unclassified', r.symbol);
  }
  return order.map((title) => ({ title, symbols: map.get(title)! }));
}

export function tvText(rows: readonly SetupBoardRow[], by: TvGroupBy): { text: string; count: number } {
  return formatTradingViewList(tvSections(rows, by));
}

export function stateTone(state: string | null | undefined): ChipTone {
  return state === 'Favour' ? 'positive' : state === 'Caution' ? 'negative' : 'neutral';
}

export function tagTone(tag: string): ChipTone {
  if (tag.startsWith('SQZ')) return 'accent';
  if (tag.startsWith('10E')) return 'info';
  if (tag.startsWith('VCP')) return 'violet';
  return 'warn'; // MOM
}

export function chipTone(kind: string): ChipTone {
  switch (kind) {
    case 'deal':
      return 'violet';
    case 'hi':
      return 'positive';
    case 'risk':
    case 'pledge':
      return 'negative';
    case 'band':
    case 'ex_date':
      return 'warn';
    default:
      return 'neutral';
  }
}

/** A tiny sparkline series of a screener's daily count (last n sessions). */
export function countSeries(info: CountInfo | undefined, n = 60): number[] {
  return (info?.series ?? []).slice(-n).map((p) => p[1]);
}

export function boardQuery(s: SetupsState) {
  const rn = Number(s.rn);
  return {
    template: s.tpl === 'sma' ? 'sma' : 'ema',
    volume_mode: s.vg === 'avg20d' ? 'avg20d' : 'day',
    results_n: Number.isFinite(rn) && rn >= 1 && rn <= 60 ? Math.round(rn) : 10,
    limit: 5000,
  } as const;
}

/** Row highlight: results within N sessions (whole row, spec Round 4). */
export function rowHighlight(r: SetupBoardRow): string | undefined {
  return r.results_soon ? 'bg-warn/10' : undefined;
}
