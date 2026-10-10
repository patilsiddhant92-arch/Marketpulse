/**
 * Group studies (moved here from Research, 10 §2): evidence-engine tables (big movers by group, entry study)
 * when built, plus the local Sector Intel evidence (07 rounds 2-3). Honest unavailable state when missing.
 */
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { Skeleton } from '../../ui/Skeleton';
import { SourceNote } from '../../ui/SourceNote';
import { useSectors, type MoodStudyRow, type ReadingsStudyRow, type SectorLevel } from './sectorApi';

interface StudyCtx {
  level: SectorLevel;
  entry_study?: Record<string, unknown>[];
  readings_study?: ReadingsStudyRow[];
  mood_study?: MoodStudyRow[];
  study_period?: string;
}

function Table({ head, rows }: { head: string[]; rows: (string | number | null | undefined)[][] }) {
  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={h} className={`border-b border-line px-2 py-1 font-medium text-fg-3 ${i ? 'text-right' : 'text-left'}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line/50">
              {r.map((c, j) => (
                <td key={j} className={`num px-2 py-1 ${j ? 'text-right' : 'text-left'} text-fg`}>
                  {c == null || c === '' ? '–' : c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const LV_KEY: Record<SectorLevel, 'ic_sector' | 'ic_broad_industry' | 'ic_industry'> = {
  sector: 'ic_sector',
  broad_industry: 'ic_broad_industry',
  industry: 'ic_industry',
};

export function GroupStudies({ level }: { level: SectorLevel }) {
  const q = useSectors<Record<string, unknown>, StudyCtx>('group-studies', { level });
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (q.isLoading || !q.data) return <Skeleton height={300} />;
  const ctx = q.data.meta.context ?? ({} as StudyCtx);
  const k = LV_KEY[level];
  const rows = q.data.rows;
  const cols = rows.length
    ? Object.keys(rows[0])
        .filter((c) => !['level'].includes(c))
        .slice(0, 8)
    : [];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3">
      <section aria-label="Which readings predict" className="rounded border border-line bg-surface p-2">
        <h2 className="text-sm font-semibold text-fg">Which group readings predicted the next 21 sessions?</h2>
        <p className="mb-1 text-2xs text-fg-3">
          {ctx.study_period}. IC = average daily rank correlation with the group&apos;s next-21-session return vs the median group. Top /
          bottom = % of days the top / bottom fifth of groups (Broad Industry) beat the median group. Thresholds are provisional until the
          five-year point-in-time recheck.
        </p>
        <Table
          head={['Reading', 'Best N', 'IC (this level)', 'IC Sector', 'IC Broad Ind', 'IC Industry', 'Top vs bottom']}
          rows={(ctx.readings_study ?? []).map((r) => [
            r.reading,
            r.best_n,
            r[k].toFixed(3),
            r.ic_sector.toFixed(3),
            r.ic_broad_industry.toFixed(3),
            r.ic_industry.toFixed(3),
            `${r.top}% vs ${r.bot}%`,
          ])}
        />
      </section>
      <section aria-label="Market state and the score" className="rounded border border-line bg-surface p-2">
        <h2 className="text-sm font-semibold text-fg">Does the market state change how well the score works?</h2>
        <p className="mb-1 text-2xs text-fg-3">
          4-part score, 2-week window. The mood level barely matters. When short-term breadth cools fast, the ranking works about half as
          well.
        </p>
        <Table
          head={['Condition', 'IC (this level)', 'IC Sector', 'IC Broad Ind', 'IC Industry', 'Top vs bottom']}
          rows={(ctx.mood_study ?? []).map((r) => [
            r.condition,
            r[k].toFixed(3),
            r.ic_sector.toFixed(3),
            r.ic_broad_industry.toFixed(3),
            r.ic_industry.toFixed(3),
            `${r.top}% vs ${r.bot}%`,
          ])}
        />
      </section>
      <section aria-label="Big movers by group" className="rounded border border-line bg-surface p-2">
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fg">Big movers by group and entry study (evidence engine)</h2>
          <SourceNote meta={q.data.meta} />
        </div>
        {q.data.meta.status === 'unavailable' ? (
          <EmptyState
            compact
            title="Not built yet"
            detail={`${q.data.meta.reason ?? 'Evidence tables missing.'} Run the evidence step on the full archive.`}
          />
        ) : (
          <Table
            head={cols}
            rows={rows.map((r) =>
              cols.map((c) => (typeof r[c] === 'number' ? Number((r[c] as number).toFixed(3)) : (r[c] as string | null))),
            )}
          />
        )}
      </section>
    </div>
  );
}
