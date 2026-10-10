/** Smoke: Sector Intel board, context gauge, gap banner, group panel, chart grid, heatmap and studies from fixture envelopes. */
import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../../App';
import { routes } from '..';

vi.mock('../../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));
vi.mock('../../ui/Chart', () => ({ Chart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }));

const FRESH = { status: 'fresh', latest_session: '2026-08-13', expected_session: '2026-08-13', sessions_behind: 0, history_mode: false };
const env = (rows: unknown[], meta: Record<string, unknown> = {}, asOf = '2026-08-13') => ({
  as_of: asOf,
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', reason: null, offset: 0, limit: 500, sources: ['indicators_daily'], notes: [], metric_keys: [], ...meta },
});

const mk = (name: string, score: number | null, extra: Record<string, unknown> = {}) => ({
  id: `broad_industry:${name}`,
  level: 'broad_industry',
  group_name: name,
  stocks: 12,
  small: false,
  ranked: true,
  state: 'Favour',
  state_reason: '66% of members are above the 50 EMA.',
  near: 44.3,
  a50: 65.8,
  leaders: ['SANSERA', 'UNIPARTS'],
  pct: { near: 96, score_2W: 97 },
  deals_buy_10d: 3,
  deals_sell_10d: 0,
  deals_flow_10d_cr: 70,
  score_2W: score,
  nh_2W: 4,
  ad_2W: 12.7,
  upd_2W: 61.4,
  tov_2W: 5184,
  sh_2W: 4.2,
  tox_2W: 1.47,
  shd_2W: 1.4,
  rx_2W: 3.3,
  ret_2W: 5.5,
  nearchg_2W: 10.1,
  ...extra,
});

const MOOD = { score: 72, label: 'Strong', dir: 'cooling fast', a10chg: -12, spark: [50, 60, 72] };
const REL = { ic: 0.151, top: 58, bot: 42, days: 63, from: '2026-04-15', to: '2026-07-15', working: true };
const CTX = {
  level: 'broad_industry',
  level_label: 'Broad Industry',
  windows: ['1D', '1W', '2W', '1M'],
  gap_windows: [],
  last_clean_session: '2026-08-13',
  mood: MOOD,
  reliability: REL,
  verdict: 'Group ranking worked lately. Short-term breadth is falling fast. In this state the ranking worked about half as well.',
  what_to_do: 'Use only the top of the board.',
  evidence: {
    period: 'Oct 2024 - Jul 2026',
    dir: { 'cooling fast': { ic: 0.061, top: 55, bot: 46 } },
    lag: { working: 0.164, not: 0.042 },
  },
  evidence_now: { ic: 0.061, top: 55, bot: 46 },
};

function mockFetch(opts: { gap?: boolean } = {}) {
  const calls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
      const p = decodeURIComponent(url.pathname);
      calls.push(`${p}?${[...url.searchParams.entries()].map(([k, v]) => `${k}=${v}`).join('&')}`);
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });
      if (p === '/api/v2/sectors/board') {
        if (url.searchParams.get('level') === 'index')
          return json(
            env(
              [
                {
                  id: 'index:Nifty Auto',
                  group_name: 'Nifty Auto',
                  category: 'Sectoral',
                  close: 500,
                  sessions: 31,
                  stale: false,
                  ret_2W: 1.2,
                  rs_2W: 0.4,
                  above_20ema: true,
                },
              ],
              {
                status: 'partial',
                reason: 'index constituents missing: price readings only',
                notes: ['Index level shows price readings only.'],
                context: { level: 'index', level_label: 'Index', windows: [], gap_windows: [] },
              },
            ),
          );
        const rows = opts.gap
          ? [mk('Auto Components', null, { score_2W: null, ret_2W: null, deals_buy_10d: null, deals_sell_10d: null })]
          : [
              mk('Auto Components', 88.6),
              mk('Banks', 20, { state: 'Caution', leaders: ['HDFCBANK'], deals_buy_10d: 0, deals_sell_10d: 1, deals_flow_10d_cr: -30 }),
            ];
        return json(
          env(
            rows,
            { status: opts.gap ? 'partial' : 'ok', context: { ...CTX, gap_windows: opts.gap ? ['1D', '1W', '2W', '1M'] : [] } },
            opts.gap ? '2026-10-08' : '2026-08-13',
          ),
        );
      }
      if (p === '/api/v2/sectors/context') return json(env([CTX]));
      if (p === '/api/v2/sectors/charts')
        return json(
          env(
            url.searchParams
              .getAll('id')
              .map((id) => ({
                id,
                group_name: id.split(':')[1],
                bars: [{ time: '2026-08-13', open: 1, high: 2, low: 0.5, close: 1.5 }],
                rs: [],
                near: [{ time: '2026-08-13', value: 44 }],
              })),
          ),
        );
      if (p === '/api/v2/sectors/members')
        return json(
          env([
            {
              symbol: 'SANSERA',
              security_name: 'Sansera',
              rs_percentile: 99,
              near_52w_high: true,
              above_50ema: true,
              deal_flow_10d_cr: 50,
              deal_last_event: 'accumulate',
              market_cap_cr: 25769,
            },
          ]),
        );
      if (p === '/api/v2/sectors/heatmap')
        return json(
          env([
            { symbol: 'AAA', sector: 'Banks', broad_industry: 'Banks', industry: 'Pvt Banks', mc: 5000, t: 100, t20: 80, r1: 1.2 },
            { symbol: 'BBB', sector: 'IT', broad_industry: 'IT', industry: 'Software', mc: 4000, t: 50, t20: 60, r1: -0.8 },
          ]),
        );
      if (p === '/api/v2/sectors/group-studies')
        return json(
          env([], {
            status: 'unavailable',
            reason: 'big_move_group_stats not built yet',
            context: {
              level: 'broad_industry',
              study_period: 'Oct 2024 - Jul 2026',
              readings_study: [
                {
                  reading: '% of members within 10% of 52W high',
                  best_n: 'level',
                  ic_sector: 0.16,
                  ic_broad_industry: 0.103,
                  ic_industry: 0.094,
                  top: 55,
                  bot: 45,
                },
              ],
              mood_study: [
                {
                  condition: 'Short-term breadth cooling fast',
                  ic_sector: 0.133,
                  ic_broad_industry: 0.061,
                  ic_industry: 0.049,
                  top: 55,
                  bot: 46,
                },
              ],
            },
          }),
        );
      return new Response('', { status: 404 });
    }),
  );
  return calls;
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  return router;
}

afterEach(() => vi.unstubAllGlobals());

describe('Sector Intel tab', () => {
  it('shows the board with the mood + working gauge, deals chip, and opens the group panel', async () => {
    const calls = mockFetch();
    const router = renderAt('/groups');
    const grid = await screen.findByRole('grid', { name: 'Broad Industry board' }, { timeout: 5000 });
    expect(await within(grid).findByRole('button', { name: 'Auto Components' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Sector Intel' })).toBeInTheDocument();
    const ctx = screen.getByRole('region', { name: 'Sector Intel context' });
    expect(within(ctx).getByText('Working')).toBeInTheDocument();
    expect(within(ctx).getByText(/about half as well/)).toBeInTheDocument();
    expect(within(ctx).getByText('What to do:')).toBeInTheDocument();
    expect(within(grid).getByText('3 buy · 0 sell · +₹70 Cr')).toBeInTheDocument();
    expect(within(grid).queryByText(/SQZ|VCP|setup/i)).toBeNull(); // no setup references in this tab
    expect(calls.some((c) => c.includes('/sectors/board?level=broad_industry'))).toBe(true);
    // default selection opens the panel of the top-scored group
    const panel = await screen.findByRole('region', { name: 'Auto Components panel' }, { timeout: 5000 });
    expect(await within(panel).findByText('1 of 1 members are within 10% of their 52-week high.', { exact: false })).toBeInTheDocument();
    fireEvent.click(within(grid).getByRole('button', { name: 'Banks' }));
    await waitFor(() => expect(router.state.location.search).toContain('group=broad_industry%3ABanks'));
    expect(await screen.findByRole('region', { name: 'Banks panel' })).toBeInTheDocument();
  }, 15_000);

  it('shows the honest data-gap banner with a jump to the latest good session', async () => {
    mockFetch({ gap: true });
    const router = renderAt('/groups?as_of=2026-10-08');
    const banner = (await screen.findByText(/Data gap: the/, {}, { timeout: 5000 })).closest('[role="status"]') as HTMLElement;
    expect(banner).toHaveTextContent('those readings are blank');
    fireEvent.click(within(banner).getByRole('button', { name: /latest good session/ }));
    await waitFor(() => expect(router.state.location.search).toContain('as_of=2026-08-13'));
  }, 15_000);

  it('switches to the chart grid, the index level, the heatmap and group studies', async () => {
    const calls = mockFetch();
    renderAt('/groups?view=grid');
    expect(await screen.findByRole('img', { name: 'Auto Components equal-weight chart' }, { timeout: 5000 })).toBeInTheDocument();
    expect(
      calls.some(
        (c) => c.includes('/sectors/charts') && c.includes('id=broad_industry:Auto Components') && c.includes('id=broad_industry:Banks'),
      ),
    ).toBe(true);
    fireEvent.click(screen.getByRole('radio', { name: 'Heatmap' }));
    expect(await screen.findByRole('combobox', { name: 'Tile colour' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Tile size' })).toHaveValue('t');
    fireEvent.click(screen.getByRole('radio', { name: 'Group studies' }));
    expect(await screen.findByText('Not built yet', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText('% of members within 10% of 52W high')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: 'Board' }));
    fireEvent.click(await screen.findByRole('radio', { name: 'Index' }));
    expect(await screen.findByRole('grid', { name: 'Index board' }, { timeout: 5000 })).toBeInTheDocument();
    expect(await screen.findByText('Nifty Auto')).toBeInTheDocument();
  }, 20_000);
});
