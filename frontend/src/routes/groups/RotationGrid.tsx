/**
 * Groups › Rotation — groups × the last 12 week-ends, each cell the group's Health that week
 * (green ≥ 50, red < 50, stronger = further from 50). Read across a row for a group's path,
 * down a column for who led that week. Source: GET /api/v2/groups/rotation (group_daily).
 */
import { useMemo, useState } from 'react';
import { useApiQuery } from '../../api/query';
import type { RotationRow } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtDateShort, fmtNum, fmtSigned } from '../../lib/fmt';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { heatStyle } from '../../ui/DataTable';
import { SkeletonRows } from '../../ui/Skeleton';
import { Segmented, SourceNote } from './kit';
import type { Floor, Level } from './groupsModel';

const EMPTY: RotationRow[] = [];
const Q_SHORT: Record<string, string> = { Leading: 'L', Improving: 'I', Weakening: 'W', Lagging: 'G' };

/** Health 0..100 → heat −1..1 around the neutral 50. */
export function healthHeat(h: number | null | undefined): number | null {
  return h == null ? null : Math.max(-1, Math.min(1, (h - 50) / 40));
}

type SortKey = 'now' | 'change';

export function sortRotation(rows: readonly RotationRow[], key: SortKey, text: string): RotationRow[] {
  const t = text.trim().toLowerCase();
  const f = t ? rows.filter((r) => r.group_name.toLowerCase().includes(t)) : [...rows];
  const v = (r: RotationRow) => (key === 'now' ? r.health_now : r.health_change);
  return f.sort((a, b) => (v(b) ?? -1e9) - (v(a) ?? -1e9));
}

export function RotationGrid({ level, floor, text, onDrill }: { level: Level; floor: Floor; text: string; onDrill: (id: string) => void }) {
  const q = useApiQuery('groups/rotation', { query: { level, floor, weeks: 12, limit: 5000 } });
  const [sort, setSort] = useState<SortKey>('now');
  const weeks = ((q.data?.meta.context as { weeks?: string[] } | undefined)?.weeks ?? []) as string[];
  const rows = useMemo(() => sortRotation(q.data?.rows ?? EMPTY, sort, text), [q.data, sort, text]);
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="groups-rotation">
      <div className="flex min-h-7 shrink-0 flex-wrap items-center gap-3 border-b border-line bg-surface px-3 py-0.5 text-2xs text-fg-3">
        <span>
          Rotation: weekly Health of <span className="num text-fg-2">{rows.length}</span> ranked groups over {weeks.length} weeks · green = healthy, red =
          weak · letter = RRG quadrant (L/I/W/G = Leading / Improving / Weakening / Lagging) · click a row to drill
        </span>
        <Segmented
          label="Sort rotation"
          size="xs"
          options={[
            { value: 'now', label: 'Health now', title: 'Healthiest this week first' },
            { value: 'change', label: 'Change 12w', title: 'Biggest Health gain over the grid first (rotating in)' },
          ]}
          value={sort}
          onChange={setSort}
        />
        <span className="ml-auto">
          <SourceNote meta={q.data?.meta} />
        </span>
      </div>
      {q.isLoading ? (
        <SkeletonRows rows={12} label="Loading rotation" />
      ) : q.data?.meta.status === 'unavailable' ? (
        <EmptyState title="Rotation unavailable" detail={q.data.meta.reason ?? undefined} />
      ) : !rows.length ? (
        <EmptyState title="No groups" detail="Clear the filter." />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full border-separate border-spacing-0 text-table" aria-label="Group rotation by week">
            <thead className="sticky top-0 z-10 bg-surface-2">
              <tr>
                <th className="sticky left-0 z-20 min-w-[220px] bg-surface-2 px-2 py-1 text-left font-medium text-fg-3">Group</th>
                {weeks.map((w) => (
                  <th key={w} className="num px-1 py-1 text-center font-medium text-fg-3" title={`Week ending ${w}`}>
                    {fmtDateShort(w)}
                  </th>
                ))}
                <th className="num px-2 py-1 text-right font-medium text-fg-3" title="Health, last week minus first week of the grid">
                  Δ
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="mp-tr cursor-pointer" onClick={() => onDrill(r.id)}>
                  <td className="sticky left-0 z-[1] truncate bg-surface px-2 py-0.5 text-fg" title={`${r.group_name} · ${r.stocks ?? '—'} stocks — click to drill`}>
                    {r.group_name}
                  </td>
                  {(r.cells ?? []).map((c, i) => (
                    <td
                      key={c.week_end ?? i}
                      className="num px-1 py-0.5 text-center text-fg"
                      style={heatStyle(healthHeat(c.health))}
                      title={`${r.group_name}, week ending ${c.week_end ?? '—'}: Health ${fmtNum(c.health, 1)}${c.health_rank != null ? ` · #${c.health_rank}` : ''}${c.rrg_quadrant ? ` · ${c.rrg_quadrant}` : ''}`}
                    >
                      {c.health == null ? <span className="text-fg-3">—</span> : fmtNum(c.health, 0)}
                      {c.rrg_quadrant && <sup className="ml-0.5 text-2xs text-fg-3">{Q_SHORT[c.rrg_quadrant] ?? ''}</sup>}
                    </td>
                  ))}
                  <td className={cn('num px-2 py-0.5 text-right', (r.health_change ?? 0) > 0 ? 'text-up' : (r.health_change ?? 0) < 0 ? 'text-down' : 'text-fg-3')}>
                    {fmtSigned(r.health_change, 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
