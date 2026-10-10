/**
 * Small pieces shared by the Groups and Deals tabs: segmented control, data
 * source note (partial / unavailable honesty), zone-coloured numbers and the
 * RRG quadrant chip.
 */
import type { ReactNode } from 'react';
import { cn } from '../../lib/cn';
import { fmtValue, isNum, type FormatKind } from '../../lib/fmt';
import { TONE_TEXT, useMetric } from '../../metrics/dictionary';
import { Chip, type ChipTone } from '../../ui/Chip';
import { MetricTooltipBody } from '../../ui/MetricTooltip';
import { Tooltip } from '../../ui/Tooltip';

// Segmented control and source note moved to the shared UI kit (one UI standard across tabs).
export { Segmented, type SegmentedOption } from '../../ui/Segmented';
export { SourceNote } from '../../ui/SourceNote';

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
