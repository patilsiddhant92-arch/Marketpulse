/**
 * One settings model for every chart (HarkPro/09-tab-charts.md §2, §4): global prefs + served
 * data -> the optional layers of ui/Chart (EMAs, price style, event candles, deal-price lines,
 * RSI + divergence lines, drawings). `buildChartLayers` is pure; `useChartLayers` adds the
 * queries (deal candles, events) and the stored prefs / drawings.
 */
import { useMemo } from 'react';
import { useApiQuery } from '../api/query';
import type { DarvasRow, StockEventRow } from '../api/types';
import { useChartPrefs, type ChartPrefs } from '../lib/chartPrefs';
import { rsi as rsiCalc, type OHLCBar } from '../lib/indicators';
import { tokenColor } from '../lib/tokens';
import type { ChartLevel, ChartMarker, ChartSegment, Timeframe } from '../ui/Chart';
import { rsiDivergences, type Divergence } from './divergence';
import { drawingLayers, useDrawings, type Drawing } from './drawings';
import {
  EVENT_COLORS,
  calendarEvents,
  dealEvent,
  paletteColor,
  priceEvents,
  resolveEvents,
  type BarEvents,
  type ChartEvent,
  type DealCandleRow,
} from './eventCandles';

/** Deal-price line length: 20 sessions, as bars of the timeframe. */
export const DEAL_LINE_BARS: Record<Timeframe, number> = { D: 20, W: 4, M: 1 };

export const DIV_COLORS = { bear: '#f2552c', bull: '#22c55e', hidden_bear: '#f2552c', hidden_bull: '#22c55e' } as const;

export interface LayerInput {
  bars: readonly OHLCBar[];
  tf: Timeframe;
  prefs: ChartPrefs;
  deals?: readonly DealCandleRow[] | null;
  events?: readonly StockEventRow[] | null;
  darvas?: readonly DarvasRow[] | null;
  drawings?: readonly Drawing[];
  /** Theme text colour for the white "volume" candle (resolved once by the hook). */
  fg?: string;
}

export interface ChartLayers {
  emaPeriods: number[];
  priceStyle: 'candles' | 'line' | 'volume';
  candleColors: { time: string; color: string }[];
  markers: ChartMarker[];
  segments: ChartSegment[];
  levels: ChartLevel[];
  rsi: { period: number } | null;
  volume: boolean;
  volumeAvg: boolean;
  divergences: Divergence[];
  byBar: Map<string, BarEvents>;
  barNote: (time: string) => string | null;
}

/** Deal-price lines for rows flagged show_line (3 latest B/S/P), 20 sessions from the deal bar. */
export function dealLines(rows: readonly DealCandleRow[], barTimes: readonly string[], tf: Timeframe): ChartSegment[] {
  const out: ChartSegment[] = [];
  if (!barTimes.length) return out;
  for (const r of rows) {
    const price = r.deal_price_adj ?? r.deal_price;
    if (!r.show_line || !r.trade_date || price == null || !r.letter) continue;
    const i = barTimes.findIndex((t) => t >= r.trade_date!);
    if (i < 0) continue;
    const j = Math.min(barTimes.length - 1, i + DEAL_LINE_BARS[tf]);
    if (j <= i) continue;
    const key = `deal_${r.letter}` as keyof typeof EVENT_COLORS;
    out.push({
      id: `deal-${r.trade_date}-${r.letter}`,
      pane: 'price',
      from: { time: barTimes[i], value: price },
      to: { time: barTimes[j], value: price },
      color: EVENT_COLORS[key] ?? EVENT_COLORS.deal_C,
      dashed: true,
      width: 1,
      axisLabel: `${r.letter}${r.status ? ` ${r.status}` : ''}`,
    });
  }
  return out;
}

export function divergenceSegments(divs: readonly Divergence[]): ChartSegment[] {
  return divs.flatMap((d) => {
    const color = DIV_COLORS[d.kind];
    const dashed = d.kind.startsWith('hidden');
    const id = `div-${d.kind}-${d.from.index}-${d.to.index}`;
    return [
      { id: `${id}-p`, pane: 'price' as const, from: { time: d.from.time, value: d.from.price }, to: { time: d.to.time, value: d.to.price }, color, dashed, width: 2 as const },
      { id: `${id}-r`, pane: 'rsi' as const, from: { time: d.from.time, value: d.from.rsi }, to: { time: d.to.time, value: d.to.rsi }, color, dashed, width: 2 as const },
    ];
  });
}

const BELOW: ReadonlySet<ChartEvent['key']> = new Set(['breakdown', 'gap_down', 'deal_S', 'ex_date']);

export function buildChartLayers(input: LayerInput): ChartLayers {
  const { bars, tf, prefs } = input;
  const times = bars.map((b) => b.time);
  const fg = input.fg ?? '#e9edf4';

  // ---- event candles
  let byBar = new Map<string, BarEvents>();
  const candleColors: { time: string; color: string }[] = [];
  const markers: ChartMarker[] = [];
  if (prefs.events && bars.length) {
    const events = [
      ...(input.deals ?? []).map(dealEvent).filter((e): e is NonNullable<typeof e> => e !== null),
      ...calendarEvents(input.events ?? []),
      ...priceEvents(bars, input.darvas ?? []),
    ];
    byBar = resolveEvents(times, events, prefs.eventGroups);
    for (const [time, be] of byBar) {
      const top = be.top;
      if (top.paints) candleColors.push({ time, color: paletteColor(top.color, fg) });
      markers.push({
        time,
        kind: 'custom',
        text: top.letter,
        color: paletteColor(top.color, fg),
        position: BELOW.has(top.key) ? 'belowBar' : 'aboveBar',
        shape: 'circle',
      });
      const chip = be.all.find((e) => e.key === 'ex_date');
      if (chip && chip !== top && top.key !== 'ex_date') {
        markers.push({ time, kind: 'custom', text: 'E', color: EVENT_COLORS.ex_date, position: 'belowBar', shape: 'square' });
      }
    }
  }

  // ---- deal-price lines (part of the deal events)
  const segments: ChartSegment[] = [];
  if (prefs.events && prefs.eventGroups.deals !== false) segments.push(...dealLines(input.deals ?? [], times, tf));

  // ---- RSI + divergences
  let divergences: Divergence[] = [];
  if (prefs.rsi && prefs.rsiDiv && bars.length > 30) {
    const r = rsiCalc(
      bars.map((b) => b.close),
      14,
    );
    divergences = rsiDivergences(bars, r, { hidden: prefs.rsiHidden });
    segments.push(...divergenceSegments(divergences));
  }

  // ---- drawings
  const drawn = drawingLayers(input.drawings ?? []);
  segments.push(...drawn.segments);

  const barNote = (time: string) => {
    const be = byBar.get(time);
    return be ? be.all.map((e) => `${e.letter} ${e.text}`).join(' · ') : null;
  };

  return {
    emaPeriods: [...prefs.emas].sort((a, b) => a - b),
    priceStyle: prefs.style,
    candleColors,
    markers: markers.sort((a, b) => a.time.localeCompare(b.time)),
    segments,
    levels: drawn.levels,
    rsi: prefs.rsi ? { period: 14 } : null,
    volume: prefs.volPane,
    volumeAvg: prefs.volPane && prefs.volAvg,
    divergences,
    byBar,
    barNote,
  };
}

/** Same query keys as Stock 360 (events) so the cache is shared. */
export function useChartLayers(
  symbol: string,
  bars: readonly OHLCBar[],
  tf: Timeframe,
  opts: { enabled?: boolean; darvas?: readonly DarvasRow[] | null } = {},
): ChartLayers {
  const [prefs] = useChartPrefs();
  const enabled = (opts.enabled ?? true) && prefs.events;
  const deals = useApiQuery('charts/{sym}/deal-candles', { params: { sym: symbol } }, { enabled });
  const events = useApiQuery('stock/{sym}/events', { params: { sym: symbol }, query: { days_ahead: 14, limit: 500 } }, { enabled });
  const drawings = useDrawings(symbol);
  const fg = useMemo(() => tokenColor('fg'), []);
  return useMemo(
    () =>
      buildChartLayers({
        bars,
        tf,
        prefs,
        deals: deals.data?.rows,
        events: events.data?.rows,
        darvas: opts.darvas,
        drawings,
        fg,
      }),
    [bars, tf, prefs, deals.data, events.data, opts.darvas, drawings, fg],
  );
}
