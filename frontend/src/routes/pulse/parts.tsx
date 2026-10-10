/** Small shared pieces for the Pulse tab. */
import type { ReactNode } from 'react';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { SkeletonRows } from '../../ui/Skeleton';
import type { PulseResult } from './data';

/** Loading / error / honest-empty wrapper for one section. */
export function SectionBody<R, C>({
  q,
  children,
  rows = 4,
  emptyTitle = 'No data for this session',
}: {
  q: PulseResult<R, C>;
  children: ReactNode;
  rows?: number;
  emptyTitle?: string;
}) {
  if (q.error) return <ErrorState error={q.error} onRetry={q.refetch} compact />;
  if (q.isLoading && !q.rows) return <SkeletonRows rows={rows} columns={4} label="Loading" />;
  if (q.unavailable || !q.rows || q.rows.length === 0)
    return <EmptyState compact title={emptyTitle} detail={q.meta?.reason ?? undefined} />;
  return <>{children}</>;
}

/** Muted footnote line under a section. */
export function Note({ children }: { children: ReactNode }) {
  return <p className="px-3 pb-2 pt-1 text-2xs leading-snug text-fg-3">{children}</p>;
}

/** Inline SVG line chart with an optional shaded band (normal range). */
export function LineChart({
  series,
  labels,
  band,
  yMin,
  yMax,
  height = 200,
  yFormat = (v: number) => `${Math.round(v)}%`,
  label,
}: {
  series: { values: (number | null)[]; colour: string; name: string }[];
  labels: string[];
  band?: [number, number] | null;
  yMin?: number;
  yMax?: number;
  height?: number;
  yFormat?: (v: number) => string;
  label: string;
}) {
  const w = 560;
  const h = height;
  const pl = 34;
  const pb = 18;
  const all = series.flatMap((s) => s.values).filter((v): v is number => typeof v === 'number');
  const lo = yMin ?? Math.min(...all, band?.[0] ?? Infinity);
  const hi = yMax ?? Math.max(...all, band?.[1] ?? -Infinity);
  const n = Math.max(1, labels.length - 1);
  const X = (i: number) => pl + (i * (w - pl - 6)) / n;
  const Y = (v: number) => h - pb - ((v - lo) * (h - pb - 6)) / (hi - lo || 1);
  const ticks = [lo, lo + (hi - lo) / 2, hi];
  const xt = labels.length > 1 ? [0, Math.floor(n / 2), n] : [0];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label={label} className="text-2xs">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={pl} x2={w} y1={Y(t)} y2={Y(t)} className="stroke-line" />
          <text x={2} y={Y(t) + 3} className="fill-fg-3" fontSize={10}>
            {yFormat(t)}
          </text>
        </g>
      ))}
      {band && (
        <rect x={pl} width={w - pl} y={Y(band[1])} height={Math.max(0, Y(band[0]) - Y(band[1]))} className="fill-up" fillOpacity={0.07} />
      )}
      {series.map((s) => {
        let d = '';
        s.values.forEach((v, i) => {
          if (typeof v === 'number') d += `${d ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
        });
        return <path key={s.name} d={d} fill="none" stroke={s.colour} strokeWidth={1.8} />;
      })}
      {xt.map((i) => (
        <text key={i} x={Math.min(X(i) - 14, w - 40)} y={h - 4} className="fill-fg-3" fontSize={10}>
          {labels[i]}
        </text>
      ))}
    </svg>
  );
}

export function Legend({ items }: { items: { name: string; colour: string; dashed?: boolean }[] }) {
  return (
    <div className="flex flex-wrap gap-3 px-3 pb-2 text-2xs text-fg-3">
      {items.map((i) => (
        <span key={i.name} className="inline-flex items-center gap-1">
          <i
            className="inline-block h-0.5 w-3"
            style={{ background: i.dashed ? 'transparent' : i.colour, borderTop: i.dashed ? `2px dashed ${i.colour}` : undefined }}
          />
          {i.name}
        </span>
      ))}
    </div>
  );
}

/** Sparkline with a shaded band (e.g. the mood's normal 45–55 band). Fixed y-range so the band means the same every day. */
export function BandSpark({
  values,
  band,
  yMin = 0,
  yMax = 100,
  width = 240,
  height = 44,
  colour = 'rgb(var(--c-accent))',
  label,
}: {
  values: (number | null)[];
  band: [number, number];
  yMin?: number;
  yMax?: number;
  width?: number;
  height?: number;
  colour?: string;
  label: string;
}) {
  const n = Math.max(1, values.length - 1);
  const X = (i: number) => 2 + (i * (width - 4)) / n;
  const Y = (v: number) => height - 2 - ((v - yMin) * (height - 4)) / (yMax - yMin || 1);
  let d = '';
  let last: [number, number] | null = null;
  values.forEach((v, i) => {
    if (typeof v === 'number') {
      d += `${d ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
      last = [X(i), Y(v)];
    }
  });
  const lp = last as [number, number] | null;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <rect x={0} width={width} y={Y(band[1])} height={Y(band[0]) - Y(band[1])} className="fill-fg-3" fillOpacity={0.12} />
      <path d={d} fill="none" stroke={colour} strokeWidth={1.6} />
      {lp && <circle cx={lp[0]} cy={lp[1]} r={2.6} fill={colour} />}
    </svg>
  );
}
