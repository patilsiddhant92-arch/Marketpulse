import { describe, expect, it } from 'vitest';
import type { HeatRow, MemberRow, SectorRow } from './sectorApi';
import {
  asBoardLevel,
  asWindow,
  dealsCell,
  filterRows,
  groupReadout,
  heatColour,
  heatGroups,
  heatPosition,
  leadersTvText,
  levelFromGroupId,
  rankTone,
  sortByScore,
  squarify,
} from './sectorModel';

const row = (name: string, score: number | null, extra: Partial<SectorRow> = {}): SectorRow =>
  ({
    id: `broad_industry:${name}`,
    level: 'broad_industry',
    group_name: name,
    stocks: 10,
    small: false,
    ranked: score != null,
    state: 'Neutral',
    state_reason: null,
    near: 40,
    a50: 50,
    leaders: [],
    pct: {},
    deals_buy_10d: 0,
    deals_sell_10d: 0,
    deals_flow_10d_cr: 0,
    score_2W: score,
    ...extra,
  }) as SectorRow;

describe('peer-rank colour (round 3b)', () => {
  const all = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  it('colours by rank vs peers, never by sign', () => {
    expect(rankTone(all, 10)).toBe('top');
    expect(rankTone(all, 1)).toBe('bottom');
    expect(rankTone(all, 5)).toBe('mid');
    // every group up: the best is green, the worst is red although it is positive
    const allUp = [0.5, 1, 1.5, 2, 3, 4];
    expect(rankTone(allUp, 0.5)).toBe('bottom');
    expect(rankTone(allUp, 4)).toBe('top');
  });
  it('is plain with too few peers and empty for NULL', () => {
    expect(rankTone([1, 2, 3], 3)).toBe('mid');
    expect(rankTone(all, null)).toBeNull();
    expect(rankTone(all, 1, false)).toBe('top');
  });
});

describe('board helpers', () => {
  it('sorts by the window score with NULL (not ranked / gap) last', () => {
    const r = sortByScore([row('B', 40), row('A', null), row('C', 90)], '2W');
    expect(r.map((x) => x.group_name)).toEqual(['C', 'B', 'A']);
  });
  it('filters by state and name', () => {
    const rows = [row('Auto', 1, { state: 'Favour' }), row('Banks', 2, { state: 'Caution' })];
    expect(filterRows(rows, 'Favour', '').map((r) => r.group_name)).toEqual(['Auto']);
    expect(filterRows(rows, 'all', 'ban').map((r) => r.group_name)).toEqual(['Banks']);
  });
  it('parses URL params with safe defaults', () => {
    expect(asBoardLevel('broad_sector')).toBe('broad_industry');
    expect(asBoardLevel('index')).toBe('index');
    expect(asWindow('3M')).toBe('2W');
    expect(levelFromGroupId('industry:2/3 Wheelers')).toBe('industry');
    expect(levelFromGroupId('broad_sector:X')).toBeNull();
  });
  it('copies leaders as TradingView sections', () => {
    const t = leadersTvText([
      { group_name: 'Auto', leaders: ['BAJAJ-AUTO', 'M&M'] },
      { group_name: 'Empty', leaders: [] },
    ]);
    expect(t.text).toBe('###Auto,NSE:BAJAJ_AUTO,NSE:M_M');
    expect(t.count).toBe(2);
  });
  it('formats the Deals 10D cell and chips 3+ net-buy names', () => {
    expect(dealsCell({ deals_buy_10d: null, deals_sell_10d: null, deals_flow_10d_cr: null })).toBeNull();
    expect(dealsCell({ deals_buy_10d: 0, deals_sell_10d: 0, deals_flow_10d_cr: 0 })).toEqual({ text: '·', chip: false });
    expect(dealsCell({ deals_buy_10d: 3, deals_sell_10d: 1, deals_flow_10d_cr: 70 })).toEqual({
      text: '3 buy · 1 sell · +₹70 Cr',
      chip: true,
    });
    expect(dealsCell({ deals_buy_10d: 0, deals_sell_10d: 1, deals_flow_10d_cr: -30 })?.text).toBe('0 buy · 1 sell · −₹30 Cr');
  });
});

describe('group read-out (house style)', () => {
  const m = (near: boolean, a50: boolean): MemberRow => ({ symbol: 'X', near_52w_high: near, above_50ema: a50 }) as MemberRow;
  it('says broad or narrow with a number behind each claim', () => {
    const r = row('Auto', 80, { nh_2W: 4, ad_2W: 15, upd_2W: 65 } as Partial<SectorRow>);
    const say = groupReadout(r, [m(true, true), m(true, true), m(false, true), m(false, false), m(false, false), m(false, false)], '2W');
    expect(say[0]).toBe('2 of 6 members are within 10% of their 52-week high.');
    expect(say).toContain('4 made a new 52-week high in the last 2 weeks.');
    expect(say).toContain('Most days, more members rose than fell.');
    expect(say[say.length - 1]).toBe('The move is broad.');
    for (const s of say) {
      expect(s.split(' ').length).toBeLessThanOrEqual(20);
      expect(s).not.toContain(';');
    }
    const narrow = groupReadout(
      row('N', 1, { nh_2W: 0 } as Partial<SectorRow>),
      [m(true, false), m(false, false), m(false, false), m(false, false), m(false, false)],
      '2W',
    );
    expect(narrow).toContain('The move is narrow: one stock or none.');
    expect(narrow).toContain('None made a new 52-week high in the last 2 weeks.');
  });
});

describe('stock heatmap', () => {
  const s = (symbol: string, sector: string, t: number, r1: number | null, mc = 5000): HeatRow =>
    ({ symbol, sector, broad_industry: 'BI', industry: 'I', mc, t, t20: t, v: 1, dv: 1, r1 }) as HeatRow;
  const rows = [s('A', 'Banks', 100, 2), s('B', 'Banks', 50, -1), s('C', 'IT', 30, 0.5), s('D', 'IT', 5, 9, 200)];
  it('squarify fills the box exactly with no overlap of area', () => {
    const out = squarify([{ v: 6 }, { v: 3 }, { v: 1 }], 0, 0, 100, 50);
    expect(out).toHaveLength(3);
    const area = out.reduce((a, r) => a + r.w * r.h, 0);
    expect(area).toBeCloseTo(5000, 6);
    expect(out[0].w * out[0].h).toBeCloseTo(3000, 6);
  });
  it('groups by taxonomy, applies the ₹1,000 Cr floor and weights the header move', () => {
    const g = heatGroups(rows, { group: 'sector', size: 't', colour: 'r1', rel: false, floor: true, focus: null });
    expect(g.groups.map((x) => x.key)).toEqual(['Banks', 'IT']);
    expect(g.groups[0].move).toBeCloseTo((100 * 2 + 50 * -1) / 150, 6);
    expect(g.shown).toHaveLength(3);
    const all = heatGroups(rows, { group: 'sector', size: 'eq', colour: 'r1', rel: true, floor: false, focus: 'IT' });
    expect(all.shown.map((x) => x.symbol)).toEqual(['C', 'D']);
    expect(all.market).toBe(2); // median of 2, -1, 0.5, 9 -> sorted [-1, 0.5, 2, 9], index 2
  });
  it('colours: centre grey, ±1 saturated, NULL dark, inverted metrics', () => {
    expect(heatPosition('r1', 3, false)).toBe(1);
    expect(heatPosition('r1', -9, false)).toBe(-1);
    expect(heatPosition('vol', 5, false)).toBe(-1); // high volatility = red
    expect(heatPosition('rs', 50, true)).toBe(0); // vs market does not apply to RS
    expect(heatColour(null)).toBe('rgb(59,66,80)');
    expect(heatColour(1)).toBe('rgb(48,204,90)');
    expect(heatColour(0)).toBe('rgb(66,72,84)');
  });
});
