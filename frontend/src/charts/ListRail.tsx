/**
 * List rail (HarkPro/09-tab-charts.md §3): the open list beside the main chart. Click or J / K
 * moves through it; the chart keeps its zoom and indicators. S stars the current stock.
 */
import { Star, X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { cn } from '../lib/cn';
import { fmtNum } from '../lib/fmt';
import { SignedNum } from '../screener/cells';
import { useShell } from '../shell/ShellContext';
import type { ChartItem } from './sources';

export interface ListRailProps {
  label: string;
  items: readonly ChartItem[];
  current: string | null;
  onPick: (sym: string) => void;
  onRemove?: (sym: string) => void;
  loading?: boolean;
  className?: string;
}

export function ListRail({ label, items, current, onPick, onRemove, loading, className }: ListRailProps) {
  const shell = useShell();
  const activeRef = useRef<HTMLLIElement>(null);
  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ block: 'nearest' });
  }, [current]);
  const pos = current ? items.findIndex((i) => i.symbol === current) : -1;
  return (
    <aside className={cn('flex min-h-0 flex-col border-l border-line bg-surface', className)} aria-label={`List: ${label}`}>
      <div className="flex h-8 shrink-0 items-center gap-1 border-b border-line px-2 text-2xs text-fg-3">
        <span className="truncate font-medium text-fg-2" title={label}>
          {label}
        </span>
        <span className="num ml-auto shrink-0">{items.length ? `${pos >= 0 ? pos + 1 : '–'} / ${items.length}` : loading ? '…' : '0'}</span>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto py-0.5 text-xs" role="listbox" aria-label="Symbols (J / K)">
        {items.map((it) => {
          const on = it.symbol === current;
          const watched = shell.isWatched(it.symbol);
          return (
            <li
              key={it.symbol}
              ref={on ? activeRef : undefined}
              role="option"
              aria-selected={on}
              className={cn('group flex cursor-pointer items-center gap-1.5 px-2 py-0.5', on ? 'bg-accent/15' : 'hover:bg-surface-3')}
              onClick={() => onPick(it.symbol)}
            >
              <button
                type="button"
                aria-label={`${watched ? 'Unstar' : 'Star'} ${it.symbol}`}
                onClick={(e) => {
                  e.stopPropagation();
                  shell.toggleWatch(it.symbol);
                }}
                className={cn('shrink-0', watched ? 'text-accent' : 'text-fg-3 opacity-40 group-hover:opacity-100')}
              >
                <Star className={cn('h-3 w-3', watched && 'fill-accent')} />
              </button>
              <span className={cn('font-mono', on ? 'font-semibold text-accent' : 'text-fg')}>{it.symbol}</span>
              {it.tags[0] && <span className="truncate text-2xs text-fg-3">{it.tags[0]}</span>}
              <span className="num ml-auto shrink-0 text-fg-2">{fmtNum(it.close ?? null)}</span>
              <span className="w-12 shrink-0 text-right">
                <SignedNum value={it.data_warning ? null : (it.change_1d_pct ?? null)} digits={1} />
              </span>
              {onRemove && (
                <button
                  type="button"
                  aria-label={`Remove ${it.symbol}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onRemove(it.symbol);
                  }}
                  className="shrink-0 text-fg-3 opacity-0 hover:text-down group-hover:opacity-100"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </li>
          );
        })}
        {!items.length && !loading && <li className="px-2 py-2 text-fg-3">No stocks in this list.</li>}
      </ul>
      <div className="shrink-0 border-t border-line px-2 py-1 text-2xs text-fg-3">J / K next · S star · I Stock 360 · H / T draw</div>
    </aside>
  );
}
