/**
 * Smoke render of the Charts tab (09-tab-charts round 1) against a fixture API: main chart +
 * list rail, J / K through the list, deal candle colour reaching the chart, Stock 360 side panel.
 */
import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { routes } from '../routes';
import { resetChartSettingsCache } from './chartSettings';

vi.mock('../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));
// lightweight-charts needs a canvas: expose the props Chart v2 hands its engine instead.
vi.mock('./ChartEngine', () => ({
  canvasSupported: () => false,
  ChartEngine: (p: {
    label: string;
    candleColors?: Map<number, string>;
    rsi?: unknown;
    lines?: { id: string }[];
    tags?: { id: string; title: string }[];
    children?: unknown;
  }) => (
    <div
      role="img"
      aria-label={p.label}
      data-candles={JSON.stringify([...(p.candleColors?.values() ?? [])])}
      data-rsi={p.rsi ? '1' : '0'}
      data-lines={(p.lines ?? []).map((l) => l.id).join(',')}
      data-tags={(p.tags ?? []).map((t) => `${t.id}:${t.title}`).join('|')}
    />
  ),
}));
// The grid tiles still use ui/Chart.
vi.mock('../ui/Chart', () => ({ Chart: (p: { label: string }) => <div role="img" aria-label={p.label} /> }));

const FRESH = { status: 'fresh', latest_session: '2026-09-25', expected_session: '2026-09-25', sessions_behind: 0, history_mode: false };
const envelope = (rows: unknown[]) => ({ as_of: '2026-09-25', freshness: FRESH, total: rows.length, returned: rows.length, rows, meta: { status: 'ok', offset: 0, limit: 500 } });
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });

const dates = Array.from({ length: 60 }, (_, i) => {
  const d = new Date(Date.UTC(2026, 6, 1 + i));
  return d.toISOString().slice(0, 10);
});
const bars = dates.map((t, i) => ({ trade_date: t, open: 100 + i, high: 101 + i, low: 99 + i, close: 100 + i, volume: 1000, delivery_pct: 50 }));

function mockApi() {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
    const p = url.pathname;
    if (p === '/api/v2/health') return json({ status: 'healthy', version: '2', build: 't', freshness: FRESH, checks: [] });
    if (/\/stock\/[A-Z]+\/bars$/.test(p)) return json(envelope(bars));
    if (p === '/api/v2/charts/AAA/deal-candles')
      return json(
        envelope([
          { trade_date: dates[50], letter: 'B', kind: 'buy', net_cr: 25, deal_price: 140, deal_price_adj: 140, top_buyer: 'GOOD FUND', top_buyer_class: 'FII', show_line: true, status: 'holding' },
        ]),
      );
    if (p.startsWith('/api/v2/')) return json(envelope([]));
    return new Response('', { status: 404 });
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('Charts tab', () => {
  beforeAll(() => document.documentElement.style.setProperty('--c-ev-buy', '20 184 166'));
  it('main chart + list rail; J moves through the list; deal candle colour and RSI reach the chart; I opens Stock 360', async () => {
    mockApi();
    localStorage.setItem('mp.chartv2.v1', JSON.stringify({ mode: 'info', colours: 'events', tf: 'D' }));
    resetChartSettingsCache();
    const router = createMemoryRouter(routes, { initialEntries: ['/charts?src=list&syms=AAA,BBB'] });
    render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);

    const chart = await screen.findByRole('img', { name: 'AAA daily chart' }, { timeout: 8000 });
    expect(screen.getByRole('listbox', { name: /Symbols/ })).toBeInTheDocument();
    await waitFor(() => expect(chart.getAttribute('data-candles')).toContain('rgba(20, 184, 166, 1)'), { timeout: 5000 });
    expect(chart.getAttribute('data-rsi')).toBe('1');
    expect(chart.getAttribute('data-lines')).toBe('ema10,ema20,ema200');
    // Info mode: the deal price gets a right-axis tag.
    expect(chart.getAttribute('data-tags')).toContain('deal-50-B:Deal');
    // The read (rule-generated) and the key levels sit under the chart.
    expect(screen.getByRole('region', { name: 'The read' })).toHaveTextContent('What to do:');
    expect(screen.getByRole('region', { name: 'Key levels' })).toHaveTextContent('EMA 20');

    fireEvent.keyDown(window, { key: 'j' });
    expect(await screen.findByRole('img', { name: 'BBB daily chart' })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'k' });
    expect(await screen.findByRole('img', { name: 'AAA daily chart' })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'i' });
    expect(await screen.findByLabelText('Stock 360: AAA')).toBeInTheDocument();

    // Layout 4 switches to the grid.
    fireEvent.click(screen.getByRole('button', { name: '4' }));
    await waitFor(() => expect(screen.queryByRole('listbox', { name: /Symbols/ })).toBeNull());
  }, 20000);
});
