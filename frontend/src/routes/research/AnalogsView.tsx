/**
 * Market analogs (spec 7.6, 5): "when did the market last look like today,
 * and what happened next". 10 nearest past dates (k-NN, most recent 60
 * sessions excluded), forward MidSml400 5/20/60 with spread and an agreement
 * warning when the analogs split.
 */
import { AlertTriangle, History } from 'lucide-react';
import { useMemo } from 'react';
import type { MarketAnalogRow } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtDateWithDay, fmtNum, fmtPct, fmtSignedPct, isNum } from '../../lib/fmt';
import { TONE_TEXT, useMetric } from '../../metrics/dictionary';
import { VERDICT_TEXT } from '../../shell/environment';
import { useAsOf } from '../../shell/urlState';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { Spark } from '../../ui/Spark';
import { useResearchQuery } from './data';
import { ANALOG_HORIZONS, analogPath, asVerdictWord, median, summarizeAnalogs, type AnalogSummary } from './model';
import { Legend, Panel, PathChart, QueryState, SampleN, Term, type PathSeries } from './parts';

const EMPTY: MarketAnalogRow[] = [];

function Distance({ v }: { v: number }) {
  const { toneFor } = useMetric('analog_distance');
  const t = toneFor(v);
  return <span className={cn('num', t ? TONE_TEXT[t] : 'text-fg')}>{fmtNum(v, 2)}</span>;
}

function useColumns(onGoTo: (d: string) => void): DataTableColumn<MarketAnalogRow>[] {
  return useMemo(
    () => [
      {
        id: 'analog_date',
        header: 'Past date',
        accessor: 'analog_date',
        width: 150,
        cell: (v) => <span className="num">{fmtDateWithDay(String(v))}</span>,
      },
      { id: 'distance', header: 'Distance', accessor: 'distance', format: 'num', metricKey: 'analog_distance', width: 80, sortDescFirst: false, cell: (v) => <Distance v={v as number} /> },
      {
        id: 'verdict_then',
        header: 'Verdict then',
        accessor: 'verdict_then',
        width: 110,
        metricKey: 'environment_verdict',
        cell: (v) => {
          const w = asVerdictWord(v);
          return <span className={w ? VERDICT_TEXT[w] : 'text-fg-2'}>{String(v)}</span>;
        },
      },
      { id: 'fwd5', header: 'Next 5', accessor: 'fwd_midsml400_5d_pct', format: 'signedPct', width: 76, headerTitle: 'MidSml400 return over the next 5 sessions', cell: (v) => <Signed v={v as number} /> },
      { id: 'fwd20', header: 'Next 20', accessor: 'fwd_midsml400_20d_pct', format: 'signedPct', width: 76, metricKey: 'forward_return_20d', cell: (v) => <Signed v={v as number} /> },
      { id: 'fwd60', header: 'Next 60', accessor: 'fwd_midsml400_60d_pct', format: 'signedPct', width: 76, headerTitle: 'MidSml400 return over the next 60 sessions', cell: (v) => <Signed v={v as number} /> },
      {
        id: 'path',
        header: 'Path 0→60',
        accessor: (r) => r.fwd_midsml400_60d_pct,
        width: 90,
        sortable: false,
        renderNull: true,
        cell: (_v, r) => <Spark values={analogPath(r)} baseline={0} label={`MidSml400 path after ${r.analog_date ?? 'analog'}: 0, 5, 20, 60 sessions`} />,
      },
      {
        id: 'ft',
        header: 'Follow-through',
        accessor: 'next_month_follow_through_pct',
        format: 'pct',
        width: 104,
        metricKey: 'follow_through_pct',
      },
      {
        id: 'go',
        header: '',
        accessor: 'analog_date',
        width: 64,
        sortable: false,
        cell: (v) => (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onGoTo(String(v));
            }}
            title="Time travel: open the whole app as of this past date"
            className="inline-flex items-center gap-1 rounded border border-line px-1.5 text-2xs text-fg-2 hover:bg-surface-3"
          >
            <History className="h-3 w-3" aria-hidden /> Go
          </button>
        ),
      },
    ],
    [onGoTo],
  );
}

function Signed({ v }: { v: number }) {
  return <span className={cn('num', v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-fg-2')}>{fmtSignedPct(v)}</span>;
}

function SummaryStrip({ s }: { s: AnalogSummary }) {
  return (
    <div className="grid grid-cols-3 gap-2 p-3">
      {s.horizons.map((h) => (
        <div key={h.horizon} className="rounded border border-line bg-surface-2 px-3 py-2" data-horizon={h.horizon}>
          <div className="text-2xs uppercase tracking-wide text-fg-3">
            {h.horizon === 20 ? <Term k="forward_return_20d">Next 20 sessions</Term> : `Next ${h.horizon} sessions`} · median
          </div>
          <div className="flex items-baseline gap-2">
            <span className={cn('num text-xl font-medium', isNum(h.median) ? (h.median > 0 ? 'text-up' : h.median < 0 ? 'text-down' : 'text-fg') : 'text-fg-3')}>
              {fmtSignedPct(h.median)}
            </span>
            <SampleN n={h.n} />
          </div>
          <div className="num text-2xs text-fg-3">
            range {fmtSignedPct(h.min)} … {fmtSignedPct(h.max)} · {h.up} up / {h.down} down
          </div>
        </div>
      ))}
    </div>
  );
}

function Agreement({ s }: { s: AnalogSummary }) {
  const a = s.agreement20;
  if (a.share === null) return null;
  const pct = fmtPct(a.share * 100, 0);
  if (s.disagree) {
    return (
      <div role="note" className="mx-3 flex items-start gap-2 rounded border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>
          Analogs disagree: only {pct} point {a.direction} over 20 sessions (<span className="num">n={a.n}</span>). The spread is the message — no
          clear edge from history.
        </span>
      </div>
    );
  }
  return (
    <div role="note" className="mx-3 rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg-2">
      {pct} of analogs were {a.direction === 'up' ? 'higher' : 'lower'} 20 sessions later (<span className="num">n={a.n}</span>). Median{' '}
      <Term k="analog_distance">distance</Term> <span className="num">{fmtNum(s.medianDistance, 2)}</span>.
    </div>
  );
}

function Fan({ rows }: { rows: readonly MarketAnalogRow[] }) {
  const { series, band } = useMemo(() => {
    const paths = rows.map((r) => ({ r, pts: analogPath(r) }));
    const series: PathSeries[] = paths.map(({ r, pts }, i) => ({
      id: `a${i}`,
      label: `${r.analog_date ?? '—'}: ${pts.map((p) => fmtSignedPct(p)).join(' → ')}`,
      points: ANALOG_HORIZONS.map((x, j) => ({ x, y: pts[j] })),
      tone: 'muted',
      opacity: 0.55,
    }));
    const band = ANALOG_HORIZONS.map((x, j) => {
      const ys = paths.map((p) => p.pts[j]).filter(isNum);
      return { x, lo: ys.length ? Math.min(...ys) : 0, hi: ys.length ? Math.max(...ys) : 0 };
    });
    const med = ANALOG_HORIZONS.map((x, j) => ({ x, y: median(paths.map((p) => p.pts[j])) }));
    series.push({ id: 'median', label: 'Median of analogs', points: med, tone: 'accent', strokeWidth: 2.25 });
    return { series, band };
  }, [rows]);
  return (
    <div className="space-y-1 px-3 pb-3">
      <PathChart
        label="Forward MidSml400 return fan across the nearest analogs"
        series={series}
        band={band}
        xTicks={ANALOG_HORIZONS.map((x) => ({ x, label: x === 0 ? 'Then' : `+${x}` }))}
        yFormat={(v) => fmtSignedPct(v, 0)}
        height={210}
      />
      <Legend
        items={[
          { label: 'Median', tone: 'accent' },
          { label: `Each analog (n=${rows.length})`, tone: 'muted' },
          { label: 'Shaded: min–max range', tone: 'neutral' },
        ]}
      />
    </div>
  );
}

export function AnalogsView() {
  const q = useResearchQuery('research/analogs');
  const [, setAsOf] = useAsOf();
  const columns = useColumns(setAsOf);
  return (
    <QueryState
      q={q}
      what="The 10 past dates whose market environment (trend, participation, leadership, follow-through, stress) was closest to today, and what the MidSmallcap 400 did 5, 20 and 60 sessions later."
    >
      {(env) => {
        const rows = env.rows.length ? env.rows : EMPTY;
        const s = summarizeAnalogs(rows);
        return (
          <div className="grid h-full min-h-0 grid-cols-1 gap-3 overflow-auto p-3 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
            <Panel
              title="What happened next"
              subtitle={
                <>
                  {s.k} nearest past dates to {fmtDateWithDay(env.as_of)} · most recent 60 sessions excluded
                </>
              }
            >
              <SummaryStrip s={s} />
              <Agreement s={s} />
              <div className="pt-3">
                <Fan rows={rows} />
              </div>
            </Panel>
            <Panel title="Nearest analogs" subtitle="Lower distance = closer match. Go = time-travel the app to that date." bodyClassName="flex min-h-[360px] flex-col">
              <DataTable
                label="Market analogs"
                columns={columns}
                rows={rows}
                total={env.total}
                getRowId={(r, i) => r.analog_date ?? String(i)}
                initialSort={[{ id: 'distance', desc: false }]}
                emptyState={<div className="p-6 text-center text-xs text-fg-3">No analogs for this date.</div>}
                className="flex-1"
              />
            </Panel>
          </div>
        );
      }}
    </QueryState>
  );
}
