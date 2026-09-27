/**
 * Small pieces shared by the Groups and Deals tabs: segmented control, data
 * source note (partial / unavailable honesty), zone-coloured numbers and the
 * RRG quadrant chip.
 */
import { Info } from 'lucide-react';
import type { ReactNode } from 'react';
import type { EnvelopeMeta } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtValue, isNum, type FormatKind } from '../../lib/fmt';
import { TONE_TEXT, useMetric } from '../../metrics/dictionary';
import { Chip, type ChipTone } from '../../ui/Chip';
import { MetricTooltipBody } from '../../ui/MetricTooltip';
import { Tooltip } from '../../ui/Tooltip';

export interface SegmentedOption<V extends string> {
  value: V;
  label: ReactNode;
  title?: string;
}

export function Segmented<V extends string>({
  options,
  value,
  onChange,
  label,
  size = 'sm',
}: {
  options: readonly SegmentedOption<V>[];
  value: V;
  onChange: (v: V) => void;
  label: string;
  size?: 'xs' | 'sm';
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex shrink-0 rounded border border-line bg-surface-2 p-px">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={cn(
            'whitespace-nowrap rounded-[3px] font-medium',
            size === 'xs' ? 'px-1.5 py-0.5 text-2xs' : 'px-2 py-0.5 text-xs',
            o.value === value ? 'bg-surface-3 text-fg shadow-sm' : 'text-fg-3 hover:text-fg',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** "Computed live" / "Partial" / "Unavailable" chip with the server's reason in a tooltip. */
export function SourceNote({ meta, liveLabel = 'computed live' }: { meta: EnvelopeMeta | undefined; liveLabel?: string }) {
  if (!meta) return null;
  const status = meta.status ?? 'ok';
  if (status === 'ok') {
    return (
      <Chip tone="positive" title={`Source: ${(meta.sources ?? []).join(', ')}`}>
        {(meta.sources ?? [])[0] ?? 'ok'}
      </Chip>
    );
  }
  const tone: ChipTone = status === 'partial' ? 'warn' : 'negative';
  return (
    <Tooltip
      content={
        <div className="max-w-sm space-y-1">
          <div className="font-medium text-fg">{status === 'partial' ? 'Partial source' : 'Unavailable'}</div>
          {meta.reason && <div className="text-fg-2">{meta.reason}</div>}
          {(meta.notes ?? []).map((n) => (
            <div key={n} className="text-fg-3">
              {n}
            </div>
          ))}
          {meta.sources && meta.sources.length > 0 && <div className="text-fg-3">Tables: {meta.sources.join(', ')}</div>}
        </div>
      }
    >
      <span tabIndex={0} className="inline-flex">
        <Chip tone={tone} icon={<Info className="h-3 w-3" />}>
          {status === 'partial' ? liveLabel : 'unavailable'}
        </Chip>
      </span>
    </Tooltip>
  );
}

/** A number coloured by its dictionary zone (no tooltip: the column header carries it). */
export function ZoneNum({
  metricKey,
  value,
  format = 'num',
  digits,
  className,
  zoneValue,
}: {
  metricKey: string;
  value: number | null | undefined;
  format?: FormatKind;
  digits?: number;
  className?: string;
  /** Value used for the zone when it differs from the displayed one. */
  zoneValue?: number | null;
}) {
  const { toneFor } = useMetric(metricKey);
  const tone = toneFor(zoneValue !== undefined ? zoneValue : value);
  return (
    <span className={cn('num', isNum(value) ? (tone ? TONE_TEXT[tone] : 'text-fg') : 'text-fg-3', className)}>
      {fmtValue(value, format, digits)}
    </span>
  );
}

/** Number with a full dictionary tooltip (for headline figures). */
export function MetricInline({
  metricKey,
  label,
  value,
  children,
}: {
  metricKey: string;
  label?: ReactNode;
  /** Highlights the matching zone in the tooltip. */
  value?: number | null;
  children: ReactNode;
}) {
  const { def, zoneFor } = useMetric(metricKey);
  return (
    <Tooltip content={<MetricTooltipBody def={def} metricKey={metricKey} activeZone={zoneFor(value)} />}>
      <span tabIndex={0} className="inline-flex cursor-help flex-col gap-0.5">
        <span className="text-2xs uppercase tracking-wide text-fg-3 underline decoration-line-strong decoration-dotted underline-offset-2">
          {label ?? def?.plain_name ?? metricKey}
        </span>
        {children}
      </span>
    </Tooltip>
  );
}

export type Quadrant = 'Leading' | 'Weakening' | 'Lagging' | 'Improving';
export const QUADRANTS: Quadrant[] = ['Leading', 'Improving', 'Weakening', 'Lagging'];
export const QUADRANT_TONE: Record<Quadrant, ChipTone> = {
  Leading: 'positive',
  Improving: 'info',
  Weakening: 'warn',
  Lagging: 'negative',
};
/** Token names for canvas/SVG use. */
export const QUADRANT_TOKEN: Record<Quadrant, 'up' | 'info' | 'warn' | 'down'> = {
  Leading: 'up',
  Improving: 'info',
  Weakening: 'warn',
  Lagging: 'down',
};

export function isQuadrant(v: unknown): v is Quadrant {
  return v === 'Leading' || v === 'Weakening' || v === 'Lagging' || v === 'Improving';
}

export function QuadrantChip({ quadrant, days }: { quadrant: string | null | undefined; days?: number | null }) {
  if (!isQuadrant(quadrant)) return <span className="text-fg-3">—</span>;
  return (
    <Chip tone={QUADRANT_TONE[quadrant]} title={days != null ? `${quadrant} for ${days} session${days === 1 ? '' : 's'}` : quadrant}>
      {quadrant}
      {days != null && <span className="num opacity-75">{days}d</span>}
    </Chip>
  );
}

/** Signed integer rank change: positive = climbed (green). */
export function RankDelta({ value }: { value: number | null | undefined }) {
  if (!isNum(value)) return <span className="num text-fg-3">—</span>;
  return (
    <span className={cn('num', value > 0 ? 'text-up' : value < 0 ? 'text-down' : 'text-fg-3')}>
      {value > 0 ? `▲${value}` : value < 0 ? `▼${Math.abs(value)}` : '0'}
    </span>
  );
}
