/**
 * Signal log + setup scorecard (10-tab-research.md §7, "log and grade"): every Desk setup's first day
 * in its queue (Darvas squeeze, 10 EMA Pullback / Trace-back / Catch-up, VCP) is logged by the daily
 * pipeline and graded 5 / 10 / 20 sessions later: return, vs the equal-weight market, R vs the stop,
 * stop hit and trigger reached. A setup that lagged the market three graded months in a row is
 * flagged "not working now". Rows logged live are the honest record; the rest were backfilled.
 */
import { useMemo, useState } from 'react';
import type { components } from '../../api/types.gen';
import { cn } from '../../lib/cn';
import { fmtDate, fmtInt, fmtNum, fmtPct, fmtSignedPct, isNum } from '../../lib/fmt';
import { useShell } from '../../shell/ShellContext';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { Segmented } from '../groups/kit';
import { useResearchQuery } from './data';
import { caveatOf, context } from './lab';
import { Caveat, Muted, SimpleTable, Summary } from './LabParts';
import { Panel, QueryState, SampleN } from './parts';

export type SignalScoreRow = components['schemas']['SignalScoreRow'];
export type SignalLogRow = components['schemas']['SignalLogRow'];

export interface MonthRow {
  setup: string;
  setup_label: string;
  month: string;
  signals: number;
  graded_20: number;
  hit_20_pct: number | null;
  avg_excess_20: number | null;
  avg_r_20: number | null;
}

export interface SignalScoreContext {
  caveat: string;
  monthly: MonthRow[];
  summary: string[];
  definition: string;
  not_working_rule: string;
}

export const SETUP_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'darvas_squeeze', label: 'Darvas squeeze' },
  { value: 'darvas_10ema:Pullback', label: '10 EMA · Pullback' },
  { value: 'darvas_10ema:Trace-back', label: '10 EMA · Trace-back' },
  { value: 'darvas_10ema:Catch-up', label: '10 EMA · Catch-up' },
  { value: 'vcp', label: 'VCP' },
] as const;
type SetupFilter = (typeof SETUP_OPTIONS)[number]['value'];

/** Last `n` months of one setup, oldest first. Pure; unit-tested. */
export function recentMonths(rows: readonly MonthRow[], setup: string, n = 12): MonthRow[] {
  return rows.filter((r) => r.setup === setup).slice(-n);
}

const signed = (v: number | null | undefined, d = 1) => (
  <span className={cn(isNum(v) ? (v >= 0 ? 'text-up' : 'text-down') : 'text-fg-3')}>{fmtSignedPct(v ?? null, d)}</span>
);
const rMult = (v: number | null | undefined) => (
  <span className={cn(isNum(v) ? (v >= 0 ? 'text-up' : 'text-down') : 'text-fg-3')}>{isNum(v) ? `${v >= 0 ? '+' : ''}${fmtNum(v, 2)}R` : '—'}</span>
);

function Scorecard({ rows, active, onPick }: { rows: SignalScoreRow[]; active: string | null; onPick: (s: string) => void }) {
  return (
    <SimpleTable<SignalScoreRow>
      label="Signal scorecard"
      rows={rows}
      rowKey={(r) => r.setup}
      rowClassName={(r) => (r.setup === active ? 'bg-accent/10' : undefined)}
      columns={[
        {
          id: 's',
          header: 'Setup',
          cell: (r) => (
            <button type="button" className="inline-flex items-center gap-1 text-left hover:underline" onClick={() => onPick(r.setup)}>
              {r.setup_label}
              {r.not_working && <Chip tone="negative">not working now</Chip>}
            </button>
          ),
        },
        { id: 'n', header: 'Signals', align: 'right', cell: (r) => <span className="inline-flex items-baseline gap-1">{fmtInt(r.signals)} <SampleN n={r.live} label="live" /></span> },
        { id: 'hit', header: 'Beat mkt 20s', align: 'right', title: 'Share of graded signals that beat the equal-weight market over 20 sessions', cell: (r) => <span className="inline-flex items-baseline gap-1">{fmtPct(r.hit_20_pct ?? null, 0)} <SampleN n={r.graded_20} /></span> },
        { id: 'e5', header: 'vs mkt 5s', align: 'right', cell: (r) => signed(r.avg_excess_5) },
        { id: 'e10', header: '10s', align: 'right', cell: (r) => signed(r.avg_excess_10) },
        { id: 'e20', header: '20s', align: 'right', cell: (r) => signed(r.avg_excess_20) },
        { id: 'r', header: 'Avg R 20s', align: 'right', title: 'Gain / (entry − stop); a stop hit exits at min(open, stop)', cell: (r) => rMult(r.avg_r_20) },
        { id: 'st', header: 'Stopped', align: 'right', cell: (r) => fmtPct(r.stopped_20_pct ?? null, 0) },
        { id: 'tr', header: 'Triggered', align: 'right', cell: (r) => fmtPct(r.triggered_20_pct ?? null, 0) },
        { id: 'rec', header: 'Last 3 mo vs mkt', align: 'right', title: 'Average 20-session excess over the last 3 graded months', cell: (r) => signed(r.recent_avg_excess_20) },
      ]}
    />
  );
}

function Months({ rows }: { rows: MonthRow[] }) {
  return (
    <SimpleTable<MonthRow>
      label="Signal scorecard by month"
      rows={rows}
      rowKey={(r) => r.month}
      empty="No months logged yet."
      columns={[
        { id: 'm', header: 'Month', cell: (r) => r.month },
        { id: 'n', header: 'Signals', align: 'right', cell: (r) => fmtInt(r.signals) },
        { id: 'g', header: 'Graded', align: 'right', cell: (r) => fmtInt(r.graded_20) },
        { id: 'h', header: 'Beat mkt', align: 'right', cell: (r) => fmtPct(r.hit_20_pct, 0) },
        { id: 'e', header: 'vs mkt 20s', align: 'right', cell: (r) => signed(r.avg_excess_20) },
        { id: 'r', header: 'Avg R', align: 'right', cell: (r) => rMult(r.avg_r_20) },
      ]}
    />
  );
}

const LOG_COLUMNS: DataTableColumn<SignalLogRow>[] = [
  { id: 'd', header: 'Signal', accessor: 'trade_date', format: 'date', width: 92 },
  { id: 'sym', header: 'Symbol', accessor: 'symbol', width: 110, sticky: true, cell: (v) => <span className="font-mono font-medium text-fg">{String(v)}</span> },
  { id: 'setup', header: 'Setup', accessor: 'setup_label', width: 140 },
  { id: 'c', header: 'Close', accessor: 'signal_close', format: 'num', digits: 1, width: 76 },
  { id: 'stop', header: 'Stop', accessor: 'stop_price', format: 'num', digits: 1, width: 76 },
  { id: 'risk', header: 'Risk %', accessor: 'risk_pct', format: 'num', digits: 1, width: 62 },
  { id: 'e5', header: 'vs mkt 5s', accessor: 'excess_5', width: 76, cell: (v) => signed(v as number | null) },
  { id: 'e20', header: 'vs mkt 20s', accessor: 'excess_20', width: 80, cell: (v) => signed(v as number | null) },
  { id: 'r20', header: 'R 20s', accessor: 'r_20', width: 66, cell: (v) => rMult(v as number | null) },
  {
    id: 'st',
    header: 'Status',
    accessor: (r) => (r.stopped_20 ? 'stopped' : r.excess_20 == null ? 'open' : 'graded'),
    width: 92,
    cell: (_v, r) =>
      r.grade_note === 'gap' && r.excess_20 == null ? (
        <Muted>data gap</Muted>
      ) : r.stopped_20 || r.stopped_10 || r.stopped_5 ? (
        <Chip tone="negative">stopped</Chip>
      ) : r.excess_20 == null ? (
        <Muted>grading</Muted>
      ) : (
        <Chip tone={(r.excess_20 ?? 0) >= 0 ? 'positive' : 'neutral'}>{(r.excess_20 ?? 0) >= 0 ? 'beat mkt' : 'lagged'}</Chip>
      ),
  },
  { id: 'log', header: 'Logged', accessor: 'logged', width: 76, cell: (v) => (v === 'live' ? <Chip tone="info">live</Chip> : <Muted>backfill</Muted>) },
];

function SignalLog({ setup }: { setup: SetupFilter }) {
  const shell = useShell();
  const [days, setDays] = useState<'10' | '30' | '90'>('30');
  const q = useResearchQuery('research/signal-log', { query: { days: Number(days), ...(setup !== 'all' ? { setup } : {}), limit: 5000 } });
  return (
    <Panel
      title="Signal log"
      subtitle="Each setup's first day in its Desk queue, newest first. Grades appear as their 5 / 10 / 20 sessions close."
      actions={<Segmented size="xs" label="Signal window" value={days} onChange={(v) => setDays(v as '10' | '30' | '90')} options={[{ value: '10', label: '10d' }, { value: '30', label: '30d' }, { value: '90', label: '90d' }]} />}
      bodyClassName="flex min-h-[360px] flex-col"
    >
      <QueryState q={q} what="The Desk signal log, written by the daily pipeline (Scripts/research_lab.py)." compact>
        {(env) => (
          <DataTable
            label="Signal log"
            columns={LOG_COLUMNS}
            rows={env.rows as SignalLogRow[]}
            total={env.total}
            getRowId={(r) => r.setup_id}
            onRowActivate={(r) => shell.openStockPage(r.symbol)}
            className="flex-1"
          />
        )}
      </QueryState>
    </Panel>
  );
}

export function SignalLogView() {
  const q = useResearchQuery('research/signal-scorecard');
  const [setup, setSetup] = useState<SetupFilter>('all');
  const [picked, setPicked] = useState<string | null>(null);
  return (
    <QueryState q={q} what="The log-and-grade scorecard of the Desk setups (written by the daily pipeline).">
      {(env) => (
        <SignalBody rows={env.rows as SignalScoreRow[]} ctx={context<SignalScoreContext>(env.meta)} caveat={caveatOf(env.meta)} setup={setup} setSetup={setSetup} picked={picked} setPicked={setPicked} />
      )}
    </QueryState>
  );
}

function SignalBody({
  rows,
  ctx,
  caveat,
  setup,
  setSetup,
  picked,
  setPicked,
}: {
  rows: SignalScoreRow[];
  ctx: Partial<SignalScoreContext>;
  caveat: string;
  setup: SetupFilter;
  setSetup: (s: SetupFilter) => void;
  picked: string | null;
  setPicked: (s: string) => void;
}) {
  const active = picked ?? rows[0]?.setup ?? null;
  const months = useMemo(() => (active ? recentMonths(ctx.monthly ?? [], active) : []), [ctx.monthly, active]);
  const activeLabel = rows.find((r) => r.setup === active)?.setup_label ?? active ?? '';
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
      <Caveat text={caveat} />
      <Summary lines={ctx.summary} />
      <Panel title="Setup scorecard: logged and graded" subtitle={ctx.definition}>
        <Scorecard rows={rows} active={active} onPick={setPicked} />
        <p className="px-3 py-1.5 text-2xs text-fg-3">{ctx.not_working_rule}</p>
      </Panel>
      <div className="grid gap-3 xl:grid-cols-[minmax(320px,420px)_1fr]">
        <Panel title={`By month: ${activeLabel}`} subtitle={`Last ${months.length} months · graded at 20 sessions${rows.find((r) => r.setup === active)?.first_signal ? ` · since ${fmtDate(rows.find((r) => r.setup === active)?.first_signal ?? null)}` : ''}`}>
          <Months rows={months} />
        </Panel>
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-2xs text-fg-3">
            <span>Setup</span>
            <Segmented size="xs" label="Setup" value={setup} onChange={(v) => setSetup(v as SetupFilter)} options={SETUP_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
          </div>
          <SignalLog setup={setup} />
        </div>
      </div>
    </div>
  );
}
