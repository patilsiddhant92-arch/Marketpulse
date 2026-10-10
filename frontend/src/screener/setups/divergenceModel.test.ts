import { describe, expect, it } from 'vitest';
import type { DivergenceScanRow } from '../../api/types';
import { divergenceQuery, divergenceTvText, filterDivergences, sideTone, statusTone } from './divergenceModel';

const row = (symbol: string, side: 'bull' | 'bear', type: 'Strong' | 'Medium' | 'Weak' | 'Hidden', industry = 'Steel'): DivergenceScanRow => ({
  symbol,
  side,
  type,
  tf: 'D',
  industry,
  group: industry,
  p1_date: '2026-07-01',
  p2_date: '2026-07-20',
  p1_price: 100,
  p2_price: 95,
  p1_rsi: 30,
  p2_rsi: 36,
  confirm_date: '2026-07-23',
  trigger_price: 110,
  stop_price: 95,
  status: 'watching',
  bars_apart: 13,
  bars_since_confirm: 0,
});

describe('divergenceQuery', () => {
  it('builds the API query and drops junk', () => {
    expect(divergenceQuery({ dtf: 'W', dside: 'bull', dtypes: 'Strong,Hidden,Bogus', dwin: '10' })).toEqual({
      tf: 'W',
      window: 10,
      limit: 5000,
      side: 'bull',
      types: 'Strong,Hidden',
    });
    expect(divergenceQuery({ dtf: 'X', dside: 'up', dtypes: '', dwin: '999' })).toEqual({ tf: 'D', window: 60, limit: 5000 });
    expect(divergenceQuery({ dtf: 'M', dside: '', dtypes: '', dwin: 'abc' }).window).toBe(5);
  });
});

describe('filterDivergences', () => {
  it('matches symbol or industry', () => {
    const rows = [row('AAA', 'bull', 'Strong'), row('BBB', 'bear', 'Weak', 'Drugs')];
    expect(filterDivergences(rows, 'drug').map((r) => r.symbol)).toEqual(['BBB']);
    expect(filterDivergences(rows, '').length).toBe(2);
  });
});

describe('divergenceTvText', () => {
  it('sections bull before bear, Strong before Hidden, de-duplicated', () => {
    const { text, count } = divergenceTvText(
      [row('ZZZ', 'bear', 'Strong'), row('M-M', 'bull', 'Hidden'), row('AAA', 'bull', 'Strong'), row('AAA', 'bull', 'Hidden')],
      'D',
    );
    expect(text).toBe('###RSI div Bull Strong D,NSE:AAA,###RSI div Bull Hidden D,NSE:M_M,###RSI div Bear Strong D,NSE:ZZZ');
    expect(count).toBe(3);
  });
});

describe('tones', () => {
  it('maps side and status', () => {
    expect(sideTone('bull')).toBe('positive');
    expect(sideTone('bear')).toBe('negative');
    expect(statusTone('triggered')).toBe('accent');
    expect(statusTone('failed')).toBe('warn');
    expect(statusTone('watching')).toBe('neutral');
  });
});
