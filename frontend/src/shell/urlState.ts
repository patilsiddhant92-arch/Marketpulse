/**
 * URL-held state (spec 7.1: URL holds tab/symbol/preset/filters/group/as_of).
 *
 * Shell-level params that must survive tab switches live in GLOBAL_PARAMS.
 * Tab-specific params (preset, group, filters) use useUrlParam() and are
 * dropped when switching tabs.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';

export const GLOBAL_PARAMS = ['as_of', 'sym'] as const;

const ISO = /^\d{4}-\d{2}-\d{2}$/;
const SYMBOL = /^[A-Z0-9&\-_.]{1,20}$/;

export function isISODate(v: string | null | undefined): v is string {
  return !!v && ISO.test(v) && !Number.isNaN(Date.parse(v));
}

export function isSymbol(v: string | null | undefined): v is string {
  return !!v && SYMBOL.test(v);
}

/** Read/write one search param; setting null/'' removes it. Uses replace for filters. */
export function useUrlParam(name: string, opts: { push?: boolean } = {}): [string | null, (v: string | null) => void] {
  const [params, setParams] = useSearchParams();
  const value = params.get(name);
  const set = useCallback(
    (v: string | null) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (v === null || v === '') next.delete(name);
          else next.set(name, v);
          return next;
        },
        { replace: !opts.push },
      );
    },
    [name, opts.push, setParams],
  );
  return [value, set];
}

/** Time-travel date. null = latest session. Invalid values are ignored. */
export function useAsOf(): [string | null, (v: string | null) => void] {
  const [raw, set] = useUrlParam('as_of', { push: true });
  return [isISODate(raw) ? raw : null, set];
}

/** Symbol shown in the Stock 360 sidecar. */
export function useSidecarSymbol(): [string | null, (v: string | null) => void] {
  const [raw, set] = useUrlParam('sym');
  const setUpper = useCallback((v: string | null) => set(v ? v.toUpperCase() : null), [set]);
  return [isSymbol(raw) ? raw : null, setUpper];
}

/** Search string carrying only the global params — for tab links. */
export function useGlobalSearch(): string {
  const [params] = useSearchParams();
  return useMemo(() => {
    const keep = new URLSearchParams();
    for (const k of GLOBAL_PARAMS) {
      const v = params.get(k);
      if (v) keep.set(k, v);
    }
    const s = keep.toString();
    return s ? `?${s}` : '';
  }, [params]);
}
