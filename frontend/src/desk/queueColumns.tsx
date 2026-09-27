import { CalendarClock, Star } from 'lucide-react';
import type { QueueRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtCr, fmtDateShort, fmtNum, fmtPct, fmtRatio, fmtSigned, fmtSignedPct } from '../lib/fmt';
import { Chip } from '../ui/Chip';
import type { DataTableColumn } from '../ui/DataTable';
import { Unclassified } from '../ui/Unclassified';
import { ZoneValue } from '../ui/ZoneValue';
import type { QueueId } from './deskModel';

const QUADRANT_TONE: Record<string, 'positive' | 'info' | 'warn' | 'negative'> = {
  Leading: 'positive',
  Improving: 'info',
  Weakening: 'warn',
  Lagging: 'negative',
};

function SymbolCell({ r, watched }: { r: QueueRow; watched: boolean }) {
  return (
    <span className="flex min-w-0 items-center gap-1">
      {watched && <Star className="h-3 w-3 shrink-0 fill-accent text-accent" aria-label="on watchlist" />}
      <span className="truncate font-mono font-semibold text-fg" title={r.security_name ?? undefined}>
        {r.symbol}
      </span>
      {r.is_new && (
        <Chip tone="accent" title="Entered this queue today (not in it on the previous session)">
          NEW
        </Chip>
      )}
      {r.results_within_10 && (
        <span title={`${(r.next_event?.event_type ?? 'results').replace(/_/g, ' ')} on ${fmtDateShort(r.next_event?.event_date)} — within ~10 sessions`}>
          <CalendarClock className="h-3.5 w-3.5 shrink-0 text-warn" aria-label="results soon" />
        </span>
      )}
    </span>
  );
}

function DistanceCell({ v }: { v: number }) {
  if (v < 0)
    return (
      <span className="num text-warn" title="Close is already above the trigger — more risk than planned">
        {fmtSignedPct(v, 2)}
      </span>
    );
  return <ZoneValue metricKey="distance_to_trigger_pct" value={v} format="signedPct" digits={2} />;
}

/** Desk queue columns (spec 7.2). `watched` marks watchlist rows. */
export function queueColumns(queue: QueueId, isWatched: (s: string) => boolean): DataTableColumn<QueueRow>[] {
  const cols: DataTableColumn<QueueRow>[] = [
    {
      id: 'symbol',
      header: 'Symbol',
      accessor: 'symbol',
      width: 138,
      sticky: true,
      hideable: false,
      cell: (_v, r) => <SymbolCell r={r} watched={!!r.symbol && isWatched(r.symbol)} />,
    },
    {
      id: 'industry',
      header: 'Industry',
      accessor: 'industry',
      width: 128,
      headerTitle: 'NSE industry; chip = its RRG quadrant (needs group_daily)',
      renderNull: true,
      cell: (v, r) => (
        <span className="flex min-w-0 items-center gap-1" title={[r.broad_sector, r.sector, r.industry].filter(Boolean).join(' › ')}>
          {r.industry_quadrant && <Chip tone={QUADRANT_TONE[r.industry_quadrant] ?? 'neutral'}>{r.industry_quadrant.slice(0, 4)}</Chip>}
          {v == null || v === '' ? <Unclassified /> : <span className="truncate text-fg-2">{String(v)}</span>}
        </span>
      ),
    },
    { id: 'close', header: 'Close', accessor: 'close', format: 'num', width: 80 },
    {
      id: 'change_1d_pct',
      header: '1D',
      accessor: 'change_1d_pct',
      metricKey: 'change_1d_pct',
      align: 'right',
      width: 64,
      cell: (v) => <span className={cn('num', (v as number) >= 0 ? 'text-up' : 'text-down')}>{fmtSignedPct(v as number, 2)}</span>,
    },
    {
      id: 'rs_percentile',
      header: 'Rank',
      accessor: 'rs_percentile',
      metricKey: 'rs_percentile',
      align: 'right',
      width: 84,
      cell: (v, r) => (
        <span className="num">
          <ZoneValue metricKey="rs_percentile" value={v as number} format="num" digits={0} />
          <span className={cn('ml-1 text-2xs', r.rs_delta_5 == null ? 'text-fg-3' : r.rs_delta_5 > 0 ? 'text-up' : r.rs_delta_5 < 0 ? 'text-down' : 'text-fg-3')} title="Change over 5 sessions">
            {fmtSigned(r.rs_delta_5, 0)}
          </span>
        </span>
      ),
    },
    { id: 'trigger_price', header: 'Trigger', accessor: 'trigger_price', metricKey: 'trigger_price', format: 'num', width: 80 },
    { id: 'stop_price', header: 'Stop', accessor: 'stop_price', metricKey: 'stop_price', format: 'num', width: 80 },
    {
      id: 'distance_to_trigger_pct',
      header: 'Dist.',
      accessor: 'distance_to_trigger_pct',
      metricKey: 'distance_to_trigger_pct',
      align: 'right',
      width: 66,
      sortDescFirst: false,
      cell: (v) => <DistanceCell v={v as number} />,
    },
    {
      id: 'risk_pct',
      header: 'Risk',
      accessor: 'risk_pct',
      metricKey: 'risk_pct',
      align: 'right',
      width: 62,
      sortDescFirst: false,
      cell: (v) => <ZoneValue metricKey="risk_pct" value={v as number} format="pct" digits={1} />,
    },
    {
      id: 'rvol',
      header: 'RVOL',
      accessor: 'rvol',
      metricKey: 'rvol',
      align: 'right',
      width: 60,
      cell: (v) => <ZoneValue metricKey="rvol" value={v as number} format="ratio" />,
    },
    {
      id: 'deliv_pct_x',
      header: 'Dlv %×',
      accessor: 'deliv_pct_x',
      headerTitle: "Delivery % ×20d: today's delivery % ÷ the stock's own 20-day average (1.00× = its usual habit)",
      align: 'right',
      width: 62,
      cell: (v, r) => (
        <span className={cn('num', (v as number) >= 1.3 ? 'text-up' : (v as number) < 0.8 ? 'text-fg-3' : 'text-fg')} title={`Delivery ${fmtPct(r.delivery_pct)}`}>
          {fmtRatio(v as number)}
        </span>
      ),
    },
    {
      id: 'excess_vs_midsml400_63d',
      header: 'vs MS400',
      accessor: 'excess_vs_midsml400_63d',
      metricKey: 'excess_vs_midsml400_63d',
      align: 'right',
      width: 74,
      cell: (v) => <ZoneValue metricKey="excess_vs_midsml400_63d" value={v as number} format="signedPct" />,
    },
    {
      id: 'setup_age_sessions',
      header: 'Age',
      accessor: 'setup_age_sessions',
      metricKey: 'setup_age_sessions',
      width: 52,
      format: 'int',
      sortDescFirst: false,
    },
    {
      id: 'deal_net_10s_cr',
      header: 'Deals',
      accessor: 'deal_net_10s_cr',
      metricKey: 'deal_net_10s_cr',
      align: 'right',
      width: 76,
      cell: (v) => (
        <Chip tone={(v as number) > 0 ? 'positive' : (v as number) < 0 ? 'negative' : 'neutral'} title="Net bulk/block deal value, last 10 sessions">
          {fmtCr(v as number, 1)}
        </Chip>
      ),
    },
  ];
  const at = cols.findIndex((c) => c.id === 'deliv_pct_x') + 1;
  if (queue === 'darvas_squeeze') {
    cols.splice(
      at,
      0,
      {
        id: 'squeeze_pct',
        header: 'Squeeze',
        accessor: 'squeeze_pct',
        metricKey: 'squeeze_pct',
      align: 'right',
        width: 70,
        sortDescFirst: false,
        cell: (v) => <ZoneValue metricKey="squeeze_pct" value={v as number} format="pct" digits={2} />,
      },
      {
        id: 'candle_range_pct',
        header: 'Range',
        accessor: 'candle_range_pct',
        metricKey: 'candle_range_pct',
      align: 'right',
        width: 62,
        sortDescFirst: false,
        defaultHidden: true,
        cell: (v) => <ZoneValue metricKey="candle_range_pct" value={v as number} format="pct" digits={2} />,
      },
    );
  }
  if (queue === 'darvas_10ema') {
    cols.splice(at, 0, {
      id: 'darvas_10ema_flavor',
      header: 'Flavor',
      accessor: 'darvas_10ema_flavor',
      metricKey: 'darvas_10ema_flavor',
      width: 92,
      cell: (v, r) => (
        <span className="text-fg-2" title={r.signal_date ? `10 EMA touch ${fmtDateShort(r.signal_date)}` : undefined}>
          {String(v)}
        </span>
      ),
    });
  }
  if (queue === 'vcp') {
    cols.splice(
      at,
      0,
      {
        id: 'vcp_t',
        header: 'Ts',
        accessor: (r) => r.vcp_contractions?.length ?? null,
        metricKey: 'vcp_contractions',
        width: 48,
        format: 'int',
      },
      {
        id: 'vcp_depth_pct',
        header: 'Last T',
        accessor: 'vcp_depth_pct',
        metricKey: 'vcp_depth_pct',
      align: 'right',
        width: 64,
        sortDescFirst: false,
        cell: (v, r) => (
          <span className="num" title={(r.vcp_contractions ?? []).map((c) => `${c.label} ${fmtNum(c.depth_pct, 1)}%`).join(' → ')}>
            {fmtPct(v as number, 1)}
          </span>
        ),
      },
      {
        id: 'vdu_ratio',
        header: 'VDU',
        accessor: 'vdu_ratio',
        metricKey: 'vdu_ratio',
      align: 'right',
        width: 56,
        sortDescFirst: false,
        cell: (v) => <ZoneValue metricKey="vdu_ratio" value={v as number} format="ratio" />,
      },
    );
  }
  return cols;
}

/** Server order is the queue's own ranking (tightest squeeze / flavor / closest pivot); no client re-sort by default. */
export const DEFAULT_SORT: Record<QueueId, { id: string; desc: boolean }[]> = { darvas_squeeze: [], darvas_10ema: [], vcp: [] };
