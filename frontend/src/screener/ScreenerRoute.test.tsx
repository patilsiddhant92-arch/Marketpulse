/** Smoke render of the rebuilt Screener against a fixture API. */
import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { routes } from '../routes';

vi.mock('../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));

const FRESH = { status: 'fresh', latest_session: '2026-09-25', expected_session: '2026-09-25', sessions_behind: 0, history_mode: false };
const env = (rows: unknown[], meta: Record<string, unknown> = {}) => ({
  as_of: '2026-09-25',
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', offset: 0, limit: 5000, sources: [], notes: [], metric_keys: [], context: {}, ...meta },
});
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });

const presets = env(
  [
    {
      id: 'minervini_8of8',
      label: 'Minervini 8/8',
      description: 'All eight checks and rank ≥ 70.',
      kind: 'rules',
      queue: null,
      category: 'Trend',
      available: true,
      rules: [
        { field: 'trend_template_pass', op: 'is_true', value: null, ref: null },
        { field: 'rs_percentile', op: 'gte', value: 70, ref: null },
      ],
    },
    {
      id: 'vcp',
      label: 'VCP',
      description: 'Desk VCP queue.',
      kind: 'queue',
      queue: 'vcp',
      category: 'Setups',
      available: true,
      rules: [],
    },
  ],
  {
    context: {
      fields: [
        { field: 'trend_template_pass', label: 'Trend template 8/8', kind: 'bool' },
        { field: 'rs_percentile', label: 'Strength rank', kind: 'num', metric_key: 'rs_percentile' },
      ],
    },
  },
);

const runRows = [
  {
    symbol: 'AAA',
    industry: 'Pharma',
    close: 100,
    change_1d_pct: 1.5,
    rs_percentile: 95,
    rs_is_ipo_rank: false,
    is_new: true,
    delivery_pct: null,
  },
  { symbol: 'BBB', industry: 'Cement', close: 50, change_1d_pct: -0.5, rs_percentile: 80, rs_is_ipo_rank: false, is_new: false },
];

afterEach(() => vi.unstubAllGlobals());

describe('ScreenerRoute', () => {
  it('renders presets, rule chips, counts, new / dropped and the rule debugger', async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
        calls.push(url.pathname + url.search);
        if (url.pathname === '/api/v2/screener/presets') return json(presets);
        if (url.pathname === '/api/v2/screener/run')
          return json(
            env(runRows, {
              context: {
                new_count: 1,
                previous_session: '2026-09-24',
                dropped: [{ symbol: 'CCC', close: 10, rs_percentile: 60, industry: 'Steel' }],
              },
            }),
          );
        if (url.pathname === '/api/v2/screener/debug')
          return json(
            env(
              [
                { kind: 'floor', label: 'market_cap_cr >= 1000', passed: true, actual: null },
                {
                  kind: 'rule',
                  label: 'Strength rank >= 70',
                  field: 'rs_percentile',
                  op: 'gte',
                  value: 70,
                  actual: null,
                  passed: false,
                  missing_input: true,
                },
              ],
              { context: { passes_all: false } },
            ),
          );
        return new Response('', { status: 404 });
      }),
    );
    const router = createMemoryRouter(routes, { initialEntries: ['/screener?as_of=2026-09-25'] });
    render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);

    expect(await screen.findByRole('tab', { name: 'Minervini 8/8' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByRole('button', { name: 'Strength rank ≥ 70' })).toBeInTheDocument();
    expect(await screen.findByText('AAA')).toBeInTheDocument();
    expect(screen.getByText('matches', { exact: false })).toHaveTextContent('2 matches');
    expect(screen.getByText('1 new')).toBeInTheDocument();
    await waitFor(() =>
      expect(
        calls.some((c) => c.startsWith('/api/v2/screener/run?') && c.includes('preset=minervini_8of8') && c.includes('as_of=2026-09-25')),
      ).toBe(true),
    );
    expect(calls.some((c) => c.startsWith('/api/v2/screener/run?') && c.includes('rules='))).toBe(false);

    fireEvent.click(screen.getByText('1 dropped'));
    expect(await screen.findByText('CCC')).toBeInTheDocument();

    // Debugger: why is ZZZ not in the list?
    fireEvent.click(screen.getByRole('button', { name: /Why not\?/ }));
    const input = await screen.findByRole('textbox', { name: 'Symbol to check' });
    fireEvent.change(input, { target: { value: 'zzz' } });
    fireEvent.click(screen.getByRole('button', { name: /Check/ }));
    expect(await screen.findByText(/ZZZ fails 1 check/)).toBeInTheDocument();
    const table = screen.getByRole('table');
    expect(within(table).getByText('missing')).toBeInTheDocument();
    expect(within(table).getByText('no data → fails (fail-closed)')).toBeInTheDocument();

    // Removing a rule chip makes it a custom run with explicit rules.
    fireEvent.click(screen.getByRole('button', { name: 'Remove rule Strength rank ≥ 70' }));
    await waitFor(() => expect(calls.some((c) => c.startsWith('/api/v2/screener/run?') && c.includes('rules='))).toBe(true));
    expect(screen.getByText('Custom')).toBeInTheDocument();
  }, 30_000);
});
