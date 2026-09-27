/**
 * Stock 360 (spec 7.7): one component, two layouts — the sidecar (narrow,
 * scrolling stack) and the full page (/stock/:sym, chart + right rail).
 */
import { ArrowLeft, ExternalLink, LayoutGrid, Star } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type PointerEvent } from 'react';
import { isUnavailable } from '../api/client';
import { cn } from '../lib/cn';
import { fmtDateWithDay } from '../lib/fmt';
import { readJSON, writeJSON } from '../lib/storage';
import { tradingViewChartUrl } from '../lib/tradingview';
import { useShell } from '../shell/ShellContext';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { DealsBlock, EventsBlock, NotesBlock } from './ListsBlocks';
import { DeliveryBlock, StrengthBlock, TrendBlock } from './MetricsBlock';
import { SetupsBlock } from './SetupsBlock';
import { StockChartPanel } from './StockChartPanel';
import { StockHeader } from './StockHeader';
import { useStock360 } from './useStock360';

function WatchButton({ symbol, withLabel }: { symbol: string; withLabel?: boolean }) {
  const shell = useShell();
  const on = shell.isWatched(symbol);
  return (
    <button
      type="button"
      onClick={() => shell.toggleWatch(symbol)}
      aria-pressed={on}
      title={shell.watchSync === 'error' ? 'Watchlist change not saved to the server' : 'Watchlist (W)'}
      className={cn(
        'inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs',
        on ? 'border-accent/40 bg-accent/10 text-accent' : 'border-line text-fg-2 hover:bg-surface-3',
      )}
    >
      <Star className={cn('h-3.5 w-3.5', on && 'fill-accent')} aria-hidden />
      {withLabel && (on ? 'Watching' : 'Watch')}
    </button>
  );
}

const CHART_FRAC_KEY = 'mp.sidecar.chart.v1';
const MIN_FRAC = 0.3;
const MAX_FRAC = 0.9;

/** Share of the sidecar body the chart takes (persisted per browser; default 68 %). */
function useChartFraction(): [number, (f: number) => void] {
  const [frac, setFrac] = useState(() => {
    const v = readJSON<number>(CHART_FRAC_KEY, 0.68);
    return typeof v === 'number' && Number.isFinite(v) ? Math.min(MAX_FRAC, Math.max(MIN_FRAC, v)) : 0.68;
  });
  const set = useCallback((f: number) => setFrac(Math.min(MAX_FRAC, Math.max(MIN_FRAC, f))), []);
  useEffect(() => writeJSON(CHART_FRAC_KEY, frac), [frac]);
  return [frac, set];
}

/** Body of the Stock 360 sidecar (the frame — resize/pin/close — is StockSidecar). */
export function Stock360Sidecar({ symbol }: { symbol: string }) {
  const shell = useShell();
  const data = useStock360(symbol);
  const { header } = data;
  const s = header.data?.rows[0];
  const [frac, setFrac] = useChartFraction();
  const bodyRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  if (header.error) return <ErrorState error={header.error} onRetry={() => void header.refetch()} />;
  if (header.data && isUnavailable(header.data))
    return <EmptyState title={`No data for ${symbol}`} detail={header.data.meta.reason ?? undefined} />;
  const onDrag = (e: PointerEvent) => {
    if (!dragging.current || !bodyRef.current) return;
    const r = bodyRef.current.getBoundingClientRect();
    if (r.height > 0) setFrac((e.clientY - r.top) / r.height);
  };
  return (
    <div ref={bodyRef} className="flex h-full min-h-0 flex-col" data-testid="stock360-sidecar">
      <div className="shrink-0 px-3 pb-1 pt-1.5">
        <StockHeader row={s} loading={header.isLoading} asOf={header.data?.as_of} compact />
      </div>
      <div className="min-h-[240px] shrink-0 overflow-hidden border-y border-line" style={{ height: `${Math.round(frac * 100)}%` }}>
        <StockChartPanel
          symbol={symbol}
          data={data}
          setups={s?.setups}
          className="h-full"
          initialBars={120}
          onExpand={() => shell.openBigChart(symbol)}
        />
      </div>
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize chart height"
        aria-valuenow={Math.round(frac * 100)}
        aria-valuemin={MIN_FRAC * 100}
        aria-valuemax={MAX_FRAC * 100}
        tabIndex={0}
        title="Drag to resize the chart (↑/↓ keys)"
        onPointerDown={(e) => {
          dragging.current = true;
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
        }}
        onPointerMove={onDrag}
        onPointerUp={() => {
          dragging.current = false;
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowUp') setFrac(frac - 0.04);
          if (e.key === 'ArrowDown') setFrac(frac + 0.04);
        }}
        className="group flex h-2 shrink-0 cursor-row-resize items-center justify-center hover:bg-accent/30"
      >
        <span className="h-0.5 w-10 rounded bg-line-strong group-hover:bg-accent" />
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
      <SetupsBlock setups={s?.setups} loading={header.isLoading} />
      {s && <StrengthBlock s={s} />}
      {s && <TrendBlock s={s} />}
      {s && <DeliveryBlock values={s.delivery_spark_60} />}
      <EventsBlock q={data.events} />
      <DealsBlock q={data.deals} />
      <NotesBlock symbol={symbol} />
      </div>
    </div>
  );
}

/** Full-page Stock 360. */
export function Stock360Page({ symbol }: { symbol: string }) {
  const shell = useShell();
  const data = useStock360(symbol);
  const { header } = data;
  const s = header.data?.rows[0];
  const unavailable = header.data && isUnavailable(header.data);
  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-bg">
      <header className="flex shrink-0 flex-wrap items-start gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-2">
        <button
          type="button"
          onClick={() => window.history.back()}
          className="mt-1 rounded p-1 text-fg-3 hover:bg-surface-3 hover:text-fg"
          aria-label="Back"
          title="Back"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="flex min-w-0 flex-1 items-start gap-4">
          <h1 className="mt-0.5 font-mono text-xl font-semibold text-fg">{symbol}</h1>
          <StockHeader row={s} loading={header.isLoading} asOf={header.data?.as_of} />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="num mr-2 text-2xs text-fg-3">as of {fmtDateWithDay(header.data?.as_of)}</span>
          <WatchButton symbol={symbol} withLabel />
          <button
            type="button"
            onClick={() => shell.openCharts([symbol])}
            className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3"
          >
            <LayoutGrid className="h-3.5 w-3.5" aria-hidden /> Charts
          </button>
          <a
            href={tradingViewChartUrl(symbol)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3"
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden /> TradingView
          </a>
        </div>
      </header>
      {header.error ? (
        <ErrorState error={header.error} onRetry={() => void header.refetch()} />
      ) : unavailable ? (
        <EmptyState title={`No data for ${symbol}`} detail={header.data?.meta.reason ?? undefined} />
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_360px] gap-2 p-2">
          <div className="flex min-w-0 flex-col gap-2">
            <div className="h-[max(560px,calc(100vh-200px))] shrink-0 overflow-hidden rounded border border-line">
              <StockChartPanel
                symbol={symbol}
                data={data}
                setups={s?.setups}
                className="h-full"
                initialBars={200}
                onExpand={() => shell.openBigChart(symbol)}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              {s && <StrengthBlock s={s} />}
              {s && <TrendBlock s={s} />}
              <EventsBlock q={data.events} />
              <DealsBlock q={data.deals} />
            </div>
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <SetupsBlock setups={s?.setups} loading={header.isLoading} />
            {s && <DeliveryBlock values={s.delivery_spark_60} />}
            <NotesBlock symbol={symbol} />
          </div>
        </div>
      )}
    </div>
  );
}

export { WatchButton };
