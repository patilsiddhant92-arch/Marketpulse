/**
 * Deals desk views restored from the old FastAPI/React desk (d871ff9 DealsWorkspace):
 * Today's prints, Repeated deals, Play tiers, Prop / churn, Star fund radar, Fund leaderboard.
 * Every symbol list has "Copy to TradingView" + "Copy selected"; row focus drives the Stock 360
 * sidecar; as_of time travel comes from useApiQuery.
 */
import { HelpCircle } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { useApiQuery } from '../../api/query';
import type { DealHolding, DealLeaderRow, DealPrintRow, DealStarRow, DealWindowRow } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtDate, fmtNum } from '../../lib/fmt';
import { useShell } from '../../shell/ShellContext';
import { useUrlParam } from '../../shell/urlState';
import { Chip, type ChipTone } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { EmptyState } from '../../ui/EmptyState';
import { Tooltip } from '../../ui/Tooltip';
import { Segmented, SourceNote, ZoneNum } from '../groups/kit';
import {
  filterRepeated,
  filterText,
  houseOf,
  inPlayScope,
  isDeskTier,
  matchesPersistence,
  persistenceCounts,
  TIER_HINT,
  TIER_LABEL,
  uniqueSymbols,
  type DeskTier,
  type Direction,
  type PlayScope,
  type Setup,
} from './deskModel';
import { EventChip, NetStrip } from './parts';
import { selectColumn, TvCopyBar, useSelection } from './TvCopy';

const TIER_TONE: Record<DeskTier, ChipTone> = {
  conviction: 'positive',
  fresh: 'info',
  distribution: 'negative',
  transfer: 'violet',
  churn: 'neutral',
  quarantined: 'warn',
};

export function TierChip({ tier, reason }: { tier: string | null | undefined; reason?: string | null }) {
  if (!isDeskTier(tier)) return <span className="text-fg-3">—</span>;
  return (
    <Tooltip content={<div className="max-w-xs text-fg-2">{TIER_HINT[tier]}</div>}>
      <span tabIndex={0} className="inline-flex items-center gap-1">
        <Chip tone={TIER_TONE[tier]}>{TIER_LABEL[tier]}</Chip>
        {reason && reason !== 'Transfer' && <span className="text-2xs text-fg-3">{reason}</span>}
      </span>
    </Tooltip>
  );
}

function Hint({ text }: { text: string }) {
  return (
    <Tooltip content={<div className="max-w-sm text-fg-2">{text}</div>}>
      <HelpCircle tabIndex={0} className="h-3 w-3 cursor-help text-fg-3" />
    </Tooltip>
  );
}

function Bar({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-8 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-3 py-1 text-2xs text-fg-3">{children}</div>;
}

/** Row focus -> Stock 360 sidecar (J/K or click), Enter -> stock page. */
function useFocus() {
  const shell = useShell();
  const [focus, setFocus] = useState<string | null>(null);
  const onFocus = useCallback(
    (sym: string | null | undefined) => {
      if (!sym) return;
      setFocus(sym);
      shell.openSymbol(sym);
    },
    [shell],
  );
  return { focus, onFocus, shell };
}

function nameCell<T extends { security_name?: string | null; industry?: string | null; sector?: string | null }>(): DataTableColumn<T> {
  return {
    id: 'name',
    header: 'Name · industry',
    accessor: (r) => r.security_name ?? null,
    width: 180,
    cell: (_v, r) => (
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="truncate text-fg-2">{r.security_name ?? '—'}</span>
        <span className="truncate text-2xs text-fg-3">{r.industry ?? r.sector ?? ''}</span>
      </span>
    ),
  };
}

const symCol = <T extends { symbol?: string | null }>(): DataTableColumn<T> => ({
  id: 'symbol',
  header: 'Symbol',
  accessor: (r) => r.symbol ?? null,
  width: 104,
  sticky: true,
  cell: (v) => <span className="font-mono font-medium text-fg">{String(v)}</span>,
});

function Trend({ above }: { above: boolean | null | undefined }) {
  if (above == null) return <span className="text-fg-3">—</span>;
  return above ? <Chip tone="positive" title="Close ≥ 200 EMA (Stage 2 context)">&gt;200 EMA</Chip> : <Chip tone="warn" title="Close below 200 EMA">Base / turn</Chip>;
}

// --------------------------------------------------------------------------
// Today: all prints of the session
// --------------------------------------------------------------------------
const EMPTY_P: DealPrintRow[] = [];

export function TodayPrintsView({ minMcap, text, onHouse }: { minMcap: number; text: string; onHouse: (h: string) => void }) {
  const { focus, onFocus, shell } = useFocus();
  const sel = useSelection();
  const q = useApiQuery('deals/prints', { query: { min_mcap_cr: minMcap, limit: 5000 } });
  const [side, setSide] = useState<'all' | 'BUY' | 'SELL'>('all');
  const [hideProp, setHideProp] = useState(false);
  const rows = useMemo(
    () => filterText(q.data?.rows ?? EMPTY_P, text).filter((r) => (side === 'all' || r.side === side) && (!hideProp || !r.is_prop)),
    [q.data, text, side, hideProp],
  );
  const [sorted, setSorted] = useState<DealPrintRow[]>([]);
  const syms = useMemo(() => uniqueSymbols(sorted), [sorted]);
  const visible = useMemo(() => uniqueSymbols(rows), [rows]);
  const ctx = q.data?.meta.context as { deal_session?: string; excluded_below_floor?: number; symbols?: number } | undefined;
  const columns = useMemo<DataTableColumn<DealPrintRow>[]>(
    () => [
      selectColumn<DealPrintRow>((r) => r.symbol, sel, visible),
      symCol<DealPrintRow>(),
      {
        id: 'client',
        header: 'Client / house',
        accessor: 'client',
        width: 260,
        cell: (_v, r) => (
          <button type="button" className="flex min-w-0 flex-col text-left leading-tight hover:text-accent" title="Open the client's track record" onClick={(e) => { e.stopPropagation(); if (r.client) onHouse(r.client); }}>
            <span className="truncate text-fg">{r.client}</span>
            {r.house && r.house !== r.client && <span className="truncate text-2xs text-fg-3">{r.house}</span>}
          </button>
        ),
      },
      { id: 'side', header: 'Side', accessor: 'side', width: 50, cell: (v) => <span className={cn('font-semibold', v === 'BUY' ? 'text-up' : 'text-down')}>{String(v)}</span> },
      { id: 'value', header: '₹ Cr', accessor: 'value_cr', format: 'num', digits: 2, width: 70 },
      { id: 'price', header: 'Price', accessor: 'price', format: 'num', digits: 2, width: 76 },
      { id: 'pvc', header: 'vs close', accessor: 'price_vs_close_pct', format: 'signedPct', digits: 1, width: 70, metricKey: 'deal_price_vs_close' },
      { id: 'class', header: 'Clientele', accessor: (r) => (r.is_prop ? 'PROP' : r.clientele), width: 80, cell: (v) => <Chip tone={v === 'FII' || v === 'DII' ? 'info' : v === 'PROP' ? 'neutral' : 'violet'}>{String(v)}</Chip> },
      { id: 'event', header: 'Stock event', accessor: 'event_type', width: 118, metricKey: 'deal_event_type', cell: (v) => <EventChip type={v as string} /> },
      { id: 'mcap', header: 'Mcap ₹Cr', accessor: 'market_cap_cr', format: 'int', width: 80, metricKey: 'market_cap_cr' },
      { id: 'trend', header: 'Trend', accessor: (r) => (r.above_200ema == null ? null : r.above_200ema ? 1 : 0), width: 84, cell: (_v, r) => <Trend above={r.above_200ema} /> },
      { id: 'sector', header: 'Sector', accessor: (r) => r.sector ?? null, width: 140 },
      { id: 'qty', header: 'Qty', accessor: 'quantity', format: 'int', width: 90, defaultHidden: true },
      { id: 'types', header: 'Files', accessor: 'deal_types', width: 84, defaultHidden: true },
    ],
    [sel, visible, onHouse],
  );
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Bar>
        <Segmented size="xs" label="Side" value={side} onChange={setSide} options={[{ value: 'all', label: 'Both sides' }, { value: 'BUY', label: 'Buys' }, { value: 'SELL', label: 'Sells' }]} />
        <label className="inline-flex items-center gap-1">
          <input type="checkbox" checked={hideProp} onChange={(e) => setHideProp(e.target.checked)} /> Hide PROP
        </label>
        <span>
          {ctx?.symbols ?? '—'} stocks · {q.data?.total ?? '—'} prints on {fmtDate(ctx?.deal_session ?? null)}
          {(ctx?.excluded_below_floor ?? 0) > 0 && ` · ${ctx?.excluded_below_floor} below floor hidden`}
        </span>
        <span>Matched buy = sell on one name is usually a transfer, not new money (see the Stock event).</span>
        <span className="ml-auto flex items-center gap-2">
          <SourceNote meta={q.data?.meta} />
          <TvCopyBar title="Deals Today" symbols={syms} selected={sel.selected} onClear={sel.clear} />
        </span>
      </Bar>
      <DataTable
        label="All deal prints of the session"
        columns={columns}
        rows={rows}
        total={q.data ? rows.length : null}
        getRowId={(r, i) => `${r.symbol}-${r.client}-${r.side}-${r.quantity}-${r.price}-${i}`}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        onActiveRowChange={(r) => onFocus(r.symbol)}
        onRowActivate={(r) => r.symbol && shell.openStockPage(r.symbol)}
        onSortedRowsChange={setSorted}
        initialSort={[{ id: 'value', desc: true }]}
        emptyState={<EmptyState title="No prints" detail={focus ? undefined : 'No bulk/block prints stored for this session (or all below the floor).'} />}
        className="min-h-0 flex-1"
      />
    </div>
  );
}

// --------------------------------------------------------------------------
// Window views: Repeated · Play · Prop / churn
// --------------------------------------------------------------------------
const EMPTY_W: DealWindowRow[] = [];

function windowColumns(dates: (string | null)[], mode: 'repeated' | 'play' | 'prop', onHouse: (h: string) => void): DataTableColumn<DealWindowRow>[] {
  const houses = (list: string[], tone: 'up' | 'down') =>
    list.length === 0 ? (
      <span className="text-fg-3">—</span>
    ) : (
      <span className="flex min-w-0 flex-col leading-tight">
        {list.slice(0, 2).map((h) => (
          <button key={h} type="button" className={cn('truncate text-left text-2xs hover:underline', tone === 'up' ? 'text-up' : 'text-down')} title={`${h} — open track record`} onClick={(e) => { e.stopPropagation(); onHouse(houseOf(h)); }}>
            {h}
          </button>
        ))}
      </span>
    );
  const cols: DataTableColumn<DealWindowRow>[] = [
    symCol<DealWindowRow>(),
    nameCell<DealWindowRow>(),
    { id: 'tier', header: 'Tier', accessor: 'tier', width: 128, cell: (_v, r) => <TierChip tier={r.tier} reason={r.play_reason} /> },
    { id: 'days', header: 'Deal days', accessor: 'deal_days', format: 'int', width: 66, headerTitle: 'Sessions in the window with any print (the old desk "repeated deals" count)' },
    { id: 'bdays', header: 'Buy days', accessor: 'net_buy_days', format: 'int', width: 60, metricKey: 'persistence_days', headerTitle: 'Accumulate / fresh sessions (net buying ex-PROP)' },
    { id: 'sdays', header: 'Sell days', accessor: 'net_sell_days', format: 'int', width: 60, headerTitle: 'Distribute sessions' },
    {
      id: 'strip',
      header: `Net by session (${dates.length})`,
      accessor: (r) => (r.net_by_session ?? []).filter((x) => x != null).length,
      width: Math.max(110, dates.length * 6 + 12),
      headerTitle: 'Flow net ex-PROP ₹ Cr per deal session (oldest → newest); flat = transfer / churn session, dot = no deal',
      cell: (_v, r) => <NetStrip values={r.net_by_session} dates={dates} />,
    },
    { id: 'net', header: 'Flow net ₹Cr', accessor: 'flow_net_cr', format: 'signed', digits: 1, width: 82, metricKey: 'deal_net_cr', cell: (v) => <ZoneNum metricKey="deal_net_cr" value={v as number} format="signed" digits={1} /> },
    { id: 'adv', header: '× ADV', accessor: 'net_vs_adv', format: 'num', digits: 2, width: 58, metricKey: 'deal_vs_adv' },
    { id: 'houses', header: 'Houses', accessor: 'n_houses', format: 'int', width: 58, headerTitle: 'Distinct non-PROP houses (entities of one fund house merged)', cell: (_v, r) => <span className="num">{r.n_buy_houses}<span className="text-fg-3">↑ </span>{r.n_sell_houses}<span className="text-fg-3">↓</span></span> },
    { id: 'buyers', header: 'Top buyers', accessor: (r) => r.top_buyers?.[0] ?? null, width: 190, renderNull: true, cell: (_v, r) => houses(r.top_buyers ?? [], 'up') },
    { id: 'sellers', header: 'Top sellers', accessor: (r) => r.top_sellers?.[0] ?? null, width: 170, renderNull: true, cell: (_v, r) => houses(r.top_sellers ?? [], 'down') },
    { id: 'trend', header: 'Trend', accessor: (r) => (r.above_200ema == null ? null : r.above_200ema ? 1 : 0), width: 84, cell: (_v, r) => <Trend above={r.above_200ema} /> },
    { id: 'away', header: '52W high', accessor: 'away_52w_high_pct', format: 'signedPct', digits: 1, width: 66, headerTitle: '% from the 52-week high' },
    { id: 'rs', header: 'RS', accessor: 'rs_percentile', format: 'num', digits: 0, width: 44, metricKey: 'rs_percentile' },
    { id: 'mcap', header: 'Mcap ₹Cr', accessor: 'market_cap_cr', format: 'int', width: 78, metricKey: 'market_cap_cr' },
    { id: 'sector', header: 'Sector', accessor: (r) => r.sector ?? null, width: 130 },
    { id: 'last', header: 'Last deal', accessor: 'last_deal_date', format: 'date', width: 80 },
    { id: 'lastev', header: 'Last event', accessor: 'last_event_type', width: 112, cell: (v) => <EventChip type={v as string} /> },
    { id: 'transfer', header: 'Transfer ₹Cr', accessor: 'transfer_cr', format: 'num', digits: 1, width: 80, defaultHidden: mode !== 'play' },
    { id: 'prop', header: 'PROP ₹Cr', accessor: 'prop_value_cr', format: 'num', digits: 1, width: 72, defaultHidden: mode !== 'prop' },
    { id: 'churn', header: 'Churn days', accessor: 'churn_days', format: 'int', width: 66, defaultHidden: mode !== 'prop' },
    { id: 'gross', header: 'Buy / Sell ₹Cr', accessor: (r) => (r.buy_cr ?? 0) + (r.sell_cr ?? 0), width: 104, defaultHidden: mode === 'repeated', cell: (_v, r) => <span className="num text-fg-2">{fmtNum(r.buy_cr, 1)} / {fmtNum(r.sell_cr, 1)}</span> },
    { id: 'fiidii', header: 'FII+DII ₹Cr', accessor: (r) => (r.fii_net_cr == null && r.dii_net_cr == null ? null : (r.fii_net_cr ?? 0) + (r.dii_net_cr ?? 0)), format: 'signed', digits: 1, width: 76, defaultHidden: true },
  ];
  return cols;
}

export function WindowView({ mode, lookback, minMcap, setup, text, onHouse }: { mode: 'repeated' | 'play' | 'prop'; lookback: number; minMcap: number; setup: Setup; text: string; onHouse: (h: string) => void }) {
  const { focus, onFocus, shell } = useFocus();
  const sel = useSelection();
  const [minDaysP, setMinDays] = useUrlParam('rdays');
  const [dirP, setDir] = useUrlParam('rdir');
  const [scopeP, setScope] = useUrlParam('tier');
  const [pillP, setPill] = useUrlParam('sessions');
  const minDays = Number(minDaysP ?? 2) || 2;
  const dir: Direction = dirP === 'buy' || dirP === 'sell' ? dirP : 'all';
  const scope: PlayScope = (['conviction', 'fresh', 'distribution', 'transfer', 'quarantined'] as const).find((s) => s === scopeP) ?? 'play';
  const pill = Number(pillP ?? 0) || 0;
  const q = useApiQuery('deals/window', { query: { lookback, min_mcap_cr: minMcap, setup, limit: 5000 } });
  const ctx = q.data?.meta.context as { window_dates?: (string | null)[]; tier_counts?: Record<string, number>; excluded_below_floor?: number; excluded_by_setup?: number } | undefined;
  const dates = useMemo(() => ctx?.window_dates ?? [], [ctx]);
  const all = q.data?.rows ?? EMPTY_W;
  const base = useMemo(() => {
    const t = filterText(all, text);
    if (mode === 'repeated') return filterRepeated(t, minDays, dir);
    if (mode === 'prop') return t.filter((r) => r.tier === 'churn');
    return t.filter((r) => inPlayScope(r.tier, scope));
  }, [all, text, mode, minDays, dir, scope]);
  const pc = useMemo(() => persistenceCounts(base), [base]);
  const rows = useMemo(() => (mode === 'play' ? base.filter((r) => matchesPersistence(r.deal_days, pill)) : base), [base, mode, pill]);
  const [sorted, setSorted] = useState<DealWindowRow[]>([]);
  const syms = useMemo(() => uniqueSymbols(sorted), [sorted]);
  const visible = useMemo(() => uniqueSymbols(rows), [rows]);
  const columns = useMemo(() => [selectColumn<DealWindowRow>((r) => r.symbol, sel, visible), ...windowColumns(dates, mode, onHouse)], [sel, visible, dates, mode, onHouse]);
  const tc = ctx?.tier_counts ?? {};
  const title =
    mode === 'repeated' ? `Deals repeated ${minDays}+ of ${lookback}s` : mode === 'prop' ? `Deals Prop HFT churn ${lookback}s` : `Deals ${scope === 'play' ? 'Play' : TIER_LABEL[scope as DeskTier]} ${lookback}s`;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Bar>
        {mode === 'repeated' && (
          <>
            <Segmented
              size="xs"
              label="Minimum deal sessions"
              value={String(minDays) as '2' | '3' | '4' | '5'}
              onChange={(v) => setMinDays(v === '2' ? null : v)}
              options={[{ value: '2', label: '≥ 2 sessions' }, { value: '3', label: '≥ 3' }, { value: '4', label: '≥ 4' }, { value: '5', label: '≥ 5' }]}
            />
            <Segmented size="xs" label="Net direction" value={dir} onChange={(v) => setDir(v === 'all' ? null : v)} options={[{ value: 'all', label: 'Any direction' }, { value: 'buy', label: 'Net buying' }, { value: 'sell', label: 'Net selling' }]} />
            <Hint text="Stocks with bulk/block prints on at least N of the last sessions. Direction = flow net ex-PROP over the window (transfers and churn sessions add nothing)." />
          </>
        )}
        {mode === 'play' && (
          <>
            <Segmented
              size="xs"
              label="Desk tier"
              value={scope}
              onChange={(v) => setScope(v === 'play' ? null : v)}
              options={[
                { value: 'play', label: `Play (${(tc.conviction ?? 0) + (tc.fresh ?? 0)})`, title: 'Conviction + fresh whales' },
                { value: 'conviction', label: `Conviction (${tc.conviction ?? 0})`, title: TIER_HINT.conviction },
                { value: 'fresh', label: `Fresh (${tc.fresh ?? 0})`, title: TIER_HINT.fresh },
                { value: 'distribution', label: `Distribution (${tc.distribution ?? 0})`, title: TIER_HINT.distribution },
                { value: 'transfer', label: `Transfers (${tc.transfer ?? 0})`, title: TIER_HINT.transfer },
                { value: 'quarantined', label: `Quarantined (${tc.quarantined ?? 0})`, title: TIER_HINT.quarantined },
              ]}
            />
            <span className="inline-flex items-center gap-1">
              Sessions
              <Segmented
                size="xs"
                label="Persistence"
                value={String(pill) as '0' | '2' | '3' | '4'}
                onChange={(v) => setPill(v === '0' ? null : v)}
                options={[{ value: '0', label: 'All' }, { value: '4', label: `4+ (${pc[4]})` }, { value: '3', label: `3 (${pc[3]})` }, { value: '2', label: `2 (${pc[2]})` }]}
              />
            </span>
          </>
        )}
        {mode === 'prop' && <span>Stocks whose every deal session in the window was churn: PROP desks or same-day round trips. Scalp turnover, no FII/DII sponsorship.</span>}
        <span>
          {rows.length} of {all.length} stocks
          {(ctx?.excluded_below_floor ?? 0) > 0 && ` · ${ctx?.excluded_below_floor} below floor`}
          {(ctx?.excluded_by_setup ?? 0) > 0 && ` · ${ctx?.excluded_by_setup} off setup`}
          {dates.length > 0 && ` · ${fmtDate(dates[0] ?? null)} → ${fmtDate(dates[dates.length - 1] ?? null)}`}
        </span>
        <span className="ml-auto flex items-center gap-2">
          <SourceNote meta={q.data?.meta} />
          <TvCopyBar title={title} symbols={syms} selected={sel.selected} onClear={sel.clear} />
        </span>
      </Bar>
      <DataTable
        label={title}
        columns={columns}
        rows={rows}
        total={q.data ? rows.length : null}
        getRowId={(r) => r.symbol}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        activeRowId={focus}
        onActiveRowChange={(r) => onFocus(r.symbol)}
        onRowActivate={(r) => shell.openStockPage(r.symbol)}
        onSortedRowsChange={setSorted}
        initialSort={mode === 'prop' ? [{ id: 'gross', desc: true }] : [{ id: 'days', desc: true }, { id: 'net', desc: true }]}
        emptyState={<EmptyState title="No stocks" detail="Widen the lookback, drop the floor or setup filter, or lower the session count." />}
        className="min-h-0 flex-1"
      />
    </div>
  );
}

// --------------------------------------------------------------------------
// Star fund radar
// --------------------------------------------------------------------------
const EMPTY_S: DealStarRow[] = [];

function useHouseOptions() {
  const [ind, setInd] = useUrlParam('ind');
  const [bets, setBets] = useUrlParam('bets');
  return { individuals: ind === '1', setIndividuals: (on: boolean) => setInd(on ? '1' : null), minBets: bets === '3' ? 3 : 5, setMinBets: (n: 3 | 5) => setBets(n === 3 ? '3' : null) };
}

function HouseOptions({ o }: { o: ReturnType<typeof useHouseOptions> }) {
  return (
    <>
      <Segmented
        size="xs"
        label="Minimum finished T+20 bets"
        value={String(o.minBets) as '3' | '5'}
        onChange={(v) => o.setMinBets(v === '3' ? 3 : 5)}
        options={[{ value: '5', label: '≥ 5 bets' }, { value: '3', label: '≥ 3 (small sample)', title: 'The old desk ranked on 2 bets; 3 is allowed but noisy' }]}
      />
      <label className="inline-flex items-center gap-1" title="Individuals (HNI / OTHER) are not funds; the old desk listed celebrity HNIs too">
        <input type="checkbox" checked={o.individuals} onChange={(e) => o.setIndividuals(e.target.checked)} /> Include individuals
      </label>
    </>
  );
}

export function StarView({ lookback, text, onHouse }: { lookback: number; text: string; onHouse: (h: string) => void }) {
  const { focus, onFocus, shell } = useFocus();
  const sel = useSelection();
  const o = useHouseOptions();
  const [fromP, setFrom] = useUrlParam('stars');
  const starsFrom = fromP === 'steady' ? 'steady' : 'strong';
  const q = useApiQuery('deals/star-radar', { query: { lookback, include_individuals: o.individuals, stars_from: starsFrom, min_bets: o.minBets, limit: 5000 } });
  const rows = useMemo(() => filterText(q.data?.rows ?? EMPTY_S, text), [q.data, text]);
  const [sorted, setSorted] = useState<DealStarRow[]>([]);
  const syms = useMemo(() => uniqueSymbols(sorted), [sorted]);
  const visible = useMemo(() => uniqueSymbols(rows), [rows]);
  const ctx = q.data?.meta.context as { star_houses?: number; star_house_names?: string[]; small_sample?: boolean } | undefined;
  const columns = useMemo<DataTableColumn<DealStarRow>[]>(
    () => [
      selectColumn<DealStarRow>((r) => r.symbol, sel, visible),
      symCol<DealStarRow>(),
      { id: 'house', header: 'Fund house', accessor: 'house', width: 230, cell: (_v, r) => <button type="button" className="truncate text-left text-fg hover:text-accent hover:underline" title={r.client ?? r.house} onClick={(e) => { e.stopPropagation(); onHouse(r.client ?? r.house); }}>{r.house}</button> },
      { id: 'tier', header: 'Tier', accessor: 'tier', width: 128, cell: (v) => <Chip tone={v === 'Star Catalyst' ? 'accent' : v === 'Strong Accumulator' ? 'positive' : 'info'}>{String(v)}</Chip> },
      { id: 'score', header: 'Catalyst', accessor: 'catalyst_score', format: 'num', digits: 1, width: 64, headerTitle: '40 % win rate + 30 % avg peak run-up + 15 % avg T+20 + 15 % speed to peak (0-100)' },
      { id: 'win', header: 'Win 20D', accessor: 'win_rate_20d', format: 'pct', digits: 0, width: 62, headerTitle: 'Share of finished bets with T+20 ≥ +5 % from the next open' },
      { id: 'date', header: 'Deal date', accessor: 'deal_date', format: 'date', width: 82 },
      { id: 'px', header: 'Deal price', accessor: 'deal_price', format: 'num', digits: 2, width: 76 },
      { id: 'entry', header: 'Entry (next open)', accessor: 'entry_open', format: 'num', digits: 2, width: 96 },
      { id: 'cmp', header: 'CMP', accessor: 'cmp', format: 'num', digits: 2, width: 72 },
      { id: 'gain', header: 'Gain %', accessor: 'gain_pct', format: 'signedPct', digits: 1, width: 66, cell: (v) => <span className={cn('num', (v as number) > 0 ? 'text-up' : (v as number) < 0 ? 'text-down' : '')}>{fmtNum(v as number, 1)}%</span> },
      { id: 'peak', header: 'Peak run-up', accessor: 'peak_runup_pct', format: 'signedPct', digits: 1, width: 78 },
      { id: 'hold', header: 'Holding days', accessor: 'holding_days', format: 'int', width: 74 },
      { id: 'value', header: 'Value ₹Cr', accessor: 'deal_cr', format: 'num', digits: 1, width: 72 },
      { id: 'rs', header: 'RS', accessor: 'rs_percentile', format: 'num', digits: 0, width: 44, metricKey: 'rs_percentile' },
      { id: 'away', header: '52W high', accessor: 'away_52w_high_pct', format: 'signedPct', digits: 1, width: 66 },
      { id: 'mcap', header: 'Mcap ₹Cr', accessor: 'market_cap_cr', format: 'int', width: 78, metricKey: 'market_cap_cr' },
      { id: 'sector', header: 'Sector', accessor: (r) => r.sector ?? null, width: 130, defaultHidden: true },
    ],
    [sel, visible, onHouse],
  );
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Bar>
        <Segmented
          size="xs"
          label="Star houses"
          value={starsFrom}
          onChange={(v) => setFrom(v === 'strong' ? null : v)}
          options={[
            { value: 'strong', label: 'Star + Strong', title: 'Tier Star Catalyst or Strong Accumulator' },
            { value: 'steady', label: '+ Steady value', title: 'Also tier Steady Value' },
          ]}
        />
        <HouseOptions o={o} />
        <span>
          {ctx?.star_houses ?? '—'} star houses · {rows.length} buys in the last {lookback} deal sessions
        </span>
        {ctx?.small_sample && <Chip tone="warn">small sample</Chip>}
        <Hint text={(q.data?.meta.notes ?? []).join(' ')} />
        <span className="ml-auto flex items-center gap-2">
          <SourceNote meta={q.data?.meta} />
          <TvCopyBar title={`Deals Star radar ${lookback}s`} symbols={syms} selected={sel.selected} onClear={sel.clear} />
        </span>
      </Bar>
      <DataTable
        label="Star fund radar"
        columns={columns}
        rows={rows}
        total={q.data ? rows.length : null}
        getRowId={(r, i) => `${r.symbol}-${r.house}-${r.deal_date}-${i}`}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        onActiveRowChange={(r) => onFocus(r.symbol)}
        onRowActivate={(r) => shell.openStockPage(r.symbol)}
        onSortedRowsChange={setSorted}
        emptyState={
          <EmptyState
            title={focus ? 'No star buys' : 'No star-house buys in the window'}
            detail={`${ctx?.star_houses ?? 0} houses qualify (ranked on ≥ ${o.minBets} finished T+20 bets, entry at the next open). Try "+ Steady value", ≥ 3 bets, individuals, or a 30-session lookback.`}
          />
        }
        className="min-h-0 flex-1"
      />
    </div>
  );
}

// --------------------------------------------------------------------------
// Fund leaderboard & alpha
// --------------------------------------------------------------------------
const EMPTY_L: DealLeaderRow[] = [];

const holdingColumns: DataTableColumn<DealHolding>[] = [
  { id: 'symbol', header: 'Symbol', accessor: 'symbol', width: 100, cell: (v) => <span className="font-mono text-fg">{String(v)}</span> },
  { id: 'net', header: 'Net ₹Cr', accessor: 'net_cr', format: 'signed', digits: 1, width: 70, cell: (v) => <ZoneNum metricKey="deal_net_cr" value={v as number} format="signed" digits={1} /> },
  { id: 'buy', header: 'Buy', accessor: 'buy_cr', format: 'num', digits: 1, width: 60 },
  { id: 'sell', header: 'Sell', accessor: 'sell_cr', format: 'num', digits: 1, width: 60 },
  { id: 'last', header: 'Last', accessor: 'last_date', format: 'date', width: 80 },
  { id: 'side', header: 'Side', accessor: 'last_side', width: 48, cell: (v) => <span className={v === 'BUY' ? 'text-up' : 'text-down'}>{String(v)}</span> },
  { id: 'px', header: 'Price', accessor: 'last_price', format: 'num', digits: 2, width: 70 },
  { id: 'prints', header: 'Prints', accessor: 'prints', format: 'int', width: 50 },
];

export function LeaderView({ lookback, text, onHouse }: { lookback: number; text: string; onHouse: (h: string) => void }) {
  const shell = useShell();
  const o = useHouseOptions();
  const [rankedP, setRanked] = useUrlParam('ranked');
  const rankedOnly = rankedP !== 'all';
  const q = useApiQuery('deals/leaderboard', { query: { lookback, include_individuals: o.individuals, ranked_only: rankedOnly, min_bets: o.minBets, limit: 5000 } });
  const rows = useMemo(() => {
    const t = text.trim().toLowerCase();
    return (q.data?.rows ?? EMPTY_L).filter((r) => !t || r.house.toLowerCase().includes(t) || (r.holdings ?? []).some((h) => h.symbol.toLowerCase().includes(t)));
  }, [q.data, text]);
  const [focus, setFocus] = useState<string | null>(null);
  const focusRow = rows.find((r) => r.house === focus) ?? null;
  const [hSorted, setHSorted] = useState<DealHolding[]>([]);
  const longSyms = useMemo(() => uniqueSymbols(hSorted.filter((h) => (h.net_cr ?? 0) > 0)), [hSorted]);
  const allSyms = useMemo(() => uniqueSymbols(hSorted), [hSorted]);
  const ctx = q.data?.meta.context as { houses_total?: number; ranked_total?: number; small_sample?: boolean } | undefined;
  const columns = useMemo<DataTableColumn<DealLeaderRow>[]>(
    () => [
      { id: 'house', header: 'Fund house', accessor: 'house', width: 250, sticky: true, cell: (v) => <span className="truncate text-fg">{String(v)}</span> },
      { id: 'class', header: 'Class', accessor: 'clientele', width: 76, cell: (v) => <Chip tone={String(v).includes('FII') || String(v).includes('DII') ? 'info' : 'violet'}>{String(v)}</Chip> },
      { id: 'tier', header: 'Tier', accessor: 'tier', width: 132, cell: (v) => <Chip tone={v === 'Star Catalyst' ? 'accent' : v === 'Strong Accumulator' ? 'positive' : v === 'Steady Value' ? 'info' : 'neutral'}>{String(v)}</Chip> },
      { id: 'score', header: 'Catalyst', accessor: 'catalyst_score', format: 'num', digits: 1, width: 64, headerTitle: '40 % win rate + 30 % avg peak run-up + 15 % avg T+20 + 15 % speed to peak (0-100)' },
      { id: 'win', header: 'Win 20D', accessor: 'win_rate_20d', format: 'pct', digits: 0, width: 62, headerTitle: 'Finished bets with T+20 ≥ +5 % from the next open' },
      { id: 'hit', header: 'Hit %', accessor: 'hit_rate_20d', format: 'pct', digits: 0, width: 54, metricKey: 'house_hit_rate_t20' },
      { id: 'avg20', header: 'Avg T+20', accessor: 'avg_ret_20d', format: 'signedPct', digits: 1, width: 68 },
      { id: 'ex20', header: 'vs index', accessor: 'avg_excess_20d', format: 'signed', digits: 1, width: 64, metricKey: 'deal_fwd_excess_t20', cell: (v) => <ZoneNum metricKey="deal_fwd_excess_t20" value={v as number} format="signed" digits={1} /> },
      { id: 'peak', header: 'Avg peak', accessor: 'avg_peak_runup', format: 'signedPct', digits: 1, width: 68, headerTitle: 'Average highest high within 60 sessions after entry' },
      { id: 'dtp', header: 'Days to peak', accessor: 'avg_days_to_peak', format: 'num', digits: 0, width: 74 },
      { id: 'bets', header: 'Bets', accessor: 'bets_t20', format: 'int', width: 70, metricKey: 'sample_n', cell: (_v, r) => <span className="num">{r.bets_t20}<span className="text-fg-3"> / {r.bets}</span></span> },
      { id: 'names', header: 'Names', accessor: 'names', format: 'int', width: 54 },
      { id: 'netlong', header: 'Net long', accessor: 'net_long_count', format: 'int', width: 62, headerTitle: `Names net bought in the last ${lookback} deal sessions (print tape, not a holdings filing)`, cell: (_v, r) => <span className="num">{r.net_long_count}<span className="text-fg-3"> / {r.names_in_window}</span></span> },
      { id: 'cr', header: '₹ Cr', accessor: 'total_cr', format: 'num', digits: 0, width: 66 },
      { id: 'bag', header: '≥ 25 % runs', accessor: 'baggers', format: 'int', width: 70, defaultHidden: true },
      { id: 'best', header: 'Best run', accessor: 'best_gain', format: 'signedPct', digits: 1, width: 66, defaultHidden: true },
      { id: 'lastbuy', header: 'Last buy', accessor: 'latest_buy_date', format: 'date', width: 80 },
    ],
    [lookback],
  );
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Bar>
        <Segmented size="xs" label="Houses shown" value={rankedOnly ? 'ranked' : 'all'} onChange={(v) => setRanked(v === 'ranked' ? null : v)} options={[{ value: 'ranked', label: 'Ranked' }, { value: 'all', label: 'All with bets' }]} />
        <HouseOptions o={o} />
        <span>
          {rows.length} houses{ctx?.houses_total != null && ` of ${ctx.houses_total}`} · entry next open · win = T+20 ≥ +5 %
        </span>
        {ctx?.small_sample && <Chip tone="warn">small sample</Chip>}
        <Hint text={(q.data?.meta.notes ?? []).join(' ')} />
        <span className="ml-auto">
          <SourceNote meta={q.data?.meta} />
        </span>
      </Bar>
      <DataTable
        label="Fund leaderboard"
        columns={columns}
        rows={rows}
        total={q.data ? rows.length : null}
        getRowId={(r) => r.house}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        activeRowId={focus}
        onActiveRowChange={(r) => setFocus(r.house)}
        onRowActivate={(r) => onHouse(r.clients?.[0] ?? r.house)}
        emptyState={<EmptyState title="No houses" detail="Show all houses with bets, ≥ 3 bets, or include individuals." />}
        className="min-h-0 flex-1"
      />
      <div className="flex h-[210px] shrink-0 flex-col border-t border-line bg-surface">
        {focusRow ? (
          <>
            <div className="flex flex-wrap items-center gap-2 px-2 py-1 text-2xs text-fg-3">
              <span className="text-xs font-semibold text-fg">{focusRow.house}</span>
              <span>print tape, last {lookback} deal sessions (≥ ₹5 Cr, PROP excluded) — not a holdings filing</span>
              <button type="button" className="text-accent hover:underline" onClick={() => onHouse(focusRow.clients?.[0] ?? focusRow.house)}>
                full track record
              </button>
              <span className="ml-auto flex items-center gap-2">
                <TvCopyBar title={`${focusRow.house.slice(0, 30)} net long`} symbols={longSyms} />
                <TvCopyBar title={`${focusRow.house.slice(0, 30)} names`} symbols={allSyms} />
              </span>
            </div>
            <DataTable
              label={`${focusRow.house} holdings`}
              columns={holdingColumns}
              rows={focusRow.holdings ?? []}
              total={focusRow.names_in_window}
              getRowId={(r) => r.symbol}
              onSortedRowsChange={setHSorted}
              onActiveRowChange={(r) => shell.openSymbol(r.symbol)}
              onRowActivate={(r) => shell.openStockPage(r.symbol)}
              emptyState={<EmptyState title={`No prints in the last ${lookback} deal sessions`} />}
              hideToolbar
              className="min-h-0 flex-1"
            />
          </>
        ) : (
          <div className="p-2 text-2xs text-fg-3">Select a house (J/K or click) to see the names it bought and sold in the window, with TradingView copy. Enter opens its full track record.</div>
        )}
      </div>
    </div>
  );
}
