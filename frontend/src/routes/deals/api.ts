/**
 * Deals tab data: types for /api/v2/deals/tab/* and the cross-tab feeds, plus one query hook.
 *
 * The endpoints return free-form rows (no response_model), so the shapes live here, next to the
 * tab. The hook mirrors useApiQuery (as_of from the URL, same key shape, same retry policy) but
 * takes a plain path so it does not depend on the generated EndpointMap.
 */
import { keepPreviousData, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { API_BASE, ApiError, buildQuery, toEnvelope, type QueryValue } from '../../api/client';
import type { Envelope, EnvelopeMeta } from '../../api/types';
import { useAsOf } from '../../shell/urlState';

export type Verdict = 'confirm' | 'watch' | 'place' | 'absorbed' | 'supply' | 'none' | 'churn' | 'avoid' | 'ignore';
export type Side = 'B' | 'S' | 'P' | 'T' | 'C';
export type EventType = 'fresh' | 'accumulate' | 'placement' | 'distribute' | 'churn' | 'transfer_interse';
export type Grade = 'good' | 'mixed' | 'poor' | 'ungraded';
export type PatternKey = 'repeat_buy' | 'single_buy' | 'selling_only' | 'mixed' | 'churn_only' | 'transfers_only';

export interface Party {
  name: string;
  house: string;
  buyer_class: string;
  value_cr: number;
  grade: Grade;
  record_n: number;
}

export interface EarlierDeal {
  deal_date: string;
  event_type: EventType;
  side: Side | null;
  net_cr: number;
  deal_price: number | null;
  verdict?: Verdict;
}

export interface DealRow {
  symbol: string;
  name: string;
  deal_date: string;
  sessions_since: number;
  event_type: EventType;
  side: Side | null;
  event_label: string;
  verdict: Verdict;
  verdict_title: string;
  why: string;
  next_action: string;
  net_cr: number;
  bought_cr: number;
  gross_cr: number | null;
  prop_cr: number | null;
  deal_price: number | null;
  close: number;
  vs_deal_pct: number | null;
  status: string | null;
  strong_chart: boolean;
  rs: number | null;
  from_high_pct: number | null;
  month_pct: number | null;
  rvol: number | null;
  mcap_cr: number | null;
  industry: string | null;
  sector: string | null;
  buyers: Party[];
  sellers: Party[];
  chips: string[];
  earlier?: EarlierDeal[];
}

export interface HistoryRow {
  symbol: string;
  industry: string | null;
  pattern: PatternKey;
  pattern_label: string;
  buy_sessions: number;
  sell_sessions: number;
  churn_sessions: number;
  net_cr: number;
  prop_cr: number;
  avg_deal_price: number | null;
  close: number;
  vs_deal_pct: number | null;
  cells: (Side | null)[];
}

export interface SpreadItem {
  industry: string;
  value_cr: number;
  share_pct: number;
  symbols: string[];
}

export interface HouseRow {
  house: string;
  name: string;
  buyer_class: string;
  bought_cr: number | null;
  symbols: string[];
  grade: Grade;
  record_n: number;
  record_avg_pct: number | null;
  record_beat_pct: number | null;
  spread: SpreadItem[];
}

export interface FundGroupRow {
  industry: string;
  houses: number;
  fii_cr: number;
  dii_cr: number;
  symbols: string[];
}

export interface GroupRow {
  industry: string;
  sector: string | null;
  buying_names: number;
  selling_names: number;
  flow_cr: number;
  symbols: string[];
  three_plus_buyers: boolean;
}

export interface Candle {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
}

export interface Marker {
  date: string;
  side: Side | null;
  event_type: EventType;
  price: number | null;
  net_cr: number | null;
  gross_cr: number | null;
}

export interface StockDetail {
  symbol: string;
  deal: DealRow | null;
  candles: Candle[];
  markers: Marker[];
  price_lines: Marker[];
}

export interface HousePosition {
  symbol: string;
  deal_date: string;
  bought_cr: number | null;
  deal_price: number | null;
  buyer_class: string;
  entry_date: string | null;
  since_entry_pct: number | null;
  market_pct: number | null;
  vs_market_pct: number | null;
  verdict: Verdict | null;
  verdict_title: string | null;
  status: string | null;
}

export interface ClassEvidence {
  buyer_class: string;
  n: number;
  vs_market_pct: number;
  beat_pct: number;
}

/** meta.context of each view (all optional: the server may answer `unavailable`). */
export interface TodayContext {
  deal_session?: string;
  skipped?: { transfer: number; churn: number; small: number };
  above50_pct?: number | null;
  summary?: { confirms: number; placements: number; supply: number; avoid: number; noise: number };
  price_gap?: { from: string; to: string } | null;
}
export interface WatchContext {
  sessions?: string[];
  filter_counts?: Record<string, number>;
}
export interface HistoryContext {
  sessions?: string[];
  pattern_counts?: Record<PatternKey, number>;
  patterns?: { key: PatternKey; label: string; note: string }[];
  total?: number;
}
export interface HousesContext {
  class_evidence?: ClassEvidence[];
  fund_groups?: FundGroupRow[];
  sessions?: string[];
  graded_houses?: number;
  finished_bets?: number;
  first_deal?: string;
  record_note?: string;
}
export interface HouseContext {
  house?: HouseRow;
  advice?: string;
}

type Meta<C> = EnvelopeMeta & { context?: C | null };

export async function fetchDeals<Row, C>(path: string, query: Record<string, QueryValue>, signal?: AbortSignal): Promise<Envelope<Row, Meta<C>>> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/${path}${buildQuery(query)}`, { signal, headers: { Accept: 'application/json' } });
  } catch (e) {
    if ((e as { name?: string })?.name === 'AbortError') throw new ApiError({ kind: 'aborted', status: 0, path, message: 'Request aborted' });
    throw new ApiError({ kind: 'network', status: 0, path, message: 'API unreachable' });
  }
  const text = await res.text().catch(() => '');
  let json: unknown = undefined;
  try {
    json = text ? JSON.parse(text) : undefined;
  } catch {
    json = text;
  }
  if (!res.ok) {
    const detail = typeof json === 'object' && json !== null && 'detail' in json ? String((json as { detail: unknown }).detail) : res.statusText;
    const kind = res.status === 404 ? 'not_found' : res.status === 503 ? 'busy' : res.status < 500 ? 'client' : 'server';
    throw new ApiError({ kind, status: res.status, path, message: detail || `HTTP ${res.status}`, body: json });
  }
  return toEnvelope<Row, Meta<C>>(json, path, res.status);
}

/** GET a Deals endpoint; as_of comes from the URL (time travel re-keys the query). */
export function useDeals<Row, C = Record<string, unknown>>(
  path: string,
  query: Record<string, QueryValue> = {},
  opts: { enabled?: boolean } = {},
): UseQueryResult<Envelope<Row, Meta<C>>> {
  const [asOf] = useAsOf();
  const q = { ...query, ...(asOf ? { as_of: asOf } : {}) };
  return useQuery({
    queryKey: ['v2', path, null, { ...query, as_of: asOf }],
    queryFn: ({ signal }) => fetchDeals<Row, C>(path, q, signal),
    enabled: opts.enabled ?? true,
    placeholderData: keepPreviousData,
    retry: (n, e) => n < 2 && !(e instanceof ApiError && (e.kind === 'not_found' || e.kind === 'client')),
  });
}
