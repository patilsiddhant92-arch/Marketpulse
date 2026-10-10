/**
 * Chart v2 series maths (pure). Indicator values on the displayed bars of one timeframe.
 */
import { ema, rsi, sma, type OHLCBar } from '../lib/indicators';

export { ema, rsi, sma };

/** Volume candles: multiplier of the normal candle width = volume / average of the 20 bars before, clamped 0.35-3×. */
export const VOL_CANDLE_MIN = 0.35;
export const VOL_CANDLE_MAX = 3;

export function volCandleMultipliers(bars: readonly OHLCBar[]): number[] {
  const avg = sma(
    bars.map((b) => (b.volume != null && b.volume > 0 ? b.volume : null)),
    20,
  );
  return bars.map((b, i) => {
    const a = i > 0 ? avg[i - 1] : null;
    if (b.volume == null || a == null || !(a > 0)) return 1;
    return Math.max(VOL_CANDLE_MIN, Math.min(VOL_CANDLE_MAX, b.volume / a));
  });
}

/** 20-bar average volume (inclusive), the line drawn over the volume bars. */
export function volumeAvg20(bars: readonly OHLCBar[]): (number | null)[] {
  return sma(
    bars.map((b) => b.volume ?? null),
    20,
  );
}

/** RSI 14 and its 14-bar SMA (the RSI pane's signal line). */
export function rsiPane(bars: readonly OHLCBar[], period = 14): { rsi: (number | null)[]; sma: (number | null)[] } {
  const r = rsi(
    bars.map((b) => b.close),
    period,
  );
  return { rsi: r, sma: sma(r, 14) };
}

/** Wilder ATR (RMA of the true range, seeded with the first true range). */
export function atr(bars: readonly OHLCBar[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array<number | null>(bars.length).fill(null);
  let v: number | null = null;
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const pc = i > 0 ? bars[i - 1].close : null;
    const tr = pc == null ? b.high - b.low : Math.max(b.high - b.low, Math.abs(b.high - pc), Math.abs(b.low - pc));
    v = v == null ? tr : v + (tr - v) / period;
    if (i >= period - 1) out[i] = v;
  }
  return out;
}

/**
 * NSE price-band tick size (equity cash tick sizes revised in 2025: < ₹250 → 0.01, < ₹1,000 → 0.05,
 * < ₹5,000 → 0.10, < ₹10,000 → 0.50, < ₹20,000 → 1, else 5). Used for the Darvas buy stop / stop.
 */
export function tickSize(price: number): number {
  if (price < 250) return 0.01;
  if (price < 1000) return 0.05;
  if (price < 5000) return 0.1;
  if (price < 10000) return 0.5;
  if (price < 20000) return 1;
  return 5;
}

export const roundTick = (v: number, tick: number) => Math.round(v / tick) * tick;

/** Anchored VWAP from bar `from` (typical price × volume); null before the anchor or without volume. */
export function anchoredVwap(bars: readonly OHLCBar[], from: number): (number | null)[] {
  let pv = 0;
  let vol = 0;
  return bars.map((b, i) => {
    if (i < from) return null;
    const v = b.volume ?? 0;
    pv += ((b.high + b.low + b.close) / 3) * v;
    vol += v;
    return vol > 0 ? pv / vol : null;
  });
}

/** Last non-null value of a series. */
export function lastValue(xs: readonly (number | null | undefined)[]): number | null {
  for (let i = xs.length - 1; i >= 0; i--) {
    const v = xs[i];
    if (v != null && Number.isFinite(v)) return v;
  }
  return null;
}

export interface BarStats {
  fromHighPct: number | null;
  atrPct: number | null;
  crPerDay: number | null;
  delivPct: number | null;
  rsi: number | null;
}

/** Stat chips computed on the bars (daily bars give the exact meaning: 252-bar high, ATR 14, 20-day ₹ Cr). */
export function barStats(bars: readonly OHLCBar[], tf: 'D' | 'W' | 'M' = 'D'): BarStats {
  const n = bars.length;
  const last = bars[n - 1];
  if (!last) return { fromHighPct: null, atrPct: null, crPerDay: null, delivPct: null, rsi: null };
  const year = tf === 'D' ? 252 : tf === 'W' ? 52 : 12;
  const hi = Math.max(...bars.slice(-year).map((b) => b.high));
  const a = lastValue(atr(bars));
  const r = lastValue(rsiPane(bars).rsi);
  const w = bars.slice(-20).filter((b) => b.volume != null);
  const cr = tf === 'D' && w.length ? w.reduce((s, b) => s + (b.volume as number) * b.close, 0) / w.length / 1e7 : null;
  return {
    fromHighPct: hi > 0 ? (last.close / hi - 1) * 100 : null,
    atrPct: a != null && last.close > 0 ? (a / last.close) * 100 : null,
    crPerDay: cr,
    delivPct: last.delivery_pct ?? null,
    rsi: r,
  };
}
