/**
 * Sector Intel pure logic (HarkPro/07-tab-sector-intel.md): peer-rank colour, sorting, read-outs,
 * TradingView copy, and the stock-heatmap maths (squarify, size / colour metrics).
 */
import { formatTradingViewList } from '../../lib/tradingview';
import { WINDOW_LABEL, type BoardLevel, type HeatRow, type MemberRow, type SectorRow, type WindowKey } from './sectorApi';

// ------------------------------------------------------------------ levels / views
export const BOARD_LEVELS: readonly { value: BoardLevel; label: string }[] = [
  { value: 'sector', label: 'Sector' },
  { value: 'broad_industry', label: 'Broad Industry' },
  { value: 'industry', label: 'Industry' },
  { value: 'index', label: 'Index' },
];
export const DEFAULT_LEVEL: BoardLevel = 'broad_industry';
export const DEFAULT_WINDOW: WindowKey = '2W';
export type SectorView = 'board' | 'grid' | 'heatmap' | 'studies';
export const VIEWS: readonly { value: SectorView; label: string; title: string }[] = [
  { value: 'board', label: 'Board', title: 'Leadership board: score, near-52W-high %, new highs, A/D, delivery, turnover, deals' },
  { value: 'grid', label: 'Chart grid', title: '9 group charts per page in board order, synced crosshair' },
  { value: 'heatmap', label: 'Heatmap', title: 'TradingView-style stock heatmap grouped by taxonomy' },
  { value: 'studies', label: 'Group studies', title: 'Evidence: which group readings predicted the next 21 sessions' },
];

export function asBoardLevel(v: string | null): BoardLevel {
  return BOARD_LEVELS.some((l) => l.value === v) ? (v as BoardLevel) : DEFAULT_LEVEL;
}
export function asWindow(v: string | null): WindowKey {
  return v === '1D' || v === '1W' || v === '2W' || v === '1M' ? v : DEFAULT_WINDOW;
}
export function asView(v: string | null): SectorView {
  return VIEWS.some((x) => x.value === v) ? (v as SectorView) : 'board';
}
/** Legacy Groups level names that other tabs still link with (?level=broad_sector). */
export function levelFromGroupId(id: string | null): BoardLevel | null {
  if (!id) return null;
  const lv = id.split(':', 1)[0];
  return lv === 'sector' || lv === 'broad_industry' || lv === 'industry' ? lv : null;
}

// ------------------------------------------------------------------ values by window
export type WinMetric = 'nh' | 'ad' | 'upd' | 'tov' | 'sh' | 'tox' | 'shd' | 'rx' | 'ret' | 'nearchg' | 'score';

export function win(row: SectorRow, key: WinMetric, w: WindowKey): number | null {
  const v = (row as Record<string, unknown>)[`${key}_${w}`];
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

// ------------------------------------------------------------------ peer-rank colour (round 3b)
export type RankTone = 'top' | 'bottom' | 'mid' | null;

/** Colour = rank against the other groups on the same day: top 20% green, bottom 20% red, else plain. Never the sign. */
export function rankTone(values: readonly (number | null | undefined)[], v: number | null | undefined, higherIsBetter = true): RankTone {
  if (v == null || !Number.isFinite(v)) return null;
  const xs = values.filter((x): x is number => x != null && Number.isFinite(x)).sort((a, b) => a - b);
  if (xs.length < 5) return 'mid';
  let lo = 0;
  let hi = xs.length;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if (xs[m] < v) lo = m + 1;
    else hi = m;
  }
  let p = lo / (xs.length - 1);
  if (!higherIsBetter) p = 1 - p;
  return p >= 0.8 ? 'top' : p <= 0.2 ? 'bottom' : 'mid';
}

export const RANK_CLASS: Record<Exclude<RankTone, null>, string> = { top: 'text-up font-semibold', bottom: 'text-down', mid: 'text-fg' };

// ------------------------------------------------------------------ filters / sort / copy
export function filterRows(rows: readonly SectorRow[], state: string, text: string): SectorRow[] {
  const t = text.trim().toLowerCase();
  return rows.filter((r) => (state === 'all' || r.state === state) && (!t || r.group_name.toLowerCase().includes(t)));
}

/** Board default order: score for the window, NULL last (not ranked / data gap). */
export function sortByScore(rows: readonly SectorRow[], w: WindowKey): SectorRow[] {
  return [...rows].sort((a, b) => {
    const x = win(a, 'score', w);
    const y = win(b, 'score', w);
    if (x == null && y == null) return a.group_name.localeCompare(b.group_name);
    if (x == null) return 1;
    if (y == null) return -1;
    return y - x;
  });
}

export function leadersTvText(rows: readonly { group_name: string; leaders: readonly string[] }[]): { text: string; count: number } {
  return formatTradingViewList(rows.filter((r) => r.leaders.length).map((r) => ({ title: r.group_name, symbols: r.leaders })));
}

export function stateCounts(rows: readonly SectorRow[]): Record<'Favour' | 'Neutral' | 'Caution', number> {
  const c = { Favour: 0, Neutral: 0, Caution: 0 };
  for (const r of rows) if (r.state && r.state in c) c[r.state] += 1;
  return c;
}

/** "3 buy · 1 sell · +₹70 Cr" chip text for the Deals 10D column; chip at 3+ net-buy names (08 §5.3). */
export function dealsCell(
  r: Pick<SectorRow, 'deals_buy_10d' | 'deals_sell_10d' | 'deals_flow_10d_cr'>,
): { text: string; chip: boolean } | null {
  if (r.deals_buy_10d == null || r.deals_sell_10d == null) return null;
  if (r.deals_buy_10d === 0 && r.deals_sell_10d === 0) return { text: '·', chip: false };
  const f = r.deals_flow_10d_cr;
  const flow =
    f == null ? '' : ` · ${f > 0 ? '+' : f < 0 ? '−' : ''}₹${Math.abs(f).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
  return { text: `${r.deals_buy_10d} buy · ${r.deals_sell_10d} sell${flow}`, chip: r.deals_buy_10d >= 3 };
}

// ------------------------------------------------------------------ plain-English read-out (04-writing-style.md)
export function groupReadout(row: SectorRow, members: readonly MemberRow[], w: WindowKey): string[] {
  const n = members.length;
  const near = members.filter((m) => m.near_52w_high).length;
  const above = members.filter((m) => m.above_50ema).length;
  const out: string[] = [];
  if (n === 0) return ['No members meet the ₹1,000 Cr floor today.'];
  out.push(`${near} of ${n} members are within 10% of their 52-week high.`);
  out.push(`${above} of ${n} are above their 50-day average.`);
  const nh = win(row, 'nh', w);
  if (nh != null)
    out.push(
      nh > 0
        ? `${nh} made a new 52-week high in the last ${WINDOW_LABEL[w]}.`
        : `None made a new 52-week high in the last ${WINDOW_LABEL[w]}.`,
    );
  const ad = win(row, 'ad', w);
  if (ad != null)
    out.push(
      ad > 10
        ? 'Most days, more members rose than fell.'
        : ad < -10
          ? 'Most days, more members fell than rose.'
          : 'Rises and falls were about even.',
    );
  const upd = win(row, 'upd', w);
  if (upd != null && upd >= 60) out.push(`${upd.toFixed(0)}% of delivered value came on up days.`);
  else if (upd != null && upd <= 40) out.push(`Only ${upd.toFixed(0)}% of delivered value came on up days.`);
  if (n >= 5 && near <= 1) out.push('The move is narrow: one stock or none.');
  else if (n >= 3 && near >= n / 3) out.push('The move is broad.');
  return out;
}

// ------------------------------------------------------------------ stock heatmap (07 §3d)
export type HeatGroup = 'sector' | 'broad_industry' | 'industry';
export type HeatSize = 't' | 't20' | 'v' | 'dv' | 'mc' | 'eq';
export type HeatColour = 'r1' | 'co' | 'gap' | 'r5' | 'r21' | 'r63' | 'r126' | 'r252' | 'rvol' | 'vol' | 'dp' | 'a52' | 'rs';

export const HEAT_SIZES: readonly { value: HeatSize; label: string }[] = [
  { value: 't', label: 'Value traded (vol × price)' },
  { value: 't20', label: 'Value traded, 20D avg' },
  { value: 'v', label: 'Volume (shares)' },
  { value: 'dv', label: 'Delivery value' },
  { value: 'mc', label: 'Market cap' },
  { value: 'eq', label: 'Equal' },
];
export const HEAT_COLOURS: readonly { value: HeatColour; label: string }[] = [
  { value: 'r1', label: 'Change 1D %' },
  { value: 'co', label: 'Change from open %' },
  { value: 'gap', label: 'Gap %' },
  { value: 'r5', label: 'Perf 1W %' },
  { value: 'r21', label: 'Perf 1M %' },
  { value: 'r63', label: 'Perf 3M %' },
  { value: 'r126', label: 'Perf 6M %' },
  { value: 'r252', label: 'Perf 1Y %' },
  { value: 'rvol', label: 'Relative volume' },
  { value: 'vol', label: 'Volatility (ATR %)' },
  { value: 'dp', label: 'Delivery %' },
  { value: 'a52', label: 'From 52W high %' },
  { value: 'rs', label: 'RS percentile' },
];
/** Each colour metric's centre and spread; `norel` = "vs market" does not apply; `inv` = low is green. */
export const HEAT_SCALE: Record<HeatColour, { c: number; s: number; u: '%' | '×' | ''; norel?: boolean; inv?: boolean }> = {
  r1: { c: 0, s: 3, u: '%' },
  co: { c: 0, s: 3, u: '%' },
  gap: { c: 0, s: 2, u: '%' },
  r5: { c: 0, s: 6, u: '%' },
  r21: { c: 0, s: 12, u: '%' },
  r63: { c: 0, s: 25, u: '%' },
  r126: { c: 0, s: 40, u: '%' },
  r252: { c: 0, s: 60, u: '%' },
  rvol: { c: 1.25, s: 1.25, u: '×', norel: true },
  vol: { c: 3, s: 2, u: '%', inv: true, norel: true },
  dp: { c: 45, s: 25, u: '%', norel: true },
  a52: { c: -15, s: 15, u: '%', norel: true },
  rs: { c: 50, s: 45, u: '', norel: true },
};

export function median(xs: readonly (number | null | undefined)[]): number | null {
  const a = xs.filter((x): x is number => x != null && Number.isFinite(x)).sort((x, y) => x - y);
  return a.length ? a[a.length >> 1] : null;
}

/** −1..1 colour position for a value (NULL = grey). `rel` subtracts the market median (return metrics only). */
export function heatPosition(metric: HeatColour, v: number | null | undefined, rel: boolean): number | null {
  if (v == null || !Number.isFinite(v)) return null;
  const m = HEAT_SCALE[metric];
  let d = (v - (rel && !m.norel ? 0 : m.c)) / m.s;
  if (m.inv) d = -d;
  return Math.max(-1, Math.min(1, d));
}

/** TradingView-like colour: grey at the centre, green / red at ±1. */
export function heatColour(pos: number | null): string {
  if (pos == null) return 'rgb(59,66,80)';
  const g = [48, 204, 90];
  const r = [242, 54, 69];
  const n = [66, 72, 84];
  const e = pos >= 0 ? g : r;
  const a = Math.abs(pos);
  return `rgb(${e.map((x, i) => Math.round(n[i] + (x - n[i]) * a)).join(',')})`;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Squarified treemap (Bruls et al.). Items sorted by value desc are laid out in (x, y, w, h). */
export function squarify<T extends { v: number }>(items: readonly T[], x: number, y: number, w: number, h: number): (T & Rect)[] {
  const out: (T & Rect)[] = [];
  const pos = items.filter((i) => i.v > 0);
  const tot = pos.reduce((s, i) => s + i.v, 0);
  if (!tot || w <= 0 || h <= 0) return out;
  const scale = (w * h) / tot;
  let rest = pos.map((i) => ({ item: i, a: i.v * scale }));
  while (rest.length) {
    const side = Math.min(w, h);
    let row: typeof rest = [];
    let best = Infinity;
    while (rest.length) {
      const c = row.concat(rest[0]);
      const s = c.reduce((acc, i) => acc + i.a, 0);
      const mx = Math.max(...c.map((i) => i.a));
      const mn = Math.min(...c.map((i) => i.a));
      const worst = Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
      if (worst <= best) {
        best = worst;
        row = c;
        rest = rest.slice(1);
      } else break;
    }
    const s = row.reduce((acc, i) => acc + i.a, 0);
    if (w >= h) {
      const rw = s / h;
      let yy = y;
      for (const i of row) {
        const ih = i.a / rw;
        out.push({ ...i.item, x, y: yy, w: rw, h: ih });
        yy += ih;
      }
      x += rw;
      w -= rw;
    } else {
      const rh = s / w;
      let xx = x;
      for (const i of row) {
        const iw = i.a / rh;
        out.push({ ...i.item, x: xx, y, w: iw, h: rh });
        xx += iw;
      }
      y += rh;
      h -= rh;
    }
  }
  return out;
}

export interface HeatGroupBox {
  key: string;
  stocks: HeatRow[];
  v: number;
  /** Size-weighted move of the group for the colour metric (vs market when rel). */
  move: number | null;
}

export function sizeOf(s: HeatRow, size: HeatSize): number {
  if (size === 'eq') return 1;
  const v = s[size];
  return typeof v === 'number' && v > 0 ? v : 0;
}

/** Group the heatmap stocks; filter by floor and focus; compute each header's weighted move. */
export function heatGroups(
  rows: readonly HeatRow[],
  opts: { group: HeatGroup; size: HeatSize; colour: HeatColour; rel: boolean; floor: boolean; focus: string | null },
): { groups: HeatGroupBox[]; market: number | null; shown: HeatRow[] } {
  const universe = rows.filter((s) => !opts.floor || (s.mc ?? 0) >= 1000);
  const market = median(universe.map((s) => s[opts.colour]));
  const rel = opts.rel && !HEAT_SCALE[opts.colour].norel;
  let shown = universe.filter((s) => s[opts.group] && sizeOf(s, opts.size) > 0);
  if (opts.focus) shown = shown.filter((s) => s[opts.group] === opts.focus);
  const by = new Map<string, HeatRow[]>();
  for (const s of shown) {
    const k = s[opts.group] as string;
    const l = by.get(k);
    if (l) l.push(s);
    else by.set(k, [s]);
  }
  const groups: HeatGroupBox[] = [...by.entries()].map(([key, stocks]) => {
    let tw = 0;
    let acc = 0;
    for (const s of stocks) {
      const v = s[opts.colour];
      if (v == null) continue;
      const w = sizeOf(s, opts.size);
      tw += w;
      acc += (rel && market != null ? v - market : v) * w;
    }
    return { key, stocks, v: stocks.reduce((a, s) => a + sizeOf(s, opts.size), 0), move: tw ? acc / tw : null };
  });
  groups.sort((a, b) => b.v - a.v);
  return { groups, market, shown };
}

export function fmtHeat(metric: HeatColour, v: number | null | undefined, rel = false): string {
  if (v == null || !Number.isFinite(v)) return '–';
  const m = HEAT_SCALE[metric];
  if (m.u === '%') return `${v > 0 && (m.c === 0 || rel) ? '+' : ''}${v.toFixed(m.s >= 12 ? 1 : 2)}%`;
  if (m.u === '×') return `${v.toFixed(2)}×`;
  return String(Math.round(v));
}
