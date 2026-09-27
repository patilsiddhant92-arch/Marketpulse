import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { fromMemberRow, fromQueueRow, fromScreenerRow, sortItems } from '../charts/sources';
import type { MemberRow, QueueRow, ScreenerRow } from '../api/types';
import { DataWarningChip } from './DataWarningChip';

const WARN = 'unexplained price jump on 2026-09-01 (×68); returns across it hidden';

describe('DataWarningChip', () => {
  it('renders nothing without a warning', () => {
    const { container } = render(<DataWarningChip warning={null} />);
    expect(container.textContent).toBe('');
  });

  it('shows a short chip with the full served text as its title', () => {
    render(<DataWarningChip warning={WARN} />);
    const chip = screen.getByText('data gap').closest('[title]');
    expect(chip?.getAttribute('title')).toBe(WARN);
  });

  it('chart items carry the warning from every stock source and NULL ranks sort last', () => {
    const scr = fromScreenerRow({ symbol: 'MBECL', rs_percentile: null, data_warning: WARN } as ScreenerRow)!;
    const q = fromQueueRow({ symbol: 'Q', queue: 'vcp', data_warning: WARN } as QueueRow)!;
    const m = fromMemberRow({ symbol: 'M', data_warning: WARN } as MemberRow)!;
    expect([scr.data_warning, q.data_warning, m.data_warning]).toEqual([WARN, WARN, WARN]);
    const sorted = sortItems([scr, { symbol: 'AAA', rs_percentile: 90, tags: [] }], 'rs');
    expect(sorted.map((x) => x.symbol)).toEqual(['AAA', 'MBECL']);
  });
});
