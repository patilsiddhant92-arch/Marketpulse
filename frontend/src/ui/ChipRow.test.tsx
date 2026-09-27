import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ChipRow, visibleCount } from './ChipRow';

describe('ChipRow', () => {
  it('fits leading labels in the budget, always at least one', () => {
    expect(visibleCount([{ label: '52W high' }, { label: '20D high + RVOL' }, { label: 'Gap-up' }], 22)).toBe(1);
    expect(visibleCount([{ label: '52W high' }, { label: 'Gap-up' }], 22)).toBe(2);
    expect(visibleCount([{ label: 'a very very long label indeed' }], 5)).toBe(1);
  });
  it('folds the rest into +N on one line', () => {
    render(
      <ChipRow
        budget={12}
        items={[
          { key: 'a', label: '52W high' },
          { key: 'b', label: '20D high + RVOL' },
          { key: 'c', label: 'Gap-up' },
        ]}
      />,
    );
    expect(screen.getByText('52W high')).toBeInTheDocument();
    expect(screen.queryByText('Gap-up')).not.toBeInTheDocument();
    expect(screen.getByLabelText('2 more')).toHaveTextContent('+2');
  });
  it('renders a dash when empty', () => {
    render(<ChipRow items={[]} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
