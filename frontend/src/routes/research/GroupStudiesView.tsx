/**
 * Group studies (spec 7.6): big movers rolled up by taxonomy level (Broad
 * Sector / Sector / Broad Industry / Industry). Every count carries n; the
 * "forward returns after an Industry enters Leading" study waits for its
 * evidence table.
 */
import { useMemo } from 'react';
import type { BigMoveRow } from '../../api/types';
import { fmtPct, fmtSignedPct } from '../../lib/fmt';
import { useUrlParam } from '../../shell/urlState';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { useResearchQuery } from './data';
import { CATALYST_LABEL, CATALYST_TONE, TAXONOMY_LEVELS, groupStudy, isTaxonomyLevel, type GroupStudyRow, type TaxonomyLevel } from './model';
import { EvidencePending, Panel, QueryState, SampleN } from './parts';

const EMPTY: BigMoveRow[] = [];

function columns(levelLabel: string): DataTableColumn<GroupStudyRow>[] {
  return [
    { id: 'group', header: levelLabel, accessor: 'group', width: 240, grow: true, cell: (v) => <span className={v === 'Unclassified' ? 'text-fg-3' : 'text-fg'}>{String(v)}</span> },
    { id: 'events', header: 'Events', accessor: 'events', format: 'int', width: 72, headerTitle: 'Big-move events in this group (n)' },
    { id: 'share', header: 'Share', accessor: (r) => r.share * 100, format: 'pct', width: 72, headerTitle: 'Share of all big-move events' },
    { id: 'symbols', header: 'Stocks', accessor: 'symbols', format: 'int', width: 72, headerTitle: 'Distinct symbols that moved' },
    {
      id: 'median',
      header: 'Median move',
      accessor: 'medianMove',
      format: 'signedPct',
      width: 110,
      renderNull: true,
      cell: (v, r) => (
        <span className="inline-flex items-baseline justify-end gap-1.5">
          <span className="num text-up">{fmtSignedPct(v as number | null)}</span>
          <SampleN n={r.events} />
        </span>
      ),
    },
    {
      id: 'sector',
      header: 'Sector-wide',
      accessor: 'sectorWide',
      format: 'int',
      width: 96,
      headerTitle: 'Events attributed to a sector-wide move (≥ 50% of the Industry moved in-window)',
      cell: (v, r) => (
        <span className="num">
          {String(v)} <span className="text-2xs text-fg-3">/ {r.events}</span>
        </span>
      ),
    },
    {
      id: 'top',
      header: 'Top catalyst',
      accessor: 'topCatalyst',
      width: 170,
      cell: (v, r) => {
        const c = v as GroupStudyRow['topCatalyst'];
        return c ? (
          <span className="inline-flex items-center gap-1">
            <Chip tone={CATALYST_TONE[c]}>{CATALYST_LABEL[c]}</Chip>
            <span className="num text-2xs text-fg-3">
              {r.topCatalystN}/{r.events}
            </span>
          </span>
        ) : null;
      },
    },
  ];
}

export function GroupStudiesView() {
  const [raw, setLevel] = useUrlParam('rlevel');
  const level: TaxonomyLevel = isTaxonomyLevel(raw) ? raw : 'industry';
  const levelLabel = TAXONOMY_LEVELS.find((l) => l.id === level)!.label;
  const q = useResearchQuery('research/big-moves', { query: { min_mcap_cr: 1000, limit: 2000 } });
  const rowsIn = q.data?.rows ?? EMPTY;
  const study = useMemo(() => groupStudy(rowsIn, level), [rowsIn, level]);
  const cols = useMemo(() => columns(levelLabel), [levelLabel]);
  return (
    <QueryState q={q} what="Big movers rolled up by Broad Sector, Sector, Broad Industry and Industry: where the big moves came from, how large, and how often the whole group moved together.">
      {(env) => (
        <div className="grid h-full min-h-0 grid-cols-1 gap-3 overflow-auto p-3 xl:grid-cols-[minmax(0,7fr)_minmax(0,4fr)]">
          <Panel
            title={`Big movers by ${levelLabel}`}
            subtitle={
              <>
                {study.total} events (mcap ≥ ₹1,000 Cr at event) · {study.classified} classified at this level
              </>
            }
            bodyClassName="flex min-h-[420px] flex-col"
            actions={
              <div role="radiogroup" aria-label="Taxonomy level" className="flex gap-1">
                {TAXONOMY_LEVELS.map((l) => (
                  <Chip key={l.id} onClick={() => setLevel(l.id === 'industry' ? null : l.id)} selected={l.id === level} tone={l.id === level ? 'accent' : 'neutral'}>
                    {l.label}
                  </Chip>
                ))}
              </div>
            }
          >
            <DataTable
              label={`Big movers by ${levelLabel}`}
              columns={cols}
              rows={study.rows}
              total={study.rows.length}
              getRowId={(r) => r.group}
              initialSort={[{ id: 'events', desc: true }]}
              emptyState={<div className="p-6 text-center text-xs text-fg-3">No big-move events on or before this date.</div>}
              className="flex-1"
            />
            {study.total > 0 && study.classified < study.total && (
              <div className="border-t border-line px-3 py-1.5 text-2xs text-fg-3">
                {study.total - study.classified} of {study.total} events have no {levelLabel} on the event row ({fmtPct(((study.total - study.classified) / study.total) * 100, 0)}); shown as
                Unclassified, never guessed.
              </div>
            )}
          </Panel>
          <Panel title="After an Industry turns Leading" subtitle="Forward member returns after an Industry enters the RRG Leading quadrant">
            <EvidencePending
              compact
              meta={{ ...env.meta, reason: 'group-entry study not served by the API yet', sources: ['group_rrg history', 'setup_outcomes'] }}
              what="For every date an Industry entered Leading: members' median forward return at 5 / 20 / 60 sessions vs all stocks, with n per level."
            />
          </Panel>
        </div>
      )}
    </QueryState>
  );
}
