/**
 * Chart v2 engine: a lightweight-charts v5 wrapper that draws exactly what ChartV2 hands it, in
 * bar-index space. Pane 0 = price (candles / line / volume candles, line series, volume bars + the
 * 20-bar average in the bottom of the pane, axis tags, markers, the canvas scene). Pane 1 = RSI
 * (RSI, its SMA, 70 / 50 / 30 guides, divergence segments + labels).
 *
 * Premium behaviour: an OHLC + volume legend that follows the crosshair (the last bar by default),
 * wheel / pinch zoom and drag / touch pan with kinetic scrolling, and click / tap callbacks with the
 * bar index and the price under the pointer (candle story, drawing tools, bar replay).
 */
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
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
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '../lib/cn';
import type { OHLCBar } from '../lib/indicators';
import { tokenColor } from '../lib/tokens';
import { ScenePrimitive, type Shape } from './scene';
import { VolCandleSeries, type VolCandleData } from './volCandles';

export interface EngineLine {
  id: string;
  values: readonly (number | null)[];
  color: string;
  width?: 1 | 2 | 3;
  dashed?: boolean;
  /** Right-axis tag title (e.g. "E20"); omitted = no tag. */
  tag?: string;
  pane?: 'price' | 'rsi';
}

export interface EngineSegment {
  id: string;
  pane: 'price' | 'rsi';
  i1: number;
  v1: number;
  i2: number;
  v2: number;
  color: string;
  width?: 1 | 2 | 3;
  dashed?: boolean;
}

export interface EngineTag {
  id: string;
  price: number;
  color: string;
  title: string;
  /** Draw the line across the pane too (default: axis tag only). */
  line?: boolean;
  dashed?: boolean;
}

export interface EngineMarker {
  index: number;
  text: string;
  color: string;
  position: 'aboveBar' | 'belowBar' | 'inBar';
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown';
  size?: number;
}

export interface EnginePoint {
  index: number;
  time: string;
  price: number | null;
  pane: number;
  x: number;
  y: number;
}

export interface ChartEngineProps {
  bars: readonly OHLCBar[];
  style: 'candles' | 'line' | 'volume';
  /** Whole-candle colour per bar index (event candles). */
  candleColors?: ReadonlyMap<number, string>;
  /** Volume-candle width multipliers per bar (0.35-3). */
  volMult?: readonly number[];
  lines?: readonly EngineLine[];
  segments?: readonly EngineSegment[];
  tags?: readonly EngineTag[];
  markers?: readonly EngineMarker[];
  rsiMarkers?: readonly EngineMarker[];
  /** Volume bars + 20-bar average in the bottom of the price pane. */
  volume?: { avg: readonly (number | null)[] } | null;
  /** RSI pane: values + SMA. */
  rsi?: { values: readonly (number | null)[]; sma: readonly (number | null)[] } | null;
  shapes?: readonly Shape[];
  /** % scale (compare mode): every series is rebased on its first visible value. */
  percent?: boolean;
  logScale?: boolean;
  /** Changing it resets the visible range to the last `initialBars`. */
  resetKey?: string;
  initialBars?: number;
  /** Centre the first view on this bar index (a focus date) instead of the last bar. */
  centerIndex?: number | null;
  rightOffset?: number;
  onClick?: (p: EnginePoint) => void;
  onHover?: (p: EnginePoint | null) => void;
  /** Legend for the hovered (or last) bar index. */
  legend?: (index: number) => ReactNode;
  /** Extra overlay inside the chart box (popover, replay bar). */
  children?: ReactNode;
  rsiHeight?: number;
  height?: number;
  label: string;
  className?: string;
}

/** jsdom (tests) has no canvas; render a labelled placeholder instead of the chart. */
export function canvasSupported(): boolean {
  if (typeof window === 'undefined' || typeof document === 'undefined') return false;
  if (/jsdom/i.test(navigator.userAgent)) return false;
  try {
    return !!document.createElement('canvas').getContext('2d');
  } catch {
    return false;
  }
}

const t = (b: OHLCBar) => b.time as Time;

export function ChartEngine(props: ChartEngineProps) {
  const {
    bars,
    style,
    rsi,
    volume,
    percent = false,
    logScale = false,
    resetKey = '',
    initialBars = 160,
    centerIndex = null,
    rightOffset = 8,
    rsiHeight = 110,
    height,
    label,
    className,
    legend,
    children,
  } = props;
  const box = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const closeRef = useRef<ISeriesApi<'Line'> | null>(null);
  const volCandleRef = useRef<ISeriesApi<'Custom', Time, VolCandleData | WhitespaceData<Time>> | null>(null);
  const volRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const volAvgRef = useRef<ISeriesApi<'Line'> | null>(null);
  const rsiRef = useRef<ISeriesApi<'Line'> | null>(null);
  const rsiSmaRef = useRef<ISeriesApi<'Line'> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const rsiMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const dynRef = useRef<ISeriesApi<'Line'>[]>([]);
  const tagRef = useRef<IPriceLine[]>([]);
  const sceneRef = useRef<ScenePrimitive | null>(null);
  const barsRef = useRef(bars);
  const cbRef = useRef({ onClick: props.onClick, onHover: props.onHover });
  const [hover, setHover] = useState<number | null>(null);
  const [seq, setSeq] = useState(0);
  const resetRef = useRef<string | null>(null);
  const supported = canvasSupported();
  useLayoutEffect(() => {
    barsRef.current = bars;
    cbRef.current = { onClick: props.onClick, onHover: props.onHover };
  });

  const hasRsi = !!rsi;
  const hasVol = !!volume;

  // ---------------------------------------------------------------- structure
  useEffect(() => {
    const el = box.current;
    if (!el || !supported) return;
    const chart = createChart(el, {
      width: el.clientWidth || 600,
      height: el.clientHeight || height || 420,
      layout: {
        background: { type: ColorType.Solid, color: tokenColor('surface') },
        textColor: tokenColor('fg-3'),
        fontFamily: getComputedStyle(document.documentElement).getPropertyValue('--font-mono') || 'monospace',
        fontSize: 11,
        attributionLogo: false,
        panes: { separatorColor: tokenColor('line'), separatorHoverColor: tokenColor('line-strong'), enableResize: true },
      },
      grid: { vertLines: { color: tokenColor('chart-grid', 0.5) }, horzLines: { color: tokenColor('chart-grid') } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: tokenColor('line'), scaleMargins: { top: 0.06, bottom: hasVol ? 0.12 : 0.06 } },
      timeScale: { borderColor: tokenColor('line'), rightOffset, minBarSpacing: 0.4, shiftVisibleRangeOnNewBar: true },
      // Smooth zoom + pan: wheel / pinch zoom, drag / touch pan with kinetic scrolling.
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true }, axisDoubleClickReset: true },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      kineticScroll: { mouse: true, touch: true },
      localization: { locale: 'en-IN' },
    });
    chartRef.current = chart;
    const clear = 'rgba(0,0,0,0)';
    const plain = style === 'candles';
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: plain ? tokenColor('up') : clear,
      downColor: plain ? tokenColor('down') : clear,
      borderUpColor: plain ? tokenColor('up') : clear,
      borderDownColor: plain ? tokenColor('down') : clear,
      wickUpColor: plain ? tokenColor('up') : clear,
      wickDownColor: plain ? tokenColor('down') : clear,
      priceLineVisible: plain,
      priceLineStyle: LineStyle.Dashed,
      lastValueVisible: plain,
    });
    closeRef.current =
      style === 'line'
        ? chart.addSeries(LineSeries, { color: tokenColor('info'), lineWidth: 2, priceLineVisible: true, priceLineStyle: LineStyle.Dashed })
        : null;
    volCandleRef.current =
      style === 'volume'
        ? chart.addCustomSeries(new VolCandleSeries(), {
            priceLineVisible: true,
            priceLineStyle: LineStyle.Dashed,
            lastValueVisible: true,
            title: '',
          })
        : null;
    markersRef.current = createSeriesMarkers(candleRef.current, []);
    const scene = new ScenePrimitive();
    candleRef.current.attachPrimitive(scene);
    sceneRef.current = scene;

    volRef.current = null;
    volAvgRef.current = null;
    if (hasVol) {
      volRef.current = chart.addSeries(HistogramSeries, {
        priceScaleId: 'vol',
        priceFormat: { type: 'volume' },
        priceLineVisible: false,
        lastValueVisible: false,
      });
      chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 }, visible: false });
      volAvgRef.current = chart.addSeries(LineSeries, {
        priceScaleId: 'vol',
        color: tokenColor('ema-20', 0.6),
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    }
    rsiRef.current = null;
    rsiSmaRef.current = null;
    rsiMarkersRef.current = null;
    if (hasRsi) {
      const r = chart.addSeries(
        LineSeries,
        {
          color: tokenColor('violet'),
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: true,
          title: 'RSI',
          crosshairMarkerVisible: false,
          priceFormat: { type: 'price', precision: 0, minMove: 1 },
          autoscaleInfoProvider: () => ({ priceRange: { minValue: 10, maxValue: 90 } }),
        },
        1,
      );
      for (const [lvl, a] of [
        [70, 0.5],
        [50, 0.25],
        [30, 0.5],
      ] as const) {
        r.createPriceLine({
          price: lvl,
          color: tokenColor('fg-3', a),
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: false,
          title: '',
        });
      }
      rsiSmaRef.current = chart.addSeries(
        LineSeries,
        {
          color: tokenColor('ema-20', 0.75),
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        },
        1,
      );
      rsiRef.current = r;
      rsiMarkersRef.current = createSeriesMarkers(r, []);
      chart.panes()[1]?.setHeight(rsiHeight);
    }

    const point = (param: MouseEventParams<Time>): EnginePoint | null => {
      const data = barsRef.current;
      if (!param.point || param.logical == null || !data.length) return null;
      const i = Math.max(0, Math.min(data.length - 1, Math.round(param.logical)));
      const pane = param.paneIndex ?? 0;
      const price = pane === 0 ? candleRef.current?.coordinateToPrice(param.point.y) : null;
      return { index: i, time: data[i].time, price: price == null ? null : Number(price), pane, x: param.point.x, y: param.point.y };
    };
    const onClick = (param: MouseEventParams<Time>) => {
      const p = point(param);
      if (p) cbRef.current.onClick?.(p);
    };
    const onMove = (param: MouseEventParams<Time>) => {
      const p = param.point && param.logical != null && param.logical <= barsRef.current.length - 1 ? point(param) : null;
      setHover(p ? p.index : null);
      cbRef.current.onHover?.(p);
    };
    chart.subscribeClick(onClick);
    chart.subscribeCrosshairMove(onMove);
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r && r.width > 0 && r.height > 0) chart.resize(Math.floor(r.width), Math.floor(r.height));
    });
    ro.observe(el);
    resetRef.current = null;
    setSeq((n) => n + 1);
    return () => {
      ro.disconnect();
      chart.unsubscribeClick(onClick);
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      closeRef.current = null;
      volCandleRef.current = null;
      volRef.current = null;
      volAvgRef.current = null;
      rsiRef.current = null;
      rsiSmaRef.current = null;
      markersRef.current = null;
      rsiMarkersRef.current = null;
      sceneRef.current = null;
      dynRef.current = [];
      tagRef.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [style, hasRsi, hasVol, supported]);

  // ---------------------------------------------------------------- scales
  useEffect(() => {
    chartRef.current?.priceScale('right').applyOptions({
      mode: percent ? PriceScaleMode.Percentage : logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
    });
  }, [percent, logScale, seq]);

  // ---------------------------------------------------------------- bars, volume, RSI, markers
  const { candleColors, volMult, markers, rsiMarkers } = props;
  useEffect(() => {
    const c = candleRef.current;
    if (!c) return;
    c.setData(
      bars.map((b, i) => {
        const col = style === 'candles' ? candleColors?.get(i) : undefined;
        const base = { time: t(b), open: b.open, high: b.high, low: b.low, close: b.close };
        return col ? { ...base, color: col, borderColor: col, wickColor: col } : base;
      }),
    );
    closeRef.current?.setData(bars.map((b) => ({ time: t(b), value: b.close })));
    volCandleRef.current?.setData(
      bars.map((b, i) => ({
        time: t(b),
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
        mult: volMult?.[i] ?? 1,
        fill: candleColors?.get(i) ?? tokenColor(b.close >= b.open ? 'up' : 'down'),
      })),
    );
    // The last-value tag of the volume candles takes the last bar's colour.
    const lastBar = bars[bars.length - 1];
    if (volCandleRef.current && lastBar)
      volCandleRef.current.applyOptions({
        color: candleColors?.get(bars.length - 1) ?? tokenColor(lastBar.close >= lastBar.open ? 'up' : 'down'),
      });
    volRef.current?.setData(
      bars.map((b) =>
        b.volume == null ? { time: t(b) } : { time: t(b), value: b.volume, color: tokenColor(b.close >= b.open ? 'up' : 'down', 0.35) },
      ),
    );
    if (volAvgRef.current && volume) {
      volAvgRef.current.setData(bars.flatMap((b, i) => (volume.avg[i] == null ? [] : [{ time: t(b), value: volume.avg[i] as number }])));
    }
    if (rsiRef.current && rsi) {
      rsiRef.current.setData(bars.flatMap((b, i) => (rsi.values[i] == null ? [] : [{ time: t(b), value: rsi.values[i] as number }])));
      rsiSmaRef.current?.setData(bars.flatMap((b, i) => (rsi.sma[i] == null ? [] : [{ time: t(b), value: rsi.sma[i] as number }])));
    }
    const mk = (list: readonly EngineMarker[] | undefined) =>
      (list ?? [])
        .filter((m) => m.index >= 0 && m.index < bars.length)
        .map(
          (m) =>
            ({
              time: t(bars[m.index]),
              position: m.position,
              shape: m.shape,
              color: m.color,
              text: m.text,
              size: m.size ?? 1,
            }) as SeriesMarker<Time>,
        )
        .sort((a, b) => String(a.time).localeCompare(String(b.time)));
    markersRef.current?.setMarkers(mk(markers));
    rsiMarkersRef.current?.setMarkers(mk(rsiMarkers));
  }, [bars, style, candleColors, volMult, volume, rsi, markers, rsiMarkers, seq]);

  // ---------------------------------------------------------------- lines + segments (re-created on change)
  const { lines, segments } = props;
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    for (const s of dynRef.current) {
      try {
        chart.removeSeries(s);
      } catch {
        /* rebuilt */
      }
    }
    dynRef.current = [];
    const paneOf = (p?: 'price' | 'rsi') => (p === 'rsi' ? (hasRsi ? 1 : -1) : 0);
    for (const l of lines ?? []) {
      const pane = paneOf(l.pane);
      if (pane < 0) continue;
      const s = chart.addSeries(
        LineSeries,
        {
          color: l.color,
          lineWidth: l.width ?? 1,
          lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: !!l.tag,
          title: l.tag ?? '',
          crosshairMarkerVisible: false,
        },
        pane,
      );
      s.setData(bars.flatMap((b, i) => (l.values[i] == null ? [] : [{ time: t(b), value: l.values[i] as number }])));
      dynRef.current.push(s);
    }
    for (const g of segments ?? []) {
      const pane = paneOf(g.pane);
      if (pane < 0) continue;
      const a = Math.round(g.i1);
      const b = Math.round(g.i2);
      if (a < 0 || b >= bars.length || b <= a) continue;
      const s = chart.addSeries(
        LineSeries,
        {
          color: g.color,
          lineWidth: g.width ?? 1,
          lineStyle: g.dashed ? LineStyle.Dashed : LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          autoscaleInfoProvider: () => null,
        },
        pane,
      );
      s.setData([
        { time: t(bars[a]), value: g.v1 },
        { time: t(bars[b]), value: g.v2 },
      ]);
      dynRef.current.push(s);
    }
  }, [lines, segments, bars, hasRsi, seq]);

  // ---------------------------------------------------------------- axis tags
  const { tags } = props;
  useEffect(() => {
    const c = candleRef.current;
    if (!c) return;
    for (const p of tagRef.current) {
      try {
        c.removePriceLine(p);
      } catch {
        /* rebuilt */
      }
    }
    tagRef.current = (tags ?? []).map((g) =>
      c.createPriceLine({
        price: g.price,
        color: g.color,
        lineWidth: 1,
        lineStyle: g.dashed ? LineStyle.Dashed : LineStyle.Solid,
        lineVisible: !!g.line,
        axisLabelVisible: true,
        title: g.title,
      }),
    );
  }, [tags, seq]);

  // ---------------------------------------------------------------- canvas scene
  const { shapes } = props;
  useEffect(() => {
    sceneRef.current?.setShapes([...(shapes ?? [])]);
  }, [shapes, seq]);

  // ---------------------------------------------------------------- visible range
  useEffect(() => {
    const chart = chartRef.current;
    const n = bars.length;
    if (!chart || !n || resetRef.current === resetKey) return;
    resetRef.current = resetKey;
    if (centerIndex != null && centerIndex >= 0 && centerIndex < n - initialBars / 2) {
      chart.timeScale().setVisibleLogicalRange({ from: centerIndex - initialBars * 0.55, to: centerIndex + initialBars * 0.45 });
    } else chart.timeScale().setVisibleLogicalRange({ from: Math.max(-2, n - initialBars), to: n + rightOffset });
  }, [bars, resetKey, initialBars, centerIndex, rightOffset, seq]);

  const legendIndex = hover ?? bars.length - 1;
  return (
    <div className={cn('relative min-h-0', className)} style={height ? { height } : undefined}>
      <div ref={box} role="img" aria-label={label} className="absolute inset-0" data-testid="chart-engine" />
      {legend && bars.length > 0 && (
        <div className="pointer-events-none absolute left-2 top-1 z-10 max-w-[calc(100%-90px)]" aria-live="off">
          {legend(Math.max(0, Math.min(bars.length - 1, legendIndex)))}
        </div>
      )}
      {children}
    </div>
  );
}
