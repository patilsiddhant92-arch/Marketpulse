/**
 * Read design tokens at runtime, for canvas libraries (lightweight-charts)
 * that cannot use Tailwind classes. Values come from src/styles/tokens.css.
 */
export type TokenName =
  | 'bg'
  | 'surface'
  | 'surface-2'
  | 'surface-3'
  | 'line'
  | 'line-strong'
  | 'fg'
  | 'fg-2'
  | 'fg-3'
  | 'accent'
  | 'up'
  | 'down'
  | 'warn'
  | 'info'
  | 'violet'
  | 'chart-grid'
  | 'ema-10'
  | 'ema-20'
  | 'ema-50'
  | 'ema-200'
  // Chart event candles + drawings (Charts tab).
  | 'ev-results'
  | 'ev-buy'
  | 'ev-placement'
  | 'ev-sell'
  | 'ev-churn'
  | 'ev-breakout'
  | 'ev-breakdown'
  | 'ev-gap'
  | 'draw';

/** Returns "rgba(r, g, b, a)" for a token, or a neutral grey if unresolved. */
export function tokenColor(name: TokenName, alpha = 1): string {
  let triple = '';
  if (typeof window !== 'undefined' && typeof getComputedStyle === 'function') {
    triple = getComputedStyle(document.documentElement).getPropertyValue(`--c-${name}`).trim();
  }
  const parts = triple
    .split(/[\s,]+/)
    .filter(Boolean)
    .map(Number);
  const [r, g, b] = parts.length === 3 && parts.every(Number.isFinite) ? parts : [128, 128, 128];
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
