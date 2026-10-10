/**
 * Chart preferences shared by every chart view in this browser (Stock 360
 * sidecar / page, big chart, Charts tiles): Darvas boxes, setup levels, RS
 * benchmark, and the global chart settings of the Charts tab (price style,
 * EMAs, event candles, volume / RSI / RS panes). Persisted to localStorage (never throws); all views stay in sync.
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
  // ---- Global chart settings (HarkPro/09-tab-charts.md §4). Added fields; old keys unchanged.
  /** Price style: candles, close line, or volume candles (width ∝ volume vs its 20-bar average). */
  style: 'candles' | 'line' | 'volume';
  /** EMA periods shown (colours fixed app-wide). Default 10 / 20 / 200. */
  emas: number[];
  /** Event-coloured candles (§5) on/off, and each event group on/off. */
  events: boolean;
  eventGroups: Record<string, boolean>;
  /** Volume pane (up/down coloured) and its 20-bar average line. */
  volPane: boolean;
  volAvg: boolean;
  /** RSI 14 pane, regular divergence lines, hidden divergences (off by default). */
  rsi: boolean;
  rsiDiv: boolean;
  rsiHidden: boolean;
  /** RS line pane (vs the RS benchmark). Off by default. */
  rsPane: boolean;
}

const KEY = 'mp.chartprefs.v1';
export const EMA_CHOICES = [10, 20, 50, 200] as const;
export const CHART_PREF_DEFAULTS: ChartPrefs = {
  darvas: true,
  levels: true,
  bm: 'midsml400',
  bigTf: 'D',
  bigLog: false,
  style: 'candles',
  emas: [10, 20, 200],
  events: true,
  eventGroups: {},
  volPane: true,
  volAvg: true,
  rsi: true,
  rsiDiv: true,
  rsiHidden: false,
  rsPane: false,
};
const DEFAULTS = CHART_PREF_DEFAULTS;
const bool = (v: unknown, d: boolean) => (typeof v === 'boolean' ? v : d);

function load(): ChartPrefs {
  const v = readJSON<Partial<ChartPrefs>>(KEY, {});
  return {
    darvas: typeof v.darvas === 'boolean' ? v.darvas : DEFAULTS.darvas,
    levels: typeof v.levels === 'boolean' ? v.levels : DEFAULTS.levels,
    bm: v.bm === 'nifty50' ? 'nifty50' : 'midsml400',
    bigTf: v.bigTf === 'W' || v.bigTf === 'M' ? v.bigTf : 'D',
    bigLog: typeof v.bigLog === 'boolean' ? v.bigLog : DEFAULTS.bigLog,
    style: v.style === 'line' || v.style === 'volume' ? v.style : 'candles',
    emas: Array.isArray(v.emas)
      ? EMA_CHOICES.filter((p) => (v.emas as unknown[]).includes(p))
      : [...DEFAULTS.emas],
    events: bool(v.events, DEFAULTS.events),
    eventGroups:
      v.eventGroups && typeof v.eventGroups === 'object'
        ? Object.fromEntries(Object.entries(v.eventGroups).filter(([, x]) => typeof x === 'boolean'))
        : {},
    volPane: bool(v.volPane, DEFAULTS.volPane),
    volAvg: bool(v.volAvg, DEFAULTS.volAvg),
    rsi: bool(v.rsi, DEFAULTS.rsi),
    rsiDiv: bool(v.rsiDiv, DEFAULTS.rsiDiv),
    rsiHidden: bool(v.rsiHidden, DEFAULTS.rsiHidden),
    rsPane: bool(v.rsPane, DEFAULTS.rsPane),
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
