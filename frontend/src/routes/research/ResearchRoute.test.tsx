/**
 * Research tab against a fixture API: the intentional "being computed" state
 * for unavailable envelopes, then each study rendered from realistic rows,
 * with n printed beside every statistic and "insufficient sample" below 30.
 */
import { QueryClient } from '@tanstack/react-query';
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../../App';
import { routes } from '..';
import { fixtureFor } from './fixtures';

vi.mock('../../components/CockpitWorkspace', () => ({ CockpitWorkspace: () => <div>legacy cockpit</div> }));
vi.mock('../../components/ExposureGateHeader', () => ({ ExposureGateHeader: () => null }));
vi.mock('../../components/MomentumWorkspace', () => ({ MomentumWorkspace: () => <div>legacy momentum</div> }));
vi.mock('../../components/VcpWorkbenchWorkspace', () => ({ VcpWorkbenchWorkspace: () => <div>legacy vcp</div> }));
vi.mock('../../components/SectorWorkspace', () => ({ SectorWorkspace: () => <div>legacy sectors</div> }));
vi.mock('../../components/CapitalFlowDashboard', () => ({ CapitalFlowDashboard: () => <div>legacy flow</div> }));
vi.mock('../../components/DealsWorkspace', () => ({ DealsWorkspace: () => <div>legacy deals</div> }));
vi.mock('../../components/InspectorSidecar', () => ({ InspectorSidecar: () => <aside>legacy inspector</aside> }));
vi.mock('../../components/MultiChartModal', () => ({ MultiChartModal: () => <div>legacy charts</div> }));
vi.mock('../../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

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
  if ((m = path.match(/^research\/big-moves\/(.+)$/))) {
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
  it('shows an intentional "being computed" state when the evidence tables are not built', async () => {
    mockFetch((url) =>
      RESEARCH.test(url.pathname) ? json(unavailable('market_analogs not built yet (evidence engine, spec §5)', ['market_analogs'])) : undefined,
    );
    renderApp('/research');
    expect(await screen.findByText('Evidence is being computed — available after the next rebuild')).toBeInTheDocument();
    expect(screen.getByText(/market_analogs not built yet/)).toBeInTheDocument();
    expect(screen.getByText(/No number is shown until it can be shown with its sample size/)).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Research studies' })).toBeInTheDocument();
    // Dev builds offer the fixture preview; switching it on renders fixture data without the API.
    fireEvent.click(screen.getByRole('button', { name: /Preview with fixtures/ }));
    expect(await screen.findByText('Fixture data — not real')).toBeInTheDocument();
    expect(await screen.findByRole('grid', { name: 'Market analogs' })).toBeInTheDocument();
  });

  it('market analogs: medians with n, spread, agreement and a time-travel link per analog', async () => {
    const fetchFn = mockFetch(serveFixtures);
    const router = renderApp('/research');
    const grid = await screen.findByRole('grid', { name: 'Market analogs' });
    expect(within(grid).getAllByRole('row')).toHaveLength(11);
    const h20 = document.querySelector('[data-horizon="20"]') as HTMLElement;
    expect(h20).toHaveTextContent('+3.8%');
    expect(h20).toHaveTextContent('n=10');
    expect(h20).toHaveTextContent('7 up / 3 down');
    expect(screen.getByText(/70% of analogs were higher 20 sessions later/)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /return fan/ })).toBeInTheDocument();
    expect(fetchFn).toHaveBeenCalledWith('/api/v2/research/analogs', expect.anything());

    fireEvent.click(within(grid).getAllByRole('button', { name: /Go/ })[0]);
    await waitFor(() => expect(router.state.location.search).toMatch(/as_of=\d{4}-\d{2}-\d{2}/));
    expect(await screen.findByText(/Studies as of/)).toBeInTheDocument();
  });

  it('big movers: event browser, catalyst shares with n, lift with precision and n, event fingerprint vs controls', async () => {
    mockFetch(serveFixtures);
    renderApp('/research?rview=movers');
    const grid = await screen.findByRole('grid', { name: 'Big-move events' });
    expect(within(grid).getAllByRole('row').length).toBe(19);
    expect(screen.getByText('events=18')).toBeInTheDocument();
    const lift = screen.getByRole('table', { name: 'Pre-move trait lift' });
    const rsRow = within(lift).getAllByRole('row')[1];
    expect(rsRow).toHaveTextContent('2.4×');
    expect(rsRow).toHaveTextContent('7.9%');
    expect(rsRow).toHaveTextContent('n=412');
    // n = 22 < 30: lift is not printed as a number.
    const dealRow = within(lift).getAllByRole('row').find((r) => r.textContent?.includes('Deal buy 10s'))!;
    expect(dealRow).toHaveTextContent('insufficient sample');
    expect(dealRow).not.toHaveTextContent('1.8×');
    expect(within(lift).getByText('in-sample')).toBeInTheDocument();

    fireEvent.click(within(grid).getByText('APARINDS'));
    const dialog = await screen.findByRole('dialog', { name: /APARINDS/ });
    expect(within(dialog).getByText('Results ±3')).toBeInTheDocument();
    expect(await within(dialog).findByRole('table', { name: 'Pre-move fingerprint vs controls' })).toBeInTheDocument();
    expect(within(dialog).getByText('controls=10')).toBeInTheDocument();
    // Bars endpoint 404s here: the served close path is drawn instead.
    expect(await within(dialog).findByRole('img', { name: /close vs T-1 close/ })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /Stock 360 as of event/ })).toBeInTheDocument();
  });

  it('pre-move watch: labelled research, precision with n, insufficient sample below 30', async () => {
    mockFetch(serveFixtures);
    renderApp('/research?rview=premove');
    const grid = await screen.findByRole('grid', { name: 'Pre-move watch' });
    expect(screen.getByText('Research list — not a trade signal')).toBeInTheDocument();
    const anant = within(grid).getAllByRole('row').find((r) => r.textContent?.includes('ANANTRAJ'))!;
    expect(anant).toHaveTextContent('insufficient sample');
    expect(anant).toHaveTextContent('n=22');
    expect(anant).not.toHaveTextContent('8.6%');
    const jyoti = within(grid).getAllByRole('row').find((r) => r.textContent?.includes('JYOTICNC'))!;
    expect(jyoti).toHaveTextContent('9.4%');
    expect(jyoti).toHaveTextContent('n=212');
    expect(jyoti).toHaveTextContent('beats base rate');
  });

  it('group studies switch taxonomy level and print n', async () => {
    mockFetch(serveFixtures);
    renderApp('/research?rview=groups');
    const grid = await screen.findByRole('grid', { name: 'Big movers by Industry' });
    expect(within(grid).getAllByRole('row').find((r) => r.textContent?.includes('Aerospace & Defense'))).toHaveTextContent('n=4');
    fireEvent.click(screen.getByRole('button', { name: 'Broad Sector' }));
    const g2 = await screen.findByRole('grid', { name: 'Big movers by Broad Sector' });
    expect(within(g2).getAllByRole('row').find((r) => r.textContent?.includes('Industrials'))).toHaveTextContent('n=7');
    expect(screen.getByText(/After an Industry turns Leading/)).toBeInTheDocument();
  });

  it('setup evidence: queue × environment with n on every cell and insufficient sample below 30', async () => {
    mockFetch(serveFixtures);
    renderApp('/research?rview=evidence');
    const table = await screen.findByRole('table', { name: 'Setup evidence by environment' });
    await waitFor(() => expect(within(table).getAllByText(/n=/).length).toBeGreaterThan(10));
    const vcp = within(table).getAllByRole('row').find((r) => r.textContent?.startsWith('VCP'))!;
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
    renderApp('/research?rview=movers&as_of=2026-08-01');
    await screen.findByRole('grid', { name: 'Big-move events' });
    const calls = fetchFn.mock.calls.map((c) => String(c[0]));
    expect(calls.some((u) => u.startsWith('/api/v2/research/big-moves?') && u.includes('as_of=2026-08-01'))).toBe(true);
    expect(screen.getByText('Studies as of Sat 1 Aug')).toBeInTheDocument();
  });
});
