/** Data for one Stock 360 view (sidecar or page). All queries honour ?as_of. */
import { useApiQuery } from '../api/query';

export const FULL_HISTORY = 5000;

export function useStock360(symbol: string, enabled = true) {
  const params = { sym: symbol };
  const header = useApiQuery('stock/{sym}', { params }, { enabled });
  const bars = useApiQuery('stock/{sym}/bars', { params, query: { tf: 'D', limit: FULL_HISTORY } }, { enabled });
  const rs = useApiQuery('stock/{sym}/rs', { params, query: { limit: FULL_HISTORY } }, { enabled });
  const events = useApiQuery('stock/{sym}/events', { params, query: { days_ahead: 14, limit: 500 } }, { enabled });
  const deals = useApiQuery('stock/{sym}/deals', { params, query: { limit: 500 } }, { enabled });
  return { header, bars, rs, events, deals };
}

export type Stock360Data = ReturnType<typeof useStock360>;
