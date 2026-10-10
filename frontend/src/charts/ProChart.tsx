/**
 * The main chart of the Charts tab (HarkPro/09-tab-charts.md §3): one symbol with every global
 * setting — EMAs, Pine Darvas, event candles + deal-price lines, volume (+ 20-bar average), RSI 14
 * with divergence lines, optional RS pane, drawings (H / T tools) — and the event legend.
 */
import { ExternalLink, Info, Star } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useApiQuery } from '../api/query';
import { useChartPrefs } from '../lib/chartPrefs';
import { cn } from '../lib/cn';
import { fmtNum } from '../lib/fmt';
import { tradingViewChartUrl } from '../lib/tradingview';
import { useShell } from '../shell/ShellContext';
import { SignedNum } from '../screener/cells';
import { Chart, type ChartOverlay, type Timeframe } from '../ui/Chart';
import { toDarvasLines } from '../ui/darvasModel';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { Skeleton } from '../ui/Skeleton';
import { RS_LABEL, rsSeries } from '../stock360/stockModel';
import { useChartLayers } from './chartLayers';
import { EventLegend } from './ChartControls';
import { addDrawing, clickTool, type DrawPoint, type DrawTool } from './drawings';
import { barsToOHLC, type ChartItem } from './sources';

export const PRO_BARS: Record<Timeframe, number> = { D: 1500, W: 520, M: 240 };
const INITIAL: Record<Timeframe, number> = { D: 200, W: 150, M: 90 };
const PANES = { volume: 90, rs: 80, rsi: 100 };

export interface ProChartProps {
  symbol: string;
  item?: ChartItem;
  tf: Timeframe;
  onTimeframeChange: (tf: Timeframe) => void;
  tool: DrawTool;
  onToolDone: () => void;
  onInfo: () => void;
  infoOpen: boolean;
  /** "3 / 40" position in the list. */
  position?: string;
  className?: string;
}

export function ProChart({ symbol, item, tf, onTimeframeChange, tool, onToolDone, onInfo, infoOpen, position, className }: ProChartProps) {
  const shell = useShell();
  const [prefs] = useChartPrefs();
  const [pending, setPending] = useState<DrawPoint | null>(null);
  const [pendingFor, setPendingFor] = useState({ symbol, tool });
  if (pendingFor.symbol !== symbol || pendingFor.tool !== tool) {
    // A new symbol or tool drops a half-drawn trend line.
    setPendingFor({ symbol, tool });
    setPending(null);
  }
  const limit = PRO_BARS[tf];
  // keepPrevious: J / K swaps the data under the same chart (zoom and panes stay), no skeleton flash.
  const bars = useApiQuery('stock/{sym}/bars', { params: { sym: symbol }, query: { tf, limit } }, { keepPrevious: true });
  const darvas = useApiQuery('stock/{sym}/darvas', { params: { sym: symbol }, query: { tf, limit } }, { keepPrevious: true });
  const rs = useApiQuery('stock/{sym}/rs', { params: { sym: symbol }, query: { limit: 5000 } }, { enabled: prefs.rsPane && tf === 'D' });

  const chartBars = useMemo(() => barsToOHLC(bars.data?.rows ?? []), [bars.data]);
  const times = useMemo(() => chartBars.map((b) => b.time), [chartBars]);
  const layers = useChartLayers(symbol, chartBars, tf, { darvas: darvas.data?.rows });
  const darvasLines = useMemo(() => toDarvasLines(darvas.data?.rows, times, { boxes: prefs.darvas }), [darvas.data, times, prefs.darvas]);
  const rsLine = useMemo(() => {
    if (!prefs.rsPane || tf !== 'D') return null;
    const pts = rsSeries(rs.data?.rows ?? [], prefs.bm);
    return pts.some((p) => p.value != null) ? { label: `${RS_LABEL[prefs.bm]} (rebased 100)`, data: pts } : null;
  }, [prefs.rsPane, prefs.bm, rs.data, tf]);

  const overlays = useMemo<ChartOverlay[]>(() => {
    if (!prefs.levels || !item || chartBars.length === 0) return [];
    const span = chartBars.slice(-Math.min(chartBars.length, tf === 'D' ? 40 : 12));
    const line = (id: string, label: string, v: number | null | undefined, color: ChartOverlay['color'], dashed?: boolean) =>
      v == null ? [] : [{ id, label, color, dashed, axisLabel: true, data: span.map((b) => ({ time: b.time, value: v })) }];
    return [...line('trigger', 'Trigger', item.trigger_price, 'accent'), ...line('stop', 'Stop', item.stop_price, 'down', true)];
  }, [prefs.levels, item, chartBars, tf]);

  const onPriceClick =
    tool === 'none'
      ? undefined
      : (p: DrawPoint) => {
          const r = clickTool(tool, pending, p);
          setPending(r.pending);
          if (r.done) {
            addDrawing(symbol, r.done);
            onToolDone();
          }
        };

  const last = chartBars[chartBars.length - 1];
  const prev = chartBars[chartBars.length - 2];
  const change = last && prev ? ((last.close - prev.close) / prev.close) * 100 : null;
  const watched = shell.isWatched(symbol);

  let body;
  if (bars.error) body = <ErrorState error={bars.error} onRetry={() => void bars.refetch()} />;
  else if (bars.isLoading) body = <Skeleton className="m-3" height="calc(100% - 1.5rem)" />;
  else if (!chartBars.length) body = <EmptyState title={`No bars for ${symbol}`} detail={bars.data?.meta.reason ?? undefined} />;
  else
    body = (
      <Chart
        bars={chartBars}
        resample={false}
        timeframe={tf}
        onTimeframeChange={onTimeframeChange}
        emaPeriods={layers.emaPeriods}
        overlays={overlays}
        darvas={darvasLines}
        volume={layers.volume}
        volumeAvg={layers.volumeAvg}
        rs={rsLine}
        rsi={layers.rsi}
        markers={layers.markers}
        candleColors={layers.candleColors}
        segments={layers.segments}
        levels={layers.levels}
        priceStyle={layers.priceStyle}
        logScale={prefs.bigLog}
        paneHeights={PANES}
        initialBars={INITIAL[tf]}
        onPriceClick={onPriceClick}
        barNote={layers.barNote}
        keepRange
        syncGroup="charts-main"
        label={`${symbol} ${tf === 'D' ? 'daily' : tf === 'W' ? 'weekly' : 'monthly'} chart`}
        className="min-h-0 flex-1"
      />
    );

  return (
    <div className={cn('flex min-h-0 min-w-0 flex-col', className)} data-testid="pro-chart">
      <div className="flex h-8 shrink-0 items-center gap-2 overflow-hidden whitespace-nowrap border-b border-line px-2 text-xs">
        <button
          type="button"
          onClick={onInfo}
          title={`${item?.name ?? symbol}: Stock 360 side panel (I)`}
          className="font-mono text-sm font-semibold text-fg hover:text-accent"
        >
          {symbol}
        </button>
        {item?.name && <span className="max-w-[220px] truncate text-fg-3">{item.name}</span>}
        <span className="num text-fg">{fmtNum(last?.close ?? null)}</span>
        {tf === 'D' && <SignedNum value={change} digits={2} />}
        {position && <span className="num text-2xs text-fg-3">{position}</span>}
        {tool !== 'none' && (
          <span className="rounded bg-accent/15 px-1.5 text-2xs text-accent">
            {tool === 'hline' ? 'Click a price for the line' : pending ? 'Click the second point' : 'Click the first point'} · Esc cancels
          </span>
        )}
        <span className="ml-auto flex items-center gap-1">
          <button
            type="button"
            aria-pressed={watched}
            onClick={() => shell.toggleWatch(symbol)}
            title="Star to the watchlist (S)"
            className={cn('rounded p-1', watched ? 'text-accent' : 'text-fg-3 hover:text-fg')}
          >
            <Star className={cn('h-3.5 w-3.5', watched && 'fill-accent')} />
          </button>
          <button
            type="button"
            aria-pressed={infoOpen}
            onClick={onInfo}
            title="Stock 360 side panel (I)"
            className={cn('rounded p-1', infoOpen ? 'text-accent' : 'text-fg-3 hover:text-fg')}
          >
            <Info className="h-3.5 w-3.5" />
          </button>
          <a href={tradingViewChartUrl(symbol)} target="_blank" rel="noopener noreferrer" title="Open in TradingView" className="rounded p-1 text-fg-3 hover:text-fg">
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </span>
      </div>
      <div className={cn('flex min-h-0 flex-1 flex-col', tool !== 'none' && 'cursor-crosshair')}>{body}</div>
      <EventLegend layers={layers} className="shrink-0 border-t border-line px-2 py-1" />
    </div>
  );
}
