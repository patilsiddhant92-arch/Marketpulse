/**
 * Setup evidence (spec 5, 6.1.5): outcome aggregates per queue × environment
 * state (or × group quadrant). n < 30 prints "insufficient sample" instead of
 * a number. Plus stock analogs: nearest past setups of the same queue for the
 * sidecar symbol and how they turned out.
 */
import type { UseQueryResult } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { isUnavailable } from '../../api/client';
import { useApiQuery } from '../../api/query';
import type { Envelope, EvidenceRow, StockAnalogRow } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtDate, fmtNum, fmtPct, fmtSigned, isNum } from '../../lib/fmt';
import { useShell } from '../../shell/ShellContext';
import { VERDICT_TEXT } from '../../shell/environment';
import { isSymbol, useUrlParam } from '../../shell/urlState';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { Skeleton } from '../../ui/Skeleton';
import { useFixtureMode, useResearchQuery } from './data';
import { MIN_SAMPLE, VERDICT_ORDER, asVerdictWord, median } from './model';
import { EvidencePending, Panel, QueryState, SampleN, Stat, Term } from './parts';

const QUEUES = [
  { id: 'darvas_squeeze', label: 'Darvas Squeeze' },
  { id: 'darvas_10ema', label: 'Darvas 10 EMA' },
  { id: 'vcp', label: 'VCP' },
] as const;

type By = 'environment' | 'quadrant' | 'all';
const BY_OPTIONS: { id: By; label: string }[] = [
  { id: 'environment', label: 'Environment state' },
  { id: 'quadrant', label: 'Industry quadrant' },
  { id: 'all', label: 'All signals' },
];
const QUADRANTS = ['Leading', 'Improving', 'Weakening', 'Lagging'];

type MetricId = 'hit_rate_2r' | 'avg_r' | 'median_r' | 'mae_pct' | 'mfe_pct';
const METRICS: { id: MetricId; label: string; fmt: (v: number) => string; signed?: boolean }[] = [
  { id: 'hit_rate_2r', label: 'Hit +2R', fmt: (v) => fmtPct(v, 1) },
  { id: 'avg_r', label: 'Avg R', fmt: (v) => `${fmtSigned(v, 2)}R`, signed: true },
  { id: 'median_r', label: 'Median R', fmt: (v) => `${fmtSigned(v, 2)}R`, signed: true },
  { id: 'mae_pct', label: 'MAE', fmt: (v) => fmtPct(v, 1) },
  { id: 'mfe_pct', label: 'MFE', fmt: (v) => fmtPct(v, 1) },
];

function bucketsFor(by: By, rows: readonly EvidenceRow[][]): string[] {
  const base = by === 'environment' ? ['all', ...VERDICT_ORDER] : by === 'quadrant' ? ['all', ...QUADRANTS] : ['all'];
  const seen = new Set(base.map((b) => b.toLowerCase()));
  const extra: string[] = [];
  rows.flat().forEach((r) => {
    if (!seen.has(r.bucket.toLowerCase())) {
      seen.add(r.bucket.toLowerCase());
      extra.push(r.bucket);
    }
  });
  return [...base, ...extra];
}

function findBucket(rows: readonly EvidenceRow[], bucket: string): EvidenceRow | undefined {
  return rows.find((r) => r.bucket.toLowerCase() === bucket.toLowerCase());
}

/** n-weighted avg R of the sufficient buckets in a set; null if none. */
function pooledAvgR(rows: readonly EvidenceRow[], buckets: readonly string[]): { r: number | null; n: number } {
  let n = 0;
  let sum = 0;
  for (const b of buckets) {
    const row = findBucket(rows, b);
    if (row && !row.insufficient_sample && isNum(row.avg_r)) {
      n += row.n;
      sum += row.avg_r * row.n;
    }
  }
  return { r: n >= MIN_SAMPLE ? sum / n : null, n };
}

function Cell({ row, metric }: { row: EvidenceRow | undefined; metric: (typeof METRICS)[number] }) {
  if (!row) return <span className="text-2xs text-fg-3">—</span>;
  const v = row[metric.id];
  const insufficient = row.insufficient_sample || row.n < MIN_SAMPLE;
  return (
    <span className="inline-flex flex-col items-end leading-tight" data-bucket={row.bucket}>
      {insufficient ? (
        <span className="text-2xs italic text-fg-3">{row.label ?? 'insufficient sample'}</span>
      ) : (
        <span className={cn('num text-sm', !isNum(v) ? 'text-fg-3' : metric.signed ? (v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-fg') : 'text-fg')}>
          {isNum(v) ? metric.fmt(v) : '—'}
        </span>
      )}
      <SampleN n={row.n} />
    </span>
  );
}

function Separation({ rows }: { rows: readonly EvidenceRow[] }) {
  const good = pooledAvgR(rows, ['Favourable', 'Constructive']);
  const bad = pooledAvgR(rows, ['Weak', 'Danger']);
  if (good.r === null || bad.r === null) {
    return (
      <span className="inline-flex flex-col items-end leading-tight">
        <span className="text-2xs italic text-fg-3">insufficient sample</span>
        <span className="num text-2xs text-fg-3">
          n={good.n}/{bad.n}
        </span>
      </span>
    );
  }
  const d = good.r - bad.r;
  return (
    <span className="inline-flex flex-col items-end leading-tight" title="Avg R in Favourable+Constructive minus Weak+Danger (n-weighted)">
      <span className={cn('num text-sm', d > 0.3 ? 'text-up' : d < 0 ? 'text-down' : 'text-warn')}>{fmtSigned(d, 2)}R</span>
      <span className="num text-2xs text-fg-3">
        n={good.n}/{bad.n}
      </span>
    </span>
  );
}

type EvQ = UseQueryResult<Envelope<EvidenceRow>>;

function SetupRow({ label, q, buckets, metric, by }: { label: string; q: EvQ; buckets: string[]; metric: (typeof METRICS)[number]; by: By }) {
  const rows = q.data?.rows ?? [];
  const pending = q.isError || isUnavailable(q.data);
  return (
    <tr className="h-11 border-t border-line">
      <th scope="row" className="px-3 text-left text-xs font-medium text-fg">
        {label}
      </th>
      {q.isPending ? (
        <td colSpan={buckets.length + (by === 'environment' ? 1 : 0)} className="px-3">
          <Skeleton height={14} />
        </td>
      ) : pending ? (
        <td colSpan={buckets.length + (by === 'environment' ? 1 : 0)} className="px-3 text-2xs text-fg-3">
          Evidence pending — {q.data?.meta.reason ?? 'not available yet'}
        </td>
      ) : (
        <>
          {buckets.map((b) => (
            <td key={b} className="px-3 text-right">
              <Cell row={findBucket(rows, b)} metric={metric} />
            </td>
          ))}
          {by === 'environment' && (
            <td className="px-3 text-right">
              <Separation rows={rows} />
            </td>
          )}
        </>
      )}
    </tr>
  );
}

function StockAnalogs() {
  const shell = useShell();
  const [typed, setTyped] = useState('');
  const sym = (typed.trim().toUpperCase() || shell.symbol || '').toUpperCase();
  const valid = isSymbol(sym);
  const q = useResearchQuery('stock/{sym}/analogs', { params: { sym } }, { enabled: valid });
  const cols = useMemo<DataTableColumn<StockAnalogRow>[]>(
    () => [
      { id: 'trade_date', header: 'Setup date', accessor: 'trade_date', format: 'date', width: 96 },
      { id: 'symbol', header: 'Symbol', accessor: 'symbol', width: 104, cell: (v) => <span className="font-mono text-fg">{String(v)}</span> },
      { id: 'queue', header: 'Queue', accessor: 'queue', width: 96 },
      { id: 'distance', header: 'Distance', accessor: 'distance', format: 'num', width: 76, metricKey: 'analog_distance', sortDescFirst: false },
      {
        id: 'r',
        header: 'R',
        accessor: 'r_multiple',
        format: 'signed',
        width: 64,
        metricKey: 'avg_r',
        cell: (v) => <span className={cn('num', (v as number) > 0 ? 'text-up' : (v as number) < 0 ? 'text-down' : 'text-fg')}>{fmtSigned(v as number, 1)}R</span>,
      },
      { id: 'hit', header: '+2R', accessor: (r) => (r.hit_2r == null ? null : r.hit_2r ? 1 : 0), width: 56, metricKey: 'hit_rate_2r', cell: (v) => (v ? <Chip tone="positive">yes</Chip> : <Chip>no</Chip>) },
      { id: 'days', header: 'Days', accessor: 'days_held', format: 'int', width: 56 },
    ],
    [],
  );
  return (
    <Panel
      title="Stock analogs"
      subtitle="Nearest past setups of the same queue (base depth, strength, RVOL, group quadrant, environment) and how they ended"
      bodyClassName="flex min-h-[300px] flex-col"
      actions={
        <input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={shell.symbol ?? 'Symbol'}
          aria-label="Symbol for stock analogs"
          className="w-28 rounded border border-line bg-surface-2 px-2 py-0.5 font-mono text-xs uppercase text-fg placeholder:text-fg-3"
        />
      }
    >
      {!valid ? (
        <div className="p-6 text-center text-xs text-fg-3">Select a stock (J/K in any list, or type a symbol) to see its nearest past setups.</div>
      ) : (
        <QueryState q={q} compact what={`The nearest past setups to ${sym}'s current setup in the same queue, with each one's R-multiple, whether it hit +2R before the stop, and days held.`}>
          {(env) => {
            const rs = env.rows.map((r) => r.r_multiple);
            const n = rs.filter(isNum).length;
            const hits = env.rows.filter((r) => r.hit_2r === true).length;
            const withHit = env.rows.filter((r) => r.hit_2r != null).length;
            return (
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="flex flex-wrap items-center gap-4 border-b border-line px-3 py-2 text-xs">
                  <span className="font-mono font-medium text-fg">{sym}</span>
                  <span className="text-fg-3">
                    <Term k="median_r">Median R</Term>{' '}
                    <Stat value={median(rs)} n={n} enforceMin={false} format={(v) => `${fmtSigned(v, 2)}R`} />
                  </span>
                  <span className="text-fg-3">
                    <Term k="hit_rate_2r">Hit +2R</Term>{' '}
                    <span className="num text-fg">
                      {hits} of {withHit}
                    </span>
                  </span>
                  <span className="text-2xs text-fg-3">Nearest neighbours: read the spread, not the average.</span>
                </div>
                <DataTable
                  label={`Stock analogs for ${sym}`}
                  columns={cols}
                  rows={env.rows}
                  total={env.total}
                  getRowId={(r, i) => `${r.symbol}-${r.trade_date}-${i}`}
                  initialSort={[{ id: 'distance', desc: false }]}
                  emptyState={<div className="p-6 text-center text-xs text-fg-3">{sym} is not in a queue today, so it has no setup analogs.</div>}
                  className="flex-1"
                />
              </div>
            );
          }}
        </QueryState>
      )}
    </Panel>
  );
}

function PresetRows({ buckets, metric, by }: { buckets: string[]; metric: (typeof METRICS)[number]; by: By }) {
  const presets = useApiQuery('screener/presets');
  const list = (presets.data?.rows ?? []).filter((p) => p.kind !== 'queue');
  if (presets.isPending) return null;
  if (!list.length) {
    return (
      <tr>
        <td colSpan={buckets.length + 2} className="px-3 py-2 text-2xs text-fg-3">
          Screener presets unavailable.
        </td>
      </tr>
    );
  }
  return (
    <>
      {list.map((p) => (
        <PresetRow key={p.id} id={p.id} label={p.label} buckets={buckets} metric={metric} by={by} />
      ))}
    </>
  );
}

function PresetRow({ id, label, buckets, metric, by }: { id: string; label: string; buckets: string[]; metric: (typeof METRICS)[number]; by: By }) {
  const q = useResearchQuery('evidence/{setup}', { params: { setup: id }, query: { by } });
  return <SetupRow label={label} q={q as EvQ} buckets={buckets} metric={metric} by={by} />;
}

export function EvidenceView() {
  const [byRaw, setBy] = useUrlParam('rby');
  const [metricRaw, setMetric] = useUrlParam('rmetric');
  const [presetsOn, setPresetsOn] = useState(false);
  const fx = useFixtureMode();
  const by: By = BY_OPTIONS.some((o) => o.id === byRaw) ? (byRaw as By) : 'environment';
  const metric = METRICS.find((m) => m.id === metricRaw) ?? METRICS[0];

  const q0 = useResearchQuery('evidence/{setup}', { params: { setup: QUEUES[0].id }, query: { by } });
  const q1 = useResearchQuery('evidence/{setup}', { params: { setup: QUEUES[1].id }, query: { by } });
  const q2 = useResearchQuery('evidence/{setup}', { params: { setup: QUEUES[2].id }, query: { by } });
  const qs = [q0, q1, q2] as EvQ[];
  const buckets = bucketsFor(
    by,
    qs.map((q) => q.data?.rows ?? []),
  );
  const allPending = qs.every((q) => !q.isPending && (q.isError || isUnavailable(q.data)));
  const minSample = (q0.data?.meta.context as Record<string, unknown> | undefined)?.min_sample;

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-3 overflow-auto p-3 xl:grid-cols-[minmax(0,7fr)_minmax(0,4fr)]">
      <Panel
        title="Setup evidence"
        subtitle={
          <>
            Outcomes of every past signal, resolved on or before the as-of date (no look-ahead) · n &lt; {typeof minSample === 'number' ? minSample : MIN_SAMPLE} ⇒
            insufficient sample
          </>
        }
        actions={
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1 text-2xs text-fg-3">
              Split by
              <select value={by} onChange={(e) => setBy(e.target.value === 'environment' ? null : e.target.value)} className="rounded border border-line bg-surface-2 px-1 py-0.5 text-2xs text-fg">
                {BY_OPTIONS.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        }
      >
        {allPending ? (
          <EvidencePending
            meta={q0.data?.meta}
            what="For each queue (Darvas Squeeze, Darvas 10 EMA, VCP) and each market environment state: how often signals hit +2R before the stop, average and median R, and typical drawdown — with the sample size on every number."
          />
        ) : (
          <div className="space-y-2 p-3">
            <div className="flex flex-wrap items-center gap-1" role="radiogroup" aria-label="Statistic">
              {METRICS.map((m) => (
                <Chip key={m.id} onClick={() => setMetric(m.id === 'hit_rate_2r' ? null : m.id)} selected={m.id === metric.id} tone={m.id === metric.id ? 'accent' : 'neutral'}>
                  {m.label}
                </Chip>
              ))}
              <Term k={metric.id} className="ml-2 text-2xs text-fg-3">
                about {metric.label}
              </Term>
            </div>
            <div className="overflow-x-auto rounded border border-line">
              <table className="w-full text-table" aria-label={`Setup evidence by ${by}`}>
                <thead className="bg-surface-2 text-2xs uppercase tracking-wide text-fg-3">
                  <tr>
                    <th className="px-3 py-1.5 text-left font-medium">Setup</th>
                    {buckets.map((b) => {
                      const v = asVerdictWord(b);
                      return (
                        <th key={b} className={cn('px-3 py-1.5 text-right font-medium', v && VERDICT_TEXT[v])}>
                          {b === 'all' ? 'All' : b}
                        </th>
                      );
                    })}
                    {by === 'environment' && (
                      <th className="px-3 py-1.5 text-right font-medium" title="Does the verdict separate outcomes? Avg R in Favourable+Constructive minus Weak+Danger">
                        Separation
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {QUEUES.map((s, i) => (
                    <SetupRow key={s.id} label={s.label} q={qs[i]} buckets={buckets} metric={metric} by={by} />
                  ))}
                  {presetsOn && <PresetRows buckets={buckets} metric={metric} by={by} />}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-2xs text-fg-3">
              <button type="button" onClick={() => setPresetsOn((v) => !v)} className="rounded border border-line px-2 py-0.5 text-fg-2 hover:bg-surface-3" aria-pressed={presetsOn}>
                {presetsOn ? 'Hide' : 'Show'} screener presets
              </button>
              <span>
                Horizon 20 sessions; trigger fill next session; <Term k="sample_n">n</Term> printed on every cell. Separation is the ship gate of spec 6.1.5 (verdict must
                separate outcomes).
              </span>
              {fx.on && <Chip tone="violet">fixture data</Chip>}
            </div>
            <div className="text-2xs text-fg-3">
              Reading: <span className="num">{fmtNum(0.5, 1)}R</span> average means half the initial risk gained per trade on average; use with the hit rate and n.
              Latest resolved outcome ≤ {fmtDate(q0.data?.as_of ?? null)}.
            </div>
          </div>
        )}
      </Panel>
      <StockAnalogs />
    </div>
  );
}
