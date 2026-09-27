import { ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { isApiError } from '../api/client';
import { useApiQuery } from '../api/query';
import type { PillarStatus } from '../api/types';
import { cn } from '../lib/cn';
import { fmtDateWithDay } from '../lib/fmt';
import { EnvironmentDrawer, VERDICT_ACTION, VERDICT_TEXT, useEnvironment } from '../shell/environment';
import { Chip } from '../ui/Chip';
import { ErrorState } from '../ui/ErrorState';
import { Metric } from '../ui/Metric';
import { Panel } from '../ui/Panel';
import { Skeleton } from '../ui/Skeleton';
import { Spark } from '../ui/Spark';
import { Tooltip } from '../ui/Tooltip';
import { breadthSeries, breadthSnapshot } from './deskModel';

const PILLAR_TONE: Record<PillarStatus, 'positive' | 'warn' | 'negative'> = { Healthy: 'positive', Neutral: 'warn', Weak: 'negative' };

const DIGITS: Record<string, { format: 'num' | 'int' | 'pct'; digits?: number; label: string }> = {
  pct_above_50ema: { format: 'pct', digits: 1, label: '> 50 EMA' },
  pct_above_200ema: { format: 'pct', digits: 1, label: '> 200 EMA' },
  pct_above_10ema: { format: 'pct', digits: 1, label: '> 10 EMA (timing)' },
  advance_pct: { format: 'pct', digits: 1, label: 'Advancers' },
  net_new_highs: { format: 'int', label: 'Net new highs' },
  distribution_days_25: { format: 'int', label: 'Distribution days' },
  india_vix: { format: 'num', digits: 2, label: 'India VIX' },
};

/** Raw breadth readings — shown on their own when the verdict is not built, and under it when it is. */
function BreadthRow() {
  const q = useApiQuery('market/health', { query: { days: 60, limit: 60 } });
  if (q.isLoading) return <Skeleton height={36} />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />;
  const rows = q.data?.rows ?? [];
  const snap = breadthSnapshot(rows);
  if (!snap.date) return <p className="text-2xs text-fg-3">No breadth rows for this date.</p>;
  return (
    <div className="flex flex-wrap items-end gap-x-5 gap-y-2">
      {snap.readings.map((r) => (
        <Metric
          key={r.key}
          metricKey={r.key}
          value={r.value}
          format={DIGITS[r.key]?.format ?? 'num'}
          digits={DIGITS[r.key]?.digits}
          label={DIGITS[r.key]?.label}
          delta={r.key === 'india_vix' ? undefined : r.delta}
          deltaFormat={DIGITS[r.key]?.format === 'pct' ? 'signedPct' : 'signed'}
          size="sm"
        />
      ))}
      <Metric metricKey="vix_change_5d" value={rows[0]?.vix_change_5d_pct ?? null} format="signedPct" digits={1} size="sm" label="VIX 5d" />
      <Tooltip content="% of stocks above their 50-day EMA, last 60 sessions">
        <span className="inline-flex flex-col gap-0.5" tabIndex={0}>
          <span className="text-2xs uppercase tracking-wide text-fg-3">&gt;50 EMA · 60d</span>
          <Spark values={breadthSeries(rows, 'pct_above_50ema')} label="% above 50 EMA, 60 sessions" width={96} height={20} baseline={50} />
        </span>
      </Tooltip>
    </div>
  );
}

/** Desk Environment panel (spec 6.1 / 7.2): verdict + what changed + pillars, with raw breadth. */
export function EnvironmentPanel({ className }: { className?: string }) {
  const { q, view, unavailable } = useEnvironment();
  const [open, setOpen] = useState(false);
  const notShipped = isApiError(q.error) && (q.error.kind === 'not_found' || q.error.kind === 'parse');

  let verdictBlock;
  if (q.isLoading) verdictBlock = <Skeleton width={260} height={28} />;
  else if (view && !unavailable) {
    verdictBlock = (
      <button type="button" onClick={() => setOpen(true)} className="group flex min-w-0 items-center gap-3 text-left" aria-label="Open market environment details">
        <span className={cn('text-2xl font-semibold leading-none', view.verdict ? VERDICT_TEXT[view.verdict] : 'text-fg-3')}>{view.verdict ?? '—'}</span>
        <span className="flex min-w-0 flex-col">
          {view.verdict && <span className="text-xs font-medium text-fg-2">{VERDICT_ACTION[view.verdict]}</span>}
          {view.whatChanged && <span className="truncate text-2xs text-fg-3">{view.whatChanged}</span>}
          {view.evidenceNote && <span className="truncate text-2xs text-warn" title={view.evidenceNote}>describes conditions — not a trade filter (5-yr test)</span>}
        </span>
        <span className="ml-2 flex flex-wrap gap-1">
          {view.pillars.map((p) => (
            <Tooltip key={p.key} content={`${p.question} ${p.sentence ?? ''}`}>
              <span>
                <Chip tone={p.status ? PILLAR_TONE[p.status] : 'neutral'}>
                  {p.name}
                  {p.status ? '' : ' —'}
                </Chip>
              </span>
            </Tooltip>
          ))}
        </span>
        <ChevronRight className="h-4 w-4 text-fg-3 group-hover:text-fg" aria-hidden />
      </button>
    );
  } else {
    const reason = q.data?.meta?.reason;
    verdictBlock = (
      <div className="flex min-w-0 flex-col">
        <span className="text-sm font-medium text-fg-2">Verdict not available</span>
        <span className="truncate text-2xs text-fg-3">
          {notShipped ? 'API v2 regime endpoint not deployed.' : q.error ? 'Could not load the regime.' : (reason ?? 'regime_daily has no row for this date.')}{' '}
          Read the raw breadth below instead.
        </span>
      </div>
    );
  }

  return (
    <Panel
      title="Market environment"
      meta={`${view?.asOf ? `as of ${fmtDateWithDay(view.asOf)} · ` : ''}small figures = change vs previous session · hover any number for what it means`}
      className={className}
      bodyClassName="space-y-3 px-3 py-2.5"
    >
      {verdictBlock}
      <BreadthRow />
      {view && <EnvironmentDrawer open={open} onClose={() => setOpen(false)} view={view} />}
    </Panel>
  );
}
