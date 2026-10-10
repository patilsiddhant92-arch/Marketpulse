/**
 * Chart v2 pure layers (HarkPro/12-sprint2-plan.md): volume-candle widths, Darvas boxes and stops,
 * the divergence port (parity with HarkPro/tools/divergence/detect_prototype.py on real bars), the
 * divergence contract parser, the read model and its house style, the Info layers and the tools.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import type { DarvasRow } from '../api/types';
import type { OHLCBar } from '../lib/indicators';
import { buildRead, dealLevels, latestCluster, px, shortName } from './chartRead';
import { CHART_V2_DEFAULTS, parseSettings, resetChartSettingsCache, setChartSettings } from './chartSettings';
import { buildV2Model } from './chartV2Model';
import { darvasModel, darvasRowsUpTo } from './darvasBoxes';
import { classifyDivergence, detectDivergences, divergenceViews, type DivergenceRow } from './divergence';
import { parseDivergenceRows } from './divergenceApi';
import { clickTool, measureText, positionTarget, sanitize } from './drawings';
import type { DealCandleRow } from './eventCandles';
import { anchoredVwap, roundTick, tickSize, VOL_CANDLE_MAX, VOL_CANDLE_MIN, volCandleMultipliers } from './series';
import parity from './__fixtures__/divergenceParity.json';

const day = (i: number) => new Date(Date.UTC(2026, 0, 1 + i)).toISOString().slice(0, 10);

function mkBars(closes: number[], vol: (i: number) => number = () => 1000): OHLCBar[] {
  return closes.map((c, i) => ({
    time: day(i),
    open: i ? closes[i - 1] : c,
    high: c * 1.01,
    low: c * 0.99,
    close: c,
    volume: vol(i),
    delivery_pct: 50,
  }));
}

describe('volume candles', () => {
  it('width multiplier = volume / average of the 20 bars before, clamped 0.35-3×', () => {
    const bars = mkBars(
      Array.from({ length: 30 }, () => 100),
      (i) => (i === 25 ? 10_000 : i === 26 ? 100 : i === 27 ? 1500 : 1000),
    );
    const m = volCandleMultipliers(bars);
    expect(m[5]).toBe(1); // no 20-bar history yet
    expect(m[25]).toBe(VOL_CANDLE_MAX);
    expect(m[26]).toBe(VOL_CANDLE_MIN);
    // The 20 bars before bar 27 hold the 10,000 spike: average 1,405, so 1,500 is 1.07×.
    expect(m[27]).toBeCloseTo(1500 / 1405, 6);
  });
});

describe('ticks and VWAP', () => {
  it('NSE tick bands', () => {
    expect(tickSize(120)).toBe(0.01);
    expect(tickSize(947)).toBe(0.05);
    expect(tickSize(4200)).toBe(0.1);
    expect(roundTick(947.0 + 0.05, 0.05)).toBeCloseTo(947.05, 6);
  });
  it('anchored VWAP starts at the anchor', () => {
    const bars = mkBars([10, 20, 30]);
    const v = anchoredVwap(bars, 1);
    expect(v[0]).toBeNull();
    expect(v[1]).toBeCloseTo(20, 6);
    expect(v[2]).toBeCloseTo(25, 6);
  });
});

// Two boxes: 90-100 on bars 0-9, 95-110 on bars 10-19 (current), projections after the last bar.
function boxRows(bars: OHLCBar[]): DarvasRow[] {
  const rows: DarvasRow[] = bars.map((b, i) => ({
    trade_date: b.time,
    top: i < 10 ? 100 : 110,
    bottom: i < 10 ? 90 : 95,
    projected: false,
    top_extension: i === bars.length - 1 ? 110 : null,
    ema_10_projection: i === bars.length - 1 ? 104 : null,
  }));
  for (let k = 1; k <= 5; k++)
    rows.push({
      trade_date: day(bars.length - 1 + k),
      top: null,
      bottom: null,
      projected: true,
      top_extension: 110,
      ema_10_projection: 104 - k,
    });
  return rows;
}

describe('Darvas boxes', () => {
  it('runs of equal top / bottom become boxes; the last one is current with buy stop + 1 tick and stop − 1 tick', () => {
    const bars = mkBars(Array.from({ length: 20 }, () => 100));
    const d = darvasModel(boxRows(bars), bars);
    expect(d.boxes.map((b) => [b.from, b.to, b.top, b.bottom, b.current])).toEqual([
      [0, 9, 100, 90, false],
      [10, 19, 110, 95, true],
    ]);
    expect(d.buyStop).toBeCloseTo(110.01, 6);
    expect(d.stop).toBeCloseTo(94.99, 6);
    expect(d.topExtension.map((p) => p.k)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(d.emaProjection[5].value).toBe(99);
  });
  it('replay drops projections and later rows', () => {
    const bars = mkBars(Array.from({ length: 20 }, () => 100));
    const rows = darvasRowsUpTo(boxRows(bars), day(12));
    expect(rows.every((r) => !r.projected && (r.trade_date as string) <= day(12))).toBe(true);
  });
});

describe('divergences', () => {
  it('classify follows the prototype table', () => {
    expect(classifyDivergence(-1, 5, 'bull')).toBe('Strong');
    expect(classifyDivergence(0.2, 5, 'bull')).toBe('Medium');
    expect(classifyDivergence(-1, 1, 'bull')).toBe('Weak');
    expect(classifyDivergence(1, -5, 'bull')).toBe('Hidden');
    expect(classifyDivergence(1, -5, 'bear')).toBe('Strong');
    expect(classifyDivergence(-1, 5, 'bear')).toBe('Hidden');
    expect(classifyDivergence(0.1, 0.1, 'bear')).toBeNull();
  });

  it.each(Object.keys(parity))('client detection matches detect_prototype.py on %s (real bars)', (sym) => {
    const fx = (
      parity as Record<
        string,
        {
          bars: { time: string; high: number; low: number; close: number }[];
          expected: { side: string; type: string; p1_date: string; p2_date: string; trigger: number }[];
        }
      >
    )[sym];
    const got = detectDivergences(fx.bars).map(
      (r) => `${r.side}|${r.type}|${r.p1_date}|${r.p2_date}|${(r.trigger_price as number).toFixed(2)}`,
    );
    const want = fx.expected.map((e) => `${e.side}|${e.type}|${e.p1_date}|${e.p2_date}|${e.trigger.toFixed(2)}`);
    expect(got.sort()).toEqual(want.sort());
  });

  it('no look-ahead: the last 3 bars never hold a pivot, confirm = pivot + 3 bars', () => {
    const fx = (parity as Record<string, { bars: { time: string; high: number; low: number; close: number }[] }>).IDEAFORGE;
    const rows = detectDivergences(fx.bars);
    const idx = new Map(fx.bars.map((b, i) => [b.time, i]));
    for (const r of rows) expect(idx.get(r.confirm_date)! - idx.get(r.p2_date)!).toBe(3);
    const cut = detectDivergences(fx.bars.slice(0, 200));
    const full = new Set(rows.map((r) => `${r.side}${r.p1_date}${r.p2_date}`));
    for (const r of cut) expect(full.has(`${r.side}${r.p1_date}${r.p2_date}`)).toBe(true);
  });

  it('parses the served contract and drops malformed rows', () => {
    const rows = parseDivergenceRows([
      {
        side: 'bear',
        type: 'Strong',
        p1_date: '2026-05-06',
        p2_date: '2026-05-15',
        p1_price: 1,
        p2_price: 2,
        p1_rsi: 80,
        p2_rsi: 70,
        confirm_date: '2026-05-20',
        trigger_price: 0.9,
        stop_price: 2.1,
        status: 'triggered',
        bars_apart: 7,
      },
      { side: 'sideways', type: 'Strong' },
      { side: 'bull', type: 'Weak', p1_date: '2026-05-06', p2_date: null },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].status).toBe('triggered');
  });

  it('views: hidden only on request, cut at the replay date, the latest one bright', () => {
    const r = (d: string, type: DivergenceRow['type'] = 'Strong'): DivergenceRow => ({
      side: 'bear',
      type,
      p1_date: d,
      p2_date: d,
      p1_price: 1,
      p2_price: 1,
      p1_rsi: 70,
      p2_rsi: 65,
      confirm_date: d,
      trigger_price: 1,
      stop_price: 1,
      status: 'watching',
    });
    const rows = [r('2026-01-05'), r('2026-02-05', 'Hidden'), r('2026-03-05')];
    expect(divergenceViews(rows).map((v) => [v.row.p1_date, v.latest])).toEqual([
      ['2026-01-05', false],
      ['2026-03-05', true],
    ]);
    expect(divergenceViews(rows, { hidden: true, upTo: '2026-02-28' }).map((v) => [v.row.type, v.latest])).toEqual([
      ['Strong', false],
      ['Hidden', true],
    ]);
    expect(divergenceViews(rows)[1].label).toBe('Bear Strong');
  });
});

// A failed breakout: box 90-100, breakout on bar 30, then four straight down days on rising volume
// into a new 95-110 box, with an FII net buy at 92 still holding.
function failedBreakoutCase() {
  const closes = [...Array.from({ length: 30 }, (_, i) => 95 + (i % 3)), 104, 108, 106, 101, 97, 93];
  const vol = (i: number) => (i >= 32 ? 1000 + (i - 31) * 400 : 1000);
  const bars = mkBars(closes, vol);
  const rows: DarvasRow[] = bars.map((b, i) => ({
    trade_date: b.time,
    top: i <= 30 ? 100 : 110,
    bottom: i <= 30 ? 90 : 95,
    projected: false,
  }));
  const deals: DealCandleRow[] = [
    {
      trade_date: bars[20].time,
      letter: 'B',
      net_cr: 10,
      deal_price: 85,
      deal_price_adj: 85,
      top_buyer: 'BNP PARIBAS ARBITRAGE',
      top_buyer_class: 'FII',
      top_buyer_cr: 10,
      show_line: true,
      status: 'holding',
    },
    { trade_date: bars[22].time, letter: 'C', net_cr: 0, gross_cr: 302, show_line: false },
    {
      trade_date: bars[24].time,
      letter: 'B',
      net_cr: 56.6,
      gross_cr: 60,
      deal_price: 92,
      deal_price_adj: 92,
      top_buyer: 'SOCIETE GENERALE',
      top_buyer_class: 'FII',
      top_buyer_cr: 40,
      show_line: true,
      status: 'holding',
    },
  ];
  return { bars, rows, deals };
}

describe('the read', () => {
  it('failed breakout: chips, read lines in house style, key levels with distances', () => {
    const { bars, rows, deals } = failedBreakoutCase();
    const d = darvasModel(rows, bars);
    const m = buildRead({
      bars,
      darvas: d,
      deals,
      emas: { 10: 100, 20: 99, 200: 80 },
      stats: { fromHighPct: -13, atrPct: 4.8, crPerDay: 23, delivPct: 46, rsi: 35 },
    });
    expect(m.breakout).toMatchObject({ index: 30, top: 100, failed: true });
    expect(m.status.map((c) => c.label)).toEqual(['Failed breakout', 'Below box 95-110', 'On FII deal ₹92']);
    expect(m.stats.map((c) => c.label)).toEqual(['−13% from 52W high', 'ATR 4.8%', '₹23 Cr/day', 'Deliv 46%', 'RSI 35']);
    expect(m.read[0]).toMatch(/^Broke out of the 90-100 box on .+\. Then it fell 4 straight days, volume rising each day\./);
    expect(m.read.join(' ')).toContain('It sits on the FII deal price (92)');
    expect(m.read.join(' ')).toContain('A close under 92 opens 85.');
    expect(m.read[m.read.length - 1]).toBe('What to do: no long setup until it closes above 95.');
    // House style (04-writing-style): ≤ 4 lines, no semicolons, ≤ 20 words a sentence, "average" not "EMA".
    expect(m.read.length).toBeLessThanOrEqual(4);
    for (const line of m.read) {
      expect(line).not.toContain(';');
      expect(line).not.toMatch(/\bEMA\b/);
      for (const s of line.split(/(?<=\.)\s+/)) expect(s.split(/\s+/).length).toBeLessThanOrEqual(20);
    }
    const lv = Object.fromEntries(m.levels.map((l) => [l.label, l.distPct]));
    expect(lv['Box top']).toBeCloseTo((110 / 93 - 1) * 100, 6);
    expect(lv['FII deal']).toBeCloseTo((92 / 93 - 1) * 100, 6);
    expect(Object.keys(lv)).toContain('Deal 2');
  });

  it('deal cluster: net buy + top buyers, churn kept apart', () => {
    const { bars, deals } = failedBreakoutCase();
    const c = latestCluster(bars, deals)!;
    expect(c.netCr).toBeCloseTo(66.6, 6);
    expect(c.churnCr).toBe(302);
    expect(c.buyers).toEqual(['Societe Generale', 'BNP Paribas']);
    expect(c.buyerClass).toBe('FII');
    expect(dealLevels(bars, deals).map((l) => [l.label, l.price])).toEqual([
      ['FII deal', 92],
      ['Deal 2', 85],
    ]);
    expect(shortName('360 ONE PRIME')).toBe('360 ONE');
    expect(px(947)).toBe('947');
    expect(px(781.8)).toBe('781.8');
  });
});

describe('Chart v2 model', () => {
  it('Clean: EMAs + Darvas shapes + volume + RSI, no event colours / tags', () => {
    const { bars, rows, deals } = failedBreakoutCase();
    const m = buildV2Model({
      bars,
      tf: 'D',
      mode: 'clean',
      colours: 'events',
      emas: [10, 20, 200],
      rsi: true,
      divergences: true,
      darvasRows: rows,
      deals,
    });
    expect(m.lines.map((l) => [l.id, l.tag])).toEqual([
      ['ema10', 'E10'],
      ['ema20', 'E20'],
      ['ema200', 'E200'],
    ]);
    expect(m.shapes.filter((s) => s.kind === 'rect')).toHaveLength(2);
    expect(m.candleColors.size).toBe(0);
    expect(m.tags).toHaveLength(0);
    expect(m.rsi?.values.length).toBe(bars.length);
  });

  it('Info: event candles (Events colours), box + deal tags, buy stop / stop, breakout label, callout', () => {
    document.documentElement.style.setProperty('--c-ev-buy', '20 184 166');
    const { bars, rows, deals } = failedBreakoutCase();
    const m = buildV2Model({
      bars,
      tf: 'D',
      mode: 'info',
      colours: 'events',
      emas: [10, 20],
      rsi: true,
      divergences: false,
      darvasRows: rows,
      deals,
    });
    expect(m.candleColors.get(20)).toBe('rgba(20, 184, 166, 1)');
    expect(m.tags.map((t) => t.title)).toEqual(['Box', 'Box', 'Deal', 'Deal']);
    const texts = m.shapes.filter((s) => s.kind === 'text').map((s) => (s as { text: string }).text);
    expect(texts).toContain('Buy stop 110');
    expect(texts).toContain('Stop 94.99');
    expect(texts.some((t) => /^Breakout \d+ \w{3}, failed$/.test(t))).toBe(true);
    const callout = m.shapes.find((s) => s.kind === 'callout') as { lines: { text: string }[] } | undefined;
    expect(callout?.lines.map((l) => l.text)).toEqual([
      expect.stringMatching(/^Deals /),
      'Net buy  +₹66.6 Cr  (FII: Societe Generale, BNP Paribas)',
      'Churn  ₹302 Cr  (prop desks, ignored)',
    ]);
    // Normal colours: same markers, plain candles.
    const n = buildV2Model({
      bars,
      tf: 'D',
      mode: 'info',
      colours: 'normal',
      emas: [],
      rsi: false,
      divergences: false,
      darvasRows: rows,
      deals,
    });
    expect(n.candleColors.size).toBe(0);
    expect(n.markers.length).toBeGreaterThan(0);
  });

  it('gaps and volume spikes are dots, never coloured candles', () => {
    const closes = Array.from({ length: 40 }, () => 100);
    const bars = mkBars(closes, (i) => (i === 35 ? 10_000 : 1000));
    bars[36] = { ...bars[36], open: 110, high: 112, low: 109, close: 111 };
    const m = buildV2Model({ bars, tf: 'D', mode: 'info', colours: 'events', emas: [], rsi: false, divergences: false });
    expect(m.candleColors.size).toBe(0);
    const dots = m.markers.filter((x) => x.text === '');
    // 35 = volume spike, 36 = gap up, 37 = gap back down.
    expect(dots.map((x) => x.index).sort()).toEqual([35, 36, 37]);
  });

  it('divergence lines on both panes, the latest bright, labels on the RSI pane', () => {
    const bars = mkBars(Array.from({ length: 60 }, (_, i) => 100 + i));
    const div = (a: number, b: number): DivergenceRow => ({
      side: 'bear',
      type: 'Strong',
      p1_date: bars[a].time,
      p2_date: bars[b].time,
      p1_price: 1,
      p2_price: 2,
      p1_rsi: 75,
      p2_rsi: 65,
      confirm_date: bars[b + 3].time,
      trigger_price: 1,
      stop_price: 2,
      status: 'watching',
    });
    const m = buildV2Model({
      bars,
      tf: 'D',
      mode: 'clean',
      colours: 'events',
      emas: [],
      rsi: true,
      divergences: true,
      divergenceRows: [div(10, 20), div(30, 40)],
    });
    expect(m.segments.map((s) => s.pane)).toEqual(['rsi', 'price', 'rsi', 'price']);
    expect(m.segments[0].color).toMatch(/0\.4\)$/);
    expect(m.segments[2].color).toMatch(/, 1\)$/);
    expect(m.rsiMarkers.map((x) => x.text)).toEqual(['Bear Strong', 'Bear Strong']);
  });
});

describe('tools', () => {
  it('rectangle / AVWAP / long / short click flows; measure text', () => {
    const p = (time: string, price: number) => ({ time, price });
    const r1 = clickTool('rect', null, p('2026-01-02', 10), 'x');
    expect(r1.done).toBeNull();
    expect(clickTool('rect', r1.pending, p('2026-01-01', 12), 'x').done).toEqual({
      id: 'x',
      kind: 'rect',
      a: p('2026-01-01', 12),
      b: p('2026-01-02', 10),
    });
    expect(clickTool('avwap', null, p('2026-01-01', 12), 'v').done).toEqual({ id: 'v', kind: 'avwap', a: p('2026-01-01', 12) });
    const l1 = clickTool('long', null, p('2026-01-01', 100), 'l');
    // A stop above the entry is ignored for a long.
    expect(clickTool('long', l1.pending, p('2026-01-05', 105), 'l').done).toBeNull();
    const long = clickTool('long', l1.pending, p('2026-01-05', 95), 'l').done!;
    expect(long).toMatchObject({ kind: 'long', rr: 2 });
    expect(positionTarget(long as Parameters<typeof positionTarget>[0])).toBe(110);
    const s1 = clickTool('short', null, p('2026-01-01', 100), 's');
    const short = clickTool('short', s1.pending, p('2026-01-05', 104), 's').done!;
    expect(positionTarget(short as Parameters<typeof positionTarget>[0])).toBe(92);
    expect(measureText({ ...p('a', 100), index: 3 }, { ...p('b', 112.4), index: 26 })).toBe('+12.4% · +12.40 · 23 bars');
  });

  it('sanitize keeps the new drawing kinds and drops malformed ones', () => {
    const ok = sanitize({
      X: [
        { id: 'a', kind: 'rect', a: { time: 't', price: 1 }, b: { time: 'u', price: 2 } },
        { id: 'b', kind: 'long', a: { time: 't', price: 1 }, b: { time: 'u', price: 0.5 }, rr: 2 },
        { id: 'c', kind: 'long', a: { time: 't', price: 1 }, b: { time: 'u', price: 0.5 } },
        { id: 'd', kind: 'avwap', a: { time: 't', price: 1 } },
        { id: 'e', kind: 'alert', a: { time: 't', price: 1 } },
      ],
    });
    expect(ok.X.map((d) => d.id)).toEqual(['a', 'b', 'd']);
  });
});

describe('global settings', () => {
  beforeEach(() => resetChartSettingsCache());
  it('defaults, parse and persist', () => {
    expect(parseSettings(null)).toEqual(CHART_V2_DEFAULTS);
    expect(parseSettings({ mode: 'info', colours: 'normal', tf: 'W' })).toEqual({ mode: 'info', colours: 'normal', tf: 'W' });
    expect(parseSettings({ mode: 'x', tf: 'Y' })).toEqual(CHART_V2_DEFAULTS);
    setChartSettings({ mode: 'info' });
    expect(JSON.parse(localStorage.getItem('mp.chartv2.v1')!)).toMatchObject({ mode: 'info' });
  });
});
