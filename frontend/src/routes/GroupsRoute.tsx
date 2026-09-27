/**
 * Groups — Sector Intel + Capital Flow merged (spec 7.4).
 *
 * Board of taxonomy groups (Broad Sector › Sector › Broad Industry › Industry)
 * at a market-cap floor, sorted by Health (peer-relative RRG + the group's own
 * trend + breadth), with a context line tied to the Desk verdict, the RRG, a
 * money-flow panel and a taxonomy heatmap view. Enter / double-click (or the RRG) drills into a group:
 * breadcrumb, history and members (row focus opens Stock 360).
 */
import { ChevronRight, HelpCircle, LineChart } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useApiQuery } from '../api/query';
import type { GroupRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtSigned, fmtSignedPct } from '../lib/fmt';
import { useShell } from '../shell/ShellContext';
import { useAsOf, useUrlParam } from '../shell/urlState';
import { Chip } from '../ui/Chip';
import { DataTable, type DataTableColumn } from '../ui/DataTable';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { Skeleton } from '../ui/Skeleton';
import { Spark } from '../ui/Spark';
import { Tooltip } from '../ui/Tooltip';
import { TodayGroups } from '../today/TodayGroups';
import { GroupDrill } from './groups/GroupDrill';
import { GroupsGlance } from './groups/GroupsGlance';
import {
  asFloor,
  asLevel,
  chartsSourceHref,
  filterGroups,
  FLOORS,
  flowLeaders,
  LEVELS,
  levelLabel,
  marketContextLine,
  quadrantCounts,
  rankSparkValues,
  rrgVisible,
  type FlowItem,
  type MarketContext,
} from './groups/groupsModel';
import { HealthCell, QuadrantWithNote, TrendArrow } from './groups/health';
import { GroupsTreemap } from './groups/Treemap';
import { QUADRANT_TONE, QUADRANTS, RankDelta, Segmented, SourceNote, ZoneNum } from './groups/kit';
import { RrgChart } from './groups/RrgChart';

const EMPTY: GroupRow[] = [];
const RRG_PER_QUADRANT = 8;
/** Levels with this many groups or fewer (Broad Sector, Sector) always show every group. */
const RRG_SHOW_ALL_UP_TO = 40;

function NameCell({ row, onDrill }: { row: GroupRow; onDrill: (id: string) => void }) {
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <button
        type="button"
        className="min-w-0 truncate text-left text-fg hover:text-accent hover:underline"
        onClick={(e) => {
          e.stopPropagation();
          onDrill(row.id);
        }}
        title={`Drill into ${row.group_name ?? ''}`}
      >
        {row.group_name ?? '—'}
      </button>
      {row.concentration_flag && (
        <Chip tone="warn" title="One member is ≥ 50% of the group's turnover: flow numbers mostly reflect that stock">
          1-stock
        </Chip>
      )}
      {(row.stocks ?? 0) < 3 && (
        <Chip title="Fewer than 3 members: listed but not ranked">thin</Chip>
      )}
    </span>
  );
}

function boardColumns(onDrill: (id: string) => void): DataTableColumn<GroupRow>[] {
  return [
    { id: 'health_rank', header: '#', accessor: 'health_rank', format: 'int', width: 40, metricKey: 'group_health', sticky: true, sortDescFirst: false, headerTitle: 'Rank by Health (1 = healthiest); groups with < 3 members are not ranked' },
    {
      id: 'group_name',
      header: 'Group',
      accessor: 'group_name',
      width: 230,
      sticky: true,
      renderNull: true,
      cell: (_v, r) => <NameCell row={r} onDrill={onDrill} />,
    },
    {
      id: 'health',
      header: 'Health',
      accessor: 'health',
      format: 'num',
      digits: 0,
      width: 92,
      metricKey: 'group_health',
      cell: (v, r) => <HealthCell value={v as number} rank={r.health_rank} />,
    },
    { id: 'stocks', header: 'Stocks', accessor: 'stocks', format: 'int', width: 60, headerTitle: 'Members meeting the floor' },
    {
      id: 'rrg_quadrant',
      header: 'RRG vs peers',
      accessor: 'rrg_quadrant',
      width: 158,
      metricKey: 'rrg_quadrant',
      cell: (_v, r) => <QuadrantWithNote quadrant={r.rrg_quadrant} days={r.days_in_quadrant} note={r.quadrant_note} />,
    },
    {
      id: 'abs_trend',
      header: 'Trend',
      accessor: (r) => ({ Up: 1, Flat: 0, Down: -1 } as Record<string, number>)[r.abs_trend ?? ''] ?? null,
      width: 50,
      metricKey: 'group_abs_trend',
      renderNull: true,
      cell: (_v, r) => <TrendArrow trend={r.abs_trend} />,
    },
    { id: 'ret_21', header: 'Ret 21d', accessor: 'return_ew_21d', format: 'signedPct', digits: 1, width: 64, metricKey: 'group_return_ew_21d', cell: (v) => <span className={cn('num', typeof v === 'number' ? (v < 0 ? 'text-down' : 'text-up') : 'text-fg-3')}>{fmtSignedPct(v as number, 1)}</span> },
    { id: 'breadth_50', header: '>50E', accessor: 'breadth_50', format: 'pct', digits: 0, width: 52, metricKey: 'group_breadth_50', cell: (v) => <ZoneNum metricKey="group_breadth_50" value={v as number} format="pct" digits={0} /> },
    { id: 'rank', header: 'Rank MS', accessor: 'rank', format: 'int', width: 58, metricKey: 'group_rank', sortDescFirst: false, headerTitle: 'Rank by mean 21d/63d excess return vs NIFTY MIDSML 400 (1 = best)' },
    { id: 'rank_delta_5', header: 'Δ5', accessor: 'rank_delta_5', format: 'int', width: 50, metricKey: 'group_rank_delta_5', cell: (v) => <RankDelta value={v as number} /> },
    { id: 'rank_delta_20', header: 'Δ20', accessor: 'rank_delta_20', format: 'int', width: 50, metricKey: 'group_rank_delta_20', cell: (v) => <RankDelta value={v as number} /> },
    { id: 'rank_delta_63', header: 'Δ63', accessor: 'rank_delta_63', format: 'int', width: 50, defaultHidden: true, headerTitle: 'Rank change over 63 sessions (positive = climbed)', cell: (v) => <RankDelta value={v as number} /> },
    {
      id: 'rank_spark',
      header: 'Rank 60d',
      accessor: (r) => r.rank_spark_60?.filter((x) => x != null).length ?? null,
      sortable: false,
      width: 84,
      headerTitle: 'Rank over the last 60 sessions (up = improving)',
      cell: (_v, r) => <Spark values={rankSparkValues(r.rank_spark_60)} label={`${r.group_name} rank, 60 sessions`} width={72} height={18} />,
    },
    { id: 'excess_21', header: 'Exc 21d', accessor: 'excess_vs_midsml400_21d', format: 'signed', digits: 1, width: 64, metricKey: 'group_excess_21d', cell: (v) => <ZoneNum metricKey="group_excess_21d" value={v as number} format="signed" digits={1} /> },
    { id: 'excess_63', header: 'Exc 63d', accessor: 'excess_vs_midsml400_63d', format: 'signed', digits: 1, width: 64, metricKey: 'group_excess_63d', cell: (v) => <ZoneNum metricKey="group_excess_63d" value={v as number} format="signed" digits={1} /> },
    {
      id: 'rs_line',
      header: 'RS line 60d',
      accessor: (r) => (r.rs_line_60 ? (r.rs_line_60[r.rs_line_60.length - 1] ?? null) : null),
      width: 84,
      headerTitle: 'Equal-weight group index ÷ MidSml400 over 60 sessions, rebased to 100 (sorts by its last value)',
      renderNull: true,
      cell: (_v, r) =>
        r.rs_line_60 ? <Spark values={r.rs_line_60} baseline={100} label={`${r.group_name} RS line`} width={72} height={18} /> : <span className="text-fg-3">—</span>,
    },
    { id: 'rs_ratio', header: 'RS-R', accessor: 'rs_ratio', format: 'num', digits: 1, width: 56, metricKey: 'rs_ratio', cell: (v) => <ZoneNum metricKey="rs_ratio" value={v as number} digits={1} /> },
    { id: 'rs_momentum', header: 'RS-M', accessor: 'rs_momentum', format: 'num', digits: 1, width: 56, metricKey: 'rs_momentum', cell: (v) => <ZoneNum metricKey="rs_momentum" value={v as number} digits={1} /> },
    { id: 'rs_ratio_self', header: 'RS self', accessor: 'rs_ratio_self', format: 'num', digits: 1, width: 60, metricKey: 'rs_ratio_self', defaultHidden: true },
    { id: 'ret_cw_21', header: 'Ret 21d CW', accessor: 'return_cw_21d', format: 'signedPct', digits: 1, width: 72, defaultHidden: true, headerTitle: 'Cap-weighted 21-session return' },
    { id: 'exn_21', header: 'vs N50 21d', accessor: 'excess_vs_nifty50_21d', format: 'signed', digits: 1, width: 72, defaultHidden: true, metricKey: 'excess_vs_nifty50_21d' },
    { id: 'exn_63', header: 'vs N50 63d', accessor: 'excess_vs_nifty50_63d', format: 'signed', digits: 1, width: 72, defaultHidden: true, metricKey: 'excess_vs_nifty50_63d' },
    { id: 'breadth_200', header: '>200E', accessor: 'breadth_200', format: 'pct', digits: 0, width: 56, metricKey: 'group_breadth_200', cell: (v) => <ZoneNum metricKey="group_breadth_200" value={v as number} format="pct" digits={0} /> },
    { id: 'tt', header: 'TT', accessor: 'trend_template_pct', format: 'pct', digits: 0, width: 48, metricKey: 'group_trend_template_pct', cell: (v) => <ZoneNum metricKey="group_trend_template_pct" value={v as number} format="pct" digits={0} /> },
    { id: 'nh', header: 'NH', accessor: 'new_highs', format: 'int', width: 40, headerTitle: 'Members making an official new 52-week high today', defaultHidden: true },
    { id: 'to_share', header: 'T/O 5d', accessor: 'turnover_share_5d', format: 'pct', digits: 2, width: 60, metricKey: 'turnover_share_5d' },
    { id: 'flow', header: 'Flow Δ', accessor: 'turnover_share_delta', format: 'signed', digits: 2, width: 62, metricKey: 'turnover_share_delta_20d', cell: (v) => <ZoneNum metricKey="turnover_share_delta_20d" value={v as number} format="signed" digits={2} /> },
    { id: 'flow_days', header: 'Flow d', accessor: 'flow_up_days_10', format: 'int', width: 52, metricKey: 'group_flow_up_days', cell: (v) => <ZoneNum metricKey="group_flow_up_days" value={v as number} format="int" /> },
    { id: 'deliv', header: 'Deliv acc', accessor: 'delivery_accumulation', format: 'signed', digits: 0, width: 64, metricKey: 'group_delivery_accumulation', cell: (v) => <ZoneNum metricKey="group_delivery_accumulation" value={v as number} format="signed" digits={0} /> },
    { id: 'deal', header: 'Deals 10s', accessor: 'deal_net_10s_cr', format: 'signed', digits: 0, width: 70, metricKey: 'deal_net_10s_cr', cell: (v) => <ZoneNum metricKey="deal_net_10s_cr" value={v as number} format="signed" digits={0} /> },
    { id: 'top1', header: 'Top-1', accessor: 'top1_turnover_share_pct', format: 'pct', digits: 0, width: 52, metricKey: 'group_top1_turnover_share', cell: (v) => <ZoneNum metricKey="group_top1_turnover_share" value={v as number} format="pct" digits={0} /> },
    {
      id: 'leaders',
      header: 'Leaders',
      accessor: (r) => r.leader_symbols?.join(' ') ?? null,
      width: 190,
      headerTitle: 'Top members by strength rank (RS percentile) at as-of',
      cell: (v) => <span className="truncate font-mono text-2xs text-fg-2">{String(v)}</span>,
    },
  ];
}

function FlowList({ title, items, tone, onDrill }: { title: string; items: FlowItem[]; tone: 'up' | 'down'; onDrill: (id: string) => void }) {
  return (
    <div className="min-w-0 flex-1">
      <div className={cn('mb-1 text-2xs font-semibold uppercase tracking-wide', tone === 'up' ? 'text-up' : 'text-down')}>{title}</div>
      {items.length === 0 ? (
        <div className="text-2xs text-fg-3">None</div>
      ) : (
        <ul className="space-y-0.5">
          {items.map(({ row, delta }) => (
            <li key={row.id}>
              <button
                type="button"
                onClick={() => onDrill(row.id)}
                className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-2xs hover:bg-surface-3"
                title={`Turnover share 5d avg ${row.turnover_share_5d?.toFixed(2) ?? '—'}% vs 20d ${row.turnover_share_20d?.toFixed(2) ?? '—'}%`}
              >
                <span className="min-w-0 flex-1 truncate text-fg">{row.group_name}</span>
                <span className={cn('num', tone === 'up' ? 'text-up' : 'text-down')}>{fmtSigned(delta, 2)}</span>
                <span className="num w-9 text-right text-fg-3" title="Inflow sessions of the last 10">
                  {row.flow_up_days_10 != null ? `${row.flow_up_days_10}/10` : '—'}
                </span>
                <span
                  className={cn('num w-12 text-right', (row.deal_net_10s_cr ?? 0) > 0 ? 'text-up' : (row.deal_net_10s_cr ?? 0) < 0 ? 'text-down' : 'text-fg-3')}
                  title="Bulk/block deal net over 10 sessions, ₹ Cr (PROP excluded)"
                >
                  {row.deal_net_10s_cr != null ? fmtSigned(row.deal_net_10s_cr, 0) : '—'}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const HOW_TO = (
  <div className="max-w-md space-y-1.5 text-fg-2">
    <div className="font-medium text-fg">How to read Groups</div>
    <div>
      <b className="text-fg">Health</b> (0–100, default sort) — 40% strength vs peers (RRG) + 35% the group&apos;s own trend (equal-weight index vs its 50/200
      EMA, 21d return) + 25% breadth (% of members above 50/200 EMA). ≥ 65 Healthy · 45–65 Mixed · &lt; 45 Weak.
    </div>
    <div>
      <b className="text-fg">RRG vs peers</b> — RS-Ratio (x) and RS-Momentum (y) are z-scores across this level&apos;s groups (100 = average group), so
      about half sit right of 100 by construction. <i>Leading = strongest vs peers, not necessarily rising</i>: the chip &quot;falling&quot; marks a
      Leading/Improving group whose 21d return is negative, &quot;narrow&quot; one with &lt; 50% of members above their 50 EMA. Trend arrow = the
      group&apos;s own direction. Hollow RRG dots = own trend Down.
    </div>
    <div>
      <b className="text-fg">Rank MS</b> — mean 21/63-session excess return over NIFTY MIDSML 400; Δ = places climbed.
    </div>
    <div>
      <b className="text-fg">Money flow</b> — share of the floor universe&apos;s turnover, 5-day average minus 20-day average (smoothed; single days swing).
      Check Top-1: a one-stock group&apos;s flow is that stock&apos;s news.
    </div>
    <div>
      <b className="text-fg">Deals</b> — disclosed bulk/block net over 10 sessions, PROP desks excluded. Context only; see the Deals tab follow-through.
    </div>
  </div>
);

export default function GroupsRoute() {
  const [levelParam, setLevel] = useUrlParam('level');
  const [floorParam, setFloor] = useUrlParam('floor');
  const [groupParam, setGroup] = useUrlParam('group', { push: true });
  const [quadParam, setQuad] = useUrlParam('quad');
  const [rrgAll, setRrgAll] = useUrlParam('rrg');
  const [viewParam, setView] = useUrlParam('view');
  const view = viewParam === 'map' ? 'map' : viewParam === 'today' ? 'today' : 'board';
  const [asOf] = useAsOf();
  const sidecarOpen = !!useShell().symbol;
  const [text, setText] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const level = asLevel(levelParam);
  const floor = asFloor(floorParam);
  const quadSet = useMemo(() => new Set((quadParam ?? '').split(',').filter(Boolean)), [quadParam]);

  const board = useApiQuery('groups/board', { query: { level, floor, limit: 5000 } });
  const rrg = useApiQuery('groups/rrg', { query: { level, floor, tail_weeks: 6 } });

  const rows = board.data?.rows ?? EMPTY;
  const filtered = useMemo(() => filterGroups(rows, text, quadSet), [rows, text, quadSet]);
  const counts = useMemo(() => quadrantCounts(rows), [rows]);
  const flow = useMemo(() => flowLeaders(rows), [rows]);
  const allowed = useMemo(() => (text || quadSet.size ? new Set(filtered.map((r) => r.id)) : null), [filtered, text, quadSet]);
  const rrgRows = rrg.data?.rows;
  const rrgView = useMemo(() => rrgVisible(rrgRows ?? [], allowed, rrgAll === 'all' || (rrgRows?.length ?? 0) <= RRG_SHOW_ALL_UP_TO ? null : RRG_PER_QUADRANT), [rrgRows, allowed, rrgAll]);
  const columns = useMemo(() => boardColumns((id) => setGroup(id)), [setGroup]);
  const ctx = board.data?.meta.context as { floor_label?: string; ranked?: number; benchmark?: string; market?: MarketContext } | undefined;
  const contextLine = marketContextLine(ctx?.market);

  const toggleQuad = (q: string) => {
    const next = new Set(quadSet);
    if (next.has(q)) next.delete(q);
    else next.add(q);
    setQuad([...next].join(',') || null);
  };

  if (groupParam) {
    return (
      <GroupDrill
        groupId={groupParam}
        floor={floor}
        onBack={() => setGroup(null)}
        onNavigate={(id) => setGroup(id)}
        chartsHref={(syms) => chartsSourceHref(groupParam, syms, asOf)}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* at-a-glance band (board data only) */}
      <div className="shrink-0 px-2 pb-1.5 pt-2">
        <GroupsGlance
          rows={rows}
          market={ctx?.market}
          contextLine={contextLine}
          quadrants={counts}
          levelLabel={levelLabel(level)}
          floorLabel={ctx?.floor_label ?? FLOORS.find((f) => f.value === floor)?.title}
          asOf={board.data?.as_of}
          loading={board.isLoading}
          onDrill={(id) => setGroup(id)}
        />
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line bg-surface px-3 py-1.5">
        <h1 className="text-sm font-semibold text-fg">Groups</h1>
        <Segmented label="Taxonomy level" options={LEVELS.map((l) => ({ value: l.value, label: l.short, title: l.label }))} value={level} onChange={(v) => setLevel(v === 'industry' ? null : v)} />
        <Segmented label="Market-cap floor" options={FLOORS} value={floor} onChange={(v) => setFloor(v === '1000' ? null : v)} />
        <Segmented
          label="View"
          options={[
            { value: 'board', label: 'Board', title: 'Board with RRG and money flow' },
            { value: 'map', label: 'Map', title: 'Taxonomy heatmap: Broad Sector › … sized by turnover, coloured by Health or 21d return' },
            { value: 'today', label: 'Today', title: 'What moved today and why: 1D return, breadth, contributors, turnover and delivery vs 20 days, deals, catalysts' },
          ]}
          value={view}
          onChange={(v) => setView(v === 'board' ? null : v)}
        />
        <input
          data-filter-input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Filter groups  /"
          aria-label="Filter groups by name"
          className="h-6 w-44 rounded border border-line bg-surface-2 px-2 text-xs text-fg placeholder:text-fg-3 focus:border-focus focus:outline-none"
        />
        <div className="flex items-center gap-1">
          {QUADRANTS.map((q) => (
            <Chip key={q} tone={quadSet.has(q) || quadSet.size === 0 ? QUADRANT_TONE[q] : 'neutral'} selected={quadSet.has(q)} onClick={() => toggleQuad(q)} title={`Show only ${q} groups`}>
              {q} <span className="num">{counts[q]}</span>
            </Chip>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <SourceNote meta={board.data?.meta} />
          <Tooltip content={HOW_TO}>
            <span tabIndex={0} className="inline-flex cursor-help items-center gap-1 text-2xs text-fg-3 hover:text-fg">
              <HelpCircle className="h-3.5 w-3.5" /> How to read
            </span>
          </Tooltip>
        </div>
      </div>
      {view === 'today' ? (
        <div className="min-h-0 flex-1">
          <TodayGroups level={level} floor={floor} text={text} onDrill={(id) => setGroup(id)} />
        </div>
      ) : view === 'map' ? (
        <div className="min-h-0 flex-1">
          <GroupsTreemap floor={floor} onDrill={(id) => setGroup(id)} />
        </div>
      ) : (
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <DataTable
            label={`${levelLabel(level)} board`}
            columns={columns}
            rows={filtered}
            total={board.data ? filtered.length : null}
            getRowId={(r) => r.id}
            loading={board.isLoading}
            error={board.error}
            onRetry={() => void board.refetch()}
            initialSort={[{ id: 'health_rank', desc: false }]}
            activeRowId={selected}
            onActiveRowChange={(r) => setSelected(r.id)}
            onRowActivate={(r) => setGroup(r.id)}
            emptyState={<EmptyState title="No groups match" detail="Clear the filter or quadrant chips." />}
            className="min-h-0 flex-1"
          />
        </div>
        <aside className={cn('flex shrink-0 flex-col border-l border-line bg-surface', sidecarOpen ? 'w-[320px]' : 'w-[400px]')}>
          <div className="flex h-7 shrink-0 items-center gap-2 border-b border-line px-2 text-2xs">
            <span className="font-semibold uppercase tracking-wide text-fg-2">Rotation</span>
            <span
              className="truncate text-fg-3"
              title="x = RS-Ratio, y = RS-Momentum, both vs the other groups (100 = average group); hollow dot = own trend Down; tails = weekly points over 6 weeks"
            >
              vs peers · hollow = falling · 6-wk tails
            </span>
            {rrgRows && rrgAll !== 'all' && rrgView.total > rrgView.shown.length && (
              <button
                type="button"
                className="ml-auto shrink-0 text-accent hover:underline"
                title={`Showing the healthiest ${RRG_PER_QUADRANT} groups of each quadrant`}
                onClick={() => setRrgAll('all')}
              >
                {rrgView.shown.length}/{rrgView.total} · show all
              </button>
            )}
            {rrgAll === 'all' && (rrgRows?.length ?? 0) > RRG_SHOW_ALL_UP_TO && (
              <button type="button" className="ml-auto shrink-0 text-accent hover:underline" onClick={() => setRrgAll(null)}>
                top {RRG_PER_QUADRANT} per quadrant
              </button>
            )}
          </div>
          <div className="h-[360px] shrink-0 p-1">
            {rrg.error ? (
              <ErrorState error={rrg.error} compact onRetry={() => void rrg.refetch()} />
            ) : rrg.isLoading ? (
              <Skeleton className="h-full w-full" />
            ) : rrg.data?.meta.status === 'unavailable' ? (
              <EmptyState compact title="RRG unavailable" detail={rrg.data.meta.reason ?? undefined} />
            ) : (
              <RrgChart rows={rrgView.shown} selectedId={selected} onSelect={(id) => setGroup(id)} />
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-auto border-t border-line p-2">
            <div className="mb-1.5 flex items-center gap-2">
              <span className="text-2xs font-semibold uppercase tracking-wide text-fg-2">Money flow</span>
              <Tooltip
                content={
                  <div className="max-w-xs text-fg-2">
                    Groups (≥ 3 members) whose 5-day average share of turnover rose / fell most versus their 20-day average. x/10 = inflow sessions of
                    the last 10 (persistence). Last column: bulk/block deal net over 10 sessions, ₹ Cr, PROP excluded.
                  </div>
                }
              >
                <HelpCircle tabIndex={0} className="h-3 w-3 cursor-help text-fg-3" />
              </Tooltip>
            </div>
            {board.isLoading ? (
              <Skeleton height={120} />
            ) : (
              <div className="flex flex-col gap-2">
                <FlowList title="Inflow" items={flow.inflow} tone="up" onDrill={(id) => setGroup(id)} />
                <FlowList title="Outflow" items={flow.outflow} tone="down" onDrill={(id) => setGroup(id)} />
              </div>
            )}
            {selected && (
              <div className="mt-3 border-t border-line pt-2 text-2xs text-fg-3">
                <button type="button" className="inline-flex items-center gap-1 text-accent hover:underline" onClick={() => setGroup(selected)}>
                  Open {rows.find((r) => r.id === selected)?.group_name} <ChevronRight className="h-3 w-3" />
                </button>
                <span className="ml-2">(Enter)</span>
                <Link className="ml-3 inline-flex items-center gap-1 text-accent hover:underline" to={chartsSourceHref(selected, [], asOf)}>
                  <LineChart className="h-3 w-3" /> charts
                </Link>
              </div>
            )}
          </div>
        </aside>
      </div>
      )}
    </div>
  );
}
