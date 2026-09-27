/**
 * Shared Research building blocks: dictionary-backed terms, sample-size
 * badges, the intentional "evidence pending" state, panel state handling and
 * a small token-coloured SVG path chart (fans / movers-vs-controls paths).
 */
import type { UseQueryResult } from '@tanstack/react-query';
import { FlaskConical, Hourglass } from 'lucide-react';
import { useMemo, type ReactNode } from 'react';
import { isUnavailable } from '../../api/client';
import type { Envelope, EnvelopeMeta } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtInt, isNum } from '../../lib/fmt';
import { useMetric } from '../../metrics/dictionary';
import { ErrorState } from '../../ui/ErrorState';
import { MetricTooltipBody } from '../../ui/MetricTooltip';
import { Skeleton, SkeletonRows } from '../../ui/Skeleton';
import { Tooltip } from '../../ui/Tooltip';
import { useFixtureMode } from './data';
import { MIN_SAMPLE } from './model';

// ------------------------------------------------------------------ terms and n

/** A label explained by the metric dictionary (dotted underline + tooltip). */
export function Term({ k, children, className }: { k: string; children?: ReactNode; className?: string }) {
  const { def } = useMetric(k);
  return (
    <Tooltip content={<MetricTooltipBody def={def} metricKey={k} />}>
      <span tabIndex={0} data-term={k} className={cn('cursor-help underline decoration-line-strong decoration-dotted underline-offset-2', className)}>
        {children ?? def?.plain_name ?? k}
      </span>
    </Tooltip>
  );
}

/** Sample size, always printed next to a statistic. */
export function SampleN({ n, label = 'n', className }: { n: number | null | undefined; label?: string; className?: string }) {
  const low = isNum(n) && n < MIN_SAMPLE;
  return (
    <Term k="sample_n" className={cn('num text-2xs no-underline', low ? 'text-warn' : 'text-fg-3', className)}>
      {label}={isNum(n) ? fmtInt(n) : '—'}
    </Term>
  );
}

/** A number with its n, or "insufficient sample" when n < 30 (spec 5). */
export function Stat({
  value,
  n,
  format,
  className,
  enforceMin = true,
}: {
  value: number | null | undefined;
  n: number | null | undefined;
  format: (v: number) => string;
  className?: string;
  /** Aggregates enforce n >= 30; nearest-neighbour summaries (k = 10) print with n instead. */
  enforceMin?: boolean;
}) {
  const insufficient = enforceMin && (!isNum(n) || n < MIN_SAMPLE);
  return (
    <span className={cn('inline-flex items-baseline gap-1.5', className)}>
      {insufficient ? (
        <span className="text-2xs italic text-fg-3">insufficient sample</span>
      ) : (
        <span className={cn('num', isNum(value) ? 'text-fg' : 'text-fg-3')}>{isNum(value) ? format(value) : '—'}</span>
      )}
      <SampleN n={n} />
    </span>
  );
}

// ------------------------------------------------------------------ cards

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cn('flex min-h-0 flex-col rounded border border-line bg-surface', className)}>
      <header className="flex items-center gap-2 border-b border-line px-3 py-2">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-xs font-semibold uppercase tracking-wide text-fg-2">{title}</h2>
          {subtitle && <div className="truncate text-2xs text-fg-3">{subtitle}</div>}
        </div>
        {actions}
      </header>
      <div className={cn('min-h-0 flex-1', bodyClassName)}>{children}</div>
    </section>
  );
}

// ------------------------------------------------------------------ pending / state

export function EvidencePending({ what, meta, compact }: { what: ReactNode; meta?: EnvelopeMeta | null; compact?: boolean }) {
  const fx = useFixtureMode();
  return (
    <div role="status" data-state="evidence-pending" className={cn('flex h-full items-center justify-center', compact ? 'p-3' : 'p-6')}>
      <div className="flex max-w-lg gap-3 rounded border border-dashed border-violet/40 bg-violet/5 p-4">
        <Hourglass className="mt-0.5 h-5 w-5 shrink-0 text-violet" aria-hidden />
        <div className="space-y-1.5">
          <div className="text-sm font-medium text-fg">Evidence is being computed — available after the next rebuild</div>
          <div className="text-xs text-fg-2">{what}</div>
          {(meta?.reason || (meta?.sources && meta.sources.length > 0)) && (
            <div className="space-y-0.5 text-2xs text-fg-3">
              {meta?.reason && <div>Server: {meta.reason}</div>}
              {meta?.sources && meta.sources.length > 0 && (
                <div>
                  Needs <span className="font-mono">{meta.sources.join(', ')}</span>
                </div>
              )}
            </div>
          )}
          <div className="text-2xs text-fg-3">No number is shown until it can be shown with its sample size.</div>
          {fx.available && !fx.on && (
            <button
              type="button"
              onClick={() => fx.set(true)}
              className="mt-1 inline-flex items-center gap-1 rounded border border-line bg-surface-2 px-2 py-0.5 text-2xs text-fg-2 hover:bg-surface-3"
            >
              <FlaskConical className="h-3 w-3" aria-hidden /> Preview with fixtures (dev)
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

type EnvQuery<R> = UseQueryResult<Envelope<R>>;

/** Loading / error / unavailable handling for one Research query. */
export function QueryState<R>({
  q,
  what,
  children,
  skeleton = 'rows',
  compact,
}: {
  q: EnvQuery<R>;
  what: ReactNode;
  children: (env: Envelope<R>) => ReactNode;
  skeleton?: 'rows' | 'block';
  compact?: boolean;
}) {
  if (q.isPending) {
    return skeleton === 'rows' ? (
      <div className="p-3">
        <SkeletonRows rows={6} columns={5} label="Loading" />
      </div>
    ) : (
      <div className="p-3">
        <Skeleton height={160} />
      </div>
    );
  }
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} compact={compact} />;
  const env = q.data;
  if (!env || isUnavailable(env)) return <EvidencePending what={what} meta={env?.meta} compact={compact} />;
  return <>{children(env)}</>;
}

// ------------------------------------------------------------------ path chart

export type PathTone = 'accent' | 'up' | 'down' | 'neutral' | 'muted' | 'violet';

const STROKE: Record<PathTone, string> = {
  accent: 'stroke-accent',
  up: 'stroke-up',
  down: 'stroke-down',
  neutral: 'stroke-fg-2',
  muted: 'stroke-fg-3',
  violet: 'stroke-violet',
};

export interface PathSeries {
  id: string;
  label: string;
  points: { x: number; y: number | null }[];
  tone: PathTone;
  strokeWidth?: number;
  dashed?: boolean;
  opacity?: number;
}

export interface PathChartProps {
  series: PathSeries[];
  band?: { x: number; lo: number; hi: number }[];
  xTicks: { x: number; label: string }[];
  yFormat: (v: number) => string;
  /** Vertical reference line (event / today). */
  markerX?: number;
  markerLabel?: string;
  zeroLine?: boolean;
  height?: number;
  label: string;
  className?: string;
}

const W = 640;

/** Multi-line SVG chart in session offsets; colours are tokens only. NULL breaks a line. */
export function PathChart({ series, band, xTicks, yFormat, markerX, markerLabel, zeroLine = true, height = 200, label, className }: PathChartProps) {
  const geo = useMemo(() => {
    const xs = [...series.flatMap((s) => s.points.map((p) => p.x)), ...xTicks.map((t) => t.x), ...(band ?? []).map((b) => b.x)];
    const ys = [
      ...series.flatMap((s) => s.points.map((p) => p.y).filter(isNum)),
      ...(band ?? []).flatMap((b) => [b.lo, b.hi]),
      ...(zeroLine ? [0] : []),
    ];
    if (!xs.length || !ys.length) return null;
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    let minY = Math.min(...ys);
    let maxY = Math.max(...ys);
    const padY = (maxY - minY || 1) * 0.08;
    minY -= padY;
    maxY += padY;
    const left = 44;
    const right = 8;
    const top = 8;
    const bottom = 20;
    const sx = (x: number) => left + ((x - minX) / (maxX - minX || 1)) * (W - left - right);
    const sy = (y: number) => top + (1 - (y - minY) / (maxY - minY || 1)) * (height - top - bottom);
    const yTicks = [minY + padY, (minY + maxY) / 2, maxY - padY];
    return { sx, sy, yTicks, left, right, top, bottom };
  }, [series, band, xTicks, zeroLine, height]);

  if (!geo) return <div className="p-4 text-center text-2xs text-fg-3">No path to draw</div>;
  const { sx, sy, yTicks, left, bottom } = geo;
  const pathD = (pts: { x: number; y: number | null }[]) => {
    let d = '';
    let pen = false;
    for (const p of pts) {
      if (!isNum(p.y)) {
        pen = false;
        continue;
      }
      d += `${pen ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  const bandD = band?.length
    ? `M${band.map((b) => `${sx(b.x).toFixed(1)},${sy(b.hi).toFixed(1)}`).join('L')}L${[...band]
        .reverse()
        .map((b) => `${sx(b.x).toFixed(1)},${sy(b.lo).toFixed(1)}`)
        .join('L')}Z`
    : null;

  return (
    <svg viewBox={`0 0 ${W} ${height}`} role="img" aria-label={label} className={cn('block w-full', className)} style={{ maxHeight: height }}>
      {yTicks.map((t, i) => (
        <g key={i}>
          <line x1={left} x2={W - 8} y1={sy(t)} y2={sy(t)} className="stroke-line" strokeWidth={0.5} />
          <text x={left - 4} y={sy(t) + 3} textAnchor="end" className="fill-fg-3 font-mono" fontSize={10}>
            {yFormat(t)}
          </text>
        </g>
      ))}
      {zeroLine && <line x1={left} x2={W - 8} y1={sy(0)} y2={sy(0)} className="stroke-line-strong" strokeDasharray="3 3" strokeWidth={0.75} />}
      {bandD && <path d={bandD} className="fill-accent/10 stroke-none" />}
      {markerX !== undefined && (
        <g>
          <line x1={sx(markerX)} x2={sx(markerX)} y1={4} y2={height - bottom} className="stroke-warn" strokeDasharray="2 3" strokeWidth={1} />
          {markerLabel && (
            <text x={sx(markerX) + 3} y={12} className="fill-warn" fontSize={10}>
              {markerLabel}
            </text>
          )}
        </g>
      )}
      {series.map((s) => (
        <path
          key={s.id}
          d={pathD(s.points)}
          fill="none"
          className={STROKE[s.tone]}
          strokeWidth={s.strokeWidth ?? 1.25}
          strokeDasharray={s.dashed ? '4 3' : undefined}
          strokeOpacity={s.opacity ?? 1}
          strokeLinejoin="round"
          strokeLinecap="round"
        >
          <title>{s.label}</title>
        </path>
      ))}
      {xTicks.map((t) => (
        <text key={t.x} x={sx(t.x)} y={height - 6} textAnchor="middle" className="fill-fg-3 font-mono" fontSize={10}>
          {t.label}
        </text>
      ))}
    </svg>
  );
}

export function Legend({ items }: { items: { label: ReactNode; tone: PathTone; dashed?: boolean }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-2xs text-fg-3">
      {items.map((it, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          <svg width={16} height={6} aria-hidden>
            <line x1={0} x2={16} y1={3} y2={3} className={STROKE[it.tone]} strokeWidth={2} strokeDasharray={it.dashed ? '4 3' : undefined} />
          </svg>
          {it.label}
        </span>
      ))}
    </div>
  );
}
