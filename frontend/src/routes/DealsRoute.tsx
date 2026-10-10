/**
 * Deals (HarkPro/08-tab-deals.md through round 5.6, mockup v1.2).
 *
 * Five views: Today (every deal stock with an evidence verdict), Deal watch (holding / lost / reclaimed
 * vs the deal price), History (5 / 10 / 20 deal sessions with patterns), Houses (class evidence,
 * out-of-sample grades, fund spread by group, Follow) and By group. Stock and house drawers. Every list
 * copies to TradingView as ###Title,NSE:SYM (- and & -> _).
 *
 * URL: ?view= (old ?view=repeated|star|… map to the closest new view), ?q= filter, ?sym= opens the
 * stock drawer, ?house= opens the house drawer.
 */
import type { ReactNode } from 'react';
import { useAsOf, useUrlParam } from '../shell/urlState';
import { fmtDate } from '../lib/fmt';
import { Segmented } from './groups/kit';
import { HouseDrawer, StockDrawer } from './deals/drawers';
import { viewFromParam, VIEWS, type DealsView } from './deals/model';
import { GroupsView, HistoryView, HousesView, TodayView, WatchView, type ViewProps } from './deals/views';

const VIEW_COMPONENTS: Record<DealsView, (p: ViewProps) => ReactNode> = {
  today: TodayView,
  watch: WatchView,
  history: HistoryView,
  houses: HousesView,
  groups: GroupsView,
};

export default function DealsRoute() {
  const [viewParam, setView] = useUrlParam('view');
  const [qParam, setQ] = useUrlParam('q');
  const [symParam, setSym] = useUrlParam('sym');
  const [houseParam, setHouse] = useUrlParam('house');
  const [asOf] = useAsOf();
  const view = viewFromParam(viewParam);
  const text = qParam ?? '';
  const View = VIEW_COMPONENTS[view];
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line bg-surface px-3 py-1.5">
        <h1 className="text-sm font-semibold text-fg">Deals</h1>
        <Segmented label="Deals view" value={view} onChange={(v) => setView(v === 'today' ? null : v)} options={VIEWS} />
        <input
          data-filter-input
          value={text}
          onChange={(e) => setQ(e.target.value || null)}
          placeholder={view === 'houses' ? 'Filter houses / stocks  /' : 'Filter symbol / name / industry  /'}
          aria-label="Filter"
          className="h-6 w-52 rounded border border-line bg-surface-2 px-2 text-xs text-fg placeholder:text-fg-3 focus:border-focus focus:outline-none"
        />
        <span className="ml-auto text-2xs text-fg-3">
          {asOf ? `As of ${fmtDate(asOf)} · ` : ''}Deals confirm a setup. They do not create one. Prop desks are left out of every net.
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        <View key={view} text={text} onStock={(s) => setSym(s)} onHouse={(h) => setHouse(h)} />
      </div>
      <StockDrawer symbol={symParam} onClose={() => setSym(null)} onHouse={(h) => { setSym(null); setHouse(h); }} />
      <HouseDrawer house={houseParam} onClose={() => setHouse(null)} onStock={(s) => { setHouse(null); setSym(s); }} />
    </div>
  );
}
