import { useMemo, useState } from 'react';
import type { QueueRow } from '../api/types';
import { cn } from '../lib/cn';
import { Chart, type ChartMarker, type Timeframe } from '../ui/Chart';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { Skeleton } from '../ui/Skeleton';
import type { Stock360Data } from './useStock360';
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
  type RsBenchmark,
} from './stockModel';

export interface StockChartPanelProps {
  symbol: string;
  data: Stock360Data;
  setups: Record<string, QueueRow | null | undefined> | undefined;
  /** Fixed chart height (sidecar); omit to fill the parent. */
  height?: number;
  initialBars?: number;
  className?: string;
}

const seg = (on: boolean) =>
  cn('whitespace-nowrap px-2 py-0.5 font-mono text-2xs', on ? 'bg-accent/20 text-accent' : 'text-fg-3 hover:bg-surface-3 hover:text-fg');

/** Adjusted candles, delivery-coloured volume, EMAs, RS pane, event/deal markers, setup levels. */
export function StockChartPanel({ symbol, data, setups, height, initialBars, className }: StockChartPanelProps) {
  const [tf, setTf] = useState<Timeframe>('D');
  const [bm, setBm] = useState<RsBenchmark>('midsml400');
  const [levels, setLevels] = useState(true);
  const { bars, rs, events, deals, header } = data;

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
    const o = setupOverlays(setups, daily);
    return tf === 'D' ? o : snapOverlays(o, times);
  }, [levels, setups, daily, tf, times]);

  const hasLevels = !!setups && Object.values(setups).some(Boolean);

  const toolbar = (
    <div className="flex h-7 shrink-0 items-center gap-2 border-b border-line bg-surface px-2 text-2xs text-fg-3">
      <div className="flex shrink-0 overflow-hidden rounded border border-line" role="group" aria-label="Timeframe">
        {(['D', 'W', 'M'] as const).map((t) => (
          <button key={t} type="button" aria-pressed={tf === t} onClick={() => setTf(t)} className={seg(tf === t)}>
            {t}
          </button>
        ))}
      </div>
      <div className="flex shrink-0 overflow-hidden rounded border border-line" role="group" aria-label="RS benchmark">
        <button type="button" aria-pressed={bm === 'midsml400'} onClick={() => setBm('midsml400')} className={seg(bm === 'midsml400')}>
          RS MS400
        </button>
        <button type="button" aria-pressed={bm === 'nifty50'} onClick={() => setBm('nifty50')} className={seg(bm === 'nifty50')}>
          RS Nifty
        </button>
      </div>
      {hasLevels && (
        <button type="button" aria-pressed={levels} onClick={() => setLevels((v) => !v)} className={cn('shrink-0 rounded border border-line', seg(levels))}>
          Setup levels
        </button>
      )}
      <span className="ml-auto min-w-0 truncate" title="Markers: R results · B/S bonus/split · X ex-date · ▲▼ institutional deals · dots on RS = new RS high">
        R results · B/S bonus/split · ▲▼ inst. deals · ● RS high
      </span>
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
        rs={rsLine}
        markers={markers}
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
