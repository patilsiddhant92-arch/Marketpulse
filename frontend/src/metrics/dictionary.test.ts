import { describe, expect, it } from 'vitest';
import type { MetricDef } from '../api/types';
import { toneForZone, zoneBounds, zoneFor } from './dictionary';

const participation: MetricDef = {
  key: 'pct_above_50ema',
  plain_name: 'Stocks above 50 EMA',
  measures: 'Share of stocks trading above their 50-day EMA',
  zones: [
    { range: '< 40', label: 'Weak', tone: 'bad', why: 'Most stocks in downtrends' },
    { range: '40–60', label: 'Neutral', tone: 'neutral' },
    { range: '> 60', label: 'Healthy', tone: 'good' },
  ],
  read_with: ['pct_above_200ema'],
  definition_sql_ref: 'breadth_daily.pct_above_50ema',
};

describe('zoneBounds', () => {
  it('parses the dictionary range strings', () => {
    expect(zoneBounds({ range: '> 60' })).toMatchObject({ min: 60, max: null, minInclusive: false });
    expect(zoneBounds({ range: '<= 40' })).toMatchObject({ min: null, max: 40, maxInclusive: true });
    expect(zoneBounds({ range: '40-60%' })).toMatchObject({ min: 40, max: 60 });
    expect(zoneBounds({ range: '1.5x' })).toBeUndefined();
    expect(zoneBounds({ range: '>= 1.5x' })).toMatchObject({ min: 1.5, max: null, minInclusive: true });
    expect(zoneBounds({ range: '-5 to 5' })).toMatchObject({ min: -5, max: 5 });
    expect(zoneBounds({ range: 'rising' })).toBeUndefined();
  });
});

describe('zoneFor', () => {
  it('finds the zone for a value', () => {
    expect(zoneFor(participation, 25)?.label).toBe('Weak');
    expect(zoneFor(participation, 40)?.label).toBe('Neutral');
    expect(zoneFor(participation, 59.9)?.label).toBe('Neutral');
    expect(zoneFor(participation, 60)?.label).toBe('Neutral');
    expect(zoneFor(participation, 60.01)?.label).toBe('Healthy');
    expect(zoneFor(participation, 75)?.label).toBe('Healthy');
  });
  it('never invents a zone for NULL or a missing definition', () => {
    expect(zoneFor(participation, null)).toBeUndefined();
    expect(zoneFor(participation, Number.NaN)).toBeUndefined();
    expect(zoneFor(undefined, 50)).toBeUndefined();
  });
});

describe('toneForZone', () => {
  it('maps served tones (good/neutral/caution/bad), else infers from the label', () => {
    expect(toneForZone({ range: '>1', label: 'Anything', tone: 'good' })).toBe('positive');
    expect(toneForZone({ range: '>1', label: 'Anything', tone: 'caution' })).toBe('warn');
    expect(toneForZone({ range: '>1', label: 'Anything', tone: 'bad' })).toBe('negative');
    expect(toneForZone({ range: '>1', label: 'Healthy' })).toBe('positive');
    expect(toneForZone({ range: '>1', label: 'Weak' })).toBe('negative');
    expect(toneForZone({ range: '>80', label: 'Stretched' })).toBe('warn');
    expect(toneForZone({ range: '>1', label: 'Neutral' })).toBe('neutral');
    expect(toneForZone(undefined)).toBeUndefined();
  });
});
