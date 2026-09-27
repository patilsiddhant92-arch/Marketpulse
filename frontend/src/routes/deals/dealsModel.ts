/** Pure helpers for the Deals tab (tested in dealsModel.test.ts). */
import type { DealSessionRow } from '../../api/types';
import type { ChipTone } from '../../ui/Chip';

export type EventType = 'accumulate' | 'fresh' | 'distribute' | 'transfer_interse' | 'placement' | 'churn';
export type EventGroup = 'main' | 'strategic' | 'churn' | 'other';

export const EVENTS: Record<EventType, { label: string; tone: ChipTone; group: EventGroup; order: number; short: string }> = {
  accumulate: { label: 'Accumulate', tone: 'positive', group: 'main', order: 0, short: 'Net buying again within 10 sessions' },
  fresh: { label: 'Fresh buyer', tone: 'info', group: 'main', order: 1, short: 'First net buying in 10 sessions' },
  distribute: { label: 'Distribute', tone: 'negative', group: 'main', order: 2, short: 'Net selling (PROP excluded)' },
  transfer_interse: { label: 'Inter-se transfer', tone: 'violet', group: 'strategic', order: 3, short: 'Matched seller → buyer (promoter/group entities)' },
  placement: { label: 'Placement', tone: 'violet', group: 'strategic', order: 4, short: 'Block absorbed by FII/DII' },
  churn: { label: 'Churn / prop', tone: 'neutral', group: 'churn', order: 5, short: 'Round trips or PROP desks dominate; not real flow' },
};

export function isEventType(v: unknown): v is EventType {
  return typeof v === 'string' && v in EVENTS;
}

export function eventGroup(et: string | null | undefined): EventGroup {
  return isEventType(et) ? EVENTS[et].group : 'other';
}

/** Main-table order: Accumulate, Fresh, Distribute (then unclassified), each by |net ex-PROP| desc. */
export function sortMain(rows: readonly DealSessionRow[]): DealSessionRow[] {
  const ord = (r: DealSessionRow) => (isEventType(r.event_type) ? EVENTS[r.event_type].order : 9);
  const net = (r: DealSessionRow) => Math.abs(r.net_ex_prop_cr ?? r.net_cr ?? 0);
  return [...rows].sort((a, b) => ord(a) - ord(b) || net(b) - net(a));
}

export function splitSession(rows: readonly DealSessionRow[]): {
  main: DealSessionRow[];
  strategic: DealSessionRow[];
  churn: DealSessionRow[];
} {
  const main: DealSessionRow[] = [];
  const strategic: DealSessionRow[] = [];
  const churn: DealSessionRow[] = [];
  for (const r of rows) {
    const g = eventGroup(r.event_type);
    if (g === 'strategic') strategic.push(r);
    else if (g === 'churn') churn.push(r);
    else main.push(r);
  }
  const gross = (r: DealSessionRow) => (r.buy_cr ?? 0) + (r.sell_cr ?? 0);
  return {
    main: sortMain(main),
    strategic: strategic.sort((a, b) => gross(b) - gross(a)),
    churn: churn.sort((a, b) => gross(b) - gross(a)),
  };
}

export function filterDeals<T extends Pick<DealSessionRow, 'symbol' | 'security_name' | 'industry'>>(rows: readonly T[], text: string): T[] {
  const q = text.trim().toLowerCase();
  if (!q) return [...rows];
  return rows.filter((r) => [r.symbol, r.security_name, r.industry].some((v) => (v ?? '').toLowerCase().includes(q)));
}

/** Bar geometry for the 10-session net strip: heights relative to the row's largest |net|. */
export function netBars(values: readonly (number | null | undefined)[]): { v: number | null; h: number }[] {
  const max = Math.max(0, ...values.map((v) => (typeof v === 'number' ? Math.abs(v) : 0)));
  return values.map((v) => (typeof v === 'number' ? { v, h: max > 0 ? Math.abs(v) / max : 0 } : { v: null, h: 0 }));
}

export function chartsDealsHref(kind: string, symbols: readonly string[], asOf: string | null): string {
  const p = new URLSearchParams();
  p.set('source', `deals:${kind}`);
  if (symbols.length) p.set('syms', symbols.slice(0, 60).join(','));
  if (asOf) p.set('as_of', asOf);
  return `/charts?${p.toString()}`;
}
