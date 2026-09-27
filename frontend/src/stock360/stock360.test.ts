import { describe, expect, it } from 'vitest';
import type { QueueRow, RsRow, StockDealRow } from '../api/types';
import { parseRupees, sizePosition } from './sizer';
import { dealMarkers, dealNet, dealSide, eventToMarker, rsSeries, setupOverlays, snapPoints, toOHLC } from './stockModel';

describe('sizePosition', () => {
  const base = { riskRupees: 10_000, capital: 5_00_000, capPct: 25 };
  it('sizes from typed ₹ risk only: floor(risk / (trigger - stop))', () => {
    const out = sizePosition(100, 95, base);
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    expect(out.result.shares).toBe(2000);
    expect(out.result.positionValue).toBe(200_000);
    expect(out.result.actualRisk).toBe(10_000);
    expect(out.result.pctOfCapital).toBeCloseTo(40);
    expect(out.result.overCap).toBe(true);
  });
  it('never invents a risk amount, trigger or stop', () => {
    expect(sizePosition(100, 95, { ...base, riskRupees: null })).toEqual({ ok: false, reason: expect.stringMatching(/Type your/) });
    expect(sizePosition(null, 95, base).ok).toBe(false);
    expect(sizePosition(100, 100, base).ok).toBe(false);
    expect(sizePosition(100, 50, { ...base, riskRupees: 10 }).ok).toBe(false);
  });
  it('capital is optional', () => {
    const out = sizePosition(100, 90, { ...base, capital: null });
    expect(out.ok && out.result.pctOfCapital).toBe(null);
  });
  it('parses typed rupees', () => {
    expect(parseRupees('25,000')).toBe(25000);
    expect(parseRupees('₹ 1,00,000')).toBe(100000);
    expect(parseRupees('')).toBe(null);
    expect(parseRupees('abc')).toBe(null);
    expect(parseRupees('-5')).toBe(null);
  });
});

describe('stockModel', () => {
  it('toOHLC drops incomplete rows instead of filling them', () => {
    const bars = toOHLC([
      { trade_date: '2026-09-24', open: 1, high: 2, low: 0.5, close: 1.5, volume: 10, delivery_pct: null, partial: false },
      { trade_date: '2026-09-25', open: null, high: 2, low: 1, close: 1.8, partial: false },
    ]);
    expect(bars).toHaveLength(1);
    expect(bars[0].delivery_pct).toBeNull();
  });

  it('maps event types to markers and ignores unknown ones', () => {
    expect(eventToMarker({ event_date: '2026-09-01', event_type: 'financial_results', source: 'x', upcoming: false })?.kind).toBe('results');
    expect(eventToMarker({ event_date: '2026-09-01', event_type: 'adjustment:bonus', source: 'x', upcoming: false })?.kind).toBe('bonus');
    expect(eventToMarker({ event_date: '2026-09-01', event_type: 'other', source: 'x', upcoming: false })).toBeNull();
  });

  it('deal markers: institutional only, correct side colour, one per day/side', () => {
    const d = (side: string, inst: boolean | null, date = '2026-06-24', value = 10): StockDealRow => ({
      trade_date: date,
      side,
      institutional: inst,
      value_cr: value,
    });
    const rows = [d('BUY', true), d('BUY', true), d('SELL', true), d('SELL', false), d('BUY', null)];
    expect(dealMarkers(rows)).toEqual([
      { time: '2026-06-24', kind: 'deal_buy' },
      { time: '2026-06-24', kind: 'deal_sell' },
    ]);
    expect(dealSide('weird')).toBeNull();
    expect(dealNet([d('BUY', true, 'x', 30), d('SELL', true, 'x', 10)])).toEqual({ buy: 30, sell: 10, net: 20 });
    expect(dealNet([])).toEqual({ buy: null, sell: null, net: null });
  });

  it('rebases the RS line to 100 and keeps NULL ratios NULL', () => {
    const rows: RsRow[] = [
      { trade_date: '2026-01-01', rs_midsml400: null },
      { trade_date: '2026-01-02', rs_midsml400: 0.05 },
      { trade_date: '2026-01-05', rs_midsml400: 0.06, rs_midsml400_new_high: true },
    ];
    const s = rsSeries(rows, 'midsml400');
    expect(s[0].value).toBeNull();
    expect(s[1].value).toBe(100);
    expect(s[2].value).toBeCloseTo(120);
    expect(s[2].new_high).toBe(true);
  });

  it('snaps daily points onto weekly bar times (last in period wins)', () => {
    const weekly = ['2026-09-18', '2026-09-25'];
    const pts = [
      { time: '2026-09-15', value: 1 },
      { time: '2026-09-17', value: 2 },
      { time: '2026-09-22', value: 3 },
      { time: '2026-09-29', value: 4 },
    ];
    expect(snapPoints(pts, weekly)).toEqual([
      { time: '2026-09-18', value: 2 },
      { time: '2026-09-25', value: 3 },
    ]);
  });

  it('setup overlays use only served geometry', () => {
    const bars = Array.from({ length: 30 }, (_, i) => ({
      time: `2026-08-${String(i + 1).padStart(2, '0')}`,
      open: 1,
      high: 1,
      low: 1,
      close: 1,
    }));
    const sq = { queue: 'darvas_squeeze', timeframe: 'D', darvas_box_top: 110, darvas_box_bottom: null, stop_price: 95, signal_date: '2026-08-25' } as QueueRow;
    const vcp = {
      queue: 'vcp',
      timeframe: 'D',
      trigger_price: 120,
      stop_price: null,
      vcp_contractions: [
        { label: 'T1', start_date: '2026-08-02', peak: 120, trough_date: '2026-08-06', trough: 100, end_date: '2026-08-10' },
        { label: 'T2', start_date: '2026-08-10', peak: 119, trough_date: '2026-08-14', trough: 110, end_date: '2026-08-20' },
      ],
    } as QueueRow;
    const o = setupOverlays({ darvas_squeeze: sq, darvas_10ema: null, vcp }, bars);
    const ids = o.map((x) => x.id);
    expect(ids).toContain('sq-top');
    expect(ids).not.toContain('sq-bottom'); // NULL bottom -> no line
    expect(ids).toContain('vcp-pivot');
    expect(ids).not.toContain('vcp-stop');
    expect(o.find((x) => x.id === 'vcp-zig')!.data.map((p) => p.value)).toEqual([120, 100, 119, 110, 119]);
    expect(setupOverlays(undefined, bars)).toEqual([]);
  });
});
