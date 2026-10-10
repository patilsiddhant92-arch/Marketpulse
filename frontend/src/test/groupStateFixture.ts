/** Fixture rows for GET /api/v2/pulse/group-state (the one Pulse-owned group state) used by the tab tests. */
import type { GroupStateRow } from '../context/groupState';

export const sharedRow = (group_name: string, state: GroupStateRow['state'], reason: string, level: GroupStateRow['level'] = 'industry'): GroupStateRow => ({
  id: `${level}:${group_name}`,
  level,
  group_name,
  state,
  reason,
  members: 10,
  pct_above_50ema: 50,
  vs_median_21d: 0,
  vs_median_63d: 0,
  ret_5d_pct: 0,
  share_5d_pct: 1,
  share_20d_pct: 1,
  ew_above_ema50: true,
  sessions_in_state: 3,
  state_since: '2026-08-11',
});

/** A /pulse/group-state envelope. */
export function groupStateEnvelope(rows: GroupStateRow[], asOf = '2026-08-13') {
  return {
    as_of: asOf,
    freshness: { status: 'fresh', latest_session: asOf, expected_session: asOf, sessions_behind: 0, history_mode: false },
    total: rows.length,
    returned: rows.length,
    rows,
    meta: { status: 'ok', reason: null, offset: 0, limit: 5000, sources: ['group_daily'], notes: [], metric_keys: [], context: { owner: 'pulse' } },
  };
}
