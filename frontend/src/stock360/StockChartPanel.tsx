import { Expand } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useApiQuery } from '../api/query';
import type { QueueRow } from '../api/types';
import { useChartPrefs } from '../lib/chartPrefs';
import { cn } from '../lib/cn';
import { Chart, type ChartMarker, type Timeframe } from '../ui/Chart';
import { toChartBoxes } from '../ui/darvasModel';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { Skeleton } from '../ui/Skeleton';
import { FULL_HISTORY, type Stock360Data } from './useStock360';
import {
  adjustmentToMarker,
  barsFor,
  dealMarkers,
  eventToMarker,
  RS_LABEL,
  rsSeries,
  setupOverlays,
  snapOverlays,
  snapPoints,
  toOHLC,
} from './stockModel';

export interface StockChartPanelProps {
  symbol: string;
  data: Stock360Data;
  setups: Record<string, QueueRow | null | undefined> | undefined;
  /** Fixed chart height; omit to fill the parent. */
  height?: number;
  initialBars?: number;
  className?: string;
  /** Controlled timeframe (big chart keys D/W/M); uncontrolled when omitted. */
  timeframe?: Timeframe;
  onTimeframeChange?: (tf: Timeframe) => void;
  /** Show an "expand" button that opens the big chart. */
  onExpand?: () => void;
  /** Log price scale. */
  logScale?: boolean;
}

const seg = (on: boolean) =>
  cn('whitespace-nowrap px-2 py-0.5 font-mono text-2xs', on ? 'bg-accent/20 text-accent' : 'text-fg-3 hover:bg-surface-3 hover:text-fg');

/** Adjusted candles, delivery-coloured volume, EMAs, RS pane, Darvas boxes, event/deal markers, setup levels. */
export function StockChartPanel({
  symbol,
  data,
  setups,
  height,
  initialBars,
  className,
  timeframe,
  onTimeframeChange,
  onExpand,
  logScale,
}: StockChartPanelProps) {
  const [innerTf, setInnerTf] = useState<Timeframe>('D');
  const tf = timeframe ?? innerTf;
  const setTf = (t: Timeframe) => (onTimeframeChange ? onTimeframeChange(t) : setInnerTf(t));
  const [prefs, setPrefs] = useChartPrefs();
  const { bm, levels, darvas: showBoxes } = prefs;
  const { bars, rs, events, deals, header } = data;
  const darvas = useApiQuery(
    'stock/{sym}/darvas',
    { params: { sym: symbol }, query: { tf, limit: FULL_HISTORY } },
    { enabled: showBoxes },
  );

  const daily = useMemo(() => toOHLC(bars.data?.rows ?? []), [bars.data]);
  const shown = useMemo(() => barsFor(daily, tf), [daily, tf]);
  const times = useMemo(() => shown.map((b) => b.time), [shown]);

  const rsLine = useMemo(() => {
    const pts = rsSeries(rs.data?.rows ?? [], bm);
    if (!pts.some((p) => p.value != null)) return null;
    return { label: `${RS_LABEL[bm]} (rebased 100)`, data: tf === 'D' ? pts : snapPoints(pts, times) };
  }, [rs.data, bm, tf, times]);

  const markers = useMemo<ChartMarker[]>(
    () =>
      [
        ...(events.data?.rows ?? []).map(eventToMarker),
        ...(header.data?.rows[0]?.adjustments ?? []).map(adjustmentToMarker),
        ...dealMarkers(deals.data?.rows ?? []),
      ].filter((m): m is ChartMarker => m !== null),
    [events.data, header.data, deals.data],
  );

  const overlays = useMemo(() => {
    if (!levels) return [];
    const o = setupOverlays(setups, daily, { darvasBoxes: showBoxes });
    return tf === 'D' ? o : snapOverlays(o, times);
  }, [levels, setups, daily, tf, times, showBoxes]);

  const boxes = useMemo(() => (showBoxes ? toChartBoxes(darvas.data?.rows, times) : []), [showBoxes, darvas.data, times]);
  const activeBox = boxes.length > 0 && boxes[boxes.length - 1].active ? boxes[boxes.length - 1] : null;

  const hasLevels = !!setups && Object.values(setups).some(Boolean);

  const toolbar = (
    <div className="flex h-7 shrink-0 items-center gap-2 overflow-hidden border-b border-line bg-surface px-2 text-2xs text-fg-3">
      <div className="flex shrink-0 overflow-hidden rounded border border-line" role="group" aria-label="Timeframe">
        {(['D', 'W', 'M'] as const).map((t) => (
          <button key={t} type="button" aria-pressed={tf === t} onClick={() => setTf(t)} className={seg(tf === t)}>
            {t}
          </button>
        ))}
      </div>
      <div className="flex shrink-0 overflow-hidden rounded border border-line" role="group" aria-label="RS benchmark">
        <button type="button" aria-pressed={bm === 'midsml400'} onClick={() => setPrefs({ bm: 'midsml400' })} className={seg(bm === 'midsml400')}>
          RS MS400
        </button>
        <button type="button" aria-pressed={bm === 'nifty50'} onClick={() => setPrefs({ bm: 'nifty50' })} className={seg(bm === 'nifty50')}>
          RS Nifty
        </button>
      </div>
      <button
        type="button"
        aria-pressed={showBoxes}
        onClick={() => setPrefs({ darvas: !showBoxes })}
        title="Historical Darvas boxes (same box as the Darvas Squeeze queue): green top, red bottom, open box highlighted; BO / BD = breakout / breakdown close"
        className={cn('shrink-0 rounded border border-line', seg(showBoxes))}
      >
        Darvas boxes
      </button>
      {hasLevels && (
        <button
          type="button"
          aria-pressed={levels}
          onClick={() => setPrefs({ levels: !levels })}
          className={cn('shrink-0 rounded border border-line', seg(levels))}
        >
          Setup levels
        </button>
      )}
      {activeBox && (
        <span className="num shrink-0 text-fg-2" title="Open Darvas box (top / bottom)">
          box {activeBox.top.toFixed(2)} / {activeBox.bottom.toFixed(2)}
        </span>
      )}
      <span
        className="ml-auto min-w-0 truncate"
        title="Markers: BO/BD Darvas breakout/breakdown · R results · B/S bonus/split · X ex-date · ▲▼ institutional deals · dots on RS = new RS high"
      >
        BO/BD box break · R results · ▲▼ inst. deals · ● RS high
      </span>
      {onExpand && (
        <button
          type="button"
          onClick={onExpand}
          aria-label="Big chart"
          title="Big chart (F) — near full screen, J/K through the current list, Esc closes"
          className="flex shrink-0 items-center gap-1 rounded border border-line px-1.5 py-0.5 text-fg-2 hover:bg-surface-3 hover:text-fg"
        >
          <Expand className="h-3 w-3" aria-hidden /> Big
        </button>
      )}
    </div>
  );

  let body;
  if (bars.error) body = <ErrorState error={bars.error} onRetry={() => void bars.refetch()} />;
  else if (bars.isLoading) body = <Skeleton className="m-3" height={height ? height - 40 : 'calc(100% - 1.5rem)'} />;
  else if (daily.length === 0)
    body = <EmptyState title="No price history" detail={`The server returned no bars for ${symbol} on or before this date.`} />;
  else
    body = (
      <Chart
        bars={shown}
        resample={false}
        timeframe={tf}
        overlays={overlays}
        boxes={boxes}
        rs={rsLine}
        markers={markers}
        logScale={logScale}
        syncGroup={`stock360-${symbol}`}
        label={`${symbol} ${tf === 'D' ? 'daily' : tf === 'W' ? 'weekly' : 'monthly'} chart`}
        initialBars={initialBars ?? (tf === 'D' ? 150 : tf === 'W' ? 120 : 60)}
        className="min-h-0 flex-1"
      />
    );

  return (
    <div className={cn('flex min-h-0 flex-col', className)} style={height ? { height } : undefined}>
      {toolbar}
      {body}
    </div>
  );
}
