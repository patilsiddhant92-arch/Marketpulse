/**
 * Desk "vs last week": now vs 5 sessions ago (GET /api/v2/desk/compare) — verdict, the three
 * queue counts, breadth, and the top-10 industry groups by Health that entered / left.
 * Every "then" value is the stored value on that real session; nothing is interpolated.
 */
import { ArrowRight, History } from 'lucide-react';
import { useApiQuery } from '../api/query';
import type { CompareRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtDateWithDay, fmtNum, fmtSigned } from '../lib/fmt';
import { useGroupNav } from '../today/parts';
import { Card } from '../ui/Card';
import { Skeleton } from '../ui/Skeleton';

interface TopGroup {
  id: string;
  group_name: string;
  health?: number | null;
  health_rank?: number | null;
  health_rank_then?: number | null;
  rrg_quadrant?: string | null;
}
interface CompareCtx {
  sessions?: number;
  then_date?: string | null;
  verdict_now?: string | null;
  verdict_then?: string | null;
  top_groups_now?: TopGroup[];
  groups_entered?: TopGroup[];
  groups_left?: TopGroup[];
}

const VERDICT_TEXT: Record<string, string> = {
  Favourable: 'text-v-favourable',
  Constructive: 'text-v-constructive',
  Mixed: 'text-v-mixed',
  Weak: 'text-v-weak',
  Danger: 'text-v-danger',
};

/** Tone of a change: `better` says which direction is good; queues are neutral. */
export function deltaTone(r: Pick<CompareRow, 'delta' | 'better'>): string {
  if (r.delta == null || r.delta === 0) return 'text-fg-3';
  if (!r.better) return 'text-fg-2';
  return (r.delta > 0) === (r.better === 'up') ? 'text-up' : 'text-down';
}

function fmtVal(v: number | null | undefined, unit: string): string {
  if (v == null) return '—';
  return unit === 'pct' ? `${fmtNum(v, 1)}%` : fmtNum(v, 0);
}

function Item({ r }: { r: CompareRow }) {
  return (
    <span className="inline-flex items-baseline gap-1 whitespace-nowrap" title={`${r.label}: ${fmtVal(r.then, r.unit)} then → ${fmtVal(r.now, r.unit)} now`}>
      <span className="text-fg-3">{r.label}</span>
      <span className="num text-fg-3">{fmtVal(r.then, r.unit)}</span>
      <ArrowRight className="h-3 w-3 self-center text-fg-3" aria-hidden />
      <span className="num font-medium text-fg">{fmtVal(r.now, r.unit)}</span>
      <span className={cn('num text-2xs', deltaTone(r))}>{r.delta == null ? '' : fmtSigned(r.delta, r.unit === 'pct' ? 1 : 0)}</span>
    </span>
  );
}

export function CompareStrip({ className }: { className?: string }) {
  const q = useApiQuery('desk/compare', { query: { sessions: 5 } });
  const onGroup = useGroupNav();
  const ctx = q.data?.meta.context as CompareCtx | undefined;
  const rows = q.data?.rows ?? [];
  if (q.error) return null;
  return (
    <Card className={cn('flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 px-3 py-1.5 text-xs', className)} aria-label="Versus last week" data-testid="desk-compare">
      <span className="mp-label inline-flex items-center gap-1 text-fg-2">
        <History className="h-3.5 w-3.5" aria-hidden /> vs {ctx?.then_date ? fmtDateWithDay(ctx.then_date) : 'last week'}
      </span>
      {q.isLoading ? (
        <Skeleton width={480} height={14} />
      ) : (
        <>
          {(ctx?.verdict_then || ctx?.verdict_now) && (
            <span className="inline-flex items-baseline gap-1 whitespace-nowrap" title="Environment verdict then → now">
              <span className="text-fg-3">Verdict</span>
              <span className={cn('font-medium', VERDICT_TEXT[ctx?.verdict_then ?? ''] ?? 'text-fg-3')}>{ctx?.verdict_then ?? '—'}</span>
              <ArrowRight className="h-3 w-3 self-center text-fg-3" aria-hidden />
              <span className={cn('font-semibold', VERDICT_TEXT[ctx?.verdict_now ?? ''] ?? 'text-fg')}>{ctx?.verdict_now ?? '—'}</span>
            </span>
          )}
          {rows.filter((r) => r.group === 'Queues').map((r) => <Item key={r.key} r={r} />)}
          <span className="h-3 w-px bg-line" aria-hidden />
          {rows.filter((r) => r.group === 'Breadth' && r.key !== 'advancers').map((r) => <Item key={r.key} r={r} />)}
          {(ctx?.groups_entered?.length || ctx?.groups_left?.length) ? (
            <span className="inline-flex min-w-0 flex-wrap items-baseline gap-1" title="Top 10 industry groups by Health: entered / left since then">
              <span className="text-fg-3">Top-10 groups</span>
              {(ctx?.groups_entered ?? []).map((g) => (
                <button key={g.id} type="button" onClick={() => onGroup(g.id)} className="whitespace-nowrap text-up hover:underline" title={`Now #${g.health_rank} by Health (was #${g.health_rank_then ?? '—'})`}>
                  +{g.group_name}
                </button>
              ))}
              {(ctx?.groups_left ?? []).map((g) => (
                <button key={g.id} type="button" onClick={() => onGroup(g.id)} className="whitespace-nowrap text-down hover:underline" title={`Was #${g.health_rank} by Health then`}>
                  −{g.group_name}
                </button>
              ))}
            </span>
          ) : null}
        </>
      )}
    </Card>
  );
}
