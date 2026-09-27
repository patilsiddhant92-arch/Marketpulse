/**
 * App shell (spec 7.1): top bar, environment strip, history / API-down
 * banners, keep-alive tab panels, Stock 360 sidecar, command palette.
 */
import { CloudOff } from 'lucide-react';
import { Suspense, useState } from 'react';
import { Outlet, useLocation } from 'react-router';
import { MarketBreadthDrawer } from '../components/MarketBreadthDrawer';
import { StagingBasketDrawer } from '../components/StagingBasketDrawer';
import { cn } from '../lib/cn';
import { fmtDate } from '../lib/fmt';
import { TAB_COMPONENTS } from '../routes/registry';
import { BigChart } from '../stock360/BigChart';
import { Stock360Sidecar } from '../stock360/Stock360';
import { ErrorBoundary } from '../ui/ErrorBoundary';
import { SkeletonRows } from '../ui/Skeleton';
import { CommandPalette } from './CommandPalette';
import { EnvironmentStrip } from './environment';
import { ShellProvider, useShell } from './ShellContext';
import { StockSidecar } from './StockSidecar';
import { TABS, tabFromPath, type TabId } from './tabs';
import { TopBar } from './TopBar';
import { useFreshness } from './useFreshness';
import { useShortcuts } from './useShortcuts';
import { useAsOf } from './urlState';

function HistoryBanner() {
  const [asOf, setAsOf] = useAsOf();
  if (!asOf) return null;
  return (
    <div role="status" className="flex h-7 shrink-0 items-center gap-3 border-b border-violet/40 bg-violet/10 px-3 text-xs text-violet">
      <span className="font-semibold uppercase tracking-wide">History mode</span>
      <span className="text-fg-2">
        Viewing data as of <span className="num text-fg">{fmtDate(asOf)}</span>. Every v2 query uses this date.
      </span>
      <button type="button" onClick={() => setAsOf(null)} className="ml-auto rounded px-2 py-0.5 font-semibold hover:bg-violet/20">
        Back to latest
      </button>
    </div>
  );
}

function ApiDownBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="flex h-7 shrink-0 items-center gap-2 border-b border-down/40 bg-down/10 px-3 text-xs text-down">
      <CloudOff className="h-3.5 w-3.5" aria-hidden />
      <span className="font-semibold">API unreachable</span>
      <span className="text-fg-2">
        The MarketPulse server is not responding — screens below may be empty because of this, not because nothing matched.
      </span>
      <button type="button" onClick={onRetry} className="ml-auto rounded px-2 py-0.5 font-semibold hover:bg-down/20">
        Retry
      </button>
    </div>
  );
}

/** Keeps every visited tab mounted (spec 7.1 "tabs stay mounted"). */
function TabPanels({ active }: { active: TabId | null }) {
  const [visited, setVisited] = useState<TabId[]>(active ? [active] : []);
  const [asOf] = useAsOf();
  if (active && !visited.includes(active)) setVisited([...visited, active]); // adjust state during render

  return (
    <>
      {TABS.filter((t) => visited.includes(t.id) || t.id === active).map((t) => {
        const C = TAB_COMPONENTS[t.id];
        const isActive = t.id === active;
        return (
          <section
            key={t.id}
            aria-label={t.label}
            data-active={isActive}
            hidden={!isActive}
            className={cn('absolute inset-0 flex-col', isActive ? 'flex' : 'hidden')}
          >
            <ErrorBoundary name={t.label} resetKeys={[asOf]}>
              <Suspense fallback={<SkeletonRows rows={12} label={`Loading ${t.label}`} />}>
                <C />
              </Suspense>
            </ErrorBoundary>
          </section>
        );
      })}
    </>
  );
}

function ShellLayout() {
  const shell = useShell();
  const location = useLocation();
  const freshness = useFreshness();
  useShortcuts();
  const activeTab = tabFromPath(location.pathname);
  const isStockPage = location.pathname.startsWith('/stock/');

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bg text-fg">
      <TopBar freshness={freshness} />
      <EnvironmentStrip />
      <HistoryBanner />
      {freshness.apiDown && <ApiDownBanner onRetry={freshness.refetch} />}
      <div className="relative flex min-h-0 flex-1">
        <main className="relative min-w-0 flex-1">
          <div className={cn('absolute inset-0', activeTab ? 'block' : 'hidden')}>
            <TabPanels active={activeTab} />
          </div>
          {!activeTab && (
            <div className="absolute inset-0 flex flex-col">
              <ErrorBoundary name={isStockPage ? 'Stock 360' : 'Page'} resetKeys={[location.pathname]}>
                <Suspense fallback={<SkeletonRows rows={12} />}>
                  <Outlet />
                </Suspense>
              </ErrorBoundary>
            </div>
          )}
        </main>
        {shell.symbol && !isStockPage && (
          <StockSidecar symbol={shell.symbol}>
            <ErrorBoundary name="Stock 360" resetKeys={[shell.symbol]}>
              <Stock360Sidecar key={shell.symbol} symbol={shell.symbol} />
            </ErrorBoundary>
          </StockSidecar>
        )}
      </div>
      {/* Legacy basket bar: the Desk has its own watchlist panel and Stock 360 its star; it would cover their content. */}
      {activeTab !== 'desk' && !isStockPage && (
        <StagingBasketDrawer basket={shell.watchlist} onRemove={shell.removeWatch} onClear={shell.clearWatch} />
      )}
      <MarketBreadthDrawer isOpen={shell.breadthOpen} onClose={() => shell.setBreadthOpen(false)} />
      <CommandPalette />
      {shell.bigChart && (
        <ErrorBoundary name="Big chart" resetKeys={[shell.bigChart]}>
          <BigChart symbol={shell.bigChart} />
        </ErrorBoundary>
      )}
    </div>
  );
}

export function Shell() {
  return (
    <ShellProvider>
      <ShellLayout />
    </ShellProvider>
  );
}
