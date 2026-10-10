/** §8 Groups table, §9 Stocks that moved, §10 Days like today. */
import { useMemo, useState } from 'react';
import { applyGroupState, useGroupState } from '../../context/groupState';
import { useShell } from '../../shell/ShellContext';
import { Chip, type ChipTone } from '../../ui/Chip';
import { DataTable, type DataTableColumn, type SortSpec } from '../../ui/DataTable';
import { DataWarningChip } from '../../ui/DataWarningChip';
import { GroupStateChip } from '../../ui/GroupState';
import { Panel } from '../../ui/Panel';
import { Spark } from '../../ui/Spark';
import { QuadrantChip, Segmented } from '../groups/kit';
import type { GroupLevel, PulseResult } from './data';
import { fixed, intIN, isNum, longDate, median, signed, sortBy, toneClass } from './model';
import { Note, SectionBody } from './parts';
import type { AnalogContext, AnalogRow, ChipCode, GroupRow, IndexRow, MoverKind, MoverRow } from './types';
import { DealIcon } from '../../ui/DealIcon';

const pctCell = (v: unknown) => <span className={toneClass(v as number)}>{signed(v as number, 1)}</span>;

// ------------------------------------------------------------------ groups

export const GROUP_LEVELS = [
  { value: 'sector', label: 'Sector' },
  { value: 'industry', label: 'Industry' },
  { value: 'sectoral', label: 'Sectoral index', title: '16 official NSE sectoral indices' },
  { value: 'thematic', label: 'Thematic index', title: '28 official NSE thematic indices' },
] as const;

const GROUP_COLUMNS: DataTableColumn<GroupRow>[] = [
  { id: 'name', header: 'Group', accessor: 'name', width: 180, sticky: true, grow: true },
  {
    id: 'state',
    header: 'State',
    accessor: (r) => (r.state === 'Favour' ? 0 : r.state === 'Neutral' ? 1 : r.state === 'Caution' ? 2 : null),
    width: 84,
    sortDescFirst: false,
    headerTitle: 'Group state (Favour / Neutral / Caution), the one state every tab shows. Hover for the reason.',
    cell: (_v, r) => <GroupStateChip state={r.state} reason={r.state_reason} />,
  },
  { id: 'members', header: 'Stocks', accessor: 'members', format: 'int', width: 56 },
  { id: 'ret_1d_pct', header: '1D %', accessor: 'ret_1d_pct', width: 60, cell: pctCell },
  { id: 'ret_1w_pct', header: '1W %', accessor: 'ret_1w_pct', width: 60, cell: pctCell },
  { id: 'ret_1m_pct', header: '1M %', accessor: 'ret_1m_pct', width: 60, cell: pctCell },
  { id: 'ret_3m_pct', header: '3M %', accessor: 'ret_3m_pct', width: 60, cell: pctCell },
  { id: 'turnover_cr', header: 'Turnover ₹Cr', accessor: 'turnover_cr', format: 'int', width: 92 },
  { id: 'share_pct', header: 'Share %', accessor: 'share_pct', format: 'num', digits: 1, width: 64 },
  { id: 'share_delta', header: 'Δ share', accessor: 'share_delta', width: 64, cell: (v) => <span className={toneClass(v as number)}>{signed(v as number, 2)}</span>, headerTitle: 'Turnover share minus its 20-day average (points)' },
  { id: 'delivered_cr', header: 'Delivered ₹Cr', accessor: 'delivered_cr', format: 'int', width: 92 },
  { id: 'pct_above_50ema', header: '> 50 EMA', accessor: 'pct_above_50ema', width: 70, cell: (v) => `${fixed(v as number, 0)}%` },
  { id: 'rank', header: 'Rank', accessor: 'rank', format: 'int', width: 52, sortDescFirst: false },
  { id: 'rank_gain_1w', header: 'Rank Δ 1W', accessor: 'rank_gain_1w', width: 70, cell: (v) => <span className={toneClass(v as number)}>{signed(v as number, 0)}</span>, headerTitle: 'Places gained in rank over 1 week (+ = better)' },
  { id: 'rrg_quadrant', header: 'RRG', accessor: 'rrg_quadrant', width: 96, cell: (v, r) => <QuadrantChip quadrant={v as string} days={r.days_in_quadrant} /> },
  { id: 'deal_net_10s_cr', header: 'Deals ₹Cr', accessor: 'deal_net_10s_cr', width: 72, cell: (v) => <span className={toneClass(v as number)}>{signed(v as number, 0)}</span>, headerTitle: 'Net bulk/block deal value, last 10 sessions' },
  { id: 'share_history', header: 'Share 3M', accessor: (r) => r.share_history?.[r.share_history.length - 1] ?? null, width: 96, sortable: false, cell: (_v, r) => <Spark values={r.share_history} width={84} height={18} tone="accent" label={`${r.name} turnover share, 3 months`} />, renderNull: true },
];

const TREND_TONE: Record<string, string> = { Constructive: 'text-up', Strong: 'text-up', Uptrend: 'text-up', Neutral: 'text-fg-3', Weak: 'text-down', Downtrend: 'text-down' };

const INDEX_COLUMNS: DataTableColumn<IndexRow>[] = [
  { id: 'name', header: 'Index', accessor: 'name', width: 180, sticky: true, grow: true, cell: (v, r) => (
    <span className="inline-flex items-center gap-1">
      {String(v)}
      {r.new_52w_high && <Chip tone="positive">52W</Chip>}
    </span>
  ) },
  { id: 'close', header: 'Close', accessor: 'close', format: 'num', digits: 1, width: 80 },
  { id: 'ret_1d_pct', header: '1D %', accessor: 'ret_1d_pct', width: 60, cell: pctCell },
  { id: 'ret_1w_pct', header: '1W %', accessor: 'ret_1w_pct', width: 60, cell: pctCell },
  { id: 'ret_1m_pct', header: '1M %', accessor: 'ret_1m_pct', width: 60, cell: pctCell },
  { id: 'ret_3m_pct', header: '3M %', accessor: 'ret_3m_pct', width: 60, cell: pctCell },
  { id: 'vs_20ema_pct', header: 'vs 20 EMA', accessor: 'vs_20ema_pct', width: 72, cell: (v) => <span className={toneClass(v as number)}>{signed(v as number, 1)}%</span> },
  { id: 'vs_50ema_pct', header: 'vs 50 EMA', accessor: 'vs_50ema_pct', width: 72, cell: (v) => <span className={toneClass(v as number)}>{signed(v as number, 1)}%</span> },
  { id: 'trend_state', header: 'Trend', accessor: 'trend_state', width: 96, cell: (v) => <span className={TREND_TONE[String(v)] ?? 'text-fg-2'}>{String(v)}</span> },
  { id: 'close_history', header: '30 sessions', accessor: (r) => r.ret_1m_pct, width: 110, sortable: false, renderNull: true, cell: (_v, r) => <Spark values={r.close_history} width={96} height={18} label={`${r.name}, 30 sessions`} /> },
];

export function GroupsTable({ q, level, onLevel }: { q: PulseResult<GroupRow | IndexRow, { data_warning?: string | null }>; level: GroupLevel; onLevel: (l: GroupLevel) => void }) {
  const isIndex = level === 'sectoral' || level === 'thematic';
  const [sorting, setSorting] = useState<SortSpec[]>([{ id: 'share_delta', desc: true }]);
  const [ixSorting, setIxSorting] = useState<SortSpec[]>([{ id: 'ret_1d_pct', desc: true }]);
  // Pulse owns the group state: the same source Sector Intel and Setups read (context/groupState.ts).
  const shared = useGroupState(isIndex ? null : level);
  const groupRows = useMemo(() => {
    const raw = (q.rows ?? []) as GroupRow[];
    if (isIndex || !raw.length || !('share_history' in raw[0])) return [];
    const rows = applyGroupState(raw, shared.map, (r) => r.name, (r, g) => ({ ...r, state: g.state, state_reason: g.reason }));
    const s = sorting[0];
    const col = GROUP_COLUMNS.find((c) => c.id === s?.id);
    const get = col && typeof col.accessor !== 'function' ? (r: GroupRow) => r[col.accessor as keyof GroupRow] : (r: GroupRow) => r.share_delta;
    const sorted = s ? sortBy(rows, get, s.desc ? -1 : 1) : rows;
    return level === 'industry' ? sorted.slice(0, 40) : sorted;
  }, [q.rows, isIndex, sorting, level, shared.map]);
  const indexRows = isIndex && q.rows?.length && 'close_history' in (q.rows[0] as IndexRow) ? (q.rows as IndexRow[]) : [];
  return (
    <Panel
      title="Groups"
      meta={isIndex ? 'Official NSE indices' : level === 'industry' ? `Top 40 of ${q.rows?.length ?? 0} by the sort column · all stocks, equal weight` : 'All stocks, equal weight'}
      actions={
        <span className="inline-flex items-center gap-2">
          <DataWarningChip warning={q.ctx?.data_warning} />
          <Segmented label="Group level" size="xs" options={GROUP_LEVELS} value={level} onChange={onLevel} />
        </span>
      }
    >
      <SectionBody q={q} rows={6} emptyTitle="No group rows for this session">
        <div className="h-[440px]">
          {isIndex ? (
            <DataTable<IndexRow> label="Index table" columns={INDEX_COLUMNS} rows={indexRows} getRowId={(r) => r.name} sorting={ixSorting} onSortingChange={setIxSorting} hideToolbar className="h-full" />
          ) : (
            <DataTable<GroupRow> label="Groups table" columns={GROUP_COLUMNS} rows={groupRows} getRowId={(r) => r.name} sorting={sorting} onSortingChange={setSorting} hideToolbar className="h-full" />
          )}
        </div>
      </SectionBody>
    </Panel>
  );
}

// ------------------------------------------------------------------ movers

export const MOVER_KINDS: readonly { value: MoverKind; label: string; title?: string }[] = [
  { value: 'gainers', label: 'Gainers' },
  { value: 'losers', label: 'Losers' },
  { value: 'turnover', label: 'Turnover' },
  { value: 'delivered', label: 'Delivered ₹' },
  { value: 'rvol', label: 'Volume surge', title: 'Highest RVOL with turnover ≥ ₹5 Cr' },
];

const CHIP_TONE: Record<ChipCode, ChipTone> = { DEAL: 'info', '52W': 'positive', IPO: 'violet', BAND: 'warn', EXT: 'negative', RES: 'accent', NEWS: 'neutral' };

export function EventChips({ chips, rules, band }: { chips: ChipCode[]; rules?: Record<string, string>; band?: string | null }) {
  return (
    <span className="inline-flex gap-0.5">
      {chips.map((c) => (
        <Chip key={c} tone={CHIP_TONE[c]} title={c === 'BAND' && band ? band : rules?.[c]}>
          {c}
        </Chip>
      ))}
    </span>
  );
}

function moverColumns(rules: Record<string, string> | undefined): DataTableColumn<MoverRow>[] {
  return [
    { id: 'symbol', header: 'Stock', accessor: 'symbol', width: 200, sticky: true, cell: (v, r) => (
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="inline-flex items-center gap-1">
          <b className="font-mono text-fg">{String(v)}</b>
          <DealIcon symbol={String(v)} />
          <EventChips chips={r.chips} rules={rules} band={r.band_remark} />
        </span>
        <span className="truncate text-2xs text-fg-3">{r.name}</span>
      </span>
    ) },
    { id: 'sector', header: 'Sector', accessor: 'sector', width: 130 },
    { id: 'close', header: 'Close', accessor: 'close', format: 'num', digits: 1, width: 70 },
    { id: 'chg_1d_pct', header: '1D %', accessor: 'chg_1d_pct', width: 60, cell: pctCell },
    { id: 'ret_1w_pct', header: '1W %', accessor: 'ret_1w_pct', width: 60, cell: pctCell },
    { id: 'ret_1m_pct', header: '1M %', accessor: 'ret_1m_pct', width: 60, cell: pctCell },
    { id: 'turnover_cr', header: 'Turnover ₹Cr', accessor: 'turnover_cr', format: 'num', digits: 0, width: 88 },
    { id: 'rvol', header: 'RVOL', accessor: 'rvol', width: 56, cell: (v) => <span className={(v as number) >= 2 ? 'text-warn' : ''}>{fixed(v as number, 1)}×</span> },
    { id: 'delivered_cr', header: 'Delivered ₹Cr', accessor: 'delivered_cr', format: 'num', digits: 0, width: 88 },
    { id: 'delivery_pct', header: 'Deliv % vs 20D', accessor: 'delivery_pct', width: 100, cell: (v, r) => {
      const x = r.delivery_vs_20d;
      return (
        <span className={isNum(x) && x >= 1.3 ? 'text-up' : isNum(x) && x < 0.7 ? 'text-down' : 'text-fg-2'}>
          {fixed(v as number, 0)}% <span className="text-2xs text-fg-3">{isNum(x) ? `${x.toFixed(1)}×` : ''}</span>
        </span>
      );
    } },
    { id: 'rs_percentile', header: 'RS', accessor: 'rs_percentile', format: 'int', width: 48 },
    { id: 'mcap_cr', header: 'Mcap ₹Cr', accessor: 'mcap_cr', width: 88, cell: (v, r) => <span className="text-fg-3" title={r.mcap_basis === 'latest' ? 'Latest market cap (no as-of value)' : undefined}>{intIN(v as number)}{r.mcap_basis === 'latest' ? '*' : ''}</span> },
  ];
}

export function MoversTable({ q, kind, onKind }: { q: PulseResult<MoverRow, { universe_all: number; universe_floor: number; min_mcap_cr: number; chip_rules: Record<string, string> }>; kind: MoverKind; onKind: (k: MoverKind) => void }) {
  const shell = useShell();
  const ctx = q.ctx;
  const columns = useMemo(() => moverColumns(ctx?.chip_rules), [ctx?.chip_rules]);
  return (
    <Panel
      title="Stocks that moved"
      meta={ctx ? `${intIN(ctx.universe_floor)} of ${intIN(ctx.universe_all)} stocks pass the ₹1,000 Cr filter` : undefined}
      actions={<Segmented label="Mover list" size="xs" options={MOVER_KINDS} value={kind} onChange={onKind} />}
    >
      <SectionBody q={q} rows={8} emptyTitle="No stocks pass the filter for this session">
        <div className="h-[600px]">
          <DataTable<MoverRow>
            label="Stocks that moved"
            columns={columns}
            rows={q.rows ?? []}
            getRowId={(r) => r.symbol}
            onRowActivate={(r) => shell.openSymbol(r.symbol)}
            onRowClick={(r) => shell.openSymbol(r.symbol)}
            hideToolbar
            rowHeight={36}
            className="h-full"
          />
        </div>
        <Note>
          Only stocks with market cap ≥ ₹1,000 Cr on the as-of date. Breadth and money flow above use all stocks. RES and NEWS chips need
          results and announcements data (not ingested yet).
        </Note>
      </SectionBody>
    </Panel>
  );
}

// ------------------------------------------------------------------ analogs

export function DaysLikeToday({ q, onOpen }: { q: PulseResult<AnalogRow, AnalogContext>; onOpen?: () => void }) {
  const rows = q.rows ?? [];
  const ctx = q.ctx;
  const up = rows.filter((r) => isNum(r.fwd_20d_pct) && r.fwd_20d_pct > 0).length;
  return (
    <Panel
      title="Days like today"
      meta="Closest past sessions by breadth (latest 25 sessions excluded)"
      actions={
        onOpen ? (
          <button type="button" className="text-2xs text-info hover:underline" onClick={onOpen}>
            Full study in History Lab
          </button>
        ) : undefined
      }
    >
      <SectionBody q={q} rows={5} emptyTitle="Not enough history for analogs">
        <div className="flex flex-wrap gap-1.5 px-3 pt-2">
          <Chip tone="info">Next 10D median {signed(ctx?.median_fwd_10d_pct ?? median(rows.map((r) => r.fwd_10d_pct)), 1)}%</Chip>
          <Chip tone="info">Next 20D median {signed(ctx?.median_fwd_20d_pct ?? median(rows.map((r) => r.fwd_20d_pct)), 1)}%</Chip>
          <Chip tone="positive">
            {up} of {rows.length} up after 20D
          </Chip>
        </div>
        <table className="mt-1 w-full text-xs tabular-nums" aria-label="Days like today">
          <thead>
            <tr className="text-2xs text-fg-3">
              {['Date', 'Above 50 EMA', '5D change', 'Above 10 EMA', 'Next 10D', 'Next 20D'].map((h, i) => (
                <th key={h} className={`px-2 py-1 font-medium ${i ? 'text-right' : 'text-left'}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ctx && (
              <tr className="bg-info/10">
                <td className="px-2 py-1">
                  <b>Today</b>
                </td>
                <td className="px-2 py-1 text-right">{fixed(ctx.today.e50, 1)}%</td>
                <td className="px-2 py-1 text-right">{signed(ctx.today.e50c5, 1)}</td>
                <td className="px-2 py-1 text-right">{fixed(ctx.today.e10, 1)}%</td>
                <td className="px-2 py-1 text-right text-fg-3">?</td>
                <td className="px-2 py-1 text-right text-fg-3">?</td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.trade_date} className="border-t border-line/60">
                <td className="px-2 py-1">{longDate(r.trade_date)}</td>
                <td className="px-2 py-1 text-right">{fixed(r.e50, 1)}%</td>
                <td className="px-2 py-1 text-right">{signed(r.e50c5, 1)}</td>
                <td className="px-2 py-1 text-right">{fixed(r.e10, 1)}%</td>
                <td className={`px-2 py-1 text-right ${toneClass(r.fwd_10d_pct)}`}>{signed(r.fwd_10d_pct, 1)}%</td>
                <td className={`px-2 py-1 text-right ${toneClass(r.fwd_20d_pct)}`}>{signed(r.fwd_20d_pct, 1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Note>Returns: equal-weight average of all stocks, daily moves capped at ±20%.</Note>
      </SectionBody>
    </Panel>
  );
}
