/**
 * Chart v2 volume candles (TradingView style): a lightweight-charts custom series whose candle
 * width = the normal width × (volume / 20-bar average), clamped 0.35-3× (series.ts). Wide candles
 * may overlap their neighbours, as on TradingView.
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

export interface VolCandleData extends CustomData<Time> {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
  /** Width multiplier of the normal candle (0.35-3). */
  mult: number;
  /** Candle colour. Not `color`: lightweight-charts strips that key from custom-series data. */
  fill: string;
}

/** Normal candle body = 60% of the bar slot. */
export const BODY_SHARE = 0.6;

export function volCandleWidthPx(slotPx: number, mult: number): number {
  return Math.max(1, slotPx * BODY_SHARE * mult);
}

type Target = Parameters<ICustomSeriesPaneRenderer['draw']>[0];

class Renderer implements ICustomSeriesPaneRenderer {
  private data: PaneRendererCustomData<Time, VolCandleData> | null = null;

  update(data: PaneRendererCustomData<Time, VolCandleData>) {
    this.data = data;
  }

  draw(target: Target, toY: PriceToCoordinateConverter): void {
    const d = this.data;
    if (!d || !d.visibleRange || d.bars.length === 0) return;
    target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
      const slot = d.barSpacing * hr;
      // Draw the widest last so a volume spike sits on top of its quieter neighbours.
      const order: number[] = [];
      for (let i = d.visibleRange!.from; i < d.visibleRange!.to; i++) order.push(i);
      order.sort((a, b) => (d.bars[a]?.originalData.mult ?? 0) - (d.bars[b]?.originalData.mult ?? 0));
      for (const i of order) {
        const bar = d.bars[i];
        if (!bar) continue;
        const c = bar.originalData;
        const yo = toY(c.open);
        const yc = toY(c.close);
        const yh = toY(c.high);
        const yl = toY(c.low);
        if (yo == null || yc == null || yh == null || yl == null) continue;
        const x = Math.round(bar.x * hr);
        const w = Math.round(volCandleWidthPx(slot, c.mult));
        ctx.fillStyle = c.fill;
        const ww = Math.max(1, Math.floor(hr));
        ctx.fillRect(x - Math.floor(ww / 2), Math.round(yh * vr), ww, Math.max(1, Math.round((yl - yh) * vr)));
        const top = Math.round(Math.min(yo, yc) * vr);
        const h = Math.max(1, Math.round(Math.abs(yc - yo) * vr));
        ctx.fillRect(x - Math.floor(w / 2), top, w, h);
      }
    });
  }
}

export class VolCandleSeries implements ICustomSeriesPaneView<Time, VolCandleData, CustomSeriesOptions> {
  private readonly r = new Renderer();

  renderer(): ICustomSeriesPaneRenderer {
    return this.r;
  }

  update(data: PaneRendererCustomData<Time, VolCandleData>): void {
    this.r.update(data);
  }

  priceValueBuilder(row: VolCandleData): CustomSeriesPricePlotValues {
    return [row.high, row.low, row.close];
  }

  isWhitespace(row: VolCandleData | CustomSeriesWhitespaceData<Time>): row is CustomSeriesWhitespaceData<Time> {
    return (row as Partial<VolCandleData>).close === undefined;
  }

  defaultOptions(): CustomSeriesOptions {
    return { ...customSeriesDefaultOptions };
  }
}
