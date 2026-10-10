/**
 * RSI divergence (HarkPro/09-tab-charts.md §6, round-1 rule). Pure; no chart imports.
 *
 * - Pivots are found on the RSI line (TradingView's "RSI Divergence" convention): a pivot high is
 *   an RSI value strictly above the `left` bars before it and at least as high as the `right`
 *   bars after it (lows mirrored). A pivot is confirmed `right` bars later, so a line never
 *   repaints: no pivot is reported inside the last `right` bars.
 * - Each pivot is compared with the previous pivot of the same type when the two are
 *   `minGap`–`maxGap` bars apart. Price is read at the pivot bars (high for highs, low for lows).
 * - Regular bearish: price higher high, RSI lower high, first RSI high > 60.
 *   Regular bullish: price lower low, RSI higher low, first RSI low < 40.
 * - Hidden (off by default): bearish = price lower high + RSI higher high (first RSI > 60);
 *   bullish = price higher low + RSI lower low (first RSI < 40).
 */

export type DivergenceKind = 'bear' | 'bull' | 'hidden_bear' | 'hidden_bull';

export interface DivergencePoint {
  index: number;
  time: string;
  price: number;
  rsi: number;
}

export interface Divergence {
  kind: DivergenceKind;
  from: DivergencePoint;
  to: DivergencePoint;
  /** Bar index at which the second pivot is confirmed (to.index + right). */
  confirmedAt: number;
}

export interface DivergenceOptions {
  left?: number;
  right?: number;
  minGap?: number;
  maxGap?: number;
  /** First RSI high must be above this for a bearish divergence (default 60). */
  bearAbove?: number;
  /** First RSI low must be below this for a bullish divergence (default 40). */
  bullBelow?: number;
  hidden?: boolean;
}

export const DIVERGENCE_DEFAULTS: Required<DivergenceOptions> = {
  left: 5,
  right: 5,
  minGap: 5,
  maxGap: 60,
  bearAbove: 60,
  bullBelow: 40,
  hidden: false,
};

export interface DivBar {
  time: string;
  high: number;
  low: number;
}

/** Indices of confirmed pivots on `values` (null breaks a window). */
export function findPivots(values: readonly (number | null)[], type: 'high' | 'low', left = 5, right = 5): number[] {
  const out: number[] = [];
  for (let i = left; i < values.length - right; i++) {
    const v = values[i];
    if (v == null) continue;
    let ok = true;
    for (let j = i - left; j <= i + right && ok; j++) {
      if (j === i) continue;
      const w = values[j];
      if (w == null) {
        ok = false;
        break;
      }
      // Strict on the left, non-strict on the right: a flat top pivots on its first bar only.
      if (type === 'high') ok = j < i ? w < v : w <= v;
      else ok = j < i ? w > v : w >= v;
    }
    if (ok) out.push(i);
  }
  return out;
}

export function rsiDivergences(
  bars: readonly DivBar[],
  rsiValues: readonly (number | null)[],
  options: DivergenceOptions = {},
): Divergence[] {
  const o = { ...DIVERGENCE_DEFAULTS, ...options };
  const n = Math.min(bars.length, rsiValues.length);
  const vals = rsiValues.slice(0, n);
  const out: Divergence[] = [];
  const point = (i: number, price: number): DivergencePoint => ({ index: i, time: bars[i].time, price, rsi: vals[i] as number });

  const scan = (type: 'high' | 'low') => {
    const piv = findPivots(vals, type, o.left, o.right);
    for (let k = 1; k < piv.length; k++) {
      const a = piv[k - 1];
      const b = piv[k];
      const gap = b - a;
      if (gap < o.minGap || gap > o.maxGap) continue;
      const ra = vals[a] as number;
      const rb = vals[b] as number;
      if (type === 'high') {
        const pa = bars[a].high;
        const pb = bars[b].high;
        if (ra <= o.bearAbove) continue;
        if (pb > pa && rb < ra) out.push({ kind: 'bear', from: point(a, pa), to: point(b, pb), confirmedAt: b + o.right });
        else if (o.hidden && pb < pa && rb > ra)
          out.push({ kind: 'hidden_bear', from: point(a, pa), to: point(b, pb), confirmedAt: b + o.right });
      } else {
        const pa = bars[a].low;
        const pb = bars[b].low;
        if (ra >= o.bullBelow) continue;
        if (pb < pa && rb > ra) out.push({ kind: 'bull', from: point(a, pa), to: point(b, pb), confirmedAt: b + o.right });
        else if (o.hidden && pb > pa && rb < ra)
          out.push({ kind: 'hidden_bull', from: point(a, pa), to: point(b, pb), confirmedAt: b + o.right });
      }
    }
  };
  scan('high');
  scan('low');
  return out.sort((x, y) => x.to.index - y.to.index || x.kind.localeCompare(y.kind));
}
