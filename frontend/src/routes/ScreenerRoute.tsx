import { MomentumWorkspace } from '../components/MomentumWorkspace';
import { VcpWorkbenchWorkspace } from '../components/VcpWorkbenchWorkspace';
import { LegacyFrame, useLegacyProps } from './legacy';

/** Screener — Momentum + VCP Workbench merged (spec D4); legacy views for now. */
export default function ScreenerRoute() {
  const p = useLegacyProps();
  return (
    <LegacyFrame
      note="Screener rebuild pending (spec 7.3)"
      views={[
        {
          id: 'momentum',
          label: 'Momentum',
          render: () => (
            <MomentumWorkspace selectedSymbol={p.selectedSymbol} onSelectSymbol={p.onSelectSymbol} onAddToBasket={p.onAddToBasket} />
          ),
        },
        {
          id: 'vcp',
          label: 'VCP Workbench',
          render: () => (
            <VcpWorkbenchWorkspace selectedSymbol={p.selectedSymbol} onSelectSymbol={p.onSelectSymbol} onAddToBasket={p.onAddToBasket} />
          ),
        },
      ]}
    />
  );
}
