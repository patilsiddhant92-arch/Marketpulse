/**
 * Chart v2 Info layer model (pure): status chips, stat chips, the deal cluster callout, deal levels,
 * key levels and "The read" (3-4 rule-generated lines in the house style, HarkPro/04-writing-style.md:
 * one idea per sentence, ≤ 20 words, a number behind every claim, "10-day average" not "10 EMA",
 * no semicolons, end with What to do).
 *
 * Everything is computed from what the chart already holds (bars, Darvas rows, deal candles), so
 * it also works in bar replay and on W / M bars.
 */
import { fmtDateShort, fmtNum } from '../lib/fmt';
import type { OHLCBar } from '../lib/indicators';
import type { DarvasModel } from './darvasBoxes';
import type { DealCandleRow } from './eventCandles';
import type { BarStats } from './series';

export type Tone = 'good' | 'bad' | 'warn' | 'neutral' | 'deal';

export interface Chip {
  label: string;
  tone: Tone;
  title?: string;
}

export interface KeyLevel {
  label: string;
  value: number;
  /** Distance from the last close, % (positive = above). */
  distPct: number;
}

export interface DealLevel {
  /** Index of the first displayed bar on / after the deal date. */
  from: number;
  price: number;
  letter: string;
  /** "FII deal", "Deal 2" … */
  label: string;
  status: string | null;
}

export interface DealCluster {
  from: number;
  to: number;
  fromDate: string;
  toDate: string;
  netCr: number;
  buyers: string[];
  buyerClass: string | null;
  churnCr: number;
  /** Price the callout points at (the low of the first deal bar). */
  anchorPrice: number;
}

export interface BreakoutInfo {
  index: number;
  date: string;
  /** The box that was broken. */
  top: number;
  bottom: number;
  failed: boolean;
}

export interface ReadModel {
  status: Chip[];
  stats: Chip[];
  read: string[];
  levels: KeyLevel[];
  deals: DealLevel[];
  cluster: DealCluster | null;
  breakout: BreakoutInfo | null;
}

export interface ReadInput {
  bars: readonly OHLCBar[];
  darvas: DarvasModel;
  deals?: readonly DealCandleRow[] | null;
  emas: Partial<Record<10 | 20 | 50 | 200, number | null>>;
  stats: BarStats;
  tf?: 'D' | 'W' | 'M';
}

/** Price as a trader reads it: 947 · 781.8 · 42.35. */
export function px(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—';
  const d = Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 100 ? 1 : 2;
  return fmtNum(v, d).replace(/\.0+$/, '');
}

const pct = (a: number, b: number) => (b > 0 ? (a / b - 1) * 100 : 0);
const sgn = (v: number, d = 1) => `${v >= 0 ? '+' : '−'}${fmtNum(Math.abs(v), d)}%`;
const unit = (tf: ReadInput['tf']) => (tf === 'W' ? 'week' : tf === 'M' ? 'month' : 'day');

/** Short buyer name for the callout: "SOCIETE GENERALE" -> "Societe Generale" (2 words, 18 chars). */
export function shortName(name: string): string {
  const words = name
    .replace(/[^A-Za-z0-9&.\s-]/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => (w.length <= 3 ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1).toLowerCase()));
  const s = words.join(' ');
  return s.length > 18 ? `${s.slice(0, 17)}…` : s;
}

function firstAtOrAfter(bars: readonly OHLCBar[], iso: string): number {
  let lo = 0;
  let hi = bars.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (bars[mid].time >= iso) {
      ans = mid;
      hi = mid - 1;
    } else lo = mid + 1;
  }
  return ans;
}

/** The latest breakout above a box top in the last 20 bars; failed = the close is back under that top. */
export function latestBreakout(bars: readonly OHLCBar[], d: DarvasModel, lookback = 20): BreakoutInfo | null {
  const n = bars.length;
  for (let i = n - 1; i >= Math.max(1, n - lookback); i--) {
    const t = d.topAt[i - 1];
    const b = d.bottomAt[i - 1];
    if (t == null || b == null) continue;
    if (bars[i].close > t && bars[i - 1].close <= t) {
      return { index: i, date: bars[i].time, top: t, bottom: b, failed: bars[n - 1].close < t };
    }
  }
  return null;
}

/** Deal levels: rows flagged show_line (the 3 latest B / S / P), on the displayed bars. */
export function dealLevels(bars: readonly OHLCBar[], rows: readonly DealCandleRow[] | null | undefined): DealLevel[] {
  const out: DealLevel[] = [];
  const last = bars[bars.length - 1]?.time;
  if (!last) return out;
  const lines = (rows ?? []).filter(
    (r) => r.show_line && r.trade_date && r.trade_date <= last && (r.deal_price_adj ?? r.deal_price) != null,
  );
  lines.sort((a, b) => (b.trade_date as string).localeCompare(a.trade_date as string));
  lines.forEach((r, k) => {
    const from = firstAtOrAfter(bars, r.trade_date as string);
    if (from < 0) return;
    const cls = r.letter === 'S' ? r.top_seller_class : r.top_buyer_class;
    const named = cls && /FII|FPI|DII|MF|INS/i.test(cls) ? `${cls.toUpperCase().slice(0, 3)} deal` : null;
    out.push({
      from,
      price: (r.deal_price_adj ?? r.deal_price) as number,
      letter: r.letter ?? 'B',
      label: named && !out.some((o) => o.label === named) ? named : `Deal ${k + 1}`,
      status: r.status ?? null,
    });
  });
  return out;
}

/** Deal clusters: deal sessions ≤ 10 bars apart. Returns the latest cluster with a net buy / sell. */
export function latestCluster(bars: readonly OHLCBar[], rows: readonly DealCandleRow[] | null | undefined, gap = 10): DealCluster | null {
  const last = bars[bars.length - 1]?.time;
  if (!last) return null;
  const hits = (rows ?? [])
    .filter((r) => r.trade_date && r.trade_date <= last && r.trade_date >= bars[0].time)
    .map((r) => ({ r, i: firstAtOrAfter(bars, r.trade_date as string) }))
    .filter((x) => x.i >= 0)
    .sort((a, b) => a.i - b.i);
  const groups: (typeof hits)[] = [];
  for (const h of hits) {
    const g = groups[groups.length - 1];
    if (g && h.i - g[g.length - 1].i <= gap) g.push(h);
    else groups.push([h]);
  }
  for (let k = groups.length - 1; k >= 0; k--) {
    const g = groups[k];
    const real = g.filter((x) => x.r.letter !== 'C');
    if (!real.length) continue;
    const net = real.reduce((s, x) => s + (x.r.net_cr ?? 0), 0);
    const churn = g.filter((x) => x.r.letter === 'C').reduce((s, x) => s + (x.r.gross_cr ?? 0), 0);
    const buy = net >= 0;
    const names: string[] = [];
    let cls: string | null = null;
    for (const x of real
      .slice()
      .sort((a, b) => Math.abs((b.r.top_buyer_cr ?? 0) as number) - Math.abs((a.r.top_buyer_cr ?? 0) as number))) {
      const nm = buy ? x.r.top_buyer : x.r.top_seller;
      const c = buy ? x.r.top_buyer_class : x.r.top_seller_class;
      if (nm && !names.includes(shortName(nm))) names.push(shortName(nm));
      cls ??= c ?? null;
    }
    return {
      from: g[0].i,
      to: g[g.length - 1].i,
      fromDate: g[0].r.trade_date as string,
      toDate: g[g.length - 1].r.trade_date as string,
      netCr: net,
      buyers: names.slice(0, 2),
      buyerClass: cls,
      churnCr: churn,
      anchorPrice: bars[g[0].i].low,
    };
  }
  return null;
}

function downStreak(bars: readonly OHLCBar[]): { days: number; volRising: boolean } {
  let k = 0;
  for (let i = bars.length - 1; i > 0 && bars[i].close < bars[i - 1].close; i--) k++;
  let rising = k >= 2;
  for (let i = bars.length - k + 1; i < bars.length && rising; i++) {
    const v0 = bars[i - 1].volume;
    const v1 = bars[i].volume;
    if (v0 == null || v1 == null || !(v1 > v0)) rising = false;
  }
  return { days: k, volRising: rising };
}

export function buildRead(input: ReadInput): ReadModel {
  const { bars, darvas: d, stats, emas, tf = 'D' } = input;
  const n = bars.length;
  const empty: ReadModel = { status: [], stats: [], read: [], levels: [], deals: [], cluster: null, breakout: null };
  if (!n) return empty;
  const close = bars[n - 1].close;
  const u = unit(tf);
  const deals = dealLevels(bars, input.deals);
  const cluster = latestCluster(bars, input.deals);
  const brk = latestBreakout(bars, d);
  const box = d.current;

  // ---------------------------------------------------------------- status chips
  const status: Chip[] = [];
  if (brk?.failed)
    status.push({
      label: 'Failed breakout',
      tone: 'bad',
      title: `Broke out on ${fmtDateShort(brk.date)}, closed back under ${px(brk.top)}`,
    });
  else if (brk) status.push({ label: `Breakout ${fmtDateShort(brk.date)}`, tone: 'good' });
  let boxState: 'above' | 'inside' | 'below' | null = null;
  if (box) {
    boxState = close > box.top ? 'above' : close < box.bottom ? 'below' : 'inside';
    const word = boxState === 'above' ? 'Above' : boxState === 'below' ? 'Below' : 'Inside';
    status.push({
      label: `${word} box ${px(box.bottom)}-${px(box.top)}`,
      tone: boxState === 'below' ? 'warn' : boxState === 'above' ? 'good' : 'neutral',
    });
  }
  const near = deals.find((x) => x.letter !== 'S' && Math.abs(pct(close, x.price)) <= 2);
  const mainDeal = near ?? deals.find((x) => x.letter !== 'S') ?? null;
  if (mainDeal) {
    const who = mainDeal.label.startsWith('Deal') ? 'deal' : mainDeal.label;
    const where = near ? 'On' : close > mainDeal.price ? 'Above' : 'Below';
    status.push({ label: `${where} ${who} ₹${px(mainDeal.price)}`, tone: where === 'Below' ? 'warn' : 'deal' });
  }

  // ---------------------------------------------------------------- stat chips
  const statChips: Chip[] = [];
  if (stats.fromHighPct != null) statChips.push({ label: `${sgn(stats.fromHighPct, 0)} from 52W high`, tone: 'neutral' });
  if (stats.atrPct != null)
    statChips.push({ label: `ATR ${fmtNum(stats.atrPct, 1)}%`, tone: 'neutral', title: 'Average true range (14) as % of the close' });
  if (stats.crPerDay != null)
    statChips.push({
      label: `₹${fmtNum(stats.crPerDay, stats.crPerDay >= 10 ? 0 : 1)} Cr/day`,
      tone: 'neutral',
      title: '20-day average traded value',
    });
  if (stats.delivPct != null) statChips.push({ label: `Deliv ${fmtNum(stats.delivPct, 0)}%`, tone: 'neutral' });
  if (stats.rsi != null)
    statChips.push({ label: `RSI ${fmtNum(stats.rsi, 0)}`, tone: stats.rsi < 40 ? 'warn' : stats.rsi > 70 ? 'warn' : 'neutral' });

  // ---------------------------------------------------------------- key levels
  const levels: KeyLevel[] = [];
  const add = (label: string, v: number | null | undefined) => {
    if (v != null && Number.isFinite(v)) levels.push({ label, value: v, distPct: pct(v, close) });
  };
  if (box) {
    add('Box top', box.top);
    add('Box bottom', box.bottom);
  }
  deals.forEach((x) => add(x.label, x.price));
  ([10, 20, 50, 200] as const).forEach((p) => add(`EMA ${p}`, emas[p]));

  // ---------------------------------------------------------------- the read
  const read: string[] = [];
  if (brk?.failed) {
    const s = downStreak(bars);
    read.push(
      `Broke out of the ${px(brk.bottom)}-${px(brk.top)} box on ${fmtDateShort(brk.date)}.` +
        (s.days >= 2
          ? ` Then it fell ${s.days} straight ${u}s${s.volRising ? ', volume rising each ' + u : ''}.`
          : ` It closed back under ${px(brk.top)}.`),
    );
  } else if (brk) {
    read.push(
      `Broke out of the ${px(brk.bottom)}-${px(brk.top)} box on ${fmtDateShort(brk.date)}. It is ${sgn(pct(close, brk.top))} above that top.`,
    );
  } else if (box && boxState === 'inside') {
    read.push(
      `Inside the ${px(box.bottom)}-${px(box.top)} box for ${box.to - box.from + 1} ${u}s. A close above ${px(d.buyStop)} is the breakout.`,
    );
  } else if (box && boxState === 'below') {
    read.push(`Closed below the box bottom (${px(box.bottom)}). The box is ${px(box.bottom)}-${px(box.top)}.`);
  } else if (box && boxState === 'above') {
    read.push(`Closed above the ${px(box.bottom)}-${px(box.top)} box. It is ${sgn(pct(close, box.top))} above the top.`);
  } else {
    read.push('No Darvas box yet on this timeframe.');
  }
  if (brk?.failed && box && boxState === 'below') read.push(`Closed below the new box bottom (${px(box.bottom)}).`);

  if (mainDeal) {
    const who = mainDeal.label.startsWith('Deal') ? 'deal' : mainDeal.label;
    const buyers = mainDeal.label.startsWith('Deal') ? 'The deal buyers' : `The ${who.replace(' deal', '')} buyers`;
    const below = levels.filter((l) => l.value < mainDeal.price * 0.995 && l.label !== mainDeal.label).sort((a, b) => b.value - a.value)[0];
    const d1 = pct(close, mainDeal.price);
    if (near) {
      read.push(
        `It sits on the ${who} price (${px(mainDeal.price)}). ${buyers} are ${fmtNum(Math.abs(d1), 1)}% ${d1 >= 0 ? 'in profit' : 'in loss'}.` +
          (below ? ` A close under ${px(mainDeal.price)} opens ${px(below.value)}.` : ''),
      );
    } else if (close > mainDeal.price) {
      read.push(`It holds ${fmtNum(d1, 1)}% above the ${who} price (${px(mainDeal.price)}). ${buyers} are in profit.`);
    } else {
      read.push(`It lost the ${who} price (${px(mainDeal.price)}). ${buyers} are ${fmtNum(Math.abs(d1), 1)}% in loss.`);
    }
  }

  const e10 = emas[10];
  const e20 = emas[20];
  const e200 = emas[200];
  const r = stats.rsi;
  const shortTerm = [e10, e20].filter((v): v is number => v != null);
  let emaLine = '';
  if (shortTerm.length) {
    const under = shortTerm.filter((v) => close < v).length;
    emaLine =
      under === shortTerm.length
        ? `It is below the 10- and 20-${u} averages (${px(e10)}, ${px(e20)}).`
        : under === 0
          ? `It is above the 10- and 20-${u} averages (${px(e10)}, ${px(e20)}).`
          : `It is between the 10- and 20-${u} averages (${px(e10)}, ${px(e20)}).`;
    if (e200 != null)
      emaLine += close >= e200 ? ` The 200-${u} average (${px(e200)}) is below it.` : ` It is under the 200-${u} average (${px(e200)}).`;
  }
  if (r != null) emaLine += ` RSI is ${fmtNum(r, 0)}${r < 40 ? ', weak momentum' : r > 70 ? ', stretched' : ''}.`;
  if (emaLine.trim()) read.push(emaLine.trim());

  // What to do
  const belowShort = shortTerm.length > 0 && shortTerm.every((v) => close < v);
  let todo: string;
  if (box && boxState === 'below') todo = `What to do: no long setup until it closes above ${px(box.bottom)}.`;
  else if (brk?.failed) todo = `What to do: wait. Do not buy until it closes above ${px(brk.top)} again.`;
  else if (box && boxState === 'inside')
    todo = belowShort
      ? `What to do: wait for a close above the 20-${u} average (${px(e20)}) first.`
      : `What to do: set a buy stop at ${px(d.buyStop)} and a stop at ${px(d.stop)}.`;
  else if (box && boxState === 'above') todo = `What to do: hold. Keep the stop at ${px(d.stop)}.`;
  else
    todo = belowShort
      ? `What to do: stay out until it reclaims the 20-${u} average (${px(e20)}).`
      : 'What to do: wait for a Darvas box to form.';
  read.push(todo);

  // Keep the read to 4 lines: merge the extra box line into the first one when needed.
  while (read.length > 4) {
    const extra = read.splice(1, 1)[0];
    read[0] = `${read[0]} ${extra}`;
  }

  return { status, stats: statChips, read, levels, deals, cluster, breakout: brk };
}
