/**
 * lightweight-charts v5 series primitive that paints Darvas boxes behind the
 * candles: translucent fill, top (green) / bottom (red) edges; the active box
 * is filled stronger with a dashed right edge at the last bar.
 */
import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  PrimitivePaneViewZOrder,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts';
import { tokenColor } from '../lib/tokens';
import { boxRects, type ChartBox } from './darvasModel';

type Target = Parameters<IPrimitivePaneRenderer['draw']>[0];

interface Palette {
  fill: string;
  fillActive: string;
  top: string;
  bottom: string;
  edge: string;
}

function palette(): Palette {
  return {
    fill: tokenColor('accent', 0.11),
    fillActive: tokenColor('accent', 0.22),
    top: tokenColor('up', 0.85),
    bottom: tokenColor('down', 0.85),
    edge: tokenColor('accent', 0.55),
  };
}

class BoxesRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly src: DarvasBoxesPrimitive) {}

  draw(target: Target): void {
    const chart = this.src.chart;
    const series = this.src.series;
    if (!chart || !series || this.src.boxes.length === 0) return;
    const ts = chart.timeScale();
    const barSpacing = ts.options().barSpacing;
    target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hr, verticalPixelRatio: vr, mediaSize }) => {
      const rects = boxRects(
        this.src.boxes,
        (t) => ts.timeToCoordinate(t as Time),
        (p) => series.priceToCoordinate(p),
        barSpacing,
        mediaSize.width,
      );
      const pal = this.src.pal;
      const lw = Math.max(1, Math.round(hr));
      for (const r of rects) {
        const x = Math.round(r.x * hr);
        const w = Math.max(1, Math.round(r.w * hr));
        const y = Math.round(r.y * vr);
        const h = Math.max(1, Math.round(r.h * vr));
        ctx.fillStyle = r.box.active ? pal.fillActive : pal.fill;
        ctx.fillRect(x, y, w, h);
        const edge = r.box.active ? lw * 2 : lw;
        ctx.fillStyle = pal.top;
        ctx.fillRect(x, y, w, edge);
        ctx.fillStyle = pal.bottom;
        ctx.fillRect(x, y + h - edge, w, edge);
        if (r.box.active) {
          ctx.fillStyle = pal.edge;
          ctx.fillRect(x, y, lw, h);
          // dashed right edge: the box is still open at the last bar
          const dash = Math.round(4 * vr);
          for (let yy = y; yy < y + h; yy += dash * 2) ctx.fillRect(x + w - lw, yy, lw, Math.min(dash, y + h - yy));
        }
      }
    });
  }
}

class BoxesView implements IPrimitivePaneView {
  private readonly r: BoxesRenderer;
  constructor(src: DarvasBoxesPrimitive) {
    this.r = new BoxesRenderer(src);
  }
  zOrder(): PrimitivePaneViewZOrder {
    return 'bottom';
  }
  renderer(): IPrimitivePaneRenderer {
    return this.r;
  }
}

export class DarvasBoxesPrimitive implements ISeriesPrimitive<Time> {
  boxes: readonly ChartBox[] = [];
  chart: IChartApiBase<Time> | null = null;
  series: ISeriesApi<SeriesType, Time> | null = null;
  pal: Palette = palette();
  private request: (() => void) | null = null;
  private readonly views: IPrimitivePaneView[] = [new BoxesView(this)];

  attached(p: SeriesAttachedParameter<Time>): void {
    this.chart = p.chart;
    this.series = p.series;
    this.request = p.requestUpdate;
    this.pal = palette();
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.request = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }

  setBoxes(boxes: readonly ChartBox[]): void {
    this.boxes = boxes;
    this.request?.();
  }
}
