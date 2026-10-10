/**
 * Chart v2 component against a fixture API (the canvas engine is mocked): divergences from the
 * served contract, the client fallback when the endpoint is missing, Clean / Info, the candle story,
 * bar replay and compare.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import parity from './__fixtures__/divergenceParity.json';
import { ChartV2 } from './ChartV2';
import { resetChartPrefsCache } from '../lib/chartPrefs';
import { resetChartSettingsCache } from './chartSettings';
import { detectDivergences } from './divergence';
import { resetDrawingsCache } from './drawings';

vi.mock('./ChartEngine', () => ({
  canvasSupported: () => false,
  ChartEngine: (p: {
    label: string;
    bars: { time: string; close: number }[];
    segments?: { id: string }[];
    lines?: { id: string }[];
    percent?: boolean;
    onClick?: (pt: { index: number; time: string; price: number; pane: number; x: number; y: number }) => void;
    children?: React.ReactNode;
  }) => {
    const n = p.bars.length;
    const last = p.bars[n - 1];
    return (
      <div
        role="img"
        aria-label={p.label}
        data-bars={n}
        data-segments={(p.segments ?? []).map((s) => s.id).join('|')}
        data-lines={(p.lines ?? []).map((l) => l.id).join(',')}
        data-percent={p.percent ? '1' : '0'}
      >
        <button type="button" onClick={() => p.onClick?.({ index: n - 1, time: last.time, price: last.close, pane: 0, x: 10, y: 10 })}>
          engine-click-last
        </button>
        <button
          type="button"
          onClick={() => p.onClick?.({ index: 250, time: p.bars[250]?.time ?? last.time, price: last.close, pane: 0, x: 10, y: 10 })}
        >
          engine-click-250
        </button>
        {p.children}
      </div>
    );
  },
}));

const fx = (parity as unknown as Record<string, { bars: { time: string; high: number; low: number; close: number }[] }>).IDEAFORGE;
const bars = fx.bars.map((b) => ({
  trade_date: b.time,
  open: b.close,
  high: b.high,
  low: b.low,
  close: b.close,
  volume: 1000,
  delivery_pct: 40,
}));
const FRESH = { status: 'fresh', latest_session: '2026-08-13', expected_session: '2026-08-13', sessions_behind: 0, history_mode: false };
const envelope = (rows: unknown[]) => ({
  as_of: '2026-08-13',
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', offset: 0, limit: 500 },
});
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function mockApi(divergences: unknown[] | null) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
    const p = url.pathname;
    if (/\/stock\/[A-Z]+\/bars$/.test(p))
      return json(envelope(p.includes('/HAL/') ? bars.map((b) => ({ ...b, close: b.close * 5 })) : bars));
    if (p.endsWith('/divergences')) return divergences ? json(envelope(divergences)) : json({ detail: 'Not Found' }, 404);
    if (p.startsWith('/api/v2/')) return json(envelope([]));
    return new Response('', { status: 404 });
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

function renderChart() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <ChartV2 symbol="IDEAFORGE" />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  resetChartSettingsCache();
  resetChartPrefsCache();
  resetDrawingsCache();
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('Chart v2', () => {
  it('draws the served divergences (contract rows) on both panes', async () => {
    mockApi([
      {
        side: 'bear',
        type: 'Strong',
        p1_date: '2026-05-06',
        p2_date: '2026-05-15',
        p1_price: 900,
        p2_price: 950,
        p1_rsi: 80,
        p2_rsi: 70,
        confirm_date: '2026-05-20',
        trigger_price: 720,
        stop_price: 960,
        status: 'triggered',
      },
    ]);
    renderChart();
    const chart = await screen.findByRole('img', { name: 'IDEAFORGE daily chart' }, { timeout: 5000 });
    await waitFor(() =>
      expect(chart.getAttribute('data-segments')).toBe('div-bear-2026-05-06-2026-05-15-r|div-bear-2026-05-06-2026-05-15-p'),
    );
  });

  it('falls back to the client rules when the endpoint is missing', async () => {
    mockApi(null);
    renderChart();
    const chart = await screen.findByRole('img', { name: 'IDEAFORGE daily chart' }, { timeout: 5000 });
    const want = detectDivergences(fx.bars).filter((d) => d.type !== 'Hidden').length;
    expect(want).toBeGreaterThan(0);
    await waitFor(() => expect(chart.getAttribute('data-segments')!.split('|').filter(Boolean)).toHaveLength(want * 2));
  });

  it('Info adds the chips, The read and Key levels; a click opens the candle story', async () => {
    mockApi([]);
    renderChart();
    await screen.findByRole('img', { name: 'IDEAFORGE daily chart' }, { timeout: 5000 });
    expect(screen.queryByRole('region', { name: 'The read' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Info' }));
    const read = await screen.findByRole('region', { name: 'The read' });
    expect(read).toHaveTextContent('What to do:');
    expect(screen.getByLabelText('Stats')).toHaveTextContent('RSI');
    fireEvent.click(screen.getByRole('button', { name: 'engine-click-last' }));
    const story = await screen.findByRole('dialog', { name: /Candle story 2026-08-13/ });
    expect(within(story).getByText(/^C /)).toBeInTheDocument();
    // Global: the mode is stored for every chart.
    expect(JSON.parse(localStorage.getItem('mp.chartv2.v1')!)).toMatchObject({ mode: 'info' });
  });

  it('bar replay: pick a bar, step forward, exit', async () => {
    mockApi([]);
    renderChart();
    const chart = await screen.findByRole('img', { name: 'IDEAFORGE daily chart' }, { timeout: 5000 });
    expect(chart.getAttribute('data-bars')).toBe(String(bars.length));
    fireEvent.click(screen.getByRole('button', { name: 'Replay' }));
    fireEvent.click(screen.getByRole('button', { name: 'engine-click-250' }));
    await waitFor(() => expect(screen.getByRole('img', { name: 'IDEAFORGE daily chart' }).getAttribute('data-bars')).toBe('251'));
    fireEvent.click(screen.getByRole('button', { name: 'Step forward' }));
    await waitFor(() => expect(screen.getByRole('img', { name: 'IDEAFORGE daily chart' }).getAttribute('data-bars')).toBe('252'));
    fireEvent.click(screen.getByRole('button', { name: 'Exit replay' }));
    await waitFor(() =>
      expect(screen.getByRole('img', { name: 'IDEAFORGE daily chart' }).getAttribute('data-bars')).toBe(String(bars.length)),
    );
  });

  it('compare overlays a second symbol on a % scale', async () => {
    mockApi([]);
    renderChart();
    await screen.findByRole('img', { name: 'IDEAFORGE daily chart' }, { timeout: 5000 });
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }));
    fireEvent.change(screen.getByLabelText('Compare symbol'), { target: { value: 'nse:hal' } });
    fireEvent.submit(screen.getByLabelText('Compare symbol').closest('form')!);
    await waitFor(() => {
      const c = screen.getByRole('img', { name: 'IDEAFORGE daily chart' });
      expect(c.getAttribute('data-lines')).toContain('cmp-HAL');
      expect(c.getAttribute('data-percent')).toBe('1');
    });
  });
});
