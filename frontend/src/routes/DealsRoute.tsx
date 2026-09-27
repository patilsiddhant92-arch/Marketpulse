import { DealsWorkspace } from '../components/DealsWorkspace';
import { LegacyFrame, useLegacyProps } from './legacy';

/** Deals — legacy Institutional Deals Desk until the rebuild. */
export default function DealsRoute() {
  const p = useLegacyProps();
  return (
    <LegacyFrame note="Deals rebuild pending (spec 7.5)">
      <DealsWorkspace selectedSymbol={p.selectedSymbol} onSelectSymbol={p.onSelectSymbol} onAddToBasket={p.onAddToBasket} />
    </LegacyFrame>
  );
}
