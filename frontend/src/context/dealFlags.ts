/**
 * Cross-tab deal flags (GET /api/v2/deals/flags): which stocks had a bulk / block deal within the last 10 deal
 * sessions, with side and verdict. ONE request per as_of (every flagged symbol, a few hundred rows) feeds the deal
 * icon on every stock list in every tab, so no table has to thread a symbol list through. Pure helpers here; the
 * icon is ui/DealIcon.tsx. Re-exported from stockContext.ts (the cross-tab stock context).
 */
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { getRawEnvelope } from '../api/raw';
import { apiQueryKey } from '../api/query';
import type { ChipTone } from '../ui/Chip';
import { useAsOf } from '../shell/urlState';

export interface DealFlag {
  symbol: string;
  has_recent_deal: boolean;
  last_deal_date: string | null;
  deal_sessions_ago: number | null;
  side: 'B' | 'S' | 'P' | 'T' | 'C' | null;
  event_type: string | null;
  deal_sessions_in_window: number;
  verdict: string | null;
  verdict_title: string | null;
  deal_price: number | null;
  status: string | null;
  vs_deal_pct: number | null;
}

export type DealFlagMap = ReadonlyMap<string, DealFlag>;
const EMPTY: DealFlagMap = new Map();
export const DEAL_FLAGS_LIMIT = 5000;

export function dealFlagMap(rows: readonly DealFlag[] | undefined): DealFlagMap {
  if (!rows?.length) return EMPTY;
  const m = new Map<string, DealFlag>();
  for (const r of rows) if (r.has_recent_deal) m.set(r.symbol.toUpperCase(), r);
  return m;
}

/** Verdict colour (the Deals tab's verdict_colours); no verdict -> colour by side. */
const VERDICT_TONE: Record<string, ChipTone> = {
  confirm: 'positive',
  place: 'info',
  absorbed: 'accent',
  watch: 'warn',
  supply: 'warn',
  churn: 'neutral',
  ignore: 'neutral',
  none: 'neutral',
  avoid: 'negative',
};
const SIDE_TONE: Record<string, ChipTone> = { B: 'positive', S: 'negative', P: 'info', T: 'neutral', C: 'neutral' };
export const SIDE_LABEL: Record<string, string> = { B: 'net buy', S: 'net sell', P: 'placement', T: 'transfer', C: 'churn' };

export function dealTone(f: DealFlag): ChipTone {
  if (f.verdict && VERDICT_TONE[f.verdict]) return VERDICT_TONE[f.verdict];
  return f.side ? (SIDE_TONE[f.side] ?? 'neutral') : 'neutral';
}

export function dealTitle(f: DealFlag): string {
  const ago = f.deal_sessions_ago == null ? '' : f.deal_sessions_ago === 0 ? ' today' : ` ${f.deal_sessions_ago} deal session${f.deal_sessions_ago === 1 ? '' : 's'} ago`;
  const bits = [`Deal${ago}${f.last_deal_date ? ` (${f.last_deal_date})` : ''}${f.side ? `: ${SIDE_LABEL[f.side] ?? f.side}` : ''}`];
  if (f.deal_sessions_in_window > 1) bits.push(`${f.deal_sessions_in_window} deal sessions in the last 10`);
  if (f.verdict_title) bits.push(f.verdict_title);
  if (f.deal_price != null) bits.push(`deal price ₹${f.deal_price.toFixed(2)}${f.vs_deal_pct != null ? `, now ${f.vs_deal_pct >= 0 ? '+' : ''}${f.vs_deal_pct.toFixed(1)}%` : ''}`);
  if (f.status) bits.push(f.status);
  return `${bits.join(' · ')}. Click for the Deals drawer.`;
}

export function dealHref(symbol: string): string {
  return `/deals?sym=${encodeURIComponent(symbol)}`;
}

/** Every flagged symbol at the URL as_of, keyed by symbol. One cached request shared by every list. */
export function useDealFlags(enabled = true): { map: DealFlagMap; loading: boolean } {
  const [asOf] = useAsOf();
  const q = useQuery({
    queryKey: apiQueryKey('deals/flags', null, { limit: DEAL_FLAGS_LIMIT }, asOf),
    queryFn: ({ signal }) => getRawEnvelope<DealFlag>('deals/flags', { limit: DEAL_FLAGS_LIMIT, ...(asOf ? { as_of: asOf } : {}) }, signal),
    enabled,
    staleTime: 10 * 60_000,
    retry: false,
  });
  const rows = q.data?.rows;
  const map = useMemo(() => dealFlagMap(rows), [rows]);
  return { map, loading: q.isLoading };
}
