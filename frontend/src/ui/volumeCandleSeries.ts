/**
 * Volume candles (TradingView style) as a lightweight-charts v5 custom series: each candle's
 * body width scales with its volume vs the 20-bar average (`width` 0..1 of the bar slot).
 * Colours are per bar (event colour or up/down). Used by ui/Chart.tsx when priceStyle='volume'.
 */
import type {
  CustomData,
  CustomSeriesOptions,
  CustomSeriesPricePlotValues,
  CustomSeriesWhitespaceData,
  ICustomSeriesPaneRenderer,
  ICustomSeriesPaneView,
  PaneRendererCustomData,
  PriceToCoordinateConverter,
  Time,
} from 'lightweight-charts';
import { customSeriesDefaultOptions } from 'lightweight-charts';

export interface VolumeCandleData extends CustomData<Time> {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
  /** Body width as a share of the bar slot (0..1). */
  width: number;
  color: string;
}

/** Relative volume -> width share. Average volume = 45% of the slot, 2× = 90%; clamped 12–100%. */
export function volumeWidth(volume: number | null | undefined, avg: number | null | undefined): number {
  if (volume == null || avg == null || !(avg > 0)) return 0.45;
  const rel = volume / avg;
  return Math.max(0.12, Math.min(1, 0.45 * rel));
}

/** Colour-intensity fallback (phones / narrow tiles): alpha from relative volume, 0.35–1. */
export function volumeAlpha(volume: number | null | undefined, avg: number | null | undefined): number {
  if (volume == null || avg == null || !(avg > 0)) return 0.6;
  return Math.max(0.35, Math.min(1, 0.25 + 0.35 * (volume / avg)));
}

type Target = Parameters<ICustomSeriesPaneRenderer['draw']>[0];

class Renderer implements ICustomSeriesPaneRenderer {
  private data: PaneRendererCustomData<Time, VolumeCandleData> | null = null;

  update(data: PaneRendererCustomData<Time, VolumeCandleData>) {
    this.data = data;
  }

  draw(target: Target, toY: PriceToCoordinateConverter): void {
    const d = this.data;
    if (!d || !d.visibleRange || d.bars.length === 0) return;
    target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
      const slot = d.barSpacing * hr;
      for (let i = d.visibleRange!.from; i < d.visibleRange!.to; i++) {
        const bar = d.bars[i];
        if (!bar) continue;
        const c = bar.originalData;
        const yo = toY(c.open);
        const yc = toY(c.close);
        const yh = toY(c.high);
        const yl = toY(c.low);
        if (yo == null || yc == null || yh == null || yl == null) continue;
        const x = Math.round(bar.x * hr);
        const w = Math.max(1, Math.round(slot * Math.max(0, Math.min(1, c.width)) * 0.9));
        const left = x - Math.floor(w / 2);
        ctx.fillStyle = c.color;
        // Wick
        const ww = Math.max(1, Math.floor(hr));
        ctx.fillRect(x - Math.floor(ww / 2), Math.round(yh * vr), ww, Math.max(1, Math.round((yl - yh) * vr)));
        // Body
        const top = Math.round(Math.min(yo, yc) * vr);
        const h = Math.max(1, Math.round(Math.abs(yc - yo) * vr));
        ctx.fillRect(left, top, w, h);
      }
    });
  }
}

export class VolumeCandleSeries implements ICustomSeriesPaneView<Time, VolumeCandleData, CustomSeriesOptions> {
  private readonly r = new Renderer();

  renderer(): ICustomSeriesPaneRenderer {
    return this.r;
  }

  update(data: PaneRendererCustomData<Time, VolumeCandleData>): void {
    this.r.update(data);
  }

  priceValueBuilder(row: VolumeCandleData): CustomSeriesPricePlotValues {
    return [row.high, row.low, row.close];
  }

  isWhitespace(row: VolumeCandleData | CustomSeriesWhitespaceData<Time>): row is CustomSeriesWhitespaceData<Time> {
    return (row as Partial<VolumeCandleData>).close === undefined;
  }

  defaultOptions(): CustomSeriesOptions {
    return { ...customSeriesDefaultOptions };
  }
}

/** '#rrggbb' or 'rgba(r, g, b, a)' / 'rgb(r, g, b)' -> rgba with the given alpha (other strings pass through). */
export function withAlpha(color: string, alpha: number): string {
  const a = Math.max(0, Math.min(1, alpha));
  const hex = /^#([0-9a-f]{6})$/i.exec(color.trim());
  if (hex) {
    const n = parseInt(hex[1], 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  }
  const rgb = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i.exec(color.trim());
  if (rgb) return `rgba(${rgb[1]}, ${rgb[2]}, ${rgb[3]}, ${a})`;
  return color;
}

/** Below this chart width (phones, small tiles) volume candles use colour intensity instead of width. */
export const NARROW_CHART_PX = 480;
