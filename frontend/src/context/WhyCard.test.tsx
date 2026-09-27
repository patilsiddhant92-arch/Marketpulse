import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it } from 'vitest';
import { WhyList } from './WhyCard';

describe('WhyList', () => {
  it('renders fact bullets with in-app links carrying as_of', () => {
    const router = createMemoryRouter(
      [
        {
          path: '/',
          element: (
            <WhyList
              rows={[
                { kind: 'setup', tone: 'accent', text: 'In the VCP queue for 4 sessions.', link: '/desk?view=setups&queue=vcp', facts: {} },
                { kind: 'footprint', tone: 'positive', text: 'Footprint: RVOL 2.00 — real participation.', link: null, facts: {} },
              ]}
            />
          ),
        },
      ],
      { initialEntries: ['/?as_of=2026-09-25'] },
    );
    render(<RouterProvider router={router} />);
    expect(screen.getByText('In the VCP queue for 4 sessions.')).toBeInTheDocument();
    expect(screen.getByText(/real participation/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'open →' })).toHaveAttribute('href', '/desk?view=setups&queue=vcp&as_of=2026-09-25');
  });
});
