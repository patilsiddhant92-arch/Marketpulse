import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { DASH } from '../lib/fmt';
import { DataTable, compareValues, groupRows, normalizeCellValue, type DataTableColumn } from './DataTable';

type Row = { symbol: string; rs: number | null; chg: number | null };

const rows: Row[] = [
  { symbol: 'HAL', rs: 91, chg: 1.2 },
  { symbol: 'BEL', rs: null, chg: -0.4 },
  { symbol: 'ABB', rs: 55, chg: null },
  { symbol: 'ZEEL', rs: 12, chg: Number.NaN },
];

const columns: DataTableColumn<Row>[] = [
  { id: 'symbol', header: 'Symbol', accessor: 'symbol' },
  { id: 'rs', header: 'Strength', accessor: 'rs', format: 'int' },
  { id: 'chg', header: '1D %', accessor: (r) => r.chg, format: 'signedPct' },
];

function wrap(ui: ReactNode) {
  // The dictionary query 404s in tests (no fetch mock) — tooltips fall back.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('', { status: 404 })),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function bodySymbols(): string[] {
  const table = screen.getByRole('grid');
  const bodyRows = within(table).getAllByRole('row').slice(1);
  return bodyRows.map((r) => within(r).getAllByRole('cell')[0].textContent ?? '');
}

describe('sorting helpers', () => {
  it('normalises NULL-ish values to undefined', () => {
    expect(normalizeCellValue(null)).toBeUndefined();
    expect(normalizeCellValue('')).toBeUndefined();
    expect(normalizeCellValue(Number.NaN)).toBeUndefined();
    expect(normalizeCellValue(0)).toBe(0);
    expect(normalizeCellValue('x')).toBe('x');
  });
  it('compares numbers numerically and strings naturally', () => {
    expect(compareValues(2, 10)).toBeLessThan(0);
    expect(compareValues('A2', 'A10')).toBeLessThan(0);
    expect(compareValues('abb', 'ABB')).toBe(0);
  });
});

describe('DataTable', () => {
  it('renders NULL / NaN as the dash, never 0', () => {
    wrap(<DataTable label="Test" columns={columns} rows={rows} getRowId={(r) => r.symbol} />);
    const table = screen.getByRole('grid');
    const bel = within(table)
      .getAllByRole('row')
      .find((r) => r.textContent?.includes('BEL'))!;
    expect(within(bel).getAllByRole('cell')[1].textContent).toBe(DASH);
    const zeel = within(table)
      .getAllByRole('row')
      .find((r) => r.textContent?.includes('ZEEL'))!;
    expect(within(zeel).getAllByRole('cell')[2].textContent).toBe(DASH);
  });

  it('sorts numeric columns descending first, NULLs last in both directions, with aria-sort', () => {
    wrap(<DataTable label="Test" columns={columns} rows={rows} getRowId={(r) => r.symbol} />);
    const header = screen.getByRole('columnheader', { name: /Strength/ });
    expect(header).toHaveAttribute('aria-sort', 'none');

    fireEvent.click(within(header).getByRole('button'));
    expect(header).toHaveAttribute('aria-sort', 'descending');
    expect(bodySymbols()).toEqual(['HAL', 'ABB', 'ZEEL', 'BEL']);

    fireEvent.click(within(header).getByRole('button'));
    expect(header).toHaveAttribute('aria-sort', 'ascending');
    expect(bodySymbols()).toEqual(['ZEEL', 'ABB', 'HAL', 'BEL']);

    fireEvent.click(within(header).getByRole('button'));
    expect(header).toHaveAttribute('aria-sort', 'none');
    expect(bodySymbols()).toEqual(['HAL', 'BEL', 'ABB', 'ZEEL']);
  });

  it('keeps NaN and NULL last when sorting an accessor-function column', () => {
    wrap(<DataTable label="Test" columns={columns} rows={rows} getRowId={(r) => r.symbol} initialSort={[{ id: 'chg', desc: false }]} />);
    expect(bodySymbols()).toEqual(['BEL', 'HAL', 'ABB', 'ZEEL']);
  });

  it('sorts text columns ascending first', () => {
    wrap(<DataTable label="Test" columns={columns} rows={rows} getRowId={(r) => r.symbol} />);
    fireEvent.click(within(screen.getByRole('columnheader', { name: /Symbol/ })).getByRole('button'));
    expect(bodySymbols()).toEqual(['ABB', 'BEL', 'HAL', 'ZEEL']);
  });

  it('shows returned vs total honestly', () => {
    const { rerender } = wrap(<DataTable label="Test" columns={columns} rows={rows} total={250} getRowId={(r) => r.symbol} />);
    expect(screen.getByText(/4 of 250 rows/)).toBeInTheDocument();
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <DataTable label="Test" columns={columns} rows={rows} total={null} getRowId={(r) => r.symbol} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByText(/total unknown/)).toBeInTheDocument();
  });

  it('moves the active row with J/K and activates with Enter', () => {
    const onActive = vi.fn();
    const onActivate = vi.fn();
    wrap(
      <DataTable
        label="Queue"
        columns={columns}
        rows={rows}
        getRowId={(r) => r.symbol}
        onActiveRowChange={onActive}
        onRowActivate={onActivate}
      />,
    );
    const region = screen.getByRole('region', { name: 'Queue' });
    fireEvent.keyDown(region, { key: 'j' });
    fireEvent.keyDown(region, { key: 'j' });
    expect(onActive).toHaveBeenLastCalledWith(rows[1]);
    fireEvent.keyDown(region, { key: 'k' });
    expect(onActive).toHaveBeenLastCalledWith(rows[0]);
    fireEvent.keyDown(region, { key: 'Enter' });
    expect(onActivate).toHaveBeenCalledWith(rows[0]);
    const selected = screen.getAllByRole('row').filter((r) => r.getAttribute('aria-selected') === 'true');
    expect(selected).toHaveLength(1);
    expect(selected[0].textContent).toContain('HAL');
  });

  it('hides columns from the Columns menu and honours defaultHidden', () => {
    const cols: DataTableColumn<Row>[] = [...columns, { id: 'extra', header: 'Extra', accessor: () => 'x', defaultHidden: true }];
    wrap(<DataTable label="Test" columns={cols} rows={rows} getRowId={(r) => r.symbol} />);
    expect(screen.queryByRole('columnheader', { name: /Extra/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Columns/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Strength' }));
    expect(screen.queryByRole('columnheader', { name: /Strength/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Extra' }));
    expect(screen.getByRole('columnheader', { name: /Extra/ })).toBeInTheDocument();
  });

  it('distinguishes empty results from errors', () => {
    const { unmount } = wrap(<DataTable label="Test" columns={columns} rows={[]} getRowId={(r) => r.symbol} />);
    expect(screen.getByRole('status')).toHaveTextContent('No rows');
    unmount();
    wrap(<DataTable label="Test" columns={columns} rows={[]} error={new Error('boom')} getRowId={(r) => r.symbol} />);
    expect(screen.getByRole('alert')).toHaveTextContent('boom');
  });
});

describe('DataTable design helpers', () => {
  it('columnGroupRuns merges adjacent columns of the same group', async () => {
    const { columnGroupRuns } = await import('./DataTable');
    type R = { a: number };
    const col = (id: string, group?: string) => ({ id, header: id, accessor: 'a' as const, group });
    expect(columnGroupRuns<R>([col('x'), col('y')])).toBeNull();
    const runs = columnGroupRuns<R>([col('sym'), col('r1', 'Returns'), col('r3', 'Returns'), col('rs', 'Strength')]);
    expect(runs?.map((r) => [r.label, r.cols.map((c) => c.id)])).toEqual([
      [null, ['sym']],
      ['Returns', ['r1', 'r3']],
      ['Strength', ['rs']],
    ]);
  });

  it('heatStyle tints by sign and magnitude with tokens only', async () => {
    const { heatStyle } = await import('./DataTable');
    expect(heatStyle(null)).toBeUndefined();
    expect(heatStyle(0)).toBeUndefined();
    expect(heatStyle(1)?.backgroundColor).toBe('rgb(var(--c-up) / 0.250)');
    expect(heatStyle(-0.5)?.backgroundColor).toBe('rgb(var(--c-down) / 0.150)');
    expect(heatStyle(-3)?.backgroundColor).toBe('rgb(var(--c-down) / 0.250)');
  });
});

describe('DataTable groupBy', () => {
  it('puts rows under group header rows in group order and sorts within groups', () => {
    wrap(
      <DataTable<Row>
        label="grouped"
        columns={columns}
        rows={rows}
        getRowId={(r) => r.symbol}
        groupBy={{
          key: (r) => ((r.rs ?? 0) >= 50 ? 'strong' : 'weak'),
          order: ['strong', 'weak'],
          header: (k, list) => `${k} (${list.length})`,
        }}
      />,
    );
    const table = screen.getByRole('grid');
    const texts = within(table)
      .getAllByRole('row')
      .slice(1)
      .map((r) => r.textContent ?? '');
    expect(texts[0]).toBe('strong (2)');
    expect(texts[1].startsWith('HAL')).toBe(true);
    expect(texts[2].startsWith('ABB')).toBe(true);
    expect(texts[3]).toBe('weak (2)');
    fireEvent.click(screen.getByRole('button', { name: /Strength/ }));
    const after = within(table)
      .getAllByRole('row')
      .slice(1)
      .map((r) => (r.textContent ?? '').slice(0, 4));
    // Sorted by strength (desc first) inside each group; groups keep their order.
    expect(after).toEqual(['stro', 'HAL9', 'ABB5', 'weak', 'ZEEL', 'BEL—']);
  });

  it('groupRows is a stable partition in the given order', () => {
    expect(groupRows([1, 2, 3, 4, 5], (n) => (n % 2 ? 'odd' : 'even'), ['even', 'odd'])).toEqual([
      { key: 'even', rows: [2, 4] },
      { key: 'odd', rows: [1, 3, 5] },
    ]);
  });
});
