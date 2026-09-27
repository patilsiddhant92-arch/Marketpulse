/** Deals building blocks: event chip, 10-session net strip, prints panel, house drawer. */
import { useMemo } from 'react';
import { useApiQuery } from '../../api/query';
import type { HousePrintRow, StockDealRow } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtDate, fmtDateShort, fmtInt, fmtNum, fmtSigned, fmtSignedPct } from '../../lib/fmt';
import { useShell } from '../../shell/ShellContext';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { Skeleton } from '../../ui/Skeleton';
import { Tooltip } from '../../ui/Tooltip';
import { MetricInline, ZoneNum } from '../groups/kit';
import { EVENTS, isEventType, netBars } from './dealsModel';

export function EventChip({ type, rule }: { type: string | null | undefined; rule?: string | null }) {
  if (!isEventType(type)) return <span className="text-fg-3">—</span>;
  const e = EVENTS[type];
  return (
    <Tooltip
      content={
        <div className="max-w-xs space-y-1">
          <div className="font-medium text-fg">{e.label}</div>
          <div className="text-fg-2">{rule ?? e.short}</div>
        </div>
      }
    >
      <span tabIndex={0} className="inline-flex">
        <Chip tone={e.tone}>{e.label}</Chip>
      </span>
    </Tooltip>
  );
}

/** Ten tiny bars: net ex-PROP ₹ Cr per session (oldest → newest), grey dot = no deal. */
export function NetStrip({ values, dates, height = 18 }: { values: readonly (number | null | undefined)[] | null | undefined; dates?: readonly (string | null)[]; height?: number }) {
  const bars = netBars(values ?? []);
  const title = bars.map((b, i) => `${dates?.[i] ? fmtDateShort(dates[i]) : `T-${bars.length - 1 - i}`}: ${b.v == null ? 'no deal' : fmtSigned(b.v, 1)}`).join('\n');
  return (
    <span className="inline-flex items-center gap-px" style={{ height }} title={title} role="img" aria-label={`Net by day: ${title.replace(/\n/g, ', ')}`}>
      {bars.map((b, i) => (
        <span key={i} className="relative inline-block w-[5px]" style={{ height }}>
          {b.v == null ? (
            <span className="absolute left-[1.5px] top-1/2 h-[2px] w-[2px] -translate-y-1/2 rounded-full bg-fg-3/50" />
          ) : (
            <span
              className={cn('absolute left-0 w-[5px] rounded-[1px]', b.v > 0 ? 'bg-up' : b.v < 0 ? 'bg-down' : 'bg-fg-3')}
              style={
                b.v >= 0
                  ? { bottom: '50%', height: `${Math.max(1, b.h * (height / 2))}px` }
                  : { top: '50%', height: `${Math.max(1, b.h * (height / 2))}px` }
              }
            />
          )}
        </span>
      ))}
    </span>
  );
}

const EMPTY_P: StockDealRow[] = [];

/** Prints behind one symbol-session (collapsed: a bulk+block duplicate counts once). */
export function PrintsPanel({ symbol, date, onHouse }: { symbol: string; date: string | null; onHouse: (house: string) => void }) {
  const q = useApiQuery('stock/{sym}/deals', { params: { sym: symbol }, query: { limit: 5000 } });
  const rows = useMemo(() => (q.data?.rows ?? EMPTY_P).filter((r) => !date || r.trade_date === date), [q.data, date]);
  const history = q.data?.rows ?? EMPTY_P;
  if (q.error) return <ErrorState error={q.error} compact onRetry={() => void q.refetch()} />;
  if (q.isLoading) return <Skeleton height={80} />;
  return (
    <div className="text-2xs">
      {rows.length === 0 ? (
        <div className="text-fg-3">No prints on {fmtDate(date)}.</div>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr className="text-left text-fg-3">
              <th className="py-0.5 pr-2 font-medium">Client</th>
              <th className="pr-2 font-medium">Class</th>
              <th className="pr-2 font-medium">Side</th>
              <th className="pr-2 text-right font-medium">Qty</th>
              <th className="pr-2 text-right font-medium">Price</th>
              <th className="pr-2 text-right font-medium">₹ Cr</th>
              <th className="font-medium">Files</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-line/60">
                <td className="max-w-[240px] truncate py-0.5 pr-2">
                  {r.client ? (
                    <button type="button" className="truncate text-left text-fg hover:text-accent hover:underline" onClick={() => onHouse(r.client as string)} title="Open house track record">
                      {r.client}
                    </button>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="pr-2">
                  <Chip tone={r.clientele === 'FII' || r.clientele === 'DII' ? 'info' : r.clientele === 'PROP' || r.is_prop ? 'neutral' : 'violet'}>
                    {r.is_prop ? 'PROP' : (r.clientele ?? '—')}
                  </Chip>
                </td>
                <td className={cn('pr-2 font-semibold', r.side === 'BUY' ? 'text-up' : 'text-down')}>{r.side}</td>
                <td className="num pr-2 text-right">{fmtInt(r.quantity)}</td>
                <td className="num pr-2 text-right">{fmtNum(r.price, 2)}</td>
                <td className="num pr-2 text-right">{fmtNum(r.value_cr, 2)}</td>
                <td className="text-fg-3">{r.deal_types}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="mt-1 text-fg-3">
        {history.length} collapsed print{history.length === 1 ? '' : 's'} in this stock since deal history began (2026-04-29).
      </div>
    </div>
  );
}

const houseColumns: DataTableColumn<HousePrintRow>[] = [
  { id: 'date', header: 'Date', accessor: 'trade_date', format: 'date', width: 84 },
  { id: 'symbol', header: 'Symbol', accessor: 'symbol', width: 100, cell: (v) => <span className="font-mono text-fg">{String(v)}</span> },
  { id: 'side', header: 'Side', accessor: 'side', width: 50, cell: (v) => <span className={v === 'BUY' ? 'text-up' : 'text-down'}>{String(v)}</span> },
  { id: 'value', header: '₹ Cr', accessor: 'value_cr', format: 'num', digits: 2, width: 70 },
  { id: 'price', header: 'Price', accessor: 'price', format: 'num', digits: 2, width: 72 },
  { id: 'entry', header: 'Entry (next open)', accessor: 'entry_open', format: 'num', digits: 2, width: 100 },
  { id: 't5', header: 'T+5', accessor: 'fwd_t5_pct', format: 'signedPct', digits: 1, width: 60 },
  { id: 't20', header: 'T+20', accessor: 'fwd_t20_pct', format: 'signedPct', digits: 1, width: 60 },
  { id: 'ex20', header: 'vs index', accessor: 'excess_t20_pct', format: 'signed', digits: 1, width: 64, metricKey: 'deal_fwd_excess_t20' },
  { id: 'types', header: 'Files', accessor: 'deal_types', width: 84 },
];

export function HouseDrawer({ house, onClose }: { house: string | null; onClose: () => void }) {
  const shell = useShell();
  const q = useApiQuery('deals/house/{house_id}', { params: { house_id: house ?? '' }, query: { limit: 5000 } }, { enabled: !!house });
  const s = q.data?.meta.context?.summary as
    | { prints: number; buy_bets_with_t20: number; ranked: boolean; hit_rate_t20: number | null; avg_fwd_t20_pct: number | null; avg_excess_t20_pct: number | null; clientele: string[] }
    | undefined;
  return (
    <Drawer open={!!house} onClose={onClose} title={<span className="truncate">{house}</span>} width={680}>
      <div className="flex h-full min-h-0 flex-col">
        {q.error ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : q.isLoading || !s ? (
          <Skeleton className="m-3" height={80} />
        ) : (
          <>
            <div className="flex flex-wrap gap-x-6 gap-y-2 border-b border-line p-3">
              <div className="flex flex-col gap-0.5">
                <span className="text-2xs uppercase tracking-wide text-fg-3">Class</span>
                <span className="text-sm text-fg">{s.clientele.join(', ') || '—'}</span>
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-2xs uppercase tracking-wide text-fg-3">Prints</span>
                <span className="num text-sm text-fg">{s.prints}</span>
              </div>
              <MetricInline metricKey="sample_n" label="Buy bets with T+20" value={s.buy_bets_with_t20}>
                <span className="num text-sm text-fg">{s.buy_bets_with_t20}</span>
              </MetricInline>
              <MetricInline metricKey="house_hit_rate_t20" label="Hit rate T+20" value={s.hit_rate_t20}>
                <ZoneNum metricKey="house_hit_rate_t20" value={s.hit_rate_t20} format="pct" digits={0} className="text-sm" />
              </MetricInline>
              <MetricInline metricKey="deal_fwd_excess_t20" label="Avg T+20" value={s.avg_excess_t20_pct}>
                <span className="text-sm">
                  <span className="num text-fg">{fmtSignedPct(s.avg_fwd_t20_pct, 1)}</span>
                  <span className="ml-1 text-2xs text-fg-3">vs index </span>
                  <ZoneNum metricKey="deal_fwd_excess_t20" value={s.avg_excess_t20_pct} format="signed" digits={1} />
                </span>
              </MetricInline>
              <div className="flex items-end">
                {s.ranked ? <Chip tone="info">ranked</Chip> : <Chip title="Needs ≥ 5 buy bets with a finished T+20 window; individuals and PROP desks are never ranked">not ranked</Chip>}
              </div>
            </div>
            <div className="px-3 py-1 text-2xs text-fg-3">
              {(q.data?.meta.notes ?? []).join(' ')} Click a row to open the stock.
            </div>
            <DataTable
              label={`${house} prints`}
              columns={houseColumns}
              rows={q.data?.rows ?? []}
              total={q.data?.total ?? null}
              getRowId={(r, i) => `${r.trade_date}-${r.symbol}-${r.side}-${i}`}
              onRowClick={(r) => {
                if (!r.symbol) return;
                onClose();
                shell.openSymbol(r.symbol);
              }}
              emptyState={<EmptyState title="No prints" />}
              className="min-h-0 flex-1"
            />
          </>
        )}
      </div>
    </Drawer>
  );
}
