/** Small table cells shared by Screener and Charts: zone-coloured numbers, rank sparks, chips. */
import { cn } from '../lib/cn';
import { fmtValue, isNum, type FormatKind } from '../lib/fmt';
import { TONE_TEXT, useMetric } from '../metrics/dictionary';
import { Spark } from '../ui/Spark';

/** Number coloured by its metric-dictionary zone; the zone label is the hover title. NULL -> "—". */
export function ZoneNum({
  metricKey,
  value,
  format = 'num',
  digits,
  suffix,
}: {
  metricKey: string;
  value: unknown;
  format?: FormatKind;
  digits?: number;
  suffix?: string;
}) {
  const { zoneFor, toneFor } = useMetric(metricKey);
  const v = isNum(value) ? value : null;
  const zone = zoneFor(v);
  const tone = toneFor(v);
  return (
    <span className={cn('num', tone ? TONE_TEXT[tone] : 'text-fg', v === null && 'text-fg-3')} title={zone ? zone.label : undefined}>
      {fmtValue(v, format, digits)}
      {v !== null && suffix}
    </span>
  );
}

/** Signed number coloured by sign (for changes without zones). */
export function SignedNum({ value, format = 'signedPct', digits = 1 }: { value: unknown; format?: FormatKind; digits?: number }) {
  const v = isNum(value) ? value : null;
  return (
    <span className={cn('num', v === null ? 'text-fg-3' : v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-fg-2')}>
      {fmtValue(v, format, digits)}
    </span>
  );
}

/** Strength-rank path T-30 -> T-15 -> T-5 -> today (served rank history). */
export function RankSpark({ t30, t15, t5, now }: { t30?: number | null; t15?: number | null; t5?: number | null; now?: number | null }) {
  const values = [t30, t15, t5, now];
  if (values.every((v) => v == null)) return <span className="text-fg-3">—</span>;
  return (
    <Spark
      values={values}
      width={56}
      height={16}
      baseline={70}
      label={`Strength rank T-30 ${t30 ?? '—'}, T-15 ${t15 ?? '—'}, T-5 ${t5 ?? '—'}, today ${now ?? '—'}`}
    />
  );
}
