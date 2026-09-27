/**
 * The "current list" of symbols (the table / queue / chart grid the user last
 * opened a stock from), so the big chart can step through it with J/K.
 * Tables register their rows in display order when a row is clicked/focused.
 */
let list: string[] = [];

export function setNavList(symbols: readonly (string | null | undefined)[]): void {
  const seen = new Set<string>();
  const next: string[] = [];
  for (const s of symbols) {
    if (typeof s === 'string' && s && !seen.has(s)) {
      seen.add(s);
      next.push(s);
    }
  }
  list = next;
}

export function getNavList(): readonly string[] {
  return list;
}

/**
 * Neighbour of `current` in `symbols` (dir +1 = next / J, -1 = previous / K).
 * Clamps at the ends; a symbol not in the list starts at the first entry.
 */
export function stepSymbol(symbols: readonly string[], current: string | null, dir: 1 | -1): string | null {
  if (symbols.length === 0) return null;
  const i = current ? symbols.indexOf(current) : -1;
  if (i < 0) return symbols[0];
  const j = Math.max(0, Math.min(symbols.length - 1, i + dir));
  return symbols[j];
}
