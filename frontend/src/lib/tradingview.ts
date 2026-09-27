/**
 * The one TradingView watchlist formatter (spec 7.1 Export).
 *   - prefixes NSE:, maps '-' to '_' (TradingView symbol rules), upper-cases
 *   - de-duplicates while keeping first-seen order
 *   - optional ###Section headers
 */
export function toTradingViewSymbol(symbol: string): string {
  return `NSE:${symbol.trim().toUpperCase().replace(/-/g, '_')}`;
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
