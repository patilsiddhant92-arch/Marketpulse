/**
 * API v2 client. Relative base (/api/v2) so it works same-origin in production
 * and through the Vite proxy in dev. Returns the typed envelope or throws
 * ApiError; never fabricates data.
 */
import type { Envelope, EnvelopeMeta, EndpointMap, Freshness, FreshnessStatus } from './types';

export const API_BASE = '/api/v2';

export type ApiErrorKind =
  | 'network' // server unreachable (fetch failed / proxy 502/504)
  | 'not_found' // 404 — endpoint not shipped yet or unknown id
  | 'busy' // 503 — DB lock / stale; carries retryAfterMs
  | 'client' // other 4xx
  | 'server' // other 5xx
  | 'parse' // response was not a v2 envelope
  | 'aborted';

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly retryAfterMs: number | null;
  readonly path: string;
  readonly body: unknown;

  constructor(opts: { kind: ApiErrorKind; status: number; path: string; message: string; retryAfterMs?: number | null; body?: unknown }) {
    super(opts.message);
    this.name = 'ApiError';
    this.kind = opts.kind;
    this.status = opts.status;
    this.path = opts.path;
    this.retryAfterMs = opts.retryAfterMs ?? null;
    this.body = opts.body;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** Parse Retry-After: delta-seconds or an HTTP date. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d+(\.\d+)?$/.test(trimmed)) return Math.round(Number(trimmed) * 1000);
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return null;
  return Math.max(0, at - now);
}

// ------------------------------------------------------------------ paths

type PathParamNames<P extends string> = P extends `${string}{${infer K}}${infer Rest}` ? K | PathParamNames<Rest> : never;

export type PathParams<P extends string> = [PathParamNames<P>] extends [never] ? undefined : Record<PathParamNames<P>, string>;

/** Fill `{name}` segments (URL-encoded). Throws if a param is missing. */
export function apiPath<P extends string>(template: P, params?: PathParams<P>): string {
  return template.replace(/\{(\w+)\}/g, (_, name: string) => {
    const v = (params as Record<string, string> | undefined)?.[name];
    if (v === undefined || v === '') throw new Error(`Missing path param "${name}" for ${template}`);
    return encodeURIComponent(v);
  });
}

export type QueryValue = string | number | boolean | null | undefined | readonly (string | number)[];

/** Build a query string, dropping null/undefined/'' values; arrays repeat the key. */
export function buildQuery(query?: Record<string, QueryValue>): string {
  if (!query) return '';
  const sp = new URLSearchParams();
  for (const key of Object.keys(query).sort()) {
    const v = query[key];
    if (v === null || v === undefined || v === '') continue;
    if (Array.isArray(v)) v.forEach((item) => sp.append(key, String(item)));
    else sp.append(key, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

// ------------------------------------------------------------------ envelope helpers

export type NormalizedFreshness = Partial<Omit<Freshness, 'status'>> & { status: FreshnessStatus };

/** Envelope freshness as an object with a status ('unknown' when absent). Tolerates a bare status string. */
export function normalizeFreshness(f: Freshness | FreshnessStatus | null | undefined): NormalizedFreshness {
  if (!f) return { status: 'unknown' };
  if (typeof f === 'string') return { status: f };
  return { ...f, status: f.status ?? 'unknown' };
}

function looksLikeEnvelope(x: unknown): x is Envelope<unknown> {
  return typeof x === 'object' && x !== null && Array.isArray((x as { rows?: unknown }).rows);
}

/** Coerce a JSON body into an Envelope, filling honest defaults for absent keys. */
export function toEnvelope<Row, Meta extends EnvelopeMeta = EnvelopeMeta>(
  body: unknown,
  path: string,
  status: number,
): Envelope<Row, Meta> {
  if (!looksLikeEnvelope(body)) {
    throw new ApiError({ kind: 'parse', status, path, message: `Response from ${path} is not a v2 envelope`, body });
  }
  const b = body as Partial<Envelope<Row, Meta>> & { rows: Row[] };
  return {
    as_of: b.as_of ?? null,
    freshness: b.freshness ?? null,
    total: typeof b.total === 'number' ? b.total : null,
    returned: typeof b.returned === 'number' ? b.returned : b.rows.length,
    rows: b.rows,
    meta: (b.meta ?? {}) as Meta,
  };
}

/** True when the server says it has nothing honest to show. */
export function isUnavailable(env: Envelope<unknown> | undefined | null): boolean {
  return !!env && env.meta?.status === 'unavailable';
}

// ------------------------------------------------------------------ requests

export interface RequestOptions {
  signal?: AbortSignal;
  /** Test seam; defaults to global fetch. */
  fetchImpl?: typeof fetch;
}

async function request<Row, Meta extends EnvelopeMeta>(
  method: 'GET' | 'PUT' | 'POST',
  path: string,
  query: Record<string, QueryValue> | undefined,
  body: unknown,
  opts: RequestOptions,
): Promise<Envelope<Row, Meta>> {
  const url = `${API_BASE}/${path}${buildQuery(query)}`;
  const doFetch = opts.fetchImpl ?? fetch;
  let res: Response;
  try {
    res = await doFetch(url, {
      method,
      signal: opts.signal,
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    if ((e as { name?: string })?.name === 'AbortError') {
      throw new ApiError({ kind: 'aborted', status: 0, path, message: 'Request aborted' });
    }
    throw new ApiError({ kind: 'network', status: 0, path, message: 'API unreachable' });
  }

  let json: unknown = undefined;
  const text = await res.text().catch(() => '');
  if (text) {
    try {
      json = JSON.parse(text);
    } catch {
      json = text;
    }
  }

  if (!res.ok) {
    const detail =
      typeof json === 'object' && json !== null && 'detail' in json ? String((json as { detail: unknown }).detail) : res.statusText;
    if (res.status === 503) {
      throw new ApiError({
        kind: 'busy',
        status: 503,
        path,
        message: detail || 'Service unavailable',
        retryAfterMs: parseRetryAfter(res.headers.get('Retry-After')),
        body: json,
      });
    }
    // The Vite dev proxy answers 502/504 when FastAPI is down.
    const kind: ApiErrorKind =
      res.status === 404 ? 'not_found' : res.status === 502 || res.status === 504 ? 'network' : res.status < 500 ? 'client' : 'server';
    throw new ApiError({ kind, status: res.status, path, message: detail || `HTTP ${res.status}`, body: json });
  }

  return toEnvelope<Row, Meta>(json, path, res.status);
}

type Row<P extends keyof EndpointMap> = EndpointMap[P]['row'];
type Meta<P extends keyof EndpointMap> = EndpointMap[P]['meta'];
type Query<P extends keyof EndpointMap> = EndpointMap[P]['query'];

/** Typed GET for a known endpoint. */
export function apiGet<P extends keyof EndpointMap>(
  endpoint: P,
  args: { params?: PathParams<P>; query?: Query<P> } = {},
  opts: RequestOptions = {},
): Promise<Envelope<Row<P>, Meta<P>>> {
  return request<Row<P>, Meta<P>>('GET', apiPath(endpoint, args.params), args.query as Record<string, QueryValue>, undefined, opts);
}

/** Typed PUT (watchlist, notes). */
export function apiPut<P extends keyof EndpointMap>(
  endpoint: P,
  body: unknown,
  args: { params?: PathParams<P> } = {},
  opts: RequestOptions = {},
): Promise<Envelope<Row<P>, Meta<P>>> {
  return request<Row<P>, Meta<P>>('PUT', apiPath(endpoint, args.params), undefined, body, opts);
}
