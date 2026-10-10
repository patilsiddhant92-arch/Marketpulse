import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { routes } from '../routes';
import { DealBadge, DealIcon } from '../ui/DealIcon';
import { dealFlagMap, dealTitle, dealTone, type DealFlag } from './dealFlags';

vi.mock('../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));

const flag = (symbol: string, extra: Partial<DealFlag> = {}): DealFlag => ({
  symbol,
  has_recent_deal: true,
  last_deal_date: '2026-08-11',
  deal_sessions_ago: 2,
  side: 'B',
  event_type: 'accumulate',
  deal_sessions_in_window: 1,
  verdict: 'confirm',
  verdict_title: 'Fund bought, stock held',
  deal_price: 101.5,
  status: 'holding',
  vs_deal_pct: 3.2,
  ...extra,
});
const FRESH = { status: 'fresh', latest_session: '2026-08-13', expected_session: '2026-08-13', sessions_behind: 0, history_mode: false };
const env = (rows: unknown[]) => ({
  as_of: '2026-08-13',
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', reason: null, offset: 0, limit: 5000, sources: [], notes: [], metric_keys: [], context: {} },
});
const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });

afterEach(() => vi.unstubAllGlobals());

describe('deal flags (pure)', () => {
  it('keys by symbol, colours by verdict then side, and tells the story', () => {
    const m = dealFlagMap([flag('aaa'), flag('BBB', { has_recent_deal: false })]);
    expect([...m.keys()]).toEqual(['AAA']);
    expect(dealTone(flag('A'))).toBe('positive');
    expect(dealTone(flag('A', { verdict: 'avoid' }))).toBe('negative');
    expect(dealTone(flag('A', { verdict: null, side: 'S' }))).toBe('negative');
    expect(dealTone(flag('A', { verdict: null, side: 'P' }))).toBe('info');
    const t = dealTitle(flag('A'));
    expect(t).toContain('Deal 2 deal sessions ago (2026-08-11): net buy');
    expect(t).toContain('Fund bought, stock held');
    expect(t).toContain('deal price ₹101.50, now +3.2%');
    expect(dealTitle(flag('A', { deal_sessions_ago: 0, verdict_title: null, deal_price: null, status: null }))).toBe('Deal today (2026-08-11): net buy. Click for the Deals drawer.');
  });

  it('renders nothing without a recent deal', () => {
    const { container } = render(<DealBadge flag={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('DealIcon', () => {
  it('fetches /deals/flags once per as_of for every icon and opens the Deals drawer on click', async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/v2/deals/flags') return json(env([flag('AAA'), flag('CCC', { verdict: 'avoid' })]));
      return new Response('', { status: 404 });
    });
    vi.stubGlobal('fetch', fetchFn);
    function Where() {
      const loc = useLocation();
      return <div data-testid="where">{loc.pathname + loc.search}</div>;
    }
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/x?as_of=2026-08-13']}>
          <Routes>
            <Route
              path="*"
              element={
                <>
                  <DealIcon symbol="AAA" />
                  <DealIcon symbol="BBB" />
                  <DealIcon symbol="ccc" />
                  <Where />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const icons = await screen.findAllByTestId('deal-icon');
    expect(icons).toHaveLength(2);
    expect(icons[0]).toHaveAttribute('data-tone', 'positive');
    expect(icons[1]).toHaveAttribute('data-tone', 'negative');
    expect(fetchFn.mock.calls.filter(([u]) => String(u).includes('/deals/flags')).length).toBe(1);
    expect(String(fetchFn.mock.calls[0][0])).toContain('as_of=2026-08-13');
    fireEvent.click(icons[0]);
    expect(screen.getByTestId('where')).toHaveTextContent('/deals?sym=AAA&as_of=2026-08-13');
  });

  it('shows on a tab stock list (Setups board)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
        if (url.pathname === '/api/v2/deals/flags') return json(env([flag('AAA')]));
        if (url.pathname === '/api/v2/setups/board')
          return json(
            env(
              ['AAA', 'BBB'].map((symbol) => ({
                symbol,
                industry: 'Steel',
                tags: ['VCP'],
                screeners: ['vcp'],
                status: 'active',
                group_state: 'Neutral',
                group_reason: 'x',
                delivery_streak: 0,
                delivery_5d: [],
                blue_sky: false,
                breakouts_held_6m: 0,
                breakouts_failed_6m: 0,
                chips: [],
                results_soon: false,
              })),
            ),
          );
        return new Response('', { status: 404 });
      }),
    );
    const router = createMemoryRouter(routes, { initialEntries: ['/screener?as_of=2026-08-13'] });
    render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    expect(await screen.findByText('BBB')).toBeInTheDocument();
    const grid = screen.getAllByRole('grid')[0];
    await waitFor(() => expect(within(grid).getAllByTestId('deal-icon')).toHaveLength(1));
    expect(within(grid).getByTestId('deal-icon')).toHaveAttribute('title', expect.stringContaining('net buy'));
  }, 30_000);
});
