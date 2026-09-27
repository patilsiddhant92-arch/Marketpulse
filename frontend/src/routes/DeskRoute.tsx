import { useEffect, useState } from 'react';
import { CockpitWorkspace } from '../components/CockpitWorkspace';
import { ExposureGateHeader } from '../components/ExposureGateHeader';
import type { MarketRegimeResponse } from '../types';
import { useShell } from '../shell/ShellContext';
import { LegacyFrame, useLegacyProps } from './legacy';

/** Desk — legacy Action Desk (Cockpit) + exposure strip until the rebuild. */
export default function DeskRoute() {
  const shell = useShell();
  const legacy = useLegacyProps();
  const [regime, setRegime] = useState<MarketRegimeResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch('/api/market/regime', { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setRegime(d as MarketRegimeResponse | null))
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, []);

  return (
    <LegacyFrame note="Desk rebuild pending (spec 7.2)">
      <div className="flex min-h-0 flex-1 flex-col">
        {(loading || regime) && (
          <ExposureGateHeader
            regime={regime}
            loading={loading}
            onOpenBreadth={() => shell.setBreadthOpen(true)}
            onNavigateTab={(t) => shell.goTab(t === 'sector' ? 'groups' : t === 'deals' ? 'deals' : t === 'cockpit' ? 'desk' : 'screener')}
          />
        )}
        <div className="flex min-h-0 flex-1">
          <CockpitWorkspace
            selectedSymbol={legacy.selectedSymbol}
            onSelectSymbol={legacy.onSelectSymbol}
            onAddToBasket={legacy.onAddToBasket}
          />
        </div>
      </div>
    </LegacyFrame>
  );
}
