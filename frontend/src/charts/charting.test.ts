import { describe, expect, it } from 'vitest';
import { rsi, sma } from '../lib/indicators';
import { volumeAlpha, volumeWidth, withAlpha } from '../ui/volumeCandleSeries';
import { findPivots, rsiDivergences, type DivBar } from './divergence';
import {
  EVENT_COLORS,
  calendarEvents,
  dealEvent,
  priceEvents,
  resolveEvents,
  type DealCandleRow,
} from './eventCandles';

const days = (n: number) => Array.from({ length: n }, (_, i) => `2026-01-${String(i + 1).padStart(2, '0')}`);

describe('indicators: rsi / sma', () => {
  it('sma window, null breaks it', () => {
    expect(sma([1, 2, 3, 4], 2)).toEqual([null, 1.5, 2.5, 3.5]);
    expect(sma([1, null, 3, 4, 5], 2)).toEqual([null, null, null, 3.5, 4.5]);
  });
  it('rsi: all gains = 100, all losses = 0, Wilder smoothing', () => {
    const up = Array.from({ length: 20 }, (_, i) => 100 + i);
    expect(rsi(up, 14)[14]).toBe(100);
    expect(rsi(up, 14)[13]).toBeNull();
    const down = up.slice().reverse();
    expect(rsi(down, 14)[19]).toBe(0);
    // Alternating +1 / -1 changes: average gain = average loss -> 50.
    const zig = Array.from({ length: 30 }, (_, i) => 100 + (i % 2));
    const z = rsi(zig, 14)[29] as number;
    expect(z).toBeGreaterThan(45);
    expect(z).toBeLessThan(55);
  });
});

describe('divergence: pivots', () => {
  it('finds a pivot only with 5 bars confirmed on each side', () => {
    const v = [1, 2, 3, 4, 5, 9, 5, 4, 3, 2, 1, 0];
    expect(findPivots(v, 'high', 5, 5)).toEqual([5]);
    // Not confirmed yet (only 4 bars after) -> no pivot (never repaints).
    expect(findPivots(v.slice(0, 10), 'high', 5, 5)).toEqual([]);
    expect(findPivots(v.map((x) => -x), 'low', 5, 5)).toEqual([5]);
  });
  it('a flat top pivots once', () => {
    const v = [1, 2, 3, 4, 5, 9, 9, 4, 3, 2, 1, 0, 0];
    expect(findPivots(v, 'high', 5, 5)).toEqual([5]);
  });
});

/** Build bars + RSI with two RSI peaks at a and b (or troughs). */
function scenario(opts: { n: number; a: number; b: number; rsiA: number; rsiB: number; pxA: number; pxB: number; low?: boolean }) {
  const t = days(opts.n);
  const rsiV: (number | null)[] = Array.from({ length: opts.n }, () => 50);
  const bars: DivBar[] = t.map((time) => ({ time, high: 100, low: 90 }));
  rsiV[opts.a] = opts.rsiA;
  rsiV[opts.b] = opts.rsiB;
  if (opts.low) {
    bars[opts.a] = { ...bars[opts.a], low: opts.pxA };
    bars[opts.b] = { ...bars[opts.b], low: opts.pxB };
  } else {
    bars[opts.a] = { ...bars[opts.a], high: opts.pxA };
    bars[opts.b] = { ...bars[opts.b], high: opts.pxB };
  }
  return { bars, rsiV };
}

describe('divergence: rules', () => {
  it('regular bearish: price higher high, RSI lower high, first RSI > 60', () => {
    const { bars, rsiV } = scenario({ n: 40, a: 10, b: 25, rsiA: 75, rsiB: 65, pxA: 110, pxB: 120 });
    const d = rsiDivergences(bars, rsiV);
    expect(d).toHaveLength(1);
    expect(d[0].kind).toBe('bear');
    expect(d[0].from).toMatchObject({ index: 10, price: 110, rsi: 75 });
    expect(d[0].to).toMatchObject({ index: 25, price: 120, rsi: 65 });
    expect(d[0].confirmedAt).toBe(30);
  });
  it('no bearish when the first RSI high is <= 60', () => {
    const { bars, rsiV } = scenario({ n: 40, a: 10, b: 25, rsiA: 58, rsiB: 55, pxA: 110, pxB: 120 });
    expect(rsiDivergences(bars, rsiV)).toEqual([]);
  });
  it('regular bullish: price lower low, RSI higher low, first RSI < 40', () => {
    const { bars, rsiV } = scenario({ n: 40, a: 8, b: 20, rsiA: 25, rsiB: 35, pxA: 80, pxB: 75, low: true });
    const d = rsiDivergences(bars, rsiV);
    expect(d.map((x) => x.kind)).toEqual(['bull']);
  });
  it('pivots must be 5-60 bars apart', () => {
    const far = scenario({ n: 90, a: 10, b: 75, rsiA: 75, rsiB: 65, pxA: 110, pxB: 120 });
    expect(rsiDivergences(far.bars, far.rsiV)).toEqual([]);
    const ok = scenario({ n: 90, a: 10, b: 70, rsiA: 75, rsiB: 65, pxA: 110, pxB: 120 });
    expect(rsiDivergences(ok.bars, ok.rsiV)).toHaveLength(1);
  });
  it('the second pivot inside the last 5 bars is not reported yet', () => {
    const { bars, rsiV } = scenario({ n: 29, a: 10, b: 25, rsiA: 75, rsiB: 65, pxA: 110, pxB: 120 });
    expect(rsiDivergences(bars, rsiV)).toEqual([]);
  });
  it('hidden divergences only when asked', () => {
    const { bars, rsiV } = scenario({ n: 40, a: 10, b: 25, rsiA: 65, rsiB: 75, pxA: 120, pxB: 110 });
    expect(rsiDivergences(bars, rsiV)).toEqual([]);
    expect(rsiDivergences(bars, rsiV, { hidden: true }).map((x) => x.kind)).toEqual(['hidden_bear']);
  });
});

const deal = (p: Partial<DealCandleRow>): DealCandleRow =>
  ({
    trade_date: '2026-01-05',
    letter: 'B',
    net_cr: 57.8,
    buy_cr: 57.8,
    sell_cr: 0,
    gross_cr: 57.8,
    deal_price: 1174.9,
    deal_price_adj: 1174.9,
    top_buyer: 'SBI MF',
    top_buyer_class: 'DII',
    top_seller: null,
    top_seller_class: null,
    show_line: true,
    status: 'holding',
    ...p,
  }) as DealCandleRow;

describe('deal candles: mapping', () => {
  it('maps each letter to its one colour and hover text', () => {
    const b = dealEvent(deal({}))!;
    expect(b).toMatchObject({ key: 'deal_B', letter: 'B', color: EVENT_COLORS.deal_B, paints: true, date: '2026-01-05' });
    expect(b.text).toContain('Net buy');
    expect(b.text).toContain('SBI MF (DII)');
    expect(b.text).toContain('deal price ₹1,174.9');
    expect(b.text).toContain('now holding');
    expect(dealEvent(deal({ letter: 'S', net_cr: -4, top_seller: 'X' }))!).toMatchObject({ color: EVENT_COLORS.deal_S, letter: 'S' });
    expect(dealEvent(deal({ letter: 'P' }))!.color).toBe('ev-placement');
    expect(dealEvent(deal({ letter: 'T' }))!.color).toBe(EVENT_COLORS.deal_T);
    expect(dealEvent(deal({ letter: 'C' }))!.text).toContain('Churn');
    expect(dealEvent(deal({ letter: 'Z' }))).toBeNull();
    expect(dealEvent(deal({ trade_date: null }))).toBeNull();
  });
  it('a deal on a weekly bar snaps to that week and beats a gap (priority 2 vs 5)', () => {
    const weekBars = ['2026-01-02', '2026-01-09', '2026-01-16'];
    const events = [
      dealEvent(deal({ trade_date: '2026-01-06' }))!,
      { date: '2026-01-08', key: 'gap_up' as const, letter: 'G', color: EVENT_COLORS.gap_up, text: 'gap', paints: true },
    ];
    const m = resolveEvents(weekBars, events);
    expect([...m.keys()]).toEqual(['2026-01-09']);
    expect(m.get('2026-01-09')!.top.key).toBe('deal_B');
    expect(m.get('2026-01-09')!.all).toHaveLength(2);
  });
  it('results beat deals; disabled groups are dropped; ex-date is a chip only', () => {
    const t = ['2026-01-05', '2026-01-06'];
    const ev = [
      dealEvent(deal({}))!,
      ...calendarEvents([
        { event_date: '2026-01-05', event_type: 'financial_results', headline: 'Q3 results', source: 's', upcoming: false },
        { event_date: '2026-01-06', event_type: 'dividend', headline: 'Dividend', source: 's', upcoming: false },
        { event_date: '2026-01-09', event_type: 'financial_results', headline: 'future', source: 's', upcoming: true },
      ]),
    ];
    const m = resolveEvents(t, ev);
    expect(m.get('2026-01-05')!.top.key).toBe('results');
    expect(m.get('2026-01-06')!.top).toMatchObject({ key: 'ex_date', paints: false });
    const off = resolveEvents(t, ev, { results: false });
    expect(off.get('2026-01-05')!.top.key).toBe('deal_B');
  });
  it('volume spike paints only when alone on the bar', () => {
    const t = ['2026-01-05'];
    const v = { date: '2026-01-05', key: 'volume' as const, letter: 'V', color: 'fg' as const, text: 'v', paints: true };
    expect(resolveEvents(t, [v]).get('2026-01-05')!.top).toMatchObject({ key: 'volume', paints: true });
    const ex = { date: '2026-01-05', key: 'ex_date' as const, letter: 'E', color: 'ev-churn' as const, text: 'e', paints: false };
    expect(resolveEvents(t, [v, ex]).get('2026-01-05')!.top.key).toBe('volume');
  });
});

describe('event candles: price events', () => {
  const mk = (n: number) =>
    days(n).map((time) => ({ time, open: 100, high: 101, low: 99, close: 100, volume: 1000 }));
  it('box-top breakout on >= 1.5x volume, gap, 3x volume', () => {
    const bars = mk(25);
    bars[22] = { ...bars[22], open: 100, close: 106, high: 106, volume: 1600 };
    bars[24] = { ...bars[24], open: 110, close: 111, high: 112, volume: 3500 };
    const boxes = bars.map((b) => ({ trade_date: b.time, top: 105, bottom: 95 }));
    const ev = priceEvents(bars, boxes);
    // Bar 24 also closes back above the box top from a close inside it (bar 23) on 3.5x volume.
    expect(ev.filter((e) => e.key === 'breakout').map((e) => e.date)).toEqual([bars[22].time, bars[24].time]);
    expect(ev.find((e) => e.key === 'gap_up')?.date).toBe(bars[24].time);
    expect(ev.find((e) => e.key === 'volume')?.date).toBe(bars[24].time);
    // Not enough history for a 20-bar average -> no volume events before bar 20.
    const early = priceEvents(mk(10).map((b, i) => (i === 5 ? { ...b, volume: 99999 } : b)), []);
    expect(early.filter((e) => e.key === 'volume')).toEqual([]);
  });
  it('box-bottom break needs volume too', () => {
    const bars = mk(22);
    bars[21] = { ...bars[21], close: 94, low: 93, volume: 1000 };
    const boxes = bars.map((b) => ({ trade_date: b.time, top: 105, bottom: 95 }));
    expect(priceEvents(bars, boxes).some((e) => e.key === 'breakdown')).toBe(false);
    bars[21] = { ...bars[21], volume: 2000 };
    expect(priceEvents(bars, boxes).some((e) => e.key === 'breakdown')).toBe(true);
  });
});

describe('volume candles', () => {
  it('width scales with relative volume, clamped', () => {
    expect(volumeWidth(1000, 1000)).toBeCloseTo(0.45);
    expect(volumeWidth(2000, 1000)).toBeCloseTo(0.9);
    expect(volumeWidth(10000, 1000)).toBe(1);
    expect(volumeWidth(10, 1000)).toBe(0.12);
    expect(volumeWidth(null, 1000)).toBe(0.45);
    expect(volumeAlpha(3000, 1000)).toBe(1);
    expect(volumeAlpha(0, 1000)).toBe(0.35);
    expect(withAlpha(`#${'ff0080'}`, 0.5)).toBe('rgba(255, 0, 128, 0.5)');
    expect(withAlpha('rgba(1, 2, 3, 1)', 0.4)).toBe('rgba(1, 2, 3, 0.4)');
    expect(withAlpha('red', 0.4)).toBe('red');
  });
});
