/** Deals tab smoke: the five views, noise toggle, drawers and TradingView copy, from fixture envelopes. */
import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../../App';
import { routes } from '..';

vi.mock('../../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));
const copied: string[] = [];
vi.mock('../../lib/clipboard', () => ({ copyText: async (t: string) => (copied.push(t), true) }));

const FRESH = { status: 'fresh', latest_session: '2026-08-13', expected_session: '2026-08-13', sessions_behind: 0, history_mode: false };
const env = (rows: unknown[], context: Record<string, unknown> = {}, notes: string[] = []) => ({
  as_of: '2026-08-13',
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', reason: null, offset: 0, limit: 500, sources: ['deal_session_net'], notes, metric_keys: [], context },
});

const party = (name: string, cls: string, grade = 'ungraded') => ({ name, house: name.toUpperCase(), buyer_class: cls, value_cr: 30, grade, record_n: 0 });
const deal = (over: Record<string, unknown>) => ({
  symbol: 'SEAMECLTD',
  name: 'Seamec Ltd',
  deal_date: '2026-08-13',
  sessions_since: 0,
  event_type: 'fresh',
  side: 'B',
  event_label: 'Net buy (new)',
  verdict: 'watch',
  verdict_title: 'Confirms setup: check day 3',
  why: 'Strong chart and a net buy.',
  next_action: 'Watch it. It confirms if it closes above ₹1,529.25 for 3 sessions.',
  net_cr: 30.7,
  bought_cr: 30.7,
  gross_cr: 30.7,
  prop_cr: 0,
  deal_price: 1529.25,
  close: 1540,
  vs_deal_pct: 0.7,
  status: 'day 0',
  strong_chart: true,
  rs: 88,
  from_high_pct: -4,
  month_pct: 6,
  rvol: 2,
  mcap_cr: 3900,
  industry: 'Shipping',
  sector: 'Services',
  buyers: [party('360 One Pipe', 'DII', 'good')],
  sellers: [],
  chips: [],
  ...over,
});
const TODAY = [
  deal({}),
  deal({ symbol: 'BAJAJ-AUTO', verdict: 'place', verdict_title: 'Placement on a strong chart', event_type: 'placement', side: 'P', net_cr: 0, bought_cr: 180, chips: ['Placement + strong chart'] }),
  deal({ symbol: 'KSCL', verdict: 'churn', verdict_title: 'Churn', event_type: 'churn', side: 'C', net_cr: 0, chips: ['Churn warning'] }),
];
const HIST = [
  { symbol: 'M&M', industry: 'Autos', pattern: 'repeat_buy', pattern_label: 'Repeated buying', buy_sessions: 2, sell_sessions: 0, churn_sessions: 0, net_cr: 40, prop_cr: 0, avg_deal_price: 3000, close: 3100, vs_deal_pct: 3.3, cells: [null, 'B', null, 'B', null] },
  { symbol: 'KSCL', industry: 'Seeds', pattern: 'churn_only', pattern_label: 'Prop desk / churn only', buy_sessions: 0, sell_sessions: 0, churn_sessions: 1, net_cr: 0, prop_cr: 12, avg_deal_price: null, close: 900, vs_deal_pct: null, cells: [null, null, null, null, 'C'] },
];
const PATTERNS = [
  { key: 'repeat_buy', label: 'Repeated buying', note: 'Buying in 2+ sessions, no selling.' },
  { key: 'churn_only', label: 'Prop desk / churn only', note: 'Same desks in and out.' },
];
const HOUSES = [
  { house: 'SBI MUTUAL FUND', name: 'Sbi Mutual Fund', buyer_class: 'DII', bought_cr: 180, symbols: ['BAJAJ-AUTO', 'SEAMECLTD'], grade: 'good', record_n: 7, record_avg_pct: 2.1, record_beat_pct: 57, spread: [{ industry: 'Automobiles', value_cr: 150, share_pct: 83, symbols: ['BAJAJ-AUTO'] }, { industry: 'Shipping', value_cr: 30, share_pct: 17, symbols: ['SEAMECLTD'] }] },
];

function mockFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
      const p = decodeURIComponent(url.pathname);
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });
      if (p === '/api/v2/deals/tab/today')
        return json(env(TODAY, { deal_session: '2026-08-13', skipped: { transfer: 0, churn: 1, small: 15 }, above50_pct: 56, summary: { confirms: 1, placements: 1, supply: 0, avoid: 0, noise: 1 } }, ['Price data gap: none.']));
      if (p === '/api/v2/deals/tab/watch') {
        const st = url.searchParams.get('status');
        const rows = st === 'lost' ? [] : [deal({ sessions_since: 4, verdict: 'confirm', verdict_title: 'Confirmed: held the deal price 3 sessions', status: 'holding' })];
        return json(env(rows, { filter_counts: { all: 1, best: 1, holding: 1, lost: 0, reclaimed: 0 } }));
      }
      if (p === '/api/v2/deals/tab/history') {
        const pat = url.searchParams.get('pattern');
        const rows = pat && pat !== 'all' ? HIST.filter((h) => h.pattern === pat) : HIST;
        return json(env(rows, { sessions: ['2026-08-07', '2026-08-10', '2026-08-11', '2026-08-12', '2026-08-13'], pattern_counts: { repeat_buy: 1, churn_only: 1 }, patterns: PATTERNS, total: 2 }));
      }
      if (p === '/api/v2/deals/tab/houses')
        return json(env(HOUSES, { class_evidence: [{ buyer_class: 'FII', n: 947, vs_market_pct: 1.2, beat_pct: 53 }], fund_groups: [{ industry: 'Automobiles', houses: 3, fii_cr: 10, dii_cr: 150, symbols: ['BAJAJ-AUTO'] }], graded_houses: 1, finished_bets: 7, first_deal: '2026-04-29' }));
      if (p === '/api/v2/deals/tab/groups')
        return json(env([{ industry: 'Shipping', sector: 'Services', buying_names: 3, selling_names: 0, flow_cr: 60, symbols: ['SEAMECLTD', 'GESHIP', 'SCI'], three_plus_buyers: true }]));
      if (p === '/api/v2/deals/tab/stock/SEAMECLTD')
        return json(
          env([
            {
              symbol: 'SEAMECLTD',
              deal: deal({ earlier: [] }),
              candles: [
                { date: '2026-08-12', open: 1500, high: 1520, low: 1490, close: 1510 },
                { date: '2026-08-13', open: 1510, high: 1550, low: 1505, close: 1540 },
              ],
              markers: [{ date: '2026-08-13', side: 'B', event_type: 'fresh', price: 1529.25, net_cr: 30.7, gross_cr: 30.7 }],
              price_lines: [{ date: '2026-08-13', side: 'B', event_type: 'fresh', price: 1529.25, net_cr: 30.7, gross_cr: 30.7 }],
            },
          ]),
        );
      if (p === '/api/v2/deals/tab/house/SBI MUTUAL FUND')
        return json(env([{ symbol: 'BAJAJ-AUTO', deal_date: '2026-08-13', bought_cr: 150, deal_price: 11600, buyer_class: 'DII', entry_date: null, since_entry_pct: null, market_pct: null, vs_market_pct: null, verdict: 'place', verdict_title: 'Placement on a strong chart', status: 'day 0' }], { house: HOUSES[0], advice: 'Alert on: buys a strong chart, and day 3 holding or lost.' }));
      return new Response('', { status: 404 });
    }),
  );
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  return router;
}

beforeEach(() => {
  copied.length = 0;
  mockFetch();
});
afterEach(() => vi.unstubAllGlobals());

describe('Deals tab', () => {
  it('Today: verdicts, noise hidden behind a toggle, TradingView copy of the rows on screen', async () => {
    renderAt('/deals');
    expect(await screen.findByText('SEAMECLTD', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Deals' })).toBeInTheDocument();
    expect(screen.getByText('Confirms setup: check day 3')).toBeInTheDocument();
    expect(screen.queryByText('KSCL')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Copy 2 to TradingView/ }));
    await waitFor(() => expect(copied[0]).toMatch(/^###Deals Today 2026-08-13,/));
    expect(copied[0]).toContain('NSE:BAJAJ_AUTO');
    expect(copied[0]).not.toContain('KSCL');
    fireEvent.click(screen.getByRole('button', { name: /Show 1 noise rows/ }));
    expect(await screen.findByText('KSCL')).toBeInTheDocument();
    expect(screen.getByText('Price data gap: none.')).toBeInTheDocument();
  });

  it('opens the stock drawer with deal candles and the next action', async () => {
    const router = renderAt('/deals?sym=SEAMECLTD');
    const dialog = await screen.findByRole('dialog', {}, { timeout: 5000 });
    expect(await within(dialog).findByText(/What to do:/)).toBeInTheDocument();
    expect(within(dialog).getByText(/confirms if it closes above/)).toBeInTheDocument();
    expect(dialog.querySelector('[data-deal="B"]')).not.toBeNull();
    fireEvent.click(within(dialog).getByRole('button', { name: '360 One Pipe' }));
    await waitFor(() => expect(router.state.location.search).toContain('house=360'));
  });

  it('Deal watch filters by status', async () => {
    renderAt('/deals?view=watch');
    expect(await screen.findByText('Confirmed: held the deal price 3 sessions', {}, { timeout: 5000 })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: /^Lost/ }));
    expect(await screen.findByText('No stocks match this filter')).toBeInTheDocument();
  });

  it('History: session cells, pattern filter with its evidence note, copy keeps the filter in the title', async () => {
    renderAt('/deals?view=repeated');
    expect(await screen.findByText('Deal history · last 10 deal sessions', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(await screen.findByText('M&M')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Repeated buying 1/ }));
    expect(await screen.findByText('Buying in 2+ sessions, no selling.')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('KSCL')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Copy 1 to TradingView/ }));
    await waitFor(() => expect(copied[0]).toBe('###Deal history 10 sessions Repeated buying,NSE:M_M'));
  });

  it('Houses: fund spread, follow, copy every list, house drawer', async () => {
    renderAt('/deals?view=houses');
    expect(await screen.findByText('Sbi Mutual Fund', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText('Automobiles 83%')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Follow' }));
    expect(screen.getByRole('button', { name: 'Following' })).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem('mp.deals.followedHouses') ?? '[]')).toEqual(['SBI MUTUAL FUND']);
    fireEvent.click(screen.getByRole('button', { name: /Copy every list/ }));
    await waitFor(() => expect(copied[0]).toBe('###Where FII DII money went by group,NSE:BAJAJ_AUTO\n###Houses buying in the window,NSE:BAJAJ_AUTO,NSE:SEAMECLTD'));
    fireEvent.click(screen.getByRole('button', { name: 'Sbi Mutual Fund' }));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('Alert on: buys a strong chart, and day 3 holding or lost.')).toBeInTheDocument();
    expect(within(dialog).getByText('entry next open')).toBeInTheDocument();
  });

  it('By group: 3+ buyers chip and copy', async () => {
    renderAt('/deals?view=groups');
    expect(await screen.findByText('3+ buyers', {}, { timeout: 5000 })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Copy 3 to TradingView/ }));
    await waitFor(() => expect(copied[0]).toBe('###Deals by group 10 sessions,NSE:SEAMECLTD,NSE:GESHIP,NSE:SCI'));
  });
});
