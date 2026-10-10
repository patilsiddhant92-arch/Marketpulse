/**
 * Chart v2 global settings (HarkPro/12-sprint2-plan.md "Chart v2"): Clean / Info mode, Events /
 * Normal candle colours and the timeframe. Stored in localStorage and shared by every chart in the
 * app (the Charts tab and every drawer that shows a chart). Price style, EMAs, RSI and the event
 * groups stay in lib/chartPrefs (the round-1 global settings), so old views keep working.
 */
import { useSyncExternalStore } from 'react';
import { readJSON, writeJSON } from '../lib/storage';

export type ChartMode = 'clean' | 'info';
export type CandleColours = 'events' | 'normal';
export type ChartTf = 'D' | 'W' | 'M';

export interface ChartV2Settings {
  mode: ChartMode;
  colours: CandleColours;
  tf: ChartTf;
}

const KEY = 'mp.chartv2.v1';
export const CHART_V2_DEFAULTS: ChartV2Settings = { mode: 'clean', colours: 'events', tf: 'D' };

export function parseSettings(v: unknown): ChartV2Settings {
  const o = (v && typeof v === 'object' ? v : {}) as Partial<ChartV2Settings>;
  return {
    mode: o.mode === 'info' ? 'info' : 'clean',
    colours: o.colours === 'normal' ? 'normal' : 'events',
    tf: o.tf === 'W' || o.tf === 'M' ? o.tf : 'D',
  };
}

let current: ChartV2Settings | null = null;
const subs = new Set<() => void>();
const get = () => (current ??= parseSettings(readJSON<unknown>(KEY, {})));

export function setChartSettings(patch: Partial<ChartV2Settings>): void {
  current = { ...get(), ...patch };
  writeJSON(KEY, current);
  subs.forEach((f) => f());
}

export function useChartSettings(): [ChartV2Settings, (patch: Partial<ChartV2Settings>) => void] {
  const s = useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    get,
    get,
  );
  return [s, setChartSettings];
}

/** Test hook. */
export function resetChartSettingsCache(): void {
  current = null;
}
