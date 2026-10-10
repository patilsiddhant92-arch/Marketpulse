/**
 * The five Deals views (HarkPro/08-tab-deals.md, mockup v1.2): Today, Deal watch, History, Houses, By group.
 * Every list has "Copy N to TradingView" for the rows on screen; Houses (2 lists) adds "Copy every list".
 */
import { useMemo, useState } from 'react';
import { fmtDate, fmtNum } from '../../lib/fmt';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { StaticTable } from '../../ui/StaticTable';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { Skeleton } from '../../ui/Skeleton';
import { Segmented } from '../../ui/Segmented';
import {
  useDeals,
  type DealRow,
  type FundGroupRow,
  type GroupRow,
  type HistoryContext,
  type HistoryRow,
  type HouseRow,
  type HousesContext,
  type PatternKey,
  type TodayContext,
  type WatchContext,
} from './api';
import { Chips, DoLine, GradeChip, NotesLine, Panel, SessionCells, Signed, StatusChip, TvCopy, TvCopyAll, VerdictChip } from './kit';
import { useFollowedHouses } from './follows';
import { filterText, NOISE, shownValue, splitNoise, spreadSummary, verdictRank, type TvList } from './model';
import { SymbolWithDeal } from '../../ui/DealIcon';

export interface ViewProps {
  text: string;
  onStock: (sym: string) => void;
  onHouse: (house: string) => void;
}

const sym = (r: { symbol: string }) => r.symbol;

/** Rows in the table's current sort order (DataTable reports them after every sort / filter change). */
function useSorted<T>(rows: T[]): [T[], (r: T[]) => void] {
  const [sorted, setSorted] = useState<T[] | null>(null);
  return [sorted ?? rows, setSorted];
}

function Status({ q }: { q: { isLoading: boolean; error: unknown; refetch: () => unknown } }) {
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  return <Skeleton height={160} />;
}

function Unavailable({ reason }: { reason?: string | null }) {
  return <EmptyState title="No deals data for this date" detail={reason ?? 'The server has no deal sessions on or before this date.'} />;
}

const symbolCol: DataTableColumn<DealRow> = {
  id: 'symbol',
  header: 'Stock',
  accessor: 'symbol',
  width: 150,
  sticky: true,
  cell: (_v, r) => (
    <span className="flex min-w-0 flex-col leading-tight">
      <SymbolWithDeal symbol={r.symbol} />
      <span className="truncate text-2xs text-fg-3">{r.industry ?? ''}</span>
    </span>
  ),
};
const verdictCol: DataTableColumn<DealRow> = {
  id: 'verdict',
  header: 'Verdict',
  accessor: (r) => verdictRank(r.verdict),
  sortDescFirst: false,
  width: 230,
  cell: (_v, r) => <VerdictChip verdict={r.verdict} title={r.verdict_title} />,
};
const chipsCol: DataTableColumn<DealRow> = { id: 'chips', header: 'Chips', accessor: (r) => r.chips.length, width: 230, grow: true, cell: (_v, r) => <Chips chips={r.chips} /> };

// ------------------------------------------------------------------ Today
export function TodayView({ text, onStock }: ViewProps) {
  const q = useDeals<DealRow, TodayContext>('deals/tab/today');
  const [noise, setNoise] = useState(false);
  const ctx = q.data?.meta.context ?? undefined;
  const all = useMemo(() => filterText(q.data?.rows ?? [], text), [q.data, text]);
  const { main, noise: nz } = useMemo(() => splitNoise(all), [all]);
  const rows = noise ? all : main;
  const [sorted, setSorted] = useSorted(rows);
  const cols = useMemo<DataTableColumn<DealRow>[]>(
    () => [
      symbolCol,
      verdictCol,
      { id: 'type', header: 'Type', accessor: 'event_label', width: 120 },
      {
        id: 'value',
        header: '₹ Cr',
        accessor: (r) => shownValue(r).value,
        width: 96,
        headerTitle: 'Net ex-PROP ₹ Cr. Placements and near-zero nets show the value bought.',
        cell: (_v, r) => {
          const s = shownValue(r);
          return (
            <span>
              <Signed value={s.value} />
              {s.bought && <span className="ml-1 text-2xs text-fg-3">bought</span>}
            </span>
          );
        },
      },
      { id: 'price', header: 'Deal price', accessor: 'deal_price', format: 'num', digits: 2, width: 90 },
      { id: 'vs', header: 'vs close', accessor: 'vs_deal_pct', width: 80, cell: (v) => <Signed value={v as number} pct /> },
      {
        id: 'buyer',
        header: 'Main buyer',
        accessor: (r) => r.buyers[0]?.name ?? null,
        width: 190,
        cell: (_v, r) =>
          r.buyers[0] ? (
            <span className="truncate">
              {r.buyers[0].name} <span className="text-2xs text-fg-3">{r.buyers[0].buyer_class}</span>
            </span>
          ) : null,
      },
      chipsCol,
    ],
    [],
  );
  if (!q.data) return <Status q={q} />;
  if (q.data.meta.status === 'unavailable') return <Unavailable reason={q.data.meta.reason} />;
  const s = ctx?.summary;
  const list: TvList = { title: `Deals Today ${ctx?.deal_session ?? ''}${noise ? ' incl noise' : ''}`, symbols: sorted.map(sym) };
  return (
    <div className="space-y-3">
      {s && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5" aria-label="Today summary">
          {[
            ['Confirms a setup', s.confirms, 'text-up'],
            ['Placements', s.placements, 'text-info'],
            ['Supply to watch', s.supply, 'text-warn'],
            ['Avoid', s.avoid, 'text-down'],
            ['Noise (churn, transfers, no edge)', s.noise, 'text-fg-3'],
          ].map(([l, n, c]) => (
            <div key={String(l)} className="rounded-card border border-line bg-surface px-3 py-2">
              <div className={`num text-lg font-semibold ${c}`}>{n}</div>
              <div className="text-2xs text-fg-3">{l}</div>
            </div>
          ))}
        </div>
      )}
      <Panel
        title="Every deal stock today"
        sub={
          <>
            Session {fmtDate(ctx?.deal_session ?? null)}. Sorted by what matters.
            {ctx?.above50_pct != null && ` ${ctx.above50_pct}% of stocks ≥ ₹1,000 Cr are above their 50-day average.`}
            {ctx?.skipped && ` Skipped ${ctx.skipped.small} stocks under ₹1,000 Cr.`} Tap a row for the chart.
          </>
        }
        actions={<TvCopy list={list} />}
      >
        <div className="h-[460px]">
          <DataTable
            label="Deals today"
            columns={cols}
            rows={rows}
            getRowId={(r) => `${r.symbol}:${r.deal_date}`}
            onRowClick={(r) => onStock(r.symbol)}
            onRowActivate={(r) => onStock(r.symbol)}
            onSortedRowsChange={setSorted}
            emptyState={<EmptyState title="No deal stocks in this view" detail={nz.length ? `${nz.length} noise rows are hidden.` : undefined} />}
          />
        </div>
        <div className="flex items-center gap-2 border-t border-line px-3 py-1.5">
          <button type="button" className="text-xs text-accent hover:underline" onClick={() => setNoise((v) => !v)} disabled={!nz.length}>
            {noise ? 'Hide' : 'Show'} {nz.length} noise rows ({NOISE.join(', ')})
          </button>
        </div>
      </Panel>
      <NotesLine notes={q.data.meta.notes} />
    </div>
  );
}

// ------------------------------------------------------------------ Deal watch
type WatchFilter = 'all' | 'best' | 'holding' | 'lost' | 'reclaimed';
export function WatchView({ text, onStock }: ViewProps) {
  const [f, setF] = useState<WatchFilter>('all');
  const q = useDeals<DealRow, WatchContext>('deals/tab/watch', { status: f });
  const rows = useMemo(() => filterText(q.data?.rows ?? [], text), [q.data, text]);
  const [sorted, setSorted] = useSorted(rows);
  const counts = q.data?.meta.context?.filter_counts ?? {};
  const cols = useMemo<DataTableColumn<DealRow>[]>(
    () => [
      { ...symbolCol, cell: (_v, r) => (<span className="flex flex-col leading-tight"><SymbolWithDeal symbol={r.symbol} /><span className="text-2xs text-fg-3">{fmtDate(r.deal_date)} · {r.event_label}</span></span>) },
      verdictCol,
      { id: 'status', header: 'Status', accessor: 'status', width: 120, cell: (_v, r) => <StatusChip status={r.status} /> },
      { id: 'days', header: 'Days', accessor: 'sessions_since', format: 'int', width: 56, headerTitle: 'Price sessions since the deal' },
      { id: 'price', header: 'Deal price', accessor: 'deal_price', format: 'num', digits: 2, width: 90 },
      { id: 'now', header: 'Now', accessor: 'close', format: 'num', digits: 2, width: 84 },
      { id: 'vs', header: 'vs deal', accessor: 'vs_deal_pct', width: 80, cell: (v) => <Signed value={v as number} pct /> },
      chipsCol,
    ],
    [],
  );
  const opts: { value: WatchFilter; label: string }[] = (['all', 'best', 'holding', 'lost', 'reclaimed'] as const).map((k) => ({
    value: k,
    label: `${k[0].toUpperCase()}${k.slice(1)}${counts[k] != null ? ` ${counts[k]}` : ''}`,
  }));
  if (!q.data) return <Status q={q} />;
  if (q.data.meta.status === 'unavailable') return <Unavailable reason={q.data.meta.reason} />;
  return (
    <div className="space-y-3">
      <Panel
        title="Deal watch · last 10 deal sessions"
        sub="The deal price is a level. Day 3 decides: holding it upgrades the verdict, losing it downgrades it. Churn and transfers are left out."
        actions={
          <>
            <Segmented size="xs" label="Watch filter" value={f} onChange={setF} options={opts} />
            <TvCopy list={{ title: `Deal watch ${f}`, symbols: sorted.map(sym) }} />
          </>
        }
      >
        <div className="h-[520px]">
          <DataTable
            label="Deal watch"
            columns={cols}
            rows={rows}
            getRowId={(r) => r.symbol}
            onRowClick={(r) => onStock(r.symbol)}
            onRowActivate={(r) => onStock(r.symbol)}
            onSortedRowsChange={setSorted}
            emptyState={<EmptyState title="No stocks match this filter" />}
          />
        </div>
      </Panel>
      <NotesLine notes={q.data.meta.notes} />
    </div>
  );
}

// ------------------------------------------------------------------ History
export function HistoryView({ text, onStock }: ViewProps) {
  const [n, setN] = useState<'5' | '10' | '20'>('10');
  const [pat, setPat] = useState<'all' | PatternKey>('all');
  const q = useDeals<HistoryRow, HistoryContext>('deals/tab/history', { sessions: Number(n), pattern: pat });
  const ctx = q.data?.meta.context ?? undefined;
  const dates = ctx?.sessions ?? [];
  const rows = useMemo(() => filterText(q.data?.rows ?? [], text), [q.data, text]);
  const [sorted, setSorted] = useSorted(rows);
  const cols = useMemo<DataTableColumn<HistoryRow>[]>(
    () => [
      { id: 'symbol', header: 'Stock', accessor: 'symbol', width: 130, sticky: true, cell: (_v, r) => (<span className="flex flex-col leading-tight"><SymbolWithDeal symbol={r.symbol} /><span className="truncate text-2xs text-fg-3">{r.industry ?? ''}</span></span>) },
      { id: 'pattern', header: 'Pattern', accessor: 'pattern_label', width: 170 },
      { id: 'cells', header: 'Sessions', accessor: (r) => r.buy_sessions + r.sell_sessions, width: Number(n) > 10 ? 250 : 170, sortable: false, cell: (_v, r) => <SessionCells cells={r.cells} dates={dates} /> },
      { id: 'buy', header: 'Buy', accessor: 'buy_sessions', format: 'int', width: 50 },
      { id: 'sell', header: 'Sell', accessor: 'sell_sessions', format: 'int', width: 50 },
      { id: 'net', header: 'Net ₹ Cr', accessor: 'net_cr', width: 84, cell: (v) => <Signed value={v as number} /> },
      { id: 'prop', header: 'Prop ₹ Cr', accessor: 'prop_cr', format: 'num', digits: 1, width: 80 },
      { id: 'lvl', header: 'Avg deal price', accessor: 'avg_deal_price', format: 'num', digits: 2, width: 100 },
      { id: 'vs', header: 'Now vs deal', accessor: 'vs_deal_pct', width: 90, cell: (v) => <Signed value={v as number} pct /> },
    ],
    [dates, n],
  );
  const counts = ctx?.pattern_counts;
  const patterns = ctx?.patterns ?? [];
  if (!q.data) return <Status q={q} />;
  if (q.data.meta.status === 'unavailable') return <Unavailable reason={q.data.meta.reason} />;
  const note = patterns.find((p) => p.key === pat)?.note;
  const label = pat === 'all' ? 'all patterns' : (patterns.find((p) => p.key === pat)?.label ?? pat);
  return (
    <div className="space-y-3">
      <Panel
        title={`Deal history · last ${n} deal sessions`}
        sub="Every stock ≥ ₹1,000 Cr with a deal, including churn, prop desks and transfers. One square per session, oldest first."
        actions={
          <>
            <Segmented size="xs" label="Deal sessions" value={n} onChange={setN} options={(['5', '10', '20'] as const).map((k) => ({ value: k, label: `${k} sessions` }))} />
            <TvCopy list={{ title: `Deal history ${n} sessions ${label}`, symbols: sorted.map(sym) }} />
          </>
        }
      >
        <div className="flex flex-wrap gap-1 border-b border-line px-3 py-1.5">
          <Chip selected={pat === 'all'} onClick={() => setPat('all')}>
            All {ctx?.total ?? ''}
          </Chip>
          {patterns.map((p) => (
            <Chip key={p.key} selected={pat === p.key} onClick={() => setPat(p.key)} title={p.note}>
              {p.label} {counts?.[p.key] ?? 0}
            </Chip>
          ))}
        </div>
        {note && (
          <div className="px-3 pt-2">
            <DoLine>{note}</DoLine>
          </div>
        )}
        <div className="h-[500px]">
          <DataTable label="Deal history" columns={cols} rows={rows} getRowId={sym} onRowClick={(r) => onStock(r.symbol)} onRowActivate={(r) => onStock(r.symbol)} onSortedRowsChange={setSorted} emptyState={<EmptyState title="No stocks with this pattern" />} />
        </div>
      </Panel>
      <NotesLine notes={q.data.meta.notes} />
    </div>
  );
}

// ------------------------------------------------------------------ Houses
export function HousesView({ text, onStock, onHouse }: ViewProps) {
  const q = useDeals<HouseRow, HousesContext>('deals/tab/houses');
  const ctx = q.data?.meta.context ?? undefined;
  const follows = useFollowedHouses();
  const followed = follows.followed;
  const toggleFollow = follows.toggle;
  const [onlyFollowed, setOnlyFollowed] = useState(false);
  const s = text.trim().toUpperCase();
  const rows = useMemo(() => {
    const all = q.data?.rows ?? [];
    return all.filter((h) => (!s || h.house.includes(s) || h.symbols.some((x) => x.includes(s))) && (!onlyFollowed || followed.includes(h.house)));
  }, [q.data, s, onlyFollowed, followed]);
  const fund = useMemo(() => (ctx?.fund_groups ?? []).filter((g) => !s || g.industry.toUpperCase().includes(s) || g.symbols.some((x) => x.includes(s))), [ctx, s]);
  const [sorted, setSorted] = useSorted(rows);
  const [fundSorted, setFundSorted] = useSorted(fund);
  const houseCols = useMemo<DataTableColumn<HouseRow>[]>(
    () => [
      { id: 'house', header: 'House', accessor: 'name', width: 200, sticky: true, cell: (_v, r) => <button type="button" className="truncate text-left font-medium text-fg hover:underline" onClick={(e) => { e.stopPropagation(); onHouse(r.house); }}>{r.name}</button> },
      { id: 'cls', header: 'Class', accessor: 'buyer_class', width: 90 },
      { id: 'v', header: 'Bought ₹ Cr', accessor: 'bought_cr', format: 'num', digits: 1, width: 96 },
      { id: 'grade', header: 'Grade', accessor: 'grade', width: 84, cell: (_v, r) => <GradeChip grade={r.grade} cls={r.buyer_class} /> },
      { id: 'n', header: 'Past trades', accessor: 'record_n', format: 'int', width: 80, headerTitle: 'Finished trades (exit on or before the as-of date)' },
      { id: 'avg', header: 'Avg vs mkt', accessor: 'record_avg_pct', width: 84, cell: (v) => <Signed value={v as number} pct /> },
      { id: 'beat', header: 'Beat %', accessor: 'record_beat_pct', format: 'num', digits: 0, width: 64 },
      {
        id: 'spread',
        header: 'Spread across groups',
        accessor: (r) => r.spread.length,
        width: 240,
        cell: (_v, r) => {
          const sp = spreadSummary(r.spread);
          return (
            <span className="flex items-center gap-1">
              <span className="text-2xs text-fg-3">{sp.groups} group{sp.groups === 1 ? '' : 's'}</span>
              {sp.top.map((t) => (
                <Chip key={t.label}>{`${t.label} ${t.pct}%`}</Chip>
              ))}
            </span>
          );
        },
      },
      { id: 'syms', header: 'Stocks', accessor: (r) => r.symbols.join(', '), width: 200, grow: true },
      {
        id: 'follow',
        header: '',
        accessor: (r) => (followed.includes(r.house) ? 1 : 0),
        width: 86,
        sortable: false,
        cell: (_v, r) => (
          <button type="button" className="rounded border border-line px-2 py-0.5 text-2xs text-fg-2 hover:bg-surface-3" onClick={(e) => { e.stopPropagation(); toggleFollow(r.house, r.name); }}>
            {followed.includes(r.house) ? 'Following' : 'Follow'}
          </button>
        ),
      },
    ],
    [followed, toggleFollow, onHouse],
  );
  const fundCols = useMemo<DataTableColumn<FundGroupRow>[]>(
    () => [
      { id: 'ind', header: 'Industry', accessor: 'industry', width: 220, sticky: true },
      { id: 'houses', header: 'Houses', accessor: 'houses', format: 'int', width: 70 },
      { id: 'fii', header: 'FII ₹ Cr', accessor: 'fii_cr', format: 'num', digits: 1, width: 90 },
      { id: 'dii', header: 'DII ₹ Cr', accessor: 'dii_cr', format: 'num', digits: 1, width: 90 },
      {
        id: 'syms',
        header: 'Stocks',
        accessor: (r) => r.symbols.join(', '),
        width: 260,
        grow: true,
        cell: (_v, r) => (
          <span className="flex flex-wrap gap-1">
            {r.symbols.map((x) => (
              <button key={x} type="button" className="font-mono text-fg hover:underline" onClick={(e) => { e.stopPropagation(); onStock(x); }}>
                {x}
              </button>
            ))}
          </span>
        ),
      },
    ],
    [onStock],
  );
  if (!q.data) return <Status q={q} />;
  if (q.data.meta.status === 'unavailable') return <Unavailable reason={q.data.meta.reason} />;
  const fundList: TvList = { title: 'Where FII DII money went by group', symbols: fundSorted.flatMap((g) => g.symbols) };
  const houseList: TvList = { title: onlyFollowed ? 'Followed houses buying' : 'Houses buying in the window', symbols: sorted.flatMap((h) => h.symbols) };
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <TvCopyAll lists={[fundList, houseList]} />
      </div>
      <Panel title="Who is buying matters more than their record" sub="Buys of ₹5 Cr or more, 20 sessions later vs the market, NSE history Apr 2024 to Jul 2026.">
        <StaticTable
          className="max-w-xl"
          label="Buyer class record"
          rows={ctx?.class_evidence ?? []}
          rowKey={(c) => c.buyer_class}
          columns={[
            { id: 'cls', header: 'Buyer class', cell: (c) => c.buyer_class },
            { id: 'n', header: 'Deals', align: 'right', cell: (c) => c.n.toLocaleString('en-IN') },
            { id: 'vs', header: 'vs market', align: 'right', cell: (c) => <Signed value={c.vs_market_pct} pct /> },
            { id: 'beat', header: 'Beat %', align: 'right', cell: (c) => `${c.beat_pct}%` },
          ]}
        />
        <div className="p-3">
          <DoLine>
            Grades show for FII/DII only, from finished trades before the as-of date. {ctx?.graded_houses ?? 0} houses are graded from {ctx?.finished_bets ?? 0} finished
            trades in this database (deal history from {fmtDate(ctx?.first_deal ?? null)}). Telegram alerts fire only when a followed FII/DII house with a good record buys a strong chart (day 0, then day 3 holding or lost).
          </DoLine>
        </div>
      </Panel>
      <Panel title="Where FII/DII money went · by group" sub="Non-prop FII and DII buys in the last 10 deal sessions, by industry. Many houses in one group means broad interest, not one desk. Context only." actions={<TvCopy list={fundList} />}>
        <div className="h-[300px]">
          <DataTable label="FII/DII money by group" columns={fundCols} rows={fund} getRowId={(r) => r.industry} onSortedRowsChange={setFundSorted} emptyState={<EmptyState title="No FII or DII buys in the window" />} />
        </div>
      </Panel>
      <Panel
        title="Houses buying in the window"
        sub={`${followed.length} followed. Follows are saved on this machine and drive the Telegram “Followed houses” alerts (good-record FII/DII buying a strong chart only).`}
        actions={
          <>
            <Segmented size="xs" label="Houses shown" value={onlyFollowed ? 'followed' : 'all'} onChange={(v) => setOnlyFollowed(v === 'followed')} options={[{ value: 'all', label: 'All' }, { value: 'followed', label: `Followed ${followed.length}` }]} />
            <TvCopy list={houseList} />
          </>
        }
      >
        <div className="h-[460px]">
          <DataTable label="Houses buying" columns={houseCols} rows={rows} getRowId={(r) => r.house} onRowClick={(r) => onHouse(r.house)} onRowActivate={(r) => onHouse(r.house)} onSortedRowsChange={setSorted} emptyState={<EmptyState title={onlyFollowed ? 'No followed house bought in the window' : 'No houses bought in the window'} />} />
        </div>
      </Panel>
      <NotesLine notes={q.data.meta.notes} />
    </div>
  );
}

// ------------------------------------------------------------------ By group
export function GroupsView({ text, onStock }: ViewProps) {
  const q = useDeals<GroupRow>('deals/tab/groups');
  const s = text.trim().toUpperCase();
  const rows = useMemo(() => (q.data?.rows ?? []).filter((g) => !s || g.industry.toUpperCase().includes(s) || g.symbols.some((x) => x.includes(s))), [q.data, s]);
  const [sorted, setSorted] = useSorted(rows);
  const cols = useMemo<DataTableColumn<GroupRow>[]>(
    () => [
      { id: 'ind', header: 'Industry', accessor: 'industry', width: 240, sticky: true, cell: (_v, r) => (<span className="flex items-center gap-1"><span className="truncate font-medium text-fg">{r.industry}</span>{r.three_plus_buyers && <Chip tone="positive">3+ buyers</Chip>}</span>) },
      { id: 'sec', header: 'Sector', accessor: 'sector', width: 140 },
      { id: 'b', header: 'Buying names', accessor: 'buying_names', format: 'int', width: 96 },
      { id: 's', header: 'Selling names', accessor: 'selling_names', format: 'int', width: 96 },
      { id: 'flow', header: 'Net ₹ Cr', accessor: 'flow_cr', width: 90, cell: (v) => <Signed value={v as number} /> },
      {
        id: 'syms',
        header: 'Stocks',
        accessor: (r) => r.symbols.join(', '),
        width: 280,
        grow: true,
        cell: (_v, r) => (
          <span className="flex flex-wrap gap-1">
            {r.symbols.map((x) => (
              <button key={x} type="button" className="font-mono text-fg hover:underline" onClick={(e) => { e.stopPropagation(); onStock(x); }}>
                {x}
              </button>
            ))}
          </span>
        ),
      },
    ],
    [onStock],
  );
  if (!q.data) return <Status q={q} />;
  if (q.data.meta.status === 'unavailable') return <Unavailable reason={q.data.meta.reason} />;
  return (
    <div className="space-y-3">
      <Panel title="Deals by industry · last 10 deal sessions" sub="Transfers and churn excluded. Context only: 3+ buying names in one group beat the market by only 0.7% over 20 sessions." actions={<TvCopy list={{ title: 'Deals by group 10 sessions', symbols: sorted.flatMap((g) => g.symbols) }} />}>
        <div className="h-[520px]">
          <DataTable label="Deals by group" columns={cols} rows={rows} getRowId={(r) => r.industry} onSortedRowsChange={setSorted} emptyState={<EmptyState title="No deal groups in the window" />} />
        </div>
      </Panel>
      <NotesLine notes={q.data.meta.notes} />
    </div>
  );
}

export function fmtCr(v: number | null | undefined): string {
  return v == null ? '–' : `₹${fmtNum(Math.abs(v), 1)} Cr`;
}
