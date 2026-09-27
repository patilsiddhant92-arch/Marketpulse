/**
 * Desk + Stock 360 smoke against fixture envelopes: queue rows with NULLs as
 * "—", unavailable meta handled, diff, watchlist sync to /api/v2/watchlist.
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
const env = (rows: unknown[], meta: Record<string, unknown> = {}) => ({
  as_of: '2026-09-25',
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', offset: 0, limit: 500, sources: [], notes: [], metric_keys: [], context: {}, ...meta },
});
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const queueRow = (o: Record<string, unknown>) => ({
  queue: 'darvas_squeeze',
  timeframe: 'D',
  risk_flag: false,
  symbol: 'AAA',
  security_name: 'Aaa Ltd',
  industry: 'Industrial Minerals',
  close: 100,
  change_1d_pct: 1.5,
  trigger_price: 102,
  stop_price: 97,
  distance_to_trigger_pct: 2,
  risk_pct: 5.15,
  rvol: 1.2,
  delivery_vs_20d: 1.1,
  rs_percentile: 85,
  rs_delta_5: 3,
  excess_vs_midsml400_63d: 4,
  setup_age_sessions: null,
  is_new: true,
  results_within_10: false,
  deal_net_10s_cr: null,
  squeeze_pct: 1.4,
  ...o,
});

const header = {
  symbol: 'AAA',
  security_name: 'Aaa Ltd',
  close: 100,
  change_1d_pct: 1.5,
  trade_date: '2026-09-25',
  stale_vs_as_of: false,
  prev_close: 98.5,
  taxonomy: [{ level: 'industry', name: 'Industrial Minerals', id: 'industry:Industrial Minerals' }],
  adjustments: [],
  prices_adjusted: false,
  delivery_spark_60: [50, 55, null, 60],
  setups: { darvas_squeeze: queueRow({}), darvas_10ema: null, vcp: null },
  rs_percentile: 85,
};

function setup(opts: { serverWatch?: string[] } = {}) {
  const puts: unknown[] = [];
  let serverWatch = opts.serverWatch ?? [];
  const fetchFn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
    const p = url.pathname;
    if (p === '/api/v2/watchlist') {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { symbols: string[] };
        puts.push(body);
        serverWatch = body.symbols;
      }
      return json(env(serverWatch.map((symbol, i) => ({ symbol, position: i }))));
    }
    if (p === '/api/v2/market/regime') return json(env([], { status: 'unavailable', reason: 'regime_daily not built yet' }));
    if (p === '/api/v2/market/health')
      return json(env([{ trade_date: '2026-09-25', pct_above_50ema: 39.7, net_new_highs: -18 }, { trade_date: '2026-09-24', pct_above_50ema: 38.5, net_new_highs: -7 }]));
    if (p === '/api/v2/desk/queues')
      return json(env([{ name: 'darvas_squeeze', label: 'Darvas Squeeze', description: 'd', timeframes: ['D', 'W', 'M'], counts: { D: 2 }, count: 2 }]));
    if (p === '/api/v2/desk/queue/darvas_squeeze')
      return json(env([queueRow({}), queueRow({ symbol: 'BBB', rs_percentile: null, trigger_price: null, stop_price: null, distance_to_trigger_pct: null, risk_pct: null, is_new: false })], { status: 'partial', reason: 'setup_daily not built yet' }));
    if (p === '/api/v2/desk/diff')
      return json(env([{ queue: 'darvas_squeeze', timeframe: 'D', change: 'new', symbol: 'AAA', rs_percentile: 85 }, { queue: 'darvas_squeeze', timeframe: 'D', change: 'dropped', symbol: 'ZZZ', rs_percentile: 40 }], { context: { previous_session: '2026-09-24' } }));
    if (p === '/api/v2/groups/board') return json(env([{ id: 'industry:X', level: 'industry', group_name: 'Big Group', rank: 3, stocks: 12, rank_delta_5: 2 }]));
    if (p.startsWith('/api/v2/evidence/')) return json(env([], { status: 'unavailable', reason: 'setup_outcomes not built yet' }));
    if (p === '/api/v2/desk/watchlist')
      return json(env((url.searchParams.get('symbols') ?? '').split(',').filter(Boolean).map((symbol) => ({ symbol, has_data: true, queues: ['darvas_squeeze'], change_1d_pct: 1 }))));
    if (p === '/api/v2/stock/AAA') return json(env([header]));
    if (p === '/api/v2/stock/AAA/bars') return json(env([{ trade_date: '2026-09-25', open: 99, high: 101, low: 98, close: 100, partial: false }]));
    if (p.startsWith('/api/v2/stock/AAA/')) return json(env([]));
    if (p === '/api/v2/notes/AAA') return json(env([]));
    return new Response('', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchFn);
  return { fetchFn, puts };
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

describe('Desk', () => {
  it('renders queues with NULL as "—", breadth fallback, diff and groups', async () => {
    setup();
    renderApp('/desk');
    const table = await screen.findByRole('grid', { name: 'Darvas Squeeze queue' });
    expect(await within(table).findByText('AAA')).toBeInTheDocument();
    const bbbRow = within(table).getByText('BBB').closest('tr') as HTMLElement;
    expect(within(bbbRow).getAllByText('—').length).toBeGreaterThanOrEqual(4); // rank, trigger, stop, dist, risk stay NULL
    expect(screen.getByText('Verdict not available')).toBeInTheDocument();
    expect(screen.getAllByText(/regime_daily not built yet/).length).toBeGreaterThan(0);
    expect(await screen.findByText('39.7%')).toBeInTheDocument();
    expect(screen.getByText(/not built yet — outcomes per setup/)).toBeInTheDocument();
    expect(screen.getByText('computed live · setup age n/a')).toBeInTheDocument();
    const diff = screen.getByRole('region', { name: 'New vs yesterday' });
    expect(await within(diff).findByRole('button', { name: 'AAA' })).toBeInTheDocument();
    expect(within(diff).getByRole('button', { name: 'ZZZ' })).toBeInTheDocument();
    expect(await screen.findByText('Big Group')).toBeInTheDocument();
  });

  it('clicking a row opens Stock 360 in the sidecar; W watches via the server', async () => {
    const { puts } = setup();
    const router = renderApp('/desk');
    const table = await screen.findByRole('grid', { name: 'Darvas Squeeze queue' });
    fireEvent.click(await within(table).findByText('AAA'));
    await waitFor(() => expect(router.state.location.search).toContain('sym=AAA'));
    const side = await screen.findByTestId('stock360-sidecar');
    expect(await within(side).findByText('Aaa Ltd')).toBeInTheDocument();
    expect(within(side).getByText('in 1 of 3 Desk queues')).toBeInTheDocument();
    expect(within(side).getByText('unadjusted prices')).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText(/0 · saved/)).toBeInTheDocument());
    fireEvent.keyDown(window, { key: 'w' });
    await waitFor(() => expect(puts).toEqual([{ symbols: ['AAA'] }]));
    const watch = screen.getByRole('region', { name: 'Watchlist' });
    expect(await within(watch).findByText('Squeeze')).toBeInTheDocument();
  });

  it('adopts the server watchlist and migrates a local-only list once', async () => {
    window.localStorage.setItem('mp.watchlist.v1', JSON.stringify(['LOCAL1']));
    const { puts } = setup({ serverWatch: [] });
    renderApp('/desk');
    await waitFor(() => expect(puts).toEqual([{ symbols: ['LOCAL1'] }]));
  });
});

describe('Stock 360 page', () => {
  it('renders header, setups and notes for /stock/:sym', async () => {
    setup();
    renderApp('/stock/AAA');
    expect(await screen.findByText('Aaa Ltd')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'AAA' })).toBeInTheDocument();
    expect(await screen.findByRole('img', { name: 'AAA daily chart' })).toBeInTheDocument();
    expect(screen.getByLabelText('Notes for AAA')).toBeInTheDocument();
    expect(screen.getByText('No disclosed bulk or block deals up to this date.')).toBeInTheDocument();
  });
});
