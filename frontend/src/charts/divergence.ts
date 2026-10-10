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

// ====================================================================== Sprint 2 contract
/**
 * RSI divergence rows as served by GET /api/v2/charts/{sym}/divergences (HarkPro/12-sprint2-plan.md,
 * built by the diverg agent). `detectDivergences` is the client fallback when the endpoint is
 * missing: a port of HarkPro/tools/divergence/detect_prototype.py with the same rules.
 *
 * - 3-bar pivots on the low (bull) / high (bear): the bar equals the min / max of the 7-bar window.
 *   A pivot is confirmed 3 bars later (no look-ahead: no pivot inside the last 3 bars).
 * - Consecutive pivots 5-60 bars apart. "Equal" = within 0.5 ATR(14) for price, 2 points for RSI.
 * - Strong: price beyond + RSI against. Medium: price equal + RSI against. Weak: price beyond + RSI
 *   equal. Hidden: price against + RSI beyond.
 * - Regular bull needs an RSI pivot < 40 and RSI never > 60 between the pivots; bear mirrored
 *   (> 60, never < 40). Hidden bull needs close > EMA50 and RSI2 < 50; hidden bear mirrored.
 * - Trigger = the high between the lows (bull) / the low between the highs (bear). Stop = the 2nd
 *   pivot's low / high. Status after the confirm bar: a close beyond the trigger = triggered, a close
 *   beyond the stop = failed (whichever comes first), else watching.
 */
export type DivSide = 'bull' | 'bear';
export type DivType = 'Strong' | 'Medium' | 'Weak' | 'Hidden';
export type DivStatus = 'watching' | 'triggered' | 'failed';

export interface DivergenceRow {
  side: DivSide;
  type: DivType;
  p1_date: string;
  p2_date: string;
  p1_price: number;
  p2_price: number;
  p1_rsi: number;
  p2_rsi: number;
  confirm_date: string;
  trigger_price: number | null;
  stop_price: number | null;
  status: DivStatus;
}

export const DIV_RULES = { K: 3, MINGAP: 5, MAXGAP: 60, PTOL: 0.5, RTOL: 2 } as const;

export interface DetectBar {
  time: string;
  high: number;
  low: number;
  close: number;
}

/** pandas ewm(alpha=1/n, adjust=False) RSI, as the prototype computes it (seeded on the first change). */
export function rsiEwm(closes: readonly number[], n = 14): (number | null)[] {
  const out: (number | null)[] = closes.map(() => null);
  let up: number | null = null;
  let dn: number | null = null;
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    const u = Math.max(d, 0);
    const w = Math.max(-d, 0);
    up = up == null ? u : up + (u - up) / n;
    dn = dn == null ? w : dn + (w - dn) / n;
    out[i] = dn === 0 ? (up === 0 ? null : 100) : 100 - 100 / (1 + up / dn);
  }
  return out;
}

function atrEwm(bars: readonly DetectBar[], n = 14): number[] {
  const out: number[] = [];
  let v = 0;
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const pc = i > 0 ? bars[i - 1].close : NaN;
    const tr = Math.max(b.high - b.low, Number.isNaN(pc) ? 0 : Math.abs(b.high - pc), Number.isNaN(pc) ? 0 : Math.abs(b.low - pc));
    v = i === 0 ? tr : v + (tr - v) / n;
    out.push(v);
  }
  return out;
}

function emaSpan(xs: readonly number[], span: number): number[] {
  const a = 2 / (span + 1);
  const out: number[] = [];
  xs.forEach((x, i) => out.push(i === 0 ? x : out[i - 1] + a * (x - out[i - 1])));
  return out;
}

export function classifyDivergence(dp: number, dr: number, side: DivSide): DivType | null {
  const { PTOL, RTOL } = DIV_RULES;
  const pe = Math.abs(dp) <= PTOL;
  const re = Math.abs(dr) <= RTOL;
  if (side === 'bull') {
    if (dp < -PTOL && dr > RTOL) return 'Strong';
    if (pe && dr > RTOL) return 'Medium';
    if (dp < -PTOL && re) return 'Weak';
    if (dp > PTOL && dr < -RTOL) return 'Hidden';
  } else {
    if (dp > PTOL && dr < -RTOL) return 'Strong';
    if (pe && dr < -RTOL) return 'Medium';
    if (dp > PTOL && re) return 'Weak';
    if (dp < -PTOL && dr > RTOL) return 'Hidden';
  }
  return null;
}

export function detectDivergences(bars: readonly DetectBar[], rsiValues?: readonly (number | null)[]): DivergenceRow[] {
  const { K, MINGAP, MAXGAP } = DIV_RULES;
  const n = bars.length;
  if (n < 2 * K + 2) return [];
  const r = rsiValues ?? rsiEwm(bars.map((b) => b.close));
  const atrs = atrEwm(bars);
  const ema50 = emaSpan(
    bars.map((b) => b.close),
    50,
  );
  const out: DivergenceRow[] = [];
  for (const side of ['bull', 'bear'] as const) {
    const s = bars.map((b) => (side === 'bull' ? b.low : b.high));
    const piv: number[] = [];
    for (let i = K; i < n - K; i++) {
      const w = s.slice(i - K, i + K + 1);
      if (side === 'bull' ? s[i] === Math.min(...w) : s[i] === Math.max(...w)) piv.push(i);
    }
    for (let k = 1; k < piv.length; k++) {
      const a = piv[k - 1];
      const b = piv[k];
      if (b - a < MINGAP || b - a > MAXGAP) continue;
      const r1 = r[a];
      const r2 = r[b];
      if (r1 == null || r2 == null || !(atrs[b] > 0)) continue;
      const mid = r.slice(a, b + 1).filter((x): x is number => x != null);
      const t = classifyDivergence((s[b] - s[a]) / atrs[b], r2 - r1, side);
      if (!t) continue;
      if (t !== 'Hidden') {
        if (side === 'bull' && (Math.min(r1, r2) >= 40 || Math.max(...mid) > 60)) continue;
        if (side === 'bear' && (Math.max(r1, r2) <= 60 || Math.min(...mid) < 40)) continue;
      } else {
        const trend = bars[b].close > ema50[b];
        if (side === 'bull' && !(trend && r2 < 50)) continue;
        if (side === 'bear' && !(!trend && r2 > 50)) continue;
      }
      const span = bars.slice(a, b + 1);
      const trigger = side === 'bull' ? Math.max(...span.map((x) => x.high)) : Math.min(...span.map((x) => x.low));
      const stop = side === 'bull' ? bars[b].low : bars[b].high;
      const conf = b + K;
      let status: DivStatus = 'watching';
      for (let j = conf + 1; j < n; j++) {
        const c = bars[j].close;
        if (side === 'bull' ? c > trigger : c < trigger) {
          status = 'triggered';
          break;
        }
        if (side === 'bull' ? c < stop : c > stop) {
          status = 'failed';
          break;
        }
      }
      out.push({
        side,
        type: t,
        p1_date: bars[a].time,
        p2_date: bars[b].time,
        p1_price: s[a],
        p2_price: s[b],
        p1_rsi: r1,
        p2_rsi: r2,
        confirm_date: bars[conf].time,
        trigger_price: trigger,
        stop_price: stop,
        status,
      });
    }
  }
  return out.sort((x, y) => x.confirm_date.localeCompare(y.confirm_date) || x.side.localeCompare(y.side));
}

export interface DivergenceView {
  row: DivergenceRow;
  /** The latest divergence is bright; older ones are faded. */
  latest: boolean;
  label: string;
}

/** Rows to draw: confirmed by `upTo` (bar replay), hidden ones only on request; the latest one bright. */
export function divergenceViews(
  rows: readonly DivergenceRow[],
  opts: { hidden?: boolean; upTo?: string | null; from?: string | null } = {},
): DivergenceView[] {
  const kept = rows
    .filter((r) => (opts.hidden ? true : r.type !== 'Hidden'))
    .filter((r) => !opts.upTo || r.confirm_date <= opts.upTo)
    .filter((r) => !opts.from || r.p1_date >= opts.from)
    .slice()
    .sort((a, b) => a.confirm_date.localeCompare(b.confirm_date) || a.p2_date.localeCompare(b.p2_date));
  return kept.map((row, i) => ({
    row,
    latest: i === kept.length - 1,
    label: `${row.side === 'bull' ? 'Bull' : 'Bear'} ${row.type}`,
  }));
}
