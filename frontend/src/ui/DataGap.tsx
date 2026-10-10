/**
 * Data-gap states, one look on every tab:
 * - DataGapBanner: a full-width warn banner (a window spans missing sessions, studies stop at a gap...) with an
 *   optional action (e.g. "Show the latest good session").
 * - DataGapList: the served list of data gaps as warn chips (hover for the text).
 * Distinct from EmptyState (a real, successful empty result) and ErrorState (the API failed).
 */
import { CalendarClock } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../lib/cn';
import { DataWarningChip } from './DataWarningChip';

export interface DataGapBannerProps {
  children: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  /** 'status' for a live condition of the data on screen, 'note' for a standing caveat. */
  role?: 'status' | 'note';
  compact?: boolean;
  className?: string;
}

export function DataGapBanner({ children, action, icon, role = 'status', compact, className }: DataGapBannerProps) {
  return (
    <div
      role={role}
      data-state="data-gap"
      className={cn(
        'flex flex-wrap items-center gap-2 rounded border border-warn/40 bg-warn/10 text-fg',
        compact ? 'px-3 py-1 text-2xs' : 'px-3 py-1.5 text-xs',
        className,
      )}
    >
      <span className="shrink-0 text-warn [&>svg]:h-3.5 [&>svg]:w-3.5" aria-hidden>
        {icon ?? <CalendarClock />}
      </span>
      <span className="min-w-0">{children}</span>
      {action}
    </div>
  );
}

export function DataGapList({ gaps, className }: { gaps?: readonly string[] | null; className?: string }) {
  if (!gaps?.length) return null;
  return (
    <div className={cn('flex flex-wrap items-center gap-1', className)} aria-label="Data gaps">
      {gaps.map((g) => (
        <DataWarningChip key={g} warning={g} />
      ))}
    </div>
  );
}
