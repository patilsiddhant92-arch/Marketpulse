/**
 * Desk › Today — what moved today and why.
 *   1. Market strip: index moves, A/D, 52W highs/lows vs 5-day avg, turnover and delivery vs 20-day avg, VIX.
 *   2. Movers: top gainers / losers with RVOL, delivery, turnover, queue, deals, catalysts and the
 *      server's quality-of-move label (rules as data, hover for the rule).
 *   3. Breakouts + delivery footprints (accumulation / distribution).
 *   4. Groups today: strongest / weakest groups with the fact-only "why" sentence.
 * Stock → Stock 360 sidecar; group → Groups drill; "Charts" → /charts?syms=…
 */
import { HelpCircle, LineChart } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useApiQuery } from '../api/query';
import type { TodayBreakoutRow, TodayMarketRow, TodayMoverRow, TodayStockRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtDate, fmtInt, fmtNum, fmtSignedPct } from '../lib/fmt';
import { TvCopyBar } from '../routes/deals/TvCopy';
import { chartsSourceHref } from '../routes/groups/groupsModel';
import { MetricInline, Segmented, SourceNote, ZoneNum } from '../routes/groups/kit';
import { useShell } from '../shell/ShellContext';
import { useAsOf, useUrlParam } from '../shell/urlState';
import { Chip } from '../ui/Chip';
import { DataTable, type DataTableColumn } from '../ui/DataTable';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { Panel } from '../ui/Panel';
import { Skeleton, SkeletonRows } from '../ui/Skeleton';
import { Tooltip } from '../ui/Tooltip';
import { ChangeCell, KindChips, stockColumns, useGroupNav } from './parts';
import {
  BREADTH_TONE,
  BREAKOUT_KINDS,
  FOOTPRINT_KINDS,
  KIND_LABELS,
  MCAP_FLOORS,
  PERSISTENCE_TONE,
  asMcapFloor,
  clauseText,
  filterByKinds,
  kindCounts,
  splitMovers,
  topBottomGroups,
  type BreakoutRule,
  type EvidenceTrait,
  type QualityRule,
  type TodayGroupRow,
} from './todayModel';

const EMPTY_M: TodayMoverRow[] = [];
const EMPTY_B: TodayBreakoutRow[] = [];
const EMPTY_G: TodayGroupRow[] = [];

// ------------------------------------------------------------------ market strip

function Tile({ label, children, title }: { label: string; children: React.ReactNode; title?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 px-3 py-1.5" title={title}>
      <span className="text-2xs uppercase tracking-wide text-fg-3">{label}</span>
      {children}
    </div>
  );
}

function MarketStrip({ row }: { row: TodayMarketRow }) {
  return (
    <div className="flex flex-wrap items-stretch divide-x divide-line" data-testid="today-market">
      {(row.indices ?? []).map((ix) => (
        <Tile key={ix.name} label={ix.label} title={`${ix.name}: 5D ${fmtSignedPct(ix.return_5d_pct, 1)} · 20D ${fmtSignedPct(ix.return_20d_pct, 1)}`}>
          <span className="flex items-baseline gap-1.5">
            <ChangeCell v={ix.return_1d_pct} />
            <span className="num text-2xs text-fg-3">{fmtNum(ix.close, 0)}</span>
          </span>
          <span className="num text-2xs text-fg-3">5D {fmtSignedPct(ix.return_5d_pct, 1)}</span>
        </Tile>
      ))}
      <div className="px-3 py-1.5">
        <MetricInline metricKey="advance_pct" label="Advance / decline" value={row.advance_pct}>
          <span className="num text-sm">
            <span className="text-up">{fmtInt(row.advancers)}</span> <span className="text-fg-3">/</span> <span className="text-down">{fmtInt(row.decliners)}</span>
          </span>
          <span className="num text-2xs text-fg-3">
            {fmtNum(row.advance_pct, 0)}% up · ≥5%: <span className="text-up">{fmtInt(row.up_5pct)}</span>/<span className="text-down">{fmtInt(row.down_5pct)}</span>
          </span>
        </MetricInline>
      </div>
      <div className="px-3 py-1.5">
        <MetricInline metricKey="new_52w_highs" label="52W highs / lows" value={row.new_52w_highs}>
          <span className="num text-sm">
            <span className="text-up">{fmtInt(row.new_52w_highs)}</span> <span className="text-fg-3">/</span> <span className="text-down">{fmtInt(row.new_52w_lows)}</span>
          </span>
          <span className="num text-2xs text-fg-3">
            5d avg {fmtNum(row.new_52w_highs_5d_avg, 0)} / {fmtNum(row.new_52w_lows_5d_avg, 0)}
          </span>
        </MetricInline>
      </div>
      <div className="px-3 py-1.5">
        <MetricInline metricKey="market_turnover_vs_20d" label="Turnover" value={row.turnover_vs_20d}>
          <span className="num text-sm text-fg">₹{fmtInt(row.turnover_cr)} Cr</span>
          <span className="num text-2xs text-fg-3">
            <ZoneNum metricKey="market_turnover_vs_20d" value={row.turnover_vs_20d} digits={2} />× of 20d avg ₹{fmtInt(row.turnover_20d_avg_cr)}
          </span>
        </MetricInline>
      </div>
      <div className="px-3 py-1.5">
        <MetricInline metricKey="market_delivery_vs_20d" label="Delivery %" value={row.deliv_pct_x}>
          <span className="num text-sm text-fg">{fmtNum(row.delivery_pct, 1)}%</span>
          <span className="num text-2xs text-fg-3">
            <ZoneNum metricKey="market_delivery_vs_20d" value={row.deliv_pct_x} digits={2} />× of 20d avg {fmtNum(row.delivery_pct_20d_avg, 1)}%
          </span>
        </MetricInline>
      </div>
      <div className="px-3 py-1.5">
        <MetricInline metricKey="india_vix" label="India VIX" value={row.india_vix}>
          <span className="num text-sm text-fg">{fmtNum(row.india_vix, 2)}</span>
          <span className="num text-2xs">
            <ChangeCell v={row.vix_change_1d_pct} digits={1} />
          </span>
        </MetricInline>
      </div>
    </div>
  );
}

function MarketPanel() {
  const q = useApiQuery('today/market');
  const row = q.data?.rows[0];
  return (
    <Panel title="Market today" meta={q.data?.as_of ? fmtDate(q.data.as_of) : undefined} actions={<SourceNote meta={q.data?.meta} />} className="shrink-0">
      {q.error ? (
        <ErrorState error={q.error} compact onRetry={() => void q.refetch()} />
      ) : q.isLoading ? (
        <Skeleton height={48} />
      ) : !row ? (
        <EmptyState compact title="No market data" detail={q.data?.meta.reason ?? undefined} />
      ) : (
        <MarketStrip row={row} />
      )}
    </Panel>
  );
}

// ------------------------------------------------------------------ movers

function RulesHelp({ rules, evidence }: { rules: readonly QualityRule[] | undefined; evidence: readonly EvidenceTrait[] | undefined }) {
  return (
    <Tooltip
      content={
        <div className="max-w-md space-y-1.5 text-fg-2">
          <div className="font-medium text-fg">Quality of move — first matching rule wins (missing inputs never match)</div>
          {(rules ?? []).map((r) => (
            <div key={r.id}>
              <b className="text-fg">{r.label}</b>: {clauseText(r.when)}
            </div>
          ))}
          {evidence && evidence.length > 0 && (
            <div className="border-t border-line pt-1.5">
              <div className="font-medium text-fg">Pre-move traits (evidence engine, session before upper-circuit moves)</div>
              {evidence.map((e) => (
                <div key={e.key}>
                  {e.meaning ?? e.key}: <span className="num text-fg">{fmtNum(e.lift_upper_circuit, 2)}×</span> vs matched controls
                  {e.lift_test_upper_circuit != null && <span className="text-fg-3"> (out of sample {fmtNum(e.lift_test_upper_circuit, 2)}×)</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      }
    >
      <span tabIndex={0} className="inline-flex cursor-help items-center gap-1 text-2xs text-fg-3 hover:text-fg">
        <HelpCircle className="h-3.5 w-3.5" /> rules
      </span>
    </Tooltip>
  );
}

function MoversPanel({ className }: { className?: string }) {
  const shell = useShell();
  const [asOf] = useAsOf();
  const onGroup = useGroupNav();
  const [mcapParam, setMcap] = useUrlParam('mcap');
  const [side, setSide] = useState<'gainer' | 'loser'>('gainer');
  const floor = asMcapFloor(mcapParam);
  const q = useApiQuery('today/movers', { query: { min_mcap_cr: Number(floor), n: 50 } });
  const ctx = q.data?.meta.context as { quality_rules?: QualityRule[]; evidence_traits?: EvidenceTrait[]; up?: number; down?: number; universe?: number } | undefined;
  const { gainers, losers } = useMemo(() => splitMovers(q.data?.rows ?? EMPTY_M), [q.data]);
  const rows = side === 'gainer' ? gainers : losers;
  const columns = useMemo(
    () => stockColumns<TodayMoverRow>({ rules: ctx?.quality_rules, evidence: ctx?.evidence_traits, asOf, onGroup }),
    [ctx?.quality_rules, ctx?.evidence_traits, asOf, onGroup],
  );
  const symbols = useMemo(() => rows.map((r) => r.symbol).filter((s): s is string => !!s), [rows]);
  return (
    <Panel
      title="Movers"
      label="Today movers"
      className={className}
      meta={ctx?.universe != null ? `${fmtInt(ctx.up)} up · ${fmtInt(ctx.down)} down of ${fmtInt(ctx.universe)}` : undefined}
      actions={
        <>
          <Segmented
            label="Side"
            size="xs"
            options={[
              { value: 'gainer', label: `Gainers ${gainers.length || ''}` },
              { value: 'loser', label: `Losers ${losers.length || ''}` },
            ]}
            value={side}
            onChange={setSide}
          />
          <Segmented label="Market-cap floor" size="xs" options={MCAP_FLOORS} value={floor} onChange={(v) => setMcap(v === '1000' ? null : v)} />
          <RulesHelp rules={ctx?.quality_rules} evidence={ctx?.evidence_traits} />
          <button
            type="button"
            onClick={() => shell.openCharts(symbols)}
            disabled={!symbols.length}
            className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3 disabled:opacity-50"
            title="Show these stocks in the Charts grid"
          >
            <LineChart className="h-3.5 w-3.5" /> Charts
          </button>
          <TvCopyBar title={side === 'gainer' ? 'Top gainers' : 'Top losers'} symbols={symbols} label="TV" />
        </>
      }
    >
      <DataTable
        label={side === 'gainer' ? 'Top gainers today' : 'Top losers today'}
        columns={columns}
        rows={rows}
        total={q.data ? rows.length : null}
        getRowId={(r) => r.symbol ?? String(r.rank)}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        activeRowId={shell.symbol}
        onActiveRowChange={(r) => r.symbol && shell.openSymbol(r.symbol)}
        onRowClick={(r) => r.symbol && shell.openSymbol(r.symbol)}
        onRowActivate={(r) => r.symbol && shell.openStockPage(r.symbol)}
        emptyState={<EmptyState title="No movers" detail={q.data?.meta.reason ?? 'Nothing moved on this date at this floor.'} />}
        hideToolbar
        className="h-full"
      />
    </Panel>
  );
}

// ------------------------------------------------------------------ breakouts

function BreakoutsPanel({ className }: { className?: string }) {
  const shell = useShell();
  const [asOf] = useAsOf();
  const onGroup = useGroupNav();
  const [mcapParam] = useUrlParam('mcap');
  const floor = asMcapFloor(mcapParam);
  const [tab, setTab] = useState<'breakouts' | 'footprints'>('breakouts');
  const [sel, setSel] = useState<ReadonlySet<string>>(() => new Set());
  const q = useApiQuery('today/breakouts', { query: { min_mcap_cr: Number(floor), limit: 5000 } });
  const ctx = q.data?.meta.context as { quality_rules?: QualityRule[]; evidence_traits?: EvidenceTrait[]; rules?: BreakoutRule[] } | undefined;
  const all = q.data?.rows ?? EMPTY_B;
  const family = tab === 'breakouts' ? BREAKOUT_KINDS : FOOTPRINT_KINDS;
  const rows = useMemo(() => filterByKinds(all, family, sel), [all, family, sel]);
  const counts = useMemo(() => kindCounts(all), [all]);
  const columns = useMemo(() => {
    const kindsCol: DataTableColumn<TodayBreakoutRow> = {
      id: 'kinds',
      header: tab === 'breakouts' ? 'Breakout' : 'Footprint',
      accessor: (r) => (r.kinds ?? []).filter((k) => (family as readonly string[]).includes(k)).join(','),
      width: 170,
      headerTitle: (ctx?.rules ?? []).map((r) => `${r.label}: ${r.rule}`).join('\n'),
      cell: (_v, r) => (
        <span className="block min-w-0 overflow-hidden" title={r.setup_trigger != null ? `Closed above the ${r.setup_queue ?? 'setup'} trigger ${fmtNum(r.setup_trigger, 2)} carried yesterday` : undefined}>
          <KindChips kinds={r.kinds} only={family} />
        </span>
      ),
    };
    return stockColumns<TodayBreakoutRow>({
      rules: ctx?.quality_rules,
      evidence: ctx?.evidence_traits,
      asOf,
      onGroup,
      leading: [kindsCol as unknown as DataTableColumn<TodayStockRow>],
    });
  }, [ctx?.quality_rules, ctx?.evidence_traits, ctx?.rules, asOf, onGroup, tab, family]);
  const symbols = useMemo(() => rows.map((r) => r.symbol).filter((s): s is string => !!s), [rows]);
  const toggle = (k: string) =>
    setSel((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  return (
    <Panel
      title="Breakouts & footprints"
      label="Today breakouts"
      className={className}
      actions={
        <>
          <Segmented
            label="Breakouts or delivery footprints"
            size="xs"
            options={[
              { value: 'breakouts', label: 'Breakouts', title: '52W highs, setup triggers, 20-day highs on RVOL, gap-ups' },
              { value: 'footprints', label: 'Delivery footprints', title: 'Delivered qty ×20d ≥ 1.5 with delivery % at or above its habit: on an up day = accumulation, on a down day = distribution' },
            ]}
            value={tab}
            onChange={(v) => {
              setTab(v);
              setSel(new Set());
            }}
          />
          {family.map((k) => (
            <Chip
              key={k}
              tone={sel.size === 0 || sel.has(k) ? KIND_LABELS[k].tone : 'neutral'}
              selected={sel.has(k)}
              onClick={() => toggle(k)}
              title={ctx?.rules?.find((r) => r.id === k)?.rule}
            >
              {KIND_LABELS[k].label} <span className="num">{counts[k] ?? 0}</span>
            </Chip>
          ))}
          <button
            type="button"
            onClick={() => shell.openCharts(symbols)}
            disabled={!symbols.length}
            className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3 disabled:opacity-50"
            title="Show these stocks in the Charts grid"
          >
            <LineChart className="h-3.5 w-3.5" /> Charts
          </button>
          <TvCopyBar title={tab === 'breakouts' ? 'Breakouts today' : 'Delivery footprints'} symbols={symbols} label="TV" />
        </>
      }
    >
      <DataTable
        label={tab === 'breakouts' ? 'Breakouts today' : 'Delivery footprints today'}
        columns={columns}
        rows={rows}
        total={q.data ? rows.length : null}
        getRowId={(r) => r.symbol ?? ''}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        activeRowId={shell.symbol}
        onActiveRowChange={(r) => r.symbol && shell.openSymbol(r.symbol)}
        onRowClick={(r) => r.symbol && shell.openSymbol(r.symbol)}
        onRowActivate={(r) => r.symbol && shell.openStockPage(r.symbol)}
        emptyState={<EmptyState title="Nothing matched" detail={q.data?.meta.reason ?? 'No stock met these rules on this date.'} />}
        hideToolbar
        className="h-full"
      />
    </Panel>
  );
}

// ------------------------------------------------------------------ groups today (compact)

function GroupItem({ g, onGroup, asOf }: { g: TodayGroupRow; onGroup: (id: string) => void; asOf: string | null }) {
  return (
    <li className="space-y-0.5 px-3 py-1.5">
      <div className="flex items-center gap-1.5 text-xs">
        <button type="button" className="min-w-0 truncate text-left font-medium text-fg hover:text-accent hover:underline" onClick={() => onGroup(g.id)} title={`Drill into ${g.group_name}`}>
          {g.group_name}
        </button>
        <ChangeCell v={g.return_1d} />
        {g.breadth_label && <Chip tone={BREADTH_TONE[g.breadth_label] ?? 'neutral'}>{g.breadth_label}</Chip>}
        {g.persistence && (
          <Chip tone={PERSISTENCE_TONE[g.persistence_id ?? ''] ?? 'neutral'} title={`5d ${fmtSignedPct(g.return_5d, 1)} · 21d ${fmtSignedPct(g.return_21d, 1)}`}>
            {g.persistence}
          </Chip>
        )}
        <Link
          to={chartsSourceHref(g.id, g.symbols ?? [], asOf)}
          className="ml-auto shrink-0 text-fg-3 hover:text-accent"
          title={`Show ${g.group_name} members as charts`}
          aria-label={`${g.group_name} charts`}
        >
          <LineChart className="h-3.5 w-3.5" />
        </Link>
      </div>
      {g.why && <p className="text-2xs leading-snug text-fg-2">{g.why}</p>}
    </li>
  );
}

const LEVEL_OPTS = [
  { value: 'sector', label: 'Sector' },
  { value: 'industry', label: 'Industry' },
] as const;

function GroupsTodayPanel({ className }: { className?: string }) {
  const onGroup = useGroupNav();
  const [asOf] = useAsOf();
  const [level, setLevel] = useState<'sector' | 'industry'>('sector');
  const q = useApiQuery('today/groups', { query: { level, floor: '1000', limit: 5000 } });
  const { up, down } = useMemo(() => topBottomGroups(q.data?.rows ?? EMPTY_G, 5), [q.data]);
  const p = new URLSearchParams({ view: 'today', ...(level !== 'industry' ? { level } : {}) });
  if (asOf) p.set('as_of', asOf);
  return (
    <Panel
      title="Groups today"
      label="Groups today"
      className={className}
      bodyClassName="overflow-y-auto"
      actions={
        <>
          <Segmented label="Group level" size="xs" options={LEVEL_OPTS} value={level} onChange={setLevel} />
          <Link to={`/groups?${p.toString()}`} className="text-2xs text-accent hover:underline" title="Every group with contributors, breadth and the why">
            all →
          </Link>
        </>
      }
    >
      {q.error ? (
        <ErrorState error={q.error} compact onRetry={() => void q.refetch()} />
      ) : q.isLoading ? (
        <SkeletonRows rows={6} label="Loading groups" />
      ) : (
        <div className="divide-y divide-line">
          <div>
            <div className="px-3 pt-1.5 text-2xs font-semibold uppercase tracking-wide text-up">Leading today</div>
            {up.length ? (
              <ul>
                {up.map((g) => (
                  <GroupItem key={g.id} g={g} onGroup={onGroup} asOf={asOf} />
                ))}
              </ul>
            ) : (
              <p className="px-3 py-1.5 text-2xs text-fg-3">No group closed higher.</p>
            )}
          </div>
          <div>
            <div className="px-3 pt-1.5 text-2xs font-semibold uppercase tracking-wide text-down">Lagging today</div>
            {down.length ? (
              <ul>
                {down.map((g) => (
                  <GroupItem key={g.id} g={g} onGroup={onGroup} asOf={asOf} />
                ))}
              </ul>
            ) : (
              <p className="px-3 py-1.5 text-2xs text-fg-3">No group closed lower.</p>
            )}
          </div>
          <p className="px-3 py-1.5 text-2xs text-fg-3">
            The sentence uses only the numbers shown: equal-weight return, members up, top contributors, turnover and delivery vs 20 days, deals, catalysts and
            5d/21d context. Thin groups (&lt; 3 stocks) are left out here.
          </p>
        </div>
      )}
    </Panel>
  );
}

// ------------------------------------------------------------------ view

export function TodayView({ rail }: { rail: boolean }) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-2" data-testid="desk-today">
      <MarketPanel />
      <div className={cn('min-h-0 flex-1', rail ? 'grid grid-cols-[minmax(0,1fr)_380px] gap-2' : 'flex flex-col gap-2 overflow-y-auto')}>
        <div className={cn('grid min-h-0 gap-2', rail ? 'grid-rows-[minmax(0,1.15fr)_minmax(0,1fr)]' : 'grid-rows-[420px_380px]')}>
          <MoversPanel className="min-h-0" />
          <BreakoutsPanel className="min-h-0" />
        </div>
        <GroupsTodayPanel className={rail ? 'min-h-0' : 'h-[520px] shrink-0'} />
      </div>
    </div>
  );
}
