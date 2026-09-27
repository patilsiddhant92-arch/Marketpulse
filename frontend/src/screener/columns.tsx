/** Screener table columns (spec 7.3). Rule presets and Desk-queue presets get different sets. */
import { Star } from 'lucide-react';
import type { QueueRow, ScreenerRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtInt } from '../lib/fmt';
import type { DataTableColumn } from '../ui/DataTable';
import { Chip } from '../ui/Chip';
import { DataWarningChip } from '../ui/DataWarningChip';
import { RankSpark, SignedNum, ZoneNum } from './cells';

/** Rows from /screener/run: rule presets return ScreenerRow, Darvas/VCP presets return Desk queue rows. */
export type SRow = ScreenerRow & Partial<QueueRow>;

export interface ColumnCtx {
  isWatched: (sym: string) => boolean;
  toggleWatch: (sym: string) => void;
}

function taxonomyTitle(r: SRow): string {
  return [r.broad_sector, r.sector, r.broad_industry, r.industry].filter(Boolean).join(' › ');
}

function watchCol(ctx: ColumnCtx): DataTableColumn<SRow> {
  return {
    id: 'watch',
    header: <Star className="h-3 w-3" aria-label="Watchlist" />,
    headerTitle: 'Watchlist (W toggles the sidecar symbol)',
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
  };
}

const symbolCol: DataTableColumn<SRow> = {
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
        <Chip tone="accent" size="xs" title="Matched today but not on the previous session">
          NEW
        </Chip>
      )}
      {r.rs_is_ipo_rank && (
        <Chip tone="violet" size="xs" title="Strength rank from the IPO peer group (too little history for the main rank)">
          IPO
        </Chip>
      )}
      <DataWarningChip warning={r.data_warning} />
    </span>
  ),
};

const industryCol: DataTableColumn<SRow> = {
  id: 'industry',
  header: 'Industry',
  accessor: 'industry',
  width: 150,
  grow: true,
  sortDescFirst: false,
  cell: (v, r) => (
    <span className="truncate text-fg-2" title={taxonomyTitle(r)}>
      {String(v)}
    </span>
  ),
};

const common = {
  close: { id: 'close', header: 'Close', accessor: 'close', format: 'num', digits: 2, width: 84 } as DataTableColumn<SRow>,
  change: {
    id: 'change_1d_pct',
    header: '1D %',
    accessor: 'change_1d_pct',
    metricKey: 'change_1d_pct',
    format: 'signedPct',
    width: 70,
    cell: (v) => <SignedNum value={v} digits={2} />,
  } as DataTableColumn<SRow>,
  rs: {
    id: 'rs_percentile',
    header: 'Strength',
    accessor: 'rs_percentile',
    metricKey: 'rs_percentile',
    format: 'num',
    width: 72,
    cell: (v) => <ZoneNum metricKey="rs_percentile" value={v} digits={0} />,
  } as DataTableColumn<SRow>,
  rsPath: {
    id: 'rs_path',
    header: 'Path',
    headerTitle: 'Strength rank T-30 → T-15 → T-5 → today (dashed line at 70)',
    accessor: (r) => r.rs_percentile,
    width: 74,
    sortable: false,
    renderNull: true,
    cell: (_v, r) => <RankSpark t30={r.rs_rank_t30} t15={r.rs_rank_t15} t5={r.rs_rank_t5} now={r.rs_percentile} />,
  } as DataTableColumn<SRow>,
  d5: {
    id: 'rs_delta_5',
    header: 'Δ5',
    accessor: 'rs_delta_5',
    metricKey: 'rs_delta_5',
    format: 'signed',
    width: 56,
    cell: (v) => <ZoneNum metricKey="rs_delta_5" value={v} format="signed" digits={0} />,
  } as DataTableColumn<SRow>,
  d20: {
    id: 'rs_delta_20',
    header: 'Δ20',
    headerTitle: 'Strength rank change over 20 sessions (points)',
    accessor: 'rs_delta_20',
    format: 'signed',
    width: 56,
    cell: (v) => <SignedNum value={v} format="signed" digits={0} />,
  } as DataTableColumn<SRow>,
  excess: {
    id: 'excess_vs_midsml400_63d',
    header: 'vs MidSml 3M',
    accessor: 'excess_vs_midsml400_63d',
    metricKey: 'excess_vs_midsml400_63d',
    format: 'signedPct',
    width: 88,
    cell: (v) => <ZoneNum metricKey="excess_vs_midsml400_63d" value={v} format="signedPct" digits={1} />,
  } as DataTableColumn<SRow>,
  tt: {
    id: 'trend_template_pass_n',
    header: 'TT',
    accessor: 'trend_template_pass_n',
    metricKey: 'trend_template_pass_n',
    format: 'int',
    width: 50,
    cell: (v) => <ZoneNum metricKey="trend_template_pass_n" value={v} format="int" suffix="/8" />,
  } as DataTableColumn<SRow>,
  off52: {
    id: 'away_52w_high_pct',
    header: 'From 52W hi',
    accessor: 'away_52w_high_pct',
    metricKey: 'away_52w_high_pct',
    format: 'signedPct',
    width: 84,
    cell: (v) => <ZoneNum metricKey="away_52w_high_pct" value={v} format="signedPct" digits={1} />,
  } as DataTableColumn<SRow>,
  since52: {
    id: 'days_since_52w_high',
    header: 'Since hi',
    headerTitle: 'Calendar days since the 52-week high was set',
    accessor: 'days_since_52w_high',
    format: 'int',
    width: 76,
    sortDescFirst: false,
  } as DataTableColumn<SRow>,
  stage2: {
    id: 'days_in_stage2',
    header: 'S2 days',
    headerTitle: 'Consecutive sessions with close > 200 EMA and 50 EMA > 200 EMA (Stage 2). "≥" = held for the whole 252-session window.',
    accessor: 'days_in_stage2',
    format: 'int',
    width: 82,
    cell: (v, r) => (
      <span className="num">
        {r.days_in_stage2_capped ? '≥' : ''}
        {fmtInt(v as number)}
      </span>
    ),
  } as DataTableColumn<SRow>,
  r1m: {
    id: 'return_1m_pct',
    header: '1M',
    accessor: 'return_1m_pct',
    format: 'signedPct',
    width: 64,
    cell: (v) => <SignedNum value={v} />,
  } as DataTableColumn<SRow>,
  r3m: {
    id: 'return_3m_pct',
    header: '3M',
    accessor: 'return_3m_pct',
    format: 'signedPct',
    width: 64,
    cell: (v) => <SignedNum value={v} />,
  } as DataTableColumn<SRow>,
  r6m: {
    id: 'return_6m_pct',
    header: '6M',
    accessor: 'return_6m_pct',
    format: 'signedPct',
    width: 68,
    cell: (v) => <SignedNum value={v} />,
  } as DataTableColumn<SRow>,
  rvol: {
    id: 'rvol',
    header: 'RVOL',
    accessor: 'rvol',
    metricKey: 'rvol',
    format: 'ratio',
    width: 60,
    cell: (v) => <ZoneNum metricKey="rvol" value={v} format="ratio" digits={2} />,
  } as DataTableColumn<SRow>,
  deliv: {
    id: 'delivery_pct',
    header: 'Deliv %',
    accessor: 'delivery_pct',
    metricKey: 'delivery_pct',
    format: 'pct',
    width: 64,
    cell: (v) => <ZoneNum metricKey="delivery_pct" value={v} format="pct" digits={0} />,
  } as DataTableColumn<SRow>,
  delivVs: {
    id: 'deliv_pct_x',
    header: 'Dlv % ×20d',
    accessor: 'deliv_pct_x',
    metricKey: 'deliv_pct_x',
    format: 'ratio',
    width: 80,
    defaultHidden: true,
    cell: (v) => <ZoneNum metricKey="deliv_pct_x" value={v} format="ratio" digits={2} />,
  } as DataTableColumn<SRow>,
  mcap: {
    id: 'market_cap_cr',
    header: 'Mcap',
    accessor: 'market_cap_cr',
    metricKey: 'market_cap_cr',
    format: 'cr',
    digits: 0,
    width: 96,
  } as DataTableColumn<SRow>,
  adv: {
    id: 'adv_cr_20d',
    header: 'ADV 20D',
    accessor: 'adv_cr_20d',
    metricKey: 'adv_cr_20d',
    format: 'cr',
    digits: 1,
    width: 84,
    defaultHidden: true,
  } as DataTableColumn<SRow>,
  lastPass: {
    id: 'last_pass_date',
    header: 'Last pass',
    headerTitle: 'Latest session in the lookback window on which every rule held',
    accessor: 'last_pass_date',
    format: 'date',
    width: 92,
  } as DataTableColumn<SRow>,
};

export function ruleColumns(ctx: ColumnCtx, lookback: boolean): DataTableColumn<SRow>[] {
  const c = common;
  return [
    watchCol(ctx),
    symbolCol,
    industryCol,
    c.close,
    c.change,
    c.rs,
    c.rsPath,
    c.d5,
    c.d20,
    c.excess,
    c.tt,
    c.off52,
    c.since52,
    c.stage2,
    c.r1m,
    c.r3m,
    c.r6m,
    c.rvol,
    c.deliv,
    c.delivVs,
    c.mcap,
    c.adv,
    ...(lookback ? [c.lastPass] : []),
  ];
}

export function queueColumns(ctx: ColumnCtx, queue: string | null | undefined): DataTableColumn<SRow>[] {
  const c = common;
  const geometry: DataTableColumn<SRow>[] = [
    { id: 'trigger_price', header: 'Trigger', accessor: 'trigger_price', metricKey: 'trigger_price', format: 'num', digits: 2, width: 80 },
    { id: 'stop_price', header: 'Stop', accessor: 'stop_price', metricKey: 'stop_price', format: 'num', digits: 2, width: 80 },
    {
      id: 'distance_to_trigger_pct',
      header: 'To trigger',
      accessor: 'distance_to_trigger_pct',
      metricKey: 'distance_to_trigger_pct',
      format: 'signedPct',
      width: 76,
      sortDescFirst: false,
      cell: (v) => <ZoneNum metricKey="distance_to_trigger_pct" value={v} format="signedPct" digits={1} />,
    },
    {
      id: 'risk_pct',
      header: 'Risk %',
      accessor: 'risk_pct',
      metricKey: 'risk_pct',
      format: 'pct',
      width: 66,
      sortDescFirst: false,
      cell: (v, r) => (
        <span className={cn(r.risk_flag && 'rounded bg-warn/10 px-1')} title={r.risk_flag ? 'Risk above 8% of price' : undefined}>
          <ZoneNum metricKey="risk_pct" value={v} format="pct" digits={1} />
        </span>
      ),
    },
  ];
  const specific: DataTableColumn<SRow>[] =
    queue === 'vcp'
      ? [
          {
            id: 'vcp_contractions',
            header: 'Ts',
            accessor: (r) => r.vcp_contractions?.length ?? null,
            metricKey: 'vcp_contractions',
            format: 'int',
            width: 44,
            cell: (_v, r) => (
              <span className="num" title={(r.vcp_contractions ?? []).map((t) => `${t.label} ${t.depth_pct ?? '—'}%`).join(' → ')}>
                {r.vcp_contractions?.length ?? '—'}
              </span>
            ),
          },
          {
            id: 'vcp_depth_pct',
            header: 'Last T',
            accessor: (r) => {
              const ts = r.vcp_contractions ?? [];
              return ts.length ? (ts[ts.length - 1].depth_pct ?? null) : null;
            },
            headerTitle: 'Depth of the last (tightest) contraction, %',
            format: 'pct',
            width: 64,
          },
          {
            id: 'vdu_ratio',
            header: 'VDU',
            accessor: 'vdu_ratio',
            metricKey: 'vdu_ratio',
            format: 'ratio',
            width: 56,
            cell: (v) => <ZoneNum metricKey="vdu_ratio" value={v} format="ratio" digits={2} />,
          },
        ]
      : [
          {
            id: 'squeeze_pct',
            header: 'Squeeze',
            accessor: 'squeeze_pct',
            metricKey: 'squeeze_pct',
            format: 'pct',
            width: 66,
            sortDescFirst: false,
            cell: (v) => <ZoneNum metricKey="squeeze_pct" value={v} format="pct" digits={1} />,
          },
          {
            id: 'candle_range_pct',
            header: 'Range',
            accessor: 'candle_range_pct',
            metricKey: 'candle_range_pct',
            format: 'pct',
            width: 60,
            sortDescFirst: false,
          },
        ];
  return [
    watchCol(ctx),
    symbolCol,
    industryCol,
    c.close,
    c.change,
    ...geometry,
    ...specific,
    c.rs,
    c.d5,
    c.excess,
    c.rvol,
    c.deliv,
    c.delivVs,
    {
      id: 'setup_age_sessions',
      header: 'Age',
      accessor: 'setup_age_sessions',
      metricKey: 'setup_age_sessions',
      format: 'int',
      width: 50,
      sortDescFirst: false,
    },
    {
      id: 'results_within_10',
      header: 'Results',
      headerTitle: 'Results / board meeting within 10 sessions',
      accessor: 'results_within_10',
      width: 64,
      cell: (v, r) =>
        v ? (
          <Chip
            tone="warn"
            size="xs"
            title={r.next_event ? `${r.next_event.event_type ?? ''} ${r.next_event.event_date ?? ''}` : undefined}
          >
            soon
          </Chip>
        ) : (
          <span className="text-fg-3">no</span>
        ),
    },
    {
      id: 'deal_net_10s_cr',
      header: 'Deals 10s',
      accessor: 'deal_net_10s_cr',
      metricKey: 'deal_net_10s_cr',
      format: 'cr',
      digits: 1,
      width: 80,
      defaultHidden: true,
    },
    c.mcap,
  ];
}
