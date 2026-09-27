/**
 * Chart preferences shared by every chart view in this browser (Stock 360
 * sidecar / page, big chart, Charts tiles): Darvas boxes, setup levels, RS
 * benchmark. Persisted to localStorage (never throws); all views stay in sync.
 */
import { useSyncExternalStore } from 'react';
import { readJSON, writeJSON } from './storage';

export interface ChartPrefs {
  /** Paint historical Darvas boxes (default ON). */
  darvas: boolean;
  /** Setup trigger / stop levels (default ON). */
  levels: boolean;
  bm: 'midsml400' | 'nifty50';
  /** Big chart timeframe and log scale. */
  bigTf: 'D' | 'W' | 'M';
  bigLog: boolean;
}

const KEY = 'mp.chartprefs.v1';
const DEFAULTS: ChartPrefs = { darvas: true, levels: true, bm: 'midsml400', bigTf: 'D', bigLog: false };

function load(): ChartPrefs {
  const v = readJSON<Partial<ChartPrefs>>(KEY, {});
  return {
    darvas: typeof v.darvas === 'boolean' ? v.darvas : DEFAULTS.darvas,
    levels: typeof v.levels === 'boolean' ? v.levels : DEFAULTS.levels,
    bm: v.bm === 'nifty50' ? 'nifty50' : 'midsml400',
    bigTf: v.bigTf === 'W' || v.bigTf === 'M' ? v.bigTf : 'D',
    bigLog: typeof v.bigLog === 'boolean' ? v.bigLog : DEFAULTS.bigLog,
  };
}

let current: ChartPrefs | null = null;
const subs = new Set<() => void>();

function get(): ChartPrefs {
  if (!current) current = load();
  return current;
}

export function setChartPrefs(patch: Partial<ChartPrefs>): void {
  current = { ...get(), ...patch };
  writeJSON(KEY, current);
  subs.forEach((f) => f());
}

function subscribe(f: () => void): () => void {
  subs.add(f);
  return () => subs.delete(f);
}

export function useChartPrefs(): [ChartPrefs, (patch: Partial<ChartPrefs>) => void] {
  const prefs = useSyncExternalStore(subscribe, get, get);
  return [prefs, setChartPrefs];
}

/** Test hook: forget the cached prefs (re-read storage next time). */
export function resetChartPrefsCache(): void {
  current = null;
}
