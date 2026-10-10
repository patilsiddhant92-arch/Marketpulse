/**
 * Divergences for one chart: GET /api/v2/charts/{sym}/divergences (contract in
 * HarkPro/12-sprint2-plan.md). When the endpoint is missing or fails, fall back to the same
 * rules on the client (divergence.ts `detectDivergences`). The endpoint is typed here by hand
 * because the generated API types do not have it yet.
 */
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { API_BASE, buildQuery } from '../api/client';
import type { OHLCBar } from '../lib/indicators';
import { useAsOf } from '../shell/urlState';
import { detectDivergences, type DivergenceRow } from './divergence';

const SIDES = new Set(['bull', 'bear']);
const TYPES = new Set(['Strong', 'Medium', 'Weak', 'Hidden']);
const STATUS = new Set(['watching', 'triggered', 'failed']);

/** Keep only well-formed rows (dates as YYYY-MM-DD, numbers finite). */
export function parseDivergenceRows(rows: unknown): DivergenceRow[] {
  if (!Array.isArray(rows)) return [];
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const day = (v: unknown) => (typeof v === 'string' && v.length >= 10 ? v.slice(0, 10) : null);
  const out: DivergenceRow[] = [];
  for (const r of rows as Record<string, unknown>[]) {
    if (!r || !SIDES.has(r.side as string) || !TYPES.has(r.type as string)) continue;
    const p1 = day(r.p1_date);
    const p2 = day(r.p2_date);
    const c = day(r.confirm_date) ?? p2;
    const n = [num(r.p1_price), num(r.p2_price), num(r.p1_rsi), num(r.p2_rsi)];
    if (!p1 || !p2 || !c || n.some((x) => x == null)) continue;
    out.push({
      side: r.side as DivergenceRow['side'],
      type: r.type as DivergenceRow['type'],
      p1_date: p1,
      p2_date: p2,
      p1_price: n[0] as number,
      p2_price: n[1] as number,
      p1_rsi: n[2] as number,
      p2_rsi: n[3] as number,
      confirm_date: c,
      trigger_price: num(r.trigger_price),
      stop_price: num(r.stop_price),
      status: STATUS.has(r.status as string) ? (r.status as DivergenceRow['status']) : 'watching',
    });
  }
  return out;
}

export interface DivergenceFetch {
  rows: DivergenceRow[];
  /** 'api' = served rows, 'client' = the client-side fallback. */
  source: 'api' | 'client';
}

export async function fetchDivergences(
  sym: string,
  tf: string,
  asOf: string | null,
  signal?: AbortSignal,
): Promise<DivergenceRow[] | null> {
  const url = `${API_BASE}/charts/${encodeURIComponent(sym)}/divergences${buildQuery({ tf, as_of: asOf ?? undefined })}`;
  try {
    const res = await fetch(url, { signal, headers: { Accept: 'application/json' } });
    if (!res.ok) return null;
    const json = (await res.json()) as { rows?: unknown; meta?: { status?: string } };
    if (json?.meta?.status && json.meta.status !== 'ok') return null;
    return parseDivergenceRows(json?.rows);
  } catch (e) {
    if ((e as { name?: string })?.name === 'AbortError') throw e;
    return null;
  }
}

export function useDivergences(sym: string, tf: 'D' | 'W' | 'M', bars: readonly OHLCBar[], enabled = true): DivergenceFetch {
  const [asOf] = useAsOf();
  const q = useQuery({
    queryKey: ['v2', 'charts/{sym}/divergences', { sym }, { tf, as_of: asOf }],
    queryFn: ({ signal }) => fetchDivergences(sym, tf, asOf, signal),
    enabled: enabled && !!sym,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const served = q.data;
  const client = useMemo(
    () => (enabled && served == null && !q.isPending ? detectDivergences(bars) : []),
    [enabled, served, q.isPending, bars],
  );
  if (served != null) return { rows: served, source: 'api' };
  return { rows: client, source: 'client' };
}
