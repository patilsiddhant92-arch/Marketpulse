/**
 * Canvas scene for Chart v2: Darvas box fills, dotted projections, buy stop / stop lines, the deal
 * callout and the drawing tools are plain shapes in (bar index, price) space. One series primitive
 * draws them: 'bg' shapes behind the candles, 'fg' shapes on top. Indices may be fractional or past
 * the last bar (projections).
 */
import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts';

export type Layer = 'bg' | 'fg';

export type Shape =
  | {
      kind: 'rect';
      layer: Layer;
      i1: number;
      i2: number;
      p1: number;
      p2: number;
      fill?: string;
      stroke?: string;
      dash?: number[];
      /** Coloured top / bottom edges (Darvas: green top, red bottom). */
      top?: string;
      bottom?: string;
      edgeWidth?: number;
    }
  | { kind: 'line'; layer: Layer; i1: number; p1: number; i2: number; p2: number; color: string; width?: number; dash?: number[] }
  | {
      kind: 'text';
      layer: Layer;
      i: number;
      p: number;
      text: string;
      color: string;
      align?: CanvasTextAlign;
      baseline?: CanvasTextBaseline;
      dx?: number;
      dy?: number;
      bg?: string;
      border?: string;
      bold?: boolean;
      size?: number;
    }
  | {
      kind: 'callout';
      layer: Layer;
      /** Anchor point (bar index, price). */
      i: number;
      p: number;
      lines: { text: string; color: string; bold?: boolean }[];
      color: string;
      bg: string;
      /** Box offset from the anchor in px. */
      dx: number;
      dy: number;
    };

type Target = Parameters<IPrimitivePaneRenderer['draw']>[0];

export interface SceneHelpers {
  x: (i: number) => number | null;
  y: (p: number) => number | null;
}

function drawShapes(ctx: CanvasRenderingContext2D, shapes: readonly Shape[], h: SceneHelpers, size: { width: number; height: number }) {
  const font = (px: number, bold?: boolean) =>
    `${bold ? '600 ' : ''}${px}px ${getComputedStyle(document.documentElement).getPropertyValue('--font-sans') || 'system-ui, sans-serif'}`;
  for (const s of shapes) {
    ctx.save();
    if (s.kind === 'rect') {
      const x1 = h.x(s.i1);
      const x2 = h.x(s.i2);
      const y1 = h.y(s.p1);
      const y2 = h.y(s.p2);
      if (x1 == null || x2 == null || y1 == null || y2 == null) {
        ctx.restore();
        continue;
      }
      const l = Math.min(x1, x2);
      const t = Math.min(y1, y2);
      const w = Math.abs(x2 - x1);
      const hh = Math.abs(y2 - y1);
      if (s.fill) {
        ctx.fillStyle = s.fill;
        ctx.fillRect(l, t, w, hh);
      }
      if (s.stroke) {
        ctx.strokeStyle = s.stroke;
        ctx.setLineDash(s.dash ?? []);
        ctx.lineWidth = 1;
        ctx.strokeRect(l + 0.5, t + 0.5, w, hh);
      }
      ctx.setLineDash([]);
      ctx.lineWidth = s.edgeWidth ?? 1.5;
      const yTop = h.y(Math.max(s.p1, s.p2));
      const yBot = h.y(Math.min(s.p1, s.p2));
      if (s.top && yTop != null) {
        ctx.strokeStyle = s.top;
        ctx.beginPath();
        ctx.moveTo(l, yTop);
        ctx.lineTo(l + w, yTop);
        ctx.stroke();
      }
      if (s.bottom && yBot != null) {
        ctx.strokeStyle = s.bottom;
        ctx.beginPath();
        ctx.moveTo(l, yBot);
        ctx.lineTo(l + w, yBot);
        ctx.stroke();
      }
    } else if (s.kind === 'line') {
      const x1 = h.x(s.i1);
      const x2 = h.x(s.i2);
      const y1 = h.y(s.p1);
      const y2 = h.y(s.p2);
      if (x1 != null && x2 != null && y1 != null && y2 != null) {
        ctx.strokeStyle = s.color;
        ctx.lineWidth = s.width ?? 1;
        ctx.setLineDash(s.dash ?? []);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }
    } else if (s.kind === 'text') {
      const x = h.x(s.i);
      const y = h.y(s.p);
      if (x != null && y != null) {
        ctx.font = font(s.size ?? 11, s.bold);
        ctx.textAlign = s.align ?? 'left';
        ctx.textBaseline = s.baseline ?? 'bottom';
        let tx = x + (s.dx ?? 0);
        const ty = y + (s.dy ?? 0);
        // Keep the label inside the pane (a label near the last bar would run under the axis).
        const tw = ctx.measureText(s.text).width + 8;
        const leftEdge = s.align === 'center' ? tx - tw / 2 : s.align === 'right' || s.align === 'end' ? tx - tw : tx;
        if (leftEdge + tw > size.width - 2) tx -= leftEdge + tw - (size.width - 2);
        else if (leftEdge < 2) tx += 2 - leftEdge;
        if (s.bg || s.border) {
          const m = ctx.measureText(s.text);
          const pad = 4;
          const fh = (s.size ?? 11) + 4;
          const left =
            s.align === 'center' ? tx - m.width / 2 - pad : s.align === 'right' || s.align === 'end' ? tx - m.width - pad : tx - pad;
          const top = s.baseline === 'top' ? ty - 2 : s.baseline === 'middle' ? ty - fh / 2 : ty - fh + 2;
          if (s.bg) {
            ctx.fillStyle = s.bg;
            ctx.fillRect(left, top, m.width + pad * 2, fh);
          }
          if (s.border) {
            ctx.strokeStyle = s.border;
            ctx.lineWidth = 1;
            ctx.strokeRect(left + 0.5, top + 0.5, m.width + pad * 2, fh);
          }
        }
        ctx.fillStyle = s.color;
        ctx.fillText(s.text, tx, ty);
      }
    } else if (s.kind === 'callout') {
      const ax = h.x(s.i);
      const ay = h.y(s.p);
      if (ax != null && ay != null) {
        const lh = 17;
        const pad = 8;
        ctx.font = font(12, true);
        const w = Math.max(...s.lines.map((l) => ctx.measureText(l.text).width)) + pad * 2;
        const hh = s.lines.length * lh + pad;
        let bx = ax + s.dx;
        let by = ay + s.dy;
        bx = Math.max(4, Math.min(size.width - w - 4, bx));
        by = Math.max(4, Math.min(size.height - hh - 4, by));
        ctx.strokeStyle = s.color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx + (ax < bx ? 0 : w), by + (ay < by ? 0 : hh));
        ctx.stroke();
        ctx.fillStyle = s.bg;
        ctx.beginPath();
        ctx.roundRect?.(bx, by, w, hh, 6);
        if (!ctx.roundRect) ctx.rect(bx, by, w, hh);
        ctx.fill();
        ctx.stroke();
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        s.lines.forEach((l, k) => {
          ctx.font = font(12, l.bold);
          ctx.fillStyle = l.color;
          ctx.fillText(l.text, bx + pad, by + pad / 2 + 2 + k * lh);
        });
      }
    }
    ctx.restore();
  }
}

class SceneRenderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly owner: ScenePrimitive,
    private readonly layer: Layer,
  ) {}

  draw(target: Target): void {
    const shapes = this.owner.shapes.filter((s) => s.layer === this.layer);
    if (!shapes.length) return;
    const h = this.owner.helpers();
    if (!h) return;
    target.useMediaCoordinateSpace(({ context, mediaSize }) => drawShapes(context, shapes, h, mediaSize));
  }
}

/** 'bg' shapes in the bottom layer (under the candles), 'fg' shapes in the top layer. */
class SceneView implements IPrimitivePaneView {
  private readonly r: SceneRenderer;
  constructor(
    owner: ScenePrimitive,
    private readonly layer: Layer,
  ) {
    this.r = new SceneRenderer(owner, layer);
  }
  zOrder() {
    return this.layer === 'bg' ? ('bottom' as const) : ('top' as const);
  }
  renderer() {
    return this.r;
  }
}

export class ScenePrimitive implements ISeriesPrimitive<Time> {
  shapes: Shape[] = [];
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private request: (() => void) | null = null;
  private readonly views: IPrimitivePaneView[] = [new SceneView(this, 'bg'), new SceneView(this, 'fg')];

  attached(p: SeriesAttachedParameter<Time>): void {
    this.chart = p.chart as IChartApi;
    this.series = p.series as ISeriesApi<SeriesType>;
    this.request = p.requestUpdate;
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.request = null;
  }

  setShapes(shapes: Shape[]): void {
    this.shapes = shapes;
    this.request?.();
  }

  helpers(): SceneHelpers | null {
    const c = this.chart;
    const s = this.series;
    if (!c || !s) return null;
    const ts = c.timeScale();
    // logicalToCoordinate is only reliable on whole bar indices: interpolate fractional ones
    // (box edges sit half a bar outside the candles).
    const at = (i: number) => ts.logicalToCoordinate(i as Logical);
    return {
      x: (i) => {
        const a = Math.floor(i);
        const xa = at(a);
        if (xa == null || i === a) return xa;
        const xb = at(a + 1);
        return xb == null ? xa : xa + (xb - xa) * (i - a);
      },
      y: (p) => s.priceToCoordinate(p),
    };
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }
}
