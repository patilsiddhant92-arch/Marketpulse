/**
 * Deals tab model (HarkPro/08-tab-deals.md, mockup v1.2): pure helpers, unit-tested.
 *  - verdict / side / grade display meta
 *  - TradingView copy: `###<list title>,NSE:SYM,...`, '-' and '&' -> '_' (NSE:BAJAJ_AUTO, NSE:M_M)
 *  - "Copy every list (sections)": one ### section per list
 *  - Today noise split, Watch filters, legacy ?view= mapping, legacy follow storage (moved to the server)
 */
import { formatTradingViewList } from '../../lib/tradingview';
import type { ChipTone } from '../../ui/Chip';
import type { DealRow, Grade, Side, Verdict } from './api';

export type DealsView = 'today' | 'watch' | 'history' | 'houses' | 'groups';
export const VIEWS: readonly { value: DealsView; label: string; title: string }[] = [
  { value: 'today', label: 'Today', title: 'Every deal stock of the latest deal session, with its verdict' },
  { value: 'watch', label: 'Deal watch', title: 'Last 10 deal sessions: holding, lost or reclaimed vs the deal price' },
  { value: 'history', label: 'History', title: 'Every deal stock over the last 5 / 10 / 20 deal sessions, with its pattern' },
  { value: 'houses', label: 'Houses', title: 'Who is buying, their class and out-of-sample grade, and where FII/DII money went' },
  { value: 'groups', label: 'By group', title: 'Deals by industry over the last 10 deal sessions' },
];

/** Old 8-view URLs (other tabs link to ?view=repeated&q=SYM) land on the closest new view. */
export function viewFromParam(v: string | null): DealsView {
  switch (v) {
    case 'watch':
    case 'history':
    case 'houses':
    case 'groups':
      return v;
    case 'repeated':
    case 'play':
    case 'prop':
      return 'history';
    case 'star':
    case 'leader':
      return 'houses';
    default:
      return 'today';
  }
}

export const VERDICT_ORDER: readonly Verdict[] = ['confirm', 'place', 'absorbed', 'watch', 'supply', 'none', 'churn', 'avoid', 'ignore'];
export const NOISE: readonly Verdict[] = ['churn', 'ignore', 'none'];

export const VERDICT_META: Record<Verdict, { tone: ChipTone; label: string; icon: string }> = {
  confirm: { tone: 'positive', label: 'Confirmed', icon: '✓' },
  watch: { tone: 'warn', label: 'Watch day 3', icon: '3' },
  place: { tone: 'info', label: 'Placement', icon: 'P' },
  absorbed: { tone: 'accent', label: 'Absorbed', icon: 'A' },
  supply: { tone: 'warn', label: 'Supply', icon: 'S' },
  none: { tone: 'neutral', label: 'No edge', icon: '·' },
  churn: { tone: 'neutral', label: 'Churn', icon: 'C' },
  avoid: { tone: 'negative', label: 'Avoid', icon: '!' },
  ignore: { tone: 'neutral', label: 'Transfer', icon: 'T' },
};

/** Deal-candle colours (mockup v1.1: one colour for the whole deal-day candle). */
export const SIDE_COLOR: Record<Side, string> = { B: '#2dd4bf', P: '#60a5fa', S: '#fb923c', C: '#64748b', T: '#94a3b8' };
export const SIDE_LABEL: Record<Side, string> = { B: 'net buy', P: 'placement', S: 'net sell', C: 'churn', T: 'transfer' };

export function gradeTone(g: Grade): ChipTone {
  return g === 'good' ? 'positive' : g === 'poor' ? 'negative' : g === 'mixed' ? 'warn' : 'neutral';
}

export function chipTone(chip: string): ChipTone {
  if (/Placement/.test(chip)) return 'info';
  if (/Holding|Good/.test(chip)) return 'positive';
  if (/Absorbed/.test(chip)) return 'accent';
  if (/Extended/.test(chip)) return 'warn';
  if (/Churn|Poor/.test(chip)) return 'negative';
  return 'neutral';
}

export function statusTone(s: string | null): ChipTone {
  if (s === 'holding' || s === 'reclaimed') return 'positive';
  if (s === 'lost' || s === 'below seller') return 'negative';
  return 'neutral';
}

export function verdictRank(v: Verdict): number {
  const i = VERDICT_ORDER.indexOf(v);
  return i < 0 ? 99 : i;
}

export function sortByVerdict<T extends { verdict: Verdict; net_cr: number }>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => verdictRank(a.verdict) - verdictRank(b.verdict) || Math.abs(b.net_cr) - Math.abs(a.net_cr));
}

export function splitNoise(rows: readonly DealRow[]): { main: DealRow[]; noise: DealRow[] } {
  const main: DealRow[] = [];
  const noise: DealRow[] = [];
  for (const r of rows) (NOISE.includes(r.verdict) ? noise : main).push(r);
  return { main, noise };
}

/** The ₹ Cr shown on Today: bought value for placements / near-zero nets, else the net ex-PROP. */
export function shownValue(r: Pick<DealRow, 'event_type' | 'net_cr' | 'bought_cr'>): { value: number; bought: boolean } {
  if (r.event_type === 'placement' || Math.abs(r.net_cr) < 0.5) return { value: r.bought_cr, bought: r.bought_cr !== r.net_cr };
  return { value: r.net_cr, bought: false };
}

export function filterText<T extends { symbol: string; name?: string; industry?: string | null }>(rows: readonly T[], q: string): T[] {
  const s = q.trim().toUpperCase();
  if (!s) return [...rows];
  return rows.filter((r) => r.symbol.toUpperCase().includes(s) || (r.name ?? '').toUpperCase().includes(s) || (r.industry ?? '').toUpperCase().includes(s));
}

// ------------------------------------------------------------------ TradingView
/** TradingView symbol body: '-' and '&' -> '_' (lib/tradingview maps '-'; '&' is mapped here). */
export function tvSafe(symbol: string): string {
  return symbol.trim().toUpperCase().replace(/[-&]/g, '_');
}

/** A `###` title must not contain the list separator. */
export function tvTitle(title: string): string {
  return title.replace(/[,·]/g, ' ').replace(/\s+/g, ' ').trim();
}

export interface TvList {
  title: string;
  symbols: readonly string[];
}

/** One list: `###Title,NSE:A,NSE:B`. */
export function tvListText(list: TvList): { text: string; count: number } {
  return formatTradingViewList([{ title: tvTitle(list.title), symbols: list.symbols.map(tvSafe) }]);
}

/** Every list on the tab, one `###` section each (newline between sections; duplicates kept per section). */
export function tvSectionsText(lists: readonly TvList[]): { text: string; count: number; lists: number } {
  const parts: string[] = [];
  let count = 0;
  for (const l of lists) {
    const { text, count: n } = tvListText(l);
    if (!n) continue;
    parts.push(text);
    count += n;
  }
  return { text: parts.join('\n'), count, lists: parts.length };
}

// ------------------------------------------------------------------ follow (legacy browser storage)
// Follows live in the user DB now (follows.ts). Older builds kept them here; they are moved once.
const FOLLOW_KEY = 'mp.deals.followedHouses';

export function readLegacyFollowed(): string[] {
  try {
    const raw = window.localStorage.getItem(FOLLOW_KEY);
    const v = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

export function clearLegacyFollowed(): void {
  try {
    window.localStorage.removeItem(FOLLOW_KEY);
  } catch {
    /* blocked storage */
  }
}

/** Spread cell: "3 groups" + top-3 industry shares (first word of the industry). */
export function spreadSummary(spread: readonly { industry: string; share_pct: number }[]): { groups: number; top: { label: string; pct: number }[] } {
  return {
    groups: spread.length,
    top: spread.slice(0, 3).map((g) => ({ label: g.industry.split(/[ /&,(]/)[0] || g.industry, pct: g.share_pct })),
  };
}
