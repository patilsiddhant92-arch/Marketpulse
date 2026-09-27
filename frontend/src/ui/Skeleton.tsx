import type { CSSProperties } from 'react';
import { cn } from '../lib/cn';

export interface SkeletonProps {
  width?: number | string;
  height?: number | string;
  className?: string;
  style?: CSSProperties;
}

/** Loading placeholder block. aria-hidden; pair with a visually-hidden status. */
export function Skeleton({ width, height = 12, className, style }: SkeletonProps) {
  return <div aria-hidden className={cn('animate-pulse rounded bg-surface-3', className)} style={{ width, height, ...style }} />;
}

export interface SkeletonRowsProps {
  rows?: number;
  columns?: number;
  rowHeight?: number;
  className?: string;
  label?: string;
}

/** Table-shaped skeleton (28px rows by default). */
export function SkeletonRows({ rows = 8, columns = 6, rowHeight = 28, className, label = 'Loading' }: SkeletonRowsProps) {
  return (
    <div className={cn('flex flex-col', className)} role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex items-center gap-3 border-b border-line/50 px-2" style={{ height: rowHeight }}>
          {Array.from({ length: columns }, (_, c) => (
            <Skeleton key={c} height={10} className="flex-1" style={{ opacity: 1 - c * 0.08 }} />
          ))}
        </div>
      ))}
    </div>
  );
}
