import { describe, expect, it } from 'vitest';
import type { DiffRow, GroupRow, MarketHealthRow, QueueRow } from '../api/types';
import { asQueueId, asTf, breadthSeries, breadthSnapshot, countFlags, evidenceFor, filterQueueRows, groupDiff, leadingGroups } from './deskModel';

const q = (o: Partial<QueueRow>): QueueRow => ({ queue: 'vcp', timeframe: 'D', risk_flag: false, ...o }) as QueueRow;

describe('deskModel', () => {
  it('validates URL queue / timeframe', () => {
    expect(asQueueId('vcp')).toBe('vcp');
    expect(asQueueId('nope')).toBe('darvas_squeeze');
    expect(asTf('W', 'darvas_10ema')).toBe('W');
    expect(asTf('W', 'vcp')).toBe('D'); // VCP is daily only
  });

  it('filters by text and New-only', () => {
    const rows = [q({ symbol: 'HAL', industry: 'Aerospace & Defense', is_new: true }), q({ symbol: 'TCS', industry: 'IT', is_new: false }), q({ symbol: 'ABB', is_new: null })];
    expect(filterQueueRows(rows, 'aero', false).map((r) => r.symbol)).toEqual(['HAL']);
    expect(filterQueueRows(rows, '', true).map((r) => r.symbol)).toEqual(['HAL']);
    expect(filterQueueRows(rows, '  ', false)).toHaveLength(3);
  });

  it('groups the diff per queue, strongest first, NULL rank last', () => {
    const d = (queue: string, change: 'new' | 'dropped', symbol: string, rs: number | null): DiffRow => ({ queue, timeframe: 'D', change, symbol, rs_percentile: rs });
    const g = groupDiff([d('vcp', 'new', 'A', 50), d('vcp', 'new', 'B', null), d('vcp', 'new', 'C', 90), d('vcp', 'dropped', 'D', 10)]);
    expect(g.vcp.added.map((r) => r.symbol)).toEqual(['C', 'A', 'B']);
    expect(g.vcp.dropped.map((r) => r.symbol)).toEqual(['D']);
    expect(g.darvas_squeeze.added).toEqual([]);
  });

  it('breadth snapshot: 1-session change only when both sessions have a value', () => {
    const rows = [
      { trade_date: '2026-09-25', pct_above_50ema: 39.71, net_new_highs: -18, india_vix: null },
      { trade_date: '2026-09-24', pct_above_50ema: 38.49, net_new_highs: -7, india_vix: 12.69 },
    ] as MarketHealthRow[];
    const s = breadthSnapshot(rows);
    const by = Object.fromEntries(s.readings.map((r) => [r.key, r]));
    expect(s.date).toBe('2026-09-25');
    expect(by.pct_above_50ema.delta).toBeCloseTo(1.22);
    expect(by.net_new_highs.delta).toBe(-11);
    expect(by.india_vix).toEqual({ key: 'india_vix', value: null, delta: null });
    expect(breadthSnapshot([]).readings).toEqual([]);
    expect(breadthSeries(rows, 'pct_above_50ema')).toEqual([38.49, 39.71]);
  });

  it('leading groups: RRG Leading when served, else ranked groups with enough members', () => {
    const g = (o: Partial<GroupRow>): GroupRow => ({ id: o.group_name, level: 'industry', ...o }) as GroupRow;
    const legacy = [g({ group_name: 'Tiny', rank: 1, stocks: 2 }), g({ group_name: 'Big', rank: 2, stocks: 20 }), g({ group_name: 'Mid', rank: 3, stocks: 5 })];
    const a = leadingGroups(legacy);
    expect(a.rrg).toBe(false);
    expect(a.rows.map((r) => r.group_name)).toEqual(['Big', 'Mid']);
    const rrg = [g({ group_name: 'L2', rank: 5, rrg_quadrant: 'Leading' }), g({ group_name: 'W', rank: 1, rrg_quadrant: 'Weakening' }), g({ group_name: 'L1', rank: 2, rrg_quadrant: 'Leading' })];
    const b = leadingGroups(rrg);
    expect(b.rrg).toBe(true);
    expect(b.rows.map((r) => r.group_name)).toEqual(['L1', 'L2']);
  });

  it('evidence picks the all-states row and the current verdict row', () => {
    const rows = [
      { bucket: 'all', n: 100, insufficient_sample: false },
      { bucket: 'Constructive', n: 40, insufficient_sample: false },
    ];
    expect(evidenceFor(rows, 'Constructive').now?.n).toBe(40);
    expect(evidenceFor(rows, null).now).toBeNull();
    expect(evidenceFor([], 'Weak')).toEqual({ all: null, now: null });
  });

  it('counts flags honestly (NULL distance is not "past trigger")', () => {
    const f = countFlags([q({ is_new: true, distance_to_trigger_pct: -1 }), q({ risk_flag: true, distance_to_trigger_pct: null, results_within_10: true })]);
    expect(f).toEqual({ isNew: 1, results: 1, wideRisk: 1, pastTrigger: 1 });
  });
});
