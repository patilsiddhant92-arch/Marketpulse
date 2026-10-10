/** Pure helpers for the Pulse tab (no React). */
import type { BreadthCell, BreadthRow, EmaKey, Lookback, N, Units } from './types';

export const LOOKBACKS: readonly { value: `${Lookback}`; label: string; title: string }[] = [
  { value: '5', label: '5D', title: 'Compare today with 5 sessions ago' },
  { value: '10', label: '10D', title: 'Compare today with 10 sessions ago' },
  { value: '20', label: '1M', title: 'Compare today with 20 sessions (1 month) ago' },
  { value: '60', label: '3M', title: 'Compare today with 60 sessions (3 months) ago' },
  { value: '250', label: '1Y', title: 'Compare today with 250 sessions (1 year) ago' },
];

export function parseLookback(v: string | null | undefined): Lookback {
  const n = Number(v);
  return ([5, 10, 20, 60, 250] as const).includes(n as Lookback) ? (n as Lookback) : 5;
}

export function lookbackLabel(lb: number): string {
  return LOOKBACKS.find((o) => Number(o.value) === lb)?.label ?? `${lb}D`;
}

export const EMA_ROWS: readonly { key: EmaKey; label: string }[] = [
  { key: 'e10', label: '10 EMA' },
  { key: 'e20', label: '20 EMA' },
  { key: 'e50', label: '50 EMA' },
  { key: 'e100', label: '100 EMA' },
  { key: 'e200', label: '200 EMA' },
];

export const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

export function signed(v: N | undefined, digits = 1): string {
  if (!isNum(v)) return '—';
  const s = v.toFixed(digits);
  return v > 0 ? `+${s}` : s === `-${(0).toFixed(digits)}` ? (0).toFixed(digits) : s;
}

export function fixed(v: N | undefined, digits = 0): string {
  return isNum(v) ? v.toFixed(digits) : '—';
}

export function intIN(v: N | undefined): string {
  return isNum(v) ? Math.round(v).toLocaleString('en-IN') : '—';
}

export function toneClass(v: N | undefined, good: 1 | -1 = 1): string {
  if (!isNum(v) || v === 0) return 'text-fg-3';
  return v * good > 0 ? 'text-up' : 'text-down';
}

/** Grid columns: the last min(lookback, 10) sessions, Today last. */
export function gridSessions<T>(rows: readonly T[], lookback: number): T[] {
  const n = Math.min(lookback, 10);
  return rows.slice(Math.max(0, rows.length - n));
}

/** Cell value in the chosen unit. */
export function cellValue(cell: BreadthCell | undefined, units: Units): N {
  if (!cell) return null;
  return units === 'pct' ? cell.pct : cell.count;
}

export function cellText(cell: BreadthCell | undefined, units: Units): string {
  const v = cellValue(cell, units);
  return units === 'pct' ? fixed(v, 0) : intIN(v);
}

/** Cell colour = change vs the prior session; intensity relative to 2.5σ (served). Never the level. */
export function cellBackground(cell: BreadthCell | undefined): string | undefined {
  if (!cell || !isNum(cell.chg) || cell.chg === 0 || !cell.intensity) return undefined;
  const a = Math.max(0, Math.min(0.85, cell.intensity));
  return `rgb(var(--c-${cell.chg > 0 ? 'up' : 'down'}) / ${(a * 0.6).toFixed(3)})`;
}

export const XP_COLOURS = { up: 'rgb(34 211 238)', down: 'rgb(244 63 94)' } as const;

/** Position 0-100 of v on the [min, max] range bar. */
export function rangePos(v: N, min: N, max: N): number | null {
  if (!isNum(v) || !isNum(min) || !isNum(max)) return null;
  if (max === min) return 50;
  return Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100));
}

export function pctlTone(p: N): string {
  if (!isNum(p)) return 'text-fg-3';
  return p >= 60 ? 'text-up' : p <= 30 ? 'text-down' : 'text-fg-2';
}

export function moodColour(tone: string | null | undefined, label?: string | null): string {
  if (label === 'Healthy') return 'text-v-constructive';
  if (label === 'Weak') return 'text-v-weak';
  return tone === 'up' ? 'text-up' : tone === 'warn' ? 'text-warn' : tone === 'down' ? 'text-down' : 'text-fg';
}

/** Generic null-last sort. */
export function sortBy<T>(rows: readonly T[], get: (r: T) => unknown, dir: 1 | -1): T[] {
  return [...rows].sort((a, b) => {
    const x = get(a);
    const y = get(b);
    const xn = x === null || x === undefined;
    const yn = y === null || y === undefined;
    if (xn && yn) return 0;
    if (xn) return 1;
    if (yn) return -1;
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
    return String(x).localeCompare(String(y)) * dir;
  });
}

export interface Rect<T> {
  item: T;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Squarified treemap (Bruls et al.), as in the mockup. Items need a positive weight. */
export function squarify<T>(items: readonly T[], weight: (t: T) => number, W: number, H: number): Rect<T>[] {
  const out: Rect<T>[] = [];
  let rest = items.filter((i) => weight(i) > 0);
  let X = 0;
  let Y = 0;
  let w = W;
  let h = H;
  while (rest.length && w > 0 && h > 0) {
    const short = Math.min(w, h);
    const area = w * h;
    const rtot = rest.reduce((s, i) => s + weight(i), 0);
    let row: T[] = [];
    let best = Infinity;
    for (let i = 0; i < rest.length; i++) {
      const r = rest.slice(0, i + 1);
      const s = (r.reduce((a, b) => a + weight(b), 0) / rtot) * area;
      const worst = Math.max(
        ...r.map((q) => {
          const a = (weight(q) / rtot) * area;
          return Math.max((short * short * a) / (s * s), (s * s) / (short * short * a));
        }),
      );
      if (worst <= best) {
        best = worst;
        row = r;
      } else break;
    }
    if (!row.length) row = [rest[0]];
    const s = (row.reduce((a, b) => a + weight(b), 0) / rtot) * area;
    const thick = s / short;
    let off = 0;
    for (const q of row) {
      const len = ((weight(q) / rtot) * area) / thick;
      if (w >= h) out.push({ item: q, x: X, y: Y + off, w: thick, h: len });
      else out.push({ item: q, x: X + off, y: Y, w: len, h: thick });
      off += len;
    }
    if (w >= h) {
      X += thick;
      w -= thick;
    } else {
      Y += thick;
      h -= thick;
    }
    rest = rest.slice(row.length);
  }
  return out;
}

/** Treemap tile colour: return scaled by period (1D 2.5%, 1W 5%, 1M 10%, 3M 20%). */
export const TREEMAP_SCALE = { ret_1d_pct: 2.5, ret_1w_pct: 5, ret_1m_pct: 10, ret_3m_pct: 20 } as const;
export type TreemapPeriod = keyof typeof TREEMAP_SCALE;

export function returnFill(ret: N, scale: number): string {
  if (!isNum(ret)) return 'rgb(var(--c-surface-3))';
  const a = Math.min(1, Math.abs(ret) / scale);
  return `rgb(var(--c-${ret >= 0 ? 'up' : 'down'}) / ${(0.2 + 0.6 * a).toFixed(3)})`;
}

/** Median of the non-null values. */
export function median(vals: readonly N[]): number | null {
  const v = vals.filter(isNum).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

/** Short date "13 Aug" (no timezone drift: parse the ISO parts). */
export function shortDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return iso;
  return `${d} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1]}`;
}

export function longDate(iso: string): string {
  return `${shortDate(iso)} ${iso.slice(0, 4)}`;
}

/** Value of a breadth row for a trend chart line. */
export function linePoints(rows: readonly BreadthRow[], key: EmaKey): N[] {
  return rows.map((r) => r[key]?.pct ?? null);
}
