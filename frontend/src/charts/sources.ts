/**
 * Charts tab sources (spec 7.8): any list in the app becomes a grid of charts.
 * Source ids live in the URL (?src=): queue:<name>|queue:all, screener:<preset>|
 * screener:custom, group:<level>:<name>, deals:buy|deals:sell, research:pre-move,
 * watchlist, list (explicit ?syms=). Pure — no React.
 */
import type { BarRow, DealSessionRow, MemberRow, QueueRow, ScreenerRow } from '../api/types';
import { isNum } from '../lib/fmt';
import type { OHLCBar } from '../lib/indicators';

export type SourceKind = 'queue' | 'screener' | 'group' | 'deals' | 'research' | 'watchlist' | 'list';

export interface ParsedSource {
  kind: SourceKind;
  /** queue name / preset id / level / buy|sell / research key. */
  key: string;
  /** Group name (group sources). */
  name?: string;
}

export const QUEUE_LABELS: Record<string, string> = {
  darvas_squeeze: 'Darvas Squeeze',
  darvas_10ema: 'Darvas 10 EMA',
  vcp: 'VCP',
};
export const QUEUE_NAMES = Object.keys(QUEUE_LABELS) as ('darvas_squeeze' | 'darvas_10ema' | 'vcp')[];
export const LEVEL_LABELS: Record<string, string> = {
  broad_sector: 'Broad Sector',
  sector: 'Sector',
  broad_industry: 'Broad Industry',
  industry: 'Industry',
};

export function parseSource(src: string | null | undefined): ParsedSource | null {
  if (!src) return null;
  const [kind, ...rest] = src.split(':');
  const key = rest[0] ?? '';
  switch (kind) {
    case 'queue':
      return key === 'all' || key in QUEUE_LABELS ? { kind, key } : null;
    case 'screener':
      return /^[a-z0-9_]{1,40}$/.test(key) ? { kind, key } : null;
    case 'group': {
      const name = rest.slice(1).join(':');
      return key in LEVEL_LABELS && name ? { kind, key, name } : null;
    }
    case 'deals':
      return key === 'buy' || key === 'sell' ? { kind, key } : null;
    case 'research':
      return key === 'pre-move' ? { kind, key } : null;
    case 'watchlist':
      return { kind, key: '' };
    case 'list':
      return { kind, key: '' };
    default:
      return null;
  }
}

export function sourceId(p: ParsedSource): string {
  switch (p.kind) {
    case 'group':
      return `group:${p.key}:${p.name ?? ''}`;
    case 'watchlist':
    case 'list':
      return p.kind;
    default:
      return `${p.kind}:${p.key}`;
  }
}

/** One stock in the grid, normalised across sources. NULL stays NULL. */
export interface ChartItem {
  symbol: string;
  name?: string | null;
  industry?: string | null;
  close?: number | null;
  change_1d_pct?: number | null;
  rs_percentile?: number | null;
  rs_delta_5?: number | null;
  distance_to_trigger_pct?: number | null;
  setup_age_sessions?: number | null;
  trigger_price?: number | null;
  stop_price?: number | null;
  darvas_box_top?: number | null;
  darvas_box_bottom?: number | null;
  net_cr?: number | null;
  market_cap_cr?: number | null;
  /** Served data_warning: an unexplained price gap inside a metric window (those metrics are NULL). */
  data_warning?: string | null;
  /** Short tags shown on the tile, e.g. queue labels for queue:all. */
  tags: string[];
}

export function fromQueueRow(r: QueueRow): ChartItem | null {
  if (!r.symbol) return null;
  return {
    symbol: r.symbol,
    name: r.security_name,
    industry: r.industry,
    close: r.close,
    change_1d_pct: r.change_1d_pct,
    rs_percentile: r.rs_percentile,
    rs_delta_5: r.rs_delta_5,
    distance_to_trigger_pct: r.distance_to_trigger_pct,
    setup_age_sessions: r.setup_age_sessions,
    trigger_price: r.trigger_price,
    stop_price: r.stop_price,
    darvas_box_top: r.darvas_box_top,
    darvas_box_bottom: r.darvas_box_bottom,
    market_cap_cr: r.market_cap_cr,
    data_warning: r.data_warning ?? null,
    tags: [QUEUE_LABELS[r.queue] ?? r.queue],
  };
}

export function fromScreenerRow(r: ScreenerRow & Partial<QueueRow>): ChartItem | null {
  if (!r.symbol) return null;
  return {
    symbol: r.symbol,
    name: r.security_name,
    industry: r.industry,
    close: r.close,
    change_1d_pct: r.change_1d_pct,
    rs_percentile: r.rs_percentile,
    rs_delta_5: r.rs_delta_5,
    distance_to_trigger_pct: r.distance_to_trigger_pct ?? null,
    setup_age_sessions: r.setup_age_sessions ?? null,
    trigger_price: r.trigger_price ?? null,
    stop_price: r.stop_price ?? null,
    darvas_box_top: r.darvas_box_top ?? null,
    darvas_box_bottom: r.darvas_box_bottom ?? null,
    market_cap_cr: r.market_cap_cr,
    data_warning: r.data_warning ?? null,
    tags: r.is_new ? ['NEW'] : [],
  };
}

export function fromMemberRow(r: MemberRow): ChartItem | null {
  if (!r.symbol) return null;
  return {
    symbol: r.symbol,
    name: r.security_name,
    industry: r.industry,
    close: r.close,
    change_1d_pct: r.change_1d_pct,
    rs_percentile: r.rs_percentile,
    rs_delta_5: r.rs_delta_5,
    market_cap_cr: r.market_cap_cr,
    data_warning: r.data_warning ?? null,
    tags: (r.active_setups ?? []).map((s) => QUEUE_LABELS[s] ?? s),
  };
}

export function fromDealRow(r: DealSessionRow): ChartItem | null {
  if (!r.symbol) return null;
  return {
    symbol: r.symbol,
    name: r.security_name,
    industry: r.industry,
    close: r.close,
    rs_percentile: r.rs_percentile,
    net_cr: r.net_cr,
    market_cap_cr: r.market_cap_cr,
    tags: r.event_type ? [r.event_type] : [],
  };
}

export function fromSymbol(symbol: string): ChartItem {
  return { symbol, tags: [] };
}

/** De-duplicate by symbol keeping first-seen order; tags from later lists are merged. */
export function mergeItems(lists: readonly (readonly ChartItem[])[]): ChartItem[] {
  const out = new Map<string, ChartItem>();
  for (const list of lists) {
    for (const it of list) {
      const prev = out.get(it.symbol);
      if (!prev) out.set(it.symbol, { ...it, tags: [...it.tags] });
      else prev.tags = Array.from(new Set([...prev.tags, ...it.tags]));
    }
  }
  return [...out.values()];
}

export const SORTS = [
  { id: 'source', label: 'Source order' },
  { id: 'rs', label: 'Strength rank' },
  { id: 'rs_delta', label: 'Strength Δ5' },
  { id: 'distance', label: 'Distance to trigger' },
  { id: 'age', label: 'Setup age (newest)' },
  { id: 'change', label: '1D %' },
  { id: 'net', label: 'Deal net ₹' },
  { id: 'mcap', label: 'Market cap' },
  { id: 'symbol', label: 'Symbol A–Z' },
] as const;
export type SortId = (typeof SORTS)[number]['id'];

const SORT_KEY: Record<Exclude<SortId, 'source' | 'symbol'>, { key: keyof ChartItem; desc: boolean; abs?: boolean }> = {
  rs: { key: 'rs_percentile', desc: true },
  rs_delta: { key: 'rs_delta_5', desc: true },
  distance: { key: 'distance_to_trigger_pct', desc: false, abs: true },
  age: { key: 'setup_age_sessions', desc: false },
  change: { key: 'change_1d_pct', desc: true },
  net: { key: 'net_cr', desc: true },
  mcap: { key: 'market_cap_cr', desc: true },
};

/** Stable sort; NULLs always last. */
export function sortItems(items: readonly ChartItem[], sort: string): ChartItem[] {
  if (sort === 'symbol') return [...items].sort((a, b) => a.symbol.localeCompare(b.symbol));
  const spec = SORT_KEY[sort as keyof typeof SORT_KEY];
  if (!spec) return [...items];
  const val = (it: ChartItem) => {
    const v = it[spec.key];
    return isNum(v) ? (spec.abs ? Math.abs(v) : v) : null;
  };
  return items
    .map((it, i) => ({ it, i, v: val(it) }))
    .sort((a, b) => {
      if (a.v === null && b.v === null) return a.i - b.i;
      if (a.v === null) return 1;
      if (b.v === null) return -1;
      const d = spec.desc ? b.v - a.v : a.v - b.v;
      return d !== 0 ? d : a.i - b.i;
    })
    .map((x) => x.it);
}

/** 1 / 2 / 8 / 12 restored from the old Tiles window (1, 2, 2x2, 2x3, 2x4, 3x3, 3x4). */
export const TILE_COUNTS = [1, 2, 4, 6, 8, 9, 12] as const;

export function pageCount(total: number, perPage: number): number {
  return Math.max(1, Math.ceil(total / Math.max(1, perPage)));
}

export function clampPage(page: number, total: number, perPage: number): number {
  const n = pageCount(total, perPage);
  return Math.min(Math.max(0, Number.isFinite(page) ? Math.floor(page) : 0), n - 1);
}

export function pageSlice<T>(items: readonly T[], page: number, perPage: number): T[] {
  const p = clampPage(page, items.length, perPage);
  return items.slice(p * perPage, p * perPage + perPage);
}

/** Grid columns for a tile count (2 -> 2x1, 4 -> 2x2, 6 -> 3x2, 8 -> 4x2, 9 -> 3x3, 12 -> 4x3). */
export function gridShape(n: number): { cols: number; rows: number } {
  if (n <= 1) return { cols: 1, rows: 1 };
  if (n <= 2) return { cols: 2, rows: 1 };
  if (n <= 4) return { cols: 2, rows: 2 };
  if (n <= 6) return { cols: 3, rows: 2 };
  if (n <= 8) return { cols: 4, rows: 2 };
  if (n <= 9) return { cols: 3, rows: 3 };
  return { cols: 4, rows: 3 };
}

/**
 * Relative performance over the last `sessions` points: stock return minus
 * benchmark return, in % points. NULL when either series lacks data.
 */
export function relativePerformance(
  rows: readonly { close?: number | null; bench?: number | null }[],
  sessions: number,
): { stock: number | null; bench: number | null; excess: number | null } {
  const valid = rows.filter((r) => isNum(r.close) && isNum(r.bench) && (r.close as number) > 0 && (r.bench as number) > 0);
  if (valid.length < 2) return { stock: null, bench: null, excess: null };
  const end = valid[valid.length - 1];
  const start = valid[Math.max(0, valid.length - 1 - sessions)];
  if (start === end) return { stock: null, bench: null, excess: null };
  const stock = ((end.close as number) / (start.close as number) - 1) * 100;
  const bench = ((end.bench as number) / (start.bench as number) - 1) * 100;
  return { stock, bench, excess: stock - bench };
}

/** href for the Charts tab showing a source, keeping as_of. */
export function chartsHref(currentSearch: string, src: string): string {
  const cur = new URLSearchParams(currentSearch);
  const next = new URLSearchParams();
  const asOf = cur.get('as_of');
  if (asOf) next.set('as_of', asOf);
  const sym = cur.get('sym');
  if (sym) next.set('sym', sym);
  next.set('src', src);
  next.set('page', '1');
  return `/charts?${next.toString()}`;
}

/** Served bars -> chart bars; rows missing a date or any OHLC value are dropped, never filled. */
export function barsToOHLC(rows: readonly BarRow[]): OHLCBar[] {
  const out: OHLCBar[] = [];
  for (const r of rows) {
    if (!r.trade_date || r.open == null || r.high == null || r.low == null || r.close == null) continue;
    out.push({
      time: r.trade_date,
      open: r.open,
      high: r.high,
      low: r.low,
      close: r.close,
      volume: r.volume ?? null,
      delivery_pct: r.delivery_pct ?? null,
    });
  }
  return out;
}
