import { describe, expect, it } from 'vitest';
import {
  barsToOHLC,
  chartsHref,
  clampPage,
  gridShape,
  mergeItems,
  pageCount,
  pageSlice,
  parseSource,
  relativePerformance,
  sortItems,
  sourceId,
  type ChartItem,
} from './sources';

const it_ = (symbol: string, extra: Partial<ChartItem> = {}): ChartItem => ({ symbol, tags: [], ...extra });

describe('chart sources', () => {
  it('parses and round-trips source ids', () => {
    for (const src of ['queue:all', 'queue:vcp', 'screener:minervini_8of8', 'screener:custom', 'deals:buy', 'research:pre-move', 'watchlist', 'list']) {
      expect(sourceId(parseSource(src)!)).toBe(src);
    }
    expect(parseSource('group:industry:Oil, Gas: Refining')).toEqual({ kind: 'group', key: 'industry', name: 'Oil, Gas: Refining' });
    expect(parseSource('queue:nope')).toBeNull();
    expect(parseSource('group:planet:X')).toBeNull();
    expect(parseSource('screener:DROP TABLE')).toBeNull();
    expect(parseSource(null)).toBeNull();
  });

  it('merges queue lists once per symbol, keeping every tag', () => {
    const merged = mergeItems([
      [it_('A', { tags: ['Darvas Squeeze'] }), it_('B', { tags: ['Darvas Squeeze'] })],
      [it_('A', { tags: ['VCP'] }), it_('C', { tags: ['VCP'] })],
    ]);
    expect(merged.map((m) => m.symbol)).toEqual(['A', 'B', 'C']);
    expect(merged[0].tags).toEqual(['Darvas Squeeze', 'VCP']);
  });

  it('sorts with NULLs last in both directions and distance by magnitude', () => {
    const items = [
      it_('A', { rs_percentile: 50, distance_to_trigger_pct: -1 }),
      it_('B', { rs_percentile: null, distance_to_trigger_pct: null }),
      it_('C', { rs_percentile: 90, distance_to_trigger_pct: 4 }),
      it_('D', { rs_percentile: 70, distance_to_trigger_pct: 0.5 }),
    ];
    expect(sortItems(items, 'rs').map((i) => i.symbol)).toEqual(['C', 'D', 'A', 'B']);
    expect(sortItems(items, 'distance').map((i) => i.symbol)).toEqual(['D', 'A', 'C', 'B']);
    expect(sortItems(items, 'source').map((i) => i.symbol)).toEqual(['A', 'B', 'C', 'D']);
    expect(sortItems(items, 'symbol').map((i) => i.symbol)).toEqual(['A', 'B', 'C', 'D']);
  });

  it('pages through the whole list', () => {
    const list = Array.from({ length: 20 }, (_, i) => i);
    expect(pageCount(20, 6)).toBe(4);
    expect(pageCount(0, 6)).toBe(1);
    expect(pageSlice(list, 3, 6)).toEqual([18, 19]);
    expect(clampPage(99, 20, 6)).toBe(3);
    expect(clampPage(-1, 20, 6)).toBe(0);
    expect(gridShape(4)).toEqual({ cols: 2, rows: 2 });
    expect(gridShape(6)).toEqual({ cols: 3, rows: 2 });
    expect(gridShape(9)).toEqual({ cols: 3, rows: 3 });
  });

  it('computes relative performance over the chosen window, NULL when data is missing', () => {
    const rows = [
      { close: 100, bench: 1000 },
      { close: 105, bench: 1010 },
      { close: 110, bench: 1020 },
      { close: 120, bench: 1050 },
    ];
    const r = relativePerformance(rows, 2);
    expect(r.stock).toBeCloseTo(((120 / 105) - 1) * 100);
    expect(r.bench).toBeCloseTo(((1050 / 1010) - 1) * 100);
    expect(r.excess).toBeCloseTo(r.stock! - r.bench!);
    expect(relativePerformance([{ close: 1, bench: null }], 21).excess).toBeNull();
  });

  it('drops incomplete bars instead of filling them', () => {
    const bars = barsToOHLC([
      { trade_date: '2026-09-24', open: 1, high: 2, low: 0.5, close: 1.5, volume: 10, delivery_pct: null, partial: false },
      { trade_date: '2026-09-25', open: 1, high: null, low: 0.5, close: 1.5, partial: false },
    ]);
    expect(bars).toHaveLength(1);
    expect(bars[0]).toMatchObject({ time: '2026-09-24', close: 1.5, delivery_pct: null });
  });

  it('builds a Charts link that keeps as_of and resets the page', () => {
    expect(chartsHref('?as_of=2026-03-12&preset=vcp', 'screener:vcp')).toBe('/charts?as_of=2026-03-12&src=screener%3Avcp&page=1');
  });
});
