/**
 * Groups Health pieces: Health score cell (zone-coloured number + bar), the
 * absolute-trend arrow and the RRG quadrant with its reality-check note
 * ("Leading but falling"). Zones come from the metric dictionary
 * (group_health, group_abs_trend, quadrant_note).
 */
import { ArrowDownRight, ArrowRight, ArrowUpRight } from 'lucide-react';
import { cn } from '../../lib/cn';
import { fmtNum, isNum } from '../../lib/fmt';
import { Chip } from '../../ui/Chip';
import { asTrend, healthZone, type HealthZone } from './groupsModel';
import { QuadrantChip } from './kit';

const ZONE_TEXT: Record<HealthZone, string> = { Healthy: 'text-up', Mixed: 'text-warn', Weak: 'text-down' };
const ZONE_BG: Record<HealthZone, string> = { Healthy: 'bg-up', Mixed: 'bg-warn', Weak: 'bg-down' };

export function HealthCell({ value, rank, compact = false }: { value: number | null | undefined; rank?: number | null; compact?: boolean }) {
  const zone = healthZone(value);
  if (!isNum(value) || !zone) return <span className="num text-fg-3">—</span>;
  return (
    <span className="flex w-full items-center gap-1.5" title={`Health ${fmtNum(value, 1)} — ${zone}${rank != null ? ` · #${rank} by Health` : ''}`}>
      <span className={cn('num w-7 text-right font-semibold', ZONE_TEXT[zone])}>{fmtNum(value, 0)}</span>
      {!compact && (
        <span className="h-1.5 min-w-[28px] flex-1 overflow-hidden rounded-full bg-surface-3" aria-hidden>
          <span className={cn('block h-full rounded-full opacity-80', ZONE_BG[zone])} style={{ width: `${Math.max(2, Math.min(100, value))}%` }} />
        </span>
      )}
    </span>
  );
}

const TREND_ICON = { Up: ArrowUpRight, Flat: ArrowRight, Down: ArrowDownRight } as const;
const TREND_TEXT = { Up: 'text-up', Flat: 'text-fg-3', Down: 'text-down' } as const;
const TREND_TITLE = {
  Up: 'Own index above a rising 50 EMA (and 50 > 200 EMA): rising in absolute terms',
  Flat: 'No clear absolute direction (basing, pulling back or bouncing)',
  Down: 'Own index below a falling 50 EMA: falling in absolute terms',
} as const;

export function TrendArrow({ trend, withLabel = false }: { trend: string | null | undefined; withLabel?: boolean }) {
  const t = asTrend(trend);
  if (!t) return <span className="text-fg-3">—</span>;
  const Icon = TREND_ICON[t];
  return (
    <span className={cn('inline-flex items-center gap-0.5', TREND_TEXT[t])} title={TREND_TITLE[t]} aria-label={`Absolute trend ${t}`}>
      <Icon className="h-3.5 w-3.5" />
      {withLabel && <span className="text-2xs font-medium">{t}</span>}
    </span>
  );
}

/** Short chip text for a quadrant note ("Leading but falling" -> "falling"). */
export function noteShort(note: string): string {
  if (/but falling/.test(note)) return 'falling';
  if (/narrow breadth/.test(note)) return 'narrow';
  if (/but rising/.test(note)) return 'rising';
  return note;
}

export function QuadrantWithNote({ quadrant, days, note }: { quadrant: string | null | undefined; days?: number | null; note?: string | null }) {
  return (
    <span className="flex min-w-0 items-center gap-1">
      <QuadrantChip quadrant={quadrant} days={days} />
      {note && (
        <Chip tone={/rising/.test(note) ? 'info' : 'warn'} title={`${note}. RRG is relative to peers; this is the absolute picture.`}>
          {noteShort(note)}
        </Chip>
      )}
    </span>
  );
}
