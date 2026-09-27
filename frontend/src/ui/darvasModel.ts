/**
 * Darvas box overlay model (pure; no chart imports). Served boxes
 * (GET /stock/{sym}/darvas) -> shapes snapped onto the displayed bar times,
 * plus breakout / breakdown markers and screen-space rectangles.
 */
import type { DarvasBoxRow } from '../api/types';

export type DarvasStatus = 'active' | 'broken_up' | 'broken_down' | 'superseded';

export interface ChartBox {
  id: string;
  /** First / last displayed bar time the box spans (YYYY-MM-DD). */
  from: string;
  to: string;
  top: number;
  bottom: number;
  status: DarvasStatus;
  /** The latest box still open: extended to the last bar and highlighted. */
  active: boolean;
  /** Displayed bar of the breakout / breakdown close, if any. */
  breakTime: string | null;
}

/** First index whose time >= iso (sorted), -1 if none. */
function firstAtOrAfter(times: readonly string[], iso: string): number {
  let lo = 0;
  let hi = times.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] >= iso) {
      ans = mid;
      hi = mid - 1;
    } else lo = mid + 1;
  }
  return ans;
}

/** Last index whose time <= iso (sorted), -1 if none. */
function lastAtOrBefore(times: readonly string[], iso: string): number {
  let lo = 0;
  let hi = times.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= iso) {
      ans = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return ans;
}

/**
 * Served boxes -> chart boxes on `barTimes` (sorted). Rows missing a date or a
 * price are dropped (never filled). An `active` box is extended to the last
 * displayed bar; boxes entirely outside the displayed bars are dropped.
 */
export function toChartBoxes(rows: readonly DarvasBoxRow[] | null | undefined, barTimes: readonly string[]): ChartBox[] {
  if (!rows?.length || barTimes.length === 0) return [];
  const lastTime = barTimes[barTimes.length - 1];
  const out: ChartBox[] = [];
  rows.forEach((r, k) => {
    if (!r.start_date || !r.end_date || r.top == null || r.bottom == null || !(r.top >= r.bottom)) return;
    const status = (r.status ?? 'active') as DarvasStatus;
    const active = status === 'active';
    const i0 = firstAtOrAfter(barTimes, r.start_date);
    if (i0 < 0) return;
    const i1 = active ? barTimes.length - 1 : lastAtOrBefore(barTimes, r.end_date);
    if (i1 < i0) return;
    const bi = r.break_date ? firstAtOrAfter(barTimes, r.break_date) : -1;
    out.push({
      id: `${r.start_date}:${r.formed_date ?? ''}:${k}`,
      from: barTimes[i0],
      to: active ? lastTime : barTimes[i1],
      top: r.top,
      bottom: r.bottom,
      status,
      active,
      breakTime: bi >= 0 ? barTimes[bi] : null,
    });
  });
  return out;
}

export interface BoxMarker {
  time: string;
  kind: 'darvas_up' | 'darvas_down';
}

/** One marker per breakout (above top) / breakdown (below bottom). */
export function boxBreakMarkers(boxes: readonly ChartBox[]): BoxMarker[] {
  const out: BoxMarker[] = [];
  for (const b of boxes) {
    if (!b.breakTime) continue;
    if (b.status === 'broken_up') out.push({ time: b.breakTime, kind: 'darvas_up' });
    else if (b.status === 'broken_down') out.push({ time: b.breakTime, kind: 'darvas_down' });
  }
  return out;
}

export interface BoxRect {
  box: ChartBox;
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Screen rectangles (media px) for boxes; half a bar of padding on each side so
 * the box covers its first and last candles. Boxes whose time or price cannot
 * be mapped, or that lie fully off-screen, are skipped.
 */
export function boxRects(
  boxes: readonly ChartBox[],
  timeToX: (time: string) => number | null,
  priceToY: (price: number) => number | null,
  barSpacing: number,
  width: number,
): BoxRect[] {
  const pad = Math.max(1, barSpacing / 2);
  const out: BoxRect[] = [];
  for (const box of boxes) {
    const x0 = timeToX(box.from);
    const x1 = timeToX(box.to);
    const yTop = priceToY(box.top);
    const yBot = priceToY(box.bottom);
    if (x0 == null || x1 == null || yTop == null || yBot == null) continue;
    const left = Math.min(x0, x1) - pad;
    const right = Math.max(x0, x1) + pad;
    if (right < 0 || left > width) continue;
    const y = Math.min(yTop, yBot);
    out.push({ box, x: left, y, w: right - left, h: Math.max(1, Math.abs(yBot - yTop)) });
  }
  return out;
}
