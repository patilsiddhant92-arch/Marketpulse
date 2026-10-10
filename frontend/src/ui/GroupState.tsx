/**
 * GroupStateChip — the one way every tab shows a group's state (Favour / Neutral / Caution) with its numeric
 * reason on hover. The state itself comes from the one Pulse-owned source (GET /api/v2/pulse/group-state,
 * context/groupState.ts); this file only draws it.
 */
import { cn } from '../lib/cn';
import { Chip, type ChipTone } from './Chip';

export type GroupStateName = 'Favour' | 'Neutral' | 'Caution';
export const GROUP_STATES: readonly GroupStateName[] = ['Favour', 'Neutral', 'Caution'];

const TONE: Record<GroupStateName, ChipTone> = { Favour: 'positive', Neutral: 'neutral', Caution: 'negative' };
const DOT: Record<GroupStateName, string> = { Favour: 'bg-up', Neutral: 'bg-fg-3', Caution: 'bg-down' };

export function isGroupState(v: unknown): v is GroupStateName {
  return v === 'Favour' || v === 'Neutral' || v === 'Caution';
}

export function groupStateTone(state: string | null | undefined): ChipTone {
  return isGroupState(state) ? TONE[state] : 'neutral';
}

export function groupStateTitle(state: string | null | undefined, reason?: string | null, sessions?: number | null): string {
  if (!state) return reason || 'No group state for this session.';
  const run = sessions != null && sessions > 1 ? ` (${sessions} sessions in this state)` : '';
  return `${state}${run}: ${reason ?? ''}`.trim();
}

export interface GroupStateChipProps {
  state: string | null | undefined;
  reason?: string | null;
  /** Consecutive sessions in the state (from the shared source), shown in the tooltip. */
  sessions?: number | null;
  /** Dot only (dense board cells); the label is still the accessible name. */
  dotOnly?: boolean;
  size?: 'xs' | 'sm';
  className?: string;
}

export function GroupStateChip({ state, reason, sessions, dotOnly, size = 'xs', className }: GroupStateChipProps) {
  const title = groupStateTitle(state, reason, sessions);
  if (dotOnly) {
    if (!isGroupState(state)) {
      return <span className={cn('inline-block h-2 w-2 shrink-0 rounded-full bg-surface-3', className)} role="img" aria-label="no state" title={title} />;
    }
    return <span className={cn('inline-block h-2 w-2 shrink-0 rounded-full', DOT[state], className)} role="img" aria-label={state} title={title} data-state={state} />;
  }
  if (!isGroupState(state)) return <span className={cn('text-fg-3', className)} title={title}>—</span>;
  return (
    <Chip tone={groupStateTone(state)} variant="dot" size={size} title={title} className={className}>
      <span data-state={state}>{state}</span>
    </Chip>
  );
}
