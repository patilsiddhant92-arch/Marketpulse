/**
 * Pre-move watch (spec 7.6): stocks matching the strongest pre-move traits
 * today, with precision and its sample size printed per row. Labelled
 * research until out-of-sample precision clearly beats the base rate.
 */
import { FlaskConical, LineChart } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { PreMoveRow } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtDateWithDay, fmtNum, fmtPct, isNum } from '../../lib/fmt';
import { useShell } from '../../shell/ShellContext';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { useResearchQuery } from './data';
import { MIN_SAMPLE, ctx, num, preMoveEdge, preMoveLift, str } from './model';
import { Panel, QueryState, SampleN, Term } from './parts';

const EMPTY: PreMoveRow[] = [];

const EDGE_CHIP = {
  edge: { tone: 'positive', text: 'beats base rate', title: 'Precision ≥ 1.5× the base rate with n ≥ 30' },
  weak: { tone: 'neutral', text: 'near base rate', title: 'Precision under 1.5× the base rate' },
  insufficient: { tone: 'warn', text: 'insufficient sample', title: `Fewer than ${MIN_SAMPLE} past stock-days with these traits` },
  unknown: { tone: 'neutral', text: '—', title: 'Precision or base rate not served' },
} as const;

const COLUMNS: DataTableColumn<PreMoveRow>[] = [
  {
    id: 'symbol',
    header: 'Symbol',
    accessor: 'symbol',
    width: 112,
    sticky: true,
    cell: (v) => <span className="font-mono font-medium text-fg">{String(v)}</span>,
  },
  {
    id: 'name',
    header: 'Name',
    accessor: (r) => str((r as Record<string, unknown>).security_name),
    width: 180,
    cell: (v) => <span className="truncate text-fg-2">{String(v)}</span>,
  },
  {
    id: 'traits',
    header: 'Matched traits',
    accessor: (r) => r.matched_traits?.length ?? null,
    width: 320,
    grow: true,
    headerTitle: 'Pre-move traits from the big-mover study that this stock shows today',
    cell: (_v, r) => (
      <span className="flex flex-wrap gap-1 py-0.5">
        {(r.matched_traits ?? []).map((t) => (
          <Chip key={t} tone="info">
            {t}
          </Chip>
        ))}
      </span>
    ),
  },
  {
    id: 'precision',
    header: 'Precision 20d',
    accessor: (r) => (isNum(r.n) && r.n >= MIN_SAMPLE ? r.precision_20d : null),
    format: 'pct',
    width: 150,
    metricKey: 'precision_20d',
    renderNull: true,
    cell: (_v, r) => {
      const ok = isNum(r.n) && r.n >= MIN_SAMPLE;
      return (
        <span className="inline-flex items-baseline justify-end gap-1.5">
          {ok ? (
            <span className="num text-fg">{fmtPct(r.precision_20d, 1)}</span>
          ) : (
            <span className="text-2xs italic text-fg-3">insufficient sample</span>
          )}
          <SampleN n={r.n} />
        </span>
      );
    },
  },
  {
    id: 'base',
    header: 'Base rate',
    accessor: 'base_rate_20d',
    format: 'pct',
    width: 84,
    headerTitle: 'Share of all stock-days that made a big move within 20 sessions',
  },
  {
    id: 'lift',
    header: 'Lift',
    accessor: (r) => (isNum(r.n) && r.n >= MIN_SAMPLE ? preMoveLift(r) : null),
    format: 'num',
    width: 70,
    metricKey: 'lift',
    cell: (v) => <span className={cn('num', (v as number) >= 1.5 ? 'text-up' : 'text-fg')}>{fmtNum(v as number, 1)}×</span>,
  },
  {
    id: 'edge',
    header: 'Status',
    accessor: (r) => preMoveEdge(r),
    width: 132,
    cell: (v) => {
      const c = EDGE_CHIP[v as keyof typeof EDGE_CHIP];
      return (
        <Chip tone={c.tone} title={c.title}>
          {c.text}
        </Chip>
      );
    },
  },
];

export function PreMoveView() {
  const shell = useShell();
  const q = useResearchQuery('research/pre-move', { query: { limit: 500 } });
  const [visible, setVisible] = useState<readonly PreMoveRow[]>(EMPTY);
  const rows = q.data?.rows ?? EMPTY;
  const counts = useMemo(() => {
    const c = { edge: 0, weak: 0, insufficient: 0, unknown: 0 };
    rows.forEach((r) => c[preMoveEdge(r)]++);
    return c;
  }, [rows]);
  return (
    <QueryState
      q={q}
      what="Stocks that today show the traits which most often preceded big moves, with each trait set's precision (share of past look-alike stock-days that moved within 20 sessions) and its sample size, against the base rate."
    >
      {(env) => {
        const baseRate = num(ctx(env.meta).base_rate) ?? num(rows.find((r) => isNum(r.base_rate_20d))?.base_rate_20d);
        const notes = env.meta.notes ?? [];
        return (
          <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
            <div role="note" className="flex items-start gap-2 rounded border border-violet/40 bg-violet/5 px-3 py-2 text-xs text-fg-2">
              <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-violet" aria-hidden />
              <div>
                <div className="font-medium text-violet">Research list — not a trade signal</div>
                <div>
                  {notes[0] ??
                    'Precision is printed per row; the list graduates only when out-of-sample precision clearly beats the base rate.'}{' '}
                  {baseRate !== null && (
                    <>
                      Base rate: <span className="num text-fg">{fmtPct(baseRate, 1)}</span> of all stock-days moved within 20 sessions.
                    </>
                  )}
                </div>
              </div>
            </div>
            <Panel
              title="Pre-move watch"
              subtitle={
                <>
                  Traits as of {fmtDateWithDay(env.as_of)} · {counts.edge} beat the base rate · {counts.weak} near it ·{' '}
                  {counts.insufficient} with too few look-alikes (n &lt; {MIN_SAMPLE})
                </>
              }
              bodyClassName="flex min-h-[420px] flex-col"
              actions={
                <div className="flex items-center gap-2">
                  <Term k="precision_20d" className="text-2xs text-fg-3">
                    What is precision?
                  </Term>
                  <button
                    type="button"
                    onClick={() => shell.openCharts(visible.map((r) => r.symbol ?? '').filter(Boolean))}
                    disabled={!visible.length}
                    className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-2xs text-fg-2 hover:bg-surface-3 disabled:opacity-50"
                  >
                    <LineChart className="h-3 w-3" aria-hidden /> Open in Charts
                  </button>
                </div>
              }
            >
              <DataTable
                label="Pre-move watch"
                columns={COLUMNS}
                rows={rows}
                total={env.total}
                getRowId={(r, i) => r.symbol ?? String(i)}
                initialSort={[{ id: 'lift', desc: true }]}
                activeRowId={shell.symbol ?? undefined}
                onActiveRowChange={(r) => r.symbol && shell.openSymbol(r.symbol)}
                onRowActivate={(r) => r.symbol && shell.openStockPage(r.symbol)}
                onSortedRowsChange={setVisible}
                emptyState={<div className="p-6 text-center text-xs text-fg-3">No stock matches the strongest traits on this date.</div>}
                className="flex-1"
              />
            </Panel>
          </div>
        );
      }}
    </QueryState>
  );
}
