/**
 * Days like today (10-tab-research.md §§3, 4, 11): the two-axis regime quadrant
 * (index range/trend × breakouts paying/failing) with its ribbon over the
 * archive, the quadrant record, how past phases lasted and ended, and the 10
 * nearest past sessions with what the equal-weight market did next vs all days.
 */
import { useMemo } from 'react';
import { cn } from '../../lib/cn';
import { fmtDate, fmtInt, fmtNum, fmtPct, fmtSignedPct, isNum } from '../../lib/fmt';
import { useAsOf } from '../../shell/urlState';
import { GlanceBand } from '../../ui/GlanceBand';
import { KpiTile } from '../../ui/KpiTile';
import { useResearchQuery } from './data';
import {
  QUADRANT_LABEL,
  QUADRANT_ORDER,
  QUADRANT_TONE,
  analogEdge,
  caveatOf,
  context,
  dateTicks,
  isQuadrant,
  ribbonRuns,
  type AnalogContext,
  type AnalogDayRow,
  type AnalogHorizon,
  type Episode,
  type QuadrantRecord,
  type RegimeContext,
  type RegimeDayRow,
} from './lab';
import { Caveat, Muted, QuadrantChip, SimpleTable, Summary } from './LabParts';
import { PathChart, Panel, QueryState, SampleN } from './parts';
import { DataGapBanner } from '../../ui/DataGap';

const pctile = (v: number | null | undefined) => (isNum(v) ? `${Math.round(v * 100)}th pct` : '—');

/** Quadrant ribbon: one coloured cell per session, aligned with the EW chart above it. */
export function QuadrantRibbon({ rows }: { rows: readonly RegimeDayRow[] }) {
  const runs = useMemo(() => ribbonRuns(rows), [rows]);
  const n = rows.length || 1;
  const left = 44;
  const W = 640;
  const w = (W - left - 8) / n;
  return (
    <svg viewBox={`0 0 ${W} 14`} className="block w-full" role="img" aria-label="Regime quadrant ribbon" style={{ maxHeight: 14 }}>
      {runs.map((r) => (
        <rect
          key={r.from}
          x={left + r.from * w}
          y={1}
          width={Math.max(0.5, (r.to - r.from + 1) * w)}
          height={12}
          className={r.q ? QUADRANT_TONE[r.q].fill : 'fill-surface-3'}
          fillOpacity={r.q ? 0.75 : 1}
        >
          <title>
            {r.q ? QUADRANT_LABEL[r.q] : 'Not classified yet'}: {fmtDate(rows[r.from]?.trade_date ?? null)} – {fmtDate(rows[r.to]?.trade_date ?? null)}
          </title>
        </rect>
      ))}
    </svg>
  );
}

function RibbonLegend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-2xs text-fg-3">
      {QUADRANT_ORDER.map((k) => (
        <span key={k} className="inline-flex items-center gap-1">
          <svg width={12} height={8} aria-hidden>
            <rect width={12} height={8} className={QUADRANT_TONE[k].fill} fillOpacity={0.75} />
          </svg>
          {QUADRANT_LABEL[k]}
        </span>
      ))}
    </div>
  );
}

function RecordTable({ record, current }: { record: QuadrantRecord[]; current: string | null }) {
  return (
    <SimpleTable
      label="Quadrant record"
      rows={record}
      rowKey={(r) => r.quadrant}
      rowClassName={(r) => (r.quadrant === current ? 'bg-accent/10' : r.quadrant === 'all' ? 'text-fg-3' : undefined)}
      columns={[
        { id: 'q', header: 'Quadrant', cell: (r) => (r.quadrant === 'all' ? 'All days' : <QuadrantChip q={r.quadrant} label={r.label} />) },
        { id: 'axes', header: 'Reading', cell: (r) => <Muted>{r.axes ?? '—'}</Muted> },
        { id: 'days', header: 'Days', align: 'right', cell: (r) => fmtInt(r.days) },
        {
          id: 'ft',
          header: 'Next breakouts held',
          align: 'right',
          title: 'Share of the next 10 sessions’ breakouts still above their breakout close 5 sessions later',
          cell: (r) => (
            <span className="inline-flex items-baseline gap-1.5">
              {fmtPct(r.next10_ft_pct, 1)} <SampleN n={r.days_graded} />
            </span>
          ),
        },
        { id: 'f20', header: 'EW next 20', align: 'right', cell: (r) => fmtSignedPct(r.ew_fwd20_pct, 1) },
        { id: 'up', header: 'EW up 20', align: 'right', cell: (r) => fmtPct(r.ew_fwd20_up_pct, 0) },
        { id: 'adv', header: 'What to do', cell: (r) => <Muted>{r.advice ?? ''}</Muted> },
      ]}
    />
  );
}

function EpisodesTable({ episodes }: { episodes: Episode[] }) {
  return (
    <SimpleTable
      label="Past regime phases"
      rows={episodes}
      rowKey={(e) => `${e.start}-${e.quadrant}`}
      rowClassName={(e) => (e.open ? 'bg-accent/10' : undefined)}
      columns={[
        { id: 'q', header: 'Phase', cell: (e) => <QuadrantChip q={e.quadrant} /> },
        { id: 'from', header: 'From', cell: (e) => fmtDate(e.start) },
        { id: 'to', header: 'To', cell: (e) => (e.open ? 'now' : fmtDate(e.end)) },
        { id: 'n', header: 'Sessions', align: 'right', cell: (e) => fmtInt(e.sessions) },
        { id: 'mv', header: 'EW move', align: 'right', cell: (e) => fmtSignedPct(e.ew_move_pct, 1) },
        { id: 'next', header: 'Ended in', cell: (e) => (e.open ? <Muted>open</Muted> : <QuadrantChip q={e.next_quadrant} />) },
        { id: 'after', header: 'EW next 20', align: 'right', cell: (e) => fmtSignedPct(e.ew_next20_pct, 1) },
      ]}
    />
  );
}

function HorizonTable({ horizons }: { horizons: AnalogHorizon[] }) {
  return (
    <SimpleTable
      label="What happened next"
      rows={horizons}
      rowKey={(h) => String(h.horizon)}
      columns={[
        { id: 'h', header: 'Sessions later', cell: (h) => `+${h.horizon}` },
        {
          id: 'med',
          header: 'Analogs median',
          align: 'right',
          cell: (h) => (
            <span className="inline-flex items-baseline gap-1.5" data-horizon={h.horizon}>
              {fmtSignedPct(h.median, 1)} <SampleN n={h.n} />
            </span>
          ),
        },
        { id: 'range', header: 'Range', align: 'right', cell: (h) => `${fmtSignedPct(h.min, 1)} … ${fmtSignedPct(h.max, 1)}` },
        { id: 'up', header: 'Analogs up', align: 'right', cell: (h) => fmtPct(h.up_pct, 0) },
        {
          id: 'base',
          header: 'All days median',
          align: 'right',
          cell: (h) => (
            <span className="inline-flex items-baseline gap-1.5">
              {fmtSignedPct(h.base_median, 1)} <SampleN n={h.base_n} />
            </span>
          ),
        },
        { id: 'bup', header: 'All days up', align: 'right', cell: (h) => fmtPct(h.base_up_pct, 0) },
        {
          id: 'edge',
          header: 'Edge',
          align: 'right',
          cell: (h) => {
            const e = analogEdge(h);
            return <span className={cn(isNum(e) && (e > 0 ? 'text-up' : e < 0 ? 'text-down' : ''))}>{isNum(e) ? `${e > 0 ? '+' : ''}${fmtNum(e, 1)} pts` : '—'}</span>;
          },
        },
      ]}
    />
  );
}

function AnalogTable({ rows, onGo }: { rows: AnalogDayRow[]; onGo: (d: string) => void }) {
  return (
    <SimpleTable
      label="Days like today"
      rows={rows}
      rowKey={(r) => r.analog_date ?? ''}
      columns={[
        { id: 'd', header: 'Date', cell: (r) => <span className="font-mono">{fmtDate(r.analog_date ?? null)}</span> },
        { id: 'dist', header: 'Distance', align: 'right', cell: (r) => fmtNum(r.distance, 2) },
        { id: 'q', header: 'Regime then', cell: (r) => <QuadrantChip q={r.quadrant} /> },
        { id: 'f5', header: '+5', align: 'right', cell: (r) => fmtSignedPct(r.fwd5_pct, 1) },
        { id: 'f20', header: '+20', align: 'right', cell: (r) => fmtSignedPct(r.fwd20_pct, 1) },
        { id: 'f60', header: '+60', align: 'right', cell: (r) => fmtSignedPct(r.fwd60_pct, 1) },
        { id: 'ft', header: 'Next breakouts held', align: 'right', cell: (r) => fmtPct(r.next10_ft_pct, 0) },
        {
          id: 'go',
          header: '',
          cell: (r) =>
            r.analog_date ? (
              <button
                type="button"
                onClick={() => onGo(r.analog_date!)}
                className="rounded border border-line px-1.5 py-0.5 text-2xs text-fg-2 hover:bg-surface-3"
                title="Open the app as of this date"
              >
                Go
              </button>
            ) : null,
        },
      ]}
    />
  );
}

export function DaysLikeTodayView() {
  const reg = useResearchQuery('research/regime', { query: { limit: 5000 } });
  const ana = useResearchQuery('research/days-like-today');
  const [, setAsOf] = useAsOf();
  return (
    <QueryState q={reg} what="The two-axis regime quadrant (index range vs trend × breakouts paying vs failing) for every session, and the past days most like today.">
      {(env) => {
        const c = context<RegimeContext>(env.meta);
        const t = c.today;
        const rows = env.rows as RegimeDayRow[];
        const dates = rows.map((r) => r.trade_date ?? '');
        const q = isQuadrant(t?.quadrant) ? t!.quadrant : null;
        const recCur = c.record?.find((r) => r.quadrant === q);
        const recAll = c.record?.find((r) => r.quadrant === 'all');
        const actx = context<AnalogContext>(ana.data?.meta);
        return (
          <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
            <Caveat text={caveatOf(env.meta)} />
            {c.dropped_sessions && c.dropped_sessions.length > 0 && (
              <DataGapBanner role="note" compact>
                Studies end on {fmtDate(c.study_end ?? null)}. {c.dropped_sessions.length} later session(s) sit after a data gap and are not studied.
              </DataGapBanner>
            )}
            <GlanceBand label="Market now">
              <KpiTile
                hero
                tone={q === 'press' ? 'up' : q === 'chop' ? 'down' : q === 'picker' ? 'warn' : 'info'}
                label="Regime quadrant"
                value={t?.label ?? '—'}
                caption={`${t?.index_axis ?? '—'} · breakouts ${t?.breakout_axis?.toLowerCase() ?? '—'} · ${t?.sessions_in_phase ?? '—'} sessions in phase`}
                hint={t?.advice ?? undefined}
                className="!min-w-[240px] !flex-[1.4]"
              />
              <KpiTile label="Choppiness (14)" value={fmtNum(t?.chop, 0)} caption={pctile(t?.chop_pctile)} hint="Above 61.8 is choppy, below 38.2 is trending. Read against its own history." />
              <KpiTile label="Efficiency ratio (20)" value={fmtNum(t?.er, 2)} caption={pctile(t?.er_pctile)} hint="Net move ÷ total path. Near 0 is chop, near 1 is a clean trend." />
              <KpiTile label="ADX (14)" value={fmtNum(t?.adx, 0)} caption="below 20 = no trend" />
              <KpiTile
                label="Breakouts holding"
                value={fmtPct(t?.ft_pct, 0)}
                caption={`${pctile(t?.ft_pctile)} · n=${fmtInt(t?.ft_n)}`}
                hint="Share of 50-day-high breakouts on ≥ 1.5× volume still above their breakout close 5 sessions later (trailing 10 sessions)."
              />
            </GlanceBand>
            <Summary lines={c.summary} />
            {recCur && recAll && (
              <p className="text-2xs text-fg-3">
                Record in this quadrant: next breakouts held {fmtPct(recCur.next10_ft_pct, 1)} vs {fmtPct(recAll.next10_ft_pct, 1)} on all days (n={fmtInt(recCur.days_graded)}).
              </p>
            )}
            <Panel
              title="Regime over the archive"
              subtitle={`Equal-weight market of stocks ≥ ₹1,000 Cr · ${fmtDate(c.sample?.from ?? null)} – ${fmtDate(c.sample?.to ?? null)} · ${fmtInt(c.sample?.classified)} sessions classified`}
              bodyClassName="p-2 space-y-1"
            >
              <PathChart
                label="Equal-weight market index"
                series={[{ id: 'ew', label: 'EW market', tone: 'accent', points: rows.map((r, i) => ({ x: i, y: r.ew_index ?? null })) }]}
                xTicks={dateTicks(dates, 6)}
                yFormat={(v) => fmtNum(v, 0)}
                zeroLine={false}
                height={180}
              />
              <QuadrantRibbon rows={rows} />
              <RibbonLegend />
              <p className="text-2xs text-fg-3">{c.definition}</p>
            </Panel>
            <div className="grid gap-3 xl:grid-cols-2">
              <Panel title="Quadrant record" subtitle="What breakouts and the EW market did after each kind of day">
                <RecordTable record={c.record ?? []} current={q} />
              </Panel>
              <Panel
                title="How past phases lasted and ended"
                subtitle={
                  c.duration
                    ? `${QUADRANT_LABEL[c.duration.quadrant] ?? ''} phases of 3+ sessions: median ${fmtNum(c.duration.median_sessions, 0)} (range ${fmtInt(c.duration.min_sessions)}–${fmtInt(c.duration.max_sessions)}, n=${fmtInt(c.duration.episodes_3plus)}) · this one: ${t?.sessions_in_phase ?? '—'}`
                    : undefined
                }
              >
                {c.duration?.exits?.length ? (
                  <div className="flex flex-wrap items-center gap-1.5 px-3 py-1.5 text-2xs text-fg-3">
                    Past phases ended in:
                    {c.duration.exits.map((e) => (
                      <span key={e.to} className="inline-flex items-center gap-1">
                        <QuadrantChip q={e.to} /> ×{e.n}
                      </span>
                    ))}
                  </div>
                ) : null}
                <EpisodesTable episodes={c.episodes ?? []} />
              </Panel>
            </div>
            <Panel title="Days like today" subtitle={actx.method}>
              <QueryState q={ana} what="The 10 past sessions nearest to today by breadth, regime and follow-through readings." compact>
                {(aenv) => (
                  <div className="space-y-2 p-2">
                    <Summary lines={actx.summary} />
                    <HorizonTable horizons={actx.horizons ?? []} />
                    <AnalogTable rows={aenv.rows as AnalogDayRow[]} onGo={(d) => setAsOf(d)} />
                    <p className="text-2xs text-fg-3">
                      Today:{' '}
                      {(actx.features ?? []).map((f) => `${f.label} ${fmtNum(f.today, f.key === 'er' ? 2 : 1)}`).join(' · ')}
                    </p>
                  </div>
                )}
              </QueryState>
            </Panel>
          </div>
        );
      }}
    </QueryState>
  );
}
