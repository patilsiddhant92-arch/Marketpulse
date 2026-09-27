/**
 * Metric dictionary client (spec 6.2). Fetched once per session from
 * GET /api/v2/metrics/dictionary; drives every tooltip and zone colour.
 * If the endpoint is missing, lookups return undefined and UI shows the
 * raw value with no zone colour — never an invented zone.
 */
import { useCallback, useMemo } from 'react';
import { useApiQuery } from '../api/query';
import type { MetricDef, MetricZone, Tone, ZoneTone } from '../api/types';

export function useMetricsDictionary() {
  const q = useApiQuery('metrics/dictionary', {}, { staleTime: Infinity });
  const byKey = useMemo(() => {
    const m = new Map<string, MetricDef>();
    for (const def of q.data?.rows ?? []) m.set(def.key, def);
    return m;
  }, [q.data]);
  return { byKey, isLoading: q.isLoading, error: q.error };
}

export interface ZoneBounds {
  min: number | null;
  max: number | null;
  /** ">" excludes the bound; ">=" and "a-b" include it. */
  minInclusive: boolean;
  maxInclusive: boolean;
}

/**
 * Numeric bounds of a zone range such as "> 60", "40-60", "<= 20" (a trailing
 * % or x is ignored). null bound = open. undefined = not numeric (e.g. "rising").
 */
export function zoneBounds(zone: Pick<MetricZone, 'range'>): ZoneBounds | undefined {
  const r: unknown = zone.range;
  if (typeof r !== 'string') return undefined;
  const s = r
    .replace(/\s+/g, '')
    .replace(/[\u2013\u2014]/g, '-')
    .replace(/[%x]$/i, '')
    .replace(/%/g, '');
  const num = String.raw`(-?\d+(?:\.\d+)?)`;
  let m = new RegExp(`^(>=|>|\u2265)${num}$`).exec(s);
  if (m) return { min: Number(m[2]), max: null, minInclusive: m[1] !== '>', maxInclusive: true };
  m = new RegExp(`^(<=|<|\u2264)${num}$`).exec(s);
  if (m) return { min: null, max: Number(m[2]), minInclusive: true, maxInclusive: m[1] !== '<' };
  m = new RegExp(`^${num}(?:-|to)${num}$`).exec(s);
  if (m) return { min: Number(m[1]), max: Number(m[2]), minInclusive: true, maxInclusive: true };
  return undefined;
}

/** First zone (in dictionary order) whose bounds contain value. */
export function zoneFor(def: MetricDef | undefined, value: number | null | undefined): MetricZone | undefined {
  if (!def || value === null || value === undefined || !Number.isFinite(value)) return undefined;
  return (def.zones ?? []).find((z) => {
    const b = zoneBounds(z);
    if (!b) return false;
    const aboveMin = b.min === null || (b.minInclusive ? value >= b.min : value > b.min);
    const belowMax = b.max === null || (b.maxInclusive ? value <= b.max : value < b.max);
    return aboveMin && belowMax;
  });
}

const SERVED_TONE: Record<ZoneTone, Tone> = { good: 'positive', neutral: 'neutral', caution: 'warn', bad: 'negative' };
const POSITIVE = /healthy|strong|leading|favourable|constructive|good|improving|accumulat|bull/i;
const NEGATIVE = /weak|danger|lagging|poor|bear|distribut|selling|fear/i;
const WARN = /stretched|caution|extended|watch|mixed|soft/i;

/** Tone from the served zone.tone (good/neutral/caution/bad), else inferred from its label. */
export function toneForZone(zone: MetricZone | undefined): Tone | undefined {
  if (!zone) return undefined;
  const t = zone.tone?.toLowerCase();
  if (t && t in SERVED_TONE) return SERVED_TONE[t as ZoneTone];
  if (t === 'positive' || t === 'negative' || t === 'warn' || t === 'info') return t;
  if (WARN.test(zone.label)) return 'warn';
  if (NEGATIVE.test(zone.label)) return 'negative';
  if (POSITIVE.test(zone.label)) return 'positive';
  return 'neutral';
}

/** Dictionary entry + zone helpers for one metric key. */
export function useMetric(key: string | undefined) {
  const { byKey, isLoading } = useMetricsDictionary();
  const def = key ? byKey.get(key) : undefined;
  const zone = useCallback((value: number | null | undefined) => zoneFor(def, value), [def]);
  const tone = useCallback((value: number | null | undefined) => toneForZone(zoneFor(def, value)), [def]);
  return { def, zoneFor: zone, toneFor: tone, isLoading };
}

/** Tailwind text class per tone (tokens only). */
export const TONE_TEXT: Record<Tone, string> = {
  positive: 'text-up',
  negative: 'text-down',
  warn: 'text-warn',
  info: 'text-info',
  neutral: 'text-fg',
};
