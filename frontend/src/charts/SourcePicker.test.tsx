import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SourcePicker } from './SourcePicker';

const env = (rows: unknown[]) => ({
  as_of: '2026-08-13',
  freshness: { status: 'fresh', latest_session: '2026-08-13', expected_session: '2026-08-13', sessions_behind: 0, history_mode: false },
  total: rows.length,
  returned: rows.length,
  rows,
  meta: { status: 'ok', reason: null, offset: 0, limit: 500, sources: [], notes: [], metric_keys: [], context: {} },
});

afterEach(() => vi.unstubAllGlobals());

describe('Charts source picker', () => {
  it('offers Pulse movers, Setups views and the Deals views incl. one house; no Pre-move watch', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost');
        if (url.pathname === '/api/v2/deals/tab/houses')
          return new Response(JSON.stringify(env([{ house: 'SOCIETE GENERALE', symbols: ['A', 'B'] }])), { status: 200, headers: { 'Content-Type': 'application/json' } });
        return new Response('', { status: 404 });
      }),
    );
    const onChange = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/charts?as_of=2026-08-13']}>
          <SourcePicker value="queue:all" label="Desk · all queues" count={3} watchCount={0} onChange={onChange} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: /Source/ }));
    expect(screen.queryByRole('button', { name: 'Research' })).not.toBeInTheDocument();
    expect(screen.queryByText('Pre-move watch')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Pulse movers' }));
    fireEvent.click(screen.getByRole('button', { name: /Volume surge/ }));
    expect(onChange).toHaveBeenLastCalledWith('pulse:rvol');

    fireEvent.click(screen.getByRole('button', { name: /Source/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Setups' }));
    fireEvent.click(screen.getByRole('button', { name: /In Favour groups/ }));
    expect(onChange).toHaveBeenLastCalledWith('setups:favour');

    fireEvent.click(screen.getByRole('button', { name: /Source/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Deals' }));
    fireEvent.click(screen.getByRole('button', { name: /Deal watch/ }));
    expect(onChange).toHaveBeenLastCalledWith('deals:watch');
    fireEvent.click(screen.getByRole('button', { name: /Source/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Deals' }));
    fireEvent.click(await screen.findByRole('button', { name: /SOCIETE GENERALE/ }));
    expect(onChange).toHaveBeenLastCalledWith('deals:house:SOCIETE GENERALE');
  });
});
