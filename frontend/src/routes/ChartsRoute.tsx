import { useMemo } from 'react';
import { MultiChartModal } from '../components/MultiChartModal';
import { useShell } from '../shell/ShellContext';
import { isSymbol, useUrlParam } from '../shell/urlState';
import { LegacyFrame } from './legacy';

/**
 * Charts (lazy-loaded) — the legacy tiled multi-chart window, contained to the
 * tab area. `transform` makes this div the containing block for the legacy
 * modal's `position: fixed`, so it fills the tab instead of the viewport.
 * Symbols come from ?syms=A,B,C (Open in Charts), else watchlist, else sidecar symbol.
 */
export default function ChartsRoute() {
  const shell = useShell();
  const [symsParam] = useUrlParam('syms');
  const symbols = useMemo(() => {
    const fromUrl = (symsParam ?? '')
      .split(',')
      .map((s) => s.trim().toUpperCase())
      .filter(isSymbol);
    if (fromUrl.length) return fromUrl;
    if (shell.watchlist.length) return shell.watchlist;
    return shell.symbol ? [shell.symbol] : [];
  }, [symsParam, shell.watchlist, shell.symbol]);

  return (
    <LegacyFrame note="Charts rebuild pending (spec 7.8) · source picker arrives with the rebuild">
      <div className="relative min-h-0 flex-1 [transform:translateZ(0)]">
        <MultiChartModal
          isOpen
          onClose={() => shell.goTab('desk')}
          initialSymbols={symbols}
          onSelectSymbol={(sym) => shell.openSymbol(sym)}
        />
      </div>
    </LegacyFrame>
  );
}
