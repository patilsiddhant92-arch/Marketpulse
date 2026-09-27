import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { GlanceBand } from './GlanceBand';
import { KpiList, KpiTile } from './KpiTile';

function wrap(ui: ReactNode) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 404 })));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('KpiTile / KpiList / GlanceBand', () => {
  it('formats the value, colours the delta by sign (inverted when asked) and shows NULL as a dash', () => {
    wrap(
      <GlanceBand label="Test band">
        <KpiTile label="Above 50 EMA" value={34.62} format="pct" digits={1} delta={1.04} deltaFormat="signedPct" />
        <KpiTile label="VIX" value={12.16} digits={2} delta={6.8} deltaFormat="signedPct" deltaTone="invert" />
        <KpiTile label="Missing" value={null} />
      </GlanceBand>,
    );
    expect(screen.getByRole('region', { name: 'Test band' })).toBeInTheDocument();
    expect(screen.getByText('34.6%')).toBeInTheDocument();
    expect(screen.getByText('+1.0%')).toHaveClass('text-up');
    expect(screen.getByText('+6.8%')).toHaveClass('text-down');
    expect(screen.getByText('—')).toHaveClass('text-fg-3');
  });

  it('clickable tiles and list items are buttons', () => {
    const onTile = vi.fn();
    const onItem = vi.fn();
    wrap(
      <>
        <KpiTile label="Squeeze queue" value={76} format="int" onClick={onTile} selected />
        <KpiList label="Top 3" items={[{ id: 'a', label: 'Dyes', value: '100', onClick: onItem }]} />
      </>,
    );
    fireEvent.click(screen.getByRole('button', { name: /Squeeze queue/ }));
    expect(onTile).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /Squeeze queue/ })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: /Dyes/ }));
    expect(onItem).toHaveBeenCalled();
  });
});
