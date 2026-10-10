/**
 * Setups board columns (locked spec "Board"). Default columns first; the column groups
 * Trade · Strength · Turnover · Group flow · Character start hidden (Columns menu).
 */
import { ExternalLink } from 'lucide-react';
import type { SetupBoardRow } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtCr, fmtNum, fmtRatio } from '../../lib/fmt';
import { tradingViewChartUrl } from '../../lib/tradingview';
import { Chip } from '../../ui/Chip';
import { DataWarningChip } from '../../ui/DataWarningChip';
import type { DataTableColumn } from '../../ui/DataTable';
import { Spark } from '../../ui/Spark';
import { SignedNum, ZoneNum } from '../cells';
import { chipTone, stateTone, tagTone } from './model';

type C = DataTableColumn<SetupBoardRow>;

const mult = (v: unknown) => {
  const n = v as number;
  return <span className={cn('num', n >= 1.5 ? 'text-up' : n < 0.7 ? 'text-fg-3' : 'text-fg')}>{fmtRatio(n)}×</span>;
};

const STATUS_ORDER: Record<string, number> = { new: 0, returning: 1, active: 2 };

export function boardColumns(): C[] {
  const defaults: C[] = [
    {
      id: 'symbol',
      header: 'Symbol',
      accessor: 'symbol',
      width: 128,
      sticky: true,
      cell: (_v, r) => (
        <span className="flex min-w-0 items-center gap-1">
          <a
            href={tradingViewChartUrl(r.symbol)}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            title={`${r.name ?? r.symbol}: open in TradingView`}
            className="flex items-center gap-0.5 font-mono font-semibold text-fg hover:text-accent"
          >
            {r.symbol}
            <ExternalLink className="h-2.5 w-2.5 text-fg-3" aria-hidden />
          </a>
          {r.status === 'new' && (
            <Chip tone="accent" size="xs" title="New on this session">
              NEW
            </Chip>
          )}
          <DataWarningChip warning={r.data_warning} />
        </span>
      ),
    },
    {
      id: 'setups',
      header: 'Setups',
      accessor: (r) => r.screeners.length * 10 - (STATUS_ORDER[r.status] ?? 2),
      width: 230,
      sortDescFirst: true,
      headerTitle: 'Screener tags (confluence first). Squeeze width %, days in setup or VCP footprint.',
      cell: (_v, r) => (
        <span className="flex min-w-0 items-center gap-1 overflow-hidden">
          {r.tags.map((t) => (
            <Chip key={t} tone={tagTone(t)} size="xs">
              {t}
            </Chip>
          ))}
          <span className="truncate text-2xs text-fg-3">
            {[r.squeeze_pct != null ? `sq ${fmtNum(r.squeeze_pct, 1)}%` : null, r.vcp_footprint, r.age ? `${r.age}d` : null]
              .filter(Boolean)
              .join(' · ')}
          </span>
        </span>
      ),
    },
    {
      id: 'group',
      header: 'Group',
      accessor: (r) => (r.group_state === 'Favour' ? 0 : r.group_state === 'Neutral' ? 1 : 2),
      width: 170,
      headerTitle: 'Industry group state from Pulse (Favour / Neutral / Caution); hover for the reason.',
      cell: (_v, r) => (
        <span className="flex min-w-0 items-center gap-1" title={`${r.group_state}: ${r.group_reason}`}>
          <Chip tone={stateTone(r.group_state)} variant="dot" size="xs">
            {r.group_state}
          </Chip>
          <span className="truncate text-2xs text-fg-2">{r.industry ?? 'Unclassified'}</span>
        </span>
      ),
    },
    { id: 'a52', header: '52W high', accessor: 'away_52w_high_pct', format: 'signedPct', digits: 1, width: 76, headerTitle: 'Distance to the 52-week high' },
    { id: 'a10', header: '10 EMA', accessor: 'away_10ema_pct', format: 'signedPct', digits: 1, width: 70, headerTitle: 'Distance to the 10-day EMA' },
    {
      id: 'rsp',
      header: 'RS',
      accessor: 'rs_percentile',
      width: 78,
      metricKey: 'rs_percentile',
      cell: (v, r) => (
        <span className="flex items-center gap-1">
          <ZoneNum metricKey="rs_percentile" value={v} digits={0} />
          {r.rs_delta_5d != null && <span className="text-2xs"><SignedNum value={r.rs_delta_5d} format="signed" digits={0} /></span>}
        </span>
      ),
    },
    { id: 'risk', header: 'Risk %', accessor: 'risk_pct', format: 'pct', digits: 1, width: 64, headerTitle: 'Trigger to stop, % of trigger' },
    {
      id: 'room',
      header: 'Room',
      accessor: (r) => (r.blue_sky ? 999 : r.room_to_run_pct),
      width: 70,
      sortDescFirst: true,
      headerTitle: 'Room to run: trigger to overhead supply (prototype: the 52W high). Blue sky = trigger at the high.',
      cell: (_v, r) => (r.blue_sky ? <span className="text-up">Blue sky</span> : <span className="num">{fmtNum(r.room_to_run_pct, 1)}%</span>),
    },
    {
      id: 'tight',
      header: 'Tightness',
      accessor: 'range_10d_pct',
      width: 96,
      headerTitle: '10-day range % · volume dry-up % (3D vs 20D)',
      cell: (_v, r) => (
        <span className="num text-fg-2">
          {fmtNum(r.range_10d_pct, 1)}%<span className="text-fg-3"> · {r.volume_dryup_pct == null ? '—' : `${fmtNum(r.volume_dryup_pct, 0)}%`}</span>
        </span>
      ),
    },
    {
      id: 'deliv',
      header: 'Delivery',
      accessor: 'delivery_streak',
      width: 128,
      sortDescFirst: true,
      headerTitle: 'Delivery % today vs own 20D avg · consecutive days above it · last 5 sessions',
      cell: (_v, r) => (
        <span className="flex items-center gap-1">
          <span className={cn('num', (r.delivery_pct ?? 0) > (r.delivery_avg_20d ?? 1e9) ? 'text-up' : 'text-fg-2')}>
            {fmtNum(r.delivery_pct, 0)}/{fmtNum(r.delivery_avg_20d, 0)}
          </span>
          <span className={cn('num text-2xs', r.delivery_streak >= 3 ? 'text-up' : 'text-fg-3')} title="Days in a row above its own 20D average">
            {r.delivery_streak}d
          </span>
          <Spark values={r.delivery_5d} width={36} height={14} showLastDot={false} label={`${r.symbol} delivery %, last 5 sessions`} />
        </span>
      ),
    },
    { id: 't1w', header: 'Turn 1W×', accessor: 'turnover_1w_x', width: 74, sortDescFirst: true, headerTitle: 'Turnover 5D avg ÷ own 3M avg', cell: mult },
    {
      id: 'base',
      header: 'Base rate',
      accessor: (r) => r.base_rate?.win ?? null,
      width: 96,
      sortDescFirst: true,
      headerTitle: 'Past new setups of the same screener in the same group state: % up after 20 sessions · median',
      cell: (_v, r) =>
        r.base_rate ? (
          <span
            className={cn('num', r.base_rate.insufficient && 'text-fg-3')}
            title={`${r.base_rate.scope ?? ''}: n ${r.base_rate.n ?? '—'}, median ${fmtNum(r.base_rate.median, 1)}%`}
          >
            {fmtNum(r.base_rate.win, 0)}% · <SignedNum value={r.base_rate.median} digits={1} />
          </span>
        ) : (
          <span className="text-fg-3">—</span>
        ),
    },
    {
      id: 'chips',
      header: 'Chips',
      accessor: (r) => r.chips.length + (r.results_soon ? 10 : 0),
      width: 190,
      grow: true,
      sortDescFirst: true,
      headerTitle: 'Data-backed only: deal, 10% band, ASM/GSM, ex-date, pledge, 52W high, results within N sessions',
      cell: (_v, r) => (
        <span className="flex min-w-0 items-center gap-1 overflow-hidden">
          {r.results_soon && (
            <Chip tone="warn" size="xs" title="Results within N sessions">
              Results {r.results_date ?? ''}
            </Chip>
          )}
          {r.chips.map((c) => (
            <Chip key={`${c.kind}-${c.label}`} tone={chipTone(c.kind)} size="xs" title={c.title ?? undefined}>
              {c.label}
            </Chip>
          ))}
          {r.peer_note && (
            <span className="truncate text-2xs text-info" title={r.peer_note}>
              peer
            </span>
          )}
        </span>
      ),
    },
  ];
  const hidden = (group: string, cols: C[]): C[] => cols.map((c) => ({ ...c, group, defaultHidden: true }));
  return [
    ...defaults,
    ...hidden('Trade', [
      { id: 'trig', header: 'Trigger', accessor: 'trigger', format: 'num', width: 76 },
      { id: 'stop', header: 'Stop', accessor: 'stop', format: 'num', width: 76 },
      { id: 'radr', header: 'Risk ÷ ADR', accessor: 'risk_adr', format: 'num', digits: 2, width: 76, headerTitle: 'Risk % in units of the 20D average daily range' },
    ]),
    ...hidden('Strength', [
      { id: 'rs21', header: 'RS 21D', accessor: 'rs_21d', format: 'signedPct', digits: 1, width: 70, headerTitle: 'Return vs Nifty MidSmallcap 400, 21D' },
      { id: 'rs63', header: 'RS 63D', accessor: 'rs_63d', format: 'signedPct', digits: 1, width: 70, headerTitle: 'Return vs Nifty MidSmallcap 400, 63D' },
      { id: 'rsd5', header: 'RS Δ5D', accessor: 'rs_delta_5d', format: 'signed', digits: 0, width: 64 },
      { id: 'a50', header: '50 EMA', accessor: 'away_50ema_pct', format: 'signedPct', digits: 1, width: 70 },
    ]),
    ...hidden('Turnover', [
      { id: 't1d', header: '1D×', accessor: 'turnover_1d_x', width: 60, sortDescFirst: true, cell: mult },
      { id: 't1w2', header: '1W×', accessor: 'turnover_1w_x', width: 60, sortDescFirst: true, cell: mult },
      { id: 't1m', header: '1M×', accessor: 'turnover_1m_x', width: 60, sortDescFirst: true, cell: mult },
      { id: 'tcr', header: '₹ Cr', accessor: 'turnover_cr', width: 70, cell: (v) => <span className="num">{fmtCr(v as number, 1)}</span> },
    ]),
    ...hidden('Group flow', [
      { id: 'g1d', header: 'Share Δ1D', accessor: 'group_share_chg_1d', format: 'signedPct', digits: 1, width: 76, headerTitle: 'Group turnover share change, 1 session' },
      { id: 'g1w', header: 'Share Δ1W', accessor: 'group_share_chg_1w', format: 'signedPct', digits: 1, width: 76, headerTitle: 'Group 5D-avg turnover share change over 5 sessions' },
      { id: 'g1m', header: 'Share Δ1M', accessor: 'group_share_chg_1m', format: 'signedPct', digits: 1, width: 76, headerTitle: 'Group 20D-avg turnover share change over 20 sessions' },
      {
        id: 'grank',
        header: 'Rank',
        accessor: 'group_rank',
        width: 84,
        headerTitle: 'Group rank by 63D excess return vs the median industry (1 = best) · change over 5 sessions',
        cell: (_v, r) => (
          <span className="num">
            {fmtNum(r.group_rank, 0)}/{r.group_rank_n ?? '—'}{' '}
            {r.group_rank_chg_5d != null && <SignedNum value={r.group_rank_chg_5d} format="signed" digits={0} />}
          </span>
        ),
      },
    ]),
    ...hidden('Character', [
      {
        id: 'box',
        header: 'Box 6M',
        accessor: (r) => r.breakouts_held_6m - r.breakouts_failed_6m,
        width: 80,
        sortDescFirst: true,
        headerTitle: 'Own Darvas box breakouts in 6M: held (+5% in 10 sessions) / failed (back in the box within 5)',
        cell: (_v, r) => (
          <span className="num">
            <span className="text-up">{r.breakouts_held_6m}</span>/<span className="text-down">{r.breakouts_failed_6m}</span>
          </span>
        ),
      },
      {
        id: 'wk',
        header: 'Weekly',
        accessor: (r) => (r.weekly_above_10w ? 1 : 0) + (r.weekly_tight ? 1 : 0),
        width: 110,
        sortDescFirst: true,
        headerTitle: 'Weekly close vs 10-week line · last 3 weekly closes within 2%',
        cell: (_v, r) => (
          <span className="text-2xs">
            <span className={r.weekly_above_10w ? 'text-up' : 'text-fg-3'}>{r.weekly_above_10w == null ? '—' : r.weekly_above_10w ? '>10W' : '<10W'}</span>
            {' · '}
            <span className={r.weekly_tight ? 'text-up' : 'text-fg-3'} title={`3-week spread ${fmtNum(r.weekly_spread_3w_pct, 1)}%`}>
              {r.weekly_tight ? 'tight' : 'loose'}
            </span>
          </span>
        ),
      },
    ]),
  ];
}
