/**
 * Chart v2 model (pure): bars + served data + global settings -> everything ChartEngine draws,
 * plus the Info-mode read model. HarkPro/12-sprint2-plan.md "Chart v2", mockups
 * chart-v2/mode_IDEAFORGE_clean.png and _info.png.
 *
 * Clean: EMAs (10/20/50/200 toggles), Darvas shaded boxes (green top, red bottom, faint fill, the
 * current box brighter) + dotted 5-bar top extension + EMA10 projection, volume bars in the bottom of
 * the price pane + 20-bar average, RSI 14 + SMA 14 + divergence lines (latest bright, older faded).
 * Info adds: event candles (deals / results / box breaks coloured, gap + volume spike as dots), the
 * deal cluster callout, deal price lines, Darvas buy stop / stop lines, axis tags for the box and the
 * deals, the breakout label, and the read model (chips, The read, Key levels).
 */
import type { DarvasRow, StockEventRow } from '../api/types';
import type { EventGroup } from './eventCandles';
import type { OHLCBar } from '../lib/indicators';
import { tokenColor, type TokenName } from '../lib/tokens';
import { buildRead, px, type ReadModel } from './chartRead';
import type { EngineLine, EngineMarker, EngineSegment, EngineTag } from './ChartEngine';
import { darvasModel, darvasRowsUpTo, type DarvasModel } from './darvasBoxes';
import { divergenceViews, type DivergenceRow } from './divergence';
import { anchoredVwap, barStats, ema, lastValue, rsiPane, volCandleMultipliers, volumeAvg20, type BarStats } from './series';
import { positionTarget, type Drawing } from './drawings';
import { calendarEvents, dealEvent, infoEventLayer, priceEvents, type BarEvents, type DealCandleRow } from './eventCandles';
import type { Shape } from './scene';

export type V2Mode = 'clean' | 'info';

export const EMA_TOKENS: Record<number, TokenName> = { 10: 'ema-10', 20: 'ema-20', 50: 'ema-50', 200: 'ema-200' };
/** Bars the projections and the right-edge lines run past the last bar. */
export const PROJ_BARS = 5;

export interface ExtraLevel {
  id: string;
  label: string;
  price: number;
  tone: 'up' | 'down' | 'accent';
}

export interface V2Input {
  bars: readonly OHLCBar[];
  tf: 'D' | 'W' | 'M';
  mode: V2Mode;
  colours: 'events' | 'normal';
  emas: readonly number[];
  rsi: boolean;
  divergences: boolean;
  hiddenDivergences?: boolean;
  darvasOn?: boolean;
  darvasRows?: readonly DarvasRow[] | null;
  deals?: readonly DealCandleRow[] | null;
  events?: readonly StockEventRow[] | null;
  divergenceRows?: readonly DivergenceRow[] | null;
  groups?: Partial<Record<EventGroup, boolean>>;
  drawings?: readonly Drawing[];
  extraLevels?: readonly ExtraLevel[];
  /** A date to mark (e.g. the move day in a Research drawer). */
  focus?: { date: string; label: string } | null;
  /** Compare overlay: closes of a second symbol by bar time. */
  compare?: { symbol: string; closes: ReadonlyMap<string, number> } | null;
  /** Bar replay: the last displayed bar date (server rows after it are dropped). */
  replayDate?: string | null;
  /** Served stats (daily, from /stock/{sym}); bar stats fill the gaps. */
  servedStats?: Partial<BarStats> | null;
}

export interface V2Model {
  lines: EngineLine[];
  segments: EngineSegment[];
  tags: EngineTag[];
  markers: EngineMarker[];
  rsiMarkers: EngineMarker[];
  candleColors: Map<number, string>;
  volMult: number[];
  volume: { avg: (number | null)[] };
  rsi: { values: (number | null)[]; sma: (number | null)[] } | null;
  shapes: Shape[];
  darvas: DarvasModel;
  read: ReadModel | null;
  byBar: Map<string, BarEvents>;
  emaLast: Record<number, number | null>;
  emaValues: Record<number, (number | null)[]>;
  stats: BarStats;
  /** Divergences drawn (for the legend). */
  divergenceCount: number;
}

function indexOf(bars: readonly OHLCBar[], iso: string): number {
  let lo = 0;
  let hi = bars.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (bars[mid].time >= iso) {
      ans = mid;
      hi = mid - 1;
    } else lo = mid + 1;
  }
  return ans;
}

export function buildV2Model(input: V2Input): V2Model {
  const { bars, mode, tf } = input;
  const n = bars.length;
  const info = mode === 'info';
  const right = n - 1 + PROJ_BARS + 0.5;
  const closes = bars.map((b) => b.close);
  const upTo = input.replayDate ?? null;

  // ---------------------------------------------------------------- EMAs
  const emaValues: Record<number, (number | null)[]> = {};
  const emaLast: Record<number, number | null> = {};
  const lines: EngineLine[] = [];
  for (const p of [10, 20, 50, 200]) {
    emaValues[p] = ema(closes, p);
    emaLast[p] = lastValue(emaValues[p]);
  }
  for (const p of [...input.emas].sort((a, b) => a - b)) {
    if (!emaValues[p]) continue;
    lines.push({
      id: `ema${p}`,
      values: emaValues[p],
      color: tokenColor(EMA_TOKENS[p] ?? 'fg-3', 0.95),
      width: p === 200 ? 1 : 1,
      tag: `E${p}`,
    });
  }

  // ---------------------------------------------------------------- Darvas
  const rows = upTo ? darvasRowsUpTo(input.darvasRows, upTo) : (input.darvasRows ?? []);
  const darvas = darvasModel(rows, bars);
  const shapes: Shape[] = [];
  if (input.darvasOn !== false) {
    for (const b of darvas.boxes) {
      const cur = b.current;
      shapes.push({
        kind: 'rect',
        layer: 'bg',
        i1: b.from - 0.5,
        i2: (cur ? n - 1 : b.to) + 0.5,
        p1: b.top,
        p2: b.bottom,
        fill: tokenColor('up', cur ? 0.12 : 0.06),
        top: tokenColor('up', cur ? 0.9 : 0.45),
        bottom: tokenColor('down', cur ? 0.9 : 0.45),
        edgeWidth: cur ? 1.5 : 1,
      });
    }
    if (darvas.topExtension.length >= 2) {
      const last = darvas.topExtension[darvas.topExtension.length - 1];
      shapes.push({
        kind: 'line',
        layer: 'fg',
        i1: n - 1,
        p1: darvas.topExtension[0].value,
        i2: n - 1 + last.k,
        p2: last.value,
        color: tokenColor('up', 0.9),
        width: 1.5,
        dash: [3, 4],
      });
    }
  }
  if (input.emas.includes(10) && darvas.emaProjection.length >= 2) {
    const pts = darvas.emaProjection;
    for (let k = 1; k < pts.length; k++) {
      shapes.push({
        kind: 'line',
        layer: 'fg',
        i1: n - 1 + pts[k - 1].k,
        p1: pts[k - 1].value,
        i2: n - 1 + pts[k].k,
        p2: pts[k].value,
        color: tokenColor('ema-10', 0.9),
        width: 1.5,
        dash: [3, 3],
      });
    }
  }

  // ---------------------------------------------------------------- volume + RSI
  const volume = { avg: volumeAvg20(bars) };
  const volMult = volCandleMultipliers(bars);
  const rp = rsiPane(bars);
  const rsi = input.rsi ? { values: rp.rsi, sma: rp.sma } : null;

  // ---------------------------------------------------------------- divergences
  const segments: EngineSegment[] = [];
  const rsiMarkers: EngineMarker[] = [];
  let divergenceCount = 0;
  if (input.rsi && input.divergences && n) {
    const views = divergenceViews(input.divergenceRows ?? [], {
      hidden: input.hiddenDivergences,
      upTo: upTo ?? bars[n - 1].time,
      from: bars[0].time,
    });
    const labelFrom = views.length - 3;
    for (const [k, v] of views.entries()) {
      const i1 = indexOf(bars, v.row.p1_date);
      const i2 = indexOf(bars, v.row.p2_date);
      if (i1 < 0 || i2 <= i1) continue;
      divergenceCount++;
      const tok: TokenName = v.row.side === 'bull' ? 'up' : 'down';
      const color = tokenColor(tok, v.latest ? 1 : 0.4);
      const id = `div-${v.row.side}-${v.row.p1_date}-${v.row.p2_date}`;
      const dashed = v.row.type === 'Hidden';
      segments.push({ id: `${id}-r`, pane: 'rsi', i1, v1: v.row.p1_rsi, i2, v2: v.row.p2_rsi, color, width: v.latest ? 2 : 1, dashed });
      segments.push({
        id: `${id}-p`,
        pane: 'price',
        i1,
        v1: v.row.p1_price,
        i2,
        v2: v.row.p2_price,
        color: tokenColor(tok, v.latest ? 0.9 : 0.3),
        width: 1,
        dashed,
      });
      // Labels on the 3 latest only (older ones crowd the pane).
      if (k >= labelFrom)
        rsiMarkers.push({
          index: i2,
          text: v.label,
          color: tokenColor(tok, v.latest ? 1 : 0.55),
          position: v.row.side === 'bull' ? 'belowBar' : 'aboveBar',
          shape: 'circle',
          size: 0.4,
        });
    }
  }

  // ---------------------------------------------------------------- events (computed in both modes: the candle story uses them)
  const evs = [
    ...(input.deals ?? [])
      .filter((r) => !upTo || (r.trade_date ?? '') <= upTo)
      .map(dealEvent)
      .filter((e): e is NonNullable<typeof e> => e !== null),
    ...calendarEvents((input.events ?? []).filter((e) => !upTo || (e.event_date ?? '') <= upTo)),
    ...priceEvents(bars, rows),
  ];
  const layer = infoEventLayer(
    bars.map((b) => b.time),
    evs,
    { colours: input.colours, groups: input.groups },
  );
  const idxOfTime = new Map(bars.map((b, i) => [b.time, i]));
  const candleColors = new Map<number, string>();
  const markers: EngineMarker[] = [];
  if (info) {
    for (const [time, color] of layer.paint) {
      const i = idxOfTime.get(time);
      if (i != null) candleColors.set(i, color);
    }
    for (const m of layer.markers) {
      const i = idxOfTime.get(m.time);
      if (i != null) markers.push({ index: i, text: m.text, color: m.color, position: m.position, shape: m.shape, size: m.size || 0.1 });
    }
  }
  if (input.focus) {
    const i = indexOf(bars, input.focus.date);
    if (i >= 0)
      markers.push({ index: i, text: input.focus.label, color: tokenColor('accent'), position: 'aboveBar', shape: 'arrowDown', size: 1 });
  }

  // ---------------------------------------------------------------- stats + read
  const own = barStats(bars, tf);
  const s = input.servedStats && !upTo ? input.servedStats : null;
  const stats: BarStats = {
    fromHighPct: s?.fromHighPct ?? own.fromHighPct,
    atrPct: s?.atrPct ?? own.atrPct,
    crPerDay: s?.crPerDay ?? own.crPerDay,
    delivPct: own.delivPct ?? s?.delivPct ?? null,
    rsi: own.rsi,
  };
  const deals = (input.deals ?? []).filter((r) => !upTo || (r.trade_date ?? '') <= upTo);
  const read = n
    ? buildRead({ bars, darvas, deals, emas: { 10: emaLast[10], 20: emaLast[20], 50: emaLast[50], 200: emaLast[200] }, stats, tf })
    : null;

  // ---------------------------------------------------------------- tags + info shapes
  const tags: EngineTag[] = [];
  if (info && read) {
    const box = darvas.current;
    if (box) {
      tags.push({ id: 'box-top', price: box.top, color: tokenColor('up', 0.85), title: 'Box' });
      tags.push({ id: 'box-bottom', price: box.bottom, color: tokenColor('down', 0.85), title: 'Box' });
    }
    for (const d of read.deals) {
      const col = tokenColor(d.letter === 'S' ? 'ev-sell' : d.letter === 'P' ? 'ev-placement' : 'ev-buy');
      tags.push({ id: `deal-${d.from}-${d.letter}`, price: d.price, color: col, title: 'Deal' });
      shapes.push({ kind: 'line', layer: 'fg', i1: d.from, p1: d.price, i2: right, p2: d.price, color: col, width: 1.25, dash: [6, 5] });
    }
    if (box && darvas.buyStop != null && darvas.stop != null) {
      shapes.push({
        kind: 'line',
        layer: 'fg',
        i1: box.from,
        p1: darvas.buyStop,
        i2: right,
        p2: darvas.buyStop,
        color: tokenColor('ev-breakout', 0.9),
        width: 1.5,
      });
      shapes.push({
        kind: 'text',
        layer: 'fg',
        i: box.from,
        p: darvas.buyStop,
        text: `Buy stop ${px(darvas.buyStop)}`,
        color: tokenColor('ev-breakout'),
        dy: -3,
        bold: true,
      });
      shapes.push({
        kind: 'line',
        layer: 'fg',
        i1: box.from,
        p1: darvas.stop,
        i2: right,
        p2: darvas.stop,
        color: tokenColor('ev-breakdown', 0.9),
        width: 1.5,
      });
      shapes.push({
        kind: 'text',
        layer: 'fg',
        i: box.from,
        p: darvas.stop,
        text: `Stop ${px(darvas.stop)}`,
        color: tokenColor('ev-breakdown'),
        dy: -3,
        bold: true,
      });
    }
    if (read.breakout) {
      const b = read.breakout;
      const col = tokenColor(b.failed ? 'ev-breakdown' : 'ev-breakout');
      shapes.push({
        kind: 'text',
        layer: 'fg',
        i: b.index,
        p: bars[b.index].high,
        text: `Breakout ${b.date.slice(8, 10).replace(/^0/, '')} ${MONTHS[Number(b.date.slice(5, 7)) - 1]}${b.failed ? ', failed' : ''}`,
        color: col,
        align: 'center',
        dy: -26,
        bg: tokenColor('surface', 0.92),
        border: col,
        bold: true,
      });
    }
    if (read.cluster) {
      const c = read.cluster;
      const buy = c.netCr >= 0;
      const lines = [
        {
          text: `Deals ${fmtShort(c.fromDate)}${c.toDate !== c.fromDate ? ` – ${fmtShort(c.toDate)}` : ''}`,
          color: tokenColor('fg'),
          bold: true,
        },
        {
          text: `Net ${buy ? 'buy' : 'sell'}  ${buy ? '+' : '−'}₹${Math.abs(c.netCr).toFixed(1)} Cr${c.buyers.length ? `  (${c.buyerClass ? `${c.buyerClass}: ` : ''}${c.buyers.join(', ')})` : ''}`,
          color: tokenColor(buy ? 'ev-buy' : 'ev-sell'),
          bold: true,
        },
      ];
      if (c.churnCr > 0)
        lines.push({ text: `Churn  ₹${c.churnCr.toFixed(0)} Cr  (prop desks, ignored)`, color: tokenColor('fg-2'), bold: false });
      shapes.push({
        kind: 'callout',
        layer: 'fg',
        i: c.from,
        p: c.anchorPrice,
        lines,
        color: tokenColor('ev-buy', 0.8),
        bg: tokenColor('surface', 0.94),
        dx: 120,
        dy: 70,
      });
    }
  }
  for (const l of input.extraLevels ?? []) {
    tags.push({
      id: `x-${l.id}`,
      price: l.price,
      color: tokenColor(l.tone === 'accent' ? 'accent' : l.tone),
      title: l.label,
      line: true,
      dashed: l.tone === 'down',
    });
  }

  // ---------------------------------------------------------------- drawings
  for (const d of input.drawings ?? []) {
    const col = tokenColor('draw');
    if (d.kind === 'hline') tags.push({ id: d.id, price: d.a.price, color: col, title: '', line: true });
    else if (d.kind === 'trend' || d.kind === 'rect') {
      const i1 = indexOf(bars, d.a.time);
      const i2 = indexOf(bars, d.b.time);
      if (i1 < 0 || i2 < 0) continue;
      if (d.kind === 'trend') shapes.push({ kind: 'line', layer: 'fg', i1, p1: d.a.price, i2, p2: d.b.price, color: col, width: 2 });
      else shapes.push({ kind: 'rect', layer: 'fg', i1, i2, p1: d.a.price, p2: d.b.price, fill: tokenColor('draw', 0.1), stroke: col });
    } else if (d.kind === 'long' || d.kind === 'short') {
      const i1 = indexOf(bars, d.a.time);
      let i2 = indexOf(bars, d.b.time);
      if (i1 < 0) continue;
      if (i2 < 0) i2 = n - 1;
      const target = positionTarget(d);
      const risk = Math.abs(d.a.price - d.b.price);
      const rp1 = ((target - d.a.price) / d.a.price) * 100;
      const sp = ((d.b.price - d.a.price) / d.a.price) * 100;
      shapes.push({
        kind: 'rect',
        layer: 'fg',
        i1,
        i2,
        p1: d.a.price,
        p2: target,
        fill: tokenColor('up', 0.16),
        stroke: tokenColor('up', 0.6),
      });
      shapes.push({
        kind: 'rect',
        layer: 'fg',
        i1,
        i2,
        p1: d.a.price,
        p2: d.b.price,
        fill: tokenColor('down', 0.16),
        stroke: tokenColor('down', 0.6),
      });
      shapes.push({
        kind: 'text',
        layer: 'fg',
        i: i1,
        p: target,
        text: `${d.kind === 'long' ? 'Long' : 'Short'} ${px(d.a.price)} · target ${px(target)} (${rp1 >= 0 ? '+' : '−'}${Math.abs(rp1).toFixed(1)}%) · ${d.rr}R`,
        color: tokenColor('up'),
        dy: d.kind === 'long' ? -3 : 15,
        bg: tokenColor('surface', 0.85),
      });
      shapes.push({
        kind: 'text',
        layer: 'fg',
        i: i1,
        p: d.b.price,
        text: `Stop ${px(d.b.price)} (${sp >= 0 ? '+' : '−'}${Math.abs(sp).toFixed(1)}%) · risk ${px(risk)}`,
        color: tokenColor('down'),
        dy: d.kind === 'long' ? 15 : -3,
        bg: tokenColor('surface', 0.85),
      });
    } else if (d.kind === 'avwap') {
      const i = indexOf(bars, d.a.time);
      if (i < 0) continue;
      lines.push({ id: d.id, values: anchoredVwap(bars, i), color: tokenColor('draw', 0.95), width: 2, tag: 'VWAP' });
    }
  }

  // ---------------------------------------------------------------- compare
  if (input.compare) {
    const vals = bars.map((b) => input.compare!.closes.get(b.time) ?? null);
    lines.push({ id: `cmp-${input.compare.symbol}`, values: vals, color: tokenColor('accent'), width: 2, tag: input.compare.symbol });
  }

  return {
    lines,
    segments,
    tags,
    markers,
    rsiMarkers,
    candleColors,
    volMult,
    volume,
    rsi,
    shapes,
    darvas,
    read,
    byBar: layer.byBar,
    emaLast,
    emaValues,
    stats,
    divergenceCount,
  };
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const fmtShort = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
