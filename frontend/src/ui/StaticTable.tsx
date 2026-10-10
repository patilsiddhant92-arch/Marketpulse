/** StaticTable — the shared small table for short study / evidence lists on every tab (no virtualisation, no sort). */
import type { ReactNode } from 'react';
import { cn } from '../lib/cn';

export interface StaticColumn<T> {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  align?: 'left' | 'right';
  title?: string;
}

/** Small static table (a handful of rows; the virtualised DataTable is for long lists). Same header / row look as DataTable. */
export function StaticTable<T>({
  label,
  columns,
  rows,
  rowKey,
  rowClassName,
  empty,
  className,
}: {
  label: string;
  columns: readonly StaticColumn<T>[];
  rows: readonly T[];
  rowKey: (row: T, i: number) => string;
  rowClassName?: (row: T) => string | undefined;
  empty?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('overflow-auto', className)}>
      <table className="w-full text-table" aria-label={label}>
        <thead className="bg-surface-2 text-2xs uppercase tracking-wide text-fg-3">
          <tr>
            {columns.map((c) => (
              <th key={c.id} title={c.title} className={cn('px-2 py-1.5 font-medium', c.align === 'right' ? 'text-right' : 'text-left')}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-2 py-4 text-center text-2xs text-fg-3">
                {empty ?? 'Nothing to show.'}
              </td>
            </tr>
          ) : (
            rows.map((r, i) => (
              <tr key={rowKey(r, i)} className={cn('border-t border-line', rowClassName?.(r))}>
                {columns.map((c) => (
                  <td key={c.id} className={cn('px-2 py-1', c.align === 'right' ? 'num text-right' : 'text-left')}>
                    {c.cell(r)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
