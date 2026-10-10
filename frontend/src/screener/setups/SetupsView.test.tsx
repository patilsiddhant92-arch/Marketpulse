/** Smoke render of the Setups board (default Screener mode) against a fixture API. */
import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../../App';
import { routes } from '../../routes';

vi.mock('../../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));

const FRESH = { status: 'fresh', latest_session: '2026-08-13', expected_session: '2026-08-13', sessions_behind: 0, history_mode: false };
const env = (rows: unknown[], meta: Record<string, unknown> = {}) => ({
  as_of: '2026-08-13',
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', offset: 0, limit: 5000, sources: [], notes: [], metric_keys: [], context: {}, ...meta },
});
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });

const base = {
  tags: [],
  screeners: [],
  status: 'active',
  delivery_streak: 0,
  delivery_5d: [],
  blue_sky: false,
  breakouts_held_6m: 0,
  breakouts_failed_6m: 0,
  chips: [],
  results_soon: false,
};
const rows = [
  {
    ...base,
    symbol: 'AAA',
    industry: 'Steel',
    sector: 'Metals',
    tags: ['SQZ', 'MOM 0–2%'],
    screeners: ['darvas_squeeze', 'momentum'],
    status: 'new',
    group_state: 'Favour',
    group_reason: 'Trending: 67% of stocks above 50 EMA.',
    rs_percentile: 92,
    delivery_streak: 3,
    base_rate: { n: 120, win: 47, median: -0.4, scope: 'Darvas Squeeze in Favour groups', horizon: 20, insufficient: false },
    chips: [{ kind: 'deal', label: 'Deal +12 Cr', title: null }],
    results_soon: true,
    results_date: '2026-08-20',
  },
  {
    ...base,
    symbol: 'BBB',
    industry: 'Drugs',
    sector: 'Pharma',
    tags: ['VCP'],
    screeners: ['vcp'],
    group_state: 'Caution',
    group_reason: 'Weak: 30% above 50 EMA.',
    rs_percentile: 70,
    data_warning: 'unexplained price gap on 2026-08-01',
  },
];
const context = {
  previous_session: '2026-08-12',
  session_gap_days: 1,
  counts: {
    darvas_squeeze: { today: 1, median_20: 1, percentile: 50, series: [['2026-08-12', 1], ['2026-08-13', 1]], history_sessions: 2 },
    darvas_10ema: { today: 0, median_20: 0, percentile: 50, series: [], history_sessions: 0 },
    vcp: { today: 1, median_20: 1, percentile: 50, series: [], history_sessions: 0 },
    momentum: { today: 1, median_20: null, percentile: null, series: [], history_sessions: 0, gap: 'not stored' },
  },
  group_split: { Favour: 1, Neutral: 0, Caution: 1 },
  confluence: 1,
  readout: { lines: ['2 stocks pass at least one screener.'], what_to_do: ['Start with the confluence rows in Favour groups'] },
  data_gaps: ['Ex-dates: corporate_actions is empty.'],
};

afterEach(() => vi.unstubAllGlobals());

describe('SetupsView', () => {
  it('renders the board, read-out, filters and switches the momentum template', async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
        calls.push(url.pathname + url.search);
        if (url.pathname === '/api/v2/setups/board') return json(env(rows, { status: 'partial', context }));
        if (url.pathname === '/api/v2/setups/near-miss')
          return json(env([{ symbol: 'NNN', gate: 'RVOL 1.40 (needs ≤ 1)', squeeze_pct: 1.2, close: 10, box_top: 10.2, ema_10: 9.9, rvol: 1.4 }]));
        return new Response('', { status: 404 });
      }),
    );
    const router = createMemoryRouter(routes, { initialEntries: ['/screener?as_of=2026-08-13'] });
    render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);

    expect(await screen.findByRole('tab', { name: 'Setups', selected: true })).toBeInTheDocument();
    expect(await screen.findByText('AAA')).toBeInTheDocument();
    expect(screen.getByText('BBB')).toBeInTheDocument();
    expect(screen.getByText('2 stocks pass at least one screener.')).toBeInTheDocument();
    expect(screen.getByText('What to do:')).toBeInTheDocument();
    expect(screen.getByText('Results 2026-08-20')).toBeInTheDocument();
    expect(screen.getAllByText('data gap').length).toBeGreaterThan(0);
    expect(calls.some((c) => c.startsWith('/api/v2/setups/board?') && c.includes('as_of=2026-08-13') && c.includes('template=ema'))).toBe(true);

    // Group-state filter: Favour only.
    fireEvent.click(screen.getByRole('button', { name: /Favour/ }));
    await waitFor(() => expect(screen.queryByText('BBB')).not.toBeInTheDocument());
    expect(screen.getByText('AAA')).toBeInTheDocument();

    // SMA template is one visible switch.
    fireEvent.click(screen.getByRole('radio', { name: 'SMA template' }));
    await waitFor(() => expect(calls.some((c) => c.startsWith('/api/v2/setups/board?') && c.includes('template=sma'))).toBe(true));

    // Near-miss view.
    fireEvent.click(screen.getByRole('tab', { name: 'Near-miss' }));
    expect(await screen.findByText('RVOL 1.40 (needs ≤ 1)')).toBeInTheDocument();
  }, 30_000);
});
