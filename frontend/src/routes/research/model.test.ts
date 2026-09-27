import { describe, expect, it } from 'vitest';
import type { BigMoveRow, EnvelopeMeta, MarketAnalogRow } from '../../api/types';
import { ANALOG_ROWS, BIG_MOVE_ROWS, PRE_MOVE_ROWS, evidenceRows, fixtureFor } from './fixtures';
import {
  catalystShares,
  eventWindow,
  groupStudy,
  median,
  pivotFeatures,
  preMoveEdge,
  preMoveLift,
  readFeaturePath,
  readFeatures,
  readLift,
  summarizeAnalogs,
} from './model';

const meta = (context: Record<string, unknown>): EnvelopeMeta => ({ status: 'ok', offset: 0, limit: 0, context });

describe('median', () => {
  it('ignores NULLs and handles even counts', () => {
    expect(median([3, null, 1, 2])).toBe(2);
    expect(median([4, 1, 3, 2])).toBe(2.5);
    expect(median([null, undefined])).toBeNull();
  });
});

describe('summarizeAnalogs', () => {
  it('computes per-horizon median, range, up/down counts with n', () => {
    const s = summarizeAnalogs(ANALOG_ROWS);
    expect(s.k).toBe(10);
    const h20 = s.horizons.find((h) => h.horizon === 20)!;
    expect(h20.n).toBe(10);
    expect(h20.up).toBe(7);
    expect(h20.down).toBe(3);
    expect(h20.min).toBe(-4.1);
    expect(h20.max).toBe(7.5);
    expect(s.agreement20).toEqual({ share: 0.7, direction: 'up', n: 10 });
    expect(s.disagree).toBe(false);
  });

  it('flags disagreement when no direction reaches 70%', () => {
    const rows: MarketAnalogRow[] = [1, -1, 2, -2, 3, -3].map((v, i) => ({ analog_date: `2020-01-0${i + 1}`, fwd_midsml400_20d_pct: v }));
    const s = summarizeAnalogs(rows);
    expect(s.disagree).toBe(true);
    expect(s.agreement20.share).toBe(0.5);
  });

  it('keeps NULL forward returns out of n (no fabricated zeros)', () => {
    const s = summarizeAnalogs([
      { analog_date: '2020-01-01', fwd_midsml400_20d_pct: null },
      { analog_date: '2020-01-02', fwd_midsml400_20d_pct: 4 },
    ]);
    expect(s.horizons[1].n).toBe(1);
    expect(s.horizons[0].n).toBe(0);
    expect(s.horizons[0].median).toBeNull();
  });
});

describe('big movers', () => {
  it('rolls up catalyst shares over every event, unattributed included', () => {
    const rows: BigMoveRow[] = [{ catalyst: 'results' }, { catalyst: 'results' }, { catalyst: 'sector' }, { catalyst: null }];
    const r = catalystShares(rows);
    expect(r.total).toBe(4);
    expect(r.shares).toEqual([
      { catalyst: 'results', n: 2, share: 0.5 },
      { catalyst: 'sector', n: 1, share: 0.25 },
      { catalyst: 'unknown', n: 1, share: 0.25 },
    ]);
  });

  it('groups by any taxonomy level and never guesses a missing level', () => {
    const s = groupStudy(BIG_MOVE_ROWS, 'broad_industry');
    expect(s.total).toBe(BIG_MOVE_ROWS.length);
    expect(s.classified).toBe(BIG_MOVE_ROWS.length);
    const ad = s.rows.find((r) => r.group === 'Aerospace & Defense')!;
    expect(ad.events).toBe(4);
    expect(ad.sectorWide).toBe(2);
    const missing = groupStudy([{ symbol: 'X', industry: null }], 'sector');
    expect(missing.rows[0].group).toBe('Unclassified');
    expect(missing.classified).toBe(0);
  });

  it('reads lift, feature path and event features from meta.context defensively', () => {
    const env = fixtureFor({ endpoint: 'research/big-moves', asOf: null });
    expect(readLift(env.meta as EnvelopeMeta).length).toBeGreaterThan(3);
    expect(readFeaturePath(env.meta as EnvelopeMeta).every((p) => typeof p.offset === 'number')).toBe(true);
    expect(readLift(meta({ lift: [{ nope: 1 }, 'x', null] }))).toEqual([]);
    const det = fixtureFor({ endpoint: 'research/big-moves/{event_id}', params: { event_id: 'BM-00001' }, asOf: null });
    const feats = readFeatures(det.meta as EnvelopeMeta);
    const p = pivotFeatures(feats);
    expect(p.offsets).toEqual([-60, -20, -5, -1]);
    expect(p.features.find((f) => f.feature === 'rs_percentile')?.cells.get(-1)?.n_controls).toBe(10);
  });

  it('windows bars around the event without reaching past the data', () => {
    const bars = Array.from({ length: 100 }, (_, i) => ({ time: `2026-01-${String(i).padStart(3, '0')}` }));
    const w = eventWindow(bars, bars[90].time, 60, 20);
    expect(w[0]).toBe(bars[30]);
    expect(w[w.length - 1]).toBe(bars[99]);
  });

  it('fixtures honour as_of (no look-ahead)', () => {
    const env = fixtureFor({ endpoint: 'research/big-moves', asOf: '2026-08-01' });
    expect((env.rows as BigMoveRow[]).every((r) => (r.event_date ?? '') <= '2026-08-01')).toBe(true);
    expect(env.rows.length).toBeLessThan(BIG_MOVE_ROWS.length);
  });
});

describe('pre-move', () => {
  it('computes lift and labels insufficient samples', () => {
    const jyoti = PRE_MOVE_ROWS[0];
    expect(preMoveLift(jyoti)).toBeCloseTo(9.4 / 3.3);
    expect(preMoveEdge(jyoti)).toBe('edge');
    expect(preMoveEdge(PRE_MOVE_ROWS.find((r) => r.symbol === 'ANANTRAJ')!)).toBe('insufficient');
    expect(preMoveEdge(PRE_MOVE_ROWS.find((r) => r.symbol === 'SAILIFE')!)).toBe('unknown');
    expect(preMoveEdge(PRE_MOVE_ROWS.find((r) => r.symbol === 'TDPOWERSYS')!)).toBe('weak');
  });
});

describe('evidence fixtures', () => {
  it('null out numbers below n = 30', () => {
    const rows = evidenceRows('vcp', 'environment')!;
    const danger = rows.find((r) => r.bucket === 'Danger')!;
    expect(danger.insufficient_sample).toBe(true);
    expect(danger.avg_r).toBeNull();
    expect(danger.label).toBe('insufficient sample');
    expect(rows.find((r) => r.bucket === 'all')!.n).toBe(74 + 131 + 88 + 26 + 4);
  });
});
