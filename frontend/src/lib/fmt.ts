/**
 * Number and date formatting — Indian conventions, one source of truth.
 *
 * Honesty rule (spec 6.3): NULL stays NULL. Every formatter returns the em dash
 * DASH for null / undefined / NaN / +-Infinity instead of inventing a value.
 * Percent inputs are already in percent units (12.3 means 12.3%).
 */

export const DASH = '—';

export type Nullable<T> = T | null | undefined;

const LOCALE = 'en-IN';

const cache = new Map<string, Intl.NumberFormat>();
function nf(opts: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = JSON.stringify(opts);
  let f = cache.get(key);
  if (!f) {
    f = new Intl.NumberFormat(LOCALE, opts);
    cache.set(key, f);
  }
  return f;
}

/** True when v is a usable finite number. */
export function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** Plain number with Indian digit grouping: 1234567.8 -> "12,34,567.80". */
export function fmtNum(v: Nullable<number>, digits = 2): string {
  if (!isNum(v)) return DASH;
  return nf({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
}

/** Integer with grouping: 1234567 -> "12,34,567". */
export function fmtInt(v: Nullable<number>): string {
  if (!isNum(v)) return DASH;
  return nf({ maximumFractionDigits: 0 }).format(Math.round(v));
}

/** Rupees: 1234.5 -> "₹1,234.50". */
export function fmtINR(v: Nullable<number>, digits = 2): string {
  if (!isNum(v)) return DASH;
  return nf({
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(v);
}

/** Value already in crores: 1234.5 -> "₹1,234.5 Cr". */
export function fmtCr(v: Nullable<number>, digits = 1): string {
  if (!isNum(v)) return DASH;
  return `${v < 0 ? '-' : ''}₹${fmtNum(Math.abs(v), digits)} Cr`;
}

/** Value already in lakhs: 12.5 -> "₹12.5 L". */
export function fmtL(v: Nullable<number>, digits = 1): string {
  if (!isNum(v)) return DASH;
  return `${v < 0 ? '-' : ''}₹${fmtNum(Math.abs(v), digits)} L`;
}

/**
 * Rupee amount picked into Cr / L / plain by magnitude:
 * 25_000_000 -> "₹2.50 Cr", 450_000 -> "₹4.50 L", 950 -> "₹950".
 */
export function fmtRupeesCompact(v: Nullable<number>, digits = 2): string {
  if (!isNum(v)) return DASH;
  const a = Math.abs(v);
  if (a >= 1e7) return fmtCr(v / 1e7, digits);
  if (a >= 1e5) return fmtL(v / 1e5, digits);
  return fmtINR(v, 0);
}

/** Count in Indian short scale without currency: 2_50_00_000 -> "2.50 Cr", 4_50_000 -> "4.50 L". */
export function fmtCompactIN(v: Nullable<number>, digits = 2): string {
  if (!isNum(v)) return DASH;
  const a = Math.abs(v);
  if (a >= 1e7) return `${fmtNum(v / 1e7, digits)} Cr`;
  if (a >= 1e5) return `${fmtNum(v / 1e5, digits)} L`;
  return fmtInt(v);
}

/** Percent (input in percent units): 12.345 -> "12.3%". */
export function fmtPct(v: Nullable<number>, digits = 1): string {
  if (!isNum(v)) return DASH;
  return `${fmtNum(v, digits)}%`;
}

/** Signed percent: 1.2 -> "+1.2%", -0.5 -> "-0.5%", 0 -> "0.0%". */
export function fmtSignedPct(v: Nullable<number>, digits = 1): string {
  if (!isNum(v)) return DASH;
  const rounded = Number(v.toFixed(digits));
  if (rounded === 0) return `${fmtNum(0, digits)}%`;
  return `${rounded > 0 ? '+' : '-'}${fmtNum(Math.abs(v), digits)}%`;
}

/** Signed number: 3 -> "+3", -2.5 -> "-2.5" (for rank deltas etc.). */
export function fmtSigned(v: Nullable<number>, digits = 0): string {
  if (!isNum(v)) return DASH;
  const rounded = Number(v.toFixed(digits));
  if (rounded === 0) return fmtNum(0, digits);
  return `${rounded > 0 ? '+' : '-'}${fmtNum(Math.abs(v), digits)}`;
}

/** Ratio with an x suffix: 1.534 -> "1.53x". */
export function fmtRatio(v: Nullable<number>, digits = 2): string {
  if (!isNum(v)) return DASH;
  return `${fmtNum(v, digits)}x`;
}

// ---------------------------------------------------------------- dates

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/**
 * Parse an ISO date (YYYY-MM-DD, optionally with time) as a *calendar* date,
 * immune to the viewer's timezone. Returns null when unparseable.
 */
export function parseISODate(v: Nullable<string>): { y: number; m: number; d: number } | null {
  if (!v) return null;
  const match = ISO_DATE.exec(v);
  if (!match) return null;
  const y = Number(match[1]);
  const m = Number(match[2]);
  const d = Number(match[3]);
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  return { y, m, d };
}

/** "2026-09-25" -> "25 Sep 2026". */
export function fmtDate(v: Nullable<string>): string {
  const p = parseISODate(v);
  if (!p) return DASH;
  return `${p.d} ${MONTHS[p.m - 1]} ${p.y}`;
}

/** "2026-09-25" -> "25 Sep". */
export function fmtDateShort(v: Nullable<string>): string {
  const p = parseISODate(v);
  if (!p) return DASH;
  return `${p.d} ${MONTHS[p.m - 1]}`;
}

/** "2026-09-25" -> "Fri". */
export function fmtWeekday(v: Nullable<string>): string {
  const p = parseISODate(v);
  if (!p) return DASH;
  return WEEKDAYS[new Date(Date.UTC(p.y, p.m - 1, p.d)).getUTCDay()];
}

/** "2026-09-25" -> "Fri 25 Sep". */
export function fmtDateWithDay(v: Nullable<string>): string {
  const p = parseISODate(v);
  if (!p) return DASH;
  return `${fmtWeekday(v)} ${fmtDateShort(v)}`;
}

// ---------------------------------------------------------------- generic

export type FormatKind =
  'num' | 'int' | 'pct' | 'signedPct' | 'signed' | 'inr' | 'cr' | 'lakh' | 'rupeesCompact' | 'ratio' | 'date' | 'text';

/** Format by kind name — used by DataTable and Metric column specs. */
export function fmtValue(v: unknown, kind: FormatKind = 'text', digits?: number): string {
  if (v === null || v === undefined || v === '') return DASH;
  switch (kind) {
    case 'num':
      return fmtNum(v as number, digits ?? 2);
    case 'int':
      return fmtInt(v as number);
    case 'pct':
      return fmtPct(v as number, digits ?? 1);
    case 'signedPct':
      return fmtSignedPct(v as number, digits ?? 1);
    case 'signed':
      return fmtSigned(v as number, digits ?? 0);
    case 'inr':
      return fmtINR(v as number, digits ?? 2);
    case 'cr':
      return fmtCr(v as number, digits ?? 1);
    case 'lakh':
      return fmtL(v as number, digits ?? 1);
    case 'rupeesCompact':
      return fmtRupeesCompact(v as number, digits ?? 2);
    case 'ratio':
      return fmtRatio(v as number, digits ?? 2);
    case 'date':
      return fmtDate(v as string);
    case 'text':
    default:
      if (typeof v === 'number') return Number.isFinite(v) ? String(v) : DASH;
      return String(v);
  }
}

/** Numeric kinds are right-aligned in tables. */
export function isNumericKind(kind: FormatKind | undefined): boolean {
  return kind !== undefined && kind !== 'text' && kind !== 'date';
}
