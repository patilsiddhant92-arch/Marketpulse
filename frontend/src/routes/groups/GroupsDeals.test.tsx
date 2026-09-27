/** Smoke: Groups board → drill-down and Deals session render from fixture envelopes. */
import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../../App';
import { routes } from '..';

vi.mock('../../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));

const FRESH = { status: 'fresh', latest_session: '2026-09-25', expected_session: '2026-09-25', sessions_behind: 0, history_mode: false };
const env = (rows: unknown[], meta: Record<string, unknown> = {}) => ({
  as_of: '2026-09-25',
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'partial', reason: 'group_daily not built yet; computed live', offset: 0, limit: 500, sources: [], notes: [], metric_keys: [], ...meta },
});

const group = {
  id: 'industry:Heavy Electrical Equipment',
  level: 'industry',
  group_name: 'Heavy Electrical Equipment',
  trade_date: '2026-09-25',
  stocks: 27,
  rrg_quadrant: 'Lagging',
  days_in_quadrant: 4,
  rs_ratio: 98.7,
  rs_momentum: 99.1,
  rank: 93,
  rank_n: 120,
  rank_delta_5: -3,
  rank_delta_20: 12,
  return_ew_21d: -1.85,
  excess_vs_midsml400_21d: 1.76,
  excess_vs_midsml400_63d: -4.2,
  breadth_50: 40.7,
  turnover_share_delta: 0.12,
  flow_up_days_10: 7,
  deal_net_10s_cr: null,
  rank_spark_60: [100, 95, 93],
  rs_line_60: [100, 99, 101],
  leader_symbols: ['INDOTECH'],
};

function mockFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
      const p = decodeURIComponent(url.pathname);
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });
      if (p === '/api/v2/groups/board') return json(env([group], { context: { ranked: 120, floor_label: 'members with market cap ≥ ₹1,000 Cr' } }));
      if (p === '/api/v2/groups/rrg') return json(env([{ ...group, tail: [] }]));
      if (p === '/api/v2/groups/industry:Heavy Electrical Equipment/members')
        return json(env([{ symbol: 'INDOTECH', security_name: 'Indo Tech', rs_percentile: 95.5, market_cap_cr: 3375, active_setups: null }]));
      if (p === '/api/v2/groups/industry:Heavy Electrical Equipment')
        return json(
          env([group], {
            context: {
              breadcrumb: [
                { level: 'sector', name: 'Capital Goods', id: 'sector:Capital Goods' },
                { level: 'industry', name: 'Heavy Electrical Equipment', id: group.id },
              ],
              children: [],
            },
          }),
        );
      if (p === '/api/v2/deals/session')
        return json(
          env(
            [
              { symbol: 'POLICYBZR', event_type: 'fresh', net_ex_prop_cr: 320.6, net_cr: 320.6, buying_houses: 1, net_10s: [null, 320.6] },
              { symbol: 'KSCL', event_type: 'churn', net_ex_prop_cr: 0, buy_cr: 300, sell_cr: 339 },
            ],
            { context: { deal_session: '2026-09-24', no_records_for_session: true, event_counts: { fresh: 1, churn: 1 }, net_10s_dates: ['2026-09-23', '2026-09-24'] } },
          ),
        );
      return new Response('', { status: 404 });
    }),
  );
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  return router;
}

afterEach(() => vi.unstubAllGlobals());

describe('Groups and Deals tabs', () => {
  it('shows the board with partial-source note and drills into a group', async () => {
    mockFetch();
    const router = renderAt('/groups');
    const drill = await screen.findByRole('button', { name: 'Heavy Electrical Equipment' }, { timeout: 5000 });
    expect(screen.getByText('computed live')).toBeInTheDocument();
    fireEvent.click(drill);
    expect(router.state.location.search).toContain('group=industry');
    const parent = await screen.findByRole('button', { name: 'Capital Goods' }, { timeout: 5000 });
    expect(parent.closest('nav')).toHaveAttribute('aria-label', 'Taxonomy path');
    expect(await screen.findByText('INDOTECH', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Show these as charts/ }).getAttribute('href')).toContain('source=group%3Aindustry%3AHeavy');
  }, 15_000); // drill = three sequential fetch-and-render steps; slow under a parallel full run

  it('lists every deal stock of the session (buying and churn) and flags NO RECORDS', async () => {
    mockFetch();
    renderAt('/deals');
    // POLICYBZR appears in the table and in the at-a-glance band's biggest net buys.
    expect((await screen.findAllByText('POLICYBZR', {}, { timeout: 5000 })).length).toBe(2);
    const band = screen.getByRole('region', { name: 'Deals at a glance' });
    expect(within(band).getByText('POLICYBZR')).toBeInTheDocument();
    expect(within(band).getByText('Fresh buyer', { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/NO RECORDS/)).toBeInTheDocument();
    // Today lists all deal stocks (default All caps); churn/prop names sit in the same table, tagged by event.
    expect(await screen.findByText('KSCL')).toBeInTheDocument();
  });
});
