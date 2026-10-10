/**
 * Tab state that lives in the URL while the tab is active and survives tab
 * switches (the shell drops tab-specific params on switch; tabs stay mounted).
 *
 * - While the tab is active, known params in the URL win (deep links such as
 *   "Open in Charts" set them); missing params are re-written from state.
 * - While the tab is hidden the state is frozen, so hidden tabs never re-key
 *   their queries off another tab's URL.
 * - Default values are kept out of the URL; state persists in localStorage.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useSearchParams } from 'react-router';
import { readJSON, writeJSON } from './storage';

export type TabParams = Record<string, string>;

/**
 * Pure reconcile step. Returns the next state and the URL edits to apply
 * (value null = delete). URL values win; state fills what the URL lacks.
 */
export function reconcileTabParams(
  url: URLSearchParams,
  state: TabParams,
  defaults: TabParams,
): { state: TabParams; writes: Record<string, string | null> } {
  const next: TabParams = { ...state };
  const writes: Record<string, string | null> = {};
  for (const key of Object.keys(defaults)) {
    const u = url.get(key);
    if (u !== null && u !== '') {
      next[key] = u;
      if (u === defaults[key]) writes[key] = null; // keep defaults out of the URL
    } else if (next[key] !== undefined && next[key] !== defaults[key]) {
      writes[key] = next[key];
    }
  }
  return { state: next, writes };
}

function sameParams(a: TabParams, b: TabParams): boolean {
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  return ka.every((k) => a[k] === b[k]);
}

/** Tabs whose path changed: saved state under the old path is read once when the new key is empty. */
const LEGACY_TAB_PATHS: Record<string, string> = { '/setups': '/screener' };

function readStored<T>(key: string, tabPath: string, suffix: string): T {
  const cur = readJSON<T | null>(key, null);
  if (cur !== null) return cur;
  const old = LEGACY_TAB_PATHS[tabPath];
  return readJSON<T>(old ? `mp.tabstate${old}${suffix}` : key, {} as T);
}

export function useTabUrlState<D extends TabParams>(
  tabPath: string,
  defaults: D,
  /** Separate localStorage slot when one tab keeps several independent param sets (disjoint keys). */
  storageSuffix?: string,
): [D, (patch: Partial<Record<keyof D, string | null>>) => void, boolean] {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const active = location.pathname === tabPath || location.pathname.startsWith(`${tabPath}/`);
  const storageKey = `mp.tabstate${tabPath}${storageSuffix ? `:${storageSuffix}` : ''}`;
  const defaultsRef = useRef(defaults);
  const [state, setState] = useState<D>(() => {
    const stored = readStored<Partial<D>>(storageKey, tabPath, storageSuffix ? `:${storageSuffix}` : '');
    const base = { ...defaults } as D;
    for (const k of Object.keys(defaults) as (keyof D)[]) {
      const v = stored[k];
      if (typeof v === 'string' && v !== '') base[k] = v as D[keyof D];
    }
    return base;
  });

  useEffect(() => writeJSON(storageKey, state), [storageKey, state]);

  useEffect(() => {
    if (!active) return;
    const { state: next, writes } = reconcileTabParams(params, state, defaultsRef.current);
    if (!sameParams(next, state)) setState(next as D);
    if (Object.keys(writes).length) {
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(writes)) {
            if (v === null) p.delete(k);
            else p.set(k, v);
          }
          return p;
        },
        { replace: true },
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reconcile on URL / activation only
  }, [active, params]);

  const update = useCallback(
    (patch: Partial<Record<keyof D, string | null>>) => {
      setState((s) => {
        const n = { ...s };
        for (const [k, v] of Object.entries(patch)) {
          (n as TabParams)[k] = v === null || v === undefined || v === '' ? defaultsRef.current[k] : v;
        }
        return n;
      });
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v === null || v === undefined || v === '' || v === defaultsRef.current[k]) p.delete(k);
            else p.set(k, v);
          }
          return p;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  return [state, update, active];
}
