/**
 * ChipRow — a single-line row of chips that never wraps inside a table row.
 * Chips are shown in order while their labels fit a character budget; the rest fold
 * into a "+N" badge whose tooltip lists every chip (hidden ones included).
 */
import type { ReactNode } from 'react';
import { cn } from '../lib/cn';
import { Chip, type ChipTone } from './Chip';
import { Tooltip } from './Tooltip';

export interface ChipRowItem {
  key: string;
  label: string;
  tone?: ChipTone;
  title?: string;
  onClick?: () => void;
}

/** How many leading items fit `budget` characters (always at least one). */
export function visibleCount(items: readonly Pick<ChipRowItem, 'label'>[], budget: number): number {
  let used = 0;
  let n = 0;
  for (const it of items) {
    const cost = it.label.length + 2; // padding + gap ≈ 2 chars
    if (n > 0 && used + cost > budget) break;
    used += cost;
    n += 1;
  }
  return n;
}

export interface ChipRowProps {
  items: readonly ChipRowItem[];
  /** Character budget for visible labels (≈ column width / 7). */
  budget?: number;
  empty?: ReactNode;
  className?: string;
}

export function ChipRow({ items, budget = 18, empty, className }: ChipRowProps) {
  if (!items.length) return <>{empty ?? <span className="text-fg-3">—</span>}</>;
  const n = visibleCount(items, budget);
  const shown = items.slice(0, n);
  const hidden = items.length - n;
  return (
    <span className={cn('flex min-w-0 flex-nowrap items-center gap-0.5 overflow-hidden', className)}>
      {shown.map((it) => (
        <Chip key={it.key} tone={it.tone ?? 'neutral'} title={it.title} onClick={it.onClick} className="min-w-0 shrink truncate">
          {it.label}
        </Chip>
      ))}
      {hidden > 0 && (
        <Tooltip
          content={
            <ul className="space-y-0.5 text-fg-2">
              {items.map((it) => (
                <li key={it.key}>
                  <b className="text-fg">{it.label}</b>
                  {it.title ? ` — ${it.title}` : ''}
                </li>
              ))}
            </ul>
          }
        >
          <span tabIndex={0} className="num shrink-0 cursor-help rounded-[3px] px-1 text-2xs text-fg-3 hover:text-fg" aria-label={`${hidden} more`}>
            +{hidden}
          </span>
        </Tooltip>
      )}
    </span>
  );
}
