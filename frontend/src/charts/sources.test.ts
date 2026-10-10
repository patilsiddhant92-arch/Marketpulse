import { describe, expect, it } from 'vitest';
import {
  barsToOHLC,
  chartsHref,
  clampPage,
  fromDealTabRow,
  fromMoverRow,
  gridShape,
  houseBuysList,
  mergeItems,
  pageCount,
  pageSlice,
  parseSource,
  relativePerformance,
  setupsViewRows,
  sortItems,
  sourceId,
  type ChartItem,
} from './sources';

const it_ = (symbol: string, extra: Partial<ChartItem> = {}): ChartItem => ({ symbol, tags: [], ...extra });

describe('chart sources', () => {
  it('parses and round-trips source ids', () => {
    for (const src of [
      'queue:all',
      'queue:vcp',
      'screener:minervini_8of8',
      'screener:custom',
      'deals:buy',
      'deals:watch',
      'deals:history',
      'deals:houses',
      'deals:house:SOCIETE GENERALE',
      'pulse:gainers',
      'pulse:rvol',
      'setups:all',
      'setups:vcp',
      'setups:favour',
      'setups:confluence',
      'setups:near',
      'setups:dropped',
      'watchlist',
      'list',
    ]) {
      expect(sourceId(parseSource(src)!)).toBe(src);
    }
    expect(parseSource('group:industry:Oil, Gas: Refining')).toEqual({ kind: 'group', key: 'industry', name: 'Oil, Gas: Refining' });
    expect(parseSource('queue:nope')).toBeNull();
    expect(parseSource('group:planet:X')).toBeNull();
    expect(parseSource('screener:DROP TABLE')).toBeNull();
    expect(parseSource(null)).toBeNull();
    // "Pre-move watch" was dropped: old links fall back to the default source.
    expect(parseSource('research:pre-move')).toBeNull();
    expect(parseSource('pulse:nope')).toBeNull();
    expect(parseSource('setups:nope')).toBeNull();
    expect(parseSource('deals:house:')).toBeNull();
    expect(parseSource('deals:house:A: B')).toEqual({ kind: 'deals', key: 'house', name: 'A: B' });
  });

  it('turns Pulse movers, Deals views and Setups views into chart lists', () => {
    expect(fromMoverRow({ symbol: 'JUBLCPL', name: 'Jubilant', close: 2322.6, chg_1d_pct: 20, rs_percentile: 81, mcap_cr: 3519, chips: ['EXT'] })).toEqual({
      symbol: 'JUBLCPL',
      name: 'Jubilant',
      industry: null,
      close: 2322.6,
      change_1d_pct: 20,
      rs_percentile: 81,
      market_cap_cr: 3519,
      tags: ['EXT'],
    });
    expect(fromMoverRow({ symbol: null })).toBeNull();
    expect(fromDealTabRow({ symbol: 'A', net_cr: 12, status: 'holding' })).toMatchObject({ symbol: 'A', net_cr: 12, tags: ['holding'] });
    expect(fromDealTabRow({ symbol: 'B', bought_cr: 5, pattern_label: 'Repeat buying' })).toMatchObject({ net_cr: 5, tags: ['Repeat buying'] });
    const hb = houseBuysList([
      { house: 'H1', symbols: ['A', 'B'] },
      { house: 'H2', symbols: ['B'] },
    ]);
    expect(hb.map((i) => [i.symbol, i.tags])).toEqual([
      ['A', ['H1']],
      ['B', ['H1', 'H2']],
    ]);
    const rows = [
      { symbol: 'A', screeners: ['vcp'], group_state: 'Favour' },
      { symbol: 'B', screeners: ['vcp', 'momentum'], group_state: 'Caution' },
      { symbol: 'C', screeners: ['darvas_squeeze'], group_state: 'Neutral' },
    ];
    expect(setupsViewRows(rows, 'vcp').map((r) => r.symbol)).toEqual(['A', 'B']);
    expect(setupsViewRows(rows, 'favour').map((r) => r.symbol)).toEqual(['A']);
    expect(setupsViewRows(rows, 'confluence').map((r) => r.symbol)).toEqual(['B']);
    expect(setupsViewRows(rows, 'all')).toHaveLength(3);
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
    // old Tiles window layouts restored: 1, 2, 2x4, 3x4
    expect(gridShape(1)).toEqual({ cols: 1, rows: 1 });
    expect(gridShape(2)).toEqual({ cols: 2, rows: 1 });
    expect(gridShape(8)).toEqual({ cols: 4, rows: 2 });
    expect(gridShape(12)).toEqual({ cols: 4, rows: 3 });
  });

  it('computes relative performance over the chosen window, NULL when data is missing', () => {
    const rows = [
      { close: 100, bench: 1000 },
      { close: 105, bench: 1010 },
      { close: 110, bench: 1020 },
      { close: 120, bench: 1050 },
    ];
    const r = relativePerformance(rows, 2);
    expect(r.stock).toBeCloseTo((120 / 105 - 1) * 100);
    expect(r.bench).toBeCloseTo((1050 / 1010 - 1) * 100);
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
