/**
 * Desk › Today and Groups › Today against fixture envelopes: market strip, movers with the
 * quality chip, row → Stock 360 sidecar, groups "why", group name → drill.
 */
import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { routes } from '../routes';

vi.mock('../ui/Chart', () => ({ Chart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }));
vi.mock('../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));

const FRESH = { status: 'fresh', latest_session: '2026-09-25', expected_session: '2026-09-25', sessions_behind: 0, history_mode: false };
const env = (rows: unknown[], context: Record<string, unknown> = {}) => ({
  as_of: '2026-09-25',
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', offset: 0, limit: 500, sources: ['indicators_daily'], notes: [], metric_keys: [], context },
});
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });

const market = {
  trade_date: '2026-09-25',
  indices: [
    { name: 'Nifty 50', label: 'Nifty 50', close: 23140.5, return_1d_pct: 0.34, return_5d_pct: -0.88, return_20d_pct: -3.94 },
    { name: 'NIFTY MIDSML 400', label: 'MidSml 400', close: 20904.95, return_1d_pct: -0.09, return_5d_pct: -1.57, return_20d_pct: -3.51 },
  ],
  india_vix: 12.16,
  vix_change_1d_pct: -4.18,
  advancers: 1495,
  decliners: 1379,
  advance_pct: 51.1,
  new_52w_highs: 79,
  new_52w_lows: 100,
  new_52w_highs_5d_avg: 101,
  new_52w_lows_5d_avg: 58.4,
  turnover_cr: 99447,
  turnover_20d_avg_cr: 115049,
  turnover_vs_20d: 0.86,
  delivery_pct: 40.3,
  delivery_pct_20d_avg: 43.1,
  deliv_pct_x: 0.93,
};
const stock = (o: Record<string, unknown>) => ({
  industry: 'Pharma',
  queues: [],
  news_today: [],
  traits: [],
  quality: 'Normal',
  quality_id: 'normal',
  quality_tone: 'neutral',
  ...o,
});
const movers = [
  stock({ side: 'gainer', rank: 1, symbol: 'P1', change_1d_pct: 10, rvol: 2, deliv_pct_x: 1.5, quality: 'Real', quality_id: 'real', quality_tone: 'good', traits: ['delivery_spike'], queues: ['vcp'] }),
  stock({ side: 'loser', rank: 1, symbol: 'P4', change_1d_pct: -1, rvol: 1.2 }),
];
const groups = [
  {
    id: 'sector:Healthcare',
    level: 'sector',
    group_name: 'Healthcare',
    stocks: 4,
    stocks_with_return: 4,
    return_1d: 3.25,
    pct_up: 75,
    breadth_label: 'one-stock',
    persistence: 'Trend',
    persistence_id: 'trend_up',
    top_contributors: [{ symbol: 'P1', change_1d_pct: 10, contribution: 2.5, share_of_move_pct: 77, weight_pct: 25 }],
    top_detractors: [],
    news_types: {},
    symbols: ['P1', 'P2'],
    why: 'Healthcare +3.2% today, driven by one stock (P1 +10.0% = 77% of the move).',
  },
];

function setup() {
  const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
    const p = url.pathname;
    if (p === '/api/v2/today/market') return json(env([market]));
    if (p === '/api/v2/today/movers')
      return json(env(movers, { quality_rules: [{ id: 'real', label: 'Real', tone: 'good', why: 'Heavy volume and delivery', when: [{ field: 'rvol', op: 'gte', value: 1.5 }] }], up: 1, down: 1, universe: 2 }));
    if (p === '/api/v2/today/breakouts') return json(env([stock({ symbol: 'P2', kinds: ['setup_trigger'], setup_trigger: 101, setup_queue: 'darvas_squeeze' })], { counts: { setup_trigger: 1 } }));
    if (p === '/api/v2/today/groups') return json(env(groups));
    if (p === '/api/v2/watchlist') return json(env([]));
    return new Response('', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchFn);
  return fetchFn;
}

function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App router={router} queryClient={client} />);
  return router;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe('Desk › Today', () => {
  it('shows the market strip, movers with quality, breakouts and groups why', async () => {
    setup();
    renderApp('/desk?view=today');
    const strip = await screen.findByTestId('today-market');
    expect(within(strip).getByText('MidSml 400')).toBeInTheDocument();
    expect(within(strip).getByText('+0.34%')).toBeInTheDocument();
    const grid = await screen.findByRole('grid', { name: 'Top gainers today' });
    expect(await within(grid).findByText('P1')).toBeInTheDocument();
    expect(within(grid).getByText('Real')).toBeInTheDocument();
    expect(within(grid).getByText('VCP')).toBeInTheDocument();
    expect(within(grid).getByText('Deliv spike')).toBeInTheDocument();
    const b = await screen.findByRole('grid', { name: 'Breakouts today' });
    expect(await within(b).findByText('P2')).toBeInTheDocument();
    expect(within(b).getByText('Setup trigger')).toBeInTheDocument();
    const g = screen.getByRole('region', { name: 'Groups today' });
    expect(await within(g).findByText(/driven by one stock \(P1 \+10\.0% = 77% of the move\)/)).toBeInTheDocument();
  });

  it('row click opens Stock 360; Losers toggle; group name drills into Groups', async () => {
    setup();
    const router = renderApp('/desk?view=today');
    const grid = await screen.findByRole('grid', { name: 'Top gainers today' });
    fireEvent.click(await within(grid).findByText('P1'));
    await waitFor(() => expect(router.state.location.search).toContain('sym=P1'));
    fireEvent.click(screen.getByRole('radio', { name: /Losers/ }));
    const losers = await screen.findByRole('grid', { name: 'Top losers today' });
    expect(await within(losers).findByText('P4')).toBeInTheDocument();
    const g = screen.getByRole('region', { name: 'Groups today' });
    fireEvent.click(await within(g).findByRole('button', { name: 'Healthcare' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/groups'));
    expect(router.state.location.search).toContain('group=sector%3AHealthcare');
  });
});

describe('Groups › Today', () => {
  it('lists groups with the why and drills on the name', async () => {
    setup();
    const router = renderApp('/groups?view=today&level=sector');
    const grid = await screen.findByRole('grid', { name: 'Groups today' });
    expect(await within(grid).findByText('Healthcare')).toBeInTheDocument();
    expect(await screen.findByTestId('group-why')).toHaveTextContent('77% of the move');
    fireEvent.click(within(grid).getByRole('button', { name: 'Healthcare' }));
    await waitFor(() => expect(router.state.location.search).toContain('group=sector%3AHealthcare'));
  });
});
