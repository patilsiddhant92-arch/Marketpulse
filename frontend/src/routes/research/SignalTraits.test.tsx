/** Research: the Signal log view (log-and-grade scorecard) and the Case study D/W/M trait strip. */
import { QueryClient } from '@tanstack/react-query';
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { App } from '../../App';
import { routes } from '..';
import { recentMonths, type MonthRow } from './SignalLogView';
import { groupTraits, type TraitStripRow } from './TraitStrip';

vi.mock('../../components/MarketBreadthDrawer', () => ({ MarketBreadthDrawer: () => null }));
vi.mock('./CaseChart', () => ({ CaseChart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }));

const FRESH = { status: 'fresh', latest_session: '2026-08-13', expected_session: '2026-08-13', sessions_behind: 0, history_mode: false };
const CAVEAT = 'Retrospective research, not advice. These studies use the local archive.';
const env = (rows: unknown[], context: Record<string, unknown> = {}) => ({
  as_of: '2026-08-13',
  freshness: FRESH,
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', reason: null, offset: 0, limit: 500, sources: ['research_signal_log'], notes: [], metric_keys: [], context: { caveat: CAVEAT, ...context } },
});
const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { 'Content-Type': 'application/json' } });

const score = (setup: string, label: string, over: Record<string, unknown> = {}) => ({
  setup, setup_label: label, queue: setup.split(':')[0], signals: 100, graded_20: 90, hit_20_pct: 44, avg_excess_5: -0.1, avg_excess_10: -0.2,
  avg_excess_20: -0.5, avg_ret_20: 0.1, avg_r_20: -0.13, stopped_20_pct: 70, triggered_20_pct: 80, live: 4, first_signal: '2024-05-17',
  last_signal: '2026-08-13', recent_months: ['2026-05', '2026-06', '2026-07'], recent_hit_20_pct: 40, recent_avg_excess_20: -1.2, not_working: false, ...over,
});
const month = (setup: string, m: string, ex: number): MonthRow => ({ setup, setup_label: setup, month: m, signals: 10, graded_20: 9, hit_20_pct: 40, avg_excess_20: ex, avg_r_20: 0.1 });
const SCORE = [score('darvas_squeeze', 'Darvas squeeze'), score('vcp', 'VCP', { not_working: true, avg_excess_20: -0.8, avg_r_20: 0.25 })];
const MONTHLY = [month('darvas_squeeze', '2026-06', 1.2), month('darvas_squeeze', '2026-07', -0.4), month('vcp', '2026-06', -2.3), month('vcp', '2026-07', -2.7)];
const LOG = [
  { setup_id: 'vcp:AARTIIND:20260813', trade_date: '2026-08-13', setup: 'vcp', setup_label: 'VCP', queue: 'vcp', flavor: null, symbol: 'AARTIIND', signal_close: 478, trigger_price: 494, stop_price: 454, risk_pct: 5, rs_percentile: 75, logged: 'live', excess_5: null, excess_20: null, r_20: null, stopped_20: null, grade_note: null },
  { setup_id: 'vcp:DEEPAKFERT:20260630', trade_date: '2026-06-30', setup: 'vcp', setup_label: 'VCP', queue: 'vcp', flavor: null, symbol: 'DEEPAKFERT', signal_close: 1558, trigger_price: 1593, stop_price: 1512, risk_pct: 3, rs_percentile: 90, logged: 'backfill', excess_5: 1.5, excess_20: 2.4, r_20: 1.1, stopped_20: false, grade_note: null },
];
const trait = (k: string, label: string, group: string, on: (boolean | null)[], score_trait = false): TraitStripRow => ({
  trait: k, label, group, group_label: group, better_when: 'high', cut: 1, lift: 1.5, score_trait, values: on.map((o) => (o == null ? null : o ? 2 : 0)), on,
  on_at_lift: on[on.length - 1] ?? null, weeks_on: on.slice(0, -1).filter(Boolean).length, weeks_known: on.slice(0, -1).filter((o) => o != null).length,
  runner_median: 1, fizzle_median: 0,
});
const TRAITS = [
  trait('w_rsi', 'weekly RSI', 'W', [false, true, true]),
  trait('d_rsi14', 'RSI 14', 'D', [null, false, true], true),
  trait('m_rsi', 'monthly RSI', 'M', [true, true, true]),
];
const TRAIT_CTX = {
  symbol: 'MTARTECH',
  lift: { date: '2025-09-12', close: 1678.5, found: true, why: "first close 20% above the move's low", family: 'trend', family_label: 'Trend lifts' },
  columns: [{ date: '2025-08-29', label: '-2w' }, { date: '2025-09-05', label: '-1w' }, { date: '2025-09-12', label: 'lift' }],
  groups: [{ group: 'D', label: 'Daily', traits: 1, on: [0, 0, 1] }, { group: 'W', label: 'Weekly', traits: 1, on: [0, 1, 1] }, { group: 'M', label: 'Monthly', traits: 1, on: [1, 1, 1] }],
  score: [0, 0, 1], score_max: 8, family_base_runner_pct: 14.1, family_events: 255,
  summary: ['MTARTECH made a trend lift on 12 Sep 2025 at 1,678.5.'], definition: 'A trait is on when its value sits in the better third.', in_sample_note: 'Partly in-sample.',
};

function mockFetch() {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost');
    const p = decodeURIComponent(url.pathname);
    if (p === '/api/v2/research/signal-scorecard') return json(env(SCORE, { monthly: MONTHLY, summary: ['2 setups logged.'], definition: 'A signal is a setup’s first day.', not_working_rule: 'Lagged 3 months.' }));
    if (p === '/api/v2/research/signal-log') {
      const setup = url.searchParams.get('setup');
      return json(env(setup && setup !== 'vcp' ? [] : LOG, { days: Number(url.searchParams.get('days')) }));
    }
    if (p === '/api/v2/research/case-study/MTARTECH/traits') return json(env(TRAITS, TRAIT_CTX));
    if (p === '/api/v2/research/case-study/MTARTECH') return json(env([], { symbol: 'MTARTECH', summary: [], presets: [], fires: [], first_fires: [], ladder: { legs: [] } }));
    if (p === '/api/v2/research/case-study') return json(env([{ symbol: 'MTARTECH', gain_pct: 500 }]));
    return new Response('', { status: 404 });
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<App router={router} queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
}

configure({ asyncUtilTimeout: 5000 });
beforeAll(async () => {
  await import('../ResearchRoute');
});
afterEach(() => vi.unstubAllGlobals());

describe('pure helpers', () => {
  it('groupTraits orders D, W, M, A, I, B', () => {
    expect(groupTraits(TRAITS).map((g) => g.group)).toEqual(['D', 'W', 'M']);
  });
  it('recentMonths keeps one setup, oldest first, capped', () => {
    expect(recentMonths(MONTHLY, 'vcp').map((m) => m.month)).toEqual(['2026-06', '2026-07']);
    expect(recentMonths(MONTHLY, 'vcp', 1).map((m) => m.month)).toEqual(['2026-07']);
  });
});

describe('Research: signal log', () => {
  it('scorecard with the not-working chip, months per setup and the log', async () => {
    const fetchFn = mockFetch();
    renderApp('/research?rview=signals');
    const table = await screen.findByRole('table', { name: 'Signal scorecard' });
    expect(within(table).getAllByRole('row')).toHaveLength(3);
    const vcp = within(table).getAllByRole('row').find((r) => r.textContent?.includes('VCP'))!;
    expect(vcp).toHaveTextContent('not working now');
    expect(vcp).toHaveTextContent('+0.25R');
    expect(screen.getAllByText(/not advice/).length).toBeGreaterThan(0);
    // months follow the picked setup
    const months = screen.getByRole('table', { name: 'Signal scorecard by month' });
    expect(within(months).getAllByRole('row')).toHaveLength(3);
    fireEvent.click(within(vcp).getByRole('button', { name: /VCP/ }));
    await waitFor(() => expect(within(screen.getByRole('table', { name: 'Signal scorecard by month' })).getByText('-2.7%')).toBeInTheDocument());
    expect(await screen.findByRole('grid', { name: 'Signal log' })).toBeInTheDocument();
    expect(await screen.findByText('DEEPAKFERT')).toBeInTheDocument();
    await waitFor(() => expect(fetchFn.mock.calls.some((c) => String(c[0]).includes('/api/v2/research/signal-log?') && String(c[0]).includes('days=30'))).toBe(true));
    fireEvent.click(screen.getByRole('radio', { name: 'VCP' }));
    await waitFor(() => expect(fetchFn.mock.calls.some((c) => String(c[0]).includes('setup=vcp'))).toBe(true));
  });
});

describe('Research: case study trait strip', () => {
  it('draws one square per weekly checkpoint, grouped D/W/M', async () => {
    mockFetch();
    renderApp('/research?rview=case&case=MTARTECH');
    const table = await screen.findByRole('table', { name: 'Trait strip' });
    expect(within(table).getByText('Daily')).toBeInTheDocument();
    expect(within(table).getByText('Weekly')).toBeInTheDocument();
    expect(within(table).getByText('lift')).toBeInTheDocument();
    expect(table.querySelectorAll('[data-on="on"]').length).toBe(6);
    expect(table.querySelectorAll('[data-on="na"]').length).toBe(1);
    expect(screen.getByText(/Trend lifts · lift/)).toBeInTheDocument();
    expect(screen.getByText('MTARTECH made a trend lift on 12 Sep 2025 at 1,678.5.')).toBeInTheDocument();
  });
});
