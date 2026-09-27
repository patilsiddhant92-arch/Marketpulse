import { useMemo } from 'react';
import { cn } from '../lib/cn';

export interface SparkProps {
  /** Values oldest -> newest. NULLs break the line (no interpolation). */
  values: readonly (number | null | undefined)[];
  width?: number;
  height?: number;
  /** Colour: auto = up if last >= first, else down. */
  tone?: 'auto' | 'up' | 'down' | 'neutral' | 'accent';
  /** Horizontal reference line value (e.g. 0 or 50). */
  baseline?: number;
  showLastDot?: boolean;
  /** Soft filled area under the line (KPI tiles). */
  area?: boolean;
  /** Accessible description, e.g. "Strength rank, 60 sessions". */
  label: string;
  className?: string;
}

const STROKE = {
  up: 'stroke-up',
  down: 'stroke-down',
  neutral: 'stroke-fg-3',
  accent: 'stroke-accent',
} as const;
const FILL = { up: 'fill-up', down: 'fill-down', neutral: 'fill-fg-3', accent: 'fill-accent' } as const;

/** Tiny inline SVG line chart for tables and cards. */
export function Spark({
  values,
  width = 72,
  height = 20,
  tone = 'auto',
  baseline,
  showLastDot = true,
  area = false,
  label,
  className,
}: SparkProps) {
  const geo = useMemo(() => {
    const nums = values.filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
    if (nums.length < 2) return null;
    let min = Math.min(...nums);
    let max = Math.max(...nums);
    if (baseline !== undefined) {
      min = Math.min(min, baseline);
      max = Math.max(max, baseline);
    }
    const span = max - min || 1;
    const pad = 2;
    const x = (i: number) => pad + (i * (width - 2 * pad)) / Math.max(1, values.length - 1);
    const y = (v: number) => pad + (1 - (v - min) / span) * (height - 2 * pad);
    const segments: string[] = [];
    let cur = '';
    values.forEach((v, i) => {
      if (typeof v !== 'number' || !Number.isFinite(v)) {
        if (cur) segments.push(cur);
        cur = '';
        return;
      }
      cur += `${cur ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    });
    if (cur) segments.push(cur);
    const areaD = segments
      .map((seg) => {
        const pts = seg.slice(1).split('L');
        const x0 = pts[0].split(',')[0];
        const x1 = pts[pts.length - 1].split(',')[0];
        return `${seg}L${x1},${height}L${x0},${height}Z`;
      })
      .join(' ');
    let lastIdx = values.length - 1;
    while (lastIdx >= 0 && (typeof values[lastIdx] !== 'number' || !Number.isFinite(values[lastIdx] as number))) lastIdx--;
    const first = nums[0];
    const last = nums[nums.length - 1];
    return {
      d: segments.join(' '),
      areaD,
      last: lastIdx >= 0 ? { cx: x(lastIdx), cy: y(values[lastIdx] as number) } : null,
      base: baseline !== undefined ? y(baseline) : null,
      rising: last >= first,
    };
  }, [values, width, height, baseline]);

  if (!geo) {
    return (
      <span className={cn('inline-block text-center text-2xs text-fg-3', className)} style={{ width }} aria-label={`${label}: no data`}>
        {'—'}
      </span>
    );
  }
  const t = tone === 'auto' ? (geo.rising ? 'up' : 'down') : tone;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className={className}>
      {geo.base !== null && <line x1={0} x2={width} y1={geo.base} y2={geo.base} className="stroke-line-strong" strokeDasharray="2 2" />}
      {area && <path d={geo.areaD} className={FILL[t]} fillOpacity={0.12} stroke="none" />}
      <path d={geo.d} fill="none" strokeWidth={1.25} className={STROKE[t]} strokeLinejoin="round" strokeLinecap="round" />
      {showLastDot && geo.last && <circle cx={geo.last.cx} cy={geo.last.cy} r={1.75} className={FILL[t]} />}
    </svg>
  );
}
