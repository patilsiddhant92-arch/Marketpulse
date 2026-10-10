/**
 * Big-mover case study (10-tab-research.md §12): pick a symbol or a stock from
 * the year's big-mover list. The chart shades the low → peak move, marks every
 * screener preset's fresh fire with its letter and the 20 EMA ladder's trades.
 * The first-fire table and the precision context are always shown, so a preset
 * that "caught" a winner never oversells.
 */
import { LineChart, Search } from 'lucide-react';
import { useMemo, useState, type FormEvent } from 'react';
import { cn } from '../../lib/cn';
import { fmtCr, fmtDate, fmtInt, fmtNum, fmtPct, fmtSignedPct, isNum } from '../../lib/fmt';
import { useShell } from '../../shell/ShellContext';
import { useUrlParam } from '../../shell/urlState';
import type { EnvelopeMeta } from '../../api/types';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { CaseChart } from './CaseChart';
import { useResearchQuery } from './data';
import {
  caveatOf,
  context,
  fireMarkers,
  precisionLift,
  type CaseBarRow,
  type CaseContext,
  type CaseMoverRow,
  type FirstFire,
  type LadderLeg,
  type PrecisionContext,
  type PrecisionRow,
} from './lab';
import { Caveat, Muted, SimpleTable, Summary } from './LabParts';
import { Panel, QueryState, SampleN } from './parts';

const SYMBOL_RE = /^[A-Z0-9&\-_.]{1,20}$/;

const MOVER_COLUMNS: DataTableColumn<CaseMoverRow>[] = [
  { id: 'symbol', header: 'Symbol', accessor: 'symbol', width: 110, sticky: true, cell: (v) => <span className="font-mono font-medium text-fg">{String(v)}</span> },
  { id: 'gain', header: 'Low → peak', accessor: 'gain_pct', format: 'signedPct', digits: 0, width: 90 },
  { id: 'low', header: 'Low on', accessor: 'low_date', format: 'date', width: 92 },
  {
    id: 'early',
    header: 'First early fire',
    accessor: 'first_early_vs_low_pct',
    width: 130,
    headerTitle: 'First fresh fire of Delivery thrust / EMAs converge / VCP flag after the low, % above the low',
    cell: (_v, r) =>
      r.first_early_preset ? (
        <span className="text-2xs">
          {r.first_early_preset} <span className="num text-fg-3">+{fmtNum(r.first_early_vs_low_pct, 0)}%</span>
        </span>
      ) : (
        <Muted>none</Muted>
      ),
  },
  { id: 'ladder', header: 'Ladder', accessor: 'ladder_pct', format: 'signedPct', digits: 0, width: 76, headerTitle: '20 EMA re-entry ladder, compounded' },
  { id: 'trades', header: 'Trades', accessor: 'trades', format: 'int', width: 60 },
];

export function PrecisionPanel({ p, highlight }: { p: Partial<PrecisionContext> | undefined; highlight?: ReadonlySet<string> }) {
  const rows = (p?.rows ?? []).filter((r) => r.preset_id !== 'all');
  const base = p?.base_hit_pct ?? null;
  return (
    <Panel
      title="Precision context: how often a fire became a +50% move"
      subtitle={`Fresh fires ${fmtDate(p?.window_from ?? null)} – ${fmtDate(p?.window_to ?? null)} · base rate ${fmtPct(base, 1)} of all stock-days (n=${fmtInt(p?.base_n)})`}
    >
      <SimpleTable<PrecisionRow>
        label="Preset precision"
        rows={rows}
        rowKey={(r) => r.preset_id}
        rowClassName={(r) => (highlight?.has(r.preset_id) ? 'bg-accent/10' : undefined)}
        columns={[
          { id: 'p', header: 'Preset', cell: (r) => <span><span className="font-mono text-violet">{r.letter}</span> {r.preset}</span> },
          { id: 'f', header: 'Fires', align: 'right', cell: (r) => fmtInt(r.fires) },
          { id: 'h', header: 'Hit +50%', align: 'right', cell: (r) => fmtPct(r.hit_pct, 1) },
          { id: 'fa', header: 'False alarms', align: 'right', cell: (r) => (isNum(r.hit_pct) ? fmtPct(100 - r.hit_pct, 1) : '—') },
          { id: 'l', header: 'vs base', align: 'right', cell: (r) => { const l = precisionLift(r, base); return isNum(l) ? `${fmtNum(l, 2)}×` : '—'; } },
          {
            id: 'rs',
            header: 'With RS ≥ 80',
            align: 'right',
            cell: (r) => (
              <span className="inline-flex items-baseline gap-1.5">
                {fmtPct(r.hit_rs80_pct, 1)} <SampleN n={r.fires_rs80} />
              </span>
            ),
          },
        ]}
      />
      <p className="px-3 py-1.5 text-2xs text-fg-3">{p?.definition} No single preset picks the winner. The edge comes from stacking evidence, small losses and re-entry.</p>
    </Panel>
  );
}

function FirstFireTable({ rows }: { rows: FirstFire[] }) {
  const sorted = useMemo(
    () => [...rows].sort((a, b) => (a.first_fire ?? '9999').localeCompare(b.first_fire ?? '9999') || a.preset.localeCompare(b.preset)),
    [rows],
  );
  return (
    <SimpleTable<FirstFire>
      label="First fire per preset"
      rows={sorted}
      rowKey={(r) => r.preset_id}
      columns={[
        {
          id: 'p',
          header: 'Preset',
          cell: (r) => (
            <span className="inline-flex items-center gap-1">
              <span className="font-mono text-violet">{r.letter}</span> {r.preset}
              {r.early && <Chip tone="violet">early</Chip>}
            </span>
          ),
        },
        { id: 'd', header: 'First fire', cell: (r) => (r.first_fire ? fmtDate(r.first_fire) : <Muted>did not fire in the move</Muted>) },
        { id: 'e', header: 'Entry', align: 'right', cell: (r) => fmtNum(r.entry, 1) },
        { id: 'l', header: 'Above low', align: 'right', cell: (r) => (isNum(r.entry_vs_low_pct) ? `+${fmtNum(r.entry_vs_low_pct, 0)}%` : '—') },
        { id: 'pk', header: 'Room to peak', align: 'right', cell: (r) => (isNum(r.to_peak_pct) ? `+${fmtNum(r.to_peak_pct, 0)}%` : '—') },
        {
          id: 't',
          header: '20 EMA exit',
          align: 'right',
          title: 'Buy at the fire close, sell at the first close below the 20 EMA',
          cell: (r) => (isNum(r.trail20_pct) ? `${fmtSignedPct(r.trail20_pct, 1)}${r.trail20_open ? ' (open)' : ''}` : '—'),
        },
        { id: 'n', header: 'Fires in move', align: 'right', cell: (r) => fmtInt(r.fresh_fires) },
      ]}
    />
  );
}

function LadderTable({ legs }: { legs: LadderLeg[] }) {
  return (
    <SimpleTable<LadderLeg>
      label="20 EMA ladder trades"
      rows={legs}
      rowKey={(l) => l.entry_date}
      empty="No entry signal fired with the close above the 20 EMA."
      columns={[
        { id: 'in', header: 'Entry', cell: (l) => fmtDate(l.entry_date) },
        { id: 's', header: 'Signal', cell: (l) => <span><span className="font-mono text-violet">{l.letter}</span> {l.signal}</span> },
        { id: 'ep', header: 'Buy', align: 'right', cell: (l) => fmtNum(l.entry, 1) },
        { id: 'out', header: 'Exit', cell: (l) => (l.open ? <Muted>open</Muted> : fmtDate(l.exit_date)) },
        { id: 'xp', header: 'Sell', align: 'right', cell: (l) => fmtNum(l.exit, 1) },
        { id: 'pnl', header: 'P&L', align: 'right', cell: (l) => <span className={cn(l.pnl_pct >= 0 ? 'text-up' : 'text-down')}>{fmtSignedPct(l.pnl_pct, 1)}</span> },
      ]}
    />
  );
}

function CaseBody({ symbol }: { symbol: string }) {
  const q = useResearchQuery('research/case-study/{sym}', { params: { sym: symbol } });
  return (
    <QueryState q={q} what={`Case study of ${symbol}: the low-to-peak move, every preset's fresh fire and the 20 EMA ladder.`} compact>
      {(env) => <CaseContent symbol={symbol} meta={env.meta} bars={env.rows as CaseBarRow[]} />}
    </QueryState>
  );
}

function CaseContent({ symbol, meta, bars }: { symbol: string; meta: EnvelopeMeta; bars: CaseBarRow[] }) {
  const shell = useShell();
  const [onlyMove, setOnlyMove] = useState(true);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const c = useMemo(() => context<CaseContext>(meta), [meta]);
  const fires = useMemo(() => fireMarkers(c.fires ?? [], onlyMove, hidden), [c, onlyMove, hidden]);
  const legs = useMemo(() => c.ladder?.legs ?? [], [c]);
  const move = useMemo(() => c.move ?? null, [c]);
  const fired = useMemo(() => new Set((c.first_fires ?? []).filter((f) => f.first_fire).map((f) => f.preset_id)), [c]);
  return (
    <div className="space-y-3">
      <Panel
        title={
          <span>
            {c.symbol} <span className="font-normal normal-case text-fg-3">{c.security_name}</span>
          </span>
        }
        subtitle={`${c.industry ?? ''} · ${fmtCr(c.mcap_cr ?? null, 0)} · window ${fmtDate(c.window_from ?? null)} – ${fmtDate(c.window_to ?? null)}`}
        actions={
          <div className="flex items-center gap-2">
            {c.big_mover ? <Chip tone="positive">big mover</Chip> : <Chip tone="neutral">not a big mover</Chip>}
            {c.below_floor && <Chip tone="warn">below ₹1,000 Cr</Chip>}
            <button
              type="button"
              onClick={() => shell.openCharts([symbol])}
              className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-2xs text-fg-2 hover:bg-surface-3"
            >
              <LineChart className="h-3 w-3" aria-hidden /> Open in Charts
            </button>
          </div>
        }
        bodyClassName="space-y-2 p-2"
      >
        <Summary lines={c.summary} />
        <div className="flex flex-wrap items-center gap-1.5 text-2xs text-fg-3">
          <label className="inline-flex items-center gap-1">
            <input type="checkbox" checked={onlyMove} onChange={(e) => setOnlyMove(e.target.checked)} /> Only fires inside the move
          </label>
          <span className="ml-2">Presets:</span>
          {(c.presets ?? []).map((p) => (
            <Chip
              key={p.id}
              tone={hidden.has(p.id) ? 'neutral' : 'violet'}
              variant={hidden.has(p.id) ? 'outline' : 'soft'}
              selected={!hidden.has(p.id)}
              title={`${p.description}${fired.has(p.id) ? '' : ' (did not fire in the move)'}`}
              onClick={() =>
                setHidden((h) => {
                  const n = new Set(h);
                  if (n.has(p.id)) n.delete(p.id);
                  else n.add(p.id);
                  return n;
                })
              }
            >
              {p.letter} {p.name}
            </Chip>
          ))}
        </div>
        <CaseChart
          label={`${symbol} case study chart`}
          bars={bars}
          move={move}
          fires={fires}
          legs={legs}
        />
        <p className="text-2xs text-fg-3">
          Shaded: low {fmtNum(c.move?.low ?? null, 1)} on {fmtDate(c.move?.low_date ?? null)} → peak {fmtNum(c.move?.peak ?? null, 1)} on{' '}
          {fmtDate(c.move?.peak_date ?? null)} ({fmtSignedPct(c.move?.gain_pct ?? null, 0)}). Letters = fresh fires (true today, false the previous 5
          sessions). B / S = ladder buy / sell. Line = 20 EMA.
        </p>
      </Panel>
      <div className="grid gap-3 xl:grid-cols-2">
        <Panel title="First fire per preset (after the low)">
          <FirstFireTable rows={c.first_fires ?? []} />
        </Panel>
        <Panel
          title={`20 EMA ladder: ${c.ladder?.trades ?? 0} trades, compounded ${fmtSignedPct(c.ladder?.compounded_pct ?? null, 0)}`}
          subtitle={c.ladder?.rule}
        >
          <LadderTable legs={legs} />
        </Panel>
      </div>
      <PrecisionPanel p={c.precision} highlight={fired} />
    </div>
  );
}

export function CaseStudyView() {
  const [sym, setSym] = useUrlParam('case');
  const [draft, setDraft] = useState(sym ?? '');
  const [bad, setBad] = useState(false);
  const movers = useResearchQuery('research/case-study', { query: { limit: 5000 } });
  const shell = useShell();
  const active = sym && SYMBOL_RE.test(sym) ? sym : (movers.data?.rows[0]?.symbol ?? null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const s = draft.trim().toUpperCase();
    if (!SYMBOL_RE.test(s)) {
      setBad(true);
      return;
    }
    setBad(false);
    setSym(s);
  };
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
      <Caveat text={caveatOf(movers.data?.meta)} />
      <form onSubmit={submit} className="flex flex-wrap items-center gap-2" role="search" aria-label="Case study symbol">
        <label className="text-2xs text-fg-3" htmlFor="case-symbol">
          Study a stock
        </label>
        <input
          id="case-symbol"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="e.g. MTARTECH"
          className={cn('w-40 rounded border bg-surface-2 px-2 py-1 font-mono text-xs uppercase', bad ? 'border-down' : 'border-line')}
        />
        <button type="submit" className="inline-flex items-center gap-1 rounded border border-line px-2 py-1 text-2xs text-fg-2 hover:bg-surface-3">
          <Search className="h-3 w-3" aria-hidden /> Study
        </button>
        {bad && <span className="text-2xs text-down">Use an NSE symbol (letters, digits, &amp; - _ .)</span>}
        <span className="text-2xs text-fg-3">or pick one from the big-mover list.</span>
      </form>
      <div className="grid min-h-0 gap-3 xl:grid-cols-[minmax(320px,420px)_1fr]">
        <Panel
          title="Big movers"
          subtitle={
            movers.data
              ? `${fmtInt(movers.data.total)} stocks ≥ ₹1,000 Cr doubled (low → peak) in the 12 months to ${fmtDate(movers.data.as_of)}`
              : undefined
          }
          bodyClassName="flex min-h-[420px] flex-col"
        >
          <QueryState q={movers} what="Stocks that doubled from their 12-month low, with the 20 EMA ladder result." compact>
            {(env) => (
              <DataTable
                label="Big movers"
                columns={MOVER_COLUMNS}
                rows={env.rows as CaseMoverRow[]}
                total={env.total}
                getRowId={(r) => r.symbol}
                initialSort={[{ id: 'gain', desc: true }]}
                activeRowId={active ?? undefined}
                onActiveRowChange={(r) => {
                  setSym(r.symbol);
                  setDraft(r.symbol);
                }}
                onRowActivate={(r) => shell.openStockPage(r.symbol)}
                className="flex-1"
              />
            )}
          </QueryState>
        </Panel>
        <div className="min-w-0">{active ? <CaseBody key={active} symbol={active} /> : <Muted>Pick a stock to study.</Muted>}</div>
      </div>
    </div>
  );
}
