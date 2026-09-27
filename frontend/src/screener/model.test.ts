import { describe, expect, it } from 'vitest';
import { reconcileTabParams } from '../lib/tabUrlState';
import {
  SCREENER_DEFAULTS,
  decodeRules,
  describeFloors,
  encodeRules,
  filterQuery,
  lookbackDays,
  ruleComplete,
  ruleLabel,
  runQuery,
  sameRules,
  type RuleField,
} from './model';

const fields = new Map<string, RuleField>([
  ['rs_percentile', { field: 'rs_percentile', label: 'Strength rank', kind: 'num', metric_key: 'rs_percentile' }],
  ['close', { field: 'close', label: 'Close', kind: 'num' }],
  ['ema_200', { field: 'ema_200', label: '200 EMA', kind: 'num' }],
  ['nr7', { field: 'nr7', label: 'NR7', kind: 'bool' }],
]);

describe('screener rules', () => {
  it('labels rules in plain words', () => {
    expect(ruleLabel({ field: 'rs_percentile', op: 'gte', value: 70 }, fields)).toBe('Strength rank ≥ 70');
    expect(ruleLabel({ field: 'close', op: 'gt', ref: 'ema_200' }, fields)).toBe('Close > 200 EMA');
    expect(ruleLabel({ field: 'nr7', op: 'is_false' }, fields)).toBe('not NR7');
    expect(ruleLabel({ field: 'unknown_x', op: 'lt', value: 1.5 }, fields)).toBe('unknown_x < 1.5');
  });

  it('round-trips rules through the URL and strips display keys', () => {
    const rules = [
      { field: 'rs_percentile', op: 'gte' as const, value: 70, label: 'x' } as never,
      { field: 'close', op: 'gt' as const, ref: 'ema_200' },
      { field: 'nr7', op: 'is_true' as const, value: 3 },
    ];
    const enc = encodeRules(rules);
    expect(JSON.parse(enc)).toEqual([
      { field: 'rs_percentile', op: 'gte', value: 70 },
      { field: 'close', op: 'gt', ref: 'ema_200' },
      { field: 'nr7', op: 'is_true' },
    ]);
    expect(decodeRules(enc)).toEqual(JSON.parse(enc));
    expect(sameRules(decodeRules(enc)!, rules)).toBe(true);
  });

  it('rejects malformed URL rules instead of guessing', () => {
    expect(decodeRules('not json')).toBeNull();
    expect(decodeRules('{"field":"close"}')).toBeNull();
    expect(decodeRules('[{"field":"close","op":"like","value":1}]')).toBeNull();
    expect(decodeRules('')).toBeNull();
  });

  it('requires a value or ref on numeric rules', () => {
    expect(ruleComplete({ field: 'close', op: 'gt', value: null })).toBe(false);
    expect(ruleComplete({ field: 'close', op: 'gt', ref: 'ema_200' })).toBe(true);
    expect(ruleComplete({ field: 'nr7', op: 'is_true' })).toBe(true);
  });
});

describe('screener query', () => {
  it('sends only the preset when rules are untouched, with honest floors', () => {
    const q = runQuery(SCREENER_DEFAULTS);
    expect(q).toMatchObject({ preset: 'minervini_8of8', min_mcap_cr: 1000, min_price: 15, lookback_days: 1 });
    expect(q).not.toHaveProperty('rules');
    expect(q).not.toHaveProperty('min_day_volume');
    expect(q).not.toHaveProperty('include_ipos');
  });

  it('keeps day volume and 20-day average volume distinct', () => {
    const q = filterQuery({ ...SCREENER_DEFAULTS, vol: '50000', avgvol: '200000' });
    expect(q.min_day_volume).toBe(50000);
    expect(q.min_avg_volume_20d).toBe(200000);
  });

  it('sends custom rules, group and IPO flags when set', () => {
    const rules = encodeRules([{ field: 'close', op: 'gt', value: 10 }]);
    const q = runQuery({ ...SCREENER_DEFAULTS, rules, ipo: '1', level: 'industry', group: 'Pharmaceuticals', price: '' });
    expect(q.rules).toBe(rules);
    expect(q).toMatchObject({ include_ipos: true, level: 'industry', group: 'Pharmaceuticals', min_price: 0 });
  });

  it('clamps the lookback window', () => {
    expect(lookbackDays({ ...SCREENER_DEFAULTS, lb: '500' })).toBe(60);
    expect(lookbackDays({ ...SCREENER_DEFAULTS, lb: 'x' })).toBe(1);
  });

  it('describes floors, and only the group for Desk-queue presets', () => {
    expect(describeFloors(SCREENER_DEFAULTS, false)).toEqual(['mcap ≥ ₹1,000 Cr', 'price ≥ ₹15']);
    expect(describeFloors({ ...SCREENER_DEFAULTS, level: 'sector', group: 'Healthcare' }, true)).toEqual(['Healthcare']);
  });
});

describe('tab URL state', () => {
  const defaults = { preset: 'a', lb: '1' };
  it('lets URL params win and keeps defaults out of the URL', () => {
    const r = reconcileTabParams(new URLSearchParams('preset=b&lb=1'), { preset: 'a', lb: '5' }, defaults);
    expect(r.state).toEqual({ preset: 'b', lb: '1' });
    expect(r.writes).toEqual({ lb: null });
  });
  it('restores non-default state into a URL that lost it on tab switch', () => {
    const r = reconcileTabParams(new URLSearchParams(''), { preset: 'b', lb: '1' }, defaults);
    expect(r.state).toEqual({ preset: 'b', lb: '1' });
    expect(r.writes).toEqual({ preset: 'b' });
  });
});
