/**
 * Before the big moves (10-tab-research.md §§5, 13): two families of early lifts
 * (Trend lifts above the 200 EMA, Turnaround lifts below it). For each: the
 * runner-vs-fizzle trait profile, today's early lifts scored by trait count
 * (with the in-sample and out-of-sample runner rate per score), and the regime
 * quadrant as a multiplier. Research only, not a setup.
 */
import { LineChart } from 'lucide-react';
import { cn } from '../../lib/cn';
import { fmtDate, fmtInt, fmtNum, fmtPct } from '../../lib/fmt';
import { useShell } from '../../shell/ShellContext';
import { useUrlParam } from '../../shell/urlState';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { useResearchQuery } from './data';
import { TRAIT_GROUPS, caveatOf, context, traitName, type BeforeMovesContext, type Bucket, type EarlyLiftRow, type Family, type TraitProfile } from './lab';
import { Caveat, Muted, QuadrantChip, SimpleTable, Summary } from './LabParts';
import { Panel, QueryState, SampleN } from './parts';

const FAMILIES: { id: Family; label: string; hint: string }[] = [
  { id: 'trend', label: 'Trend lifts', hint: 'Close above the 200 EMA at the lift' },
  { id: 'turnaround', label: 'Turnaround lifts', hint: 'Close below the 200 EMA at the lift' },
];

const LIFT_COLUMNS: DataTableColumn<EarlyLiftRow>[] = [
  { id: 'symbol', header: 'Symbol', accessor: 'symbol', width: 110, sticky: true, cell: (v) => <span className="font-mono font-medium text-fg">{String(v)}</span> },
  { id: 'name', header: 'Name', accessor: 'security_name', width: 170, cell: (v) => <span className="truncate text-fg-2">{String(v ?? '')}</span> },
  { id: 'date', header: 'Lift on', accessor: 'lift_date', format: 'date', width: 90 },
  {
    id: 'score',
    header: 'Score',
    accessor: 'score',
    width: 70,
    cell: (_v, r) => (
      <span className="num">
        {r.score}/{r.score_max}
      </span>
    ),
  },
  {
    id: 'rate',
    header: 'Past runner rate',
    accessor: 'bucket_runner_pct',
    width: 140,
    headerTitle: 'In-sample runner rate of past lifts with the same score bucket',
    cell: (_v, r) => (
      <span className="inline-flex items-baseline gap-1.5">
        <span className="num">{fmtPct(r.bucket_runner_pct, 0)}</span> <SampleN n={r.bucket_events} />
      </span>
    ),
  },
  {
    id: 'traits',
    header: 'Traits on',
    accessor: (r) => r.traits_on?.length ?? 0,
    width: 300,
    grow: true,
    cell: (_v, r) => (
      <span className="flex flex-wrap gap-1 py-0.5">
        {(r.traits_on ?? []).map((t) => (
          <Chip key={t} tone="info" title={t}>
            {traitName(t)}
          </Chip>
        ))}
      </span>
    ),
  },
  { id: 'regime', header: 'Regime', accessor: 'quadrant', width: 120, cell: (_v, r) => <QuadrantChip q={r.quadrant} label={r.quadrant_label} /> },
  { id: 'mult', header: 'Regime ×', accessor: 'regime_multiplier', width: 76, cell: (v) => (v == null ? '—' : `${fmtNum(v as number, 2)}×`) },
  { id: 'rs', header: 'RS %', accessor: 'rs_percentile', format: 'int', width: 56 },
  { id: 'range', header: '50d range', accessor: 'range_50d_pct', format: 'pct', digits: 0, width: 76 },
];

function BucketTable({ label, rows }: { label: string; rows: Bucket[] }) {
  return (
    <SimpleTable<Bucket>
      label={label}
      rows={rows}
      rowKey={(b) => b.bucket}
      columns={[
        { id: 'b', header: 'Score', cell: (b) => b.bucket },
        { id: 'e', header: 'Lifts', align: 'right', cell: (b) => fmtInt(b.events) },
        {
          id: 'r',
          header: 'Runners',
          align: 'right',
          cell: (b) => (b.events < 30 ? <span className="text-2xs italic text-fg-3">{fmtPct(b.runner_pct, 0)} · small n</span> : fmtPct(b.runner_pct, 1)),
        },
      ]}
    />
  );
}

function ProfileTable({ rows, picked }: { rows: TraitProfile[]; picked: ReadonlySet<string> }) {
  return (
    <SimpleTable<TraitProfile>
      label="Runner vs fizzle trait profile"
      rows={rows}
      rowKey={(r) => r.trait}
      rowClassName={(r) => (picked.has(r.trait) ? 'bg-accent/5' : undefined)}
      columns={[
        {
          id: 't',
          header: 'Trait',
          cell: (r) => (
            <span className="inline-flex items-center gap-1">
              <span className="w-[74px] shrink-0 text-2xs text-fg-3">{TRAIT_GROUPS[r.group] ?? r.group}</span>
              {traitName(r.label)}
              {picked.has(r.trait) && <Chip tone="accent">scored</Chip>}
            </span>
          ),
        },
        { id: 'rm', header: 'Runner median', align: 'right', cell: (r) => fmtNum(r.runner_median, 2) },
        { id: 'fm', header: 'Fizzle median', align: 'right', cell: (r) => fmtNum(r.fizzle_median, 2) },
        { id: 'lo', header: 'Low third', align: 'right', cell: (r) => <span className={cn(r.better_when === 'low' && 'font-medium text-up')}>{fmtPct(r.low_third_pct, 1)}</span> },
        { id: 'hi', header: 'High third', align: 'right', cell: (r) => <span className={cn(r.better_when === 'high' && 'font-medium text-up')}>{fmtPct(r.high_third_pct, 1)}</span> },
        { id: 'lift', header: 'Lift', align: 'right', cell: (r) => `${fmtNum(r.lift, 2)}×` },
        { id: 'n', header: 'n', align: 'right', cell: (r) => <SampleN n={r.n} /> },
      ]}
    />
  );
}

export function BeforeMovesView() {
  const [raw, setFam] = useUrlParam('family');
  const family: Family = raw === 'turnaround' ? 'turnaround' : 'trend';
  const q = useResearchQuery('research/before-moves', { query: { family, limit: 5000 } });
  const shell = useShell();
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
      <Caveat text={caveatOf(q.data?.meta)} />
      <nav aria-label="Lift family" className="flex flex-wrap gap-1">
        {FAMILIES.map((f) => (
          <button
            key={f.id}
            type="button"
            title={f.hint}
            aria-current={f.id === family ? 'page' : undefined}
            onClick={() => setFam(f.id === 'trend' ? null : f.id)}
            className={cn('rounded border px-2.5 py-1 text-xs', f.id === family ? 'border-accent bg-accent/10 text-fg' : 'border-line text-fg-3 hover:bg-surface-2')}
          >
            {f.label}
          </button>
        ))}
      </nav>
      <QueryState q={q} what="Early lifts (a stock closes 20% above its 120-session low), what separated runners from fizzles, and today's lifts scored by trait count.">
        {(env) => {
          const c = context<BeforeMovesContext>(env.meta);
          const picked = new Set((c.score_traits ?? []).map((t) => t.trait));
          const rows = env.rows as EarlyLiftRow[];
          const oos = c.oos;
          return (
            <>
              <Summary lines={c.summary} />
              <p className="text-2xs text-fg-3">
                {c.definition} {c.families?.[family]?.rule} Sample: {fmtInt(c.counts?.events)} lifts ({fmtInt(c.counts?.runners)} runners,{' '}
                {fmtInt(c.counts?.fizzles)} fizzles, {fmtInt(c.counts?.middle_excluded)} in between left out) from {fmtDate(c.counts?.from ?? null)} to{' '}
                {fmtDate(c.counts?.to ?? null)}. Base runner rate {fmtPct(c.counts?.base_runner_pct ?? null, 1)}.
              </p>
              <Panel
                title={`Today's early lifts · last ${c.today_sessions ?? 10} sessions`}
                subtitle={`Scored by ${c.score_traits?.length ?? 0} traits (on = value in the better third) · regime now: ${c.regime_now_label ?? '—'} · research, not a setup`}
                bodyClassName="flex min-h-[260px] flex-col"
                actions={
                  <button
                    type="button"
                    onClick={() => shell.openCharts(rows.map((r) => r.symbol))}
                    disabled={!rows.length}
                    className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-2xs text-fg-2 hover:bg-surface-3 disabled:opacity-50"
                  >
                    <LineChart className="h-3 w-3" aria-hidden /> Open in Charts
                  </button>
                }
              >
                <DataTable
                  label="Today's early lifts"
                  columns={LIFT_COLUMNS}
                  rows={rows}
                  total={env.total}
                  getRowId={(r) => `${r.symbol}-${r.lift_date}`}
                  initialSort={[{ id: 'score', desc: true }]}
                  activeRowId={shell.symbol ?? undefined}
                  onActiveRowChange={(r) => shell.openSymbol(r.symbol)}
                  onRowActivate={(r) => shell.openStockPage(r.symbol)}
                  emptyState={<div className="p-6 text-center text-xs text-fg-3">No stock in this family made an early lift in the window.</div>}
                  className="flex-1"
                />
              </Panel>
              <div className="grid gap-3 xl:grid-cols-3">
                <Panel title="Runner rate by score (in-sample)" subtitle={c.score_note}>
                  <BucketTable label="Runner rate by score" rows={c.score_buckets ?? []} />
                </Panel>
                <Panel
                  title="Out-of-sample check"
                  subtitle={
                    oos && oos.test_events
                      ? `Traits picked on ${fmtInt(oos.train_events)} lifts to ${fmtDate(oos.train_to ?? null)}, tested on ${fmtInt(oos.test_events)} later lifts (base ${fmtPct(oos.test_base_pct, 1)})`
                      : 'Too few lifts for a split'
                  }
                >
                  <BucketTable label="Out-of-sample runner rate by score" rows={oos?.buckets ?? []} />
                </Panel>
                <Panel title="Regime as a multiplier" subtitle="Runner rate of past lifts by the quadrant on the lift day, vs the family base">
                  <SimpleTable
                    label="Runner rate by regime quadrant"
                    rows={c.regime ?? []}
                    rowKey={(r) => r.quadrant}
                    rowClassName={(r) => (r.quadrant === c.regime_now ? 'bg-accent/10' : undefined)}
                    columns={[
                      { id: 'q', header: 'Quadrant', cell: (r) => <QuadrantChip q={r.quadrant} label={r.label} /> },
                      { id: 'n', header: 'Lifts', align: 'right', cell: (r) => fmtInt(r.events) },
                      { id: 'r', header: 'Runners', align: 'right', cell: (r) => fmtPct(r.runner_pct, 1) },
                      { id: 'm', header: '× base', align: 'right', cell: (r) => (r.multiplier == null ? '—' : `${fmtNum(r.multiplier, 2)}×`) },
                    ]}
                  />
                </Panel>
              </div>
              <Panel title="Trait profile: runners vs fizzles" subtitle="Runner rate in the low vs high third of each trait. Lift = better third ÷ family base.">
                <ProfileTable rows={c.profile ?? []} picked={picked} />
                <p className="px-3 py-1.5 text-2xs text-fg-3">
                  <Muted>
                    D = daily, W = weekly, M = monthly, A = accumulation over 10–13 weeks, I = improvement over 1–3 months, B = base. Accumulation counts from EOD
                    volume and delivery were weak in round 1.
                  </Muted>
                </p>
              </Panel>
            </>
          );
        }}
      </QueryState>
    </div>
  );
}
