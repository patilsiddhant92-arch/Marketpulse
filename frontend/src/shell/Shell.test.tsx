/**
 * Smoke render of the shell against a fixture API: six tabs, freshness chip,
 * environment strip (ok / unavailable / 404), history mode, palette.
 */
import { QueryClient } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { routes } from '../routes';

// Legacy workspaces fetch old endpoints and draw canvases; they are covered by
// their own screens. Stub them so the smoke test exercises the new shell only.
vi.mock('../components/CockpitWorkspace', () => ({ CockpitWorkspace: () => <div>legacy cockpit</div> }));
vi.mock('../components/ExposureGateHeader', () => ({ ExposureGateHeader: () => null }));
vi.mock('../components/MomentumWorkspace', () => ({ MomentumWorkspace: () => <div>legacy momentum</div> }));
vi.mock('../components/VcpWorkbenchWorkspace', () => ({ VcpWorkbenchWorkspace: () => <div>legacy vcp</div> }));
vi.mock('../components/SectorWorkspace', () => ({ SectorWorkspace: () => <div>legacy sectors</div> }));
vi.mock('../components/CapitalFlowDashboard', () => ({ CapitalFlowDashboard: () => <div>legacy flow</div> }));
vi.mock('../components/DealsWorkspace', () => ({ DealsWorkspace: () => <div>legacy deals</div> }));
vi.mock('../components/InspectorSidecar', () => ({
  InspectorSidecar: ({ symbol }: { symbol: string }) => <aside>legacy inspector {symbol}</aside>,
}));
vi.mock('../components/MultiChartModal', () => ({ MultiChartModal: () => <div>legacy charts</div> }));
vi.mock('../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));

const FRESH = { status: 'fresh', latest_session: '2026-09-25', expected_session: '2026-09-25', sessions_behind: 0, history_mode: false };

const envelope = (rows: unknown[], extra: Record<string, unknown> = {}) => ({
  as_of: '2026-09-25',
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', offset: 0, limit: 500 },
  ...extra,
});

const health = {
  status: 'healthy',
  version: '2.0.0',
  build: 'test',
  freshness: FRESH,
  checks: [{ name: 'prices_daily', ok: true, detail: null }],
};

const pillar = (status: string | null, extra: Record<string, unknown> = {}) => ({
  status,
  sentence: null,
  dir_1d: null,
  dir_1w: null,
  dir_1m: null,
  inputs: {},
  ...extra,
});

// Newest first, as the server orders them.
const regimeRows = [
  {
    trade_date: '2026-09-25',
    verdict: 'Constructive',
    previous_verdict: 'Mixed',
    rule_id: 'R2',
    days_in_state: 4,
    changed_on: '2026-09-21',
    readings: [{ title: 'Leaders holding', text: 'New highs rising while the index dips.' }],
    pillars: {
      trend: pillar('Healthy', { sentence: 'MidSml400 above a rising 50 EMA.', dir_1d: 'up', dir_1w: 'up', dir_1m: 'flat' }),
      participation: pillar('Neutral', { inputs: { pct_above_50ema: 62.5 } }),
      leadership: pillar('Healthy'),
      follow_through: pillar('Weak'),
      stress: pillar(null),
    },
    inputs: {},
  },
  {
    trade_date: '2026-09-24',
    verdict: 'Constructive',
    previous_verdict: 'Mixed',
    rule_id: 'R2',
    days_in_state: 3,
    changed_on: '2026-09-21',
    readings: null,
    pillars: {
      trend: pillar('Healthy'),
      participation: pillar('Neutral'),
      leadership: pillar('Neutral'),
      follow_through: pillar('Weak'),
      stress: pillar(null),
    },
    inputs: {},
  },
];

type Handler = (url: URL) => Response | undefined;

function mockFetch(handler: Handler) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
    return handler(url) ?? new Response('', { status: 404 });
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function renderApp(path = '/desk') {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App router={router} queryClient={client} />);
  return router;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Shell', () => {
  it('renders six tabs, the freshness chip and the environment verdict', async () => {
    const fetchFn = mockFetch((url) => {
      if (url.pathname === '/api/v2/health') return json(health);
      if (url.pathname === '/api/v2/market/regime') return json(envelope(regimeRows));
      if (url.pathname === '/api/v2/metrics/dictionary')
        return json(
          envelope([
            {
              key: 'pct_above_50ema',
              plain_name: 'Stocks above 50 EMA',
              measures: 'Share above 50 EMA',
              zones: [{ range: '> 60', label: 'Healthy', tone: 'good' }],
              read_with: [],
              definition_sql_ref: 'breadth_daily.pct_above_50ema',
            },
          ]),
        );
      return undefined;
    });
    renderApp('/');

    const nav = screen.getByRole('navigation', { name: 'Tabs' });
    expect(
      within(nav)
        .getAllByRole('link')
        .map((a) => a.textContent?.replace(/^\d/, '')),
    ).toEqual(['Desk', 'Screener', 'Groups', 'Deals', 'Charts', 'Research']);
    expect(await screen.findByText('legacy cockpit')).toBeInTheDocument();
    expect(await screen.findByText('Constructive')).toBeInTheDocument();
    expect(screen.getByText('improved from Mixed on Mon · 4th day')).toBeInTheDocument();
    expect(await screen.findByText('Fri 25 Sep')).toBeInTheDocument();

    // Drawer: pillars + dictionary-labelled reading.
    fireEvent.click(screen.getByRole('button', { name: /market environment details/i }));
    const dialog = await screen.findByRole('dialog', { name: 'Market environment' });
    expect(within(dialog).getByText(/rule R2/)).toBeInTheDocument();
    expect(within(dialog).getByRole('region', { name: 'Participation pillar' })).toHaveTextContent('Are most stocks joining?');
    expect(await within(dialog).findByText('Stocks above 50 EMA')).toBeInTheDocument();
    expect(within(dialog).getByText('62.50')).toHaveClass('text-up');
    expect(within(dialog).getByText('Leaders holding')).toBeInTheDocument();
    expect(within(dialog).getByRole('img', { name: 'Verdict history' })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Market environment' })).not.toBeInTheDocument());

    expect(fetchFn).toHaveBeenCalledWith('/api/v2/market/regime', expect.anything());
    expect(screen.getByText('Fri 25 Sep')).toBeInTheDocument();
  });

  it('degrades gracefully when v2 is not deployed (404) and falls back to legacy health', async () => {
    mockFetch((url) => {
      if (url.pathname === '/api/health')
        return json({ status: 'healthy', actionable: true, database_date: '2026-09-24', expected_session: '2026-09-25', detail: 'stale' });
      return undefined;
    });
    renderApp('/desk');
    expect(await screen.findByText(/not available yet \(API v2 pending\)/)).toBeInTheDocument();
    expect(await screen.findByText('Thu 24 Sep')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows "unavailable" when meta.status says so, and an API-down banner when the server is unreachable', async () => {
    mockFetch((url) => {
      if (url.pathname === '/api/v2/market/regime')
        return json(envelope([], { meta: { status: 'unavailable', reason: 'regime_daily not built yet', offset: 0, limit: 500 } }));
      if (url.pathname === '/api/v2/health') return new Response('', { status: 502 });
      return undefined;
    });
    renderApp('/desk');
    expect(await screen.findByText(/Market environment unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/regime_daily not built yet/)).toBeInTheDocument();
    expect(await screen.findByText('API unreachable')).toBeInTheDocument();
  });

  it('propagates as_of from the URL into v2 queries and shows history mode', async () => {
    const fetchFn = mockFetch((url) => {
      if (url.pathname === '/api/v2/market/regime') return json(envelope(regimeRows));
      return undefined;
    });
    renderApp('/screener?as_of=2026-03-12');
    expect(await screen.findByText('History mode')).toBeInTheDocument();
    await waitFor(() => expect(fetchFn).toHaveBeenCalledWith('/api/v2/market/regime?as_of=2026-03-12', expect.anything()));
    // The rebuilt Screener asks for its presets (no as_of: presets are date-free).
    await waitFor(() => expect(fetchFn).toHaveBeenCalledWith('/api/v2/screener/presets', expect.anything()));
    // Tab links keep as_of.
    expect(screen.getByRole('link', { name: /Deals/ })).toHaveAttribute('href', '/deals?as_of=2026-03-12');
  });

  it('switches tabs with number keys and keeps visited tabs mounted', async () => {
    mockFetch(() => undefined);
    const router = renderApp('/desk');
    expect(await screen.findByText('legacy cockpit')).toBeInTheDocument();
    act(() => {
      fireEvent.keyDown(window, { key: '4' });
    });
    await waitFor(() => expect(router.state.location.pathname).toBe('/deals'));
    expect(await screen.findByText('legacy deals')).toBeVisible();
    expect(screen.getByText('legacy cockpit')).not.toBeVisible();
  });

  it('opens the command palette with Ctrl+K and opens a typed symbol in the sidecar', async () => {
    mockFetch(() => undefined);
    const router = renderApp('/desk');
    await screen.findByText('legacy cockpit');
    act(() => {
      fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    });
    const input = await screen.findByPlaceholderText(/Symbol, tab, preset/);
    fireEvent.change(input, { target: { value: 'hal' } });
    fireEvent.click(await screen.findByText(/in Stock 360 sidecar/));
    await waitFor(() => expect(router.state.location.search).toContain('sym=HAL'));
    expect(await screen.findByText('legacy inspector HAL')).toBeInTheDocument();
  });

  it('lazy-loads Research', async () => {
    mockFetch(() => undefined);
    renderApp('/research');
    expect(await screen.findByText(/Research lands with the evidence engine/)).toBeInTheDocument();
  });
});
