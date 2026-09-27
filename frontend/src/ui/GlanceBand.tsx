import type { ReactNode } from 'react';
import { cn } from '../lib/cn';

export interface GlanceBandProps {
  /** Accessible name, e.g. "Desk at a glance". */
  label: string;
  /** KpiTiles (and optionally a trailing custom block). */
  children: ReactNode;
  /** Right-edge slot (as-of, source, a link). */
  aside?: ReactNode;
  className?: string;
}

/**
 * The "at a glance" story band at the top of each tab: one card, tiles
 * separated by hairlines, so the tab's headline numbers read left to right
 * before the table does.
 */
export function GlanceBand({ label, children, aside, className }: GlanceBandProps) {
  return (
    <section
      aria-label={label}
      data-glance
      className={cn('mp-fade-in flex min-h-[76px] shrink-0 overflow-hidden rounded-card border border-line bg-surface shadow-card', className)}
    >
      <div className="flex min-w-0 flex-1 divide-x divide-line/70 overflow-x-auto [&>*]:min-w-[132px] [&>*]:flex-1">{children}</div>
      {aside && <div className="flex shrink-0 flex-col items-end justify-center gap-1 border-l border-line/70 px-4 text-2xs text-fg-3">{aside}</div>}
    </section>
  );
}
