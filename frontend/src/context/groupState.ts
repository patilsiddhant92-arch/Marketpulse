/**
 * The one group state (Favour / Neutral / Caution + reason). Pulse owns it: GET /api/v2/pulse/group-state
 * (App/services/group_state.py). Pulse, Sector Intel and Setups all read it through this hook, so a group shows
 * the same state on every tab for the same as_of. Pure helpers here; the chip is ui/GroupState.tsx.
 */
import { useMemo } from 'react';
import { useApiQuery } from '../api/query';
import type { EndpointMap } from '../api/types';

export type GroupStateRow = EndpointMap['pulse/group-state']['row'];
export type GroupStateLevel = GroupStateRow['level'];
export type GroupStateMap = ReadonlyMap<string, GroupStateRow>;

const EMPTY: GroupStateMap = new Map();

/** Rows -> map keyed by group name. */
export function groupStateMap(rows: readonly GroupStateRow[] | undefined): GroupStateMap {
  if (!rows?.length) return EMPTY;
  const m = new Map<string, GroupStateRow>();
  for (const r of rows) m.set(r.group_name, r);
  return m;
}

/**
 * Overlay the shared state on rows that carry their own copy. Rows whose group the shared source knows get its
 * state + reason; the rest are returned unchanged. Returns the same array when nothing changed (memo friendly).
 */
export function applyGroupState<T>(
  rows: readonly T[],
  map: GroupStateMap,
  nameOf: (row: T) => string | null | undefined,
  write: (row: T, s: GroupStateRow) => T,
): T[] {
  if (!map.size) return rows as T[];
  let changed = false;
  const out = rows.map((r) => {
    const n = nameOf(r);
    const s = n ? map.get(n) : undefined;
    if (!s) return r;
    changed = true;
    return write(r, s);
  });
  return changed ? out : (rows as T[]);
}

/** Shared group state for one level at the URL as_of. Pass null to skip (e.g. the Index board). */
export function useGroupState(level: GroupStateLevel | null): { map: GroupStateMap; loading: boolean; asOf: string | null } {
  const q = useApiQuery('pulse/group-state', { query: { level: level ?? 'industry', limit: 5000 } }, { enabled: level !== null, staleTime: 10 * 60_000 });
  const rows = q.data?.rows;
  const map = useMemo(() => groupStateMap(rows), [rows]);
  return { map: level === null ? EMPTY : map, loading: q.isLoading, asOf: q.data?.as_of ?? null };
}
