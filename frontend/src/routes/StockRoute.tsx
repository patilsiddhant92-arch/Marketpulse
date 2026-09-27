/**
 * Stock 360 full page (/stock/:sym). Header + chart read /api/v2 and render
 * honest empty/error states until the endpoints ship; the legacy inspector
 * sits alongside so nothing the user relies on disappears.
 */
import { useMemo, useState } from 'react';
import { useParams } from 'react-router';
import { InspectorSidecar } from '../components/InspectorSidecar';
import { useApiQuery } from '../api/query';
import type { BarRow, StockAdjustment, StockEventRow } from '../api/types';
import type { OHLCBar } from '../lib/indicators';
import { cn } from '../lib/cn';
import { fmtCr, fmtDateShort, fmtINR, fmtSignedPct } from '../lib/fmt';
import { useShell } from '../shell/ShellContext';
import { isSymbol } from '../shell/urlState';
import { Chart, type ChartMarker, type Timeframe } from '../ui/Chart';
import { Chip } from '../ui/Chip';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { Skeleton } from '../ui/Skeleton';
import { useLegacyProps } from './legacy';

/** Map served events onto chart marker kinds by their free-text type. */
export function eventToMarker(e: StockEventRow): ChartMarker | null {
  if (!e.event_date || !e.event_type) return null;
  const t = e.event_type.toLowerCase();
  if (t.includes('bonus')) return { time: e.event_date, kind: 'bonus' };
  if (t.includes('split')) return { time: e.event_date, kind: 'split' };
  if (t.includes('demerger')) return { time: e.event_date, kind: 'demerger' };
  if (t.includes('result') || t.includes('board')) return { time: e.event_date, kind: 'results' };
  if (t.includes('dividend') || t.includes('ex')) return { time: e.event_date, kind: 'ex_date' };
  return null;
}

function adjustmentToMarker(a: StockAdjustment): ChartMarker | null {
  if (!a.ex_date) return null;
  const k = (a.kind ?? '').toLowerCase();
  return { time: a.ex_date, kind: k === 'bonus' ? 'bonus' : k === 'split' ? 'split' : k === 'demerger' ? 'demerger' : 'custom' };
}

/** Served bars -> chart bars; rows missing a date or any OHLC value are dropped, never filled. */
export function toOHLC(rows: readonly BarRow[]): OHLCBar[] {
  return rows.flatMap((r) =>
    r.trade_date && r.open != null && r.high != null && r.low != null && r.close != null
      ? [
          {
            time: r.trade_date,
            open: r.open,
            high: r.high,
            low: r.low,
            close: r.close,
            volume: r.volume ?? null,
            delivery_pct: r.delivery_pct ?? null,
          },
        ]
      : [],
  );
}

export default function StockRoute() {
  const { sym = '' } = useParams();
  const symbol = sym.toUpperCase();
  const valid = isSymbol(symbol);
  const shell = useShell();
  const legacy = useLegacyProps();
  const [tf, setTf] = useState<Timeframe>('D');

  const stock = useApiQuery('stock/{sym}', { params: { sym: symbol } }, { enabled: valid });
  const bars = useApiQuery('stock/{sym}/bars', { params: { sym: symbol }, query: { tf: 'D' } }, { enabled: valid });
  const rs = useApiQuery('stock/{sym}/rs', { params: { sym: symbol } }, { enabled: valid && !!bars.data });
  const events = useApiQuery('stock/{sym}/events', { params: { sym: symbol } }, { enabled: valid && !!bars.data });

  const s = stock.data?.rows[0];
  const chartBars = useMemo(() => toOHLC(bars.data?.rows ?? []), [bars.data]);
  const markers = useMemo(
    () =>
      [...(events.data?.rows ?? []).map(eventToMarker), ...(s?.adjustments ?? []).map(adjustmentToMarker)].filter(
        (m): m is ChartMarker => m !== null,
      ),
    [events.data, s],
  );
  const rsSeries = useMemo(() => {
    const rows = rs.data?.rows ?? [];
    if (!rows.some((r) => r.rs_midsml400 != null)) return null;
    return {
      label: 'RS vs MidSml400',
      data: rows.flatMap((r) =>
        r.trade_date ? [{ time: r.trade_date, value: r.rs_midsml400 ?? null, new_high: r.rs_midsml400_new_high }] : [],
      ),
    };
  }, [rs.data]);

  if (!valid) return <EmptyState title="Invalid symbol" detail={`"${sym}" is not a valid NSE symbol.`} />;

  const adjusted = s?.adjustments?.filter((a) => a.kind === 'bonus' || a.kind === 'split') ?? [];
  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-line bg-surface px-4 py-2">
          <h1 className="font-mono text-lg font-semibold text-fg">{symbol}</h1>
          {stock.isLoading ? (
            <Skeleton width={240} height={12} />
          ) : s ? (
            <>
              <span className="text-xs text-fg-2">{s.security_name ?? ''}</span>
              <span className="num text-sm text-fg">{fmtINR(s.close)}</span>
              <span className={cn('num text-sm', s.change_1d_pct == null ? 'text-fg-3' : s.change_1d_pct >= 0 ? 'text-up' : 'text-down')}>
                {fmtSignedPct(s.change_1d_pct, 2)}
              </span>
              <span className="num text-xs text-fg-3">mcap {fmtCr(s.market_cap_cr, 0)}</span>
              {s.circuit_band != null && <Chip>band {s.circuit_band}%</Chip>}
              {s.stale_vs_as_of && <Chip tone="warn">stale vs as-of</Chip>}
              {s.taxonomy.length > 0 && (
                <span className="text-2xs text-fg-3">
                  {s.taxonomy
                    .map((t) => t.name)
                    .filter(Boolean)
                    .join(' › ')}
                </span>
              )}
              {adjusted.map((a) => (
                <Chip key={`${a.ex_date}-${a.kind}`} tone="violet" title={a.description ?? undefined}>
                  adjusted for {a.kind} {a.factor != null ? `×${a.factor}` : ''} on {fmtDateShort(a.ex_date)}
                </Chip>
              ))}
            </>
          ) : (
            <span className="text-xs text-fg-3">Stock header needs /api/v2/stock/{'{sym}'}.</span>
          )}
          <button
            type="button"
            onClick={() => shell.toggleWatch(symbol)}
            className="ml-auto rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3"
          >
            {shell.isWatched(symbol) ? '★ Watching' : '☆ Watch'}
          </button>
        </header>
        <div className="min-h-0 flex-1">
          {bars.error ? (
            <ErrorState error={bars.error} onRetry={() => void bars.refetch()} />
          ) : bars.isLoading ? (
            <Skeleton className="m-4" height="calc(100% - 2rem)" />
          ) : chartBars.length > 0 ? (
            <Chart
              bars={chartBars}
              timeframe={tf}
              onTimeframeChange={setTf}
              rs={rsSeries}
              markers={markers}
              syncGroup={`stock-${symbol}`}
              label={`${symbol} chart`}
              className="h-full"
            />
          ) : (
            <EmptyState title="No bars" detail="The server returned no price history for this symbol and date." />
          )}
        </div>
      </div>
      <div className="w-[420px] shrink-0 [&>aside]:!w-full">
        <InspectorSidecar
          symbol={symbol}
          onAddToBasket={legacy.onAddToBasket}
          isStaged={shell.isWatched(symbol)}
          onSelectSymbol={(s2) => shell.openStockPage(s2)}
          onOpenMultiChart={legacy.onOpenMultiChart}
        />
      </div>
    </div>
  );
}
