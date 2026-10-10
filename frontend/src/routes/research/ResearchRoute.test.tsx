/**
 * Research tab against a fixture API (real /api/v2/research envelopes captured
 * on the local archive, trimmed): the intentional "being computed" state for
 * unavailable envelopes, then each study view, with the caveat on every view
 * and n printed beside every statistic.
 */
import { QueryClient } from '@tanstack/react-query';
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../../App';
import { routes } from '..';
import { fixtureFor } from './fixtures';

vi.mock('../../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));
// lightweight-charts needs a canvas.
vi.mock('./CaseChart', () => ({ CaseChart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }));

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const RESEARCH = /^\/api\/v2\/(research\/.*|evidence\/.*|stock\/[^/]+\/analogs)$/;

function unavailable(reason: string, sources: string[]) {
  return {
    as_of: '2026-09-25',
    freshness: null,
    total: 0,
    returned: 0,
    rows: [],
    meta: { status: 'unavailable', reason, sources, offset: 0, limit: 500, context: {} },
  };
}

/** Serve research endpoints from the shared fixtures (as the real API would). */
function serveFixtures(url: URL): Response | undefined {
  if (!RESEARCH.test(url.pathname)) return undefined;
  const path = url.pathname.replace('/api/v2/', '');
  const q = Object.fromEntries(url.searchParams.entries());
  const query: Record<string, unknown> = { ...q, ...(q.min_mcap_cr ? { min_mcap_cr: Number(q.min_mcap_cr) } : {}) };
  let endpoint = path;
  let params: Record<string, string> | undefined;
  let m: RegExpMatchArray | null;
  if ((m = path.match(/^research\/case-study\/([^/]+)\/traits$/))) {
    endpoint = 'research/case-study/{sym}/traits';
    params = { sym: decodeURIComponent(m[1]) };
  } else if ((m = path.match(/^research\/case-study\/(.+)$/))) {
    endpoint = 'research/case-study/{sym}';
    params = { sym: decodeURIComponent(m[1]) };
  } else if ((m = path.match(/^research\/big-moves\/(.+)$/))) {
    endpoint = 'research/big-moves/{event_id}';
    params = { event_id: decodeURIComponent(m[1]) };
  } else if ((m = path.match(/^evidence\/(.+)$/))) {
    endpoint = 'evidence/{setup}';
    params = { setup: m[1] };
  } else if ((m = path.match(/^stock\/([^/]+)\/analogs$/))) {
    endpoint = 'stock/{sym}/analogs';
    params = { sym: m[1] };
  }
  return json(fixtureFor({ endpoint, params, query, asOf: q.as_of ?? null }));
}

function mockFetch(handler: (url: URL) => Response | undefined) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
    return handler(url) ?? new Response('', { status: 404 });
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App router={router} queryClient={client} />);
  return router;
}

// The tab is lazy-loaded; warm the chunk so the first test is not timing the import.
configure({ asyncUtilTimeout: 5000 });
beforeAll(async () => {
  await import('../ResearchRoute');
});
beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Research tab', () => {
  it('shows an intentional "being computed" state when a study is unavailable', async () => {
    mockFetch((url) =>
      RESEARCH.test(url.pathname) ? json(unavailable('not enough history for the regime study', ['indicators_daily'])) : undefined,
    );
    renderApp('/research');
    expect(await screen.findByText('Evidence is being computed — available after the next rebuild')).toBeInTheDocument();
    expect(screen.getByText(/not enough history for the regime study/)).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Research studies' });
    expect(within(nav).getByRole('button', { name: 'Days like today' })).toHaveAttribute('aria-current', 'page');
    // Pre-move watch is cut; group studies moved to Sector Intel.
    expect(within(nav).queryByRole('button', { name: 'Pre-move watch' })).toBeNull();
    expect(within(nav).queryByRole('button', { name: 'Group studies' })).toBeNull();
    expect(within(nav).queryByRole('button', { name: 'Market analogs' })).toBeNull();
  });

  it('days like today: regime quadrant, ribbon, record with n, analogs vs all days, time travel', async () => {
    const fetchFn = mockFetch(serveFixtures);
    const router = renderApp('/research');
    expect((await screen.findAllByText("Stock-picker's market")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Retrospective research, not advice/).length).toBeGreaterThan(0);
    expect(screen.getByRole('img', { name: 'Regime quadrant ribbon' })).toBeInTheDocument();
    const record = screen.getByRole('table', { name: 'Quadrant record' });
    expect(within(record).getAllByRole('row')).toHaveLength(6);
    expect(within(record).getAllByText(/n=/).length).toBeGreaterThan(3);
    expect(screen.getByText(/What to do:/)).toBeInTheDocument();
    const analogs = await screen.findByRole('table', { name: 'Days like today' });
    expect(within(analogs).getAllByRole('row')).toHaveLength(11);
    const h20 = document.querySelector('[data-horizon="20"]') as HTMLElement;
    expect(h20).toHaveTextContent('n=10');
    expect(fetchFn).toHaveBeenCalledWith(expect.stringMatching(/^\/api\/v2\/research\/regime/), expect.anything());
    fireEvent.click(within(analogs).getAllByRole('button', { name: 'Go' })[0]);
    await waitFor(() => expect(router.state.location.search).toMatch(/as_of=\d{4}-\d{2}-\d{2}/));
  });

  it('before the big moves: two families, today\'s lifts scored, profile, out-of-sample and regime multiplier', async () => {
    const fetchFn = mockFetch(serveFixtures);
    renderApp('/research?rview=before');
    const grid = await screen.findByRole('grid', { name: "Today's early lifts" });
    expect(within(grid).getAllByRole('row').length).toBeGreaterThan(5);
    expect(screen.getByRole('table', { name: 'Runner vs fizzle trait profile' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Out-of-sample runner rate by score' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Runner rate by regime quadrant' })).toBeInTheDocument();
    expect(screen.getAllByText(/not advice/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'Turnaround lifts' }));
    await waitFor(() =>
      expect(fetchFn.mock.calls.some((c) => String(c[0]).startsWith('/api/v2/research/before-moves') && String(c[0]).includes('family=turnaround'))).toBe(true),
    );
    expect(await screen.findByText(/330 past turnaround lifts had an outcome/)).toBeInTheDocument();
  });

  it('case study: big-mover list, symbol search, first-fire table, ladder and precision context', async () => {
    const fetchFn = mockFetch(serveFixtures);
    renderApp('/research?rview=case');
    const grid = await screen.findByRole('grid', { name: 'Big movers' });
    expect(within(grid).getAllByRole('row').length).toBeGreaterThan(5);
    // The top mover is studied by default.
    await waitFor(() => expect(fetchFn.mock.calls.some((c) => String(c[0]).startsWith('/api/v2/research/case-study/STLTECH'))).toBe(true));
    fireEvent.change(screen.getByLabelText('Study a stock'), { target: { value: 'mtartech' } });
    fireEvent.click(screen.getByRole('button', { name: /Study/ }));
    await waitFor(() => expect(fetchFn.mock.calls.some((c) => String(c[0]).startsWith('/api/v2/research/case-study/MTARTECH'))).toBe(true));
    expect(await screen.findByRole('img', { name: 'MTARTECH case study chart' })).toBeInTheDocument();
    const first = screen.getByRole('table', { name: 'First fire per preset' });
    const dt = within(first).getAllByRole('row').find((r) => r.textContent?.includes('Delivery thrust'))!;
    expect(dt).toHaveTextContent('12 Sep 2025');
    expect(dt).toHaveTextContent('+20%');
    expect(screen.getByText(/6 trades, compounded \+246%/)).toBeInTheDocument();
    expect(within(screen.getByRole('table', { name: '20 EMA ladder trades' })).getAllByRole('row')).toHaveLength(7);
    const prec = screen.getByRole('table', { name: 'Preset precision' });
    expect(within(prec).getByText('False alarms')).toBeInTheDocument();
    expect(screen.getAllByText(/not advice/).length).toBeGreaterThan(0);
  });

  it('setup scorecard: catch rate with n beside precision and false alarms', async () => {
    mockFetch(serveFixtures);
    renderApp('/research?rview=scorecard');
    const table = await screen.findByRole('table', { name: 'Setup scorecard' });
    expect(within(table).getAllByRole('row')).toHaveLength(12);
    const vcp = within(table).getAllByRole('row').find((r) => r.textContent?.includes('VCP flag'))!;
    expect(vcp).toHaveTextContent('93%');
    expect(vcp).toHaveTextContent('fires=');
    expect(screen.getByText(/226 stocks doubled in the window/)).toBeInTheDocument();
  });

  it('index study: drawdown table and leadership', async () => {
    mockFetch(serveFixtures);
    renderApp('/research?rview=index');
    const table = await screen.findByRole('table', { name: 'Drawdown table' });
    expect(within(table).getAllByRole('row')).toHaveLength(3);
    expect(screen.getByText(/data gap #3/)).toBeInTheDocument();
  });

  it('setup evidence: queue × environment with n on every cell and insufficient sample below 30', async () => {
    mockFetch(serveFixtures);
    renderApp('/research?rview=evidence');
    const table = await screen.findByRole('table', { name: 'Setup evidence by environment' });
    await waitFor(() => expect(within(table).getAllByText(/n=/).length).toBeGreaterThan(10));
    const vcp = within(table)
      .getAllByRole('row')
      .find((r) => r.textContent?.startsWith('VCP'))!;
    const danger = vcp.querySelector('[data-bucket="Danger"]') as HTMLElement;
    expect(danger).toHaveTextContent('insufficient sample');
    expect(danger).toHaveTextContent('n=4');
    const fav = vcp.querySelector('[data-bucket="Favourable"]') as HTMLElement;
    expect(fav).toHaveTextContent('44.6%');
    expect(fav).toHaveTextContent('n=74');
    fireEvent.click(screen.getByRole('button', { name: 'Avg R' }));
    await waitFor(() => expect(vcp.querySelector('[data-bucket="Favourable"]')).toHaveTextContent('+1.08R'));
  });

  it('passes as_of from the URL to research queries', async () => {
    const fetchFn = mockFetch(serveFixtures);
    renderApp('/research?rview=scorecard&as_of=2026-08-01');
    await screen.findByRole('table', { name: 'Setup scorecard' });
    const calls = fetchFn.mock.calls.map((c) => String(c[0]));
    expect(calls.some((u) => u.startsWith('/api/v2/research/scorecard?') && u.includes('as_of=2026-08-01'))).toBe(true);
    expect(screen.getByText('Studies as of Sat 1 Aug')).toBeInTheDocument();
  });
});
