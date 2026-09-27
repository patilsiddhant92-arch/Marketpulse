import { CalendarClock, TriangleAlert } from 'lucide-react';
import type { StockHeaderRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtCr, fmtDateShort, fmtDateWithDay, fmtINR, fmtSignedPct } from '../lib/fmt';
import { Chip } from '../ui/Chip';
import { Skeleton } from '../ui/Skeleton';
import { Tooltip } from '../ui/Tooltip';

const LEVEL_LABEL: Record<string, string> = {
  broad_sector: 'Broad sector',
  sector: 'Sector',
  broad_industry: 'Broad industry',
  industry: 'Industry',
};

function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);
}

export interface StockHeaderProps {
  row: StockHeaderRow | undefined;
  loading: boolean;
  /** Envelope as_of (the session every number is bounded to). */
  asOf: string | null | undefined;
  compact?: boolean;
}

/** Price, change vs previous close, as-of/staleness, size, band, taxonomy, adjustment note. */
export function StockHeader({ row: s, loading, asOf, compact }: StockHeaderProps) {
  if (loading) return <Skeleton width={260} height={14} className="my-1" />;
  if (!s) return null;
  const adjusted = s.adjustments.filter((a) => a.kind === 'bonus' || a.kind === 'split');
  const ev = s.next_event;
  const evDays = ev?.event_date && asOf ? daysBetween(asOf, ev.event_date) : null;
  return (
    <div className={cn('flex min-w-0 flex-col gap-1', compact ? 'text-xs' : 'text-sm')}>
      {s.security_name && <div className="truncate text-xs text-fg-2">{s.security_name}</div>}
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className={cn('num font-semibold text-fg', compact ? 'text-lg' : 'text-2xl')}>{fmtINR(s.close)}</span>
        <Tooltip content="Close vs previous session's close">
          <span
            className={cn(
              'num font-medium',
              compact ? 'text-sm' : 'text-base',
              s.change_1d_pct == null ? 'text-fg-3' : s.change_1d_pct >= 0 ? 'text-up' : 'text-down',
            )}
          >
            {fmtSignedPct(s.change_1d_pct, 2)}
          </span>
        </Tooltip>
        <span className="num text-2xs text-fg-3">
          {s.trade_date ? `close of ${fmtDateWithDay(s.trade_date)}` : 'no session'}
          {s.prev_close != null && ` · prev ${fmtINR(s.prev_close)}`}
        </span>
        {s.stale_vs_as_of && (
          <Chip tone="warn" title={`No row on ${asOf ?? 'as-of'}; showing the last session the stock traded.`}>
            stale: last traded {fmtDateShort(s.trade_date)}
          </Chip>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip title={s.mcap_point_in_time ? 'Market cap as of this session' : 'Market cap from the current master file (not point-in-time)'}>
          mcap {fmtCr(s.market_cap_cr, 0)}
          {s.mcap_point_in_time === false && '*'}
        </Chip>
        {s.circuit_band != null && (
          <Chip tone={s.circuit_band <= 5 ? 'warn' : 'neutral'} title="NSE price band (circuit limit)">
            band {s.circuit_band}%
          </Chip>
        )}
        {s.series && s.series !== 'EQ' && (
          <Chip tone="warn" title="Not in the EQ series (trade-for-trade / BE / BZ)">
            {s.series}
          </Chip>
        )}
        {s.band_remarks && s.band_remarks !== '-' && <Chip tone="warn">{s.band_remarks}</Chip>}
        {ev?.event_date && (
          <Chip tone="warn" icon={<CalendarClock className="h-3 w-3" />} title={ev.event_type ?? undefined}>
            {ev.event_type === 'financial_results' ? 'results' : (ev.event_type ?? 'event').replace(/_/g, ' ')} {fmtDateShort(ev.event_date)}
            {evDays != null && ` (${evDays}d)`}
          </Chip>
        )}
        {adjusted.map((a) => (
          <Chip key={`${a.ex_date}-${a.kind}`} tone="violet" title={a.description ?? undefined}>
            adjusted for {a.kind}
            {a.factor != null ? ` ×${a.factor}` : ''} on {fmtDateShort(a.ex_date)}
          </Chip>
        ))}
        {!s.prices_adjusted && (
          <Tooltip content="prices_daily has no adjusted columns yet: splits/bonuses can show as fake gaps on the chart.">
            <span className="inline-flex items-center gap-1 text-2xs text-warn">
              <TriangleAlert className="h-3 w-3" aria-hidden /> unadjusted prices
            </span>
          </Tooltip>
        )}
      </div>
      {s.taxonomy.some((t) => t.name) && (
        <div className="flex min-w-0 flex-wrap items-center gap-1 text-2xs text-fg-3" aria-label="Taxonomy">
          {s.taxonomy
            .filter((t) => t.name)
            .map((t, i) => (
              <span key={t.level} className="inline-flex items-center gap-1">
                {i > 0 && <span aria-hidden>›</span>}
                <span title={LEVEL_LABEL[t.level] ?? t.level} className={i === s.taxonomy.length - 1 ? 'text-fg-2' : undefined}>
                  {t.name}
                </span>
              </span>
            ))}
        </div>
      )}
    </div>
  );
}
