/**
 * Desk (spec 7.2) — today's decision screen: environment + what changed,
 * the three setup queues with trigger/stop/risk, what's new vs yesterday,
 * and the watchlist with its setup status.
 */
import { useEffect, useRef, useState } from 'react';
import { EnvironmentPanel } from '../desk/EnvironmentPanel';
import { QueuePanel } from '../desk/QueuePanel';
import { DiffPanel, LeadingGroupsPanel, WatchlistPanel } from '../desk/SidePanels';

/** Width of an element (ResizeObserver). */
function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth);
    const ro = new ResizeObserver((e) => setW(Math.round(e[0]?.contentRect.width ?? 0)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** Below this width the right rail folds into the queue panel's tabs. */
const RAIL_MIN_WIDTH = 1060;

export default function DeskRoute() {
  const [ref, width] = useWidth<HTMLDivElement>();
  const rail = width === 0 || width >= RAIL_MIN_WIDTH;
  return (
    <div ref={ref} className="flex h-full min-h-0 flex-col gap-2 overflow-hidden p-2">
      {/* At-a-glance band: verdict + breadth + queue counts (desk/EnvironmentPanel). */}
      <EnvironmentPanel />
      <div className={rail ? 'grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_320px] gap-2' : 'flex min-h-0 flex-1 flex-col'}>
        <QueuePanel
          className="min-h-0 flex-1"
          extraTabs={
            rail
              ? []
              : [
                  { id: 'diff', label: 'New vs yesterday', render: () => <DiffPanel /> },
                  { id: 'watch', label: 'Watchlist', render: () => <WatchlistPanel /> },
                  { id: 'groups', label: 'Groups', render: () => <LeadingGroupsPanel /> },
                ]
          }
        />
        {rail && (
          <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)_minmax(0,1fr)] gap-2">
            <LeadingGroupsPanel />
            <DiffPanel className="min-h-0" />
            <WatchlistPanel className="min-h-0" />
          </div>
        )}
      </div>
    </div>
  );
}
