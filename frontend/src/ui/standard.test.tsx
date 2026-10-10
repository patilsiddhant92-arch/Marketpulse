import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DataGapBanner, DataGapList } from './DataGap';
import { Segmented } from './Segmented';
import { SignedNum } from './SignedNum';
import { StaticTable } from './StaticTable';

describe('shared UI standard pieces', () => {
  it('StaticTable renders rows, right-aligns numbers and shows the empty line', () => {
    const { rerender } = render(
      <StaticTable
        label="Evidence"
        rows={[{ k: 'FII', n: 12 }]}
        rowKey={(r) => r.k}
        columns={[
          { id: 'k', header: 'Class', cell: (r) => r.k },
          { id: 'n', header: 'Deals', align: 'right', cell: (r) => r.n },
        ]}
      />,
    );
    expect(screen.getByRole('table', { name: 'Evidence' })).toBeInTheDocument();
    expect(screen.getByText('12').closest('td')).toHaveClass('text-right');
    rerender(<StaticTable label="Evidence" rows={[]} rowKey={() => 'x'} columns={[{ id: 'k', header: 'Class', cell: () => null }]} empty="No rows" />);
    expect(screen.getByText('No rows')).toBeInTheDocument();
  });

  it('DataGapBanner / DataGapList draw the standard data-gap state', () => {
    const onClick = vi.fn();
    render(
      <>
        <DataGapBanner action={<button onClick={onClick}>Show 2026-08-13</button>}>Data gap: the 1M window spans missing sessions.</DataGapBanner>
        <DataGapList gaps={['corporate_actions is empty']} />
        <DataGapList gaps={[]} />
      </>,
    );
    expect(screen.getByRole('status')).toHaveAttribute('data-state', 'data-gap');
    fireEvent.click(screen.getByRole('button', { name: 'Show 2026-08-13' }));
    expect(onClick).toHaveBeenCalled();
    expect(screen.getAllByLabelText('Data gaps')).toHaveLength(1);
  });

  it('Segmented is a radiogroup and SignedNum colours by sign with NULL as —', () => {
    const onChange = vi.fn();
    render(
      <>
        <Segmented label="Window" value="1W" onChange={onChange} options={[{ value: '1D', label: '1D' }, { value: '1W', label: '1W' }]} />
        <SignedNum value={2.5} />
        <SignedNum value={-1} format="signed" digits={0} />
        <SignedNum value={null} />
      </>,
    );
    expect(screen.getByRole('radio', { name: '1W' })).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(screen.getByRole('radio', { name: '1D' }));
    expect(onChange).toHaveBeenCalledWith('1D');
    expect(screen.getByText('+2.5%')).toHaveClass('text-up');
    expect(screen.getByText('-1')).toHaveClass('text-down');
    expect(screen.getByText('—')).toHaveClass('text-fg-3');
  });
});
