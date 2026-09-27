/**
 * Desk (spec 7.2) — two sub-views:
 *   Today  — what moved today and why (market strip, movers, breakouts, groups today);
 *   Setups — environment + what changed, the three setup queues with trigger/stop/risk,
 *            what's new vs yesterday, and the watchlist with its setup status.
 * The sub-view is remembered per browser (?view=today|setups while the tab is active).
 */
import { useEffect, useRef, useState } from 'react';
import { CompareStrip } from '../desk/CompareStrip';
import { EnvironmentPanel } from '../desk/EnvironmentPanel';
import { QueuePanel } from '../desk/QueuePanel';
import { DiffPanel, LeadingGroupsPanel, WatchlistPanel } from '../desk/SidePanels';
import { useTabUrlState } from '../lib/tabUrlState';
import { TodayView } from '../today/TodayView';
import { Segmented } from './groups/kit';

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

const DESK_VIEWS = [
  { value: 'today', label: 'Today', title: 'What moved today and why: market strip, movers, breakouts, groups' },
  { value: 'setups', label: 'Setups', title: 'Environment, the three setup queues, new vs yesterday, watchlist' },
] as const;
type DeskView = (typeof DESK_VIEWS)[number]['value'];
const DESK_DEFAULTS = { view: 'setups' };

export default function DeskRoute() {
  const [ref, width] = useWidth<HTMLDivElement>();
  const rail = width === 0 || width >= RAIL_MIN_WIDTH;
  const [state, setState] = useTabUrlState('/desk', DESK_DEFAULTS);
  const view: DeskView = state.view === 'today' ? 'today' : 'setups';
  // Keep a visited view mounted (queries and scroll survive switching back).
  const [seen, setSeen] = useState<ReadonlySet<DeskView>>(() => new Set([view]));
  if (!seen.has(view)) setSeen(new Set([...seen, view])); // adjust state while rendering (no effect round-trip)
  return (
    <div ref={ref} className="flex h-full min-h-0 flex-col gap-2 overflow-hidden p-2">
      <div className="flex shrink-0 items-center gap-2">
        <Segmented label="Desk view" options={DESK_VIEWS} value={view} onChange={(v) => setState({ view: v === 'setups' ? null : v })} />
      </div>
      {seen.has('today') && (
        <div className={view === 'today' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
          <TodayView rail={rail} />
        </div>
      )}
      {seen.has('setups') && (
        <div className={view === 'setups' ? 'flex min-h-0 flex-1 flex-col gap-2' : 'hidden'}>
          <SetupsView rail={rail} />
        </div>
      )}
    </div>
  );
}

function SetupsView({ rail }: { rail: boolean }) {
  return (
    <>
      {/* At-a-glance band: verdict + breadth + queue counts (desk/EnvironmentPanel). */}
      <EnvironmentPanel />
      {/* Trend: now vs 5 sessions ago (queues, breadth, verdict, top groups). */}
      <CompareStrip />
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
    </>
  );
}
