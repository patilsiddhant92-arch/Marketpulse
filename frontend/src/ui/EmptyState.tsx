import type { ReactNode } from 'react';
import { cn } from '../lib/cn';

export interface EmptyStateProps {
  title: string;
  detail?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  compact?: boolean;
  className?: string;
}

/**
 * "Nothing matched" — a real, successful empty result. Visually distinct from
 * ErrorState (API down / endpoint missing), per spec 7.1.
 */
export function EmptyState({ title, detail, action, icon, compact, className }: EmptyStateProps) {
  return (
    <div
      role="status"
      className={cn('flex flex-col items-center justify-center gap-1.5 text-center text-fg-3', compact ? 'p-3' : 'p-8', className)}
    >
      {icon && <div className="text-fg-3">{icon}</div>}
      <div className="text-sm font-medium text-fg-2">{title}</div>
      {detail && <div className="max-w-md text-xs">{detail}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
