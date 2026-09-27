/**
 * TanStack Query setup + the one hook every tab uses to read /api/v2.
 *
 * - Query keys always include as_of (time travel re-keys every query).
 * - as_of is read from the URL (?as_of=YYYY-MM-DD) automatically.
 * - Stale-while-revalidate: cached data stays on screen while refetching;
 *   EOD data changes at most once a day, so staleTime is generous.
 * - Retry: never on 4xx; 503 honours Retry-After; network errors back off.
 * - Abort: TanStack passes an AbortSignal; unmount/re-key cancels in flight.
 */
import { QueryClient, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiGet, isApiError, type PathParams } from './client';
import type { EndpointMap, Envelope } from './types';
import { useAsOf } from '../shell/urlState';

/** Endpoints that do not take as_of (user data, dictionary). */
const NO_AS_OF = new Set<keyof EndpointMap>(['metrics/dictionary', 'screener/presets', 'watchlist', 'notes/{sym}']);

const MAX_RETRIES = 3;

export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_RETRIES) return false;
  if (!isApiError(error)) return failureCount < 1;
  switch (error.kind) {
    case 'busy':
      return true;
    case 'network':
    case 'server':
      return failureCount < 2;
    default:
      return false; // not_found, client, parse, aborted
  }
}

export function retryDelay(failureCount: number, error: unknown): number {
  if (isApiError(error) && error.kind === 'busy' && error.retryAfterMs != null) {
    return Math.min(Math.max(error.retryAfterMs, 250), 60_000);
  }
  return Math.min(1000 * 2 ** failureCount, 15_000);
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5 * 60_000,
        gcTime: 30 * 60_000,
        retry: shouldRetry,
        retryDelay,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export type ApiQueryArgs<P extends keyof EndpointMap> = {
  params?: PathParams<P>;
  query?: Omit<EndpointMap[P]['query'], 'as_of'>;
};

export type ApiQueryOptions = {
  enabled?: boolean;
  staleTime?: number;
  /** Override the URL as_of: a date, null (= latest), or false (never send). */
  asOf?: string | null | false;
};

/** Stable query key: ['v2', endpoint, pathParams, {…query, as_of}]. */
export function apiQueryKey(endpoint: string, params: unknown, query: Record<string, unknown> | undefined, asOf: string | null) {
  return ['v2', endpoint, params ?? null, { ...(query ?? {}), as_of: asOf }] as const;
}

export function useApiQuery<P extends keyof EndpointMap>(
  endpoint: P,
  args: ApiQueryArgs<P> = {},
  options: ApiQueryOptions = {},
): UseQueryResult<Envelope<EndpointMap[P]['row'], EndpointMap[P]['meta']>> {
  const [urlAsOf] = useAsOf();
  const asOf = NO_AS_OF.has(endpoint) || options.asOf === false ? null : options.asOf === undefined ? urlAsOf : options.asOf;
  const query = { ...(args.query ?? {}), ...(asOf ? { as_of: asOf } : {}) } as EndpointMap[P]['query'];
  return useQuery({
    queryKey: apiQueryKey(endpoint, args.params, args.query as Record<string, unknown> | undefined, asOf),
    queryFn: ({ signal }) => apiGet(endpoint, { params: args.params, query }, { signal }),
    enabled: options.enabled ?? true,
    staleTime: options.staleTime,
  });
}
