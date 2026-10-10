/**
 * Sector Intel data hooks (/api/v2/sectors/*, App/api/v2/routes_sectors.py).
 * The endpoints return plain envelopes (no generated row schema), so row types live here.
 */
import { keepPreviousData, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { ApiError, API_BASE, buildQuery, toEnvelope, type QueryValue } from '../../api/client';
import type { Envelope, EnvelopeMeta } from '../../api/types';
import { useAsOf } from '../../shell/urlState';

export type SectorLevel = 'sector' | 'broad_industry' | 'industry';
export type BoardLevel = SectorLevel | 'index';
export type WindowKey = '1D' | '1W' | '2W' | '1M';
export type GroupState = 'Favour' | 'Neutral' | 'Caution';
export const WINDOWS: readonly WindowKey[] = ['1D', '1W', '2W', '1M'];
export const WINDOW_LABEL: Record<WindowKey, string> = { '1D': '1 day', '1W': '1 week', '2W': '2 weeks', '1M': '1 month' };

type PerWindow<K extends string> = { [P in `${K}_${WindowKey}`]?: number | null };

export type SectorRow = {
  id: string;
  level: SectorLevel;
  group_name: string;
  stocks: number;
  small: boolean;
  ranked: boolean;
  state: GroupState | null;
  state_reason: string | null;
  near: number | null;
  a50: number | null;
  leaders: string[];
  pct: Record<string, number | null>;
  deals_buy_10d: number | null;
  deals_sell_10d: number | null;
  deals_flow_10d_cr: number | null;
} & PerWindow<'nh' | 'ad' | 'upd' | 'tov' | 'sh' | 'tox' | 'shd' | 'rx' | 'ret' | 'nearchg' | 'score'>;

export type IndexRow = {
  id: string;
  group_name: string;
  category: string | null;
  close: number | null;
  sessions: number;
  stale: boolean;
  above_20ema: boolean | null;
} & PerWindow<'ret' | 'rs'>;

export interface Mood {
  score: number | null;
  label: string | null;
  dir: string | null;
  a10chg: number | null;
  a10?: number | null;
  spark: (number | null)[];
  note?: string;
}

export interface Reliability {
  ic: number | null;
  top: number | null;
  bot: number | null;
  days: number;
  from: string | null;
  to: string | null;
  working: boolean | null;
}

export interface Evidence {
  period: string;
  dir: Record<string, { ic: number; top: number; bot: number }>;
  lag: { working: number; not: number };
}

export interface BoardContext {
  level: BoardLevel;
  level_label: string;
  windows: WindowKey[];
  gap_windows: WindowKey[];
  last_clean_session?: string | null;
  deals_reason?: string | null;
  mood?: Mood;
  reliability?: Reliability;
  verdict?: string;
  what_to_do?: string;
  evidence?: Evidence;
  evidence_now?: { ic: number; top: number; bot: number } | null;
}

export interface LinePt {
  time: string;
  value: number | null;
}

export interface ChartRow {
  id: string;
  group_name: string;
  level?: SectorLevel;
  bars: { time: string; open: number; high: number; low: number; close: number }[];
  rs: LinePt[];
  near: LinePt[];
  reason?: string;
}

export interface MemberRow {
  symbol: string;
  security_name: string | null;
  market_cap_cr: number | null;
  close: number | null;
  rs_percentile: number | null;
  change_1d_pct: number | null;
  return_1m_pct: number | null;
  from_52w_high_pct: number | null;
  near_52w_high: boolean;
  above_50ema: boolean | null;
  new_high_1w: boolean | null;
  deal_flow_10d_cr: number | null;
  deal_last_event: string | null;
}

export interface HeatRow {
  symbol: string;
  security_name: string | null;
  sector: string | null;
  broad_industry: string | null;
  industry: string | null;
  mc: number | null;
  c: number | null;
  r1: number | null;
  r5: number | null;
  r21: number | null;
  t: number | null;
  t20: number | null;
  v: number | null;
  dv: number | null;
  co: number | null;
  gap: number | null;
  r63: number | null;
  r126: number | null;
  r252: number | null;
  rvol: number | null;
  vol: number | null;
  dp: number | null;
  a52: number | null;
  rs: number | null;
}

export interface ReadingsStudyRow {
  reading: string;
  best_n: string;
  ic_sector: number;
  ic_broad_industry: number;
  ic_industry: number;
  top: number;
  bot: number;
}

export interface MoodStudyRow {
  condition: string;
  ic_sector: number;
  ic_broad_industry: number;
  ic_industry: number;
  top: number;
  bot: number;
}

export type SectorMeta<C = Record<string, unknown>> = EnvelopeMeta & { context?: C };

async function getEnvelope<Row, C>(
  path: string,
  query: Record<string, QueryValue>,
  signal?: AbortSignal,
): Promise<Envelope<Row, SectorMeta<C>>> {
  const url = `${API_BASE}/${path}${buildQuery(query)}`;
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: 'application/json' }, signal });
  } catch (e) {
    if ((e as { name?: string })?.name === 'AbortError')
      throw new ApiError({ kind: 'aborted', status: 0, path, message: 'Request aborted' });
    throw new ApiError({ kind: 'network', status: 0, path, message: 'API unreachable' });
  }
  const text = await res.text().catch(() => '');
  let json: unknown;
  try {
    json = text ? JSON.parse(text) : undefined;
  } catch {
    json = text;
  }
  if (!res.ok) {
    const detail = typeof json === 'object' && json && 'detail' in json ? String((json as { detail: unknown }).detail) : res.statusText;
    const kind = res.status === 503 ? 'busy' : res.status === 404 ? 'not_found' : res.status < 500 ? 'client' : 'server';
    throw new ApiError({ kind, status: res.status, path, message: detail || `HTTP ${res.status}`, body: json });
  }
  return toEnvelope<Row, SectorMeta<C>>(json, path, res.status);
}

/** GET /api/v2/sectors/<path> with the URL as_of (time travel), cached by TanStack Query. */
export function useSectors<Row, C = Record<string, unknown>>(
  path: 'board' | 'context' | 'charts' | 'members' | 'heatmap' | 'group-studies',
  query: Record<string, QueryValue> = {},
  options: { enabled?: boolean; keepPrevious?: boolean } = {},
): UseQueryResult<Envelope<Row, SectorMeta<C>>> {
  const [asOf] = useAsOf();
  const q = { ...query, ...(asOf ? { as_of: asOf } : {}) };
  return useQuery({
    queryKey: ['v2', `sectors/${path}`, q],
    queryFn: ({ signal }) => getEnvelope<Row, C>(`sectors/${path}`, q, signal),
    enabled: options.enabled ?? true,
    staleTime: 5 * 60_000,
    ...(options.keepPrevious ? { placeholderData: keepPreviousData } : {}),
  });
}
