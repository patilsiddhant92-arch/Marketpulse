import { describe, expect, it } from 'vitest';
import type { DealSessionRow } from '../../api/types';
import { chartsDealsHref, eventGroup, filterDeals, netBars, splitSession } from './dealsModel';

const d = (symbol: string, event_type: string | null, net: number | null, gross = 1): DealSessionRow =>
  ({ symbol, event_type, net_ex_prop_cr: net, net_cr: net, buy_cr: gross, sell_cr: 0 }) as DealSessionRow;

describe('dealsModel', () => {
  it('routes event types to the main table and rails', () => {
    expect(eventGroup('accumulate')).toBe('main');
    expect(eventGroup('placement')).toBe('strategic');
    expect(eventGroup('churn')).toBe('churn');
    expect(eventGroup(null)).toBe('other');
    const s = splitSession([d('A', 'distribute', -5), d('B', 'fresh', 3), d('C', 'accumulate', 1), d('D', 'accumulate', 9), d('E', 'churn', 0, 50), d('F', 'transfer_interse', 0, 99)]);
    expect(s.main.map((r) => r.symbol)).toEqual(['D', 'C', 'B', 'A']);
    expect(s.churn.map((r) => r.symbol)).toEqual(['E']);
    expect(s.strategic.map((r) => r.symbol)).toEqual(['F']);
  });

  it('filters on symbol, name or industry', () => {
    const rows = [{ symbol: 'POLICYBZR', security_name: 'PB Fintech', industry: 'Fintech' }, { symbol: 'AAA', security_name: null, industry: null }];
    expect(filterDeals(rows, 'fin').map((r) => r.symbol)).toEqual(['POLICYBZR']);
    expect(filterDeals(rows, '')).toHaveLength(2);
  });

  it('net bars scale to the largest |net| and keep "no deal" distinct from zero', () => {
    expect(netBars([null, 5, -10, 0])).toEqual([
      { v: null, h: 0 },
      { v: 5, h: 0.5 },
      { v: -10, h: 1 },
      { v: 0, h: 0 },
    ]);
    expect(netBars([null, null])).toEqual([
      { v: null, h: 0 },
      { v: null, h: 0 },
    ]);
  });

  it('charts link names the deals source', () => {
    const u = new URL(chartsDealsHref('buy', ['A'], null), 'http://x');
    expect(u.searchParams.get('source')).toBe('deals:buy');
    expect(u.searchParams.get('as_of')).toBeNull();
  });
});
