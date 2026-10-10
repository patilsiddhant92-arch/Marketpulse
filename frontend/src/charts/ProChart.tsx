/**
 * The main chart of the Charts tab: Chart v2 (HarkPro/12-sprint2-plan.md) for one symbol, with the
 * list position, star, Stock 360 and TradingView buttons in its header. The tab keeps the URL
 * timeframe and the H / T tool keys; everything else is Chart v2's global settings.
 */
import { ExternalLink, Info, Star } from 'lucide-react';
import { useMemo } from 'react';
import { useChartPrefs } from '../lib/chartPrefs';
import { cn } from '../lib/cn';
import { tradingViewChartUrl } from '../lib/tradingview';
import { useShell } from '../shell/ShellContext';
import type { Timeframe } from '../ui/Chart';
import { ChartV2, V2_BARS } from './ChartV2';
import type { ExtraLevel } from './chartV2Model';
import type { DrawTool } from './drawings';
import type { ChartItem } from './sources';

export const PRO_BARS: Record<Timeframe, number> = V2_BARS;

export interface ProChartProps {
  symbol: string;
  item?: ChartItem;
  tf: Timeframe;
  onTimeframeChange: (tf: Timeframe) => void;
  tool: DrawTool;
  onToolDone: () => void;
  onToolChange?: (t: DrawTool) => void;
  onInfo: () => void;
  infoOpen: boolean;
  /** "3 / 40" position in the list. */
  position?: string;
  className?: string;
}

/** Setup trigger / stop of a list item as tagged lines (the "Setup trigger / stop" setting). */
export function itemLevels(item: ChartItem | undefined, on: boolean): ExtraLevel[] {
  if (!on || !item) return [];
  const out: ExtraLevel[] = [];
  if (item.trigger_price != null) out.push({ id: 'trigger', label: 'Trigger', price: item.trigger_price, tone: 'accent' });
  if (item.stop_price != null) out.push({ id: 'stop', label: 'Stop', price: item.stop_price, tone: 'down' });
  return out;
}

export function ProChart({ symbol, item, tf, onTimeframeChange, tool, onToolDone, onToolChange, onInfo, infoOpen, position, className }: ProChartProps) {
  const shell = useShell();
  const [prefs] = useChartPrefs();
  const watched = shell.isWatched(symbol);
  const levels = useMemo(() => itemLevels(item, prefs.levels), [item, prefs.levels]);
  const actions = (
    <span className="flex items-center gap-1 pt-1">
      {position && <span className="num mr-1 text-2xs text-fg-3">{position}</span>}
      <button
        type="button"
        aria-pressed={watched}
        onClick={() => shell.toggleWatch(symbol)}
        title="Star to the watchlist (S)"
        className={cn('rounded p-1', watched ? 'text-accent' : 'text-fg-3 hover:text-fg')}
      >
        <Star className={cn('h-3.5 w-3.5', watched && 'fill-accent')} />
      </button>
      <button
        type="button"
        aria-pressed={infoOpen}
        onClick={onInfo}
        title="Stock 360 side panel (I)"
        className={cn('rounded p-1', infoOpen ? 'text-accent' : 'text-fg-3 hover:text-fg')}
      >
        <Info className="h-3.5 w-3.5" />
      </button>
      <a href={tradingViewChartUrl(symbol)} target="_blank" rel="noopener noreferrer" title="Open in TradingView" className="rounded p-1 text-fg-3 hover:text-fg">
        <ExternalLink className="h-3.5 w-3.5" />
      </a>
    </span>
  );
  return (
    <div className={cn('flex min-h-0 min-w-0 flex-col overflow-y-auto p-1', className)} data-testid="pro-chart">
      <ChartV2
        symbol={symbol}
        tf={tf}
        onTfChange={onTimeframeChange}
        actions={actions}
        extraLevels={levels}
        tool={tool}
        onToolChange={(t) => (t === 'none' ? onToolDone() : onToolChange?.(t))}
        onSymbolClick={onInfo}
        className="min-h-[560px] flex-1"
      />
    </div>
  );
}
