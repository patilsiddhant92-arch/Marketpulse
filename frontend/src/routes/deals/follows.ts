/**
 * Followed deal houses (08-tab-deals.md §5.3-4), stored server-side in the user DB:
 *   GET /api/v2/deals/follows · POST {house, name} · DELETE ?house=
 * The Telegram digest reads the same table, so a follow made here drives its "Followed houses"
 * section. Follows that older builds kept in localStorage are moved to the server once, then cleared.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { API_BASE, ApiError, toEnvelope } from '../../api/client';
import type { Envelope } from '../../api/types';
import { clearLegacyFollowed, readLegacyFollowed } from './model';

export interface FollowedHouse {
  house: string;
  name: string;
  added_at: string | null;
}

export const FOLLOWS_KEY = ['v2', 'deals/follows'] as const;
const PATH = 'deals/follows';

async function call(method: 'GET' | 'POST' | 'DELETE', body?: { house: string; name?: string }, house?: string): Promise<FollowedHouse[]> {
  const qs = method === 'DELETE' && house ? `?house=${encodeURIComponent(house)}` : '';
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/${PATH}${qs}`, {
      method,
      headers: body ? { Accept: 'application/json', 'Content-Type': 'application/json' } : { Accept: 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError({ kind: 'network', status: 0, path: PATH, message: 'API unreachable' });
  }
  const text = await res.text().catch(() => '');
  let json: unknown = undefined;
  try {
    json = text ? JSON.parse(text) : undefined;
  } catch {
    json = text;
  }
  if (!res.ok) {
    const detail = typeof json === 'object' && json !== null && 'detail' in json ? String((json as { detail: unknown }).detail) : res.statusText;
    throw new ApiError({ kind: res.status < 500 ? 'client' : 'server', status: res.status, path: PATH, message: detail || `HTTP ${res.status}` });
  }
  return (toEnvelope<FollowedHouse>(json, PATH, res.status) as Envelope<FollowedHouse>).rows;
}

export const fetchFollows = () => call('GET');
export const addFollow = (house: string, name?: string) => call('POST', name ? { house, name } : { house });
export const removeFollow = (house: string) => call('DELETE', undefined, house);

export interface FollowsState {
  /** Followed house keys (deal_desk.house_key, as the Deals rows carry them). */
  followed: string[];
  isFollowed: (house: string) => boolean;
  toggle: (house: string, name?: string) => void;
  loading: boolean;
  error: unknown;
}

/** Module-wide guard: several components mount the hook; only one moves the legacy follows. */
let migrating = false;

export function useFollowedHouses(): FollowsState {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: FOLLOWS_KEY, queryFn: fetchFollows, staleTime: 60_000, retry: 1 });
  const migrated = useRef(false);

  // One-time move of browser-only follows to the server.
  useEffect(() => {
    if (migrated.current || migrating || !q.data) return;
    migrated.current = true;
    const legacy = readLegacyFollowed().filter((h) => !q.data.some((f) => f.house === h));
    if (!legacy.length) {
      clearLegacyFollowed();
      return;
    }
    migrating = true;
    void (async () => {
      let rows = q.data;
      try {
        for (const h of legacy) rows = await addFollow(h);
        clearLegacyFollowed();
        qc.setQueryData(FOLLOWS_KEY, rows);
      } catch {
        migrated.current = false; // try again on the next load
      } finally {
        migrating = false;
      }
    })();
  }, [q.data, qc]);

  const m = useMutation({
    mutationFn: ({ house, name, follow }: { house: string; name?: string; follow: boolean }) => (follow ? addFollow(house, name) : removeFollow(house)),
    onMutate: async ({ house, name, follow }) => {
      await qc.cancelQueries({ queryKey: FOLLOWS_KEY });
      const prev = qc.getQueryData<FollowedHouse[]>(FOLLOWS_KEY);
      const base = prev ?? [];
      qc.setQueryData<FollowedHouse[]>(
        FOLLOWS_KEY,
        follow ? [...base.filter((f) => f.house !== house), { house, name: name ?? house, added_at: null }] : base.filter((f) => f.house !== house),
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(FOLLOWS_KEY, ctx.prev);
    },
    onSuccess: (rows) => qc.setQueryData(FOLLOWS_KEY, rows),
  });

  const followed = useMemo(() => (q.data ?? []).map((f) => f.house), [q.data]);
  const isFollowed = useCallback((house: string) => followed.includes(house), [followed]);
  const { mutate } = m;
  const toggle = useCallback(
    (house: string, name?: string) => mutate({ house, name, follow: !followed.includes(house) }),
    [mutate, followed],
  );
  return useMemo(
    () => ({ followed, isFollowed, toggle, loading: q.isLoading, error: q.error ?? m.error }),
    [followed, isFollowed, toggle, q.isLoading, q.error, m.error],
  );
}
