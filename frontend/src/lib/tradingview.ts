/**
 * The one TradingView symbol helper + watchlist formatter (spec 7.1 Export). Every tab copies through here.
 *   - prefixes NSE:, maps '-' and '&' to '_' (TradingView symbol rules: BAJAJ-AUTO -> NSE:BAJAJ_AUTO,
 *     M&M -> NSE:M_M), upper-cases
 *   - de-duplicates while keeping first-seen order
 *   - optional ###Section headers
 */
/** Ticker body without the exchange prefix ('m&m' -> 'M_M'). Accepts an already-prefixed 'NSE:SYM'. */
export function tradingViewTicker(symbol: string): string {
  return symbol
    .trim()
    .toUpperCase()
    .replace(/^NSE:/, '')
    .replace(/[-&]/g, '_');
}

export function toTradingViewSymbol(symbol: string): string {
  return `NSE:${tradingViewTicker(symbol)}`;
}

export interface TvSection {
  title?: string;
  symbols: readonly (string | null | undefined)[];
}

/** Returns the paste-ready text and the true number of unique symbols. */
export function formatTradingViewList(sections: readonly TvSection[]): { text: string; count: number } {
  const seen = new Set<string>();
  const lines: string[] = [];
  for (const section of sections) {
    const items: string[] = [];
    for (const raw of section.symbols) {
      if (!raw || !raw.trim()) continue;
      const tv = toTradingViewSymbol(raw);
      if (seen.has(tv)) continue;
      seen.add(tv);
      items.push(tv);
    }
    if (items.length === 0) continue;
    if (section.title) lines.push(`###${section.title}`);
    lines.push(...items);
  }
  return { text: lines.join(','), count: seen.size };
}

export function tradingViewChartUrl(symbol: string): string {
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(toTradingViewSymbol(symbol))}`;
}
