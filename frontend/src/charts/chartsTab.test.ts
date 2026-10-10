import { beforeEach, describe, expect, it } from 'vitest';
import { CHART_PREF_DEFAULTS, resetChartPrefsCache, setChartPrefs, useChartPrefs } from '../lib/chartPrefs';
import { buildChartLayers, dealLines, DEAL_LINE_BARS } from './chartLayers';
import { clickTool, drawingLayers, sanitize } from './drawings';
import { EVENT_COLORS, type DealCandleRow } from './eventCandles';
import { parseSource, parseSymbolText, peersList, sourceId } from './sources';
import type { PeerRow } from '../api/types';
import type { OHLCBar } from '../lib/indicators';

const days = (n: number) => {
  const out: string[] = [];
  const d = new Date(Date.UTC(2026, 0, 1));
  while (out.length < n) {
    out.push(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
};
const flatBars = (n: number): OHLCBar[] => days(n).map((time) => ({ time, open: 100, high: 101, low: 99, close: 100, volume: 1000 }));

describe('sources: peers + pasted lists', () => {
  it('parses peers:SYM', () => {
    expect(parseSource('peers:HAL')).toEqual({ kind: 'peers', key: 'HAL' });
    expect(parseSource('peers:bad sym')).toBeNull();
    expect(sourceId({ kind: 'peers', key: 'HAL' })).toBe('peers:HAL');
  });
  it('parses a TradingView export, lines and plain text', () => {
    expect(parseSymbolText('###Deals,NSE:HAL,NSE:BAJAJ_AUTO,NSE:M_M,BSE:500325,NSE:HAL')).toEqual(['HAL', 'BAJAJ-AUTO', 'M&M']);
    expect(parseSymbolText('hal\nbel  tcs; infy')).toEqual(['HAL', 'BEL', 'TCS', 'INFY']);
    expect(parseSymbolText('')).toEqual([]);
  });
  it('peers list: the stock first, then peers >= 1,000 Cr by strength', () => {
    const rows = [
      { symbol: 'A', rs_percentile: 50, market_cap_cr: 5000 },
      { symbol: 'B', rs_percentile: 90, market_cap_cr: 5000 },
      { symbol: 'C', rs_percentile: 99, market_cap_cr: 500 },
      { symbol: 'X', rs_percentile: 10, market_cap_cr: 800, is_target: true },
    ] as PeerRow[];
    expect(peersList(rows, 'X').map((i) => i.symbol)).toEqual(['X', 'B', 'A']);
    expect(peersList([], 'Z').map((i) => i.symbol)).toEqual(['Z']);
  });
});

describe('drawings', () => {
  it('horizontal line in one click, trend line in two (ordered by time)', () => {
    expect(clickTool('hline', null, { time: '2026-01-02', price: 10 }, 'x').done).toEqual({ id: 'x', kind: 'hline', a: { time: '2026-01-02', price: 10 } });
    const first = clickTool('trend', null, { time: '2026-01-05', price: 12 }, 'y');
    expect(first.done).toBeNull();
    const second = clickTool('trend', first.pending, { time: '2026-01-02', price: 10 }, 'y');
    expect(second.done).toEqual({ id: 'y', kind: 'trend', a: { time: '2026-01-02', price: 10 }, b: { time: '2026-01-05', price: 12 } });
    expect(second.pending).toBeNull();
    expect(clickTool('none', null, { time: '2026-01-02', price: 1 }).done).toBeNull();
  });
  it('sanitizes stored drawings and maps them to levels / segments', () => {
    const store = sanitize({ HAL: [{ id: 'a', kind: 'hline', a: { time: 't', price: 1 } }, { id: 'b', kind: 'trend', a: { time: 't', price: 1 } }, 'junk'], X: 'bad' });
    expect(store).toEqual({ HAL: [{ id: 'a', kind: 'hline', a: { time: 't', price: 1 } }] });
    const l = drawingLayers([
      { id: 'a', kind: 'hline', a: { time: '2026-01-02', price: 5 } },
      { id: 'b', kind: 'trend', a: { time: '2026-01-02', price: 5 }, b: { time: '2026-01-09', price: 7 } },
    ]);
    expect(l.levels.map((x) => x.price)).toEqual([5]);
    expect(l.segments[0]).toMatchObject({ pane: 'price', from: { value: 5 }, to: { time: '2026-01-09', value: 7 } });
  });
});

describe('chart prefs: global settings, backward-compatible', () => {
  beforeEach(() => {
    localStorage.clear();
    resetChartPrefsCache();
  });
  it('defaults follow the spec (10/20/200 EMA, events on, RSI + divergences on, hidden off, RS pane off)', () => {
    expect(CHART_PREF_DEFAULTS).toMatchObject({
      style: 'candles',
      emas: [10, 20, 200],
      events: true,
      volPane: true,
      rsi: true,
      rsiDiv: true,
      rsiHidden: false,
      rsPane: false,
      darvas: true,
    });
  });
  it('old stored prefs keep their keys and gain the new defaults; junk is dropped', () => {
    localStorage.setItem('mp.chartprefs.v1', JSON.stringify({ darvas: false, bm: 'nifty50', style: 'weird', emas: [10, 33, 50] }));
    resetChartPrefsCache();
    let got: ReturnType<typeof useChartPrefs>[0] | null = null;
    // Read through the setter path (no React needed): patch nothing, then read storage back.
    setChartPrefs({});
    got = JSON.parse(localStorage.getItem('mp.chartprefs.v1') ?? '{}');
    expect(got).toMatchObject({ darvas: false, bm: 'nifty50', style: 'candles', emas: [10, 50], rsi: true });
  });
});

const dealRow = (p: Partial<DealCandleRow>): DealCandleRow =>
  ({ trade_date: '2026-01-05', letter: 'B', net_cr: 10, deal_price: 100, deal_price_adj: 100, show_line: true, status: 'holding', ...p }) as DealCandleRow;

describe('chart layers', () => {
  it('deal-price lines run 20 sessions (D) from the deal bar, only for show_line rows', () => {
    const t = days(40);
    const segs = dealLines([dealRow({}), dealRow({ trade_date: '2026-01-07', show_line: false })], t, 'D');
    expect(segs).toHaveLength(1);
    expect(segs[0]).toMatchObject({ from: { time: '2026-01-05', value: 100 }, to: { time: t[4 + DEAL_LINE_BARS.D], value: 100 }, dashed: true, axisLabel: 'B holding' });
    expect(segs[0].color).toBe(EVENT_COLORS.deal_B);
    // A deal near the end stops at the last bar.
    expect(dealLines([dealRow({ trade_date: t[38] })], t, 'D')[0].to.time).toBe(t[39]);
  });
  it('builds candle colours, a letter marker and a hover note for a deal day', () => {
    const bars = flatBars(40);
    const prefs = { ...CHART_PREF_DEFAULTS };
    const l = buildChartLayers({ bars, tf: 'D', prefs, deals: [dealRow({})] });
    expect(l.candleColors).toEqual([{ time: '2026-01-05', color: EVENT_COLORS.deal_B }]);
    expect(l.markers[0]).toMatchObject({ time: '2026-01-05', text: 'B', color: EVENT_COLORS.deal_B, position: 'aboveBar' });
    expect(l.barNote('2026-01-05')).toContain('Net buy');
    expect(l.barNote('2026-01-06')).toBeNull();
    expect(l.emaPeriods).toEqual([10, 20, 200]);
    expect(l.rsi).toEqual({ period: 14 });
    expect(l.segments.some((s) => s.id.startsWith('deal-'))).toBe(true);
    // Events off: nothing painted, no deal lines.
    const off = buildChartLayers({ bars, tf: 'D', prefs: { ...prefs, events: false }, deals: [dealRow({})] });
    expect(off.candleColors).toEqual([]);
    expect(off.segments).toEqual([]);
    // Deals group off: no deal colour and no deal line.
    const noDeals = buildChartLayers({ bars, tf: 'D', prefs: { ...prefs, eventGroups: { deals: false } }, deals: [dealRow({})] });
    expect(noDeals.candleColors).toEqual([]);
    expect(noDeals.segments).toEqual([]);
  });
  it('divergence lines appear on both panes', () => {
    // A steep rally to a high (RSI 86), a pullback, then a choppy grind to a higher high (RSI 70), then a drop.
    const closes: number[] = [];
    for (let i = 0; i < 30; i++) closes.push(100 + (i % 2 ? 0.5 : -0.5));
    for (let i = 0; i < 8; i++) closes.push(closes[closes.length - 1] + 3);
    for (let i = 0; i < 8; i++) closes.push(closes[closes.length - 1] - 2);
    for (let i = 0; i < 20; i++) closes.push(closes[closes.length - 1] + (i % 2 === 0 ? 3 : -1));
    for (let i = 0; i < 8; i++) closes.push(closes[closes.length - 1] - 2);
    const t = days(closes.length);
    const bars = closes.map((c, i) => ({ time: t[i], open: c, high: c + 0.2, low: c - 0.2, close: c, volume: 1000 }));
    const l = buildChartLayers({ bars, tf: 'D', prefs: { ...CHART_PREF_DEFAULTS, events: false } });
    expect(l.divergences.map((d) => [d.kind, d.from.index, d.to.index])).toEqual([['bear', 37, 64]]);
    const ids = l.segments.map((s) => s.pane);
    expect(ids).toContain('price');
    expect(ids).toContain('rsi');
    const noDiv = buildChartLayers({ bars, tf: 'D', prefs: { ...CHART_PREF_DEFAULTS, events: false, rsiDiv: false } });
    expect(noDiv.segments).toEqual([]);
  });
});
