import { fmtValue, isNum, type FormatKind } from '../lib/fmt';
import { cn } from '../lib/cn';
import { TONE_TEXT, useMetric } from '../metrics/dictionary';

export interface ZoneValueProps {
  metricKey: string;
  value: number | null | undefined;
  format?: FormatKind;
  digits?: number;
  className?: string;
}

/** A bare number coloured by its dictionary zone (table cells). NULL -> muted "—". */
export function ZoneValue({ metricKey, value, format = 'num', digits, className }: ZoneValueProps) {
  const { toneFor, zoneFor } = useMetric(metricKey);
  const tone = toneFor(value);
  const zone = zoneFor(value);
  return (
    <span className={cn('num', !isNum(value) ? 'text-fg-3' : tone ? TONE_TEXT[tone] : 'text-fg', className)} title={zone ? zone.label : undefined}>
      {fmtValue(value, format, digits)}
    </span>
  );
}
