/**
 * Pulse tab smoke against real envelopes captured from /api/v2/pulse/* at as_of 2026-08-13 (fixtures.json):
 * hero + commentary + What to do, participation grid, expansion log, internals, money, groups, movers, analogs;
 * lookback / units / level / mover toggles re-key the queries; unavailable meta shows the honest empty state.
 */
import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../../App';
import { legacyDeskRedirect } from '../DeskRoute';
import { routes } from '../index';
import fixtures from './fixtures.json';

vi.mock('../../ui/Chart', () => ({ Chart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }));
vi.mock('../../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));

type Fx = Record<string, { rows: unknown[]; meta: Record<string, unknown> } & Record<string, unknown>>;
const FX = fixtures as unknown as Fx;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function setup(overrides: Record<string, unknown> = {}) {
  const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    const p = url.pathname;
    if (p in overrides) return json(overrides[p]);
    if (p === '/api/v2/pulse/groups') return json(url.searchParams.get('level') === 'sectoral' ? FX.sectoral : FX.groups);
    const key = p.replace('/api/v2/pulse/', '');
    if (p.startsWith('/api/v2/pulse/') && key in FX) return json(FX[key]);
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

const summary = (FX.summary.rows[0] ?? {}) as { mood: number; mood_label: string; action: string; commentary: { text: string }[]; history_line: string };

describe('Pulse tab', () => {
  it('renders the mood hero, commentary and What to do from the summary', async () => {
    setup();
    renderApp('/desk');
    expect(await screen.findByTestId('mood-label')).toHaveTextContent(summary.mood_label);
    expect(screen.getByTestId('mood-score')).toHaveTextContent(`${Math.round(summary.mood)} / 100`);
    expect(screen.getByText('and cooling fast')).toBeInTheDocument();
    const todo = screen.getByTestId('what-to-do');
    expect(todo).toHaveTextContent(summary.action);
    expect(todo).toHaveTextContent(summary.history_line);
    for (const line of summary.commentary) expect(screen.getByText(line.text, { exact: false })).toBeInTheDocument();
    expect(screen.getByTestId('pulse-asof')).toHaveTextContent('As of 13 Aug 2026 close');
  });

  it('shows the participation grid with every row and today, plus the expansion log and analogs', async () => {
    setup();
    renderApp('/desk');
    const grid = await screen.findByRole('table', { name: 'Participation grid' });
    for (const l of ['10 EMA', '20 EMA', '50 EMA', '100 EMA', '200 EMA']) expect(within(grid).getByText(l)).toBeInTheDocument();
    expect(within(grid).getByText('Today')).toBeInTheDocument();
    // 5D lookback -> 5 session columns
    expect(within(grid).getAllByRole('columnheader')).toHaveLength(1 + 5 + 3);
    const log = await screen.findByRole('table', { name: 'Expansion log' });
    expect(within(log).getAllByRole('row').length).toBeGreaterThan(1);
    expect(screen.getByLabelText('Expansion summary')).toHaveTextContent('20 EMA: expansions 28×');
    const ana = await screen.findByRole('table', { name: 'Days like today' });
    expect(within(ana).getAllByRole('row')).toHaveLength(1 + 1 + 8);
  });

  it('renders internals, money flow, groups and movers', async () => {
    setup();
    renderApp('/desk');
    const internals = await screen.findByRole('region', { name: 'Market internals' });
    for (const l of ['Advancers %', 'Up-volume %', 'Net new highs', 'In Stage 2', 'Breakouts holding', 'India VIX'])
      expect(within(internals).getByText(l)).toBeInTheDocument();
    expect(await screen.findByRole('img', { name: 'Sector turnover treemap' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Sector rotation' })).toBeInTheDocument();
    expect(screen.getByText(/pass the ₹1,000 Cr filter/)).toBeInTheDocument();
    const movers = FX.movers.rows as { symbol: string }[];
    expect(await screen.findByText(movers[0].symbol)).toBeInTheDocument();
  });

  it('lookback, units, group level and mover tabs re-key the queries', async () => {
    const fetchFn = setup();
    const router = renderApp('/desk');
    await screen.findByRole('table', { name: 'Participation grid' });
    fireEvent.click(within(screen.getByRole('radiogroup', { name: 'Compare today with' })).getByRole('radio', { name: '1M' }));
    await waitFor(() => expect(fetchFn.mock.calls.some(([u]) => String(u).includes('/pulse/summary?lookback=20'))).toBe(true));
    await waitFor(() => expect(router.state.location.search).toContain('lb=20'));
    fireEvent.click(screen.getByRole('radio', { name: '# stocks' }));
    await waitFor(() => expect(router.state.location.search).toContain('units=count'));
    fireEvent.click(screen.getByRole('radio', { name: 'Sectoral index' }));
    await waitFor(() => expect(fetchFn.mock.calls.some(([u]) => String(u).includes('/pulse/groups?level=sectoral'))).toBe(true));
    fireEvent.click(screen.getByRole('radio', { name: 'Losers' }));
    await waitFor(() => expect(fetchFn.mock.calls.some(([u]) => String(u).includes('/pulse/movers?kind=losers'))).toBe(true));
  });

  it('passes as_of from the URL and shows honest empty states when data is unavailable', async () => {
    const unavailable = { ...FX.summary, rows: [], total: 0, returned: 0, meta: { ...FX.summary.meta, status: 'unavailable', reason: 'breadth_daily missing' } };
    const fetchFn = setup({ '/api/v2/pulse/summary': unavailable });
    renderApp('/desk?as_of=2026-08-13');
    expect(await screen.findByText('Mood is not available for this session')).toBeInTheDocument();
    expect(screen.getByText('breadth_daily missing')).toBeInTheDocument();
    await waitFor(() => expect(fetchFn.mock.calls.some(([u]) => String(u).includes('as_of=2026-08-13'))).toBe(true));
  });

  it('sends old legacy-view links to their new homes', async () => {
    setup();
    const router = renderApp('/desk?view=setups&queue=vcp&as_of=2026-08-13');
    await waitFor(() => expect(router.state.location.pathname).toBe('/setups'));
    expect(router.state.location.search).toContain('sq=vcp');
    expect(router.state.location.search).toContain('as_of=2026-08-13');
    expect(router.state.location.search).not.toContain('view=');
  });

  it('drops the old ?view=today and stays on Pulse', async () => {
    setup();
    const router = renderApp('/desk?view=today');
    await screen.findByTestId('pulse-view');
    await waitFor(() => expect(router.state.location.search).not.toContain('view=today'));
    expect(router.state.location.pathname).toBe('/desk');
  });
});

describe('legacyDeskRedirect', () => {
  it('maps the legacy views and leaves other links alone', () => {
    expect(legacyDeskRedirect('?view=setups&queue=darvas_squeeze&tf=W')).toEqual({ pathname: '/setups', search: '?sq=darvas_squeeze' });
    expect(legacyDeskRedirect('?view=setups')).toEqual({ pathname: '/setups', search: '' });
    expect(legacyDeskRedirect('?view=today&as_of=2026-08-13')).toEqual({ pathname: '/desk', search: '?as_of=2026-08-13' });
    expect(legacyDeskRedirect('?as_of=2026-08-13')).toBeNull();
    expect(legacyDeskRedirect('')).toBeNull();
  });
});
