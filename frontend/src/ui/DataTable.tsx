/**
 * DataTable — the one table component (spec 9).
 *
 * TanStack Table v9 owns sorting + column-visibility state; TanStack Virtual
 * renders only visible rows. Features: aria-sort headers, sticky header,
 * keyboard row focus (Arrow/J/K/Home/End/PageUp/PageDown, Enter activates),
 * column visibility menu, NULL rendered as "—" and always sorted last,
 * honest "returned of total" count.
 */
import {
  columnVisibilityFeature,
  createSortedRowModel,
  rowSortingFeature,
  tableFeatures,
  useTable,
  type ColumnDef,
  type Row,
  type RowData,
  type SortingState,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ArrowDown, ArrowUp, Columns3 } from 'lucide-react';
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { cn } from '../lib/cn';
import { DASH, fmtInt, fmtValue, isNumericKind, type FormatKind } from '../lib/fmt';
import { useEscapeLayer } from '../lib/layers';
import { setNavList } from '../lib/navList';
import { useMetric } from '../metrics/dictionary';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';
import { MetricTooltipBody } from './MetricTooltip';
import { SkeletonRows } from './Skeleton';
import { Tooltip } from './Tooltip';

export type { RowData };
export type SortSpec = { id: string; desc: boolean };
export type ColumnVisibility = Record<string, boolean>;

export interface DataTableColumn<T extends RowData> {
  /** Unique, stable id (also the URL/sort key). */
  id: string;
  /** Header label. */
  header: ReactNode;
  /** Value getter: a key of T or a function. The value drives sort + default format. */
  accessor: keyof T | ((row: T) => unknown);
  /** Default formatter when no `cell` is given. Numeric kinds right-align. */
  format?: FormatKind;
  digits?: number;
  /** Custom cell. Receives non-null values only unless `renderNull` is true. */
  cell?: (value: unknown, row: T) => ReactNode;
  renderNull?: boolean;
  /** Metric-dictionary key: header gets the dictionary tooltip. */
  metricKey?: string;
  /** Plain tooltip for the header when there is no metricKey. */
  headerTitle?: string;
  align?: 'left' | 'right' | 'center';
  /** Width in px (default 96; text columns 140). */
  width?: number;
  /** Let this column absorb spare width. */
  grow?: boolean;
  sortable?: boolean;
  hideable?: boolean;
  /** Hidden until the user enables it in the Columns menu. */
  defaultHidden?: boolean;
  /** First click sorts descending (default for numeric formats). */
  sortDescFirst?: boolean;
  /** Pin to the left while scrolling horizontally. */
  sticky?: boolean;
  /** Column-group label: adjacent columns with the same group share a header above theirs. */
  group?: string;
  /**
   * Heat tint: return -1..1 (NULL = none). Positive tints the cell with the up
   * colour, negative with down, strength by magnitude.
   */
  heat?: (value: unknown, row: T) => number | null | undefined;
}

export interface DataTableProps<T extends RowData> {
  columns: DataTableColumn<T>[];
  rows: readonly T[];
  getRowId: (row: T, index: number) => string;
  /** Accessible name, e.g. "Darvas Squeeze queue". */
  label: string;
  /** Server-side total before paging (envelope.total). NULL = unknown. */
  total?: number | null;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  emptyState?: ReactNode;

  /** Sorting: uncontrolled with initialSort, or controlled with sorting + onSortingChange. */
  initialSort?: SortSpec[];
  sorting?: SortSpec[];
  onSortingChange?: (next: SortSpec[]) => void;
  /** Column visibility: same controlled/uncontrolled pattern. */
  columnVisibility?: ColumnVisibility;
  onColumnVisibilityChange?: (next: ColumnVisibility) => void;

  /** Row focus (J/K). Controlled via activeRowId, or internal. */
  activeRowId?: string | null;
  onActiveRowChange?: (row: T) => void;
  /** Enter or double-click on a row. */
  onRowActivate?: (row: T) => void;
  onRowClick?: (row: T) => void;
  /** Receives rows in current sort order whenever it changes (export / Charts). */
  onSortedRowsChange?: (rows: T[]) => void;

  rowHeight?: number;
  /** Extra toolbar content (right side). */
  toolbar?: ReactNode;
  /** Hide the count/columns toolbar entirely. */
  hideToolbar?: boolean;
  className?: string;
}

const features = tableFeatures({
  rowSortingFeature,
  columnVisibilityFeature,
  sortedRowModel: createSortedRowModel(),
});

type Feat = typeof features;

/** Nullish / NaN / '' collapse to undefined so TanStack's sortUndefined:'last' applies. */
export function normalizeCellValue(v: unknown): unknown {
  if (v === null || v === undefined || v === '') return undefined;
  if (typeof v === 'number' && !Number.isFinite(v)) return undefined;
  return v;
}

/** Comparator for non-null values: numbers, booleans, then locale/natural strings. */
export function compareValues(a: unknown, b: unknown): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  if (typeof a === 'boolean' && typeof b === 'boolean') return a === b ? 0 : a ? 1 : -1;
  return String(a).localeCompare(String(b), 'en-IN', { numeric: true, sensitivity: 'base' });
}

/** Background tint for a heat value in -1..1 (tokens only). */
export function heatStyle(h: number | null | undefined): { backgroundColor: string } | undefined {
  if (h === null || h === undefined || !Number.isFinite(h) || h === 0) return undefined;
  const a = Math.min(1, Math.abs(h));
  return { backgroundColor: `rgb(var(--c-${h > 0 ? 'up' : 'down'}) / ${(0.05 + 0.2 * a).toFixed(3)})` };
}

/** Runs of adjacent columns sharing a `group`; null when no column is grouped. */
export function columnGroupRuns<T extends RowData>(
  cols: DataTableColumn<T>[],
): { key: string; label: string | null; cols: DataTableColumn<T>[] }[] | null {
  if (!cols.some((c) => c.group)) return null;
  const runs: { key: string; label: string | null; cols: DataTableColumn<T>[] }[] = [];
  for (const c of cols) {
    const g = c.group ?? null;
    const last = runs[runs.length - 1];
    if (last && last.label === g) last.cols.push(c);
    else runs.push({ key: `${g ?? '_'}-${c.id}`, label: g, cols: [c] });
  }
  return runs;
}

function getValue<T extends RowData>(col: DataTableColumn<T>, row: T): unknown {
  return typeof col.accessor === 'function' ? col.accessor(row) : row[col.accessor];
}

function HeaderLabel<T extends RowData>({ col }: { col: DataTableColumn<T> }) {
  const { def } = useMetric(col.metricKey);
  if (col.metricKey) {
    return (
      <Tooltip content={<MetricTooltipBody def={def} metricKey={col.metricKey} />}>
        <span className="cursor-help truncate underline decoration-line-strong decoration-dotted underline-offset-2">{col.header}</span>
      </Tooltip>
    );
  }
  return (
    <span className="truncate" title={col.headerTitle}>
      {col.header}
    </span>
  );
}

function ColumnsMenu<T extends RowData>({
  columns,
  visibility,
  onToggle,
}: {
  columns: DataTableColumn<T>[];
  visibility: ColumnVisibility;
  onToggle: (id: string, visible: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menuId = useId();
  useEscapeLayer(open, () => setOpen(false));
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);
  const hideable = columns.filter((c) => c.hideable !== false);
  if (hideable.length === 0) return null;
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        className="flex h-6 items-center gap-1 rounded border border-line px-1.5 text-2xs text-fg-2 hover:bg-surface-3 hover:text-fg"
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((o) => !o)}
      >
        <Columns3 className="h-3 w-3" /> Columns
      </button>
      {open && (
        <div
          id={menuId}
          className="absolute right-0 top-7 z-30 max-h-80 w-52 overflow-auto rounded border border-line-strong bg-surface-2 p-1 shadow-xl"
        >
          {hideable.map((c) => {
            const visible = visibility[c.id] !== false;
            return (
              <label key={c.id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs text-fg-2 hover:bg-surface-3">
                <input type="checkbox" checked={visible} onChange={(e) => onToggle(c.id, e.target.checked)} className="accent-accent" />
                <span className="truncate">{typeof c.header === 'string' ? c.header : c.id}</span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function DataTable<T extends RowData>(props: DataTableProps<T>) {
  const {
    columns,
    rows,
    getRowId,
    label,
    total,
    loading,
    error,
    onRetry,
    emptyState,
    rowHeight = 28,
    toolbar,
    hideToolbar,
    className,
  } = props;

  // ---- state (controlled or internal)
  const [innerSort, setInnerSort] = useState<SortingState>(props.initialSort ?? []);
  const sorting = props.sorting ?? innerSort;
  const defaultVisibility = useMemo(() => {
    const v: ColumnVisibility = {};
    for (const c of columns) if (c.defaultHidden) v[c.id] = false;
    return v;
  }, [columns]);
  const [innerVis, setInnerVis] = useState<ColumnVisibility>(defaultVisibility);
  const visibility = props.columnVisibility ?? innerVis;
  const [innerActive, setInnerActive] = useState<string | null>(null);
  const activeRowId = props.activeRowId !== undefined ? props.activeRowId : innerActive;

  const { onSortingChange, onColumnVisibilityChange } = props;
  const setSorting = useCallback(
    (updater: SortingState | ((old: SortingState) => SortingState)) => {
      const next = typeof updater === 'function' ? updater(sorting) : updater;
      if (onSortingChange) onSortingChange(next);
      if (props.sorting === undefined) setInnerSort(next);
    },
    [sorting, onSortingChange, props.sorting],
  );
  const setVisibility = useCallback(
    (updater: ColumnVisibility | ((old: ColumnVisibility) => ColumnVisibility)) => {
      const next = typeof updater === 'function' ? updater(visibility) : updater;
      if (onColumnVisibilityChange) onColumnVisibilityChange(next);
      if (props.columnVisibility === undefined) setInnerVis(next);
    },
    [visibility, onColumnVisibilityChange, props.columnVisibility],
  );

  // ---- TanStack column defs (sorting + visibility only; we render cells ourselves)
  const colById = useMemo(() => new Map(columns.map((c) => [c.id, c])), [columns]);
  const tsColumns = useMemo<ColumnDef<Feat, T>[]>(
    () =>
      columns.map((c) => ({
        id: c.id,
        accessorFn: (row: T) => normalizeCellValue(getValue(c, row)),
        header: c.id,
        enableSorting: c.sortable !== false,
        enableHiding: c.hideable !== false,
        sortDescFirst: c.sortDescFirst ?? isNumericKind(c.format),
        sortUndefined: 'last' as const,
        sortFn: (a: Row<Feat, T>, b: Row<Feat, T>, id: string) => compareValues(a.getValue(id), b.getValue(id)),
      })),
    [columns],
  );

  const data = rows as T[];
  const table = useTable({
    features,
    columns: tsColumns,
    data,
    getRowId,
    state: { sorting, columnVisibility: visibility },
    onSortingChange: setSorting,
    onColumnVisibilityChange: setVisibility,
    enableSortingRemoval: true,
  });

  const modelRows = table.getRowModel().rows;
  const visibleCols = table
    .getVisibleLeafColumns()
    .map((c) => colById.get(c.id)!)
    .filter(Boolean);

  /** Runs of adjacent visible columns sharing a `group` (null = ungrouped spacer). */
  const groupRuns = columnGroupRuns(visibleCols);
  const headRows = groupRuns ? 2 : 1;

  const { onSortedRowsChange } = props;
  useEffect(() => {
    onSortedRowsChange?.(modelRows.map((r) => r.original));
  }, [modelRows, onSortedRowsChange]);

  // ---- virtualisation
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: modelRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    getItemKey: (i) => modelRows[i]?.id ?? i,
    overscan: 12,
  });

  const activeIndex = activeRowId == null ? -1 : modelRows.findIndex((r) => r.id === activeRowId);

  /** Rows carrying a `symbol` become the big chart's J/K list (display order). */
  const registerNavList = useCallback(() => {
    const syms = modelRows.map((m) => (m.original as { symbol?: unknown }).symbol).filter((v): v is string => typeof v === 'string');
    if (syms.length > 0) setNavList(syms);
  }, [modelRows]);

  const setActive = useCallback(
    (index: number) => {
      const r = modelRows[index];
      if (!r) return;
      if (props.activeRowId === undefined) setInnerActive(r.id);
      registerNavList();
      props.onActiveRowChange?.(r.original);
      virtualizer.scrollToIndex(index, { align: 'auto' });
    },
    [modelRows, props, virtualizer, registerNavList],
  );

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget || e.ctrlKey || e.metaKey || e.altKey) return;
    const n = modelRows.length;
    if (n === 0) return;
    const page = Math.max(1, Math.floor((scrollRef.current?.clientHeight ?? rowHeight * 10) / rowHeight) - 1);
    const cur = activeIndex;
    let next: number;
    switch (e.key) {
      case 'ArrowDown':
      case 'j':
      case 'J':
        next = Math.min(n - 1, cur + 1);
        break;
      case 'ArrowUp':
      case 'k':
      case 'K':
        next = Math.max(0, cur < 0 ? 0 : cur - 1);
        break;
      case 'Home':
        next = 0;
        break;
      case 'End':
        next = n - 1;
        break;
      case 'PageDown':
        next = Math.min(n - 1, Math.max(0, cur) + page);
        break;
      case 'PageUp':
        next = Math.max(0, cur - page);
        break;
      case 'Enter':
        if (cur >= 0) {
          e.preventDefault();
          props.onRowActivate?.(modelRows[cur].original);
        }
        return;
      default:
        return;
    }
    e.preventDefault();
    e.stopPropagation();
    setActive(next);
  };

  // ---- layout
  const widthOf = (c: DataTableColumn<T>) => c.width ?? (isNumericKind(c.format) ? 96 : 140);
  const totalWidth = visibleCols.reduce((s, c) => s + widthOf(c), 0);
  const alignOf = (c: DataTableColumn<T>) => c.align ?? (isNumericKind(c.format) ? 'right' : 'left');
  const alignCls = (c: DataTableColumn<T>) =>
    alignOf(c) === 'right' ? 'justify-end text-right' : alignOf(c) === 'center' ? 'justify-center text-center' : 'justify-start text-left';
  const cellStyle = (c: DataTableColumn<T>) => ({
    width: widthOf(c),
    minWidth: widthOf(c),
    flex: c.grow ? '1 0 auto' : '0 0 auto',
  });

  const returned = rows.length;
  const countText =
    total === undefined
      ? `${fmtInt(returned)} rows`
      : total === null
        ? `${fmtInt(returned)} rows · total unknown`
        : total > returned
          ? `${fmtInt(returned)} of ${fmtInt(total)} rows`
          : `${fmtInt(total)} rows`;

  const tableId = useId();
  let body: ReactNode;
  if (error && rows.length === 0) {
    body = <ErrorState error={error} onRetry={onRetry} />;
  } else if (loading && rows.length === 0) {
    body = <SkeletonRows rows={10} columns={Math.min(visibleCols.length, 8)} rowHeight={rowHeight} label={`Loading ${label}`} />;
  } else if (rows.length === 0) {
    body = emptyState ?? <EmptyState title="No rows" detail="Nothing matched for this session." />;
  } else {
    body = null;
  }

  return (
    <div className={cn('flex min-h-0 flex-col', className)}>
      {!hideToolbar && (
        <div className="flex h-9 shrink-0 items-center gap-2 border-b border-line/80 px-3 text-2xs text-fg-3">
          <span className="num" aria-live="polite">
            {countText}
            {total !== undefined && total !== null && total > returned && (
              <span className="ml-1 text-warn" title="The server returned a page of the full result">
                (paged)
              </span>
            )}
          </span>
          {loading && rows.length > 0 && <span className="text-info">refreshing…</span>}
          <div className="ml-auto flex items-center gap-2">
            {toolbar}
            <ColumnsMenu columns={columns} visibility={visibility} onToggle={(id, v) => setVisibility({ ...visibility, [id]: v })} />
          </div>
        </div>
      )}
      <div
        ref={scrollRef}
        tabIndex={0}
        role="region"
        aria-label={label}
        aria-describedby={tableId}
        onKeyDown={onKeyDown}
        className="relative min-h-0 flex-1 overflow-auto bg-surface outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-focus"
      >
        <table
          id={tableId}
          role="grid"
          aria-label={label}
          aria-rowcount={modelRows.length + headRows}
          aria-colcount={visibleCols.length}
          className="grid text-table"
          style={{ minWidth: totalWidth }}
        >
          <thead className="sticky top-0 z-10 grid bg-surface-2">
            {groupRuns && (
              <tr className="flex w-full border-b border-line/70" aria-rowindex={1}>
                {groupRuns.map((run) => {
                  const w = run.cols.reduce((sum, c) => sum + widthOf(c), 0);
                  const grow = run.cols.some((c) => c.grow);
                  const sticky = run.cols.length === 1 && run.cols[0].sticky;
                  return (
                    <th
                      key={run.key}
                      scope="colgroup"
                      colSpan={run.cols.length}
                      className={cn(
                        'flex h-6 items-end px-2 pb-1',
                        run.label && 'mx-1 justify-center border-b border-line-strong/80 px-1',
                        sticky && 'sticky left-0 z-20 bg-surface-2',
                      )}
                      style={{ width: run.label ? w - 8 : w, minWidth: run.label ? w - 8 : w, flex: grow ? '1 0 auto' : '0 0 auto' }}
                    >
                      {run.label && <span className="mp-label truncate !text-[10.5px] !tracking-[0.08em]">{run.label}</span>}
                    </th>
                  );
                })}
              </tr>
            )}
            <tr className="flex w-full border-b border-line-strong" aria-rowindex={headRows}>
              {table.getVisibleLeafColumns().map((tc, ci) => {
                const c = colById.get(tc.id);
                if (!c) return null;
                const sorted = tc.getIsSorted();
                const canSort = tc.getCanSort();
                const ariaSort = sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : canSort ? 'none' : undefined;
                return (
                  <th
                    key={tc.id}
                    scope="col"
                    aria-sort={ariaSort}
                    aria-colindex={ci + 1}
                    className={cn(
                      'flex h-8 items-center px-2 text-2xs font-semibold uppercase tracking-[0.05em] text-fg-3',
                      alignCls(c),
                      c.sticky && 'sticky left-0 z-20 bg-surface-2',
                    )}
                    style={cellStyle(c)}
                  >
                    {canSort ? (
                      <button
                        type="button"
                        onClick={tc.getToggleSortingHandler()}
                        className={cn(
                          'flex min-w-0 items-center gap-1 transition-colors duration-fast hover:text-fg',
                          sorted && 'text-accent',
                        )}
                      >
                        {alignOf(c) === 'right' && <SortIcon dir={sorted} />}
                        <HeaderLabel col={c} />
                        {alignOf(c) !== 'right' && <SortIcon dir={sorted} />}
                      </button>
                    ) : (
                      <HeaderLabel col={c} />
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          {body === null && (
            <tbody className="relative grid" style={{ height: virtualizer.getTotalSize() }}>
              {virtualizer.getVirtualItems().map((vi) => {
                const r = modelRows[vi.index];
                const isActive = vi.index === activeIndex;
                return (
                  <tr
                    key={r.id}
                    data-index={vi.index}
                    aria-rowindex={vi.index + 1 + headRows}
                    aria-selected={isActive}
                    data-row-id={r.id}
                    onClick={() => {
                      setActive(vi.index);
                      props.onRowClick?.(r.original);
                    }}
                    onDoubleClick={() => {
                      registerNavList();
                      props.onRowActivate?.(r.original);
                    }}
                    data-odd={vi.index % 2 === 1 || undefined}
                    data-active={isActive || undefined}
                    className="mp-tr absolute left-0 top-0 flex w-full cursor-default border-b border-line/40"
                    style={{ transform: `translateY(${vi.start}px)`, height: rowHeight }}
                  >
                    {visibleCols.map((c, ci) => {
                      const raw = getValue(c, r.original);
                      const v = normalizeCellValue(raw);
                      const heat = c.heat && v !== undefined ? heatStyle(c.heat(v, r.original)) : undefined;
                      let content: ReactNode;
                      if (v === undefined && !c.renderNull) content = <span className="text-fg-3">{DASH}</span>;
                      else if (c.cell) content = c.cell(v ?? null, r.original);
                      else content = fmtValue(v, c.format ?? 'text', c.digits);
                      return (
                        <td
                          key={c.id}
                          aria-colindex={ci + 1}
                          className={cn(
                            'flex items-center overflow-hidden whitespace-nowrap px-2',
                            alignCls(c),
                            isNumericKind(c.format) ? 'num text-fg' : 'text-fg-2',
                            c.sticky && 'mp-td-sticky sticky left-0 z-[1]',
                          )}
                          style={heat ? { ...cellStyle(c), ...heat } : cellStyle(c)}
                        >
                          {content}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          )}
        </table>
        {body}
      </div>
    </div>
  );
}

function SortIcon({ dir }: { dir: false | 'asc' | 'desc' }) {
  if (dir === 'asc') return <ArrowUp className="h-3 w-3 shrink-0" aria-hidden />;
  if (dir === 'desc') return <ArrowDown className="h-3 w-3 shrink-0" aria-hidden />;
  return <span className="inline-block w-3 shrink-0" aria-hidden />;
}
