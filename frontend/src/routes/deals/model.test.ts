import { afterEach, describe, expect, it } from 'vitest';
import { tradingViewTicker } from '../../lib/tradingview';
import type { DealRow } from './api';
import { readFollowed, shownValue, sortByVerdict, splitNoise, spreadSummary, toggleFollowed, tvListText, tvSectionsText, tvTitle, viewFromParam } from './model';

const row = (over: Partial<DealRow>): DealRow =>
  ({ symbol: 'AAA', verdict: 'none', net_cr: 0, bought_cr: 0, event_type: 'fresh', ...over }) as DealRow;

describe('TradingView copy', () => {
  it('maps - and & to _ and prefixes NSE:', () => {
    expect(tradingViewTicker('bajaj-auto')).toBe('BAJAJ_AUTO');
    expect(tradingViewTicker('M&M')).toBe('M_M');
    expect(tvListText({ title: 'Deals Today', symbols: ['BAJAJ-AUTO', 'M&M', 'TCS', 'TCS'] })).toEqual({
      text: '###Deals Today,NSE:BAJAJ_AUTO,NSE:M_M,NSE:TCS',
      count: 3,
    });
  });

  it('keeps commas and dots out of the ### title', () => {
    expect(tvTitle('Deal watch · last 10, holding')).toBe('Deal watch last 10 holding');
  });

  it('copies every list as ### sections and skips empty lists', () => {
    const r = tvSectionsText([
      { title: 'A', symbols: ['X', 'Y'] },
      { title: 'Empty', symbols: [] },
      { title: 'B', symbols: ['X'] },
    ]);
    expect(r.text).toBe('###A,NSE:X,NSE:Y\n###B,NSE:X');
    expect(r.lists).toBe(2);
  });
});

describe('views and rows', () => {
  it('maps the old 8-view URLs to the new views', () => {
    expect(viewFromParam(null)).toBe('today');
    expect(viewFromParam('repeated')).toBe('history');
    expect(viewFromParam('star')).toBe('houses');
    expect(viewFromParam('follow')).toBe('today');
    expect(viewFromParam('groups')).toBe('groups');
  });

  it('sorts by verdict order, then by size', () => {
    const out = sortByVerdict([row({ symbol: 'N', verdict: 'none', net_cr: 50 }), row({ symbol: 'C', verdict: 'confirm', net_cr: 1 }), row({ symbol: 'P', verdict: 'place', net_cr: 9 }), row({ symbol: 'P2', verdict: 'place', net_cr: -20 })]);
    expect(out.map((r) => r.symbol)).toEqual(['C', 'P2', 'P', 'N']);
  });

  it('hides churn, transfers and no-edge rows as noise', () => {
    const { main, noise } = splitNoise([row({ verdict: 'churn' }), row({ verdict: 'ignore' }), row({ verdict: 'none' }), row({ verdict: 'watch' }), row({ verdict: 'avoid' })]);
    expect(main.map((r) => r.verdict)).toEqual(['watch', 'avoid']);
    expect(noise).toHaveLength(3);
  });

  it('shows the bought value for placements and near-zero nets', () => {
    expect(shownValue(row({ event_type: 'placement', net_cr: 0, bought_cr: 180 }))).toEqual({ value: 180, bought: true });
    expect(shownValue(row({ event_type: 'distribute', net_cr: -25, bought_cr: 5 }))).toEqual({ value: -25, bought: false });
  });

  it('summarises a fund spread as group count + top-3 shares', () => {
    const s = spreadSummary([
      { industry: 'E-Retail/ E-Commerce', share_pct: 60 },
      { industry: 'Financial Technology (Fintech)', share_pct: 30 },
      { industry: 'Healthcare Service Provider', share_pct: 7 },
      { industry: 'Banks', share_pct: 3 },
    ]);
    expect(s.groups).toBe(4);
    expect(s.top).toEqual([
      { label: 'E-Retail', pct: 60 },
      { label: 'Financial', pct: 30 },
      { label: 'Healthcare', pct: 7 },
    ]);
  });
});

describe('follow', () => {
  afterEach(() => window.localStorage.clear());
  it('toggles a followed house in local storage', () => {
    expect(readFollowed()).toEqual([]);
    expect(toggleFollowed('SBI MUTUAL FUND')).toEqual(['SBI MUTUAL FUND']);
    expect(readFollowed()).toEqual(['SBI MUTUAL FUND']);
    expect(toggleFollowed('SBI MUTUAL FUND')).toEqual([]);
  });
});
