/** Momentum scanner columns — the old workspace's columns on the platform table (NULL renders "—"). */
import { ExternalLink, Star } from 'lucide-react';
import type { MomentumRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtCompactIN, fmtSignedPct } from '../lib/fmt';
import { tradingViewChartUrl } from '../lib/tradingview';
import { Chip } from '../ui/Chip';
import type { DataTableColumn } from '../ui/DataTable';
import { DataWarningChip } from '../ui/DataWarningChip';
import { Unclassified } from '../ui/Unclassified';
import { SignedNum, ZoneNum } from './cells';
import { coilTone } from './momentumModel';

export type MRow = MomentumRow;

export interface MomentumColumnCtx {
  isWatched: (sym: string) => boolean;
  toggleWatch: (sym: string) => void;
}

function taxonomyTitle(r: MRow): string {
  return [r.broad_sector, r.sector, r.broad_industry, r.industry].filter(Boolean).join(' › ');
}

function textCol(id: 'sector' | 'industry', header: string, width: number, grow = false): DataTableColumn<MRow> {
  return {
    id,
    header,
    accessor: id,
    width,
    grow,
    sortDescFirst: false,
    renderNull: true,
    cell: (v, r) =>
      v == null || v === '' ? (
        <Unclassified />
      ) : (
        <span className="truncate text-fg-2" title={taxonomyTitle(r)}>
          {String(v)}
        </span>
      ),
  };
}

export function momentumColumns(ctx: MomentumColumnCtx): DataTableColumn<MRow>[] {
  return [
    {
      id: 'watch',
      header: <Star className="h-3 w-3" aria-label="Watchlist" />,
      headerTitle: 'Add to / remove from the watchlist',
      accessor: (r) => (r.symbol ? ctx.isWatched(r.symbol) : false),
      width: 28,
      sortable: false,
      hideable: false,
      align: 'center',
      renderNull: true,
      cell: (_v, r) =>
        r.symbol ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              ctx.toggleWatch(r.symbol!);
            }}
            aria-pressed={ctx.isWatched(r.symbol)}
            aria-label={`Watch ${r.symbol}`}
            className="text-fg-3 hover:text-accent"
          >
            <Star className={cn('h-3 w-3', ctx.isWatched(r.symbol) && 'fill-accent text-accent')} />
          </button>
        ) : null,
    },
    {
      id: 'symbol',
      header: 'Symbol',
      accessor: 'symbol',
      width: 150,
      sticky: true,
      hideable: false,
      sortDescFirst: false,
      cell: (v, r) => (
        <span className="flex min-w-0 items-center gap-1" title={r.security_name ?? undefined}>
          <span className="truncate font-mono font-medium text-fg">{String(v)}</span>
          {r.is_new && (
            <Chip tone="accent" size="xs" title="Listed today but not on the previous session">
              NEW
            </Chip>
          )}
          <DataWarningChip warning={r.data_warning} />
          <a
            href={tradingViewChartUrl(String(v))}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="ml-auto shrink-0 text-fg-3 hover:text-accent"
            title={`Open ${String(v)} on TradingView`}
            aria-label={`Open ${String(v)} on TradingView`}
          >
            <ExternalLink className="h-3 w-3" />
          </a>
        </span>
      ),
    },
    textCol('sector', 'Sector', 130),
    textCol('industry', 'Industry', 150, true),
    {
      id: 'trigger_date',
      header: 'Trigger',
      headerTitle: 'Latest session in the lookback on which every trigger condition held',
      accessor: 'trigger_date',
      format: 'date',
      width: 92,
      sortDescFirst: true,
    },
    { id: 'close', header: 'CMP', accessor: 'close', format: 'inr', digits: 2, width: 90 },
    {
      id: 'change_1d_pct',
      header: '1D %',
      accessor: 'change_1d_pct',
      metricKey: 'change_1d_pct',
      format: 'signedPct',
      width: 66,
      cell: (v) => <SignedNum value={v} digits={2} />,
    },
    {
      id: 'away_10ema_pct',
      header: 'vs 10 EMA',
      accessor: 'away_10ema_pct',
      metricKey: 'away_10ema_pct',
      format: 'signedPct',
      width: 88,
      cell: (v, r) => (
        <Chip tone={coilTone(r.bucket)} size="xs" title={`Coil bucket ${r.bucket ?? '—'}`}>
          <span className="num">{fmtSignedPct(v as number, 2)}</span>
        </Chip>
      ),
    },
    {
      id: 'return_5d_pct',
      header: '5D %',
      accessor: 'return_5d_pct',
      format: 'signedPct',
      width: 62,
      cell: (v) => <SignedNum value={v} digits={1} />,
    },
    {
      id: 'return_1m_pct',
      header: '1M %',
      accessor: 'return_1m_pct',
      format: 'signedPct',
      width: 62,
      cell: (v) => <SignedNum value={v} digits={1} />,
    },
    {
      id: 'return_3m_pct',
      header: '3M %',
      accessor: 'return_3m_pct',
      format: 'signedPct',
      width: 62,
      defaultHidden: true,
      cell: (v) => <SignedNum value={v} digits={1} />,
    },
    {
      id: 'rs_percentile',
      header: 'Strength',
      accessor: 'rs_percentile',
      metricKey: 'rs_percentile',
      format: 'num',
      width: 70,
      cell: (v) => <ZoneNum metricKey="rs_percentile" value={v} digits={0} />,
    },
    {
      id: 'away_52w_high_pct',
      header: 'From 52W hi',
      accessor: 'away_52w_high_pct',
      metricKey: 'away_52w_high_pct',
      format: 'signedPct',
      width: 84,
      cell: (v) => <ZoneNum metricKey="away_52w_high_pct" value={v} format="signedPct" digits={1} />,
    },
    {
      id: 'away_52w_low_pct',
      header: 'Above 52W lo',
      accessor: 'away_52w_low_pct',
      metricKey: 'away_52w_low_pct',
      format: 'signedPct',
      width: 88,
      cell: (v) => <ZoneNum metricKey="away_52w_low_pct" value={v} format="signedPct" digits={1} />,
    },
    {
      id: 'volume',
      header: 'Day vol',
      accessor: 'volume',
      format: 'int',
      width: 74,
      cell: (v) => <span className="num">{fmtCompactIN(v as number, 1)}</span>,
    },
    {
      id: 'avg_volume_20d',
      header: '20D avg vol',
      accessor: 'avg_volume_20d',
      format: 'int',
      width: 80,
      cell: (v) => <span className="num text-fg-2">{fmtCompactIN(v as number, 1)}</span>,
    },
    {
      id: 'rvol',
      header: 'RVOL',
      accessor: 'rvol',
      metricKey: 'rvol',
      format: 'ratio',
      width: 60,
      cell: (v) => <ZoneNum metricKey="rvol" value={v} format="ratio" digits={2} />,
    },
    {
      id: 'delivery_pct',
      header: 'Delivery %',
      accessor: 'delivery_pct',
      metricKey: 'delivery_pct',
      format: 'pct',
      width: 78,
      cell: (v) => <ZoneNum metricKey="delivery_pct" value={v} format="pct" digits={1} />,
    },
    {
      id: 'market_cap_cr',
      header: 'Mcap ₹Cr',
      accessor: 'market_cap_cr',
      metricKey: 'market_cap_cr',
      format: 'int',
      width: 88,
      defaultHidden: true,
    },
    {
      id: 'indicators',
      header: 'Signals',
      headerTitle:
        '10>20>50: bullish EMA stack (10 > 20 > 50 > 200) · THRUST: delivery spike (today or a trigger session) · NR7: NR7 or inside bar today',
      accessor: (r) => (r.bullish_stack ? 1 : 0) + (r.delivery_spike ? 1 : 0) + (r.coiling ? 1 : 0),
      width: 150,
      renderNull: true,
      cell: (_v, r) => (
        <span className="flex items-center gap-0.5">
          {r.bullish_stack && (
            <Chip tone="positive" size="xs" title="Bullish EMA stack (10 > 20 > 50 > 200)">
              10&gt;20&gt;50
            </Chip>
          )}
          {r.delivery_spike && (
            <Chip tone="info" size="xs" title="Delivery spike today or on a trigger session">
              THRUST
            </Chip>
          )}
          {r.coiling && (
            <Chip tone="warn" size="xs" title="NR7 or inside bar today (coiling)">
              NR7
            </Chip>
          )}
          {!r.bullish_stack && !r.delivery_spike && !r.coiling && <span className="text-fg-3">—</span>}
        </span>
      ),
    },
  ];
}
