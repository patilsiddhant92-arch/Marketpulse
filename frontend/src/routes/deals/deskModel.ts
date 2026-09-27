/** Pure helpers for the restored Deals desk views (tested in deskModel.test.ts). */
import type { DealWindowRow } from '../../api/types';

export type DeskTier = 'conviction' | 'fresh' | 'distribution' | 'transfer' | 'churn' | 'quarantined';
export type PlayScope = 'play' | 'conviction' | 'fresh' | 'distribution' | 'transfer' | 'quarantined';
export type Direction = 'all' | 'buy' | 'sell';
export type Setup = 'ALL' | 'ABOVE_200' | 'TURNAROUND';

export const LOOKBACKS = [10, 20, 30] as const;

export const TIER_LABEL: Record<DeskTier, string> = {
  conviction: 'Conviction',
  fresh: 'Fresh whale',
  distribution: 'Distribution',
  transfer: 'Transfer',
  churn: 'Prop / churn',
  quarantined: 'Quarantined',
};

export const TIER_HINT: Record<DeskTier, string> = {
  conviction: 'Flow net > 0 with a repeat buyer, ≥ 2 net-buy sessions, ≥ 2 buying houses, or size (net ≥ ₹20 Cr, flow buys ≥ ₹25 Cr or ≥ 0.5× ADV).',
  fresh: 'Flow net > 0 from a single house on a single session, below the size bar.',
  distribution: 'Flow net < 0 over the window (PROP excluded, transfers and churn not counted).',
  transfer: 'Only inter-se transfer / placement sessions in the window: ownership moved, no market flow.',
  churn: 'Only churn sessions: PROP desks or same-day round trips dominate. Not a signal.',
  quarantined: 'Circuit band ≤ 5 %: illiquid / collar risk, kept out of Play.',
};

export function isDeskTier(v: unknown): v is DeskTier {
  return typeof v === 'string' && v in TIER_LABEL;
}

export function inPlayScope(tier: string, scope: PlayScope): boolean {
  if (scope === 'play') return tier === 'conviction' || tier === 'fresh';
  return tier === scope;
}

/** Persistence pill: 0 = all, 4 = 4 or more sessions, else exactly n (old desk semantics). */
export function matchesPersistence(days: number, pill: number): boolean {
  if (pill <= 0) return true;
  return pill >= 4 ? days >= 4 : days === pill;
}

export function persistenceCounts(rows: readonly Pick<DealWindowRow, 'deal_days'>[]): Record<2 | 3 | 4, number> {
  const out = { 2: 0, 3: 0, 4: 0 } as Record<2 | 3 | 4, number>;
  for (const r of rows) {
    if (r.deal_days >= 4) out[4] += 1;
    else if (r.deal_days === 3) out[3] += 1;
    else if (r.deal_days === 2) out[2] += 1;
  }
  return out;
}

/** Repeated deals: stocks with deals on at least `minDays` sessions, optionally by net direction. */
export function filterRepeated<T extends Pick<DealWindowRow, 'deal_days' | 'flow_net_cr'>>(rows: readonly T[], minDays: number, dir: Direction): T[] {
  return rows.filter((r) => {
    if (r.deal_days < minDays) return false;
    const net = r.flow_net_cr ?? 0;
    if (dir === 'buy') return net > 0;
    if (dir === 'sell') return net < 0;
    return true;
  });
}

export function filterText<T extends { symbol?: string | null; security_name?: string | null; industry?: string | null; sector?: string | null; house?: string | null }>(rows: readonly T[], text: string): T[] {
  const q = text.trim().toLowerCase();
  if (!q) return [...rows];
  return rows.filter((r) => [r.symbol, r.security_name, r.industry, r.sector, r.house].some((v) => (v ?? '').toLowerCase().includes(q)));
}

/** Unique symbols in first-seen order (TradingView lists must not repeat). */
export function uniqueSymbols(rows: readonly { symbol?: string | null }[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const r of rows) {
    const s = r.symbol;
    if (s && !seen.has(s)) {
      seen.add(s);
      out.push(s);
    }
  }
  return out;
}

/** "HOUSE NAME (+12.3)" -> "HOUSE NAME". */
export function houseOf(label: string): string {
  return label.replace(/\s*\([+-]?[\d.]+\)\s*$/, '');
}
