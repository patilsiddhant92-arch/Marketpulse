/**
 * Tiny pure helpers for the tab "at a glance" bands. They only count or
 * reduce rows a tab already loaded; they never invent a value.
 */

/** Most frequent non-empty key, ties broken alphabetically. NULL when no key. */
export function topCount<T>(rows: readonly T[], key: (r: T) => string | null | undefined): { key: string; count: number } | null {
  const counts = new Map<string, number>();
  for (const r of rows) {
    const k = key(r);
    if (k) counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  let best: { key: string; count: number } | null = null;
  for (const [k, c] of counts) {
    if (!best || c > best.count || (c === best.count && k.localeCompare(best.key) < 0)) best = { key: k, count: c };
  }
  return best;
}

/** Count of rows matching a predicate. */
export function countWhere<T>(rows: readonly T[], pred: (r: T) => boolean): number {
  let n = 0;
  for (const r of rows) if (pred(r)) n++;
  return n;
}

/** Sum of finite values; NULL when there are none. */
export function sumOf<T>(rows: readonly T[], val: (r: T) => number | null | undefined): number | null {
  let s = 0;
  let any = false;
  for (const r of rows) {
    const v = val(r);
    if (typeof v === 'number' && Number.isFinite(v)) {
      s += v;
      any = true;
    }
  }
  return any ? s : null;
}

/** Median of finite values; NULL when there are none. */
export function medianOf<T>(rows: readonly T[], val: (r: T) => number | null | undefined): number | null {
  const xs = rows.map(val).filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  if (xs.length === 0) return null;
  xs.sort((a, b) => a - b);
  const m = xs.length >> 1;
  return xs.length % 2 ? xs[m] : (xs[m - 1] + xs[m]) / 2;
}
