/**
 * Darvas overlay model (pure; no chart imports). Mirrors the user's Pine
 * "SUCCESS" indicator: GET /stock/{sym}/darvas serves per-bar TopBox /
 * BottomBox (drawn as two step lines) plus projected rows for the next 5
 * sessions / periods (dotted top box extension and EMA10 projection).
 * Projected rows are future time points only; never candles.
 */
import type { DarvasRow } from '../api/types';

export interface DarvasPoint {
  time: string;
  value: number;
}

export interface DarvasLines {
  /** TopBox per displayed bar (green step line); bars before the first box are absent. */
  top: DarvasPoint[];
  /** BottomBox per displayed bar (red step line). */
  bottom: DarvasPoint[];
  /** Dotted top box extension: last bar -> 5 bars ahead at the last TopBox. */
  topExtension: DarvasPoint[];
  /** Dotted EMA10 projection: last bar's EMA10 -> ema10 + slope * 5. */
  emaProjection: DarvasPoint[];
  /** Latest served TopBox / BottomBox (W: the last completed week), if any. */
  last: { top: number; bottom: number } | null;
}

export const EMPTY_DARVAS: DarvasLines = { top: [], bottom: [], topExtension: [], emaProjection: [], last: null };

/**
 * Served rows -> chart lines on `barTimes` (sorted YYYY-MM-DD). Real rows must
 * sit on a displayed bar; projected rows must lie after the last bar. NULLs are
 * dropped, never filled. `boxes: false` keeps only the EMA10 projection.
 */
export function toDarvasLines(
  rows: readonly DarvasRow[] | null | undefined,
  barTimes: readonly string[],
  opts: { boxes?: boolean } = {},
): DarvasLines {
  if (!rows?.length || barTimes.length === 0) return EMPTY_DARVAS;
  const boxes = opts.boxes ?? true;
  const onBar = new Set(barTimes);
  const lastTime = barTimes[barTimes.length - 1];
  const out: DarvasLines = { top: [], bottom: [], topExtension: [], emaProjection: [], last: null };
  for (const r of rows) {
    const t = r.trade_date;
    if (!t) continue;
    if (r.projected ? t <= lastTime : !onBar.has(t)) continue;
    if (!r.projected) {
      if (r.top != null) out.top.push({ time: t, value: r.top });
      if (r.bottom != null) out.bottom.push({ time: t, value: r.bottom });
    }
    // Projection lines start on the last displayed bar and run into the future points.
    if (r.projected || t === lastTime) {
      if (r.top_extension != null) out.topExtension.push({ time: t, value: r.top_extension });
      if (r.ema_10_projection != null) out.emaProjection.push({ time: t, value: r.ema_10_projection });
    }
  }
  const byTime = (a: DarvasPoint, b: DarvasPoint) => a.time.localeCompare(b.time);
  for (const k of ['top', 'bottom', 'topExtension', 'emaProjection'] as const) out[k].sort(byTime);
  const lt = out.top[out.top.length - 1];
  const lb = out.bottom[out.bottom.length - 1];
  out.last = lt && lb ? { top: lt.value, bottom: lb.value } : null;
  // A projection needs its anchor on the last bar plus at least one future point.
  if (out.topExtension.length < 2 || out.topExtension[0].time !== lastTime) out.topExtension = [];
  if (out.emaProjection.length < 2 || out.emaProjection[0].time !== lastTime) out.emaProjection = [];
  if (!boxes) return { ...EMPTY_DARVAS, emaProjection: out.emaProjection };
  return out;
}
