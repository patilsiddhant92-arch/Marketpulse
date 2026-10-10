/**
 * Cross-tab stock context (GET /api/v2/context/stocks): one batched request per ≤ 200 symbols,
 * shared by every table that shows stocks (Pulse, Setups, Sector Intel, Deals, Charts, Stock 360).
 * Pure helpers here; React pieces in StockContextChips.tsx.
 */
import { useQueries } from '@tanstack/react-query';
import { useMemo } from 'react';
import { apiGet } from '../api/client';
import { apiQueryKey } from '../api/query';
import type { ContextSetup, GroupContext, StockContextRow } from '../api/types';
import type { ChipTone } from '../ui/Chip';
import { useAsOf } from '../shell/urlState';

export const CONTEXT_CHUNK = 200;
/** Hard cap on symbols one table asks context for (5 requests). */
export const CONTEXT_MAX = 1000;

/** Unique, upper-cased, sorted symbols split into request chunks (stable query keys). */
export function contextChunks(symbols: readonly (string | null | undefined)[], chunk = CONTEXT_CHUNK, max = CONTEXT_MAX): string[][] {
  const uniq = [...new Set(symbols.filter((s): s is string => !!s).map((s) => s.toUpperCase()))].slice(0, max).sort();
  const out: string[][] = [];
  for (let i = 0; i < uniq.length; i += chunk) out.push(uniq.slice(i, i + chunk));
  return out;
}

export type StockContextMap = ReadonlyMap<string, StockContextRow>;
const EMPTY_MAP: StockContextMap = new Map();

/** Context rows for the given symbols, keyed by symbol. Batched, cached per as_of. */
export function useStockContext(symbols: readonly (string | null | undefined)[], enabled = true): { map: StockContextMap; loading: boolean } {
  const [asOf] = useAsOf();
  const chunks = useMemo(() => contextChunks(symbols), [symbols]);
  const results = useQueries({
    queries: chunks.map((c) => {
      const query = { symbols: c.join(','), ...(asOf ? { as_of: asOf } : {}) };
      return {
        queryKey: apiQueryKey('context/stocks', null, { symbols: c.join(',') }, asOf),
        queryFn: ({ signal }: { signal: AbortSignal }) => apiGet('context/stocks', { query }, { signal }),
        enabled,
        staleTime: 5 * 60_000,
      };
    }),
  });
  const loading = results.some((r) => r.isLoading);
  const stamp = results.map((r) => r.dataUpdatedAt).join(',');
  const map = useMemo(() => {
    if (!results.some((r) => r.data)) return EMPTY_MAP;
    const m = new Map<string, StockContextRow>();
    for (const r of results) for (const row of r.data?.rows ?? []) m.set(row.symbol, row);
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `stamp` changes exactly when any chunk's data does
  }, [stamp]);
  return { map, loading };
}

// ------------------------------------------------------------------ chip model (pure)

export type ContextPart = 'group' | 'deals' | 'setups' | 'warning' | 'events';

export interface ContextChip {
  key: string;
  part: ContextPart;
  label: string;
  tone: ChipTone;
  title: string;
  /** In-app path (as_of is added by the caller). */
  href?: string;
}

export const QUEUE_SHORT: Record<string, string> = { darvas_squeeze: 'Squeeze', darvas_10ema: '10 EMA', vcp: 'VCP' };
const ZONE_TONE: Record<string, ChipTone> = { Healthy: 'positive', Mixed: 'warn', Weak: 'negative' };
const QUAD_SHORT: Record<string, string> = { Leading: 'Lead', Improving: 'Impr', Weakening: 'Weak', Lagging: 'Lag' };

export function noteShort(note: string | null | undefined): string | null {
  if (!note) return null;
  if (/falling/.test(note)) return 'falling';
  if (/narrow/.test(note)) return 'narrow';
  if (/rising/.test(note)) return 'rising';
  return note;
}

export function dealsHref(symbol: string): string {
  return `/deals?view=repeated&lb=10&floor=all&rdays=1&q=${encodeURIComponent(symbol)}`;
}

export function groupHref(id: string): string {
  return `/groups?group=${encodeURIComponent(id)}`;
}

export function groupTitle(g: GroupContext): string {
  const bits = [`${g.group_name ?? g.id}: Health ${g.health != null ? g.health.toFixed(0) : '—'}${g.health_zone ? ` (${g.health_zone})` : ''}`];
  if (g.health_rank != null) bits.push(`#${g.health_rank} by Health`);
  if (g.rrg_quadrant) bits.push(`${g.rrg_quadrant} vs peers${g.quadrant_note ? ` — ${g.quadrant_note}` : ''}`);
  if (g.abs_trend) bits.push(`own trend ${g.abs_trend}`);
  const s = (g.health_spark_21 ?? []).filter((v): v is number => v != null);
  if (s.length >= 2) bits.push(`Health ${s[s.length - 1] - s[0] >= 0 ? '+' : ''}${(s[s.length - 1] - s[0]).toFixed(0)} over ${s.length} sessions`);
  if (g.thin) bits.push('thin group (< 3 members)');
  return bits.join(' · ');
}

function setupChip(s: ContextSetup, symbol: string): ContextChip {
  const d = s.distance_to_trigger_pct;
  return {
    key: `setup:${s.queue}`,
    part: 'setups',
    label: `${QUEUE_SHORT[s.queue] ?? s.label}${d != null ? ` ${Math.abs(d) < 10 ? d.toFixed(1) : d.toFixed(0)}%` : ''}`,
    tone: 'accent',
    title: `${symbol} is in the ${s.label} queue${s.setup_age_sessions != null ? ` (${s.setup_age_sessions} sessions)` : ''}${
      s.trigger_price != null ? ` · trigger ₹${s.trigger_price.toFixed(2)}${d != null ? `, ${d.toFixed(1)}% from the close` : ''}` : ''
    }${s.risk_pct != null ? ` · risk ${s.risk_pct.toFixed(1)}%` : ''}`,
    href: `/setups?sq=${s.queue}`,
  };
}

function daysUntil(iso: string | null | undefined, asOf: string | null | undefined): number | null {
  if (!iso) return null;
  const base = asOf ? Date.parse(asOf) : Date.now();
  const d = Date.parse(iso);
  return Number.isFinite(d) && Number.isFinite(base) ? Math.round((d - base) / 86_400_000) : null;
}

/** The chips for one stock, in display order. `omit` drops parts the table already shows. */
export function contextChips(
  ctx: StockContextRow | undefined,
  opts: { omit?: readonly ContextPart[]; asOf?: string | null; skipQueue?: string } = {},
): ContextChip[] {
  if (!ctx) return [];
  const omit = new Set(opts.omit ?? []);
  const out: ContextChip[] = [];
  const g = ctx.group;
  if (!omit.has('group') && g && g.health != null) {
    const q = g.rrg_quadrant ? ` ${QUAD_SHORT[g.rrg_quadrant] ?? g.rrg_quadrant}` : '';
    const n = noteShort(g.quadrant_note);
    out.push({
      key: 'group',
      part: 'group',
      label: `H${g.health.toFixed(0)}${q}${n ? ` ${n === 'falling' ? '↓' : n}` : ''}`,
      tone: ZONE_TONE[g.health_zone ?? ''] ?? 'neutral',
      title: groupTitle(g),
      href: groupHref(g.id),
    });
  }
  if (!omit.has('setups')) for (const s of ctx.setups ?? []) if (s.queue !== opts.skipQueue) out.push(setupChip(s, ctx.symbol));
  if (!omit.has('deals') && (ctx.deal_prints_10s ?? 0) > 0) {
    const v = ctx.deal_net_10s_cr;
    out.push({
      key: 'deals',
      part: 'deals',
      label: `Deals ${v == null ? ctx.deal_prints_10s : `${v >= 0 ? '+' : '−'}${Math.abs(v) >= 100 ? Math.abs(v).toFixed(0) : Math.abs(v).toFixed(1)}`}`,
      tone: v == null || v === 0 ? 'neutral' : v > 0 ? 'positive' : 'negative',
      title: `Bulk/block deals, last 10 sessions: ${ctx.deal_prints_10s} print(s)${v != null ? `, net ₹${v.toFixed(2)} Cr` : ''} (PROP excluded)${
        ctx.deal_last_date ? `, last ${ctx.deal_last_date}` : ''
      }. Click for the Deals view filtered to ${ctx.symbol}.`,
      href: dealsHref(ctx.symbol),
    });
  }
  if (!omit.has('events')) {
    const r = ctx.next_results;
    if (r?.event_date) {
      const d = daysUntil(r.event_date, opts.asOf);
      out.push({ key: 'results', part: 'events', label: `Res${d != null ? ` ${d}d` : ''}`, tone: 'warn', title: `${(r.event_type ?? 'results').replace(/_/g, ' ')} on ${r.event_date}` });
    }
    const a = ctx.next_corp_action;
    if (a?.event_date) {
      const d = daysUntil(a.event_date, opts.asOf);
      const kind = (a.event_type ?? 'action').replace(/_/g, ' ');
      out.push({ key: 'ca', part: 'events', label: `${kind.split(' ')[0]}${d != null ? ` ${d}d` : ''}`, tone: 'info', title: `${kind} ex-date ${a.event_date}${a.headline ? ` — ${a.headline}` : ''}` });
    }
  }
  if (!omit.has('warning') && ctx.data_warning) {
    out.push({ key: 'gap', part: 'warning', label: 'Data gap', tone: 'warn', title: `${ctx.data_warning}. Multi-session numbers spanning it are hidden.` });
  }
  return out;
}
