/** Stock 360 full page (/stock/:sym), spec 7.7. */
import { useParams } from 'react-router';
import { Stock360Page } from '../stock360/Stock360';
import { isSymbol } from '../shell/urlState';
import { EmptyState } from '../ui/EmptyState';

// Re-exported for other tabs that map served bars/events onto the Chart.
export { eventToMarker, toOHLC } from '../stock360/stockModel';

export default function StockRoute() {
  const { sym = '' } = useParams();
  const symbol = sym.toUpperCase();
  if (!isSymbol(symbol)) return <EmptyState title="Invalid symbol" detail={`"${sym}" is not a valid NSE symbol.`} />;
  return <Stock360Page key={symbol} symbol={symbol} />;
}
