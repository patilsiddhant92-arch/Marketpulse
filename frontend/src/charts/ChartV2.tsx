/**
 * Chart v2: the one stock chart used everywhere a stock chart appears (the Charts tab main chart,
 * the Stock 360 sidecar / big chart, the Setups detail drawer, the Research move drawer).
 * HarkPro/12-sprint2-plan.md "Chart v2" + "Chart tools"; approved mockups
 * mockups/chart-v2/mode_IDEAFORGE_clean.png and _info.png.
 *
 * Settings are global (localStorage): Clean / Info, Candles / Line / Vol candles, D / W / M,
 * Events / Normal colours, EMA 10 / 20 / 50 / 200. Tools: line, trend, rectangle, measure,
 * long / short position, anchored VWAP, compare (2nd symbol in %), bar replay. No line alerts.
 */
import { Pause, Play, SkipBack, SkipForward, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useApiQuery } from '../api/query';
import { useChartPrefs } from '../lib/chartPrefs';
import { cn } from '../lib/cn';
import { fmtCompactIN, fmtDate, fmtNum } from '../lib/fmt';
import { tokenColor } from '../lib/tokens';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { Skeleton } from '../ui/Skeleton';
import { px, type Chip, type ReadModel } from './chartRead';
import { useChartSettings, type ChartTf } from './chartSettings';
import { ColourToggle, EmaToggles, ModeToggle, StyleToggleV2, TfToggle, ToolBar } from './ChartControls';
import { ChartEngine, type EnginePoint } from './ChartEngine';
import { buildV2Model, EMA_TOKENS, type ExtraLevel } from './chartV2Model';
import { useDivergences } from './divergenceApi';
import { addDrawing, clickTool, measureText, useDrawings, type DrawPoint, type DrawTool } from './drawings';
import type { BarEvents } from './eventCandles';
import type { Shape } from './scene';
import { barsToOHLC } from './sources';

export const V2_BARS: Record<ChartTf, number> = { D: 1500, W: 520, M: 240 };
const INITIAL: Record<ChartTf, number> = { D: 140, W: 120, M: 90 };
const REPLAY_MS = 600;

export interface ChartV2Props {
  symbol: string;
  /** Controlled timeframe; omitted = the global setting. */
  tf?: ChartTf;
  onTfChange?: (tf: ChartTf) => void;
  /** Big header (symbol, sector · ₹ Cr · as of, last close, change, vol ×). Default true. */
  header?: boolean;
  /** Extra controls on the header's right (star, Stock 360, TradingView…). */
  actions?: ReactNode;
  /** Setup trigger / stop or other levels drawn as tagged lines. */
  extraLevels?: readonly ExtraLevel[];
  /** A date to mark with an arrow (e.g. the move day). */
  focus?: { date: string; label: string } | null;
  initialBars?: number;
  /** Small drawer layout: one toolbar row, smaller RSI pane. */
  compact?: boolean;
  /** Fixed chart height in px (drawers); default fills the parent. */
  chartHeight?: number;
  onSymbolClick?: () => void;
  /** Controlled drawing tool (the Charts tab binds H / T keys); omitted = internal. */
  tool?: DrawTool;
  onToolChange?: (t: DrawTool) => void;
  className?: string;
}

const CHIP_TONE: Record<Chip['tone'], string> = {
  good: 'bg-up/15 text-up',
  bad: 'bg-down/20 text-down',
  warn: 'bg-warn/15 text-warn',
  neutral: 'bg-surface-3 text-fg',
  deal: 'bg-[rgb(var(--c-ev-buy)/0.18)] text-[rgb(var(--c-ev-buy))]',
};

function ChipRow({ chips, muted, label }: { chips: readonly Chip[]; muted?: boolean; label: string }) {
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5" aria-label={label}>
      {chips.map((c) => (
        <span
          key={c.label}
          title={c.title}
          className={cn(
            'rounded-md px-2 py-0.5 text-xs',
            muted ? 'border border-line bg-surface-2 text-fg-2' : cn('font-semibold', CHIP_TONE[c.tone]),
          )}
        >
          {c.label}
        </span>
      ))}
    </div>
  );
}

function ReadPanel({ read, close }: { read: ReadModel; close: number }) {
  return (
    <div className="grid gap-3 md:grid-cols-[1.4fr_1fr]">
      <section aria-label="The read" className="rounded-lg bg-surface-2 p-3">
        <h3 className="mb-1.5 text-sm font-semibold text-fg">The read</h3>
        <ul className="space-y-1.5 text-xs leading-relaxed">
          {read.read.map((l, i) => (
            <li key={i} className={i === 0 ? 'text-fg' : l.startsWith('What to do') ? 'font-medium text-fg' : 'text-fg-2'}>
              {l}
            </li>
          ))}
        </ul>
      </section>
      <section aria-label="Key levels" className="rounded-lg bg-surface-2 p-3">
        <h3 className="mb-1.5 text-sm font-semibold text-fg">
          Key levels <span className="font-normal text-fg-3">(distance from {px(close)})</span>
        </h3>
        <table className="w-full text-xs">
          <tbody>
            {read.levels.map((l) => (
              <tr key={l.label}>
                <td className="py-0.5 text-fg-2">{l.label}</td>
                <td className="num py-0.5 text-right font-semibold text-fg">{px(l.value)}</td>
                <td className={cn('num py-0.5 pl-3 text-right', l.distPct >= 0 ? 'text-up' : 'text-down')}>
                  {l.distPct >= 0 ? '+' : '−'}
                  {fmtNum(Math.abs(l.distPct), Math.abs(l.distPct) < 10 ? 1 : 0)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

interface Story {
  index: number;
  x: number;
  y: number;
}

function StoryPopover({
  story,
  bars,
  byBar,
  volAvg,
  onClose,
}: {
  story: Story;
  bars: readonly {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number | null;
    delivery_pct?: number | null;
  }[];
  byBar: Map<string, BarEvents>;
  volAvg: readonly (number | null)[];
  onClose: () => void;
}) {
  const b = bars[story.index];
  if (!b) return null;
  const prev = bars[story.index - 1];
  const ch = prev ? (b.close / prev.close - 1) * 100 : null;
  const avg = story.index > 0 ? volAvg[story.index - 1] : null;
  const vx = b.volume != null && avg ? b.volume / avg : null;
  const evs = byBar.get(b.time)?.all ?? [];
  return (
    <div
      role="dialog"
      aria-label={`Candle story ${b.time}`}
      className="absolute z-20 w-64 rounded-lg border border-line-strong bg-surface-2 p-2.5 text-xs shadow-2xl"
      style={{ left: Math.max(4, Math.min(story.x + 12, 9999)), top: Math.max(4, story.y - 20) }}
    >
      <div className="mb-1 flex items-center gap-2">
        <span className="font-semibold text-fg">{fmtDate(b.time)}</span>
        {ch != null && <span className={ch >= 0 ? 'text-up' : 'text-down'}>{`${ch >= 0 ? '+' : '−'}${fmtNum(Math.abs(ch), 1)}%`}</span>}
        <button type="button" aria-label="Close" onClick={onClose} className="ml-auto text-fg-3 hover:text-fg">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="num grid grid-cols-4 gap-1 text-fg-2">
        <span>O {px(b.open)}</span>
        <span>H {px(b.high)}</span>
        <span>L {px(b.low)}</span>
        <span>C {px(b.close)}</span>
      </div>
      <div className="num mt-0.5 text-fg-3">
        Vol {fmtCompactIN(b.volume ?? null)}
        {vx != null && ` · ${fmtNum(vx, 1)}× the 20-bar average`}
        {b.delivery_pct != null && ` · Deliv ${fmtNum(b.delivery_pct, 0)}%`}
      </div>
      {evs.length > 0 ? (
        <ul className="mt-1.5 space-y-1 border-t border-line pt-1.5">
          {evs.map((e, i) => (
            <li key={i} className="flex gap-1.5">
              <span className="w-3 shrink-0 text-center font-bold" style={{ color: tokenColor(e.color) }}>
                {e.letter}
              </span>
              <span className="text-fg">{e.text}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-1.5 border-t border-line pt-1.5 text-fg-3">No deal or event on this bar.</div>
      )}
    </div>
  );
}

export function ChartV2({
  symbol,
  tf: tfProp,
  onTfChange,
  header = true,
  actions,
  extraLevels,
  focus,
  initialBars,
  compact = false,
  chartHeight,
  onSymbolClick,
  tool: toolProp,
  onToolChange,
  className,
}: ChartV2Props) {
  const [settings, setSettings] = useChartSettings();
  const [prefs] = useChartPrefs();
  const tf = tfProp ?? settings.tf;
  const setTf = (t: ChartTf) => (onTfChange ? onTfChange(t) : setSettings({ tf: t }));
  const mode = settings.mode;
  const limit = V2_BARS[tf];

  const bars = useApiQuery('stock/{sym}/bars', { params: { sym: symbol }, query: { tf, limit } }, { keepPrevious: true });
  const darvas = useApiQuery('stock/{sym}/darvas', { params: { sym: symbol }, query: { tf, limit } }, { keepPrevious: true });
  const head = useApiQuery('stock/{sym}', { params: { sym: symbol } });
  const deals = useApiQuery('charts/{sym}/deal-candles', { params: { sym: symbol } });
  const events = useApiQuery('stock/{sym}/events', { params: { sym: symbol }, query: { days_ahead: 14, limit: 500 } });

  const allBars = useMemo(() => barsToOHLC(bars.data?.rows ?? []), [bars.data]);

  // ---------------------------------------------------------------- tools, replay, compare
  const [innerTool, setInnerTool] = useState<DrawTool>('none');
  const tool = toolProp ?? innerTool;
  const [pending, setPending] = useState<DrawPoint | null>(null);
  const [measure, setMeasure] = useState<{ a: DrawPoint & { index: number }; b: (DrawPoint & { index: number }) | null } | null>(null);
  const [replay, setReplay] = useState<{ index: number; playing: boolean } | null>(null);
  const [compare, setCompare] = useState<string | null>(null);
  const [story, setStory] = useState<Story | null>(null);
  const [keyFor, setKeyFor] = useState(`${symbol}|${tf}`);
  if (keyFor !== `${symbol}|${tf}`) {
    // A new symbol or timeframe drops half-finished tool state and the replay.
    setKeyFor(`${symbol}|${tf}`);
    setPending(null);
    setMeasure(null);
    setReplay(null);
    setStory(null);
  }
  const chooseTool = useCallback(
    (t: DrawTool) => {
      setInnerTool(t);
      onToolChange?.(t);
      setPending(null);
      setMeasure(null);
      setStory(null);
    },
    [onToolChange],
  );
  // An outside tool change (H / T keys) also drops the half-drawn point.
  const [toolSeen, setToolSeen] = useState(tool);
  if (toolSeen !== tool) {
    setToolSeen(tool);
    setPending(null);
    if (tool !== 'measure') setMeasure(null);
  }

  const shown = useMemo(() => (replay ? allBars.slice(0, Math.min(allBars.length, replay.index + 1)) : allBars), [allBars, replay]);
  const replayDate = replay ? (shown[shown.length - 1]?.time ?? null) : null;

  useEffect(() => {
    if (!replay?.playing) return;
    const id = window.setInterval(() => {
      setReplay((r) => {
        if (!r) return r;
        if (r.index >= allBars.length - 1) return { ...r, playing: false };
        return { ...r, index: r.index + 1 };
      });
    }, REPLAY_MS);
    return () => window.clearInterval(id);
  }, [replay?.playing, allBars.length]);

  useEffect(() => {
    if (tool === 'none' && !story && !measure) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      setStory(null);
      chooseTool('none');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [tool, story, measure, chooseTool]);

  const cmpBars = useApiQuery('stock/{sym}/bars', { params: { sym: compare ?? '' }, query: { tf, limit } }, { enabled: !!compare });
  const cmpCloses = useMemo(() => {
    if (!compare) return null;
    const m = new Map<string, number>();
    for (const r of cmpBars.data?.rows ?? []) if (r.trade_date && r.close != null) m.set(r.trade_date, r.close);
    return m.size ? { symbol: compare, closes: m } : null;
  }, [compare, cmpBars.data]);

  // ---------------------------------------------------------------- model
  const div = useDivergences(symbol, tf, allBars, prefs.rsi && prefs.rsiDiv && allBars.length > 30);
  const drawings = useDrawings(symbol);
  const h = head.data?.rows[0];
  const servedStats = useMemo(
    () =>
      tf === 'D' && h
        ? {
            fromHighPct: h.away_52w_high_pct ?? (h.high_52w && h.close ? (h.close / h.high_52w - 1) * 100 : null),
            atrPct: h.atr_pct ?? null,
            crPerDay: h.adv_cr_20d ?? null,
          }
        : null,
    [h, tf],
  );
  const model = useMemo(
    () =>
      buildV2Model({
        bars: shown,
        tf,
        mode,
        colours: settings.colours,
        emas: prefs.emas,
        rsi: prefs.rsi,
        divergences: prefs.rsiDiv,
        hiddenDivergences: prefs.rsiHidden,
        darvasOn: prefs.darvas,
        darvasRows: darvas.data?.rows,
        deals: deals.data?.rows,
        events: events.data?.rows,
        divergenceRows: div.rows,
        groups: prefs.eventGroups,
        drawings,
        extraLevels,
        focus,
        compare: cmpCloses,
        replayDate,
        servedStats,
      }),
    [
      shown,
      tf,
      mode,
      settings.colours,
      prefs,
      darvas.data,
      deals.data,
      events.data,
      div.rows,
      drawings,
      extraLevels,
      focus,
      cmpCloses,
      replayDate,
      servedStats,
    ],
  );

  // Pending tool preview + measure on top of the model shapes.
  const shapes = useMemo<Shape[]>(() => {
    const extra: Shape[] = [];
    const idx = (time: string) => shown.findIndex((b) => b.time >= time);
    if (pending && (tool === 'trend' || tool === 'rect' || tool === 'long' || tool === 'short')) {
      const i = idx(pending.time);
      if (i >= 0)
        extra.push({
          kind: 'text',
          layer: 'fg',
          i,
          p: pending.price,
          text: tool === 'long' || tool === 'short' ? '● entry: now click the stop' : '● first point',
          color: tokenColor('draw'),
          dy: -4,
          bold: true,
        });
    }
    if (measure?.b) {
      const { a, b } = measure;
      const up = b.price >= a.price;
      const col = tokenColor(up ? 'up' : 'down');
      extra.push({
        kind: 'rect',
        layer: 'fg',
        i1: a.index,
        i2: b.index,
        p1: a.price,
        p2: b.price,
        fill: tokenColor(up ? 'up' : 'down', 0.14),
        stroke: col,
      });
      extra.push({
        kind: 'text',
        layer: 'fg',
        i: (a.index + b.index) / 2,
        p: Math.max(a.price, b.price),
        text: measureText(a, b),
        color: col,
        align: 'center',
        dy: -4,
        bg: tokenColor('surface', 0.9),
        bold: true,
      });
    } else if (measure) {
      extra.push({
        kind: 'text',
        layer: 'fg',
        i: measure.a.index,
        p: measure.a.price,
        text: '● measure from here',
        color: tokenColor('draw'),
        dy: -4,
      });
    }
    return extra.length ? [...model.shapes, ...extra] : model.shapes;
  }, [model.shapes, pending, measure, tool, shown]);

  const onClick = useCallback(
    (p: EnginePoint) => {
      if (tool === 'none') {
        setStory((s) => (s && s.index === p.index ? null : { index: p.index, x: p.x, y: p.y }));
        return;
      }
      if (p.pane !== 0 || p.price == null) return;
      const pt = { time: p.time, price: p.price };
      if (tool === 'replay') {
        setReplay({ index: Math.max(20, p.index), playing: false });
        chooseTool('none');
        return;
      }
      if (tool === 'measure') {
        setMeasure((m) => (!m || m.b ? { a: { ...pt, index: p.index }, b: null } : { a: m.a, b: { ...pt, index: p.index } }));
        return;
      }
      const r = clickTool(tool, pending, pt);
      setPending(r.pending);
      if (r.done) {
        addDrawing(symbol, r.done);
        chooseTool('none');
      }
    },
    [tool, pending, symbol, chooseTool],
  );

  // ---------------------------------------------------------------- legend
  const emaShown = useMemo(() => [...prefs.emas].sort((a, b) => a - b), [prefs.emas]);
  const legend = useCallback(
    (i: number) => {
      const b = shown[i];
      if (!b) return null;
      const prev = shown[i - 1];
      const up = prev ? b.close >= prev.close : b.close >= b.open;
      return (
        <div className="num space-y-0.5 text-xs">
          <div className="flex flex-wrap items-baseline gap-x-2.5 rounded bg-surface/70 px-1">
            <span className="font-semibold text-fg-2">{fmtDate(b.time).replace(/ \d{4}$/, '')}</span>
            <span className="text-fg-3">
              O <span className="font-semibold text-fg">{px(b.open)}</span>
            </span>
            <span className="text-fg-3">
              H <span className="font-semibold text-fg">{px(b.high)}</span>
            </span>
            <span className="text-fg-3">
              L <span className="font-semibold text-fg">{px(b.low)}</span>
            </span>
            <span className={up ? 'text-up' : 'text-down'}>
              C <span className="font-semibold">{px(b.close)}</span>
            </span>
            <span className="text-fg-3">Vol {fmtCompactIN(b.volume ?? null, 1)}</span>
          </div>
          {emaShown.length > 0 && (
            <div className="flex gap-2.5 px-1 text-2xs">
              {emaShown.map((p) => (
                <span key={p} style={{ color: tokenColor(EMA_TOKENS[p] ?? 'fg-3') }}>
                  EMA{p} {px(model.emaValues[p]?.[i] ?? null)}
                </span>
              ))}
            </div>
          )}
        </div>
      );
    },
    [shown, emaShown, model.emaValues],
  );

  // ---------------------------------------------------------------- header
  const last = shown[shown.length - 1];
  const prev = shown[shown.length - 2];
  const change = last && prev ? (last.close / prev.close - 1) * 100 : null;
  const avgPrev = shown.length > 1 ? model.volume.avg[shown.length - 2] : null;
  const volX = last?.volume != null && avgPrev ? last.volume / avgPrev : null;
  const tfWord = tf === 'D' ? 'Daily' : tf === 'W' ? 'Weekly' : 'Monthly';
  const sub = [
    h?.industry ?? h?.sector,
    h?.market_cap_cr != null ? `₹${fmtNum(h.market_cap_cr, 0)} Cr` : null,
    last ? `${tfWord}, as of ${fmtDate(last.time)}` : tfWord,
  ]
    .filter(Boolean)
    .join(' · ');

  const read = model.read;
  const info = mode === 'info';

  let body: ReactNode;
  if (bars.error) body = <ErrorState error={bars.error} onRetry={() => void bars.refetch()} />;
  else if (bars.isLoading) body = <Skeleton className="m-2" height={chartHeight ?? 'calc(100% - 1rem)'} />;
  else if (!allBars.length) body = <EmptyState title={`No bars for ${symbol}`} detail={bars.data?.meta.reason ?? undefined} />;
  else
    body = (
      <ChartEngine
        bars={shown}
        style={prefs.style}
        candleColors={model.candleColors}
        volMult={model.volMult}
        lines={model.lines}
        segments={model.segments}
        tags={model.tags}
        markers={model.markers}
        rsiMarkers={model.rsiMarkers}
        volume={prefs.volPane ? model.volume : null}
        rsi={model.rsi}
        shapes={shapes}
        percent={!!cmpCloses}
        logScale={prefs.bigLog}
        resetKey={`${symbol}|${tf}|${replay ? 'r' : ''}|${focus?.date ?? ''}`}
        initialBars={initialBars ?? INITIAL[tf]}
        centerIndex={focus ? shown.findIndex((b) => b.time >= focus.date) : null}
        onClick={onClick}
        legend={legend}
        rsiHeight={compact ? 80 : 120}
        label={`${symbol} ${tf === 'D' ? 'daily' : tf === 'W' ? 'weekly' : 'monthly'} chart`}
        className={cn(chartHeight ? 'shrink-0' : 'min-h-[260px] flex-1', tool !== 'none' && 'cursor-crosshair')}
        height={chartHeight}
      >
        {story && tool === 'none' && (
          <StoryPopover story={story} bars={shown} byBar={model.byBar} volAvg={model.volume.avg} onClose={() => setStory(null)} />
        )}
        {replay && (
          <div
            className="absolute bottom-2 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1 rounded-lg border border-line-strong bg-surface-2 px-2 py-1 text-xs shadow-xl"
            role="toolbar"
            aria-label="Bar replay"
          >
            <span className="mr-1 font-semibold text-accent">Replay</span>
            <button
              type="button"
              aria-label="Step back"
              onClick={() => setReplay((r) => r && { ...r, playing: false, index: Math.max(1, r.index - 1) })}
              className="rounded p-1 hover:bg-surface-3"
            >
              <SkipBack className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              aria-label={replay.playing ? 'Pause' : 'Play'}
              onClick={() => setReplay((r) => r && { ...r, playing: !r.playing })}
              className="rounded p-1 hover:bg-surface-3"
            >
              {replay.playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            </button>
            <button
              type="button"
              aria-label="Step forward"
              onClick={() => setReplay((r) => r && { ...r, playing: false, index: Math.min(allBars.length - 1, r.index + 1) })}
              className="rounded p-1 hover:bg-surface-3"
            >
              <SkipForward className="h-3.5 w-3.5" />
            </button>
            <span className="num px-1 text-fg-2">{replayDate ? fmtDate(replayDate) : ''}</span>
            <span className="num text-fg-3">{Math.max(0, allBars.length - 1 - replay.index)} bars left</span>
            <button
              type="button"
              aria-label="Exit replay"
              onClick={() => setReplay(null)}
              className="ml-1 rounded p-1 text-fg-3 hover:bg-surface-3 hover:text-fg"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </ChartEngine>
    );

  const toolHint =
    tool === 'none'
      ? null
      : tool === 'replay'
        ? 'Click the bar to start the replay from'
        : tool === 'measure'
          ? 'Click two points to measure'
          : tool === 'hline' || tool === 'avwap'
            ? tool === 'hline'
              ? 'Click a price for the line'
              : 'Click the anchor bar'
            : pending
              ? tool === 'long' || tool === 'short'
                ? 'Click the stop'
                : 'Click the second point'
              : tool === 'long' || tool === 'short'
                ? 'Click the entry'
                : 'Click the first point';

  return (
    <div className={cn('flex min-h-0 min-w-0 flex-col gap-2', className)} data-testid="chart-v2" data-mode={mode}>
      {header && (
        <div className="flex items-start gap-3 px-1">
          <div className="min-w-0">
            <button
              type="button"
              onClick={onSymbolClick}
              disabled={!onSymbolClick}
              className="text-left text-xl font-bold leading-tight text-fg enabled:hover:text-accent"
            >
              {symbol}
            </button>
            <div className="truncate text-xs text-fg-3">{sub}</div>
          </div>
          <div className="ml-auto flex items-start gap-2">
            {actions}
            <div className="text-right">
              <div className="num text-xl font-bold leading-tight text-fg">{px(last?.close ?? null)}</div>
              <div className={cn('num text-xs font-semibold', change == null ? 'text-fg-3' : change >= 0 ? 'text-up' : 'text-down')}>
                {change == null ? '—' : `${change >= 0 ? '+' : '−'}${fmtNum(Math.abs(change), 1)}%`}
                {volX != null && ` · ${fmtNum(volX, 1)}× vol`}
              </div>
            </div>
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1.5 px-1">
        <ModeToggle />
        <StyleToggleV2 />
        <TfToggle tf={tf} onChange={setTf} />
        {info && <ColourToggle />}
        {!compact && <EmaToggles />}
        <ToolBar symbol={symbol} tool={tool} onTool={chooseTool} compare={compare} onCompare={setCompare} />
        {toolHint && <span className="rounded bg-accent/15 px-1.5 py-0.5 text-2xs text-accent">{toolHint} · Esc cancels</span>}
        {cmpCloses && <span className="rounded bg-accent/15 px-1.5 py-0.5 text-2xs text-accent">% scale · vs {cmpCloses.symbol}</span>}
        {!header && actions && <span className="ml-auto">{actions}</span>}
      </div>
      {info && read && (
        <div className="space-y-1.5 px-1">
          <ChipRow chips={read.status} label="Status" />
          <ChipRow chips={read.stats} muted label="Stats" />
        </div>
      )}
      {body}
      {info && read && last && !compact && <ReadPanel read={read} close={last.close} />}
      {info && read && last && compact && (
        <details className="px-1 text-xs">
          <summary className="cursor-pointer text-fg-2">The read and key levels</summary>
          <div className="mt-1.5">
            <ReadPanel read={read} close={last.close} />
          </div>
        </details>
      )}
      <div className="px-1 text-2xs text-fg-3">
        {info
          ? `Tap any candle for its story · Events / Normal colours · D W M${div.source === 'client' && model.divergenceCount ? ' · Divergences computed in the browser' : ''}`
          : `Clean: EMAs, Darvas, volume, RSI.${prefs.style === 'volume' ? ' Candle width = volume vs its 20-bar average.' : ''} Tap a candle for its story.`}
      </div>
    </div>
  );
}
