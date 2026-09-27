/**
 * One chart in the Charts grid. Loads bars only once the tile is on screen
 * (IntersectionObserver), shares the bar / RS cache with Stock 360 (same query
 * keys), draws trigger / stop lines for queue sources and shows the stock's
 * return vs the MidSml400 over the chosen window.
 */
import { Expand, Maximize2, Minimize2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useApiQuery } from '../api/query';
import { useChartPrefs } from '../lib/chartPrefs';
import { cn } from '../lib/cn';
import { fmtCr, fmtNum, fmtSignedPct } from '../lib/fmt';
import { ZoneNum, SignedNum } from '../screener/cells';
import { Chart, type ChartOverlay, type Timeframe } from '../ui/Chart';
import { Chip } from '../ui/Chip';
import { toChartBoxes } from '../ui/darvasModel';
import { DataWarningChip } from '../ui/DataWarningChip';
import { ErrorState } from '../ui/ErrorState';
import { Skeleton } from '../ui/Skeleton';
import { barsToOHLC, relativePerformance, type ChartItem } from './sources';

export const REL_WINDOWS = [
  { id: '1M', sessions: 21 },
  { id: '3M', sessions: 63 },
  { id: '6M', sessions: 126 },
] as const;

function useInView<T extends Element>(): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setSeen(true);
        io.disconnect();
      }
    });
    io.observe(el);
    return () => io.disconnect();
  }, [seen]);
  return [ref, seen];
}

const INITIAL_BARS: Record<Timeframe, number> = { D: 120, W: 104, M: 60 };

export interface ChartTileProps {
  item: ChartItem;
  timeframe: Timeframe;
  relWindow: (typeof REL_WINDOWS)[number]['id'];
  syncGroup: string;
  compact: boolean;
  /** Draw the volume / delivery pane (off for small tiles). */
  volume: boolean;
  active: boolean;
  expanded?: boolean;
  onInspect: (sym: string) => void;
  onToggleExpand: (sym: string) => void;
  /** Open the near-full-screen big chart for this symbol. */
  onOpenBig?: (sym: string) => void;
}

export function ChartTile({
  item,
  timeframe,
  relWindow,
  syncGroup,
  compact,
  volume,
  active,
  expanded,
  onInspect,
  onToggleExpand,
  onOpenBig,
}: ChartTileProps) {
  const [prefs, setPrefs] = useChartPrefs();
  const [ref, inView] = useInView<HTMLDivElement>();
  const sym = item.symbol;
  const bars = useApiQuery('stock/{sym}/bars', { params: { sym }, query: { tf: timeframe } }, { enabled: inView });
  const rs = useApiQuery('stock/{sym}/rs', { params: { sym } }, { enabled: inView });
  const darvas = useApiQuery('stock/{sym}/darvas', { params: { sym }, query: { tf: timeframe } }, { enabled: inView && prefs.darvas });

  const chartBars = useMemo(() => barsToOHLC(bars.data?.rows ?? []), [bars.data]);
  const last = chartBars[chartBars.length - 1];
  const prev = chartBars[chartBars.length - 2];
  const close = item.close ?? last?.close ?? null;
  // A served data_warning means an unexplained price gap: never re-derive the hidden % from bars.
  const change = item.change_1d_pct ?? (!item.data_warning && timeframe === 'D' && last && prev ? ((last.close - prev.close) / prev.close) * 100 : null);

  const rel = useMemo(() => {
    if (item.data_warning) return { stock: null, bench: null, excess: null };
    const w = REL_WINDOWS.find((x) => x.id === relWindow)?.sessions ?? 63;
    return relativePerformance(
      (rs.data?.rows ?? []).map((r) => ({ close: r.close, bench: r.midsml400_close })),
      w,
    );
  }, [rs.data, relWindow, item.data_warning]);

  const overlays = useMemo<ChartOverlay[]>(() => {
    if (chartBars.length === 0) return [];
    const span = chartBars.slice(-Math.min(chartBars.length, timeframe === 'D' ? 40 : 12));
    const line = (id: string, label: string, v: number | null | undefined, color: ChartOverlay['color'], dashed?: boolean) =>
      v == null ? [] : [{ id, label, color, dashed, data: span.map((b) => ({ time: b.time, value: v })) }];
    return [...line('trigger', 'Trigger', item.trigger_price, 'accent'), ...line('stop', 'Stop', item.stop_price, 'down', true)];
  }, [chartBars, item.trigger_price, item.stop_price, timeframe]);

  const boxes = useMemo(
    () => (prefs.darvas ? toChartBoxes(darvas.data?.rows, chartBars.map((b) => b.time)) : []),
    [prefs.darvas, darvas.data, chartBars],
  );

  const served = bars.data?.rows ?? [];
  const partial = served.length > 0 && served[served.length - 1].partial;

  return (
    <div
      ref={ref}
      className={cn('flex min-h-0 min-w-0 flex-col overflow-hidden rounded border bg-surface', active ? 'border-accent/70' : 'border-line')}
    >
      <div className="flex h-7 shrink-0 items-center gap-2 overflow-hidden whitespace-nowrap border-b border-line px-2 text-2xs">
        <button
          type="button"
          onClick={() => onInspect(sym)}
          title={`${item.name ?? sym} — open Stock 360 in the sidecar`}
          aria-label={`${sym}: open Stock 360`}
          className="font-mono text-xs font-semibold text-fg hover:text-accent"
        >
          {sym}
        </button>
        <span className="num text-fg">{fmtNum(close)}</span>
        <SignedNum value={change} digits={2} />
        <span className="flex items-center gap-1 text-fg-3" title="Strength rank (0–100)">
          RS <ZoneNum metricKey="rs_percentile" value={item.rs_percentile ?? null} digits={0} />
        </span>
        <span
          className="flex items-center gap-1 text-fg-3"
          title={
            item.data_warning
              ? item.data_warning
              : rel.excess == null
              ? 'Relative performance needs stock and MidSml400 closes'
              : `${relWindow}: stock ${fmtSignedPct(rel.stock, 1)} vs MidSml400 ${fmtSignedPct(rel.bench, 1)}`
          }
        >
          {relWindow} rel <SignedNum value={rel.excess} digits={1} />
        </span>
        {item.net_cr != null && (
          <span className="num text-fg-3">
            net <SignedNum value={item.net_cr} format="cr" digits={1} />
          </span>
        )}
        <span className="ml-auto flex min-w-0 items-center gap-1">
          {!compact &&
            item.tags.slice(0, 2).map((t) => (
              <Chip key={t} size="xs" tone={t === 'NEW' ? 'accent' : 'neutral'}>
                {t}
              </Chip>
            ))}
          <DataWarningChip warning={item.data_warning} />
          {partial && (
            <Chip size="xs" tone="warn" title="The last bar's week / month is not complete yet">
              partial
            </Chip>
          )}
          {expanded && (
            <button
              type="button"
              aria-pressed={prefs.darvas}
              onClick={() => setPrefs({ darvas: !prefs.darvas })}
              title="Darvas boxes"
              className={cn('rounded border border-line px-1.5', prefs.darvas ? 'bg-accent/20 text-accent' : 'text-fg-3 hover:text-fg')}
            >
              Darvas
            </button>
          )}
          {onOpenBig && (
            <button
              type="button"
              onClick={() => onOpenBig(sym)}
              aria-label={`Big chart ${sym}`}
              title="Big chart (F) — all indicators, J/K through this list"
              className="rounded p-0.5 text-fg-3 hover:bg-surface-3 hover:text-fg"
            >
              <Expand className="h-3 w-3" />
            </button>
          )}
          <button
            type="button"
            onClick={() => onToggleExpand(sym)}
            aria-label={expanded ? 'Back to grid' : `Expand ${sym}`}
            title={expanded ? 'Back to grid (Esc)' : 'Expand this chart (grid stays one click away)'}
            className="rounded p-0.5 text-fg-3 hover:bg-surface-3 hover:text-fg"
          >
            {expanded ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
          </button>
        </span>
      </div>
      <div className="relative min-h-0 flex-1" onDoubleClick={() => onToggleExpand(sym)}>
        {!inView || bars.isLoading ? (
          <Skeleton className="absolute inset-2" height="auto" />
        ) : bars.error ? (
          <ErrorState error={bars.error} onRetry={() => void bars.refetch()} compact />
        ) : chartBars.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-fg-3">
            {bars.data?.meta.reason ?? 'No bars for this date.'}
          </div>
        ) : (
          <Chart
            bars={chartBars}
            timeframe={timeframe}
            resample={false}
            overlays={overlays}
            boxes={boxes}
            volume={volume}
            syncGroup={syncGroup}
            initialBars={INITIAL_BARS[timeframe]}
            showLegend={!!expanded}
            label={`${sym} ${timeframe === 'D' ? 'daily' : timeframe === 'W' ? 'weekly' : 'monthly'} chart`}
            className="absolute inset-0"
          />
        )}
      </div>
      {expanded && item.market_cap_cr != null && (
        <div className="shrink-0 border-t border-line px-2 py-0.5 text-2xs text-fg-3">
          {item.industry ?? '—'} · mcap {fmtCr(item.market_cap_cr, 0)}
          {item.trigger_price != null && ` · trigger ${fmtNum(item.trigger_price)}`}
          {item.stop_price != null && ` · stop ${fmtNum(item.stop_price)}`}
        </div>
      )}
    </div>
  );
}
