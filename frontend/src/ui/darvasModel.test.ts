import { describe, expect, it } from 'vitest';
import type { DarvasRow } from '../api/types';
import { getNavList, setNavList, stepSymbol } from '../lib/navList';
import { EMPTY_DARVAS, toDarvasLines } from './darvasModel';

const times = ['2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24', '2026-09-25'];

const row = (p: Partial<DarvasRow>): DarvasRow =>
  ({ trade_date: null, top: null, bottom: null, projected: false, top_extension: null, ema_10_projection: null, ...p }) as DarvasRow;

// Payload as GET /stock/{sym}/darvas serves it: per-bar Pine TopBox / BottomBox, then 5 projected rows.
const payload: DarvasRow[] = [
  row({ trade_date: '2026-09-21' }),
  row({ trade_date: '2026-09-22', top: 494.4, bottom: 431.5 }),
  row({ trade_date: '2026-09-23', top: 539, bottom: 465.05 }),
  row({ trade_date: '2026-09-24', top: 539, bottom: 465.05 }),
  row({ trade_date: '2026-09-25', top: 552, bottom: 515, top_extension: 552, ema_10_projection: 521.45 }),
  ...['2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-05'].map((d, k) =>
    row({ trade_date: d, projected: true, top_extension: 552, ema_10_projection: 521.45 + 0.12 * (k + 1) }),
  ),
];

describe('toDarvasLines', () => {
  it('builds the two step series from per-bar values (NULL before the first box is skipped)', () => {
    const l = toDarvasLines(payload, times);
    expect(l.top).toEqual([
      { time: '2026-09-22', value: 494.4 },
      { time: '2026-09-23', value: 539 },
      { time: '2026-09-24', value: 539 },
      { time: '2026-09-25', value: 552 },
    ]);
    expect(l.bottom.map((p) => p.value)).toEqual([431.5, 465.05, 465.05, 515]);
    expect(l.last).toEqual({ top: 552, bottom: 515 });
  });

  it('builds the dotted projections from the last bar to 5 future points (no candles)', () => {
    const l = toDarvasLines(payload, times);
    expect(l.topExtension.map((p) => p.time)).toEqual(['2026-09-25', '2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-05']);
    expect(l.topExtension.every((p) => p.value === 552)).toBe(true);
    expect(l.emaProjection[0]).toEqual({ time: '2026-09-25', value: 521.45 });
    expect(l.emaProjection).toHaveLength(6);
    expect(l.emaProjection[5].value).toBeCloseTo(522.05, 6);
  });

  it('boxes off keeps only the EMA10 projection', () => {
    const l = toDarvasLines(payload, times, { boxes: false });
    expect([l.top, l.bottom, l.topExtension, l.last]).toEqual([[], [], [], null]);
    expect(l.emaProjection).toHaveLength(6);
  });

  it('ignores rows off the displayed bars, stale projections and empty input', () => {
    // Bars end earlier than the payload: 09-25 is not displayed, so its values and the projection anchor are dropped.
    const l = toDarvasLines(payload, times.slice(0, 4));
    expect(l.top.map((p) => p.time)).toEqual(['2026-09-22', '2026-09-23', '2026-09-24']);
    expect(l.topExtension).toEqual([]);
    expect(l.emaProjection).toEqual([]);
    expect(toDarvasLines(undefined, times)).toBe(EMPTY_DARVAS);
    expect(toDarvasLines(payload, [])).toBe(EMPTY_DARVAS);
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
