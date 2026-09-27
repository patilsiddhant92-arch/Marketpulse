import { CapitalFlowDashboard } from '../components/CapitalFlowDashboard';
import { SectorWorkspace } from '../components/SectorWorkspace';
import { LegacyFrame, useLegacyProps } from './legacy';

/** Groups — Sector Intel + Capital Flow merged (spec D4); legacy views for now. */
export default function GroupsRoute() {
  const p = useLegacyProps();
  return (
    <LegacyFrame
      note="Groups rebuild pending (spec 7.4)"
      views={[
        {
          id: 'sectors',
          label: 'Sector matrix',
          render: () => <SectorWorkspace onSelectSymbol={p.onSelectSymbol} onOpenMultiChart={p.onOpenMultiChart} />,
        },
        {
          id: 'flow',
          label: 'Capital flow',
          render: () => (
            <CapitalFlowDashboard onSelectSymbol={p.onSelectSymbol} onOpenMultiChart={p.onOpenMultiChart} onAddToBasket={p.onAddToBasket} />
          ),
        },
      ]}
    />
  );
}
