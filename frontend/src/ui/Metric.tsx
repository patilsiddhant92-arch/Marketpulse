import type { ReactNode } from 'react';
import { fmtValue, isNum, type FormatKind } from '../lib/fmt';
import { cn } from '../lib/cn';
import { TONE_TEXT, useMetric } from '../metrics/dictionary';
import { MetricTooltipBody } from './MetricTooltip';
import { Tooltip } from './Tooltip';

export interface MetricProps {
  /** Metric-dictionary key; drives label, tooltip and zone colour. */
  metricKey: string;
  value: number | null | undefined;
  format?: FormatKind;
  digits?: number;
  /** Override the dictionary plain_name. */
  label?: ReactNode;
  /** Show the label above the value (default true). */
  showLabel?: boolean;
  /** Optional change figure shown after the value, e.g. "+3" rank delta. */
  delta?: number | null;
  deltaFormat?: FormatKind;
  size?: 'sm' | 'md' | 'lg';
  /** Colour by zone (default true). Off for values whose zone is not meaningful. */
  zoneColor?: boolean;
  className?: string;
}

const SIZES = { sm: 'text-xs', md: 'text-sm', lg: 'text-xl' } as const;

/** A number with its zone colour and a metric-dictionary tooltip. NULL -> "—". */
export function Metric({
  metricKey,
  value,
  format = 'num',
  digits,
  label,
  showLabel = true,
  delta,
  deltaFormat = 'signed',
  size = 'md',
  zoneColor = true,
  className,
}: MetricProps) {
  const { def, zoneFor, toneFor } = useMetric(metricKey);
  const zone = zoneFor(value);
  const tone = zoneColor ? toneFor(value) : undefined;
  const text = fmtValue(value, format, digits);
  const name = label ?? def?.plain_name ?? metricKey;
  return (
    <Tooltip content={<MetricTooltipBody def={def} metricKey={metricKey} activeZone={zone} />}>
      <span className={cn('inline-flex flex-col gap-0.5', className)} tabIndex={0} data-metric={metricKey}>
        {showLabel && <span className="text-2xs uppercase tracking-wide text-fg-3">{name}</span>}
        <span className={cn('num font-medium', SIZES[size], tone ? TONE_TEXT[tone] : 'text-fg', !isNum(value) && 'text-fg-3')}>
          {text}
          {delta !== undefined && (
            <span
              className={cn('ml-1 text-2xs', isNum(delta) ? (delta > 0 ? 'text-up' : delta < 0 ? 'text-down' : 'text-fg-3') : 'text-fg-3')}
            >
              {fmtValue(delta, deltaFormat)}
            </span>
          )}
        </span>
        {zone && <span className="sr-only">Zone: {zone.label}</span>}
      </span>
    </Tooltip>
  );
}
