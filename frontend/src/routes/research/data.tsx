/**
 * Research data hook: useApiQuery, plus a dev-only fixture mode so the tab can
 * be built and reviewed before the evidence tables exist. In production
 * builds `import.meta.env.DEV` is false, the fixture branch is folded away and
 * the fixtures chunk is never emitted.
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { useApiQuery, type ApiQueryArgs, type ApiQueryOptions } from '../../api/query';
import type { EndpointMap, Envelope } from '../../api/types';
import { readJSON, writeJSON } from '../../lib/storage';
import { useAsOf } from '../../shell/urlState';

const STORAGE_KEY = 'mp.research.fixtures';

interface FixtureMode {
  /** True only in dev builds with the toggle on. */
  on: boolean;
  /** False in production: the toggle is not rendered. */
  available: boolean;
  set: (on: boolean) => void;
}

const FixtureContext = createContext<FixtureMode>({ on: false, available: false, set: () => undefined });

export function FixtureModeProvider({ children, initial }: { children: ReactNode; initial?: boolean }) {
  const available = import.meta.env.DEV;
  const [on, setOn] = useState<boolean>(() => available && (initial ?? readJSON<boolean>(STORAGE_KEY, false)));
  const set = useCallback(
    (v: boolean) => {
      if (!available) return;
      setOn(v);
      writeJSON(STORAGE_KEY, v);
    },
    [available],
  );
  const value = useMemo(() => ({ on: available && on, available, set }), [available, on, set]);
  return <FixtureContext.Provider value={value}>{children}</FixtureContext.Provider>;
}

export function useFixtureMode(): FixtureMode {
  return useContext(FixtureContext);
}

type Result<P extends keyof EndpointMap> = UseQueryResult<Envelope<EndpointMap[P]['row'], EndpointMap[P]['meta']>>;

const loadFixture = import.meta.env.DEV
  ? async (endpoint: string, args: { params?: unknown; query?: unknown }, asOf: string | null) => {
      const { fixtureFor } = await import('./fixtures');
      return fixtureFor({
        endpoint,
        params: args.params as Record<string, string> | undefined,
        query: args.query as Record<string, unknown> | undefined,
        asOf,
      });
    }
  : async () => {
      throw new Error('fixtures are dev-only');
    };

/** useApiQuery for Research endpoints, served from fixtures when the dev toggle is on. */
export function useResearchQuery<P extends keyof EndpointMap>(endpoint: P, args: ApiQueryArgs<P> = {}, options: ApiQueryOptions = {}): Result<P> {
  const fx = useFixtureMode();
  const [urlAsOf] = useAsOf();
  const enabled = options.enabled ?? true;
  const live = useApiQuery(endpoint, args, { ...options, enabled: enabled && !fx.on });
  const fixture = useQuery({
    queryKey: ['fixture', endpoint, args.params ?? null, args.query ?? null, urlAsOf],
    queryFn: () => loadFixture(endpoint, args, urlAsOf),
    enabled: enabled && fx.on,
    staleTime: Infinity,
  });
  return (fx.on ? fixture : live) as Result<P>;
}
