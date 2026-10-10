/**
 * Darvas boxes for Chart v2 (pure). The served Pine TopBox / BottomBox step lines
 * (GET /stock/{sym}/darvas) become shaded boxes: one box per run of bars with the same
 * top and bottom. The last box is the current box (drawn brighter). Projections (dotted
 * 5-bar top extension and EMA10 projection) are kept as offsets after the last bar.
 */
import type { DarvasRow } from '../api/types';
import type { OHLCBar } from '../lib/indicators';
import { roundTick, tickSize } from './series';

export interface DarvasBox {
  /** First / last displayed bar index of the box. */
  from: number;
  to: number;
  top: number;
  bottom: number;
  current: boolean;
}

export interface DarvasModel {
  boxes: DarvasBox[];
  /** Dotted top extension: [k, value] for k = 0 (last bar) .. 5 bars ahead. */
  topExtension: { k: number; value: number }[];
  /** Dotted EMA10 projection: [k, value]. */
  emaProjection: { k: number; value: number }[];
  current: DarvasBox | null;
  /** Darvas buy stop (box top + 1 tick) and stop (box bottom − 1 tick) of the current box. */
  buyStop: number | null;
  stop: number | null;
  /** Box top / bottom per displayed bar (null before the first box). */
  topAt: (number | null)[];
  bottomAt: (number | null)[];
}

export const EMPTY_DARVAS_MODEL: DarvasModel = {
  boxes: [],
  topExtension: [],
  emaProjection: [],
  current: null,
  buyStop: null,
  stop: null,
  topAt: [],
  bottomAt: [],
};

export function darvasModel(rows: readonly DarvasRow[] | null | undefined, bars: readonly OHLCBar[]): DarvasModel {
  if (!rows?.length || !bars.length) return { ...EMPTY_DARVAS_MODEL, topAt: bars.map(() => null), bottomAt: bars.map(() => null) };
  const idx = new Map(bars.map((b, i) => [b.time, i]));
  const lastTime = bars[bars.length - 1].time;
  const topAt: (number | null)[] = bars.map(() => null);
  const bottomAt: (number | null)[] = bars.map(() => null);
  const ext: { t: string; v: number }[] = [];
  const proj: { t: string; v: number }[] = [];
  for (const r of rows) {
    const t = r.trade_date;
    if (!t) continue;
    if (!r.projected) {
      const i = idx.get(t);
      if (i == null) continue;
      topAt[i] = r.top ?? null;
      bottomAt[i] = r.bottom ?? null;
    }
    if (r.projected ? t > lastTime : t === lastTime) {
      if (r.top_extension != null) ext.push({ t, v: r.top_extension });
      if (r.ema_10_projection != null) proj.push({ t, v: r.ema_10_projection });
    }
  }
  const boxes: DarvasBox[] = [];
  for (let i = 0; i < bars.length; i++) {
    const t = topAt[i];
    const b = bottomAt[i];
    if (t == null || b == null) continue;
    const prev = boxes[boxes.length - 1];
    if (prev && prev.to === i - 1 && prev.top === t && prev.bottom === b) prev.to = i;
    else boxes.push({ from: i, to: i, top: t, bottom: b, current: false });
  }
  const cur = boxes[boxes.length - 1] ?? null;
  // Only a box that runs to the last bar is "current".
  const current = cur && cur.to === bars.length - 1 ? cur : null;
  if (current) current.current = true;
  const offsets = (pts: { t: string; v: number }[]) => {
    const s = [...pts].sort((a, b) => a.t.localeCompare(b.t));
    return s.length >= 2 && s[0].t === lastTime ? s.map((p, k) => ({ k, value: p.v })) : [];
  };
  const topExtension = offsets(ext);
  const emaProjection = offsets(proj);
  const tickTop = current ? tickSize(current.top) : 0;
  const tickBot = current ? tickSize(current.bottom) : 0;
  return {
    boxes,
    topExtension,
    emaProjection,
    current,
    buyStop: current ? roundTick(current.top + tickTop, tickTop) : null,
    stop: current ? roundTick(current.bottom - tickBot, tickBot) : null,
    topAt,
    bottomAt,
  };
}

/** Rows up to a date (bar replay): projections are dropped, they belong to the real last bar. */
export function darvasRowsUpTo(rows: readonly DarvasRow[] | null | undefined, date: string | null): DarvasRow[] {
  if (!rows) return [];
  if (!date) return rows.slice();
  return rows.filter((r) => !r.projected && !!r.trade_date && r.trade_date <= date);
}
