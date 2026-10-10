/** Client-side helpers for chart overlays. Inputs must already be adjusted prices. */

export interface OHLCBar {
  time: string; // YYYY-MM-DD (a real session date)
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  delivery_pct?: number | null;
}

/** Exponential moving average seeded with an SMA; null until `period` bars exist. */
export function ema(values: readonly number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array<number | null>(values.length).fill(null);
  if (period <= 0 || values.length < period) return out;
  const k = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) seed += values[i];
  let prev = seed / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

function isoWeekKey(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  const day = date.getUTCDay() || 7; // ISO: Monday=1 .. Sunday=7
  date.setUTCDate(date.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((date.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  return `${date.getUTCFullYear()}-W${week}`;
}

/**
 * Resample daily bars to weekly / monthly. Each bar is stamped with the LAST
 * session of its period so a date-synced crosshair lands on a real session.
 * Delivery % is volume-weighted; NULL delivery stays NULL.
 */
export function resampleBars(bars: readonly OHLCBar[], tf: 'D' | 'W' | 'M'): OHLCBar[] {
  if (tf === 'D') return bars.slice();
  const keyOf = tf === 'W' ? isoWeekKey : (iso: string) => iso.slice(0, 7);
  const out: OHLCBar[] = [];
  let cur: OHLCBar | null = null;
  let curKey = '';
  let delivNum = 0;
  let delivDen = 0;
  const flush = () => {
    if (!cur) return;
    cur.delivery_pct = delivDen > 0 ? delivNum / delivDen : null;
    out.push(cur);
  };
  for (const b of bars) {
    const k = keyOf(b.time);
    if (!cur || k !== curKey) {
      flush();
      cur = { ...b, volume: b.volume ?? null };
      curKey = k;
      delivNum = 0;
      delivDen = 0;
    } else {
      cur.high = Math.max(cur.high, b.high);
      cur.low = Math.min(cur.low, b.low);
      cur.close = b.close;
      cur.time = b.time;
      if (cur.volume == null) cur.volume = b.volume ?? null;
      else if (b.volume != null) cur.volume += b.volume;
    }
    if (b.delivery_pct != null && b.volume != null && b.volume > 0) {
      delivNum += b.delivery_pct * b.volume;
      delivDen += b.volume;
    }
  }
  flush();
  return out;
}

/** Simple moving average; null until `period` values exist. NULL / non-finite inputs break the window (stay null). */
export function sma(values: readonly (number | null | undefined)[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array<number | null>(values.length).fill(null);
  if (period <= 0) return out;
  let sum = 0;
  let run = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null || !Number.isFinite(v)) {
      sum = 0;
      run = 0;
      continue;
    }
    sum += v;
    run++;
    if (run > period) {
      sum -= values[i - period] as number;
      run = period;
    }
    if (run === period) out[i] = sum / period;
  }
  return out;
}

/**
 * Wilder RSI (TradingView `ta.rsi`): RMA of gains / losses seeded with the SMA of the
 * first `period` changes. null for the first `period` bars. 100 when there are no losses.
 */
export function rsi(closes: readonly number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array<number | null>(closes.length).fill(null);
  if (period <= 0 || closes.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) gain += d;
    else loss -= d;
  }
  gain /= period;
  loss /= period;
  const val = (g: number, l: number) => (l === 0 ? (g === 0 ? 50 : 100) : 100 - 100 / (1 + g / l));
  out[period] = val(gain, loss);
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    gain = (gain * (period - 1) + Math.max(d, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-d, 0)) / period;
    out[i] = val(gain, loss);
  }
  return out;
}
