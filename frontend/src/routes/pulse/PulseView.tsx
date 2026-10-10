/**
 * Pulse (HarkPro/02-tab1-pulse.md, locked 2026-10-09). One vertical page:
 * hero (mood + What to do) → participation grid + expansion log → trend chart → internals →
 * money in the market (turnover, treemap, rotation) → groups → stocks that moved → days like today.
 *
 * Global controls: as-of = the shell's time-travel date (?as_of=); lookback and units live in the URL
 * while the tab is active (?lb=, ?units=).
 */
import { useAsOf } from '../../shell/urlState';
import { useShell } from '../../shell/ShellContext';
import { useTabUrlState } from '../../lib/tabUrlState';
import { Segmented } from '../../ui/Segmented';
import { ExpansionLog, BreadthGrid, TrendChart } from './Breadth';
import { useAnalogs, useBreadth, useExpansions, useFlow, useGroups, useInternals, useMovers, useSummary, type GroupLevel } from './data';
import { Hero } from './Hero';
import { Internals } from './Internals';
import { LOOKBACKS, longDate, parseLookback } from './model';
import { RotationBars, SectorTreemap, TurnoverPanel } from './Money';
import { DaysLikeToday, GroupsTable, MoversTable } from './Tables';
import type { MoverKind, Units } from './types';

const DEFAULTS = { lb: '5', units: 'pct', glevel: 'sector', movers: 'gainers' };
const UNITS = [
  { value: 'pct', label: '%', title: 'Breadth as percent of stocks' },
  { value: 'count', label: '# stocks', title: 'Breadth as a count of stocks' },
] as const;
const LEVELS: GroupLevel[] = ['sector', 'industry', 'sectoral', 'thematic'];
const KINDS: MoverKind[] = ['gainers', 'losers', 'turnover', 'delivered', 'rvol'];

export function PulseView({ tabPath = '/desk' }: { tabPath?: string }) {
  const [state, setState] = useTabUrlState(tabPath, DEFAULTS, 'pulse');
  const [urlAsOf] = useAsOf();
  const shell = useShell();
  const lookback = parseLookback(state.lb);
  const units: Units = state.units === 'count' ? 'count' : 'pct';
  const level: GroupLevel = LEVELS.includes(state.glevel as GroupLevel) ? (state.glevel as GroupLevel) : 'sector';
  const kind: MoverKind = KINDS.includes(state.movers as MoverKind) ? (state.movers as MoverKind) : 'gainers';

  const summary = useSummary(lookback);
  const breadth = useBreadth(lookback);
  const internals = useInternals(lookback);
  const expansions = useExpansions();
  const flow = useFlow(lookback);
  const groups = useGroups(level);
  const movers = useMovers(kind);
  const analogs = useAnalogs();
  const openHistory = () => shell.goTab('research');
  const asOf = summary.asOf ?? breadth.asOf;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pb-4" data-testid="pulse-view">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-fg-2" data-testid="pulse-asof">
          {asOf ? `As of ${longDate(asOf)} close` : 'Latest session'}
          {urlAsOf ? ' · replay' : ''}
        </span>
        <span className="ml-auto text-2xs text-fg-3">Compare today with</span>
        <Segmented label="Compare today with" size="xs" options={LOOKBACKS} value={`${lookback}` as (typeof LOOKBACKS)[number]['value']} onChange={(v) => setState({ lb: v })} />
        <Segmented label="Units" size="xs" options={UNITS} value={units} onChange={(v) => setState({ units: v })} />
      </div>

      <Hero q={summary} onOpenHistory={openHistory} />

      <div className="grid gap-2 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <BreadthGrid q={breadth} units={units} lookback={lookback} />
        <TrendChart q={breadth} lookback={lookback} />
      </div>
      <ExpansionLog q={expansions} />

      <Internals q={internals} lookback={lookback} />

      <div className="grid gap-2 xl:grid-cols-3">
        <TurnoverPanel q={flow} />
        <SectorTreemap q={flow} />
        <RotationBars q={flow} />
      </div>

      <GroupsTable q={groups} level={level} onLevel={(l) => setState({ glevel: l })} />
      <MoversTable q={movers} kind={kind} onKind={(k) => setState({ movers: k })} />
      <DaysLikeToday q={analogs} onOpen={openHistory} />

      <p className="px-1 text-2xs leading-snug text-fg-3">
        Mood score = average history-percentile of six readings (10/50/200 EMA participation, up-volume, net new highs, Stage 2). It is a
        prototype and is not yet tested against forward returns. Percentiles use every session up to the as-of date, so a replay shows only
        what was known on that date.
      </p>
    </div>
  );
}
