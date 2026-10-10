/**
 * One group state across tabs: Pulse (groups table), Sector Intel (board) and Setups (board) all show the state
 * served by GET /api/v2/pulse/group-state, even when their own endpoints carry a different (stale) copy.
 */
import { QueryClient } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { routes } from '../routes';
import fixtures from '../routes/pulse/fixtures.json';
import { groupStateEnvelope, sharedRow } from '../test/groupStateFixture';

vi.mock('../ui/Chart', () => ({ Chart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }));
vi.mock('../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));

type Fx = Record<string, { rows: { name?: string }[]; meta: Record<string, unknown> } & Record<string, unknown>>;
const FX = fixtures as unknown as Fx;
const GROUP = String(FX.groups.rows[0].name);
const REASON = 'Money leaving: turnover share 0.80% vs 1.00% 20D avg. Group -1.5% in 5D.';

const FRESH = { status: 'fresh', latest_session: '2026-08-13', expected_session: '2026-08-13', sessions_behind: 0, history_mode: false };
const env = (rows: unknown[], meta: Record<string, unknown> = {}) => ({
  as_of: '2026-08-13',
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', reason: null, offset: 0, limit: 5000, sources: [], notes: [], metric_keys: [], context: {}, ...meta },
});
const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });

const boardRow = {
  id: `broad_industry:${GROUP}`,
  level: 'broad_industry',
  group_name: GROUP,
  stocks: 12,
  small: false,
  ranked: true,
  state: 'Favour', // stale local copy: the shared source says Caution
  state_reason: 'stale',
  near: 40,
  a50: 60,
  leaders: [],
  pct: {},
  deals_buy_10d: 0,
  deals_sell_10d: 0,
  deals_flow_10d_cr: 0,
  score_2W: 80,
};
const setupRow = {
  symbol: 'AAA',
  industry: GROUP,
  sector: 'X',
  tags: ['VCP'],
  screeners: ['vcp'],
  status: 'active',
  group_state: 'Favour', // stale local copy
  group_reason: 'stale',
  delivery_streak: 0,
  delivery_5d: [],
  blue_sky: false,
  breakouts_held_6m: 0,
  breakouts_failed_6m: 0,
  chips: [],
  results_soon: false,
};

function mockApi() {
  const calls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
      const p = decodeURIComponent(url.pathname);
      calls.push(p + url.search);
      if (p === '/api/v2/pulse/group-state') {
        const level = (url.searchParams.get('level') ?? 'industry') as 'industry';
        return json(groupStateEnvelope([sharedRow(GROUP, 'Caution', REASON, level)]));
      }
      if (p === '/api/v2/pulse/groups') return json(url.searchParams.get('level') === 'sectoral' ? FX.sectoral : FX.groups);
      const key = p.replace('/api/v2/pulse/', '');
      if (p.startsWith('/api/v2/pulse/') && key in FX) return json(FX[key]);
      if (p === '/api/v2/sectors/board')
        return json(env([boardRow], { context: { level: 'broad_industry', level_label: 'Broad Industry', windows: ['1D', '1W', '2W', '1M'], gap_windows: [] } }));
      if (p === '/api/v2/setups/board') return json(env([setupRow]));
      return new Response('', { status: 404 });
    }),
  );
  return calls;
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
}

afterEach(() => vi.unstubAllGlobals());

describe('one group state across Pulse, Sector Intel and Setups', () => {
  it('Pulse groups table shows the shared state', async () => {
    const calls = mockApi();
    renderAt('/desk?as_of=2026-08-13');
    const table = await screen.findByRole('grid', { name: 'Groups table' });
    await waitFor(() => expect(within(table).getAllByText('Caution')[0]).toHaveAttribute('data-state', 'Caution'));
    expect(within(table).getAllByText('Caution')[0].closest('[title]')).toHaveAttribute('title', expect.stringContaining(REASON));
    expect(calls.some((c) => c.startsWith('/api/v2/pulse/group-state?') && c.includes('level=sector') && c.includes('as_of=2026-08-13'))).toBe(true);
  }, 30_000);

  it('Sector Intel board shows the shared state, not its own copy', async () => {
    const calls = mockApi();
    renderAt('/groups?as_of=2026-08-13');
    await screen.findAllByText(GROUP);
    await waitFor(() => expect(screen.getAllByRole('img', { name: 'Caution' }).length).toBeGreaterThan(0));
    expect(screen.queryAllByRole('img', { name: 'Favour' })).toHaveLength(0);
    expect(screen.getAllByRole('img', { name: 'Caution' })[0]).toHaveAttribute('title', expect.stringContaining(REASON));
    expect(calls.some((c) => c.startsWith('/api/v2/pulse/group-state?') && c.includes('level=broad_industry'))).toBe(true);
  }, 30_000);

  it('Setups board shows the shared Industry state, not its own copy', async () => {
    const calls = mockApi();
    renderAt('/screener?as_of=2026-08-13');
    expect(await screen.findByText('AAA')).toBeInTheDocument();
    const table = screen.getAllByRole('grid')[0];
    await waitFor(() => expect(within(table).getByText('Caution')).toHaveAttribute('data-state', 'Caution'));
    expect(within(table).queryByText('Favour')).not.toBeInTheDocument();
    expect(calls.some((c) => c.startsWith('/api/v2/pulse/group-state?') && c.includes('level=industry'))).toBe(true);
  }, 30_000);
});
