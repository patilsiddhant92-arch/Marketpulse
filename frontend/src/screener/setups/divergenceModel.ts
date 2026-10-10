/**
 * Setups · Divergences view: pure helpers. The server (GET /api/v2/setups/divergences) owns
 * every rule (HarkPro/12-sprint2-plan.md "Divergence API contract"); this file builds the query,
 * filters and formats.
 */
import type { DivergenceScanRow } from '../../api/types';
import type { ChipTone } from '../../ui/Chip';
import { formatTradingViewList } from '../../lib/tradingview';

export type DivSide = 'bull' | 'bear';
export type DivType = 'Strong' | 'Medium' | 'Weak' | 'Hidden';
export type DivTf = 'D' | 'W' | 'M';

export const DIV_SIDES: { id: '' | DivSide; label: string }[] = [
  { id: '', label: 'Both' },
  { id: 'bull', label: 'Bullish' },
  { id: 'bear', label: 'Bearish' },
];
export const DIV_TYPES: { id: DivType; hint: string }[] = [
  { id: 'Strong', hint: 'Bull: price lower low, RSI higher low. Bear: price higher high, RSI lower high.' },
  { id: 'Medium', hint: 'Bull: price equal low (within 0.5 ATR), RSI higher low. Bear mirrored.' },
  { id: 'Weak', hint: 'Bull: price lower low, RSI equal low (within 2 points). Bear mirrored.' },
  { id: 'Hidden', hint: 'Trend continuation. Bull: price higher low, RSI lower low, close above EMA50, RSI below 50. Bear mirrored.' },
];
export const DIV_TFS: { id: DivTf; label: string }[] = [
  { id: 'D', label: 'Daily' },
  { id: 'W', label: 'Weekly' },
  { id: 'M', label: 'Monthly' },
];
export const DIV_WINDOWS: { id: string; label: string }[] = [
  { id: '1', label: 'Last bar' },
  { id: '5', label: '5 bars' },
  { id: '10', label: '10 bars' },
  { id: '20', label: '20 bars' },
];

/** URL keys (merged into SETUPS_DEFAULTS so mode switches clear them). */
export const DIVERGENCE_DEFAULTS = {
  dtf: 'D', // timeframe
  dside: '', // '' | bull | bear
  dtypes: '', // comma list of DivType; '' = all
  dwin: '5', // confirmed within the last N bars
};

export function divergenceQuery(s: { dtf: string; dside: string; dtypes: string; dwin: string }): Record<string, string | number> {
  const tf = (['D', 'W', 'M'] as const).includes(s.dtf as DivTf) ? s.dtf : 'D';
  const win = Math.min(60, Math.max(1, Number.parseInt(s.dwin, 10) || 5));
  const q: Record<string, string | number> = { tf, window: win, limit: 5000 };
  if (s.dside === 'bull' || s.dside === 'bear') q.side = s.dside;
  const types = s.dtypes
    .split(',')
    .map((t) => t.trim())
    .filter((t) => DIV_TYPES.some((d) => d.id === t));
  if (types.length) q.types = types.join(',');
  return q;
}

export function filterDivergences(rows: readonly DivergenceScanRow[], search = ''): DivergenceScanRow[] {
  const q = search.trim().toLowerCase();
  if (!q) return [...rows];
  return rows.filter(
    (r) => r.symbol.toLowerCase().includes(q) || (r.industry ?? '').toLowerCase().includes(q) || (r.name ?? '').toLowerCase().includes(q),
  );
}

export function sideTone(side: string): ChipTone {
  return side === 'bull' ? 'positive' : 'negative';
}
export function statusTone(status: string): ChipTone {
  return status === 'triggered' ? 'accent' : status === 'failed' ? 'warn' : 'neutral';
}
export function typeRank(t: string): number {
  return ['Strong', 'Medium', 'Weak', 'Hidden'].indexOf(t);
}

/** TradingView watchlist: one section per side + type (Bull Strong first), rows in the given order. */
export function divergenceTvText(rows: readonly DivergenceScanRow[], tf: string): { text: string; count: number } {
  const order: string[] = [];
  const by = new Map<string, string[]>();
  for (const r of rows) {
    const k = `${r.side === 'bull' ? 'Bull' : 'Bear'} ${r.type} ${tf}`;
    if (!by.has(k)) {
      by.set(k, []);
      order.push(k);
    }
    by.get(k)!.push(r.symbol);
  }
  order.sort((a, b) => (a.startsWith('Bull') === b.startsWith('Bull') ? typeRank(a.split(' ')[1]) - typeRank(b.split(' ')[1]) : a.startsWith('Bull') ? -1 : 1));
  return formatTradingViewList(order.map((k) => ({ title: `RSI div ${k}`, symbols: by.get(k)! })));
}
