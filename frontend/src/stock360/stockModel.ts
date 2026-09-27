/**
 * Pure view-model helpers for Stock 360 (spec 7.7). Only reshape served
 * values; never fill a missing number.
 */
import type { BarRow, QueueRow, RsRow, StockAdjustment, StockDealRow, StockEventRow } from '../api/types';
import type { OHLCBar } from '../lib/indicators';
import { resampleBars } from '../lib/indicators';
import type { ChartMarker, ChartOverlay, LinePoint, Timeframe } from '../ui/Chart';

export const QUEUE_ORDER = ['darvas_squeeze', 'darvas_10ema', 'vcp'] as const;
export type QueueKey = (typeof QUEUE_ORDER)[number];

export const QUEUE_LABEL: Record<string, string> = {
  darvas_squeeze: 'Darvas Squeeze',
  darvas_10ema: 'Darvas 10 EMA',
  vcp: 'VCP',
};

/** Served bars -> chart bars; rows missing a date or any OHLC value are dropped, never filled. */
export function toOHLC(rows: readonly BarRow[]): OHLCBar[] {
  return rows.flatMap((r) =>
    r.trade_date && r.open != null && r.high != null && r.low != null && r.close != null
      ? [
          {
            time: r.trade_date,
            open: r.open,
            high: r.high,
            low: r.low,
            close: r.close,
            volume: r.volume ?? null,
            delivery_pct: r.delivery_pct ?? null,
          },
        ]
      : [],
  );
}

/** Map served events onto chart marker kinds by their free-text type. */
export function eventToMarker(e: StockEventRow): ChartMarker | null {
  if (!e.event_date || !e.event_type) return null;
  const t = e.event_type.toLowerCase();
  if (t.includes('bonus')) return { time: e.event_date, kind: 'bonus' };
  if (t.includes('split')) return { time: e.event_date, kind: 'split' };
  if (t.includes('demerger')) return { time: e.event_date, kind: 'demerger' };
  if (t.includes('result') || t.includes('board')) return { time: e.event_date, kind: 'results' };
  if (t.includes('dividend') || t.startsWith('ex')) return { time: e.event_date, kind: 'ex_date' };
  return null;
}

export function adjustmentToMarker(a: StockAdjustment): ChartMarker | null {
  if (!a.ex_date) return null;
  const k = (a.kind ?? '').toLowerCase();
  return { time: a.ex_date, kind: k === 'bonus' ? 'bonus' : k === 'split' ? 'split' : k === 'demerger' ? 'demerger' : 'custom' };
}

/** 'BUY' / 'SELL' (any case, B/S) -> side; anything else -> null (never guessed). */
export function dealSide(side: string | null | undefined): 'buy' | 'sell' | null {
  const s = (side ?? '').trim().toLowerCase();
  if (s === 'buy' || s === 'b' || s === 'purchase') return 'buy';
  if (s === 'sell' || s === 's' || s === 'sale') return 'sell';
  return null;
}

/** Institutional prints only (spec 7.7), one marker per session and side. */
export function dealMarkers(rows: readonly StockDealRow[]): ChartMarker[] {
  const seen = new Set<string>();
  const out: ChartMarker[] = [];
  for (const d of rows) {
    const side = dealSide(d.side);
    if (!d.trade_date || !side || d.institutional !== true) continue;
    const key = `${d.trade_date}:${side}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ time: d.trade_date, kind: side === 'buy' ? 'deal_buy' : 'deal_sell' });
  }
  return out;
}

/** Net institutional ₹ Cr per side for a list of prints (NULL when no priced prints). */
export function dealNet(rows: readonly StockDealRow[]): { buy: number | null; sell: number | null; net: number | null } {
  let buy: number | null = null;
  let sell: number | null = null;
  for (const d of rows) {
    const side = dealSide(d.side);
    if (!side || d.value_cr == null) continue;
    if (side === 'buy') buy = (buy ?? 0) + d.value_cr;
    else sell = (sell ?? 0) + d.value_cr;
  }
  const net = buy == null && sell == null ? null : (buy ?? 0) - (sell ?? 0);
  return { buy, sell, net };
}

/** Bars shown for a timeframe (client resample of full daily history). */
export function barsFor(daily: readonly OHLCBar[], tf: Timeframe): OHLCBar[] {
  return resampleBars(daily, tf);
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

/**
 * Snap dated points onto the displayed bar times (a weekly bar carries the
 * week's points; the last point in a period wins). Points after the last bar
 * are dropped.
 */
export function snapPoints<P extends LinePoint>(points: readonly P[], barTimes: readonly string[]): P[] {
  const out = new Map<string, P>();
  for (const p of points) {
    const i = firstAtOrAfter(barTimes, p.time);
    if (i < 0) continue;
    out.set(barTimes[i], { ...p, time: barTimes[i] });
  }
  return [...out.values()].sort((a, b) => a.time.localeCompare(b.time));
}

export type RsBenchmark = 'midsml400' | 'nifty50';
export const RS_LABEL: Record<RsBenchmark, string> = { midsml400: 'RS vs MidSml400', nifty50: 'RS vs Nifty 50' };

/**
 * RS line rebased to 100 at its first non-null value, so the pane reads as
 * "% out/under-performance since the start". NULL ratios stay NULL.
 */
export function rsSeries(rows: readonly RsRow[], bm: RsBenchmark): (LinePoint & { new_high?: boolean | null })[] {
  const key = bm === 'midsml400' ? 'rs_midsml400' : 'rs_nifty50';
  const hiKey = bm === 'midsml400' ? 'rs_midsml400_new_high' : 'rs_nifty50_new_high';
  const base = rows.find((r) => r[key] != null && (r[key] as number) > 0)?.[key] as number | undefined;
  return rows.flatMap((r) => {
    if (!r.trade_date) return [];
    const v = r[key];
    return [{ time: r.trade_date, value: v == null || !base ? null : (v / base) * 100, new_high: r[hiKey] ?? null }];
  });
}

/** Flat line from `from` to the last bar at `value` (NULL value = no line). */
function level(
  id: string,
  label: string,
  value: number | null | undefined,
  from: string | null | undefined,
  lastTime: string,
  color: ChartOverlay['color'],
  dashed = true,
  axisLabel = false,
): ChartOverlay | null {
  if (value == null || !from || from > lastTime) return null;
  return { id, label, color, dashed, axisLabel, data: [{ time: from, value }, { time: lastTime, value }] };
}

export interface SetupOverlayOptions {
  /** Real Darvas boxes are painted: skip the flat box-top/bottom lines, keep the trigger. */
  darvasBoxes?: boolean;
}

/**
 * Price-pane overlays for the stock's active setups: trigger / stop levels,
 * Darvas box, VCP contraction zig-zag. Uses only served geometry.
 */
export function setupOverlays(
  setups: Record<string, QueueRow | null | undefined> | null | undefined,
  bars: readonly OHLCBar[],
  opts: SetupOverlayOptions = {},
): ChartOverlay[] {
  if (!setups || bars.length === 0) return [];
  const last = bars[bars.length - 1].time;
  const lookbackStart = bars[Math.max(0, bars.length - 20)].time;
  const out: ChartOverlay[] = [];
  const sq = setups.darvas_squeeze;
  if (sq) {
    const from = sq.signal_date && sq.signal_date < lookbackStart ? sq.signal_date : lookbackStart;
    const box = opts.darvasBoxes
      ? [level('sq-trigger', 'Squeeze trigger', sq.trigger_price ?? sq.darvas_box_top, from, last, 'up', true, true)]
      : [
          level('sq-top', 'Darvas box top', sq.darvas_box_top, from, last, 'accent', false),
          level('sq-bottom', 'Darvas box bottom', sq.darvas_box_bottom, from, last, 'accent', false),
        ];
    out.push(
      ...[...box, level('sq-stop', 'Squeeze stop', sq.stop_price, lookbackStart, last, 'down', true, true)].filter(
        (o): o is ChartOverlay => o !== null,
      ),
    );
  }
  const e10 = setups.darvas_10ema;
  if (e10) {
    const from = e10.signal_date ?? lookbackStart;
    out.push(
      ...[
        level('e10-trigger', '10 EMA trigger', e10.trigger_price, from, last, 'up', true, true),
        level('e10-stop', '10 EMA stop', e10.stop_price, from, last, 'down', true, true),
      ].filter((o): o is ChartOverlay => o !== null),
    );
  }
  const vcp = setups.vcp;
  if (vcp) {
    const cs = vcp.vcp_contractions ?? [];
    const zig: LinePoint[] = [];
    for (const c of cs) {
      if (c.start_date && c.peak != null) zig.push({ time: c.start_date, value: c.peak });
      if (c.trough_date && c.trough != null) zig.push({ time: c.trough_date, value: c.trough });
    }
    const lastC = cs[cs.length - 1];
    if (lastC?.end_date && lastC.peak != null) zig.push({ time: lastC.end_date, value: lastC.peak });
    const dedup = [...new Map(zig.sort((a, b) => a.time.localeCompare(b.time)).map((p) => [p.time, p])).values()];
    if (dedup.length >= 2) out.push({ id: 'vcp-zig', label: 'VCP contractions', color: 'violet', data: dedup });
    const from = cs[0]?.start_date ?? lookbackStart;
    out.push(
      ...[
        level('vcp-pivot', 'VCP pivot', vcp.trigger_price, lastC?.start_date ?? from, last, 'up', true, true),
        level('vcp-stop', 'VCP stop', vcp.stop_price, lastC?.trough_date ?? from, last, 'down', true, true),
      ].filter((o): o is ChartOverlay => o !== null),
    );
  }
  return out;
}

/** Overlays snapped onto W/M bars (flat levels keep their two ends). */
export function snapOverlays(overlays: readonly ChartOverlay[], barTimes: readonly string[]): ChartOverlay[] {
  return overlays
    .map((o) => ({ ...o, data: snapPoints(o.data, barTimes) }))
    .filter((o) => o.data.length >= 1);
}
