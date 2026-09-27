import type { ReactNode } from 'react';
import { cn } from '../lib/cn';
import { fmtValue, isNum, type FormatKind } from '../lib/fmt';
import type { Tone } from '../api/types';
import { useMetric } from '../metrics/dictionary';
import { MetricTooltipBody } from './MetricTooltip';
import { Skeleton } from './Skeleton';
import { Spark } from './Spark';
import { Tooltip } from './Tooltip';

export type KpiTone = 'up' | 'down' | 'warn' | 'accent' | 'info' | 'violet' | 'neutral';

const TEXT: Record<KpiTone, string> = {
  up: 'text-up',
  down: 'text-down',
  warn: 'text-warn',
  accent: 'text-accent',
  info: 'text-info',
  violet: 'text-violet',
  neutral: 'text-fg',
};
const RAIL: Record<KpiTone, string> = {
  up: 'before:bg-up',
  down: 'before:bg-down',
  warn: 'before:bg-warn',
  accent: 'before:bg-accent',
  info: 'before:bg-info',
  violet: 'before:bg-violet',
  neutral: 'before:bg-transparent',
};
const WASH: Record<KpiTone, string> = {
  up: 'from-up/[0.09]',
  down: 'from-down/[0.09]',
  warn: 'from-warn/[0.09]',
  accent: 'from-accent/[0.09]',
  info: 'from-info/[0.09]',
  violet: 'from-violet/[0.09]',
  neutral: 'from-transparent',
};
const FROM_ZONE: Record<Tone, KpiTone> = { positive: 'up', negative: 'down', warn: 'warn', info: 'info', neutral: 'neutral' };

export interface KpiTileProps {
  label: ReactNode;
  /** A number (formatted with `format`) or any node (e.g. a verdict word). NULL -> "—". */
  value: ReactNode;
  format?: FormatKind;
  digits?: number;
  /** Change figure shown as a small pill next to the value. */
  delta?: number | null;
  deltaFormat?: FormatKind;
  /** Colour of the delta: `auto` = sign; `invert` = down is good (e.g. VIX). */
  deltaTone?: 'auto' | 'invert' | 'neutral';
  /** Short text under the value. */
  caption?: ReactNode;
  /** Oldest -> newest values for a sparkline. */
  spark?: readonly (number | null | undefined)[];
  sparkBaseline?: number;
  sparkLabel?: string;
  /** Explicit tone; otherwise the dictionary zone of a numeric value when `metricKey` is set. */
  tone?: KpiTone;
  /** Metric-dictionary key: tooltip + zone colour. */
  metricKey?: string;
  /** Plain tooltip when there is no metric key. */
  hint?: ReactNode;
  /** Hero tile: display-size value, tinted wash, wider. */
  hero?: boolean;
  loading?: boolean;
  onClick?: () => void;
  selected?: boolean;
  className?: string;
}

/**
 * One at-a-glance figure: label, big tabular value, delta pill, optional spark
 * and caption. Coloured by its dictionary zone (or an explicit tone) with a
 * thin left rail so the colour reads without shouting.
 */
export function KpiTile({
  label,
  value,
  format = 'num',
  digits,
  delta,
  deltaFormat = 'signed',
  deltaTone = 'auto',
  caption,
  spark,
  sparkBaseline,
  sparkLabel,
  tone,
  metricKey,
  hint,
  hero,
  loading,
  onClick,
  selected,
  className,
}: KpiTileProps) {
  const { def, zoneFor, toneFor } = useMetric(metricKey);
  const numeric = typeof value === 'number' || value === null || value === undefined;
  const numValue = typeof value === 'number' ? value : null;
  const zoneTone = metricKey && numeric ? toneFor(numValue) : undefined;
  const t: KpiTone = tone ?? (zoneTone ? FROM_ZONE[zoneTone] : 'neutral');
  const shown = numeric ? fmtValue(value, format, digits) : value;
  const muted = numeric && !isNum(value);

  let deltaCls = 'text-fg-3 bg-surface-3';
  if (isNum(delta) && delta !== 0 && deltaTone !== 'neutral') {
    const good = deltaTone === 'invert' ? delta < 0 : delta > 0;
    deltaCls = good ? 'text-up bg-up/10' : 'text-down bg-down/10';
  }

  const body = (
    <>
      <span className="mp-label block truncate">{label}</span>
      {loading ? (
        <Skeleton height={hero ? 28 : 22} width={hero ? 120 : 72} className="mt-1.5" />
      ) : (
        <span className="mt-1 flex items-baseline gap-2">
          <span
            className={cn(
              numeric && 'num',
              hero ? 'text-display' : 'text-kpi',
              'truncate font-semibold',
              muted ? 'text-fg-3' : TEXT[t],
            )}
          >
            {shown}
          </span>
          {delta !== undefined && (
            <span className={cn('num shrink-0 rounded px-1 py-px text-2xs font-medium', deltaCls)}>{fmtValue(delta, deltaFormat)}</span>
          )}
        </span>
      )}
      {(caption || spark) && (
        <span className="mt-1 flex min-w-0 items-end justify-between gap-2">
          {caption ? <span className="min-w-0 truncate text-2xs text-fg-3">{caption}</span> : <span />}
          {spark && (
            <Spark
              values={spark}
              baseline={sparkBaseline}
              label={sparkLabel ?? (typeof label === 'string' ? `${label} trend` : 'trend')}
              width={hero ? 96 : 64}
              height={18}
              area
              className="shrink-0"
            />
          )}
        </span>
      )}
      {metricKey && zoneFor(numValue) && <span className="sr-only">Zone: {zoneFor(numValue)?.label}</span>}
    </>
  );

  const cls = cn(
    'group relative flex min-w-0 flex-col justify-center px-4 py-2.5 text-left',
    'before:absolute before:bottom-3 before:left-0 before:top-3 before:w-[2px] before:rounded-full before:opacity-80',
    RAIL[t],
    hero && cn('bg-gradient-to-r to-transparent', WASH[t]),
    onClick && 'cursor-pointer transition-colors duration-fast ease-out hover:bg-surface-2/70 focus-visible:bg-surface-2/70',
    selected && 'bg-surface-2 shadow-[inset_0_-2px_0_0_rgb(var(--c-accent))]',
    className,
  );

  const tile = onClick ? (
    <button type="button" onClick={onClick} aria-pressed={selected} className={cls} data-kpi>
      {body}
    </button>
  ) : (
    <div className={cls} tabIndex={metricKey || hint ? 0 : undefined} data-kpi>
      {body}
    </div>
  );

  if (metricKey) {
    return (
      <Tooltip content={<MetricTooltipBody def={def} metricKey={metricKey} activeZone={zoneFor(numValue)} />} className="flex min-w-0 [&>*]:flex-1">
        {tile}
      </Tooltip>
    );
  }
  if (hint) {
    return (
      <Tooltip content={hint} className="flex min-w-0 [&>*]:flex-1">
        {tile}
      </Tooltip>
    );
  }
  return tile;
}
