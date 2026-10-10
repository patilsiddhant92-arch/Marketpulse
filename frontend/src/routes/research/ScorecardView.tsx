/**
 * Setup scorecard (10-tab-research.md §12): for each screener preset, how many
 * of the year's big movers it caught, how near the low it fired, how much room
 * was left, and — always beside it — its precision and false alarms on every
 * fresh fire. Catch rate alone flatters a preset that fires on everything.
 */
import { cn } from '../../lib/cn';
import { fmtDate, fmtInt, fmtNum, fmtPct, fmtSignedPct, isNum } from '../../lib/fmt';
import { Chip } from '../../ui/Chip';
import { useResearchQuery } from './data';
import { caveatOf, context, type ScorecardContext, type ScorecardRow } from './lab';
import { Caveat, SimpleTable, Summary } from './LabParts';
import { Panel, QueryState, SampleN } from './parts';

export function ScorecardView() {
  const q = useResearchQuery('research/scorecard');
  return (
    <QueryState q={q} what="Each screener preset's catch rate on the year's big movers, how early it fired, and its precision and false alarms.">
      {(env) => {
        const c = context<ScorecardContext>(env.meta);
        const base = c.precision?.base_hit_pct ?? null;
        const rows = env.rows as ScorecardRow[];
        return (
          <div className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
            <Caveat text={caveatOf(env.meta)} />
            <Summary lines={c.summary} />
            <Panel
              title="Setup scorecard"
              subtitle={`${fmtInt(c.movers)} big movers (≥ ₹1,000 Cr, low → peak ≥ +100%) · ${fmtDate(c.window_from ?? null)} – ${fmtDate(c.window_to ?? null)} · precision on fresh fires to ${fmtDate(c.precision?.window_to ?? null)}, base rate ${fmtPct(base, 1)}`}
            >
              <SimpleTable<ScorecardRow>
                label="Setup scorecard"
                rows={rows}
                rowKey={(r) => r.preset_id}
                columns={[
                  {
                    id: 'p',
                    header: 'Preset',
                    cell: (r) => (
                      <span className="inline-flex items-center gap-1" title={r.description ?? undefined}>
                        <span className="font-mono text-violet">{r.letter}</span> {r.preset}
                        {r.early && <Chip tone="violet">early</Chip>}
                      </span>
                    ),
                  },
                  { id: 'cat', header: 'Kind', cell: (r) => <span className="text-fg-3">{r.category ?? '—'}</span> },
                  {
                    id: 'caught',
                    header: 'Movers caught',
                    align: 'right',
                    cell: (r) => (
                      <span className="inline-flex items-baseline gap-1.5">
                        {fmtPct(r.caught_pct, 0)} <SampleN n={r.movers} />
                      </span>
                    ),
                  },
                  { id: 'low', header: 'Entry above low', align: 'right', cell: (r) => (isNum(r.entry_vs_low_pct) ? `+${fmtNum(r.entry_vs_low_pct, 0)}%` : '—') },
                  { id: 'room', header: 'Room to peak', align: 'right', cell: (r) => (isNum(r.to_peak_pct) ? `+${fmtNum(r.to_peak_pct, 0)}%` : '—') },
                  { id: 't20', header: '20 EMA exit', align: 'right', cell: (r) => fmtSignedPct(r.trail20_pct, 1) },
                  {
                    id: 'hit',
                    header: 'Hit +50%',
                    align: 'right',
                    title: 'Share of all fresh fires followed by a close ≥ +50% within 120 sessions',
                    cell: (r) => (
                      <span className="inline-flex items-baseline gap-1.5">
                        {fmtPct(r.hit_pct, 1)} <SampleN n={r.fires} label="fires" />
                      </span>
                    ),
                  },
                  { id: 'fa', header: 'False alarms', align: 'right', cell: (r) => <span className="text-down">{fmtPct(r.false_alarm_pct, 1)}</span> },
                  {
                    id: 'lift',
                    header: 'vs base',
                    align: 'right',
                    cell: (r) => <span className={cn(isNum(r.lift) && r.lift >= 1.3 ? 'text-up' : '')}>{isNum(r.lift) ? `${fmtNum(r.lift, 2)}×` : '—'}</span>,
                  },
                  {
                    id: 'rs',
                    header: 'Hit with RS ≥ 80',
                    align: 'right',
                    cell: (r) => (
                      <span className="inline-flex items-baseline gap-1.5">
                        {fmtPct(r.hit_rs80_pct, 1)} <SampleN n={r.fires_rs80} label="fires" />
                      </span>
                    ),
                  },
                ]}
              />
              <p className="px-3 py-1.5 text-2xs text-fg-3">
                {c.definition} 20 EMA ladder across all movers: median {fmtSignedPct(c.ladder?.median_pct ?? null, 0)} vs a median move of{' '}
                {fmtSignedPct(c.ladder?.median_move_pct ?? null, 0)} ({fmtNum(c.ladder?.median_trades ?? null, 0)} trades). Presets use the exact rules of the
                screener. The VCP flag is the indicator flag, not the Desk VCP queue.
              </p>
            </Panel>
          </div>
        );
      }}
    </QueryState>
  );
}
