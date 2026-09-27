import { describe, expect, it } from 'vitest';
import { filterRepeated, houseOf, inPlayScope, matchesPersistence, persistenceCounts, uniqueSymbols } from './deskModel';
import { formatTradingViewList } from '../../lib/tradingview';

describe('deals desk model', () => {
  it('persistence pills follow the old desk (4 = 4+, else exact)', () => {
    expect(matchesPersistence(5, 4)).toBe(true);
    expect(matchesPersistence(3, 4)).toBe(false);
    expect(matchesPersistence(3, 3)).toBe(true);
    expect(matchesPersistence(4, 3)).toBe(false);
    expect(matchesPersistence(1, 0)).toBe(true);
    expect(persistenceCounts([{ deal_days: 1 }, { deal_days: 2 }, { deal_days: 3 }, { deal_days: 6 }, { deal_days: 4 }])).toEqual({ 2: 1, 3: 1, 4: 2 });
  });

  it('repeated filter uses session count and net direction (NULL net is neither buy nor sell)', () => {
    const rows = [
      { deal_days: 1, flow_net_cr: 5 },
      { deal_days: 2, flow_net_cr: 5 },
      { deal_days: 3, flow_net_cr: -2 },
      { deal_days: 4, flow_net_cr: null },
    ];
    expect(filterRepeated(rows, 2, 'all')).toHaveLength(3);
    expect(filterRepeated(rows, 2, 'buy')).toEqual([rows[1]]);
    expect(filterRepeated(rows, 2, 'sell')).toEqual([rows[2]]);
  });

  it('play scope = conviction + fresh', () => {
    expect(inPlayScope('conviction', 'play')).toBe(true);
    expect(inPlayScope('fresh', 'play')).toBe(true);
    expect(inPlayScope('distribution', 'play')).toBe(false);
    expect(inPlayScope('transfer', 'transfer')).toBe(true);
  });

  it('TradingView copy: unique NSE: symbols, section header, dash to underscore', () => {
    const syms = uniqueSymbols([{ symbol: 'BAJAJ-AUTO' }, { symbol: 'TCS' }, { symbol: 'TCS' }, { symbol: null }]);
    expect(syms).toEqual(['BAJAJ-AUTO', 'TCS']);
    expect(formatTradingViewList([{ title: 'Deals Play 20s', symbols: syms }])).toEqual({ text: '###Deals Play 20s,NSE:BAJAJ_AUTO,NSE:TCS', count: 2 });
  });

  it('house label strips the net suffix', () => {
    expect(houseOf('GOLDMAN SACHS (+12.5)')).toBe('GOLDMAN SACHS');
    expect(houseOf('X FUND (-3)')).toBe('X FUND');
  });
});
