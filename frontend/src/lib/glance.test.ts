import { describe, expect, it } from 'vitest';
import { countWhere, medianOf, sumOf, topCount } from './glance';

describe('glance helpers', () => {
  it('topCount picks the most frequent key and ignores blanks', () => {
    const rows = [{ g: 'B' }, { g: 'A' }, { g: 'B' }, { g: null }, { g: '' }];
    expect(topCount(rows, (r) => r.g)).toEqual({ key: 'B', count: 2 });
    expect(topCount([{ g: 'B' }, { g: 'A' }], (r) => r.g)).toEqual({ key: 'A', count: 1 });
    expect(topCount([], () => 'x')).toBeNull();
  });
  it('sumOf / medianOf skip NULL and NaN, return NULL when empty', () => {
    const rows = [{ v: 1 }, { v: null }, { v: Number.NaN }, { v: 4 }, { v: 2 }];
    expect(sumOf(rows, (r) => r.v)).toBe(7);
    expect(medianOf(rows, (r) => r.v)).toBe(2);
    expect(medianOf([{ v: 1 }, { v: 3 }], (r) => r.v)).toBe(2);
    expect(sumOf([{ v: null }], (r) => r.v)).toBeNull();
    expect(medianOf([], () => 1)).toBeNull();
  });
  it('countWhere counts matches', () => {
    expect(countWhere([1, 2, 3, 4], (x) => x % 2 === 0)).toBe(2);
  });
});
