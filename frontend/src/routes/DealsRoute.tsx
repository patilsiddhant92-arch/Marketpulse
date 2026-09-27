/**
 * Deals — disclosed bulk/block deals (spec 7.5).
 *
 * Session: per-stock nets for the latest deal session (prints collapsed, PROP
 * excluded from events), grouped Accumulate · Fresh · Distribute, with rails
 * for strategic transfers, churn/prop and the watchlist, and the prints behind
 * the focused row. Houses: every client with its next-open track record.
 * Follow-through: what happened after each event type vs all stocks.
 */
import { AlertTriangle, HelpCircle, LineChart } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useApiQuery } from '../api/query';
import type { DealSessionRow, FollowThroughRow, HouseRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtDate, fmtNum, fmtSigned, fmtSignedPct } from '../lib/fmt';
import { useShell } from '../shell/ShellContext';
import { useAsOf, useUrlParam } from '../shell/urlState';
import { Chip } from '../ui/Chip';
import { DataTable, type DataTableColumn } from '../ui/DataTable';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { Skeleton } from '../ui/Skeleton';
import { Tooltip } from '../ui/Tooltip';
import { Segmented, SourceNote, ZoneNum } from './groups/kit';
import { chartsDealsHref, EVENTS, filterDeals, splitSession, type EventType } from './deals/dealsModel';
import { EventChip, HouseDrawer, NetStrip, PrintsPanel } from './deals/parts';

type View = 'session' | 'houses' | 'follow';
const EMPTY: DealSessionRow[] = [];
const EMPTY_H: HouseRow[] = [];

function Align({ ok, label, title }: { ok: boolean | null | undefined; label: string; title: string }) {
  if (ok == null) return <span className="text-2xs text-fg-3" title={`${title}: unknown`}>·</span>;
  return (
    <span title={`${title}: ${ok ? 'yes' : 'no'}`} className={cn('rounded px-1 text-2xs font-medium', ok ? 'bg-up/15 text-up' : 'bg-surface-3 text-fg-3 line-through')}>
      {label}
    </span>
  );
}

function sessionColumns(dates: (string | null)[]): DataTableColumn<DealSessionRow>[] {
  return [
    { id: 'event', header: 'Event', accessor: (r) => (r.event_type && r.event_type in EVENTS ? EVENTS[r.event_type as EventType].order : 9), width: 118, metricKey: 'deal_event_type', sortDescFirst: false, cell: (_v, r) => <EventChip type={r.event_type} rule={r.event_rule} /> },
    { id: 'symbol', header: 'Symbol', accessor: 'symbol', width: 104, sticky: true, cell: (v) => <span className="font-mono font-medium text-fg">{String(v)}</span> },
    {
      id: 'name',
      header: 'Name · industry',
      accessor: 'security_name',
      width: 190,
      cell: (_v, r) => (
        <span className="flex min-w-0 flex-col leading-tight">
          <span className="truncate text-fg-2">{r.security_name ?? '—'}</span>
          <span className="truncate text-2xs text-fg-3">{r.industry ?? ''}</span>
        </span>
      ),
    },
    { id: 'net', header: 'Net ₹Cr', accessor: (r) => r.net_ex_prop_cr ?? r.net_cr, format: 'signed', digits: 1, width: 76, metricKey: 'deal_net_cr', cell: (v) => <ZoneNum metricKey="deal_net_cr" value={v as number} format="signed" digits={1} /> },
    { id: 'vs_adv', header: '× ADV', accessor: 'vs_adv', format: 'num', digits: 2, width: 58, metricKey: 'deal_vs_adv' },
    { id: 'buyers', header: 'Buyers', accessor: 'buying_houses', format: 'int', width: 56, metricKey: 'buying_houses', cell: (v) => <ZoneNum metricKey="buying_houses" value={v as number} format="int" /> },
    { id: 'sellers', header: 'Sellers', accessor: 'selling_houses', format: 'int', width: 56, headerTitle: 'Distinct non-PROP net sellers' },
    { id: 'persist', header: 'Persist', accessor: 'persistence_days', format: 'int', width: 58, metricKey: 'persistence_days', cell: (v) => <ZoneNum metricKey="persistence_days" value={v as number} format="int" /> },
    {
      id: 'net10',
      header: 'Net by day (10)',
      accessor: (r) => (r.net_10s ?? []).filter((x) => x != null).length,
      width: 96,
      headerTitle: 'Net ex-PROP ₹ Cr on each of the last 10 sessions (oldest → today); dot = no deal. Hover for values.',
      cell: (_v, r) => <NetStrip values={r.net_10s} dates={dates} />,
    },
    { id: 'vwap_cmp', header: 'CMP vs VWAP', accessor: 'vwap_vs_cmp_pct', format: 'signedPct', digits: 1, width: 84, metricKey: 'deal_vwap_vs_cmp', cell: (v) => <ZoneNum metricKey="deal_vwap_vs_cmp" value={v as number} format="signedPct" digits={1} /> },
    { id: 'px_close', header: 'Deal vs close', accessor: 'deal_price_vs_close_pct', format: 'signedPct', digits: 1, width: 84, metricKey: 'deal_price_vs_close', cell: (v) => <ZoneNum metricKey="deal_price_vs_close" value={v as number} format="signedPct" digits={1} /> },
    {
      id: 'align',
      header: 'Alignment',
      accessor: (r) => [r.above_200ema, r.rs_ge_70, r.within_15pct_of_high].filter(Boolean).length,
      width: 118,
      headerTitle: 'Chart context: above 200 EMA · strength rank ≥ 70 · within 15% of the 52-week high',
      cell: (_v, r) => (
        <span className="flex gap-0.5">
          <Align ok={r.above_200ema} label="200E" title="Close above 200 EMA" />
          <Align ok={r.rs_ge_70} label="RS70" title="Strength rank ≥ 70" />
          <Align ok={r.within_15pct_of_high} label="Hi15" title="Within 15% of 52-week high" />
        </span>
      ),
    },
    { id: 'inst', header: 'FII+DII', accessor: 'institutional_net_cr', format: 'signed', digits: 1, width: 66, headerTitle: 'Net of FII and DII clients, ₹ Cr' },
    { id: 'prints', header: 'Prints', accessor: 'prints', format: 'int', width: 50, headerTitle: 'Collapsed prints (a bulk+block duplicate counts once)' },
    { id: 'mcap', header: 'Mcap ₹Cr', accessor: 'market_cap_cr', format: 'int', width: 76, metricKey: 'market_cap_cr' },
    { id: 'rs', header: 'RS', accessor: 'rs_percentile', format: 'num', digits: 0, width: 44, metricKey: 'rs_percentile', defaultHidden: true },
    { id: 'gross', header: 'Buy / Sell ₹Cr', accessor: (r) => (r.buy_cr ?? 0) + (r.sell_cr ?? 0), format: 'num', width: 104, cell: (_v, r) => <span className="num text-fg-2">{fmtNum(r.buy_cr, 1)} / {fmtNum(r.sell_cr, 1)}</span> },
    { id: 'types', header: 'Files', accessor: 'deal_types', width: 84, defaultHidden: true },
  ];
}

function RailList({ title, hint, rows, focus, onFocus }: { title: string; hint: string; rows: DealSessionRow[]; focus: string | null; onFocus: (r: DealSessionRow) => void }) {
  return (
    <section className="border-b border-line p-2">
      <div className="mb-1 flex items-center gap-2">
        <span className="text-2xs font-semibold uppercase tracking-wide text-fg-2">{title}</span>
        <span className="num text-2xs text-fg-3">{rows.length}</span>
        <Tooltip content={<div className="max-w-xs text-fg-2">{hint}</div>}>
          <HelpCircle tabIndex={0} className="h-3 w-3 cursor-help text-fg-3" />
        </Tooltip>
      </div>
      {rows.length === 0 ? (
        <div className="text-2xs text-fg-3">None this session.</div>
      ) : (
        <ul className="max-h-56 space-y-px overflow-auto">
          {rows.map((r) => (
            <li key={r.symbol}>
              <button
                type="button"
                onClick={() => onFocus(r)}
                className={cn('flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-2xs hover:bg-surface-3', focus === r.symbol && 'bg-surface-3')}
              >
                <span className="w-24 truncate font-mono text-fg">{r.symbol}</span>
                <EventChip type={r.event_type} rule={r.event_rule} />
                <span className="num ml-auto text-fg-2" title="Gross buy + sell, ₹ Cr">
                  {fmtNum((r.buy_cr ?? 0) + (r.sell_cr ?? 0), 1)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SessionView({ rows, dates, text, dealDate, onHouse, loading, error, onRetry }: {
  rows: DealSessionRow[];
  dates: (string | null)[];
  text: string;
  dealDate: string | null;
  onHouse: (h: string) => void;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  const shell = useShell();
  const [focus, setFocus] = useState<string | null>(null);
  const filtered = useMemo(() => filterDeals(rows, text), [rows, text]);
  const parts = useMemo(() => splitSession(filtered), [filtered]);
  const watch = useMemo(() => filtered.filter((r) => r.symbol && shell.isWatched(r.symbol)), [filtered, shell]);
  const columns = useMemo(() => sessionColumns(dates), [dates]);
  const focusRow = rows.find((r) => r.symbol === focus) ?? null;
  const onFocus = (r: DealSessionRow) => {
    if (!r.symbol) return;
    setFocus(r.symbol);
    shell.openSymbol(r.symbol);
  };
  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <DataTable
          label="Deal session: accumulate, fresh buyers and distribution"
          columns={columns}
          rows={parts.main}
          total={parts.main.length}
          getRowId={(r, i) => r.symbol ?? String(i)}
          loading={loading}
          error={error}
          onRetry={onRetry}
          activeRowId={focus}
          onActiveRowChange={onFocus}
          onRowActivate={(r) => r.symbol && shell.openStockPage(r.symbol)}
          emptyState={
            <EmptyState
              title="No accumulate / fresh / distribute rows"
              detail="Every deal this session was a transfer or churn (see the rails), or nothing passed the floor."
            />
          }
          className="min-h-0 flex-1"
        />
        <div className="h-[190px] shrink-0 overflow-auto border-t border-line bg-surface p-2">
          {focusRow?.symbol ? (
            <>
              <div className="mb-1 flex items-center gap-2 text-2xs">
                <span className="font-mono text-xs font-semibold text-fg">{focusRow.symbol}</span>
                <EventChip type={focusRow.event_type} rule={focusRow.event_rule} />
                <span className="text-fg-3">Prints on {fmtDate(dealDate)} — click a client for its track record</span>
                <span className="ml-auto flex items-center gap-2 text-fg-3">
                  Net by day <NetStrip values={focusRow.net_10s} dates={dates} height={22} />
                </span>
              </div>
              {focusRow.event_rule && <div className="mb-1 text-2xs text-fg-3">Why this label: {focusRow.event_rule}</div>}
              <PrintsPanel symbol={focusRow.symbol} date={dealDate} onHouse={onHouse} />
            </>
          ) : (
            <div className="text-2xs text-fg-3">Select a row (J/K or click) to see its prints and the houses behind it. The Stock 360 sidecar follows.</div>
          )}
        </div>
      </div>
      <aside className="w-[330px] shrink-0 overflow-auto border-l border-line bg-surface">
        <RailList
          title="Strategic / transfer"
          hint="Inter-se transfers (seller matched by buyers at the same price and quantity — promoter or group entities) and placements absorbed by FII/DII. Ownership moves, not market flow."
          rows={parts.strategic}
          focus={focus}
          onFocus={onFocus}
        />
        <RailList
          title="Churn / prop"
          hint="PROP desks or same-day round trips are at least half the value, or the net excluding PROP is zero. Not a signal."
          rows={parts.churn}
          focus={focus}
          onFocus={onFocus}
        />
        <RailList title="Watch" hint="Your watchlist symbols with deals this session." rows={watch} focus={focus} onFocus={onFocus} />
      </aside>
    </div>
  );
}

const houseColumns: DataTableColumn<HouseRow>[] = [
  { id: 'house', header: 'House', accessor: 'house', width: 260, sticky: true, cell: (v) => <span className="truncate text-fg">{String(v)}</span> },
  { id: 'class', header: 'Class', accessor: 'clientele', width: 90, cell: (v) => <Chip tone={v === 'FII' || v === 'DII' ? 'info' : v === 'PROP' ? 'neutral' : 'violet'}>{String(v)}</Chip> },
  { id: 'snet', header: 'Session net', accessor: 'session_net_cr', format: 'signed', digits: 1, width: 84, headerTitle: 'Net ₹ Cr on the deal session', cell: (v) => <ZoneNum metricKey="deal_net_cr" value={v as number} format="signed" digits={1} /> },
  { id: 'ssyms', header: 'Session stocks', accessor: (r) => r.session_symbols?.join(' ') ?? null, width: 150, cell: (v) => <span className="truncate font-mono text-2xs text-fg-2">{String(v)}</span> },
  { id: 'bets', header: 'Bets T+20', accessor: 'buy_bets_t20', format: 'int', width: 70, metricKey: 'sample_n' },
  { id: 'hit', header: 'Hit %', accessor: 'hit_rate_t20', format: 'pct', digits: 0, width: 56, metricKey: 'house_hit_rate_t20', cell: (v) => <ZoneNum metricKey="house_hit_rate_t20" value={v as number} format="pct" digits={0} /> },
  { id: 'avg20', header: 'Avg T+20', accessor: 'avg_fwd_t20_pct', format: 'signedPct', digits: 1, width: 70 },
  { id: 'ex20', header: 'vs index', accessor: 'avg_excess_t20_pct', format: 'signed', digits: 1, width: 64, metricKey: 'deal_fwd_excess_t20', cell: (v) => <ZoneNum metricKey="deal_fwd_excess_t20" value={v as number} format="signed" digits={1} /> },
  { id: 'prints', header: 'Prints', accessor: 'prints', format: 'int', width: 56 },
  { id: 'buy', header: 'Bought ₹Cr', accessor: 'buy_value_cr', format: 'num', digits: 0, width: 80 },
  { id: 'sell', header: 'Sold ₹Cr', accessor: 'sell_value_cr', format: 'num', digits: 0, width: 72 },
  { id: 'syms', header: 'Stocks', accessor: 'symbols', format: 'int', width: 56 },
  { id: 'rt', header: 'Round-trip %', accessor: 'round_trip_pct', format: 'pct', digits: 0, width: 84, headerTitle: 'Share of its stock-days with both a buy and a sell (churn behaviour)' },
  { id: 'flags', header: 'Flags', accessor: (r) => (r.churner ? 'churner' : r.ranked ? 'ranked' : null), width: 76, cell: (v) => <Chip tone={v === 'churner' ? 'warn' : 'info'}>{String(v)}</Chip> },
  { id: 'last', header: 'Last seen', accessor: 'last_date', format: 'date', width: 84 },
  { id: 'first', header: 'First seen', accessor: 'first_date', format: 'date', width: 84, defaultHidden: true },
];

function HousesView({ text, onHouse }: { text: string; onHouse: (h: string) => void }) {
  const [scope, setScope] = useUrlParam('hscope');
  const [hideChurn, setHideChurn] = useState(true);
  const session = scope !== 'all' && scope !== 'ranked';
  const q = useApiQuery('deals/houses', { query: { session_only: session, limit: 5000 } });
  const rows = useMemo(() => {
    const t = text.trim().toLowerCase();
    return (q.data?.rows ?? EMPTY_H).filter(
      (r) => (!hideChurn || !r.churner) && (scope !== 'ranked' || r.ranked) && (!t || r.house.toLowerCase().includes(t) || (r.session_symbols ?? []).some((s) => s.toLowerCase().includes(t))),
    );
  }, [q.data, text, hideChurn, scope]);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-8 shrink-0 items-center gap-3 border-b border-line bg-surface px-3 text-2xs text-fg-3">
        <Segmented
          size="xs"
          label="Houses shown"
          value={session ? 'session' : (scope as 'all' | 'ranked')}
          onChange={(v) => setScope(v === 'session' ? null : v)}
          options={[
            { value: 'session', label: 'Active this session' },
            { value: 'ranked', label: 'Ranked (≥ 5 bets)' },
            { value: 'all', label: 'All houses' },
          ]}
        />
        <label className="inline-flex items-center gap-1">
          <input type="checkbox" checked={hideChurn} onChange={(e) => setHideChurn(e.target.checked)} /> Hide churners / PROP
        </label>
        {q.data && q.data.rows.length > rows.length && <span className="text-fg-2">{q.data.rows.length - rows.length} hidden by filters</span>}
        <span>Track record: buy prints entered at the next open, returns at T+20 and vs NIFTY MIDSML 400. Individuals are never ranked as funds.</span>
      </div>
      <DataTable
        label="Deal houses"
        columns={houseColumns}
        rows={rows}
        total={q.data ? rows.length : null}
        getRowId={(r) => r.house}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        onRowClick={(r) => onHouse(r.house)}
        onRowActivate={(r) => onHouse(r.house)}
        emptyState={<EmptyState title="No houses" detail="Change the scope or untick 'Hide churners'." />}
        className="min-h-0 flex-1"
      />
    </div>
  );
}

function FollowView() {
  const [floor, setFloor] = useUrlParam('ffloor');
  const minMcap = floor === 'all' ? 0 : 1000;
  const q = useApiQuery('deals/followthrough', { query: { min_mcap_cr: minMcap } });
  const rows = q.data?.rows ?? [];
  const base = rows.find((r) => r.is_baseline);
  const ctx = q.data?.meta.context as { first_event?: string; last_event?: string; min_n?: number } | undefined;
  const cell = (r: FollowThroughRow, v: number | null | undefined, kind: 'pct' | 'signed' | 'hit') => {
    if (r.insufficient_sample) return <span className="text-fg-3">—</span>;
    if (kind === 'hit') return <span className="num">{fmtNum(v, 0)}%</span>;
    if (kind === 'signed') return <ZoneNum metricKey="deal_fwd_excess_t20" value={v} format="signed" digits={2} />;
    return <span className={cn('num', (v ?? 0) > 0 ? 'text-up' : (v ?? 0) < 0 ? 'text-down' : 'text-fg')}>{fmtSignedPct(v, 2)}</span>;
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto p-3">
      <div className="mb-2 flex flex-wrap items-center gap-3 text-2xs text-fg-3">
        <Segmented size="xs" label="Floor" value={floor === 'all' ? 'all' : '1000'} onChange={(v) => setFloor(v === '1000' ? null : v)} options={[{ value: '1000', label: '≥ ₹1,000 Cr' }, { value: 'all', label: 'All' }]} />
        <span>
          Events {fmtDate(ctx?.first_event ?? null)} → {fmtDate(ctx?.last_event ?? null)} · entry next open · exit close T+5 / T+20 · never past as-of · n &lt;{' '}
          {ctx?.min_n ?? 30} shows no numbers
        </span>
        <SourceNote meta={q.data?.meta} />
      </div>
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.isLoading ? (
        <Skeleton height={200} />
      ) : rows.length === 0 ? (
        <EmptyState title="No follow-through data" detail={q.data?.meta.reason ?? undefined} />
      ) : (
        <table className="w-full max-w-5xl border-collapse text-table">
          <thead>
            <tr className="border-b border-line text-left text-2xs uppercase tracking-wide text-fg-3">
              <th className="py-1 pr-3 font-medium">Event</th>
              <th className="pr-3 text-right font-medium">n (T+20)</th>
              <th className="pr-3 text-right font-medium">Avg T+5</th>
              <th className="pr-3 text-right font-medium">Avg T+20</th>
              <th className="pr-3 text-right font-medium">Median T+20</th>
              <th className="pr-3 text-right font-medium">Hit T+20</th>
              <th className="pr-3 text-right font-medium">vs index T+20</th>
              <th className="pr-3 text-right font-medium">vs baseline</th>
              <th className="font-medium">Rule</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const edge = !r.insufficient_sample && !r.is_baseline && base && r.avg_fwd_t20_pct != null && base.avg_fwd_t20_pct != null ? r.avg_fwd_t20_pct - base.avg_fwd_t20_pct : null;
              return (
                <tr key={r.event_type ?? 'x'} className={cn('border-b border-line/60 align-top', r.is_baseline && 'bg-surface-2')}>
                  <td className="py-1.5 pr-3">{r.is_baseline ? <Chip>Baseline</Chip> : <EventChip type={r.event_type} rule={r.rule} />}</td>
                  <td className="num pr-3 text-right">
                    {r.n}
                    {r.insufficient_sample && <div className="text-2xs text-warn">insufficient sample</div>}
                  </td>
                  <td className="pr-3 text-right">{cell(r, r.avg_fwd_t5_pct, 'pct')}</td>
                  <td className="pr-3 text-right">{cell(r, r.avg_fwd_t20_pct, 'pct')}</td>
                  <td className="pr-3 text-right">{cell(r, r.median_fwd_t20_pct, 'pct')}</td>
                  <td className="pr-3 text-right">{cell(r, r.hit_rate_t20, 'hit')}</td>
                  <td className="pr-3 text-right">{cell(r, r.avg_excess_t20_pct, 'signed')}</td>
                  <td className="num pr-3 text-right">{edge == null ? <span className="text-fg-3">—</span> : <span className={edge > 0 ? 'text-up' : 'text-down'}>{fmtSigned(edge, 2)}</span>}</td>
                  <td className="max-w-md text-2xs text-fg-3">{r.rule}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div className="mt-3 max-w-4xl rounded border border-line bg-surface-2 p-2 text-2xs text-fg-2">
        <b className="text-fg">Read this before acting on deals.</b> Deal history starts 2026-04-29, so samples are small and overlapping. The
        audit backtest found no standalone edge in FII/DII net buying ≥ 0.3× ADV (T+20 −3.14% vs baseline +2.08%, n = 21). Treat deals as
        context for a setup you already like, never as the reason to buy.
      </div>
    </div>
  );
}

export default function DealsRoute() {
  const [viewParam, setView] = useUrlParam('view');
  const [floorParam, setFloor] = useUrlParam('floor');
  const [asOf] = useAsOf();
  const [text, setText] = useState('');
  const [house, setHouse] = useState<string | null>(null);
  const view: View = viewParam === 'houses' || viewParam === 'follow' ? viewParam : 'session';
  const minMcap = floorParam === 'all' ? 0 : 1000;
  const q = useApiQuery('deals/session', { query: { min_mcap_cr: minMcap, limit: 5000 } });
  const ctx = q.data?.meta.context as
    | { deal_session?: string | null; no_records_for_session?: boolean; excluded_below_floor?: number; event_counts?: Record<string, number>; net_10s_dates?: (string | null)[] }
    | undefined;
  const rows = q.data?.rows ?? EMPTY;
  const dates = ctx?.net_10s_dates ?? [];
  const buySyms = useMemo(() => splitSession(rows).main.filter((r) => r.event_type === 'accumulate' || r.event_type === 'fresh').map((r) => r.symbol).filter((s): s is string => !!s), [rows]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line bg-surface px-3 py-1.5">
        <h1 className="text-sm font-semibold text-fg">Deals</h1>
        <Segmented
          label="Deals view"
          value={view}
          onChange={(v) => setView(v === 'session' ? null : v)}
          options={[
            { value: 'session', label: 'Session' },
            { value: 'houses', label: 'Houses' },
            { value: 'follow', label: 'Follow-through' },
          ]}
        />
        {view === 'session' && (
          <Segmented label="Market-cap floor" value={minMcap ? '1000' : 'all'} onChange={(v) => setFloor(v === '1000' ? null : v)} options={[{ value: '1000', label: '≥ ₹1,000 Cr' }, { value: 'all', label: 'All' }]} />
        )}
        {view !== 'follow' && (
          <input
            data-filter-input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={view === 'houses' ? 'Filter houses / stocks  /' : 'Filter symbol / name  /'}
            aria-label="Filter"
            className="h-6 w-44 rounded border border-line bg-surface-2 px-2 text-xs text-fg placeholder:text-fg-3 focus:border-focus focus:outline-none"
          />
        )}
        {ctx?.deal_session && (
          <span className="text-xs text-fg-2">
            Session <span className="num text-fg">{fmtDate(ctx.deal_session)}</span>
          </span>
        )}
        {ctx?.no_records_for_session && ctx.deal_session && (
          <Chip tone="warn" icon={<AlertTriangle className="h-3 w-3" />} title="No bulk/block deals were stored for the as-of session">
            NO RECORDS for {fmtDate(q.data?.as_of ?? null)} — showing {fmtDate(ctx.deal_session)}
          </Chip>
        )}
        {view === 'session' && ctx?.event_counts && (
          <span className="flex items-center gap-1">
            {(Object.keys(EVENTS) as EventType[])
              .filter((k) => ctx.event_counts?.[k])
              .map((k) => (
                <Chip key={k} tone={EVENTS[k].tone} title={EVENTS[k].short}>
                  {EVENTS[k].label} <span className="num">{ctx.event_counts?.[k]}</span>
                </Chip>
              ))}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {view === 'session' && ctx && (ctx.excluded_below_floor ?? 0) > 0 && (
            <span className="text-2xs text-fg-3" title="Stocks below the market-cap floor (or with unknown market cap) hidden">
              {ctx.excluded_below_floor} below floor hidden
            </span>
          )}
          {view === 'session' && <SourceNote meta={q.data?.meta} />}
          {view === 'session' && (
            <Link
              to={chartsDealsHref('buy', buySyms, asOf)}
              className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3"
              title="Open Accumulate + Fresh buyer stocks in Charts"
            >
              <LineChart className="h-3.5 w-3.5" /> Charts ({buySyms.length})
            </Link>
          )}
        </div>
      </div>
      {view === 'session' && (
        <div className="flex h-6 shrink-0 items-center gap-2 border-b border-line bg-surface px-3 text-2xs text-fg-3">
          <span>Prints collapsed (bulk ∩ block counted once) · net and events exclude PROP desks · deals are context, not a buy signal —</span>
          <button type="button" className="text-accent hover:underline" onClick={() => setView('follow')}>
            see follow-through
          </button>
        </div>
      )}
      {q.error && view === 'session' ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : view === 'session' ? (
        <SessionView rows={rows} dates={dates} text={text} dealDate={ctx?.deal_session ?? null} onHouse={setHouse} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} />
      ) : view === 'houses' ? (
        <HousesView text={text} onHouse={setHouse} />
      ) : (
        <FollowView />
      )}
      <HouseDrawer house={house} onClose={() => setHouse(null)} />
    </div>
  );
}
