import { describe, expect, it } from 'vitest';
import {
  cellBackground,
  cellText,
  gridSessions,
  lookbackLabel,
  median,
  parseLookback,
  rangePos,
  returnFill,
  shortDate,
  signed,
  sortBy,
  squarify,
} from './model';
import type { BreadthCell } from './types';

const cell = (o: Partial<BreadthCell>): BreadthCell => ({
  pct: 50,
  count: 1370,
  chg: 0,
  chg_count: 0,
  rel_pct: 0,
  sd60: 3,
  z: 0,
  unusual: false,
  intensity: 0,
  flag: 0,
  pctl: 50,
  ...o,
});

describe('pulse model', () => {
  it('parses lookbacks and labels them', () => {
    expect(parseLookback('20')).toBe(20);
    expect(parseLookback('7')).toBe(5);
    expect(parseLookback(null)).toBe(5);
    expect(lookbackLabel(60)).toBe('3M');
    expect(lookbackLabel(250)).toBe('1Y');
  });

  it('grid shows the last min(lookback, 10) sessions, Today last', () => {
    const rows = Array.from({ length: 30 }, (_, i) => i);
    expect(gridSessions(rows, 5)).toEqual([25, 26, 27, 28, 29]);
    expect(gridSessions(rows, 60)).toHaveLength(10);
    expect(gridSessions(rows, 60)[9]).toBe(29);
  });

  it('cell colour follows the change, never the level', () => {
    expect(cellBackground(cell({ pct: 90, chg: 0, intensity: 0 }))).toBeUndefined();
    expect(cellBackground(cell({ pct: 10, chg: 2, intensity: 0.4 }))).toContain('--c-up');
    expect(cellBackground(cell({ pct: 90, chg: -2, intensity: 0.4 }))).toContain('--c-down');
    expect(cellText(cell({ pct: 47.6, count: 1303.4 }), 'pct')).toBe('48');
    expect(cellText(cell({ pct: 47.6, count: 1303.4 }), 'count')).toBe('1,303');
  });

  it('formats signs and dates', () => {
    expect(signed(2.345, 1)).toBe('+2.3');
    expect(signed(-0.04, 1)).toBe('0.0');
    expect(signed(null)).toBe('—');
    expect(shortDate('2026-08-13')).toBe('13 Aug');
  });

  it('range position and fills', () => {
    expect(rangePos(50, 0, 100)).toBe(50);
    expect(rangePos(150, 0, 100)).toBe(100);
    expect(rangePos(null, 0, 100)).toBeNull();
    expect(returnFill(null, 2.5)).toContain('surface-3');
    expect(returnFill(-3, 2.5)).toContain('--c-down');
  });

  it('sorts nulls last in both directions', () => {
    const rows = [{ v: 2 }, { v: null }, { v: 5 }];
    expect(sortBy(rows, (r) => r.v, -1).map((r) => r.v)).toEqual([5, 2, null]);
    expect(sortBy(rows, (r) => r.v, 1).map((r) => r.v)).toEqual([2, 5, null]);
  });

  it('median', () => {
    expect(median([3, 1, null, 2])).toBe(2);
    expect(median([4, 1, 3, 2])).toBe(2.5);
    expect(median([])).toBeNull();
  });

  it('squarify fills the box and keeps area proportional', () => {
    const items = [{ w: 6 }, { w: 6 }, { w: 4 }, { w: 3 }, { w: 2 }, { w: 2 }, { w: 1 }];
    const rects = squarify(items, (i) => i.w, 600, 400);
    expect(rects).toHaveLength(items.length);
    const total = rects.reduce((s, r) => s + r.w * r.h, 0);
    expect(total).toBeCloseTo(600 * 400, 3);
    const first = rects.find((r) => r.item === items[0])!;
    expect((first.w * first.h) / total).toBeCloseTo(6 / 24, 3);
    for (const r of rects) {
      expect(r.x).toBeGreaterThanOrEqual(-1e-6);
      expect(r.x + r.w).toBeLessThanOrEqual(600 + 1e-6);
    }
  });
});
