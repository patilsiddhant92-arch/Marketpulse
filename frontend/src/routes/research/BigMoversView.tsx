/**
 * Big movers (spec 7.6): event browser, rolled-up catalyst attribution, the
 * out-of-sample lift table (with precision and n) and the median feature path
 * movers vs controls. Row focus follows the Stock 360 sidecar; click or Enter
 * opens the event.
 */
import { LineChart } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { BigMoveRow, EnvelopeMeta } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtCr, fmtDate, fmtNum, fmtPct, fmtSignedPct, isNum } from '../../lib/fmt';
import { useShell } from '../../shell/ShellContext';
import { VERDICT_TEXT } from '../../shell/environment';
import { useUrlParam } from '../../shell/urlState';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { Spark } from '../../ui/Spark';
import { CatalystChip, BigMoveDrawer } from './BigMoveDrawer';
import { useResearchQuery } from './data';
import {
  CATALYST_LABEL,
  CATALYST_TONE,
  TRIGGER_LABEL,
  TRIGGER_SHORT,
  asCatalyst,
  bigMoveExtras,
  catalystShares,
  ctx,
  featureLabel,
  num,
  offsetLabel,
  readFeaturePath,
  readLift,
  type LiftRow,
} from './model';
import { EvidencePending, FeatureName, Legend, Panel, PathChart, QueryState, SampleN, Stat, Term } from './parts';
import { SymbolWithDeal } from '../../ui/DealIcon';

const EMPTY: BigMoveRow[] = [];
const MCAP_FLOORS = [
  { v: 1000, label: '≥ ₹1,000 Cr' },
  { v: 5000, label: '≥ ₹5,000 Cr' },
  { v: 300, label: '≥ ₹300 Cr (watch)' },
];

const COLUMNS: DataTableColumn<BigMoveRow>[] = [
  { id: 'event_date', header: 'Event', accessor: 'event_date', format: 'date', width: 92, sortDescFirst: true },
  {
    id: 'symbol',
    header: 'Symbol',
    accessor: 'symbol',
    width: 100,
    sticky: true,
    cell: (v) => <SymbolWithDeal symbol={String(v)} />,
  },
  {
    id: 'trigger',
    header: 'Trigger',
    accessor: 'trigger',
    width: 92,
    headerTitle: 'Upper circuit · +30% in 20 sessions · +50% in 60 sessions',
    cell: (v) => (
      <span className="text-fg-2" title={TRIGGER_LABEL[String(v)]}>
        {TRIGGER_SHORT[String(v)] ?? String(v)}
      </span>
    ),
  },
  {
    id: 'move_pct',
    header: 'Move',
    accessor: 'move_pct',
    format: 'signedPct',
    width: 64,
    cell: (v) => <span className="num text-up">{fmtSignedPct(v as number)}</span>,
  },
  {
    id: 'path',
    header: 'T-20…T+20',
    accessor: (r) => bigMoveExtras(r).path_pct?.length ?? null,
    width: 84,
    sortable: false,
    renderNull: true,
    cell: (_v, r) => {
      const p = bigMoveExtras(r).path_pct;
      return p ? (
        <Spark values={p} baseline={0} tone="accent" label={`${r.symbol ?? ''} close vs T-1 around the event`} />
      ) : (
        <span className="text-fg-3">—</span>
      );
    },
  },
  { id: 'mcap', header: 'Mcap at event', accessor: 'mcap_cr_at_event', format: 'cr', digits: 0, width: 96, metricKey: 'market_cap_cr' },
  { id: 'catalyst', header: 'Catalyst', accessor: 'catalyst', width: 116, cell: (v) => <CatalystChip value={v} /> },
  {
    id: 'industry',
    header: 'Industry',
    accessor: 'industry',
    width: 128,
    grow: true,
    cell: (v) => <span className="truncate text-fg-2">{String(v)}</span>,
  },
  {
    id: 'verdict_then',
    header: 'Env then',
    accessor: (r) => bigMoveExtras(r).verdict_then,
    width: 96,
    defaultHidden: true,
    metricKey: 'environment_verdict',
    cell: (v) => <span className={VERDICT_TEXT[v as keyof typeof VERDICT_TEXT] ?? 'text-fg-2'}>{String(v)}</span>,
  },
];

function CatalystRollup({ rows }: { rows: readonly BigMoveRow[] }) {
  const { total, shares } = catalystShares(rows);
  if (!total) return <div className="p-3 text-2xs text-fg-3">No events in range.</div>;
  return (
    <div className="space-y-1.5 p-3">
      {shares.map((s) => (
        <div key={s.catalyst} className="grid grid-cols-[120px_1fr_88px] items-center gap-2 text-xs">
          <span>
            {s.catalyst === 'unknown' ? (
              <Chip>unattributed</Chip>
            ) : (
              <Chip tone={CATALYST_TONE[s.catalyst]}>{CATALYST_LABEL[s.catalyst]}</Chip>
            )}
          </span>
          <div className="h-2 rounded bg-surface-3" aria-hidden>
            <div
              className={cn('h-2 rounded', s.catalyst === 'unexplained' || s.catalyst === 'unknown' ? 'bg-fg-3' : 'bg-accent')}
              style={{ width: `${s.share * 100}%` }}
            />
          </div>
          <span className="num text-right">
            {fmtPct(s.share * 100, 0)} <span className="text-2xs text-fg-3">({s.n})</span>
          </span>
        </div>
      ))}
      <div className="flex items-center gap-2 pt-1 text-2xs text-fg-3">
        <span>Share of events by attributed catalyst.</span>
        <SampleN n={total} label="events" />
      </div>
    </div>
  );
}

function LiftTable({ meta }: { meta: EnvelopeMeta }) {
  const rows = readLift(meta);
  const baseRate = num(ctx(meta).base_rate_20d);
  if (!rows.length) {
    return (
      <EvidencePending
        compact
        meta={{ ...meta, reason: meta.reason ?? 'lift table not served yet', sources: ['big_move_features'] }}
        what="Out-of-sample lift of each pre-move trait (movers vs matched controls) and its precision: of stock-days like this, how many moved within 20 sessions."
      />
    );
  }
  return (
    <div className="space-y-1 p-3">
      <table className="w-full text-table" aria-label="Pre-move trait lift">
        <thead className="text-2xs uppercase tracking-wide text-fg-3">
          <tr>
            <th className="py-1 text-left font-medium">Trait</th>
            <th className="py-1 text-right font-medium">
              <Term k="lift">Lift</Term>
            </th>
            <th className="py-1 text-right font-medium">
              <Term k="precision_20d">Precision</Term>
            </th>
            <th className="py-1 text-right font-medium">Sample</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r: LiftRow) => (
            <tr key={`${r.feature}-${r.bucket}`} className="h-7 border-t border-line">
              <td className="pr-2">
                <div className="text-fg-2">
                  <FeatureName feature={r.feature} metricKey={r.metric_key} />
                </div>
                {r.bucket && <div className="text-2xs text-fg-3">{r.bucket}</div>}
              </td>
              <td className="text-right">
                <Stat
                  value={r.lift}
                  n={r.n_movers}
                  format={(v) => `${fmtNum(v, 1)}×`}
                  className={cn(isNum(r.lift) && r.lift >= 1.5 ? '[&_.num]:text-up' : '')}
                />
              </td>
              <td className="text-right">
                <Stat value={r.precision_20d} n={r.n_movers} format={(v) => fmtPct(v, 1)} />
              </td>
              <td className="text-right">
                <SampleN n={r.n_controls} label="ctrl" />
                {r.oos === false && (
                  <Chip tone="warn" className="ml-1" title="In-sample only: not validated on held-out data">
                    in-sample
                  </Chip>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="text-2xs text-fg-3">
        Precision = of stock-days with the trait, share that made a big move within 20 sessions.
        {baseRate !== null && (
          <>
            {' '}
            Base rate <span className="num text-fg-2">{fmtPct(baseRate, 1)}</span> for all stock-days.
          </>
        )}{' '}
        n = movers with the trait; ctrl = matched controls. Out-of-sample unless flagged.
      </div>
    </div>
  );
}

function FeaturePath({ meta }: { meta: EnvelopeMeta }) {
  const path = readFeaturePath(meta);
  const features = useMemo(() => [...new Set(path.map((p) => p.feature))], [path]);
  const [pick, setPick] = useState<string | null>(null);
  const feature = pick && features.includes(pick) ? pick : features[0];
  if (!features.length) {
    return (
      <EvidencePending
        compact
        meta={{ ...meta, reason: meta.reason ?? 'feature path not served yet', sources: ['big_move_features'] }}
        what="Median path of each trait from T-60 to T+20 for movers vs matched controls — when does strength build, when does volume dry up."
      />
    );
  }
  const pts = path.filter((p) => p.feature === feature).sort((a, b) => a.offset - b.offset);
  const nM = Math.max(...pts.map((p) => p.n_movers ?? 0));
  const nC = Math.max(...pts.map((p) => p.n_controls ?? 0));
  const offs = pts.map((p) => p.offset);
  return (
    <div className="space-y-1 p-3">
      <div className="flex flex-wrap gap-1">
        {features.map((f) => (
          <Chip key={f} onClick={() => setPick(f)} selected={f === feature} tone={f === feature ? 'accent' : 'neutral'}>
            {featureLabel(f)}
          </Chip>
        ))}
      </div>
      <PathChart
        label={`Median ${featureLabel(feature)} path, movers vs controls`}
        series={[
          { id: 'm', label: 'Movers (median)', points: pts.map((p) => ({ x: p.offset, y: p.movers })), tone: 'accent', strokeWidth: 2 },
          { id: 'c', label: 'Controls (median)', points: pts.map((p) => ({ x: p.offset, y: p.controls })), tone: 'muted', dashed: true },
        ]}
        xTicks={[...new Set([offs[0], -20, 0, offs[offs.length - 1]])]
          .filter((x) => x !== undefined)
          .map((x) => ({ x, label: offsetLabel(x) }))}
        yFormat={(v) => fmtNum(v, 1)}
        markerX={0}
        markerLabel="T"
        zeroLine={false}
        height={170}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Legend
          items={[
            { label: 'Movers', tone: 'accent' },
            { label: 'Controls', tone: 'muted', dashed: true },
          ]}
        />
        <SampleN n={nM} label="movers" />
        <SampleN n={nC} label="controls" />
      </div>
    </div>
  );
}

export function BigMoversView() {
  const shell = useShell();
  const [floorRaw, setFloor] = useUrlParam('rfloor');
  const [trigger, setTrigger] = useUrlParam('rtrig');
  const [catalyst, setCatalyst] = useUrlParam('rcat');
  const floor = MCAP_FLOORS.find((f) => String(f.v) === floorRaw)?.v ?? 1000;
  const q = useResearchQuery('research/big-moves', { query: { min_mcap_cr: floor, limit: 2000 } });
  const [open, setOpen] = useState<BigMoveRow | null>(null);
  const [visible, setVisible] = useState<readonly BigMoveRow[]>(EMPTY);
  const all = q.data?.rows ?? EMPTY;
  const rows = useMemo(
    () => all.filter((r) => (!trigger || r.trigger === trigger) && (!catalyst || (asCatalyst(r.catalyst) ?? 'unknown') === catalyst)),
    [all, trigger, catalyst],
  );

  return (
    <QueryState
      q={q}
      what="Every upper-circuit, +30% in 20 sessions and +50% in 60 sessions event (mcap ≥ ₹1,000 Cr as of the event date), its catalyst, and the traits that preceded it compared with matched controls."
    >
      {(env) => {
        return (
          <div className="grid h-full min-h-0 grid-cols-1 gap-3 overflow-auto p-3 xl:grid-cols-[minmax(0,7fr)_minmax(0,4fr)]">
            <Panel
              title="Event browser"
              subtitle={`Movers with mcap ${MCAP_FLOORS.find((f) => f.v === floor)?.label} as of the event date · click an event for its fingerprint`}
              bodyClassName="flex min-h-[420px] flex-col"
              actions={
                <button
                  type="button"
                  onClick={() => shell.openCharts(visible.map((r) => r.symbol ?? '').filter(Boolean))}
                  disabled={!visible.length}
                  className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-2xs text-fg-2 hover:bg-surface-3 disabled:opacity-50"
                >
                  <LineChart className="h-3 w-3" aria-hidden /> Open in Charts
                </button>
              }
            >
              <div className="flex flex-wrap items-center gap-1 border-b border-line px-3 py-1.5">
                <span className="mr-1 text-2xs text-fg-3">Trigger</span>
                <Chip onClick={() => setTrigger(null)} selected={!trigger}>
                  All
                </Chip>
                {Object.entries(TRIGGER_SHORT).map(([k, label]) => (
                  <Chip key={k} onClick={() => setTrigger(trigger === k ? null : k)} selected={trigger === k} title={TRIGGER_LABEL[k]}>
                    {label}
                  </Chip>
                ))}
                <span className="ml-3 mr-1 text-2xs text-fg-3">Catalyst</span>
                <Chip onClick={() => setCatalyst(null)} selected={!catalyst}>
                  All
                </Chip>
                {Object.entries(CATALYST_LABEL).map(([k, label]) => (
                  <Chip key={k} onClick={() => setCatalyst(catalyst === k ? null : k)} selected={catalyst === k}>
                    {label}
                  </Chip>
                ))}
                <label className="ml-auto flex items-center gap-1 text-2xs text-fg-3">
                  Mcap
                  <select
                    value={floor}
                    onChange={(e) => setFloor(e.target.value === '1000' ? null : e.target.value)}
                    className="rounded border border-line bg-surface-2 px-1 py-0.5 text-2xs text-fg"
                  >
                    {MCAP_FLOORS.map((f) => (
                      <option key={f.v} value={f.v}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <DataTable
                label="Big-move events"
                columns={COLUMNS}
                rows={rows}
                total={trigger || catalyst ? rows.length : env.total}
                getRowId={(r, i) => r.event_id ?? `${r.symbol}-${r.event_date}-${i}`}
                initialSort={[{ id: 'event_date', desc: true }]}
                activeRowId={open?.event_id ?? undefined}
                onActiveRowChange={(r) => r.symbol && shell.openSymbol(r.symbol)}
                onRowClick={(r) => setOpen(r)}
                onRowActivate={(r) => setOpen(r)}
                onSortedRowsChange={setVisible}
                emptyState={
                  <div className="p-6 text-center text-xs text-fg-3">
                    No big-move events match these filters on or before {fmtDate(env.as_of)}.
                  </div>
                }
                className="flex-1"
              />
            </Panel>
            <div className="flex min-h-0 flex-col gap-3">
              <Panel title="Catalyst attribution" subtitle="Results / deal ±3 sessions · sector-wide if ≥ 50% of the Industry moved">
                <CatalystRollup rows={rows} />
              </Panel>
              <Panel title="What preceded the move" subtitle="Out-of-sample lift vs matched controls (date, industry, mcap/ADV bucket)">
                <LiftTable meta={env.meta} />
              </Panel>
              <Panel title="Median path T-60 … T+20" subtitle="Movers vs matched controls">
                <FeaturePath meta={env.meta} />
              </Panel>
              <div className="text-2xs text-fg-3">
                Mcap floor applied as of each event date (<span className="num">{fmtCr(floor, 0)}</span>); no survivorship.
              </div>
            </div>
            <BigMoveDrawer row={open} onClose={() => setOpen(null)} />
          </div>
        );
      }}
    </QueryState>
  );
}
