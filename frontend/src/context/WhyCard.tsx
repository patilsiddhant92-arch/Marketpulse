/**
 * "Why is this stock here?" — plain-language bullets served by GET /api/v2/stock/{sym}/why,
 * each restating stored facts (queue rule and values, trigger / stop, evidence in today's
 * environment with n, group Health, deals, delivery / RVOL footprint, events, data gaps).
 */
import { HelpCircle } from 'lucide-react';
import { Link } from 'react-router';
import { useApiQuery } from '../api/query';
import type { WhyBullet } from '../api/types';
import { cn } from '../lib/cn';
import { useAsOf } from '../shell/urlState';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { Panel } from '../ui/Panel';
import { SkeletonRows } from '../ui/Skeleton';
import { withAsOf } from './StockContextChips';

const DOT: Record<WhyBullet['tone'], string> = {
  positive: 'bg-up',
  negative: 'bg-down',
  warn: 'bg-warn',
  info: 'bg-info',
  accent: 'bg-accent',
  neutral: 'bg-fg-3',
};

export function WhyList({ rows }: { rows: readonly WhyBullet[] }) {
  const [asOf] = useAsOf();
  return (
    <ul className="space-y-1.5" data-testid="why-list">
      {rows.map((b, i) => (
        <li key={`${b.kind}-${i}`} className="flex gap-2 text-xs leading-snug text-fg-2">
          <span className={cn('mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full', DOT[b.tone])} aria-hidden />
          <span className="min-w-0">
            {b.text}
            {b.link && (
              <Link to={withAsOf(b.link, asOf)} className="ml-1 whitespace-nowrap text-accent hover:underline">
                open →
              </Link>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function WhyCard({ symbol, className, compact = false }: { symbol: string; className?: string; compact?: boolean }) {
  const q = useApiQuery('stock/{sym}/why', { params: { sym: symbol } });
  const body = q.error ? (
    <ErrorState error={q.error} compact onRetry={() => void q.refetch()} />
  ) : q.isLoading ? (
    <SkeletonRows rows={3} label="Loading why" />
  ) : !q.data?.rows.length ? (
    <EmptyState compact title="No facts to show" detail={q.data?.meta.reason ?? undefined} />
  ) : (
    <WhyList rows={q.data.rows} />
  );
  if (compact) {
    return (
      <section className={cn('space-y-1.5', className)} aria-label="Why is this stock here?">
        <h3 className="mp-label flex items-center gap-1 text-fg-2">
          Why is this stock here? <HelpCircle className="h-3 w-3 text-fg-3" aria-hidden />
        </h3>
        {body}
      </section>
    );
  }
  return (
    <Panel title="Why is this stock here?" label="Why is this stock here" className={className} bodyClassName="p-3" meta="facts only, nothing predicted">
      {body}
    </Panel>
  );
}
