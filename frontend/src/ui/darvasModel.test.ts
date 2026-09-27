import { describe, expect, it } from 'vitest';
import type { DarvasBoxRow } from '../api/types';
import { getNavList, setNavList, stepSymbol } from '../lib/navList';
import { boxBreakMarkers, boxRects, toChartBoxes } from './darvasModel';

const times = ['2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04', '2026-09-07', '2026-09-08', '2026-09-09', '2026-09-10'];

const row = (p: Partial<DarvasBoxRow>): DarvasBoxRow =>
  ({ start_date: null, formed_date: null, end_date: null, top: null, bottom: null, status: 'active', break_date: null, break_close: null, bars: null, ...p }) as DarvasBoxRow;

describe('toChartBoxes', () => {
  it('snaps served boxes onto bars, extends the active box to the last bar, keeps breaks', () => {
    const boxes = toChartBoxes(
      [
        row({ start_date: '2026-09-01', formed_date: '2026-09-03', end_date: '2026-09-04', top: 110, bottom: 99, status: 'broken_up', break_date: '2026-09-04' }),
        row({ start_date: '2026-09-04', formed_date: '2026-09-08', end_date: '2026-09-09', top: 113, bottom: 102, status: 'active' }),
      ],
      times,
    );
    expect(boxes.map((b) => [b.from, b.to, b.status, b.active, b.breakTime])).toEqual([
      ['2026-09-01', '2026-09-04', 'broken_up', false, '2026-09-04'],
      ['2026-09-04', '2026-09-10', 'active', true, null], // extended past its served end to the last bar
    ]);
    expect(boxBreakMarkers(boxes)).toEqual([{ time: '2026-09-04', kind: 'darvas_up' }]);
  });

  it('snaps daily dates onto weekly bars (week = last session time)', () => {
    const weeks = ['2026-09-04', '2026-09-11'];
    const [b] = toChartBoxes([row({ start_date: '2026-09-02', end_date: '2026-09-09', top: 5, bottom: 4, status: 'broken_down', break_date: '2026-09-09' })], weeks);
    expect([b.from, b.to, b.breakTime]).toEqual(['2026-09-04', '2026-09-04', '2026-09-11']);
    expect(boxBreakMarkers([b])).toEqual([{ time: '2026-09-11', kind: 'darvas_down' }]);
  });

  it('drops rows with missing values, inverted ranges or no overlap; never fills', () => {
    expect(
      toChartBoxes(
        [
          row({ start_date: '2026-09-01', end_date: '2026-09-02', top: null, bottom: 1 }),
          row({ start_date: '2026-09-01', end_date: '2026-09-02', top: 1, bottom: 2 }),
          row({ start_date: '2026-10-01', end_date: '2026-10-02', top: 2, bottom: 1, status: 'superseded' }),
          row({ start_date: '2026-08-01', end_date: '2026-08-10', top: 2, bottom: 1, status: 'superseded' }),
        ],
        times,
      ),
    ).toEqual([]);
    expect(toChartBoxes(undefined, times)).toEqual([]);
    expect(toChartBoxes([row({ start_date: '2026-09-01', end_date: '2026-09-02', top: 2, bottom: 1 })], [])).toEqual([]);
  });
});

describe('boxRects', () => {
  const [box] = toChartBoxes([row({ start_date: '2026-09-02', end_date: '2026-09-03', top: 110, bottom: 100, status: 'superseded' })], times);
  const timeToX = (t: string) => times.indexOf(t) * 10;
  const priceToY = (p: number) => 1000 - p * 5;
  it('pads half a bar each side and spans top..bottom', () => {
    expect(boxRects([box], timeToX, priceToY, 10, 500)).toEqual([{ box, x: 5, y: 450, w: 20, h: 50 }]);
  });
  it('skips unmappable or fully off-screen boxes', () => {
    expect(boxRects([box], () => null, priceToY, 10, 500)).toEqual([]);
    expect(boxRects([box], (t) => timeToX(t) + 1000, priceToY, 10, 500)).toEqual([]);
  });
});

describe('navList', () => {
  it('dedupes, keeps order and steps with clamping', () => {
    setNavList(['A', 'B', null, 'A', 'C']);
    expect(getNavList()).toEqual(['A', 'B', 'C']);
    expect(stepSymbol(getNavList(), 'B', 1)).toBe('C');
    expect(stepSymbol(getNavList(), 'C', 1)).toBe('C');
    expect(stepSymbol(getNavList(), 'A', -1)).toBe('A');
    expect(stepSymbol(getNavList(), 'ZZZ', 1)).toBe('A');
    expect(stepSymbol([], 'A', 1)).toBeNull();
  });
});
