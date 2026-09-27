/**
 * Shell-wide actions shared by every tab (new and legacy):
 * sidecar symbol, watchlist, navigation helpers, legacy drawers.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { apiGet, apiPut } from '../api/client';
import { readJSON, writeJSON } from '../lib/storage';
import { TABS, type TabId } from './tabs';
import { GLOBAL_PARAMS, isSymbol, useSidecarSymbol } from './urlState';

export interface ShellApi {
  /** Symbol in the Stock 360 sidecar (URL ?sym=). */
  symbol: string | null;
  /** Open/replace the sidecar symbol (null closes it). */
  openSymbol: (sym: string | null) => void;
  /** Navigate to the full Stock 360 page. */
  openStockPage: (sym: string) => void;
  /** Navigate to Charts with a symbol list (legacy "Tiles" / "Open in Charts"). */
  openCharts: (symbols?: string[]) => void;
  goTab: (id: TabId) => void;
  /** Symbol shown in the near-full-screen big chart (F), null when closed. */
  bigChart: string | null;
  openBigChart: (sym: string | null) => void;

  /**
   * Watchlist, persisted to /api/v2/watchlist (localStorage is only an
   * offline cache). `watchSync` says whether the server has the latest list.
   */
  watchlist: string[];
  watchSync: WatchSync;
  isWatched: (sym: string) => boolean;
  toggleWatch: (sym: string) => void;
  removeWatch: (sym: string) => void;
  clearWatch: () => void;

  /** Recently opened symbols, newest first (for Ctrl+K). */
  recent: string[];

  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
  breadthOpen: boolean;
  setBreadthOpen: (open: boolean) => void;
}

/** loading = first GET in flight · synced = server has it · local = server unreachable (cache only) · error = last save failed. */
export type WatchSync = 'loading' | 'synced' | 'local' | 'error';

const Ctx = createContext<ShellApi | null>(null);

const WATCH_KEY = 'mp.watchlist.v1';
const RECENT_KEY = 'mp.recent.v1';

export function ShellProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [symbol, setSymbol] = useSidecarSymbol();
  const [watchlist, setWatchlist] = useState<string[]>(() => readJSON<string[]>(WATCH_KEY, []).filter(isSymbol));
  const [watchSync, setWatchSync] = useState<WatchSync>('loading');
  const watchRef = useRef(watchlist);
  const serverOk = useRef(false);
  const saveSeq = useRef(0);
  const [recent, setRecent] = useState<string[]>(() => readJSON<string[]>(RECENT_KEY, []).filter(isSymbol));
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [breadthOpen, setBreadthOpen] = useState(false);
  const [bigChart, setBigChart] = useState<string | null>(null);
  const openBigChart = useCallback((sym: string | null) => {
    const s = sym ? sym.toUpperCase() : null;
    if (s && !isSymbol(s)) return;
    setBigChart(s);
  }, []);

  useEffect(() => writeJSON(WATCH_KEY, watchlist), [watchlist]);

  /** PUT the full list; latest call wins. */
  const saveWatch = useCallback((list: string[]) => {
    const seq = ++saveSeq.current;
    apiPut('watchlist', { symbols: list })
      .then((env) => {
        if (seq !== saveSeq.current) return;
        serverOk.current = true;
        setWatchSync('synced');
        const served = env.rows.map((r) => r.symbol).filter(isSymbol);
        watchRef.current = served;
        setWatchlist(served);
      })
      .catch(() => {
        if (seq === saveSeq.current) setWatchSync('error');
      });
  }, []);

  // Hydrate once from the server. Server wins; a local-only list (pre-v2) is migrated up.
  useEffect(() => {
    const ctrl = new AbortController();
    apiGet('watchlist', {}, { signal: ctrl.signal })
      .then((env) => {
        const served = env.rows.map((r) => r.symbol).filter(isSymbol);
        serverOk.current = true;
        if (served.length === 0 && watchRef.current.length > 0) {
          saveWatch(watchRef.current);
          return;
        }
        watchRef.current = served;
        setWatchlist(served);
        setWatchSync('synced');
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setWatchSync('local');
      });
    return () => ctrl.abort();
  }, [saveWatch]);

  const commitWatch = useCallback(
    (next: (cur: string[]) => string[]) => {
      const list = next(watchRef.current);
      watchRef.current = list;
      setWatchlist(list);
      if (serverOk.current) saveWatch(list);
    },
    [saveWatch],
  );
  useEffect(() => writeJSON(RECENT_KEY, recent), [recent]);

  const remember = useCallback((sym: string) => {
    setRecent((r) => [sym, ...r.filter((s) => s !== sym)].slice(0, 12));
  }, []);

  /** Current global params (as_of, sym) as a search string, optionally overriding sym. */
  const globalSearch = useCallback(
    (overrides: Record<string, string | null> = {}) => {
      const cur = new URLSearchParams(location.search);
      const next = new URLSearchParams();
      for (const k of GLOBAL_PARAMS) {
        const v = k in overrides ? overrides[k] : cur.get(k);
        if (v) next.set(k, v);
      }
      const s = next.toString();
      return s ? `?${s}` : '';
    },
    [location.search],
  );

  const openSymbol = useCallback(
    (sym: string | null) => {
      const s = sym ? sym.toUpperCase() : null;
      if (s && !isSymbol(s)) return;
      if (s) remember(s);
      setSymbol(s);
    },
    [remember, setSymbol],
  );

  const openStockPage = useCallback(
    (sym: string) => {
      const s = sym.toUpperCase();
      if (!isSymbol(s)) return;
      remember(s);
      navigate(`/stock/${encodeURIComponent(s)}${globalSearch({ sym: null })}`);
    },
    [navigate, globalSearch, remember],
  );

  const openCharts = useCallback(
    (symbols?: string[]) => {
      const list = (symbols ?? []).map((s) => s.toUpperCase()).filter(isSymbol);
      const search = new URLSearchParams(globalSearch());
      if (list.length) search.set('syms', list.join(','));
      const s = search.toString();
      navigate(`/charts${s ? `?${s}` : ''}`);
    },
    [navigate, globalSearch],
  );

  const goTab = useCallback(
    (id: TabId) => {
      const tab = TABS.find((t) => t.id === id);
      if (tab) navigate(`${tab.path}${globalSearch()}`);
    },
    [navigate, globalSearch],
  );

  const isWatched = useCallback((sym: string) => watchlist.includes(sym), [watchlist]);
  const toggleWatch = useCallback(
    (sym: string) => {
      const s = sym.toUpperCase();
      if (!isSymbol(s)) return;
      commitWatch((w) => (w.includes(s) ? w.filter((x) => x !== s) : [...w, s]));
    },
    [commitWatch],
  );
  const removeWatch = useCallback((sym: string) => commitWatch((w) => w.filter((x) => x !== sym)), [commitWatch]);
  const clearWatch = useCallback(() => commitWatch(() => []), [commitWatch]);

  const value = useMemo<ShellApi>(
    () => ({
      symbol,
      openSymbol,
      openStockPage,
      openCharts,
      goTab,
      bigChart,
      openBigChart,
      watchlist,
      watchSync,
      isWatched,
      toggleWatch,
      removeWatch,
      clearWatch,
      recent,
      paletteOpen,
      setPaletteOpen,
      breadthOpen,
      setBreadthOpen,
    }),
    [
      symbol,
      openSymbol,
      openStockPage,
      openCharts,
      goTab,
      bigChart,
      openBigChart,
      watchlist,
      watchSync,
      isWatched,
      toggleWatch,
      removeWatch,
      clearWatch,
      recent,
      paletteOpen,
      breadthOpen,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useShell(): ShellApi {
  const v = useContext(Ctx);
  if (!v) throw new Error('useShell must be used inside <ShellProvider>');
  return v;
}
