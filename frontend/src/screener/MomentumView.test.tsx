/** Screener → Momentum (default mode): parity controls, bucket grouping, leaders, copy buttons. */
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

const row = (symbol: string, bucket: string, away: number, sector: string, industry: string, extra: Record<string, unknown> = {}) => ({
  symbol,
  bucket,
  away_10ema_pct: away,
  sector,
  industry,
  close: 100,
  change_1d_pct: 1,
  rs_percentile: 90,
  trigger_date: '2026-09-20',
  is_new: false,
  bullish_stack: true,
  delivery_spike: false,
  coiling: false,
  ...extra,
});
const rows = [
  row('AAA', '0_2%', 1.2, 'Healthcare', 'Pharma', { is_new: true }),
  row('B-B', '0_2%', 1.9, 'Healthcare', 'Pharma'),
  row('CCC', '2_5%', 3.1, 'Capital Goods', 'Heavy Electrical', { rs_percentile: null }),
];
const leader = (sector: string, industry: string | undefined, syms: string[]) => ({
  sector,
  ...(industry ? { industry } : {}),
  stock_count: syms.length,
  avg_rs: 90,
  symbols: syms,
  tv_str: syms.map((s) => `NSE:${s.replace('-', '_')}`).join(','),
  new_count: 0,
  group: null,
});
const context = {
  is_default: true,
  buckets_tv: '###0_2%,NSE:AAA,NSE:B_B,###2_5%,NSE:CCC',
  buckets: [
    { bucket: '0_2%', count: 2, symbols: ['AAA', 'B-B'], tv_str: 'NSE:AAA,NSE:B_B', new_count: 1 },
    { bucket: '2_5%', count: 1, symbols: ['CCC'], tv_str: 'NSE:CCC', new_count: 0 },
  ],
  top_sectors: [leader('Healthcare', undefined, ['AAA', 'B-B']), leader('Capital Goods', undefined, ['CCC'])],
  top_industries: [leader('Healthcare', 'Pharma', ['AAA', 'B-B']), leader('Capital Goods', 'Heavy Electrical', ['CCC'])],
  sector_distribution: [leader('Healthcare', undefined, ['AAA', 'B-B']), leader('Capital Goods', undefined, ['CCC'])],
  previous_session: '2026-09-24',
  new_count: 1,
  dropped: [{ symbol: 'DDD', bucket: '5_10%', industry: 'Steel', close: 10, rs_percentile: 70 }],
  debug: null,
};

afterEach(() => vi.unstubAllGlobals());

describe('Screener → Momentum', () => {
  it('is the default mode with the old defaults, buckets, leaders and TradingView copy', async () => {
    const calls: string[] = [];
    const copied: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
        calls.push(url.pathname + url.search);
        if (url.pathname === '/api/v2/screener/momentum') return json(env(rows, { context }));
        if (url.pathname === '/api/v2/screener/momentum/evidence')
          return json(env([{ bucket: '0_2%', n_5: 100, n_10: 100, n_20: 90, avg_20: 2.3, hit_rate_20: 52.8, insufficient_sample: false }]));
        return new Response('', { status: 404 });
      }),
    );
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: async (t: string) => void copied.push(t) },
      configurable: true,
    });
    const router = createMemoryRouter(routes, { initialEntries: ['/screener?as_of=2026-09-25'] });
    render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);

    expect(await screen.findByRole('tab', { name: 'Momentum' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('AAA')).toBeInTheDocument();
    // Old defaults sent as-is.
    const q = calls.find((c) => c.startsWith('/api/v2/screener/momentum?'))!;
    for (const part of [
      'lookback_days=20',
      'min_mcap_cr=1000',
      'min_volume=1000000',
      'min_avg_volume_20d=0',
      'max_52w_away_pct=25',
      'min_52w_low_pct=50',
      'cmp_gt_10=true',
      'cmp_gt_200=true',
      'ema10_gt_20=true',
      'ema100_gt_200=true',
      'sma50_gt_150=false',
      'as_of=2026-09-25',
    ])
      expect(q).toContain(part);

    // Bucket group headers with counts; evidence line in the header.
    const table = screen.getByRole('grid');
    const headers = table.querySelectorAll('tr[data-group]');
    expect([...headers].map((h) => h.getAttribute('data-group'))).toEqual(['0_2%', '2_5%']);
    expect(within(headers[0] as HTMLElement).getByText('2')).toBeInTheDocument();
    expect(within(headers[0] as HTMLElement).getByText(/past hits: 20D \+2\.3% avg/)).toBeInTheDocument();
    const charts = within(headers[0] as HTMLElement).getByRole('link', { name: /Charts/ });
    expect(charts.getAttribute('href')).toBe('/charts?source=momentum%3A0_2%25&syms=AAA%2CB-B&as_of=2026-09-25');

    // Leaders panel.
    expect(screen.getByText('Sec #1')).toBeInTheDocument();
    expect(screen.getByText('Ind #1')).toBeInTheDocument();

    // Copy Buckets pastes the ###bucket sections verbatim.
    fireEvent.click(screen.getByRole('button', { name: /Copy Buckets/ }));
    await waitFor(() => expect(copied).toContain('###0_2%,NSE:AAA,NSE:B_B,###2_5%,NSE:CCC'));
    fireEvent.click(screen.getByRole('button', { name: /Copy All to TV/ }));
    await waitFor(() => expect(copied).toContain('NSE:AAA,NSE:B_B,NSE:CCC'));
    fireEvent.click(screen.getByRole('button', { name: /Copy Top Sectors/ }));
    await waitFor(() => expect(copied).toContain('NSE:AAA,NSE:B_B,NSE:CCC'));

    // Preset button: SMA template turns the EMA stack off and the SMA template on.
    fireEvent.click(screen.getByRole('button', { name: 'SMA Template' }));
    await waitFor(() => expect(calls.some((c) => c.includes('sma50_gt_150=true') && c.includes('ema10_gt_20=false'))).toBe(true));

    // Sector quick filter narrows the table.
    fireEvent.click(within(await screen.findByRole('group', { name: 'Filter sector' })).getByRole('button', { name: /Capital Goods/ }));
    await waitFor(() => expect(screen.queryByText('AAA')).not.toBeInTheDocument());
    expect(screen.getByText('CCC')).toBeInTheDocument();

    // Presets mode is one click away.
    fireEvent.click(screen.getByRole('tab', { name: 'Presets' }));
    expect(await screen.findByRole('tab', { name: 'Presets' })).toHaveAttribute('aria-selected', 'true');
  }, 30_000);
});
