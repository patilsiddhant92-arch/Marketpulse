/**
 * Group context everywhere a group appears: Health chip (zone colour, quadrant, "falling" note)
 * with its 21-session Health spark. Fed by GET /api/v2/context/groups (one request per level).
 */
import { useMemo } from 'react';
import { useNavigate } from 'react-router';
import { useApiQuery } from '../api/query';
import type { GroupContext, GroupRow } from '../api/types';
import { cn } from '../lib/cn';
import { useAsOf } from '../shell/urlState';
import { Spark } from '../ui/Spark';
import { groupHref, groupTitle, noteShort } from './stockContext';
import { withAsOf } from './StockContextChips';

type Level = 'broad_sector' | 'sector' | 'broad_industry' | 'industry';
type Floor = '1000' | 'all' | 'watch';

const EMPTY: ReadonlyMap<string, GroupContext> = new Map();

/** A Groups board row already carries the context fields. */
export function groupRowContext(r: GroupRow): GroupContext {
  const h = r.health ?? null;
  return {
    id: r.id,
    group_name: r.group_name ?? null,
    level: r.level,
    stocks: r.stocks ?? null,
    thin: (r.stocks ?? 0) < 3,
    health: h,
    health_zone: h == null ? null : h >= 65 ? 'Healthy' : h >= 45 ? 'Mixed' : 'Weak',
    health_rank: r.health_rank ?? null,
    rrg_quadrant: r.rrg_quadrant ?? null,
    quadrant_note: r.quadrant_note ?? null,
    abs_trend: r.abs_trend ?? null,
    return_ew_21d: r.return_ew_21d ?? null,
    health_spark_21: r.health_spark_21 ?? null,
  };
}

export function useGroupContext(level: Level = 'industry', floor: Floor = '1000'): ReadonlyMap<string, GroupContext> {
  const q = useApiQuery('context/groups', { query: { level, floor, limit: 5000 } });
  return useMemo(() => (q.data ? new Map(q.data.rows.map((r) => [r.id, r])) : EMPTY), [q.data]);
}

const ZONE_TEXT: Record<string, string> = { Healthy: 'text-up', Mixed: 'text-warn', Weak: 'text-down' };
const ZONE_BORDER: Record<string, string> = { Healthy: 'border-up/30 bg-up/10', Mixed: 'border-warn/30 bg-warn/10', Weak: 'border-down/30 bg-down/10' };

export function GroupHealthChip({ g, spark = true, quadrant = true, clickable = true, className }: { g: GroupContext | undefined; spark?: boolean; quadrant?: boolean; clickable?: boolean; className?: string }) {
  const navigate = useNavigate();
  const [asOf] = useAsOf();
  if (!g || g.health == null) return <span className="text-2xs text-fg-3">—</span>;
  const zone = g.health_zone ?? '';
  const note = noteShort(g.quadrant_note);
  const body = (
    <>
      <span className={cn('num font-semibold', ZONE_TEXT[zone] ?? 'text-fg-2')}>H{g.health.toFixed(0)}</span>
      {spark && g.health_spark_21 && g.health_spark_21.some((v) => v != null) && (
        <Spark values={g.health_spark_21} label={`${g.group_name} Health, 21 sessions`} width={34} height={12} baseline={50} showLastDot={false} />
      )}
      {quadrant && g.rrg_quadrant && <span className="text-fg-2">{g.rrg_quadrant.slice(0, 4)}</span>}
      {quadrant && note && <span className={note === 'rising' ? 'text-info' : 'text-warn'}>{note}</span>}
    </>
  );
  const cls = cn('inline-flex h-[18px] shrink-0 items-center gap-1 whitespace-nowrap rounded-[3px] border px-1 text-2xs leading-none', ZONE_BORDER[zone] ?? 'border-line', className);
  if (!clickable) return <span className={cls} title={groupTitle(g)}>{body}</span>;
  return (
    <button
      type="button"
      className={cn(cls, 'hover:brightness-125')}
      title={`${groupTitle(g)}. Click to drill in.`}
      onClick={(e) => {
        e.stopPropagation();
        navigate(withAsOf(groupHref(g.id), asOf));
      }}
    >
      {body}
    </button>
  );
}
