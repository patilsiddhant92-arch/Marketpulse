import { describe, expect, it } from 'vitest';
import type { RegimeRow } from '../api/types';
import { asVerdict, describeChange, toEnvironmentView } from './regimeView';

const pillar = (status: string | null, inputs: Record<string, unknown> = {}) => ({
  status,
  sentence: null,
  dir_1d: 'rising',
  dir_1w: null,
  dir_1m: 'down',
  inputs,
});

const row = (over: Partial<RegimeRow> = {}): RegimeRow => ({
  trade_date: '2026-09-25',
  verdict: 'weak',
  previous_verdict: 'Mixed',
  rule_id: 'R4',
  days_in_state: 2,
  changed_on: '2026-09-24',
  readings: ['Narrow rally'],
  pillars: {
    trend: pillar('Weak', { pct_above_50ema: 38.2, state: 'below 200', missing: null }),
    participation: pillar('neutral'),
    leadership: pillar('bogus'),
    follow_through: pillar(null),
    stress: pillar('Healthy'),
  },
  inputs: {},
  ...over,
});

describe('regime view', () => {
  it('normalises verdict case and rejects unknown words', () => {
    expect(asVerdict('weak')).toBe('Weak');
    expect(asVerdict('Sunny')).toBeNull();
    expect(asVerdict(null)).toBeNull();
  });

  it('describes changes from served fields only', () => {
    expect(describeChange('Weak', 'Mixed', '2026-09-24', 2)).toBe('worsened from Mixed on Thu · 2nd day');
    expect(describeChange('Favourable', 'Constructive', null, 11)).toBe('improved from Constructive · 11th day');
    expect(describeChange('Mixed', null, null, 23)).toBe('23rd day in this state');
    expect(describeChange('Mixed', null, null, null)).toBeNull();
    expect(describeChange(null, 'Mixed', '2026-09-24', 1)).toBeNull();
  });

  it('builds pillars in spec order with honest statuses and split inputs', () => {
    const v = toEnvironmentView([row(), row({ trade_date: '2026-09-24', verdict: 'Mixed' })])!;
    expect(v.verdict).toBe('Weak');
    expect(v.pillars.map((p) => p.key)).toEqual(['trend', 'participation', 'leadership', 'follow_through', 'stress']);
    expect(v.pillars.map((p) => p.status)).toEqual(['Weak', 'Neutral', null, null, 'Healthy']);
    expect(v.pillars[0].dir1d).toBe('up');
    expect(v.pillars[0].dir1m).toBe('down');
    expect(v.pillars[0].metrics).toEqual([
      { metric: 'pct_above_50ema', value: 38.2 },
      { metric: 'missing', value: null },
    ]);
    expect(v.pillars[0].notes).toEqual([{ key: 'state', value: 'below 200' }]);
    expect(v.readings).toEqual([{ id: '0', title: 'Narrow rally', text: '', tone: 'neutral' }]);
    expect(v.history.map((h) => h.date)).toEqual(['2026-09-24', '2026-09-25']);
  });

  it('returns null for no rows and tolerates unexpected readings', () => {
    expect(toEnvironmentView([])).toBeNull();
    expect(toEnvironmentView([row({ readings: { weird: true } })])!.readings).toEqual([]);
  });
});
