/**
 * Deals tab data: types for /api/v2/deals/tab/* and the cross-tab feeds, plus one query hook.
 *
 * Row types are the generated response models (api/types). meta.context stays free-form on the
 * server, so the per-view context shapes are typed here. The hook mirrors useApiQuery (as_of from
 * the URL, same key shape, same retry policy) but takes a plain path and a context type.
 */
import { keepPreviousData, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { API_BASE, ApiError, buildQuery, toEnvelope, type QueryValue } from '../../api/client';
import type {
  DealCandle,
  DealEarlier,
  DealFlagRow,
  DealGroupRow,
  DealHistoryRow,
  DealHousePosition,
  DealHouseRow,
  DealMarker,
  DealParty,
  DealSpreadItem,
  DealStockDetail,
  DealTabRow,
  DealTelegramRow,
  Envelope,
  EnvelopeMeta,
} from '../../api/types';
import { useAsOf } from '../../shell/urlState';

export type Verdict = DealTabRow['verdict'];
export type Side = NonNullable<DealTabRow['side']>;
export type EventType = DealTabRow['event_type'];
export type Grade = DealParty['grade'];
export type PatternKey = DealHistoryRow['pattern'];

// Row shapes are generated from the server's response models (App/api/v2/models_deals.py -> types.gen.ts).
export type Party = DealParty;
export type EarlierDeal = DealEarlier;
export type DealRow = DealTabRow;
export type HistoryRow = DealHistoryRow;
export type SpreadItem = DealSpreadItem;
export type HouseRow = DealHouseRow;
export type GroupRow = DealGroupRow;
export type Candle = DealCandle;
export type Marker = DealMarker;
export type StockDetail = DealStockDetail;
export type HousePosition = DealHousePosition;
export type TelegramRow = DealTelegramRow;
export type FlagRow = DealFlagRow;

export interface FundGroupRow {
  industry: string;
  houses: number;
  fii_cr: number;
  dii_cr: number;
  symbols: string[];
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
