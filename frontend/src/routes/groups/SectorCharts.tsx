/**
 * Chart grid (9 cards per page in board order, synced crosshair) and the group panel (large chart,
 * plain-English read-out, members by RS). 07 §7 "Chart grid of groups", mockup v1 group panel.
 */
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useMemo } from 'react';
import { cn } from '../../lib/cn';
import { fmtSignedPct } from '../../lib/fmt';
import { tradingViewChartUrl } from '../../lib/tradingview';
import { Chart } from '../../ui/Chart';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { Skeleton } from '../../ui/Skeleton';
import { Spark } from '../../ui/Spark';
import { useSectors, type ChartRow, type MemberRow, type SectorRow, type WindowKey } from './sectorApi';
import { GroupStateChip } from '../../ui/GroupState';
import { StateDot } from './SectorBoard';
import { groupReadout, win } from './sectorModel';

export const GRID_PAGE = 9;
const EMAS = [10, 20, 50] as const;

function GroupChart({ row, height, label }: { row: ChartRow; height: number; label: string }) {
  if (!row.bars.length) return <EmptyState compact title="No chart" detail={row.reason ?? 'No bars for this group.'} />;
  const near = row.near.map((p) => p.value);
  const lastNear = near.length ? near[near.length - 1] : null;
  return (
    <div>
      <Chart
        bars={row.bars}
        emaPeriods={EMAS}
        volume={false}
        rs={{ label: 'RS vs market', data: row.rs }}
        syncGroup="sector-intel"
        height={height}
        initialBars={160}
        label={label}
      />
      <div className="flex items-center gap-2 px-1 text-2xs text-fg-3">
        <span>near 52W high</span>
        <Spark values={near.slice(-160)} width={200} height={16} tone="accent" baseline={50} label={`${row.group_name} % near 52W high`} />
        <span className="num text-fg-2">{lastNear == null ? '–' : `${lastNear}%`}</span>
      </div>
    </div>
  );
}

export function SectorChartGrid({
  rows,
  w,
  page,
  onPage,
  onOpen,
}: {
  rows: readonly SectorRow[];
  w: WindowKey;
  page: number;
  onPage: (p: number) => void;
  onOpen: (id: string) => void;
}) {
  const pages = Math.max(1, Math.ceil(rows.length / GRID_PAGE));
  const pg = Math.min(page, pages - 1);
  const slice = rows.slice(pg * GRID_PAGE, pg * GRID_PAGE + GRID_PAGE);
  const ids = slice.map((r) => r.id);
  const q = useSectors<ChartRow>('charts', { id: ids }, { enabled: ids.length > 0 });
  const byId = useMemo(() => new Map((q.data?.rows ?? []).map((c) => [c.id, c])), [q.data]);
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto p-2">
      <div className="mb-2 flex items-center justify-end gap-2 text-2xs text-fg-3">
        <span>
          Sorted like the board · page {pg + 1} of {pages}
        </span>
        <button
          type="button"
          aria-label="Previous page"
          className="rounded border border-line p-0.5 hover:text-fg disabled:opacity-40"
          disabled={pg === 0}
          onClick={() => onPage(pg - 1)}
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Next page"
          className="rounded border border-line p-0.5 hover:text-fg disabled:opacity-40"
          disabled={pg >= pages - 1}
          onClick={() => onPage(pg + 1)}
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {slice.map((r) => {
            const c = byId.get(r.id);
            const sc = win(r, 'score', w);
            return (
              <div key={r.id} className="rounded border border-line bg-surface p-1.5">
                <button
                  type="button"
                  className="mb-1 flex w-full items-center justify-between gap-2 text-left text-xs"
                  onClick={() => onOpen(r.id)}
                  title={`Open ${r.group_name}`}
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    <StateDot state={r.state} reason={r.state_reason} />
                    <b className="truncate text-fg">{r.group_name}</b>
                  </span>
                  <span className="shrink-0 text-fg-3">
                    score {sc == null ? '–' : sc.toFixed(0)} · {fmtSignedPct(win(r, 'ret', w), 1)}
                  </span>
                </button>
                {q.isLoading || !c ? (
                  <Skeleton height={230} />
                ) : (
                  <GroupChart row={c} height={210} label={`${r.group_name} equal-weight chart`} />
                )}
              </div>
            );
          })}
        </div>
      )}
      <p className="mt-2 text-2xs text-fg-3">
        Equal-weight group candles (members ≥ ₹1,000 Cr, rebased to 100) · 10 / 20 / 50 EMA · RS line vs the equal-weight market (MidSml400
        history is too short locally) · lower strip = % of members near the 52W high.
        {(q.data?.meta.notes ?? []).slice(1).map((n) => (
          <span key={n}> {n}</span>
        ))}
      </p>
    </div>
  );
}

const memberColumns = (onSymbol: (s: string) => void): DataTableColumn<MemberRow>[] => [
  {
    id: 'symbol',
    header: 'Stock',
    accessor: 'symbol',
    width: 190,
    sticky: true,
    cell: (_v, m) => (
      <span className="flex min-w-0 items-center gap-1.5">
        <button type="button" className="font-medium text-fg hover:text-accent" onClick={() => onSymbol(m.symbol)} title="Open Stock 360">
          {m.symbol}
        </button>
        <a
          className="text-2xs text-fg-3 hover:text-accent"
          href={tradingViewChartUrl(m.symbol)}
          target="_blank"
          rel="noreferrer"
          title="TradingView chart"
        >
          TV
        </a>
        <span className="truncate text-2xs text-fg-3">{m.security_name}</span>
      </span>
    ),
  },
  { id: 'rs', header: 'RS', accessor: 'rs_percentile', format: 'int', width: 48 },
  { id: 'chg', header: '1D', accessor: 'change_1d_pct', format: 'signedPct', digits: 1, width: 60 },
  { id: 'r1m', header: '1M', accessor: 'return_1m_pct', format: 'signedPct', digits: 1, width: 60 },
  { id: 'fh', header: 'From 52W hi', accessor: 'from_52w_high_pct', format: 'signedPct', digits: 1, width: 80 },
  {
    id: 'a50',
    header: '> 50E',
    accessor: (m) => (m.above_50ema == null ? null : m.above_50ema ? 1 : 0),
    width: 50,
    renderNull: true,
    cell: (v) => (v == null ? <span className="text-fg-3">–</span> : v ? '✓' : <span className="text-fg-3">·</span>),
  },
  {
    id: 'deal',
    header: 'Deals 10D',
    headerTitle: 'Net deal flow over 10 sessions, ₹ Cr (PROP, transfers, placements and churn excluded) · last event',
    accessor: 'deal_flow_10d_cr',
    width: 110,
    renderNull: true,
    cell: (v, m) =>
      m.deal_last_event == null ? (
        <span className="text-fg-3">–</span>
      ) : (
        <span
          className={cn(
            'text-2xs',
            typeof v === 'number' && v > 0 ? 'text-up' : typeof v === 'number' && v < 0 ? 'text-down' : 'text-fg-3',
          )}
        >
          {typeof v === 'number' ? `${v > 0 ? '+' : ''}${v.toFixed(1)}` : '0'} · {m.deal_last_event.replace('_', ' ')}
        </span>
      ),
  },
  { id: 'mcap', header: 'Mcap ₹Cr', accessor: 'market_cap_cr', format: 'int', width: 86 },
];

export function GroupPanel({
  row,
  w,
  levelLabel,
  onSymbol,
}: {
  row: SectorRow | undefined;
  w: WindowKey;
  levelLabel: string;
  onSymbol: (s: string) => void;
}) {
  const id = row?.id ?? '';
  const chart = useSectors<ChartRow>('charts', { id: [id] }, { enabled: !!row });
  const mem = useSectors<MemberRow>('members', { id }, { enabled: !!row });
  const cols = useMemo(() => memberColumns(onSymbol), [onSymbol]);
  if (!row) return <EmptyState compact title="Pick a group" detail="Click a row or a chart card to open its panel." />;
  const c = chart.data?.rows[0];
  const say = groupReadout(row, mem.data?.rows ?? [], w);
  return (
    <section aria-label={`${row.group_name} panel`} className="flex min-h-0 flex-col gap-2 p-2">
      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <b className="text-base text-fg">{row.group_name}</b>{' '}
          <span className="text-xs text-fg-3">
            {levelLabel} · {row.stocks} stocks
          </span>
        </div>
        <GroupStateChip state={row.state} reason={row.state_reason} size="sm" />
      </div>
      {row.state_reason && <div className="text-2xs text-fg-3">{row.state_reason}</div>}
      {chart.error ? (
        <ErrorState compact error={chart.error} />
      ) : c ? (
        <GroupChart row={c} height={300} label={`${row.group_name} group chart`} />
      ) : (
        <Skeleton height={320} />
      )}
      <div className="rounded bg-surface-2 px-2 py-1.5 text-xs leading-relaxed text-fg">{mem.isLoading ? '…' : say.join(' ')}</div>
      <div className="text-2xs uppercase tracking-wide text-fg-3">Members by RS (≥ ₹1,000 Cr)</div>
      <div className="flex min-h-[240px] flex-1 flex-col">
        <DataTable
          label={`${row.group_name} members`}
          columns={cols}
          rows={mem.data?.rows ?? []}
          total={mem.data?.total ?? null}
          getRowId={(m) => m.symbol}
          loading={mem.isLoading}
          error={mem.error}
          onRetry={() => void mem.refetch()}
          onRowActivate={(m) => onSymbol(m.symbol)}
          initialSort={[{ id: 'rs', desc: true }]}
          className="min-h-0 flex-1"
        />
      </div>
    </section>
  );
}
