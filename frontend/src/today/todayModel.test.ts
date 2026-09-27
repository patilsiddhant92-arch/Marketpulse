import { describe, expect, it } from 'vitest';
import type { TodayBreakoutRow, TodayGroupRow, TodayMoverRow } from '../api/types';
import { broadMoveScore, clauseText, eventWhen, withoutThinGroups, filterByKinds, kindCounts, qualitySideNote, splitMovers, topBottomGroups, traitTitle } from './todayModel';

const mover = (o: Partial<TodayMoverRow>): TodayMoverRow => ({ side: 'gainer', rank: 1, symbol: 'X', ...o }) as TodayMoverRow;
const group = (o: Partial<TodayGroupRow>): TodayGroupRow =>
  ({ id: `industry:${o.group_name}`, level: 'industry', group_name: 'G', stocks: 5, stocks_with_return: 5, symbols: [], ...o }) as TodayGroupRow;

describe('todayModel', () => {
  it('splits movers by side in rank order', () => {
    const { gainers, losers } = splitMovers([mover({ symbol: 'B', rank: 2 }), mover({ symbol: 'L', side: 'loser' }), mover({ symbol: 'A', rank: 1 })]);
    expect(gainers.map((r) => r.symbol)).toEqual(['A', 'B']);
    expect(losers.map((r) => r.symbol)).toEqual(['L']);
  });

  it('says which side a Real move is on', () => {
    expect(qualitySideNote({ quality_id: 'real', change_1d_pct: -3 })).toBe('real selling');
    expect(qualitySideNote({ quality_id: 'real', change_1d_pct: 3 })).toBe('real buying');
    expect(qualitySideNote({ quality_id: 'thin', change_1d_pct: 3 })).toBeNull();
  });

  it('filters breakouts by kind family and selection', () => {
    const rows = [
      { symbol: 'A', kinds: ['new_52w_high', 'accumulation'] },
      { symbol: 'B', kinds: ['gap_up'] },
      { symbol: 'C', kinds: ['distribution'] },
    ] as TodayBreakoutRow[];
    expect(filterByKinds(rows, ['new_52w_high', 'gap_up'], new Set()).map((r) => r.symbol)).toEqual(['A', 'B']);
    expect(filterByKinds(rows, ['new_52w_high', 'gap_up'], new Set(['gap_up'])).map((r) => r.symbol)).toEqual(['B']);
    expect(filterByKinds(rows, ['accumulation', 'distribution'], new Set()).map((r) => r.symbol)).toEqual(['A', 'C']);
    expect(kindCounts(rows)).toEqual({ new_52w_high: 1, accumulation: 1, gap_up: 1, distribution: 1 });
  });

  it('puts the evidence lift into the trait tooltip only when served', () => {
    expect(traitTitle('delivery_spike', undefined)).toMatch(/^Delivered shares > 2×/);
    expect(traitTitle('delivery_spike', [{ key: 'delivery_spike', lift_upper_circuit: 2.14, lift_test_upper_circuit: 2.19 }])).toContain('2.14×');
  });

  it('describes event timing relative to as_of', () => {
    expect(eventWhen({ event_type: 'financial_results', event_date: '2026-09-23' }, '2026-09-25')).toBe('results 2d ago');
    expect(eventWhen({ event_type: 'board_meeting', event_date: '2026-09-28' }, '2026-09-25')).toBe('results meeting in 3d');
    expect(eventWhen(null, '2026-09-25')).toBeNull();
  });

  it('picks leading / lagging groups, skipping thin ones', () => {
    const rows = [
      group({ group_name: 'Up', return_1d: 2, breadth_label: 'broad' }),
      group({ group_name: 'Thin', return_1d: 9, breadth_label: 'thin' }),
      group({ group_name: 'Down', return_1d: -1, breadth_label: 'mixed' }),
      group({ group_name: 'Null', return_1d: null }),
    ];
    const { up, down } = topBottomGroups(rows, 5);
    expect(up.map((g) => g.group_name)).toEqual(['Up']);
    expect(down.map((g) => g.group_name)).toEqual(['Down']);
  });

  it('scores broad moves above one-stock pops and hides thin groups by default', () => {
    const pop = group({ group_name: 'Pop', return_1d: 8, advancers: 1, decliners: 3, stocks: 4, stocks_with_return: 4 });
    const broad = group({ group_name: 'Broad', return_1d: 2, advancers: 9, decliners: 1, stocks: 10, stocks_with_return: 10 });
    const down = group({ group_name: 'Down', return_1d: -3, advancers: 0, decliners: 5, stocks: 5, stocks_with_return: 5 });
    expect(broadMoveScore(pop)).toBeCloseTo(2);
    expect(broadMoveScore(broad)).toBeCloseTo(1.8);
    expect(broadMoveScore(down)).toBeCloseTo(3);
    expect(broadMoveScore(group({ return_1d: null, stocks_with_return: 3 }))).toBeNull();
    const thin = group({ group_name: 'Thin', stocks: 1, stocks_with_return: 1 });
    expect(withoutThinGroups([pop, thin], false).map((g) => g.group_name)).toEqual(['Pop']);
    expect(withoutThinGroups([pop, thin], true)).toHaveLength(2);
  });

  it('renders served rule clauses in plain words', () => {
    expect(clauseText([{ field: 'rvol', op: 'gte', value: 1.5 }, { field: 'delivery_vs_20d', op: 'gte', value: 1.2 }])).toBe('RVOL ≥ 1.5 and delivery × ≥ 1.2');
    expect(clauseText([{ field: 'at_circuit', op: 'is_true', value: null }])).toBe('closed at price band is true');
  });
});
