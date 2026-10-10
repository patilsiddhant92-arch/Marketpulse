/**
 * Chart — lightweight-charts v5 wrapper (spec 9, 7.7, 7.8).
 *
 * Panes: 0 = candles + EMAs + overlays, 1 = volume coloured by delivery %,
 * 2 = RS line (optional). D/W/M toggle (client-side resample of daily bars
 * unless the caller supplies per-timeframe bars), corporate-action / results /
 * deal markers, date-synced crosshair across charts sharing `syncGroup`,
 * ResizeObserver sizing. Colours come from design tokens.
 *
 * Charts-tab additions (all optional, off by default, so existing callers are unchanged):
 * per-bar candle colours (event candles), volume candles (priceStyle 'volume'), a 20-bar
 * volume average line, an RSI pane, straight segments on the price / RSI pane (trend,
 * divergence and deal-price lines), horizontal levels, coloured markers, a click callback
 * for drawing tools and a per-bar note in the legend.
 */
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  LineType,
  PriceScaleMode,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type WhitespaceData,
} from 'lightweight-charts';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { cn } from '../lib/cn';
import { fmtCompactIN, fmtDate, fmtNum, fmtPct, fmtSignedPct } from '../lib/fmt';
import { ema, resampleBars, rsi as rsiCalc, sma, type OHLCBar } from '../lib/indicators';
import { tokenColor, type TokenName } from '../lib/tokens';
import type { DarvasLines, DarvasPoint } from './darvasModel';
import { NARROW_CHART_PX, VolumeCandleSeries, volumeAlpha, volumeWidth, withAlpha, type VolumeCandleData } from './volumeCandleSeries';

export type { DarvasLines } from './darvasModel';

export type Timeframe = 'D' | 'W' | 'M';

export type ChartMarkerKind =
  | 'split'
  | 'bonus'
  | 'results'
  | 'ex_date'
  | 'demerger'
  | 'deal_buy'
  | 'deal_sell'
  | 'custom';

export interface ChartMarker {
  time: string; // YYYY-MM-DD
  kind: ChartMarkerKind;
  /** Short label drawn next to the marker (1-3 chars recommended). */
  text?: string;
  /** Overrides for the kind's default style (event candles). */
  color?: string;
  position?: 'aboveBar' | 'belowBar' | 'inBar';
  shape?: 'circle' | 'square' | 'arrowUp' | 'arrowDown';
}

/** A straight line between two points on the price or RSI pane. */
export interface ChartSegment {
  id: string;
  pane: 'price' | 'rsi';
  from: { time: string; value: number };
  to: { time: string; value: number };
  /** CSS colour. */
  color: string;
  dashed?: boolean;
  width?: 1 | 2 | 3 | 4;
  /** Show the end value + label on the price axis. */
  axisLabel?: string;
}

/** A horizontal level drawn across the whole price pane (drawing tool / alert line). */
export interface ChartLevel {
  id: string;
  price: number;
  color: string;
  title?: string;
  dashed?: boolean;
}

export interface LinePoint {
  time: string;
  value: number | null;
}

export interface ChartOverlay {
  id: string;
  label: string;
  data: LinePoint[];
  color?: TokenName;
  dashed?: boolean;
  /** Show the level's value + label on the price axis (trigger / stop). */
  axisLabel?: boolean;
}

export interface ChartProps {
  /** Adjusted daily (or timeframe-specific) bars, oldest first. */
  bars: readonly OHLCBar[];
  timeframe?: Timeframe;
  /** Show the D/W/M toggle; omit to hide it. */
  onTimeframeChange?: (tf: Timeframe) => void;
  /** Resample daily bars client-side for W/M (default true). Set false if `bars` already match `timeframe`. */
  resample?: boolean;
  /** EMA periods computed client-side from displayed closes (default 10/20/50/200). */
  emaPeriods?: readonly number[];
  /** Server-provided lines on the price pane (Darvas box, pivots...). */
  overlays?: readonly ChartOverlay[];
  /**
   * Pine Darvas lines: TopBox / BottomBox step lines, dotted top box extension and
   * (when EMA 10 is shown) dotted EMA10 projection, both 5 bars past the last candle.
   */
  darvas?: DarvasLines | null;
  /** Volume pane coloured by delivery % (default true). */
  volume?: boolean;
  /** RS line pane; `newHighs` marks RS new-high sessions. */
  rs?: { label: string; data: readonly (LinePoint & { new_high?: boolean | null })[] } | null;
  markers?: readonly ChartMarker[];
  /** Charts with the same group share a date-synced crosshair. */
  syncGroup?: string;
  /** Also sync pan / zoom (visible date range) across the group (old Tiles window "Sync ON"). */
  syncRange?: boolean;
  /**
   * 'line' draws a close line instead of candles (old Tiles window Candles / Line toggle).
   * 'volume' draws volume candles: body width ∝ volume vs its 20-bar average (TradingView style).
   */
  priceStyle?: 'candles' | 'line' | 'volume';
  /** Whole-candle colours (event candles), snapped onto displayed bars; the first entry per bar wins. */
  candleColors?: readonly { time: string; color: string }[];
  /** 20-bar average volume line on the volume pane. */
  volumeAvg?: boolean;
  /** RSI pane (last pane), computed on displayed closes; 70 / 50 / 30 guide lines. */
  rsi?: { period?: number } | null;
  /** Straight segments (trend lines, divergence lines, deal-price lines). */
  segments?: readonly ChartSegment[];
  /** Horizontal levels across the price pane. */
  levels?: readonly ChartLevel[];
  /** Click on the price pane: nearest displayed bar time and the price under the cursor. */
  onPriceClick?: (p: { time: string; price: number }) => void;
  /** Extra legend text for the hovered (or last) bar, e.g. the event on it. */
  barNote?: (time: string) => string | null;
  /**
   * Keep the zoom when the bars change (a new symbol from J / K): the same number of bars stays
   * visible, anchored on the latest bar. The first data of a chart still uses `initialBars`.
   */
  keepRange?: boolean;
  logScale?: boolean;
  /** Lower pane heights in px (defaults: volume 90 / 70 with RS, RS 80, RSI 90). */
  paneHeights?: { volume?: number; rs?: number; rsi?: number };
  /** Fixed height in px; default fills the parent. */
  height?: number;
  /** Visible bars on first render (default 150). */
  initialBars?: number;
  showLegend?: boolean;
  onCrosshairTime?: (time: string | null) => void;
  /** Accessible name, e.g. "HAL daily chart". */
  label: string;
  className?: string;
}

const EMA_COLORS: Record<number, TokenName> = { 10: 'ema-10', 20: 'ema-20', 50: 'ema-50', 200: 'ema-200' };
const DEFAULT_EMAS = [10, 20, 50, 200] as const;

type DarvasLineKey = 'top' | 'bottom' | 'topExtension' | 'emaProjection';

// ------------------------------------------------------------------ crosshair sync bus

interface SyncMember {
  id: number;
  setTime: (time: string | null) => void;
}
const syncGroups = new Map<string, Set<SyncMember>>();
let syncSeq = 1;

function joinSync(group: string, member: SyncMember): () => void {
  let set = syncGroups.get(group);
  if (!set) {
    set = new Set();
    syncGroups.set(group, set);
  }
  set.add(member);
  return () => {
    set!.delete(member);
    if (set!.size === 0) syncGroups.delete(group);
  };
}

function broadcast(group: string, fromId: number, time: string | null) {
  syncGroups.get(group)?.forEach((m) => {
    if (m.id !== fromId) m.setTime(time);
  });
}

// ------------------------------------------------------------------ pan / zoom (date range) sync bus

interface RangeMember {
  id: number;
  setRange: (from: string, to: string) => void;
}
const rangeGroups = new Map<string, Set<RangeMember>>();

function joinRange(group: string, member: RangeMember): () => void {
  let set = rangeGroups.get(group);
  if (!set) {
    set = new Set();
    rangeGroups.set(group, set);
  }
  set.add(member);
  return () => {
    set!.delete(member);
    if (set!.size === 0) rangeGroups.delete(group);
  };
}

function broadcastRange(group: string, fromId: number, from: string, to: string) {
  rangeGroups.get(group)?.forEach((m) => {
    if (m.id !== fromId) m.setRange(from, to);
  });
}

// ------------------------------------------------------------------ helpers

function timeToISO(t: Time | undefined): string | null {
  if (t === undefined) return null;
  if (typeof t === 'string') return t;
  if (typeof t === 'number') return new Date(t * 1000).toISOString().slice(0, 10);
  return `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`;
}

/** Index of the first bar whose time >= iso (bars sorted); -1 if none. */
function firstBarAtOrAfter(bars: readonly OHLCBar[], iso: string): number {
  let lo = 0;
  let hi = bars.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (bars[mid].time >= iso) {
      ans = mid;
      hi = mid - 1;
    } else lo = mid + 1;
  }
  return ans;
}

/** Index of the last bar whose time <= iso; -1 if none. */
function lastBarAtOrBefore(bars: readonly OHLCBar[], iso: string): number {
  let lo = 0;
  let hi = bars.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (bars[mid].time <= iso) {
      ans = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return ans;
}

function markerStyle(kind: ChartMarkerKind): Pick<SeriesMarker<Time>, 'position' | 'shape' | 'color'> & { text: string } {
  switch (kind) {
    case 'split':
      return { position: 'belowBar', shape: 'square', color: tokenColor('violet'), text: 'S' };
    case 'bonus':
      return { position: 'belowBar', shape: 'square', color: tokenColor('violet'), text: 'B' };
    case 'demerger':
      return { position: 'belowBar', shape: 'square', color: tokenColor('warn'), text: 'D' };
    case 'results':
      return { position: 'aboveBar', shape: 'circle', color: tokenColor('info'), text: 'R' };
    case 'ex_date':
      return { position: 'belowBar', shape: 'circle', color: tokenColor('warn'), text: 'X' };
    case 'deal_buy':
      return { position: 'belowBar', shape: 'arrowUp', color: tokenColor('up'), text: '' };
    case 'deal_sell':
      return { position: 'aboveBar', shape: 'arrowDown', color: tokenColor('down'), text: '' };
    default:
      return { position: 'aboveBar', shape: 'circle', color: tokenColor('fg-3'), text: '' };
  }
}

/** Volume bar colour: direction hue, opacity scaled by delivery % (NULL = faint). */
function volumeColor(bar: OHLCBar): string {
  const up = bar.close >= bar.open;
  const d = bar.delivery_pct;
  const alpha = d == null ? 0.25 : Math.min(0.9, 0.25 + (Math.max(0, Math.min(100, d)) / 100) * 0.8);
  return tokenColor(up ? 'up' : 'down', Number(alpha.toFixed(2)));
}

interface Legend {
  bar: OHLCBar;
  change: number | null;
  rs: number | null;
}

// ------------------------------------------------------------------ component

export function Chart({
  bars,
  timeframe = 'D',
  onTimeframeChange,
  resample = true,
  emaPeriods = DEFAULT_EMAS,
  overlays,
  darvas,
  volume = true,
  rs,
  markers,
  syncGroup,
  syncRange = false,
  priceStyle = 'candles',
  logScale = false,
  paneHeights,
  height,
  initialBars = 150,
  showLegend = true,
  onCrosshairTime,
  label,
  className,
  candleColors,
  volumeAvg = false,
  rsi,
  segments,
  levels,
  onPriceClick,
  barNote,
  keepRange = false,
}: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const closeLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const ignoreRangeUntil = useRef(0);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const emaRefs = useRef<Map<number, ISeriesApi<'Line'>>>(new Map());
  const overlayRefs = useRef<Map<string, ISeriesApi<'Line'>>>(new Map());
  const rsRef = useRef<ISeriesApi<'Line'> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const darvasRefs = useRef<Record<DarvasLineKey, ISeriesApi<'Line'>> | null>(null);
  const rsMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const volCandleRef = useRef<ISeriesApi<'Custom', Time, VolumeCandleData | WhitespaceData<Time>> | null>(null);
  const volAvgRef = useRef<ISeriesApi<'Line'> | null>(null);
  const rsiRef = useRef<ISeriesApi<'Line'> | null>(null);
  const segmentRefs = useRef<ISeriesApi<'Line'>[]>([]);
  const levelRefs = useRef<IPriceLine[]>([]);
  const onPriceClickRef = useRef(onPriceClick);
  const [structureSeq, setStructureSeq] = useState(0);
  const rangeSetRef = useRef(false);
  const syncIdRef = useRef(syncSeq++);
  const suppressRef = useRef(false);
  const onCrosshairRef = useRef(onCrosshairTime);
  const [hoverLegend, setHoverLegend] = useState<Legend | null>(null);

  useEffect(() => {
    onCrosshairRef.current = onCrosshairTime;
    onPriceClickRef.current = onPriceClick;
  });

  const shown = useMemo(() => (resample ? resampleBars(bars, timeframe) : bars.slice()), [bars, timeframe, resample]);
  const rsByTime = useMemo(() => {
    const m = new Map<string, number | null>();
    rs?.data.forEach((p) => m.set(p.time, p.value));
    return m;
  }, [rs]);
  // Latest values for chart callbacks (which are created once per structure).
  const shownRef = useRef(shown);
  const rsByTimeRef = useRef(rsByTime);
  useLayoutEffect(() => {
    shownRef.current = shown;
    rsByTimeRef.current = rsByTime;
  });

  /** Legend: hovered bar, else the last bar. */
  const legend = useMemo<Legend | null>(() => {
    if (hoverLegend) return hoverLegend;
    const n = shown.length;
    const last = shown[n - 1];
    if (!last) return null;
    const prev = shown[n - 2];
    return { bar: last, change: prev ? ((last.close - prev.close) / prev.close) * 100 : null, rs: rsByTime.get(last.time) ?? null };
  }, [hoverLegend, shown, rsByTime]);

  const emaKey = emaPeriods.join(',');
  const overlayKey = (overlays ?? []).map((o) => `${o.id}:${o.color ?? ''}:${o.dashed ? 1 : 0}:${o.axisLabel ? 1 : 0}`).join('|');
  const hasRs = !!rs;
  const withFuture = darvas !== undefined;
  const hasEma10 = emaPeriods.includes(10);
  const hasRsi = !!rsi;
  const rsiPeriod = rsi?.period ?? 14;

  // ---- create chart + series (structure changes rebuild)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      width: el.clientWidth || 600,
      height: el.clientHeight || height || 360,
      layout: {
        background: { type: ColorType.Solid, color: tokenColor('surface') },
        textColor: tokenColor('fg-3'),
        fontFamily: getComputedStyle(document.documentElement).getPropertyValue('--font-mono') || 'monospace',
        fontSize: 11,
        attributionLogo: false,
        panes: { separatorColor: tokenColor('line'), separatorHoverColor: tokenColor('line-strong'), enableResize: true },
      },
      grid: { vertLines: { color: tokenColor('chart-grid') }, horzLines: { color: tokenColor('chart-grid') } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: tokenColor('line'), mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal },
      timeScale: { borderColor: tokenColor('line'), rightOffset: 4, minBarSpacing: 0.5 },
      localization: { locale: 'en-IN' },
    });
    chartRef.current = chart;

    // Line mode keeps the candle series (markers, boxes, crosshair and price scale live on it) but
    // makes it transparent, and draws the closes as a line on top.
    const line = priceStyle === 'line' || priceStyle === 'volume';
    const clear = 'rgba(0,0,0,0)';
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: line ? clear : tokenColor('up'),
      downColor: line ? clear : tokenColor('down'),
      borderUpColor: line ? clear : tokenColor('up'),
      borderDownColor: line ? clear : tokenColor('down'),
      wickUpColor: line ? clear : tokenColor('up'),
      wickDownColor: line ? clear : tokenColor('down'),
      priceLineVisible: false,
      lastValueVisible: !line,
    });
    closeLineRef.current =
      priceStyle === 'line'
        ? chart.addSeries(LineSeries, { color: tokenColor('info'), lineWidth: 2, priceLineVisible: false, crosshairMarkerVisible: true })
        : null;
    volCandleRef.current =
      priceStyle === 'volume'
        ? chart.addCustomSeries(new VolumeCandleSeries(), { priceLineVisible: false, lastValueVisible: true, title: '' })
        : null;
    markersRef.current = createSeriesMarkers(candleRef.current, []);

    emaRefs.current = new Map();
    for (const p of emaPeriods) {
      emaRefs.current.set(
        p,
        chart.addSeries(LineSeries, {
          color: tokenColor(EMA_COLORS[p] ?? 'fg-3', 0.9),
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: '',
        }),
      );
    }
    overlayRefs.current = new Map();
    for (const o of overlays ?? []) {
      overlayRefs.current.set(
        o.id,
        chart.addSeries(LineSeries, {
          color: tokenColor(o.color ?? 'accent'),
          lineWidth: 1,
          lineStyle: o.dashed ? LineStyle.Dashed : LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: !!o.axisLabel,
          title: o.axisLabel ? o.label : '',
          crosshairMarkerVisible: false,
        }),
      );
    }

    // Pine Darvas: TopBox green / BottomBox red, 50% transparent, width 3, step lines;
    // dotted top extension (width 2) and dotted EMA10 projection (width 3, EMA-10 colour).
    const quiet = { priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: '' } as const;
    darvasRefs.current = {
      top: chart.addSeries(LineSeries, { ...quiet, color: tokenColor('up', 0.5), lineWidth: 3, lineType: LineType.WithSteps }),
      bottom: chart.addSeries(LineSeries, { ...quiet, color: tokenColor('down', 0.5), lineWidth: 3, lineType: LineType.WithSteps }),
      topExtension: chart.addSeries(LineSeries, { ...quiet, color: tokenColor('up'), lineWidth: 2, lineStyle: LineStyle.Dotted }),
      emaProjection: chart.addSeries(LineSeries, {
        ...quiet,
        color: tokenColor(EMA_COLORS[10], 0.9),
        lineWidth: 3,
        lineStyle: LineStyle.Dotted,
      }),
    };

    volumeRef.current = null;
    volAvgRef.current = null;
    if (volume) {
      volumeRef.current = chart.addSeries(
        HistogramSeries,
        { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false },
        1,
      );
      if (volumeAvg) {
        volAvgRef.current = chart.addSeries(
          LineSeries,
          {
            color: tokenColor('fg-2', 0.7),
            lineWidth: 1,
            priceFormat: { type: 'volume' },
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          },
          1,
        );
      }
    }
    rsRef.current = null;
    rsMarkersRef.current = null;
    if (hasRs) {
      rsRef.current = chart.addSeries(
        LineSeries,
        { color: tokenColor('accent'), lineWidth: 1, priceLineVisible: false, lastValueVisible: true },
        volume ? 2 : 1,
      );
      rsMarkersRef.current = createSeriesMarkers(rsRef.current, []);
    }
    rsiRef.current = null;
    const rsiPane = 1 + (volume ? 1 : 0) + (hasRs ? 1 : 0);
    if (hasRsi) {
      const r = chart.addSeries(
        LineSeries,
        {
          color: tokenColor('violet'),
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: false,
          priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
          autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
        },
        rsiPane,
      );
      for (const [lvl, alpha] of [
        [70, 0.6],
        [50, 0.3],
        [30, 0.6],
      ] as const) {
        r.createPriceLine({
          price: lvl,
          color: tokenColor('fg-3', alpha),
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: false,
          title: '',
        });
      }
      rsiRef.current = r;
    }
    const panes = chart.panes();
    if (panes[1]) panes[1].setHeight(volume ? (paneHeights?.volume ?? (hasRs ? 70 : 90)) : hasRs ? (paneHeights?.rs ?? 80) : (paneHeights?.rsi ?? 90));
    if (panes[2]) panes[2].setHeight(volume && hasRs ? (paneHeights?.rs ?? 80) : (paneHeights?.rsi ?? 90));
    if (panes[3]) panes[3].setHeight(paneHeights?.rsi ?? 90);

    // ---- click on the price pane (drawing tools)
    const onClick = (param: MouseEventParams<Time>) => {
      const cb = onPriceClickRef.current;
      const series = candleRef.current;
      if (!cb || !series || !param.point || (param.paneIndex ?? 0) !== 0) return;
      const price = series.coordinateToPrice(param.point.y);
      const data = shownRef.current;
      let iso = timeToISO(param.time);
      if (!iso && param.logical != null && data.length) {
        const i = Math.max(0, Math.min(data.length - 1, Math.round(param.logical)));
        iso = data[i].time;
      }
      if (price == null || !iso) return;
      cb({ time: iso, price: Number(price) });
    };
    chart.subscribeClick(onClick);

    // ---- crosshair: legend + sync
    const onMove = (param: MouseEventParams<Time>) => {
      const iso = timeToISO(param.time);
      const data = shownRef.current;
      const idx = iso ? lastBarAtOrBefore(data, iso) : -1;
      const bar = idx >= 0 ? data[idx] : undefined;
      if (bar) {
        const prev = idx > 0 ? data[idx - 1] : undefined;
        setHoverLegend({
          bar,
          change: prev ? ((bar.close - prev.close) / prev.close) * 100 : null,
          rs: rsByTimeRef.current.get(bar.time) ?? null,
        });
      } else setHoverLegend(null);
      if (suppressRef.current) return;
      onCrosshairRef.current?.(iso);
      if (syncGroup) broadcast(syncGroup, syncIdRef.current, iso);
    };
    chart.subscribeCrosshairMove(onMove);

    const leaveSync = syncGroup
      ? joinSync(syncGroup, {
          id: syncIdRef.current,
          setTime: (iso) => {
            const c = chartRef.current;
            const series = candleRef.current;
            if (!c || !series) return;
            suppressRef.current = true;
            try {
              if (!iso) c.clearCrosshairPosition();
              else {
                const data = shownRef.current;
                const i = lastBarAtOrBefore(data, iso);
                if (i >= 0) c.setCrosshairPosition(data[i].close, data[i].time as Time, series);
                else c.clearCrosshairPosition();
              }
            } finally {
              suppressRef.current = false;
            }
          },
        })
      : undefined;

    // ---- pan / zoom sync (dates, so stocks with different histories line up)
    const onRange = (r: { from: Time; to: Time } | null) => {
      if (!syncGroup || !syncRange || !r || performance.now() < ignoreRangeUntil.current) return;
      const from = timeToISO(r.from);
      const to = timeToISO(r.to);
      if (from && to) broadcastRange(syncGroup, syncIdRef.current, from, to);
    };
    const leaveRange =
      syncGroup && syncRange
        ? joinRange(syncGroup, {
            id: syncIdRef.current,
            setRange: (from, to) => {
              const c = chartRef.current;
              if (!c || shownRef.current.length === 0) return;
              ignoreRangeUntil.current = performance.now() + 200;
              try {
                c.timeScale().setVisibleRange({ from: from as Time, to: to as Time });
              } catch {
                /* range outside this chart's data */
              }
            },
          })
        : undefined;
    if (syncGroup && syncRange) chart.timeScale().subscribeVisibleTimeRangeChange(onRange);

    // ---- sizing
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r && r.width > 0 && r.height > 0) chart.resize(Math.floor(r.width), Math.floor(r.height));
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      leaveSync?.();
      leaveRange?.();
      if (syncGroup && syncRange) chart.timeScale().unsubscribeVisibleTimeRangeChange(onRange);
      chart.unsubscribeCrosshairMove(onMove);
      chart.unsubscribeClick(onClick);
      chart.remove();
      volCandleRef.current = null;
      volAvgRef.current = null;
      rsiRef.current = null;
      segmentRefs.current = [];
      levelRefs.current = [];
      chartRef.current = null;
      candleRef.current = null;
      closeLineRef.current = null;
      volumeRef.current = null;
      rsRef.current = null;
      markersRef.current = null;
      rsMarkersRef.current = null;
      darvasRefs.current = null;
    };
    rangeSetRef.current = false;
    setStructureSeq((n) => n + 1);
    // Rebuild only on structural change; data flows through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emaKey, overlayKey, volume, hasRs, syncGroup, syncRange, priceStyle, paneHeights?.volume, paneHeights?.rs, paneHeights?.rsi, volumeAvg, hasRsi]);

  // ---- log / linear without rebuild
  useEffect(() => {
    chartRef.current?.priceScale('right').applyOptions({ mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal });
  }, [logScale]);

  // ---- data
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !candleRef.current) return;
    // Event candle colours: snap each entry onto its displayed bar; the first entry per bar wins.
    const paint = new Map<string, string>();
    for (const c of candleColors ?? []) {
      const i = firstBarAtOrAfter(shown, c.time);
      if (i >= 0 && !paint.has(shown[i].time)) paint.set(shown[i].time, c.color);
    }
    const painted = priceStyle === 'candles';
    candleRef.current.setData(
      shown.map((b) => {
        const c = painted ? paint.get(b.time) : undefined;
        const base = { time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close };
        return c ? { ...base, color: c, borderColor: c, wickColor: c } : base;
      }),
    );
    if (volCandleRef.current) {
      const vavg = sma(shown.map((b) => b.volume ?? null), 20);
      // Narrow charts (phones, small tiles): colour intensity instead of width (09-tab-charts §4).
      const narrow = (containerRef.current?.clientWidth ?? NARROW_CHART_PX) < NARROW_CHART_PX;
      volCandleRef.current.setData(
        shown.map((b, i) => {
          // Average of the 20 bars before this one (a spike does not dilute its own baseline).
          const avg = i > 0 ? vavg[i - 1] : null;
          const base = paint.get(b.time) ?? tokenColor(b.close >= b.open ? 'up' : 'down');
          return {
            time: b.time as Time,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
            width: narrow ? 0.7 : volumeWidth(b.volume, avg),
            color: narrow ? withAlpha(base, volumeAlpha(b.volume, avg)) : base,
          };
        }),
      );
    }
    if (volAvgRef.current) {
      const vavg = sma(shown.map((b) => b.volume ?? null), 20);
      volAvgRef.current.setData(shown.flatMap((b, i) => (vavg[i] == null ? [] : [{ time: b.time as Time, value: vavg[i] as number }])));
    }
    if (rsiRef.current) {
      const r = rsiCalc(
        shown.map((b) => b.close),
        rsiPeriod,
      );
      rsiRef.current.setData(shown.flatMap((b, i) => (r[i] == null ? [] : [{ time: b.time as Time, value: r[i] as number }])));
    }
    closeLineRef.current?.setData(shown.map((b) => ({ time: b.time as Time, value: b.close })));

    const closes = shown.map((b) => b.close);
    emaRefs.current.forEach((series, period) => {
      const vals = ema(closes, period);
      series.setData(shown.flatMap((b, i) => (vals[i] == null ? [] : [{ time: b.time as Time, value: vals[i] as number }])));
    });

    (overlays ?? []).forEach((o) => {
      overlayRefs.current.get(o.id)?.setData(o.data.flatMap((p) => (p.value == null ? [] : [{ time: p.time as Time, value: p.value }])));
    });

    volumeRef.current?.setData(
      shown.map((b) => (b.volume == null ? { time: b.time as Time } : { time: b.time as Time, value: b.volume, color: volumeColor(b) })),
    );

    if (rsRef.current && rs) {
      rsRef.current.setData(rs.data.flatMap((p) => (p.value == null ? [] : [{ time: p.time as Time, value: p.value }])));
      rsMarkersRef.current?.setMarkers(
        rs.data
          .filter((p) => p.new_high && p.value != null)
          .map((p) => ({
            time: p.time as Time,
            position: 'inBar' as const,
            shape: 'circle' as const,
            color: tokenColor('accent'),
            size: 0.6,
          })),
      );
    }

    // Snap markers onto displayed bars (a weekly bar carries its week's events).
    const snapped: SeriesMarker<Time>[] = [];
    for (const m of markers ?? []) {
      const i = firstBarAtOrAfter(shown, m.time);
      if (i < 0) continue;
      const s = markerStyle(m.kind);
      snapped.push({
        time: shown[i].time as Time,
        position: m.position ?? s.position,
        shape: m.shape ?? s.shape,
        color: m.color ?? s.color,
        text: m.text ?? s.text,
      } as SeriesMarker<Time>);
    }
    snapped.sort((a, b) => String(a.time).localeCompare(String(b.time)));
    markersRef.current?.setMarkers(snapped);

    const lines = darvasRefs.current;
    if (lines) {
      const pts = (p: readonly DarvasPoint[] | undefined) => (p ?? []).map((x) => ({ time: x.time as Time, value: x.value }));
      lines.top.setData(pts(darvas?.top));
      lines.bottom.setData(pts(darvas?.bottom));
      lines.topExtension.setData(pts(darvas?.topExtension));
      lines.emaProjection.setData(hasEma10 ? pts(darvas?.emaProjection) : []);
    }
  }, [shown, overlays, darvas, hasEma10, rs, markers, emaKey, overlayKey, volume, hasRs, syncGroup, syncRange, priceStyle, paneHeights?.volume, paneHeights?.rs, candleColors, rsiPeriod, structureSeq]);

  // ---- segments (trend / divergence / deal-price lines) and levels: re-drawn on change, no rebuild
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    for (const s of segmentRefs.current) {
      try {
        chart.removeSeries(s);
      } catch {
        /* chart rebuilt */
      }
    }
    segmentRefs.current = [];
    const rsiPane = 1 + (volume ? 1 : 0) + (hasRs ? 1 : 0);
    for (const seg of segments ?? []) {
      if (seg.pane === 'rsi' && !hasRsi) continue;
      const a = firstBarAtOrAfter(shown, seg.from.time);
      const b = firstBarAtOrAfter(shown, seg.to.time);
      if (a < 0 || b < 0 || b <= a) continue;
      const line = chart.addSeries(
        LineSeries,
        {
          color: seg.color,
          lineWidth: seg.width ?? 1,
          lineStyle: seg.dashed ? LineStyle.Dashed : LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: !!seg.axisLabel,
          title: seg.axisLabel ?? '',
          crosshairMarkerVisible: false,
          autoscaleInfoProvider: () => null,
        },
        seg.pane === 'rsi' ? rsiPane : 0,
      );
      line.setData([
        { time: shown[a].time as Time, value: seg.from.value },
        { time: shown[b].time as Time, value: seg.to.value },
      ]);
      segmentRefs.current.push(line);
    }
  }, [segments, shown, structureSeq, volume, hasRs, hasRsi]);

  useEffect(() => {
    const series = candleRef.current;
    if (!series) return;
    for (const l of levelRefs.current) {
      try {
        series.removePriceLine(l);
      } catch {
        /* chart rebuilt */
      }
    }
    levelRefs.current = (levels ?? []).map((l) =>
      series.createPriceLine({
        price: l.price,
        color: l.color,
        lineWidth: 1,
        lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid,
        axisLabelVisible: true,
        title: l.title ?? '',
      }),
    );
  }, [levels, structureSeq]);

  // ---- initial visible range: only when the bars (or chart structure) change, so toggling
  // overlays / boxes keeps the user's zoom.
  useEffect(() => {
    const chart = chartRef.current;
    const n = shown.length;
    // Charts with Darvas projections leave room for the 5 future (candle-less) points.
    if (!chart || n === 0) return;
    const pad = withFuture ? 7 : 3;
    const cur = keepRange && rangeSetRef.current ? chart.timeScale().getVisibleLogicalRange() : null;
    const width = cur ? Math.max(10, cur.to - cur.from - pad) : initialBars;
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - width), to: n + pad });
    rangeSetRef.current = true;
  }, [shown, initialBars, withFuture, emaKey, overlayKey, volume, hasRs, syncGroup, syncRange, priceStyle, paneHeights?.volume, paneHeights?.rs, paneHeights?.rsi, volumeAvg, hasRsi, keepRange]);

  return (
    <div className={cn('relative flex min-h-0 flex-col', className)} style={height ? { height } : undefined}>
      {(onTimeframeChange || showLegend) && (
        <div className="flex h-7 shrink-0 items-center gap-3 border-b border-line bg-surface px-2 text-2xs">
          {onTimeframeChange && (
            <div className="flex overflow-hidden rounded border border-line" role="group" aria-label="Timeframe">
              {(['D', 'W', 'M'] as const).map((tf) => (
                <button
                  key={tf}
                  type="button"
                  aria-pressed={timeframe === tf}
                  onClick={() => onTimeframeChange(tf)}
                  className={cn(
                    'px-2 py-0.5 font-mono',
                    timeframe === tf ? 'bg-accent/20 text-accent' : 'text-fg-3 hover:bg-surface-3 hover:text-fg',
                  )}
                >
                  {tf}
                </button>
              ))}
            </div>
          )}
          {showLegend && legend && (
            <div className="num flex min-w-0 items-center gap-2.5 truncate text-fg-3" aria-live="off">
              <span className="text-fg-2">{fmtDate(legend.bar.time)}</span>
              <span>
                O <span className="text-fg">{fmtNum(legend.bar.open)}</span>
              </span>
              <span>
                H <span className="text-fg">{fmtNum(legend.bar.high)}</span>
              </span>
              <span>
                L <span className="text-fg">{fmtNum(legend.bar.low)}</span>
              </span>
              <span>
                C <span className="text-fg">{fmtNum(legend.bar.close)}</span>
              </span>
              <span className={legend.change == null ? '' : legend.change >= 0 ? 'text-up' : 'text-down'}>
                {fmtSignedPct(legend.change, 2)}
              </span>
              {volume && <span>Vol {fmtCompactIN(legend.bar.volume)}</span>}
              {volume && <span>Deliv {fmtPct(legend.bar.delivery_pct)}</span>}
              {rs && (
                <span>
                  {rs.label} {fmtNum(legend.rs)}
                </span>
              )}
              {emaPeriods.length > 0 && <span className="hidden xl:inline">EMA {emaPeriods.join('/')}</span>}
              {barNote && (() => {
                const note = barNote(legend.bar.time);
                return note ? <span className="truncate text-fg-2">{note}</span> : null;
              })()}
            </div>
          )}
        </div>
      )}
      <div ref={containerRef} role="img" aria-label={label} className="min-h-0 flex-1" />
    </div>
  );
}
