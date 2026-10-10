/** Leadership board at every level (07 §7 revised board, round 3b colours, Deals 10D from 08 §5.3). */
import { useMemo, type ReactNode } from 'react';
import { cn } from '../../lib/cn';
import { tradingViewChartUrl } from '../../lib/tradingview';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { EmptyState } from '../../ui/EmptyState';
import { GroupStateChip } from '../../ui/GroupState';
import { WINDOW_LABEL, type IndexRow, type SectorRow, type WindowKey } from './sectorApi';
import { RANK_CLASS, dealsCell, rankTone, win, type WinMetric } from './sectorModel';

const DASH = <span className="text-fg-3">–</span>;

/** Board state dot: the shared GroupStateChip (ui/GroupState.tsx) in its dense form. */
export function StateDot({ state, reason }: { state: string | null; reason?: string | null }) {
  return <GroupStateChip state={state} reason={reason} dotOnly />;
}

function Pct({ v }: { v: number | null | undefined }) {
  if (v == null) return null;
  return (
    <span className="ml-1 text-2xs text-fg-3" title="Percentile vs this group's own last 2 years">
      p{v}
    </span>
  );
}

function signed(v: number, d: number, suf = ''): string {
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}${suf}`;
}

/** Ranked cell: colour = rank vs the other groups on the same day, never the sign. */
function Ranked({ all, v, children }: { all: readonly (number | null)[]; v: number | null; children: ReactNode }) {
  const t = rankTone(all, v);
  return <span className={cn('num', t ? RANK_CLASS[t] : 'text-fg')}>{children}</span>;
}

export function boardColumns(rows: readonly SectorRow[], w: WindowKey, onOpen: (id: string) => void): DataTableColumn<SectorRow>[] {
  const col = (k: WinMetric) => rows.map((r) => win(r, k, w));
  const all = {
    score: col('score'),
    nh: col('nh'),
    ad: col('ad'),
    upd: col('upd'),
    tov: col('tov'),
    tox: col('tox'),
    shd: col('shd'),
    rx: col('rx'),
    near: rows.map((r) => r.near),
  };
  const W = WINDOW_LABEL[w];
  const metric = (
    id: WinMetric,
    header: string,
    title: string,
    render: (v: number, r: SectorRow) => ReactNode,
    extra: Partial<DataTableColumn<SectorRow>> = {},
  ): DataTableColumn<SectorRow> => ({
    id,
    header,
    headerTitle: title,
    accessor: (r) => win(r, id, w),
    width: 84,
    renderNull: true,
    cell: (v, r) =>
      v == null ? (
        DASH
      ) : (
        <Ranked all={(all as Record<string, (number | null)[]>)[id] ?? []} v={v as number}>
          {render(v as number, r)}
        </Ranked>
      ),
    ...extra,
  });
  return [
    {
      id: 'group_name',
      header: 'Group',
      accessor: 'group_name',
      width: 230,
      sticky: true,
      cell: (_v, r) => (
        <span className="flex min-w-0 items-center gap-1.5">
          <StateDot state={r.state} reason={r.state_reason} />
          <button
            type="button"
            className="min-w-0 truncate text-left text-fg hover:text-accent hover:underline"
            title={`Open ${r.group_name}`}
            onClick={(e) => {
              e.stopPropagation();
              onOpen(r.id);
            }}
          >
            {r.group_name}
          </button>
          {r.small && (
            <Chip title={r.ranked ? 'Fewer than 5 members: readings are noisy' : 'Fewer than 3 members: listed, not ranked'}>small</Chip>
          )}
        </span>
      ),
    },
    { id: 'stocks', header: 'Stocks', accessor: 'stocks', format: 'int', width: 56, headerTitle: 'Members with market cap ≥ ₹1,000 Cr' },
    metric(
      'score',
      'Score',
      'Leadership score 0–100: average rank of near-52W-high %, new highs, A/D and up-day delivery share (this window). Default sort.',
      (v, r) => (
        <>
          <span className="mr-1 inline-block h-1.5 rounded bg-accent/70 align-middle" style={{ width: `${Math.round(v * 0.32)}px` }} />
          {v.toFixed(0)}
          <Pct v={r.pct[`score_${w}`]} />
        </>
      ),
      { width: 104 },
    ),
    {
      id: 'near',
      header: 'Near 52W high',
      headerTitle: `% of members within 10% of their 52-week high · change over ${W} · p = vs own 2 years`,
      accessor: 'near',
      width: 124,
      renderNull: true,
      cell: (v, r) => {
        if (v == null) return DASH;
        const chg = win(r, 'nearchg', w);
        return (
          <span>
            <Ranked all={all.near} v={v as number}>
              {(v as number).toFixed(0)}%
            </Ranked>
            {chg != null && <span className="ml-1 text-2xs text-fg-2">{signed(chg, 0)}</span>}
            <Pct v={r.pct.near} />
          </span>
        );
      },
    },
    metric('nh', 'New highs', `Members that made a new 52-week high in the last ${W}`, (v, r) => (
      <>
        {v.toFixed(0)}
        <Pct v={r.pct[`nh_${w}`]} />
      </>
    )),
    metric('ad', 'A/D', `Net % of members up per day, averaged over ${W}`, (v, r) => (
      <>
        {signed(v, 0, '%')}
        <Pct v={r.pct[`ad_${w}`]} />
      </>
    )),
    metric(
      'upd',
      'Up-day delivery',
      `Delivered value on up days ÷ all delivered value, ${W}`,
      (v, r) => (
        <>
          {v.toFixed(0)}%
          <Pct v={r.pct[`upd_${w}`]} />
        </>
      ),
      { width: 96 },
    ),
    metric(
      'tov',
      'Turnover ₹Cr/day',
      `Average daily turnover over ${W}, ₹ Cr (attention, not direction)`,
      (v) => Math.round(v).toLocaleString('en-IN'),
      {
        width: 100,
        group: 'Turnover (attention)',
      },
    ),
    {
      id: 'sh',
      header: 'Share',
      headerTitle: `Share of all-stock turnover over ${W}`,
      accessor: (r) => win(r, 'sh', w),
      width: 64,
      renderNull: true,
      group: 'Turnover (attention)',
      cell: (v) => (v == null ? DASH : <span className="num text-fg">{(v as number).toFixed(2)}%</span>),
    },
    metric(
      'tox',
      'Turnover ×',
      `Turnover over ${W} vs its own 3-month average`,
      (v, r) => (
        <>
          {v.toFixed(2)}×
          <Pct v={r.pct[`tox_${w}`]} />
        </>
      ),
      { group: 'Turnover (attention)', width: 92 },
    ),
    metric('shd', 'Share Δ', 'Turnover share vs its 3-month average, points', (v) => signed(v, 2), {
      group: 'Turnover (attention)',
      width: 70,
    }),
    metric('rx', 'Return vs median', `Group equal-weight return over ${W} minus the median group, points`, (v) => signed(v, 1), {
      width: 92,
    }),
    {
      id: 'deals',
      header: 'Deals 10D',
      headerTitle:
        'Bulk/block deals over the last 10 sessions: net-buy names · net-sell names · flow ₹ Cr (PROP, transfers, placements and churn excluded). Chip at 3+ net-buy names. Context only: evidence +0.7%, weak.',
      accessor: (r) => r.deals_flow_10d_cr,
      width: 150,
      renderNull: true,
      cell: (_v, r) => {
        const d = dealsCell(r);
        if (!d) return DASH;
        return d.chip ? (
          <Chip tone="violet" title="3+ names with net deal buying in 10 sessions">
            {d.text}
          </Chip>
        ) : (
          <span className="text-2xs text-fg-2">{d.text}</span>
        );
      },
    },
    {
      id: 'leaders',
      header: 'Leaders',
      headerTitle: 'Top 3 members by RS percentile (opens the TradingView chart)',
      accessor: (r) => r.leaders.join(' '),
      width: 200,
      sortable: false,
      cell: (_v, r) => (
        <span className="flex gap-1.5 truncate">
          {r.leaders.map((s) => (
            <a
              key={s}
              href={tradingViewChartUrl(s)}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-fg hover:text-accent"
              onClick={(e) => e.stopPropagation()}
            >
              {s}
            </a>
          ))}
        </span>
      ),
    },
  ];
}

export function SectorBoard({
  rows,
  w,
  levelLabel,
  loading,
  error,
  onRetry,
  selected,
  onSelect,
  onOpen,
  onSortedRows,
}: {
  rows: readonly SectorRow[];
  w: WindowKey;
  levelLabel: string;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  selected: string | null;
  onSelect: (id: string) => void;
  onOpen: (id: string) => void;
  onSortedRows?: (rows: SectorRow[]) => void;
}) {
  const columns = useMemo(() => boardColumns(rows, w, onOpen), [rows, w, onOpen]);
  return (
    <DataTable
      label={`${levelLabel} board`}
      columns={columns}
      rows={rows}
      total={rows.length}
      getRowId={(r) => r.id}
      loading={loading}
      error={error}
      onRetry={onRetry}
      initialSort={[{ id: 'score', desc: true }]}
      activeRowId={selected}
      onActiveRowChange={(r) => onSelect(r.id)}
      onRowClick={(r) => onSelect(r.id)}
      onRowActivate={(r) => onOpen(r.id)}
      onSortedRowsChange={onSortedRows}
      emptyState={<EmptyState title="No groups match" detail="Clear the state filter or the name filter." />}
      className="min-h-0 flex-1"
    />
  );
}

export function IndexBoard({
  rows,
  w,
  loading,
  error,
  onRetry,
}: {
  rows: readonly IndexRow[];
  w: WindowKey;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
}) {
  const all = (k: 'ret' | 'rs') => rows.map((r) => (r as Record<string, unknown>)[`${k}_${w}`] as number | null);
  const columns: DataTableColumn<IndexRow>[] = [
    { id: 'group_name', header: 'Index', accessor: 'group_name', width: 220, sticky: true },
    { id: 'category', header: 'Type', accessor: 'category', width: 90 },
    { id: 'close', header: 'Close', accessor: 'close', format: 'num', digits: 1, width: 90 },
    ...(['1D', '1W', '2W', '1M'] as WindowKey[]).map<DataTableColumn<IndexRow>>((k) => ({
      id: `ret_${k}`,
      header: `${k} %`,
      accessor: (r) => (r as Record<string, unknown>)[`ret_${k}`] as number | null,
      width: 72,
      renderNull: true,
      cell: (v) =>
        v == null ? (
          DASH
        ) : (
          <Ranked all={k === w ? all('ret') : rows.map((r) => (r as Record<string, unknown>)[`ret_${k}`] as number | null)} v={v as number}>
            {signed(v as number, 2, '%')}
          </Ranked>
        ),
    })),
    {
      id: 'rs',
      header: `vs MidSml400 (${w})`,
      headerTitle: `Index return minus NIFTY MIDSML 400 return over ${WINDOW_LABEL[w]}, points`,
      accessor: (r) => (r as Record<string, unknown>)[`rs_${w}`] as number | null,
      width: 110,
      renderNull: true,
      cell: (v) =>
        v == null ? (
          DASH
        ) : (
          <Ranked all={all('rs')} v={v as number}>
            {signed(v as number, 2)}
          </Ranked>
        ),
    },
    {
      id: 'above_20ema',
      header: '> 20 EMA',
      accessor: (r) => (r.above_20ema == null ? null : r.above_20ema ? 1 : 0),
      width: 72,
      renderNull: true,
      cell: (v) => (v == null ? DASH : v ? <span className="text-up">Yes</span> : <span className="text-down">No</span>),
    },
    {
      id: 'sessions',
      header: 'Sessions',
      accessor: 'sessions',
      format: 'int',
      width: 70,
      headerTitle: 'Sessions of index history in the database',
    },
  ];
  return (
    <DataTable
      label="Index board"
      columns={columns}
      rows={rows}
      total={rows.length}
      getRowId={(r) => r.id}
      loading={loading}
      error={error}
      onRetry={onRetry}
      initialSort={[{ id: `ret_${w}`, desc: true }]}
      emptyState={<EmptyState title="No index data" detail="index_daily holds no sessions for the 44 sectoral and thematic indices." />}
      className="min-h-0 flex-1"
    />
  );
}
