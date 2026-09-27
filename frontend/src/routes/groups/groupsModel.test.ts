import { describe, expect, it } from 'vitest';
import type { GroupRow, RrgRow } from '../../api/types';
import { asFloor, asLevel, chartsSourceHref, filterGroups, flowLeaders, parseGroupId, quadrantCounts, rankSparkValues, rrgDomain, rrgVisible } from './groupsModel';

const g = (over: Partial<GroupRow>): GroupRow => ({ id: `industry:${over.group_name ?? 'x'}`, level: 'industry', ...over }) as GroupRow;
const r = (id: string, rank: number | null, q: string | null, x = 100, y = 100): RrgRow =>
  ({ id, group_name: id, level: 'industry', rank, rrg_quadrant: q, rs_ratio: x, rs_momentum: y, tail: [] }) as RrgRow;

describe('groupsModel', () => {
  it('parses group ids and URL params defensively', () => {
    expect(parseGroupId('industry:2/3 Wheelers')).toEqual({ level: 'industry', name: '2/3 Wheelers' });
    expect(parseGroupId('galaxy:x')).toBeNull();
    expect(parseGroupId('sector:')).toBeNull();
    expect(asLevel('nope')).toBe('industry');
    expect(asFloor('watch')).toBe('watch');
    expect(asFloor(null)).toBe('1000');
  });

  it('counts quadrants and filters by text and quadrant', () => {
    const rows = [g({ group_name: 'Pharma', rrg_quadrant: 'Leading' }), g({ group_name: 'Banks', rrg_quadrant: 'Lagging' }), g({ group_name: 'Tiny' })];
    expect(quadrantCounts(rows)).toMatchObject({ Leading: 1, Lagging: 1, none: 1 });
    expect(filterGroups(rows, 'pha', new Set()).map((x) => x.group_name)).toEqual(['Pharma']);
    expect(filterGroups(rows, '', new Set(['Lagging'])).map((x) => x.group_name)).toEqual(['Banks']);
  });

  it('flow leaders skip thin groups and NULL deltas', () => {
    const rows = [
      g({ group_name: 'A', stocks: 10, turnover_share_delta: 0.5 }),
      g({ group_name: 'B', stocks: 2, turnover_share_delta: 2 }),
      g({ group_name: 'C', stocks: 5, turnover_share_delta: -0.3 }),
      g({ group_name: 'D', stocks: 5, turnover_share_delta: null }),
    ];
    const f = flowLeaders(rows);
    expect(f.inflow.map((i) => i.row.group_name)).toEqual(['A']);
    expect(f.outflow.map((i) => i.row.group_name)).toEqual(['C']);
  });

  it('RRG cap keeps the best-ranked groups of every quadrant and reports the true total', () => {
    const rows = [r('a', 1, 'Leading'), r('b', 2, 'Leading'), r('c', 3, 'Leading'), r('d', 50, 'Improving'), r('e', null, 'Lagging')];
    const v = rrgVisible(rows, null, 2);
    expect(v.shown.map((x) => x.id)).toEqual(['a', 'b', 'd', 'e']);
    expect(v.total).toBe(5);
    expect(rrgVisible(rows, new Set(['d']), 2)).toEqual({ shown: [rows[3]], total: 1 });
  });

  it('RRG domain always contains the 100/100 centre and every point', () => {
    const d = rrgDomain([r('a', 1, 'Leading', 104, 101), { ...r('b', 2, 'Lagging', 98, 99), tail: [{ trade_date: null, rs_ratio: 96, rs_momentum: 97 }] }]);
    expect(d.x[0]).toBeLessThan(96);
    expect(d.x[1]).toBeGreaterThan(104);
    expect(d.y[0]).toBeLessThan(97);
    expect(d.y[1]).toBeGreaterThan(101);
  });

  it('rank spark inverts ranks and keeps NULL gaps; charts link carries the source', () => {
    expect(rankSparkValues([3, null, 1])).toEqual([-3, null, -1]);
    const href = chartsSourceHref('industry:Heavy Electrical', ['AAA', 'BBB'], '2026-09-24');
    const u = new URL(href, 'http://x');
    expect(u.pathname).toBe('/charts');
    expect(u.searchParams.get('source')).toBe('group:industry:Heavy Electrical');
    expect(u.searchParams.get('syms')).toBe('AAA,BBB');
    expect(u.searchParams.get('as_of')).toBe('2026-09-24');
  });
});
