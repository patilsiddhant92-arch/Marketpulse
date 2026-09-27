import { describe, expect, it } from 'vitest';
import { ema, resampleBars, type OHLCBar } from './indicators';
import { formatTradingViewList, toTradingViewSymbol } from './tradingview';

describe('TradingView formatter', () => {
  it('prefixes NSE:, maps - to _, upper-cases', () => {
    expect(toTradingViewSymbol('bajaj-auto')).toBe('NSE:BAJAJ_AUTO');
    expect(toTradingViewSymbol('M&M')).toBe('NSE:M&M');
  });
  it('de-duplicates across sections, skips blanks, reports the true count', () => {
    const out = formatTradingViewList([
      { title: 'Squeeze', symbols: ['HAL', 'BEL', 'HAL', '', null] },
      { title: 'VCP', symbols: ['bel', 'ABB'] },
      { title: 'Empty', symbols: [] },
    ]);
    expect(out.text).toBe('###Squeeze,NSE:HAL,NSE:BEL,###VCP,NSE:ABB');
    expect(out.count).toBe(3);
  });
});

describe('ema', () => {
  it('seeds with SMA and is NULL before the period', () => {
    const out = ema([1, 2, 3, 4, 5], 3);
    expect(out.slice(0, 2)).toEqual([null, null]);
    expect(out[2]).toBe(2);
    expect(out[3]).toBeCloseTo(3);
    expect(out[4]).toBeCloseTo(4);
    expect(ema([1, 2], 3)).toEqual([null, null]);
  });
});

describe('resampleBars', () => {
  const bar = (time: string, o: number, h: number, l: number, c: number, v: number | null, d: number | null): OHLCBar => ({
    time,
    open: o,
    high: h,
    low: l,
    close: c,
    volume: v,
    delivery_pct: d,
  });
  const daily = [
    bar('2026-09-21', 10, 12, 9, 11, 100, 50), // Mon
    bar('2026-09-22', 11, 13, 10, 12, 300, 30),
    bar('2026-09-25', 12, 14, 8, 13, 100, null), // Fri
    bar('2026-09-28', 13, 15, 12, 14, 50, 40), // next Mon
    bar('2026-10-01', 14, 16, 13, 15, 50, 60),
  ];
  it('builds weekly bars stamped on the last session', () => {
    const w = resampleBars(daily, 'W');
    expect(w).toHaveLength(2);
    expect(w[0]).toMatchObject({ time: '2026-09-25', open: 10, high: 14, low: 8, close: 13, volume: 500 });
    // volume-weighted delivery, NULL day excluded: (50*100 + 30*300) / 400
    expect(w[0].delivery_pct).toBeCloseTo(35);
  });
  it('builds monthly bars', () => {
    const m = resampleBars(daily, 'M');
    expect(m.map((b) => b.time)).toEqual(['2026-09-28', '2026-10-01']);
    expect(m[1].delivery_pct).toBe(60);
  });
  it('returns a copy for D', () => {
    const d = resampleBars(daily, 'D');
    expect(d).toEqual(daily);
    expect(d).not.toBe(daily);
  });
});
