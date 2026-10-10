/**
 * Case-study price chart (10-tab-research.md §12): daily candles + 20 EMA, the
 * low → peak move shaded, every preset's fresh fire marked with its letter, and
 * the 20 EMA ladder's entries / exits with P&L. Built on lightweight-charts with
 * design-token colours. The shared ui/Chart has no shading or coloured custom
 * markers, so this study chart is local to the Research tab (candidate for the
 * cross-tab UI pass).
 */
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';
import { useEffect, useRef } from 'react';
import { tokenColor } from '../../lib/tokens';
import type { CaseBarRow, LadderLeg } from './lab';

export interface CaseChartProps {
  bars: readonly CaseBarRow[];
  move: { low_date: string; peak_date: string; low: number; peak: number } | null;
  fires: readonly { time: string; text: string; inMove: boolean }[];
  legs: readonly LadderLeg[];
  height?: number;
  label: string;
}

/** Markers sorted by time (lightweight-charts requires it): fires above, ladder entries below, exits above. */
export function caseMarkers(
  fires: CaseChartProps['fires'],
  legs: readonly LadderLeg[],
  colors: { fire: string; fireOut: string; up: string; down: string },
): SeriesMarker<Time>[] {
  const out: SeriesMarker<Time>[] = [];
  for (const f of fires) {
    out.push({ time: f.time as Time, position: 'aboveBar', shape: 'circle', color: f.inMove ? colors.fire : colors.fireOut, text: f.text, size: 0.6 });
  }
  for (const l of legs) {
    out.push({ time: l.entry_date as Time, position: 'belowBar', shape: 'arrowUp', color: colors.up, text: `B ${l.letter}` });
    if (!l.open)
      out.push({
        time: l.exit_date as Time,
        position: 'aboveBar',
        shape: 'arrowDown',
        color: l.pnl_pct >= 0 ? colors.up : colors.down,
        text: `S ${l.pnl_pct > 0 ? '+' : ''}${l.pnl_pct.toFixed(1)}%`,
      });
  }
  return out.sort((a, b) => String(a.time).localeCompare(String(b.time)));
}

export function CaseChart({ bars, move, fires, legs, height = 380, label }: CaseChartProps) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      width: el.clientWidth || 800,
      height,
      layout: {
        background: { type: ColorType.Solid, color: tokenColor('surface') },
        textColor: tokenColor('fg-3'),
        fontSize: 11,
        attributionLogo: false,
      },
      grid: { vertLines: { color: tokenColor('chart-grid') }, horzLines: { color: tokenColor('chart-grid') } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: tokenColor('line') },
      timeScale: { borderColor: tokenColor('line'), rightOffset: 4 },
      localization: { locale: 'en-IN' },
    });
    chartRef.current = chart;
    const shade = chart.addSeries(HistogramSeries, {
      priceScaleId: 'shade',
      color: tokenColor('accent', 0.09),
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.priceScale('shade').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: tokenColor('up'),
      downColor: tokenColor('down'),
      borderUpColor: tokenColor('up'),
      borderDownColor: tokenColor('down'),
      wickUpColor: tokenColor('up'),
      wickDownColor: tokenColor('down'),
      priceLineVisible: false,
    });
    const ema = chart.addSeries(LineSeries, {
      color: tokenColor('ema-20'),
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    const ok = bars.filter((b) => b.open != null && b.high != null && b.low != null && b.close != null);
    candles.setData(ok.map((b) => ({ time: b.time as Time, open: b.open!, high: b.high!, low: b.low!, close: b.close! })));
    ema.setData(ok.filter((b) => b.ema_20 != null).map((b) => ({ time: b.time as Time, value: b.ema_20! })));
    if (move) {
      shade.setData(ok.map((b) => ({ time: b.time as Time, value: b.time >= move.low_date && b.time <= move.peak_date ? 1 : 0 })));
      candles.createPriceLine({ price: move.low, color: tokenColor('fg-3'), lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: 'low' });
      candles.createPriceLine({ price: move.peak, color: tokenColor('fg-3'), lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: 'peak' });
    }
    createSeriesMarkers(
      candles,
      caseMarkers(fires, legs, {
        fire: tokenColor('violet'),
        fireOut: tokenColor('fg-3', 0.7),
        up: tokenColor('up'),
        down: tokenColor('down'),
      }),
    );
    chart.timeScale().fitContent();
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r && r.width > 0) chart.resize(Math.floor(r.width), height);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, move, fires, legs, height]);

  return <div ref={ref} role="img" aria-label={label} className="w-full" style={{ height }} />;
}
