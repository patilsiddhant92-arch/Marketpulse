/**
 * Data as-of + freshness for the top bar, from GET /api/v2/health
 * (HealthResponse; the server answers 503 with the same body when data is
 * stale/degraded). While v2 is not deployed (404) it falls back to the legacy
 * /api/health so the chip is never blank during the migration.
 */
import { useQuery } from '@tanstack/react-query';
import type { FreshnessStatus, HealthCheck, HealthResponse } from '../api/types';

export interface FreshnessInfo {
  /** Latest session in the DB. */
  latestSession: string | null;
  expectedSession: string | null;
  status: FreshnessStatus;
  sessionsBehind: number | null;
  detail: string | null;
  checks: HealthCheck[];
  version: string | null;
  source: 'v2' | 'legacy' | 'none';
  /** The API server itself is unreachable. */
  apiDown: boolean;
  isLoading: boolean;
  refetch: () => void;
}

interface LegacyHealth {
  actionable?: boolean;
  database_date?: string | null;
  expected_session?: string | null;
  detail?: string | null;
}

type HealthResult = { kind: 'v2'; body: HealthResponse } | { kind: 'legacy'; body: LegacyHealth } | { kind: 'down' } | { kind: 'none' };

/** The Vite dev proxy answers 502/504 when FastAPI is not running. */
const isDownStatus = (s: number) => s === 502 || s === 504;

async function readJson(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return undefined;
  }
}

/** Exported for tests. */
export async function fetchHealth(signal?: AbortSignal, fetchImpl: typeof fetch = fetch): Promise<HealthResult> {
  try {
    const res = await fetchImpl('/api/v2/health', { signal, headers: { Accept: 'application/json' } });
    if (res.ok || res.status === 503) {
      const body = (await readJson(res)) as HealthResponse | undefined;
      if (body && typeof body === 'object' && 'freshness' in body) return { kind: 'v2', body };
      if (res.status === 503) return { kind: 'none' }; // busy (DB lock), not down
    } else if (isDownStatus(res.status)) {
      return { kind: 'down' };
    }
    // 404 (v2 not deployed) or an unexpected body: try the legacy endpoint.
    const legacy = await fetchImpl('/api/health', { signal, headers: { Accept: 'application/json' } });
    if (isDownStatus(legacy.status)) return { kind: 'down' };
    if (!legacy.ok) return { kind: 'none' };
    const body = (await readJson(legacy)) as LegacyHealth | undefined;
    return body ? { kind: 'legacy', body } : { kind: 'none' };
  } catch (e) {
    if ((e as { name?: string }).name === 'AbortError') throw e;
    return { kind: 'down' };
  }
}

export function useFreshness(): FreshnessInfo {
  const q = useQuery({
    queryKey: ['v2', 'health'],
    queryFn: ({ signal }) => fetchHealth(signal),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    retry: false,
  });
  const refetch = () => void q.refetch();
  const base = { refetch, isLoading: q.isLoading, checks: [] as HealthCheck[], version: null, expectedSession: null };
  const r = q.data;

  if (r?.kind === 'v2') {
    const f = r.body.freshness;
    return {
      ...base,
      latestSession: f.latest_session ?? null,
      expectedSession: f.expected_session ?? null,
      status: f.status,
      sessionsBehind: f.sessions_behind ?? null,
      detail: f.reason ?? null,
      checks: r.body.checks,
      version: `${r.body.version} (${r.body.build})`,
      source: 'v2',
      apiDown: false,
    };
  }
  if (r?.kind === 'legacy') {
    const h = r.body;
    const stale = !!h.database_date && !!h.expected_session && h.database_date < h.expected_session;
    const status: FreshnessStatus = h.actionable === false ? 'degraded' : stale ? 'stale' : h.database_date ? 'fresh' : 'unknown';
    return {
      ...base,
      latestSession: h.database_date ?? null,
      expectedSession: h.expected_session ?? null,
      status,
      sessionsBehind: null,
      detail: h.detail ?? null,
      source: 'legacy',
      apiDown: false,
    };
  }
  return {
    ...base,
    latestSession: null,
    status: 'unknown',
    sessionsBehind: null,
    detail: null,
    source: 'none',
    apiDown: r?.kind === 'down',
  };
}
