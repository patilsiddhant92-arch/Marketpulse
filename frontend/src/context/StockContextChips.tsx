/**
 * StockContextChips — one line of cross-tab context for a stock: its group's Health zone +
 * quadrant (↓ = "falling"), active setups with distance to trigger, deals over 10 sessions,
 * results / corporate action soon, data-gap warning. Each chip links to the view behind it.
 * Never wraps: overflow folds into "+N" with a tooltip listing everything.
 */
import { useMemo } from 'react';
import { useNavigate } from 'react-router';
import type { StockContextRow } from '../api/types';
import { cn } from '../lib/cn';
import { useAsOf } from '../shell/urlState';
import { Chip } from '../ui/Chip';
import type { RowData } from '@tanstack/react-table';
import type { DataTableColumn } from '../ui/DataTable';
import { visibleCount } from '../ui/ChipRow';
import { Tooltip } from '../ui/Tooltip';
import { contextChips, useStockContext, type ContextPart, type StockContextMap } from './stockContext';

/** Adds ?as_of to an in-app path. */
export function withAsOf(href: string, asOf: string | null | undefined): string {
  if (!asOf) return href;
  return `${href}${href.includes('?') ? '&' : '?'}as_of=${asOf}`;
}

export interface StockContextChipsProps {
  ctx: StockContextRow | undefined;
  omit?: readonly ContextPart[];
  /** Leave out this queue's setup chip (the table is that queue). */
  skipQueue?: string;
  /** Character budget before folding into +N (≈ width / 7). 0 = show all. */
  budget?: number;
  className?: string;
  size?: 'xs' | 'sm';
}

export function StockContextChips({ ctx, omit, skipQueue, budget = 26, className, size = 'xs' }: StockContextChipsProps) {
  const navigate = useNavigate();
  const [asOf] = useAsOf();
  const chips = contextChips(ctx, { omit, asOf, skipQueue });
  if (!ctx) return <span className="text-2xs text-fg-3">…</span>;
  if (!chips.length) return <span className="text-fg-3">—</span>;
  const n = budget > 0 ? visibleCount(chips, budget) : chips.length;
  const hidden = chips.length - n;
  return (
    <span className={cn('flex min-w-0 flex-nowrap items-center gap-0.5 overflow-hidden', className)} data-testid="stock-context">
      {chips.slice(0, n).map((c) => (
        <Chip
          key={c.key}
          size={size}
          tone={c.tone}
          title={c.title}
          className="shrink-0"
          onClick={
            c.href
              ? () => {
                  navigate(withAsOf(c.href as string, asOf));
                }
              : undefined
          }
        >
          {c.label}
        </Chip>
      ))}
      {hidden > 0 && (
        <Tooltip
          content={
            <ul className="max-w-sm space-y-0.5 text-fg-2">
              {chips.map((c) => (
                <li key={c.key}>
                  <b className="text-fg">{c.label}</b> — {c.title}
                </li>
              ))}
            </ul>
          }
        >
          <span tabIndex={0} className="num shrink-0 cursor-help px-0.5 text-2xs text-fg-3 hover:text-fg" aria-label={`${hidden} more context`}>
            +{hidden}
          </span>
        </Tooltip>
      )}
    </span>
  );
}

/** A "Context" column for any stock table. Rebuild when `map` changes (new data). */
export function contextColumn<T extends RowData>(getSymbol: (row: T) => string | null | undefined, map: StockContextMap, opts: { omit?: readonly ContextPart[]; width?: number; skipQueue?: string } = {}): DataTableColumn<T> {
  const width = opts.width ?? 190;
  return {
    id: 'context',
    header: 'Context',
    accessor: (r: T) => {
      const c = map.get((getSymbol(r) ?? '').toUpperCase());
      return c?.group?.health ?? null;
    },
    width,
    renderNull: true,
    sortable: true,
    headerTitle:
      "Cross-tab context: group Health + quadrant (↓ = leading/improving but falling), setups with distance to trigger, deals net ₹Cr over 10 sessions (PROP excluded), results / corporate action soon, data gap. Click a chip to open that view. Sorts by group Health.",
    cell: (_v, r) => <StockContextChips ctx={map.get((getSymbol(r) ?? '').toUpperCase())} omit={opts.omit} skipQueue={opts.skipQueue} budget={Math.floor(width / 7)} />,
  } as DataTableColumn<T>;
}

/** Context line for one stock (Stock 360 header / sidecar). */
export function StockContextLine({ symbol, className }: { symbol: string; className?: string }) {
  const syms = useMemo(() => [symbol], [symbol]);
  const { map } = useStockContext(syms);
  const ctx = map.get(symbol.toUpperCase());
  if (!ctx) return null;
  return (
    <div className={cn('flex min-w-0 items-center gap-1.5 text-2xs text-fg-3', className)} aria-label="Context across tabs">
      <span className="mp-label shrink-0">Context</span>
      {/* events and the data gap are already chips in the header */}
      <StockContextChips ctx={ctx} omit={['events', 'warning']} budget={0} className="flex-wrap" />
    </div>
  );
}
