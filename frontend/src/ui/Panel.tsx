import type { ReactNode } from 'react';
import { cn } from '../lib/cn';

export interface PanelProps {
  title: ReactNode;
  /** Small muted text after the title (counts, as-of, source). */
  meta?: ReactNode;
  /** Right-aligned header controls. */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** aria-label when the title is not plain text. */
  label?: string;
}

/** A titled card section used by Desk and Stock 360. */
export function Panel({ title, meta, actions, children, className, bodyClassName, label }: PanelProps) {
  return (
    <section
      aria-label={label ?? (typeof title === 'string' ? title : undefined)}
      className={cn('flex min-h-0 flex-col overflow-hidden rounded border border-line bg-surface', className)}
    >
      <header className="flex h-8 shrink-0 items-center gap-2 border-b border-line px-3">
        <h2 className="text-2xs font-semibold uppercase tracking-wide text-fg-2">{title}</h2>
        {meta && <span className="min-w-0 truncate text-2xs text-fg-3">{meta}</span>}
        {actions && <div className="ml-auto flex shrink-0 items-center gap-1">{actions}</div>}
      </header>
      <div className={cn('min-h-0 flex-1', bodyClassName)}>{children}</div>
    </section>
  );
}
