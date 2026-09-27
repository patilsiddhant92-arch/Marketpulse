import { describe, expect, it, vi } from 'vitest';
import { ApiError, apiGet, apiPath, buildQuery, normalizeFreshness, parseRetryAfter } from './client';
import { apiQueryKey, retryDelay, shouldRetry } from './query';

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' }, ...init });
}

describe('paths and queries', () => {
  it('fills and encodes path params', () => {
    expect(apiPath('stock/{sym}/bars', { sym: 'M&M' })).toBe('stock/M%26M/bars');
    expect(() => apiPath('stock/{sym}', { sym: '' })).toThrow(/Missing path param/);
  });
  it('drops empty query values and sorts keys', () => {
    expect(buildQuery({ tf: 'W', as_of: '2026-09-25', x: null, y: undefined, z: '' })).toBe('?as_of=2026-09-25&tf=W');
    expect(buildQuery({})).toBe('');
  });
  it('query keys always carry as_of', () => {
    expect(apiQueryKey('market/regime', undefined, undefined, null)).toEqual(['v2', 'market/regime', null, { as_of: null }]);
    expect(apiQueryKey('stock/{sym}', { sym: 'HAL' }, { tf: 'D' }, '2026-01-02')).toEqual([
      'v2',
      'stock/{sym}',
      { sym: 'HAL' },
      { tf: 'D', as_of: '2026-01-02' },
    ]);
  });
});

describe('apiGet', () => {
  it('requests relative /api/v2 and returns the envelope', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ as_of: '2026-09-25', freshness: { status: 'fresh' }, total: 10, returned: 1, rows: [{ key: 'rs' }], meta: {} }),
    );
    const env = await apiGet('metrics/dictionary', {}, { fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(fetchImpl).toHaveBeenCalledWith('/api/v2/metrics/dictionary', expect.objectContaining({ method: 'GET' }));
    expect(env.total).toBe(10);
    expect(env.returned).toBe(1);
  });

  it('fills honest defaults for missing envelope keys (total stays NULL)', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ rows: [1, 2] }));
    const env = await apiGet('market/health', {}, { fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(env.total).toBeNull();
    expect(env.returned).toBe(2);
    expect(env.meta).toEqual({});
  });

  it('maps 503 + Retry-After to a busy error', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ detail: 'DB locked' }, { status: 503, headers: { 'Retry-After': '7' } }));
    const err = await apiGet('market/regime', {}, { fetchImpl: fetchImpl as unknown as typeof fetch }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.kind).toBe('busy');
    expect(err.retryAfterMs).toBe(7000);
    expect(err.message).toBe('DB locked');
  });

  it('maps 404 to not_found, proxy 502 and fetch failure to network', async () => {
    const e404 = await apiGet(
      'market/regime',
      {},
      { fetchImpl: (async () => new Response('', { status: 404 })) as unknown as typeof fetch },
    ).catch((e) => e);
    expect(e404.kind).toBe('not_found');
    const e502 = await apiGet(
      'market/regime',
      {},
      { fetchImpl: (async () => new Response('', { status: 502 })) as unknown as typeof fetch },
    ).catch((e) => e);
    expect(e502.kind).toBe('network');
    const eNet = await apiGet(
      'market/regime',
      {},
      {
        fetchImpl: (async () => {
          throw new TypeError('Failed to fetch');
        }) as unknown as typeof fetch,
      },
    ).catch((e) => e);
    expect(eNet.kind).toBe('network');
  });

  it('rejects non-envelope bodies as parse errors', async () => {
    const err = await apiGet('market/regime', {}, { fetchImpl: (async () => jsonResponse({ hello: 1 })) as unknown as typeof fetch }).catch(
      (e) => e,
    );
    expect(err.kind).toBe('parse');
  });

  it('reports aborts distinctly', async () => {
    const ctrl = new AbortController();
    const fetchImpl = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return jsonResponse({ rows: [] });
    });
    ctrl.abort();
    const err = await apiGet('market/regime', {}, { signal: ctrl.signal, fetchImpl: fetchImpl as unknown as typeof fetch }).catch((e) => e);
    expect(err.kind).toBe('aborted');
  });
});

describe('retry policy', () => {
  const busy = new ApiError({ kind: 'busy', status: 503, path: 'x', message: '', retryAfterMs: 4000 });
  const notFound = new ApiError({ kind: 'not_found', status: 404, path: 'x', message: '' });
  const network = new ApiError({ kind: 'network', status: 0, path: 'x', message: '' });
  it('never retries 4xx, retries 503 and network with limits', () => {
    expect(shouldRetry(0, notFound)).toBe(false);
    expect(shouldRetry(0, busy)).toBe(true);
    expect(shouldRetry(2, busy)).toBe(true);
    expect(shouldRetry(3, busy)).toBe(false);
    expect(shouldRetry(1, network)).toBe(true);
    expect(shouldRetry(2, network)).toBe(false);
  });
  it('honours Retry-After for 503', () => {
    expect(retryDelay(1, busy)).toBe(4000);
    expect(retryDelay(1, network)).toBe(2000);
  });
  it('parses Retry-After seconds and HTTP dates', () => {
    expect(parseRetryAfter('3')).toBe(3000);
    expect(parseRetryAfter(null)).toBeNull();
    const now = Date.parse('2026-09-27T10:00:00Z');
    expect(parseRetryAfter('Sun, 27 Sep 2026 10:00:05 GMT', now)).toBe(5000);
    expect(parseRetryAfter('garbage')).toBeNull();
  });
});

describe('normalizeFreshness', () => {
  it('accepts object, string or null', () => {
    expect(normalizeFreshness(null)).toEqual({ status: 'unknown' });
    expect(normalizeFreshness('stale')).toEqual({ status: 'stale' });
    expect(normalizeFreshness({ status: 'fresh', latest_session: '2026-09-25', history_mode: false })).toEqual({
      status: 'fresh',
      latest_session: '2026-09-25',
      history_mode: false,
    });
  });
});
