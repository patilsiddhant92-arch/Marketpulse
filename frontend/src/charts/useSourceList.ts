/**
 * Resolve a Charts source into a normalised symbol list (spec 7.8).
 * Every source is an existing v2 endpoint; hooks are unconditional and gated
 * by `enabled`, so switching sources never violates the rules of hooks.
 */
import { useMemo } from 'react';
import { useApiQuery } from '../api/query';
import type { EnvelopeMeta } from '../api/types';
import { loadLastRun } from '../screener/model';
import {
  LEVEL_LABELS,
  QUEUE_LABELS,
  fromDealRow,
  fromMemberRow,
  fromQueueRow,
  fromScreenerRow,
  fromSymbol,
  mergeItems,
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

  const deals = useApiQuery('deals/session', { query: { limit: 5000 } }, { enabled: kind === 'deals' });
  const pre = useApiQuery('research/pre-move', { query: { limit: 5000 } }, { enabled: kind === 'research' });
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
          note: 'Bulk / block deals on the session, sorted by |net ₹|. Accumulate / Fresh / Distribute labels arrive with deal_session_net.',
          refetch: () => void deals.refetch(),
        };
      }
      case 'research': {
        const d = pre.data;
        return {
          items: (d?.rows ?? [])
            .map((r) => ((r as { symbol?: string | null }).symbol ? fromSymbol((r as { symbol: string }).symbol) : null))
            .filter(nonNull),
          total: d?.total ?? null,
          label: 'Research · pre-move watch',
          asOf: d?.as_of ?? null,
          loading: pre.isLoading,
          error: pre.error,
          status: d?.meta.status ?? null,
          reason: d?.meta.reason ?? null,
          note: null,
          refetch: () => void pre.refetch(),
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
    }
  }, [src, q1, q2, q3, scr, grp, deals, pre, lastRun, watchlist, syms, presetLabel]);
}
