/**
 * Resolve a Charts source into a normalised symbol list (spec 7.8).
 * Every source is an existing v2 endpoint; hooks are unconditional and gated
 * by `enabled`, so switching sources never violates the rules of hooks.
 */
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import type { QueryValue } from '../api/client';
import { apiQueryKey, useApiQuery } from '../api/query';
import { getRawEnvelope } from '../api/raw';
import type { EnvelopeMeta } from '../api/types';
import { loadLastRun } from '../screener/model';
import { useAsOf } from '../shell/urlState';
import {
  DEALS_LABELS,
  LEVEL_LABELS,
  PULSE_MOVER_LABELS,
  QUEUE_LABELS,
  SETUPS_LABELS,
  fromDealRow,
  fromDealTabRow,
  fromMoverRow,
  fromSetupRow,
  houseBuysList,
  setupsViewRows,
  type DealTabLike,
  type MoverLike,
  fromMemberRow,
  fromQueueRow,
  fromScreenerRow,
  fromSymbol,
  mergeItems,
  peersList,
  type ChartItem,
  type ParsedSource,
} from './sources';

export interface SourceList {
  items: ChartItem[];
  /** Server total (before paging) when the source is server-backed. */
  total: number | null;
  label: string;
  asOf: string | null;
  loading: boolean;
  error: unknown;
  status: EnvelopeMeta['status'] | null;
  reason: string | null;
  note: string | null;
  refetch: () => void;
}

const nonNull = <T>(x: T | null): x is T => x !== null;

/** Free-form endpoints (no generated row schema, e.g. /deals/tab/*): same key shape and as_of as useApiQuery. */
function useRawList<Row>(path: string, query: Record<string, QueryValue>, enabled: boolean) {
  const [asOf] = useAsOf();
  return useQuery({
    queryKey: apiQueryKey(path, null, query, asOf),
    queryFn: ({ signal }) => getRawEnvelope<Row>(path, { ...query, ...(asOf ? { as_of: asOf } : {}) }, signal),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useSourceList(
  src: ParsedSource | null,
  opts: { watchlist: string[]; syms: string[]; presetLabel?: (id: string) => string | undefined },
): SourceList {
  const kind = src?.kind;
  const key = src?.key ?? '';
  const isQueue = kind === 'queue';
  const qEnabled = (name: string) => isQueue && (key === 'all' || key === name);
  const q1 = useApiQuery(
    'desk/queue/{name}',
    { params: { name: 'darvas_squeeze' }, query: { tf: 'D', limit: 5000 } },
    { enabled: qEnabled('darvas_squeeze') },
  );
  const q2 = useApiQuery(
    'desk/queue/{name}',
    { params: { name: 'darvas_10ema' }, query: { tf: 'D', limit: 5000 } },
    { enabled: qEnabled('darvas_10ema') },
  );
  const q3 = useApiQuery('desk/queue/{name}', { params: { name: 'vcp' }, query: { tf: 'D', limit: 5000 } }, { enabled: qEnabled('vcp') });

  const lastRun = useMemo(() => (kind === 'screener' && key === 'custom' ? loadLastRun() : null), [kind, key]);
  const screenerQuery = kind === 'screener' ? (key === 'custom' ? lastRun?.query : { preset: key, limit: 5000 }) : undefined;
  const scr = useApiQuery('screener/run', { query: (screenerQuery ?? {}) as never }, { enabled: !!screenerQuery });

  const groupId = kind === 'group' ? `${key}:${src?.name ?? ''}` : '';
  const grp = useApiQuery(
    'groups/{group_id}/members',
    { params: { group_id: groupId }, query: { floor: '1000', limit: 5000 } },
    { enabled: kind === 'group' },
  );

  const isDealsSession = kind === 'deals' && (key === 'buy' || key === 'sell');
  const deals = useApiQuery('deals/session', { query: { limit: 5000 } }, { enabled: isDealsSession });
  const movers = useApiQuery(
    'pulse/movers',
    { query: { kind: (kind === 'pulse' ? key : 'gainers') as 'gainers' } },
    { enabled: kind === 'pulse' },
  );
  const dealsWatch = useRawList<DealTabLike>('deals/tab/watch', { limit: 5000 }, kind === 'deals' && key === 'watch');
  const dealsHistory = useRawList<DealTabLike>('deals/tab/history', { sessions: 10, limit: 5000 }, kind === 'deals' && key === 'history');
  const dealsHouses = useRawList<{ house?: string | null; symbols?: string[] | null }>('deals/tab/houses', { limit: 5000 }, kind === 'deals' && key === 'houses');
  const houseName = kind === 'deals' && key === 'house' ? (src?.name ?? '') : '';
  const dealsHouse = useRawList<DealTabLike>(`deals/tab/house/${encodeURIComponent(houseName || '_')}`, {}, !!houseName);
  const isSetupsBoard = kind === 'setups' && key !== 'near' && key !== 'dropped';
  const setupsBoard = useApiQuery('setups/board', { query: { limit: 5000 } as never }, { enabled: isSetupsBoard });
  const setupsNear = useApiQuery('setups/near-miss', { query: { limit: 500 } as never }, { enabled: kind === 'setups' && key === 'near' });
  const setupsDropped = useApiQuery('setups/dropped', { query: {} as never }, { enabled: kind === 'setups' && key === 'dropped' });
  const peers = useApiQuery(
    'stock/{sym}/peers',
    { params: { sym: kind === 'peers' && key ? key : '_' }, query: { limit: 500 } },
    { enabled: kind === 'peers' && !!key },
  );
  const { watchlist, syms, presetLabel } = opts;

  return useMemo<SourceList>(() => {
    const base = { total: null, asOf: null, loading: false, error: null, status: null, reason: null, note: null, refetch: () => {} };
    if (!src) return { ...base, items: [], label: 'Choose a source' };
    switch (src.kind) {
      case 'queue': {
        const qs = src.key === 'all' ? [q1, q2, q3] : [src.key === 'darvas_squeeze' ? q1 : src.key === 'darvas_10ema' ? q2 : q3];
        const items = mergeItems(qs.map((q) => (q.data?.rows ?? []).map(fromQueueRow).filter(nonNull)));
        const first = qs.find((q) => q.data)?.data;
        return {
          items,
          total: items.length,
          label: src.key === 'all' ? 'Desk · all queues' : `Desk · ${QUEUE_LABELS[src.key]}`,
          asOf: first?.as_of ?? null,
          loading: qs.some((q) => q.isLoading),
          error: qs.find((q) => q.error)?.error ?? null,
          status: first?.meta.status ?? null,
          reason: first?.meta.reason ?? null,
          note: src.key === 'all' ? 'A stock in several queues appears once, tagged with each.' : null,
          refetch: () => qs.forEach((q) => void q.refetch()),
        };
      }
      case 'screener': {
        if (src.key === 'custom' && !lastRun) {
          return {
            ...base,
            items: [],
            label: 'Screener · last custom run',
            note: 'No custom screener run saved yet — edit rules or floors in the Screener first.',
          };
        }
        const d = scr.data;
        const label = src.key === 'custom' ? `Screener · ${lastRun?.label ?? 'custom'}` : `Screener · ${presetLabel?.(src.key) ?? src.key}`;
        return {
          items: (d?.rows ?? []).map((r) => fromScreenerRow(r)).filter(nonNull),
          total: d?.total ?? null,
          label,
          asOf: d?.as_of ?? null,
          loading: scr.isLoading,
          error: scr.error,
          status: d?.meta.status ?? null,
          reason: d?.meta.reason ?? null,
          note: src.key === 'custom' ? null : 'Preset with default floors (≥ ₹1,000 Cr, price ≥ ₹15).',
          refetch: () => void scr.refetch(),
        };
      }
      case 'group': {
        const d = grp.data;
        return {
          items: (d?.rows ?? []).map(fromMemberRow).filter(nonNull),
          total: d?.total ?? null,
          label: `${LEVEL_LABELS[src.key]} · ${src.name}`,
          asOf: d?.as_of ?? null,
          loading: grp.isLoading,
          error: grp.error,
          status: d?.meta.status ?? null,
          reason: d?.meta.reason ?? null,
          note: 'Members with market cap ≥ ₹1,000 Cr.',
          refetch: () => void grp.refetch(),
        };
      }
      case 'deals': {
        if (src.key === 'buy' || src.key === 'sell') {
          const d = deals.data;
          const rows = (d?.rows ?? []).filter((r) => (src.key === 'buy' ? (r.net_cr ?? 0) > 0 : (r.net_cr ?? 0) < 0));
          rows.sort((a, b) => Math.abs(b.net_cr ?? 0) - Math.abs(a.net_cr ?? 0));
          return {
            items: rows.map(fromDealRow).filter(nonNull),
            total: rows.length,
            label: src.key === 'buy' ? 'Deals · net buying' : 'Deals · net selling',
            asOf: d?.as_of ?? null,
            loading: deals.isLoading,
            error: deals.error,
            status: d?.meta.status ?? null,
            reason: d?.meta.reason ?? null,
            note: 'Bulk / block deals on the session, sorted by |net ₹|.',
            refetch: () => void deals.refetch(),
          };
        }
        const q = src.key === 'watch' ? dealsWatch : src.key === 'history' ? dealsHistory : src.key === 'houses' ? dealsHouses : dealsHouse;
        const d = q.data;
        const items =
          src.key === 'houses'
            ? houseBuysList((dealsHouses.data?.rows ?? []) as { house?: string | null; symbols?: string[] | null }[])
            : mergeItems([((d?.rows ?? []) as DealTabLike[]).map((r) => fromDealTabRow(r)).filter(nonNull)]);
        const notes: Record<string, string> = {
          watch: 'Stocks with a deal in the last 10 deal sessions (no churn / transfers), as on the Deals tab.',
          history: 'Every stock ≥ ₹1,000 Cr with a deal in the last 10 deal sessions, tagged with its pattern.',
          houses: 'Every stock a house bought in the last 10 deal sessions, tagged with the houses.',
          house: "This house's buys over the last 20 deal sessions.",
        };
        return {
          items,
          total: items.length,
          label: src.key === 'house' ? `Deals · ${src.name} buys` : `Deals · ${DEALS_LABELS[src.key]}`,
          asOf: d?.as_of ?? null,
          loading: q.isLoading,
          error: q.error,
          status: d?.meta.status ?? null,
          reason: d?.meta.reason ?? null,
          note: notes[src.key] ?? null,
          refetch: () => void q.refetch(),
        };
      }
      case 'pulse': {
        const d = movers.data;
        const items = ((d?.rows ?? []) as MoverLike[]).map(fromMoverRow).filter(nonNull);
        return {
          items,
          total: items.length,
          label: `Pulse · ${PULSE_MOVER_LABELS[src.key]}`,
          asOf: d?.as_of ?? null,
          loading: movers.isLoading,
          error: movers.error,
          status: d?.meta.status ?? null,
          reason: d?.meta.reason ?? null,
          note: 'Top 20 stocks that moved (≥ ₹1,000 Cr), as on Pulse.',
          refetch: () => void movers.refetch(),
        };
      }
      case 'setups': {
        if (src.key === 'near' || src.key === 'dropped') {
          const q = src.key === 'near' ? setupsNear : setupsDropped;
          const d = q.data;
          const rows = (d?.rows ?? []) as { symbol?: string | null; industry?: string | null; close?: number | null; gate?: string; screener_name?: string }[];
          const items = mergeItems([
            rows
              .filter((r) => !!r.symbol)
              .map((r) => ({ symbol: r.symbol as string, industry: r.industry ?? null, close: r.close ?? null, tags: [r.gate ?? r.screener_name ?? ''].filter(Boolean) })),
          ]);
          return {
            items,
            total: items.length,
            label: `Setups · ${SETUPS_LABELS[src.key]}`,
            asOf: d?.as_of ?? null,
            loading: q.isLoading,
            error: q.error,
            status: d?.meta.status ?? null,
            reason: d?.meta.reason ?? null,
            note: src.key === 'near' ? 'Darvas Squeeze near-miss: in the zone, exactly one strict gate failed.' : 'Stocks that left a screener since the previous session.',
            refetch: () => void q.refetch(),
          };
        }
        const d = setupsBoard.data;
        const items = setupsViewRows(d?.rows ?? [], src.key).map(fromSetupRow).filter(nonNull);
        return {
          items,
          total: items.length,
          label: `Setups · ${SETUPS_LABELS[src.key]}`,
          asOf: d?.as_of ?? null,
          loading: setupsBoard.isLoading,
          error: setupsBoard.error,
          status: d?.meta.status ?? null,
          reason: d?.meta.reason ?? null,
          note: 'Setups board with the default momentum template (EMA) and volume gate.',
          refetch: () => void setupsBoard.refetch(),
        };
      }
      case 'watchlist':
        return {
          ...base,
          items: watchlist.map(fromSymbol),
          total: watchlist.length,
          label: 'Watchlist',
          note: watchlist.length ? null : 'Watchlist is empty — star stocks (W) to add them.',
        };
      case 'list':
        return { ...base, items: syms.map(fromSymbol), total: syms.length, label: 'Selected symbols' };
      case 'peers': {
        const d = peers.data;
        const items = d ? peersList(d.rows, src.key) : [];
        return {
          items,
          total: items.length,
          label: `Peers of ${src.key}`,
          asOf: d?.as_of ?? null,
          loading: peers.isLoading,
          error: peers.error,
          status: d?.meta.status ?? null,
          reason: d?.meta.reason ?? null,
          note: 'Same industry, market cap ≥ ₹1,000 Cr, strongest first. The stock itself leads.',
          refetch: () => void peers.refetch(),
        };
      }
    }
  }, [src, q1, q2, q3, scr, grp, deals, movers, dealsWatch, dealsHistory, dealsHouses, dealsHouse, setupsBoard, setupsNear, setupsDropped, peers, lastRun, watchlist, syms, presetLabel]);
}
