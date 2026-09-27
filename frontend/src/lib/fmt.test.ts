import { describe, expect, it } from 'vitest';
import {
  DASH,
  fmtCompactIN,
  fmtCr,
  fmtDate,
  fmtDateShort,
  fmtDateWithDay,
  fmtINR,
  fmtInt,
  fmtL,
  fmtNum,
  fmtPct,
  fmtRatio,
  fmtRupeesCompact,
  fmtSigned,
  fmtSignedPct,
  fmtValue,
  fmtWeekday,
  parseISODate,
} from './fmt';

describe('NULL stays NULL', () => {
  const nulls = [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY];
  it.each(nulls)('every numeric formatter returns the dash for %s', (v) => {
    for (const f of [fmtNum, fmtInt, fmtINR, fmtCr, fmtL, fmtRupeesCompact, fmtPct, fmtSignedPct, fmtSigned, fmtRatio, fmtCompactIN]) {
      expect(f(v as number)).toBe(DASH);
    }
  });
  it('dates return the dash for empty or garbage input', () => {
    expect(fmtDate(null)).toBe(DASH);
    expect(fmtDate('')).toBe(DASH);
    expect(fmtDate('not a date')).toBe(DASH);
    expect(fmtDate('2026-13-01')).toBe(DASH);
  });
  it('zero is a value, not NULL', () => {
    expect(fmtNum(0)).toBe('0.00');
    expect(fmtPct(0)).toBe('0.0%');
    expect(fmtInt(0)).toBe('0');
  });
});

describe('Indian grouping', () => {
  it('groups lakhs and crores', () => {
    expect(fmtNum(1234567.891)).toBe('12,34,567.89');
    expect(fmtInt(123456789)).toBe('12,34,56,789');
  });
  it('formats rupees', () => {
    expect(fmtINR(1234.5)).toBe('₹1,234.50');
    expect(fmtINR(1234.5, 0)).toBe('₹1,235');
  });
  it('formats values already in crores / lakhs', () => {
    expect(fmtCr(12345.67)).toBe('₹12,345.7 Cr');
    expect(fmtCr(1000, 0)).toBe('₹1,000 Cr');
    expect(fmtL(12.5)).toBe('₹12.5 L');
  });
  it('picks Cr / L / plain by magnitude', () => {
    expect(fmtRupeesCompact(25_000_000)).toBe('₹2.50 Cr');
    expect(fmtRupeesCompact(450_000)).toBe('₹4.50 L');
    expect(fmtRupeesCompact(950)).toBe('₹950');
    expect(fmtRupeesCompact(-25_000_000)).toBe('-₹2.50 Cr');
    expect(fmtCompactIN(12_500_000)).toBe('1.25 Cr');
    expect(fmtCompactIN(99_999)).toBe('99,999');
  });
});

describe('percent', () => {
  it('formats percent units', () => {
    expect(fmtPct(12.345)).toBe('12.3%');
    expect(fmtPct(12.345, 2)).toBe('12.35%');
  });
  it('signs percent and treats rounded zero as unsigned', () => {
    expect(fmtSignedPct(1.24)).toBe('+1.2%');
    expect(fmtSignedPct(-0.55)).toBe('-0.6%');
    expect(fmtSignedPct(0)).toBe('0.0%');
    expect(fmtSignedPct(-0.01)).toBe('0.0%');
    expect(fmtSignedPct(1234.5, 1)).toBe('+1,234.5%');
  });
  it('signs plain numbers (rank deltas)', () => {
    expect(fmtSigned(3)).toBe('+3');
    expect(fmtSigned(-2)).toBe('-2');
    expect(fmtSigned(0)).toBe('0');
  });
  it('ratios', () => {
    expect(fmtRatio(1.534)).toBe('1.53x');
  });
});

describe('dates', () => {
  it('parses calendar dates without timezone drift', () => {
    expect(parseISODate('2026-09-25')).toEqual({ y: 2026, m: 9, d: 25 });
    expect(parseISODate('2026-09-25T23:30:00Z')).toEqual({ y: 2026, m: 9, d: 25 });
  });
  it('formats', () => {
    expect(fmtDate('2026-09-25')).toBe('25 Sep 2026');
    expect(fmtDateShort('2026-01-05')).toBe('5 Jan');
    expect(fmtWeekday('2026-09-25')).toBe('Fri');
    expect(fmtDateWithDay('2026-11-08')).toBe('Sun 8 Nov');
  });
});

describe('fmtValue dispatch', () => {
  it('routes by kind and keeps NULL', () => {
    expect(fmtValue(12.34, 'pct')).toBe('12.3%');
    expect(fmtValue(2.5, 'signedPct', 2)).toBe('+2.50%');
    expect(fmtValue(1500, 'cr', 0)).toBe('₹1,500 Cr');
    expect(fmtValue('2026-09-25', 'date')).toBe('25 Sep 2026');
    expect(fmtValue('HAL', 'text')).toBe('HAL');
    expect(fmtValue(null, 'num')).toBe(DASH);
    expect(fmtValue('', 'text')).toBe(DASH);
    expect(fmtValue(Number.NaN, 'text')).toBe(DASH);
  });
});
