/** Setups · Divergences view against a fixture API: filters hit the endpoint, row click opens the drawer symbol. */
import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../../App';
import { routes } from '../../routes';

vi.mock('../../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));
const copied: string[] = [];
vi.mock('../../lib/clipboard', () => ({ copyText: async (t: string) => (copied.push(t), true) }));

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

const div = (symbol: string, side: string, type: string, extra: Record<string, unknown> = {}) => ({
  symbol,
  name: `${symbol} Ltd`,
  side,
  type,
  tf: 'D',
  industry: 'Steel',
  group: 'Steel',
  group_state: 'Favour',
  group_reason: 'Trending',
  market_cap_cr: 5000,
  p1_date: '2026-07-01',
  p2_date: '2026-08-07',
  p1_price: 100,
  p2_price: 95,
  p1_rsi: 31,
  p2_rsi: 37,
  confirm_date: '2026-08-12',
  trigger_price: 110,
  stop_price: 95,
  status: 'watching',
  status_date: null,
  bars_apart: 26,
  bars_since_confirm: 1,
  close: 100,
  distance_to_trigger_pct: 10,
  risk_pct: 5,
  rsi: 41.2,
  ...extra,
});

afterEach(() => vi.unstubAllGlobals());

describe('DivergencesView', () => {
  it('lists divergences, filters by side / type / tf and copies for TradingView', async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
        calls.push(url.pathname + url.search);
        if (url.pathname === '/api/v2/setups/divergences') {
          const side = url.searchParams.get('side');
          const all = [div('AAA', 'bull', 'Strong'), div('BBB', 'bear', 'Hidden', { status: 'triggered', status_date: '2026-08-13' })];
          return json(env(side ? all.filter((r) => r.side === side) : all, { context: { counts: { 'bull:Strong': 1, 'bear:Hidden': 1 }, universe: 2 } }));
        }
        if (url.pathname === '/api/v2/setups/board') return json(env([]));
        return new Response('', { status: 404 });
      }),
    );
    const router = createMemoryRouter(routes, { initialEntries: ['/screener?as_of=2026-08-13&sv=div'] });
    render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);

    expect(await screen.findByRole('tab', { name: 'Divergences', selected: true })).toBeInTheDocument();
    expect(await screen.findByText('AAA')).toBeInTheDocument();
    expect(screen.getByText('BBB')).toBeInTheDocument();
    expect(screen.getByText('triggered')).toBeInTheDocument();
    expect(calls.some((c) => c.startsWith('/api/v2/setups/divergences?') && c.includes('tf=D') && c.includes('window=5'))).toBe(true);

    fireEvent.click(screen.getByRole('radio', { name: 'Bullish' }));
    await waitFor(() => expect(screen.queryByText('BBB')).not.toBeInTheDocument());
    expect(calls.some((c) => c.includes('side=bull'))).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: /Strong/ }));
    await waitFor(() => expect(calls.some((c) => c.includes('types=Strong'))).toBe(true));

    fireEvent.click(screen.getByRole('radio', { name: 'Weekly' }));
    await waitFor(() => expect(calls.some((c) => c.includes('tf=W'))).toBe(true));

    fireEvent.click(screen.getByTitle(/one section per side/));
    await waitFor(() => expect(copied.length).toBe(1));
    expect(copied[0]).toContain('###RSI div Bull Strong W,NSE:AAA');
    expect(await screen.findByText('Copied 1 symbols')).toBeInTheDocument();

    // Row click opens the chart drawer (sidecar symbol).
    fireEvent.click(screen.getAllByText('Steel')[0]);
    await waitFor(() => expect(new URLSearchParams(router.state.location.search).get('sym')).toBe('AAA'));
  }, 30_000);
});
