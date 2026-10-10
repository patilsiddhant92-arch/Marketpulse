/**
 * GET an /api/v2 envelope by plain path, for endpoints without a generated row schema (free-form rows, e.g.
 * /deals/flags, /deals/tab/*). Same error mapping as the typed client; never fabricates data.
 */
import { API_BASE, ApiError, buildQuery, toEnvelope, type QueryValue } from './client';
import type { Envelope, EnvelopeMeta } from './types';

export async function getRawEnvelope<Row, Meta extends EnvelopeMeta = EnvelopeMeta>(
  path: string,
  query: Record<string, QueryValue> = {},
  signal?: AbortSignal,
): Promise<Envelope<Row, Meta>> {
  const url = `${API_BASE}/${path.replace(/^\//, '')}${buildQuery(query)}`;
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: 'application/json' }, signal });
  } catch (e) {
    if ((e as { name?: string })?.name === 'AbortError') throw new ApiError({ kind: 'aborted', status: 0, path, message: 'Request aborted' });
    throw new ApiError({ kind: 'network', status: 0, path, message: 'API unreachable' });
  }
  const text = await res.text().catch(() => '');
  let json: unknown;
  try {
    json = text ? JSON.parse(text) : undefined;
  } catch {
    json = text;
  }
  if (!res.ok) {
    const detail = typeof json === 'object' && json && 'detail' in json ? String((json as { detail: unknown }).detail) : res.statusText;
    const kind = res.status === 503 ? 'busy' : res.status === 404 ? 'not_found' : res.status < 500 ? 'client' : 'server';
    throw new ApiError({ kind, status: res.status, path, message: detail || `HTTP ${res.status}`, body: json });
  }
  return toEnvelope<Row, Meta>(json, path, res.status);
}
