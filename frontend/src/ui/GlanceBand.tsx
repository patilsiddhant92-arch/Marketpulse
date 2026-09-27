import type { ReactNode } from 'react';
import { cn } from '../lib/cn';

export interface GlanceBandProps {
  /** Accessible name, e.g. "Desk at a glance". */
  label: string;
  /** KpiTiles (and optionally a trailing custom block). */
  children: ReactNode;
  /** Right-edge slot (as-of, source, a link). */
  aside?: ReactNode;
  /** Slim band (chart-first tabs): pair with compact KpiTiles. */
  compact?: boolean;
  className?: string;
}

/**
 * The "at a glance" story band at the top of each tab: one card, tiles
 * separated by hairlines, so the tab's headline numbers read left to right
 * before the table does.
 */
export function GlanceBand({ label, children, aside, compact, className }: GlanceBandProps) {
  return (
    <section
      aria-label={label}
      data-glance
      className={cn(
        'mp-fade-in flex shrink-0 overflow-hidden rounded-card border border-line bg-surface shadow-card',
        compact ? 'min-h-[48px]' : 'min-h-[76px]',
        className,
      )}
    >
      <div className="flex min-w-0 flex-1 divide-x divide-line/70 overflow-x-auto [&>*]:min-w-[132px] [&>*]:flex-1">{children}</div>
      {aside && (
        <div
          className={cn(
            'flex min-w-0 shrink flex-col items-end justify-center border-l border-line/70 px-4 text-2xs text-fg-3',
            compact ? 'gap-0.5' : 'gap-1',
          )}
        >
          {aside}
        </div>
      )}
    </section>
  );
}
