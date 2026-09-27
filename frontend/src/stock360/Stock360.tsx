/**
 * Stock 360 (spec 7.7): one component, two layouts — the sidecar (narrow,
 * scrolling stack) and the full page (/stock/:sym, chart + right rail).
 */
import { ArrowLeft, ExternalLink, LayoutGrid, Star } from 'lucide-react';
import { isUnavailable } from '../api/client';
import { cn } from '../lib/cn';
import { fmtDateWithDay } from '../lib/fmt';
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

/** Body of the Stock 360 sidecar (the frame — resize/pin/close — is StockSidecar). */
export function Stock360Sidecar({ symbol }: { symbol: string }) {
  const data = useStock360(symbol);
  const { header } = data;
  const s = header.data?.rows[0];
  if (header.error) return <ErrorState error={header.error} onRetry={() => void header.refetch()} />;
  if (header.data && isUnavailable(header.data))
    return <EmptyState title={`No data for ${symbol}`} detail={header.data.meta.reason ?? undefined} />;
  return (
    <div className="h-full space-y-2 overflow-y-auto p-2" data-testid="stock360-sidecar">
      <div className="px-1">
        <StockHeader row={s} loading={header.isLoading} asOf={header.data?.as_of} compact />
      </div>
      <div className="overflow-hidden rounded border border-line">
        <StockChartPanel symbol={symbol} data={data} setups={s?.setups} height={320} initialBars={90} />
      </div>
      <SetupsBlock setups={s?.setups} loading={header.isLoading} />
      {s && <StrengthBlock s={s} />}
      {s && <TrendBlock s={s} />}
      {s && <DeliveryBlock values={s.delivery_spark_60} />}
      <EventsBlock q={data.events} />
      <DealsBlock q={data.deals} />
      <NotesBlock symbol={symbol} />
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
            <div className="h-[560px] shrink-0 overflow-hidden rounded border border-line">
              <StockChartPanel symbol={symbol} data={data} setups={s?.setups} className="h-full" initialBars={180} />
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
