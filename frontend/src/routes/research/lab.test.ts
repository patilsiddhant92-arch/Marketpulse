import { describe, expect, it } from 'vitest';
import { caseMarkers } from './CaseChart';
import { analogEdge, caveatOf, compound, dateTicks, fireMarkers, precisionLift, rebasePct, ribbonRuns, traitName, type Fire, type LadderLeg } from './lab';

const fire = (date: string, letter: string, preset_id: string, in_move = true): Fire => ({
  date,
  letter,
  preset_id,
  preset: preset_id,
  close: 100,
  in_move,
});

describe('research lab model', () => {
  it('ribbonRuns merges consecutive sessions of one quadrant and keeps unclassified gaps', () => {
    const runs = ribbonRuns([{ quadrant: null }, { quadrant: 'chop' }, { quadrant: 'chop' }, { quadrant: 'press' }, { quadrant: 'bogus' }]);
    expect(runs).toEqual([
      { from: 0, to: 0, q: null },
      { from: 1, to: 2, q: 'chop' },
      { from: 3, to: 3, q: 'press' },
      { from: 4, to: 4, q: null },
    ]);
  });

  it('fireMarkers groups letters per session, filters to the move and hidden presets', () => {
    const fires = [fire('2025-09-12', 'D', 'delivery_thrust'), fire('2025-09-12', 'C', 'emas_converge'), fire('2025-08-01', 'N', 'near_52w_high', false)];
    expect(fireMarkers(fires, false).map((m) => [m.time, m.text])).toEqual([
      ['2025-08-01', 'N'],
      ['2025-09-12', 'DC'],
    ]);
    expect(fireMarkers(fires, true).map((m) => m.text)).toEqual(['DC']);
    expect(fireMarkers(fires, true, new Set(['delivery_thrust'])).map((m) => m.text)).toEqual(['C']);
  });

  it('compound multiplies leg returns', () => {
    expect(compound([])).toBe(0);
    expect(compound([{ pnl_pct: 10 }, { pnl_pct: -10 }])).toBeCloseTo(-1, 6);
  });

  it('caseMarkers are time-sorted, with entries below and closed exits above with P&L', () => {
    const legs: LadderLeg[] = [
      { entry_date: '2025-09-12', signal_id: 'd', signal: 'Delivery thrust', letter: 'D', entry: 1, exit_date: '2025-10-01', exit: 2, pnl_pct: 47, open: false },
      { entry_date: '2026-08-05', signal_id: 'v', signal: 'VCP flag', letter: 'V', entry: 1, exit_date: '2026-08-13', exit: 1, pnl_pct: 9.1, open: true },
    ];
    const m = caseMarkers([{ time: '2025-09-20', text: 'N', inMove: true }], legs, { fire: 'f', fireOut: 'o', up: 'u', down: 'd' });
    expect(m.map((x) => [x.time, x.position, x.text])).toEqual([
      ['2025-09-12', 'belowBar', 'B D'],
      ['2025-09-20', 'aboveBar', 'N'],
      ['2025-10-01', 'aboveBar', 'S +47.0%'],
      ['2026-08-05', 'belowBar', 'B V'],
    ]);
  });

  it('small readers', () => {
    expect(rebasePct([null, 100, 110, null])).toEqual([null, 0, 10.000000000000009, null]);
    expect(dateTicks(['2025-01-02', '2025-02-03', '2025-03-04'], 3)).toEqual([
      { x: 0, label: '25-01' },
      { x: 1, label: '25-02' },
      { x: 2, label: '25-03' },
    ]);
    expect(analogEdge({ horizon: 20, n: 10, median: -0.5, mean: null, min: null, max: null, up_pct: null, base_median: 1.4, base_up_pct: null, base_n: 500 })).toBeCloseTo(-1.9);
    expect(precisionLift({ hit_pct: 13.2 }, 9.5)).toBeCloseTo(1.389, 2);
    expect(precisionLift({ hit_pct: null }, 9.5)).toBeNull();
    expect(traitName('B: 50d range %')).toBe('50d range %');
    expect(caveatOf(undefined)).toMatch(/not advice/);
    expect(caveatOf({ context: { caveat: 'X' } } as never)).toBe('X');
  });
});
