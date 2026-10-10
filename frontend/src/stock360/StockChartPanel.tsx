/**
 * Stock 360 chart (sidecar, full page and big chart): Chart v2 (charts/ChartV2.tsx), the one stock
 * chart of the app with the global chart settings. Setup trigger / stop levels ride on it as tagged
 * lines; the Big button opens the big chart.
 *
 * Sprint 2: the RS pane of the old chart is not part of Chart v2 yet (see the Strength block).
 */
import { Expand } from 'lucide-react';
import { useMemo } from 'react';
import type { QueueRow } from '../api/types';
import { ChartV2 } from '../charts/ChartV2';
import type { ExtraLevel } from '../charts/chartV2Model';
import { useChartPrefs } from '../lib/chartPrefs';
import { cn } from '../lib/cn';
import type { Timeframe } from '../ui/Chart';
import type { Stock360Data } from './useStock360';

export interface StockChartPanelProps {
  symbol: string;
  /** Kept for the callers; Chart v2 reads its own data (the query cache is shared). */
  data?: Stock360Data;
  setups: Record<string, QueueRow | null | undefined> | undefined;
  /** Fixed chart height; omit to fill the parent. */
  height?: number;
  initialBars?: number;
  className?: string;
  /** Controlled timeframe (big chart keys D/W/M); uncontrolled (global setting) when omitted. */
  timeframe?: Timeframe;
  onTimeframeChange?: (tf: Timeframe) => void;
  /** Show an "expand" button that opens the big chart. */
  onExpand?: () => void;
  /** Log price scale (big chart). */
  logScale?: boolean;
  paneHeights?: { volume?: number; rs?: number; rsi?: number };
}

const QUEUE_LABEL: Record<string, string> = { darvas_squeeze: 'Squeeze', darvas_10ema: '10 EMA', vcp: 'VCP' };

/** Trigger / stop of every live setup as tagged lines. */
export function setupLevels(setups: Record<string, QueueRow | null | undefined> | undefined, on: boolean): ExtraLevel[] {
  if (!on || !setups) return [];
  const out: ExtraLevel[] = [];
  for (const [q, row] of Object.entries(setups)) {
    if (!row) continue;
    const name = QUEUE_LABEL[q] ?? q;
    if (row.trigger_price != null) out.push({ id: `${q}-trigger`, label: `${name} trigger`, price: row.trigger_price, tone: 'accent' });
    if (row.stop_price != null) out.push({ id: `${q}-stop`, label: `${name} stop`, price: row.stop_price, tone: 'down' });
  }
  return out;
}

export function StockChartPanel({ symbol, setups, height, initialBars, className, timeframe, onTimeframeChange, onExpand }: StockChartPanelProps) {
  const [prefs] = useChartPrefs();
  const levels = useMemo(() => setupLevels(setups, prefs.levels), [setups, prefs.levels]);
  const actions = onExpand ? (
    <button
      type="button"
      onClick={onExpand}
      aria-label="Big chart"
      title="Big chart (F): near full screen, J/K through the current list, Esc closes"
      className="flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-2xs text-fg-2 hover:bg-surface-3 hover:text-fg"
    >
      <Expand className="h-3 w-3" aria-hidden /> Big
    </button>
  ) : null;
  return (
    <div className={cn('flex min-h-0 flex-col overflow-y-auto p-1', className)} style={height ? { height } : undefined}>
      <ChartV2
        symbol={symbol}
        tf={timeframe}
        onTfChange={onTimeframeChange}
        header={false}
        compact={!onTimeframeChange}
        actions={actions}
        extraLevels={levels}
        initialBars={initialBars}
        className="min-h-[300px] flex-1"
      />
    </div>
  );
}
