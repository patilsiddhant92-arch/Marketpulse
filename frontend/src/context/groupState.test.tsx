import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { GroupStateChip, groupStateTitle, groupStateTone } from '../ui/GroupState';
import { sharedRow } from '../test/groupStateFixture';
import { applyGroupState, groupStateMap } from './groupState';

describe('shared group state', () => {
  it('overlays the shared state on rows that carry their own copy, by group name', () => {
    const map = groupStateMap([sharedRow('Steel', 'Caution', 'Money leaving.')]);
    const rows = [
      { name: 'Steel', state: 'Favour', why: 'stale' },
      { name: 'Drugs', state: 'Neutral', why: 'own' },
    ];
    const out = applyGroupState(rows, map, (r) => r.name, (r, s) => ({ ...r, state: s.state, why: s.reason }));
    expect(out[0]).toEqual({ name: 'Steel', state: 'Caution', why: 'Money leaving.' });
    expect(out[1]).toBe(rows[1]);
    // nothing to overlay -> same array (memo friendly)
    expect(applyGroupState(rows, groupStateMap([]), (r) => r.name, (r) => r)).toBe(rows);
    expect(applyGroupState(rows, groupStateMap([sharedRow('Gold', 'Favour', 'x')]), (r) => r.name, (r) => r)).toBe(rows);
  });

  it('draws one chip for every tab: tone, label, reason + run length in the tooltip', () => {
    expect(groupStateTone('Favour')).toBe('positive');
    expect(groupStateTone('Caution')).toBe('negative');
    expect(groupStateTone(null)).toBe('neutral');
    expect(groupStateTitle('Caution', 'Money leaving.', 4)).toBe('Caution (4 sessions in this state): Money leaving.');
    render(
      <>
        <GroupStateChip state="Caution" reason="Money leaving." sessions={4} />
        <GroupStateChip state="Favour" reason="Trending." dotOnly />
        <GroupStateChip state={null} />
      </>,
    );
    expect(screen.getByText('Caution')).toHaveAttribute('data-state', 'Caution');
    expect(screen.getByRole('img', { name: 'Favour' })).toHaveAttribute('title', 'Favour: Trending.');
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
