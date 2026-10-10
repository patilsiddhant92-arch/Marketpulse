/**
 * Charts toolbar controls (HarkPro/09-tab-charts.md §3-§7): price style, Indicators ▾ (the global
 * chart settings), Draw ▾ (horizontal / trend line, saved per symbol) and the event legend.
 */
import { ArrowDownRight, ArrowUpRight, ChevronDown, GitCompare, History, Minus, PenLine, Ruler, Square, Trash2, Waves, X } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { EMA_CHOICES, useChartPrefs } from '../lib/chartPrefs';
import { cn } from '../lib/cn';
import { fmtNum } from '../lib/fmt';
import { useEscapeLayer } from '../lib/layers';
import { DIV_TOKENS, type ChartLayers } from './chartLayers';
import { useChartSettings } from './chartSettings';
import { clearDrawings, removeDrawing, useDrawings, type Drawing, type DrawTool } from './drawings';
import { EVENT_COLORS, EVENT_GROUPS, type EventKey } from './eventCandles';

export const segBtn = (on: boolean) =>
  cn('px-2 py-1 text-xs', on ? 'bg-accent/20 text-accent' : 'text-fg-3 hover:bg-surface-3 hover:text-fg');

function Menu({ label, children, title, width = 260 }: { label: ReactNode; children: ReactNode; title?: string; width?: number }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEscapeLayer(open, () => setOpen(false));
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        title={title}
        onClick={() => setOpen(!open)}
        className="flex h-7 items-center gap-1 rounded border border-line px-2 text-xs text-fg-2 hover:bg-surface-3 hover:text-fg"
      >
        {label}
        <ChevronDown className="h-3 w-3 text-fg-3" />
      </button>
      {open && (
        <div
          role="menu"
          style={{ width }}
          className="absolute left-0 top-full z-40 mt-1 max-h-[70vh] overflow-auto rounded-md border border-line-strong bg-surface-2 p-2 text-xs shadow-2xl"
        >
          {children}
        </div>
      )}
    </div>
  );
}

function Check({ on, onChange, children, title }: { on: boolean; onChange: (v: boolean) => void; children: ReactNode; title?: string }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-surface-3" title={title}>
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} className="accent-[rgb(var(--c-accent))]" />
      <span className="flex min-w-0 items-center gap-1.5 text-fg">{children}</span>
    </label>
  );
}

const swatch = (token: string) => (
  <span aria-hidden className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: `rgb(var(--c-${token}))` }} />
);

const GROUP_SWATCH: Record<string, EventKey> = {
  results: 'results',
  deals: 'deal_B',
  breakout: 'breakout',
  breakdown: 'breakdown',
  gap: 'gap_up',
  volume: 'volume',
  chips: 'ex_date',
};

/** Candles · Line · Volume candles (global). */
export function StyleToggle() {
  const [prefs, setPrefs] = useChartPrefs();
  const opts = [
    { id: 'candles', label: 'Candles', title: 'Candlesticks' },
    { id: 'line', label: 'Line', title: 'Close line' },
    { id: 'volume', label: 'Vol candles', title: 'Volume candles: body width grows with volume vs its 20-bar average (TradingView style)' },
  ] as const;
  return (
    <div className="flex overflow-hidden rounded border border-line" role="group" aria-label="Price style">
      {opts.map((o) => (
        <button key={o.id} type="button" aria-pressed={prefs.style === o.id} title={o.title} onClick={() => setPrefs({ style: o.id })} className={segBtn(prefs.style === o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Indicators ▾ — every global chart setting (stored, applies to every chart). */
export function IndicatorsMenu() {
  const [prefs, setPrefs] = useChartPrefs();
  const groups = prefs.eventGroups;
  const toggleEma = (p: number, on: boolean) =>
    setPrefs({ emas: EMA_CHOICES.filter((x) => (x === p ? on : prefs.emas.includes(x))) });
  return (
    <Menu label="Indicators" title="Chart settings: saved, and used by every chart in the app" width={280}>
      <div className="mb-1 text-2xs uppercase tracking-wide text-fg-3">Price pane</div>
      <div className="mb-1 flex flex-wrap gap-x-3">
        {EMA_CHOICES.map((p) => (
          <Check key={p} on={prefs.emas.includes(p)} onChange={(v) => toggleEma(p, v)}>
            <span className="inline-block h-0.5 w-3" style={{ background: `rgb(var(--c-ema-${p}))` }} /> EMA {p}
          </Check>
        ))}
      </div>
      <Check on={prefs.darvas} onChange={(v) => setPrefs({ darvas: v })} title="Pine SUCCESS Darvas: TopBox / BottomBox step lines + 5-bar projection">
        Darvas box (Pine)
      </Check>
      <Check on={prefs.levels} onChange={(v) => setPrefs({ levels: v })}>
        Setup trigger / stop
      </Check>
      <div className="mb-1 mt-2 text-2xs uppercase tracking-wide text-fg-3">Event candles</div>
      <Check on={prefs.events} onChange={(v) => setPrefs({ events: v })}>
        Colour candles by event
      </Check>
      <div className={cn('ml-4', !prefs.events && 'pointer-events-none opacity-40')}>
        {EVENT_GROUPS.map((g) => (
          <Check key={g.id} on={groups[g.id] !== false} onChange={(v) => setPrefs({ eventGroups: { ...groups, [g.id]: v } })}>
            {swatch(EVENT_COLORS[GROUP_SWATCH[g.id]])}
            <span className="w-3 font-mono text-fg-3">{g.letter}</span> {g.label}
          </Check>
        ))}
      </div>
      <div className="mb-1 mt-2 text-2xs uppercase tracking-wide text-fg-3">Lower panes</div>
      <Check on={prefs.volPane} onChange={(v) => setPrefs({ volPane: v })}>
        Volume (up / down)
      </Check>
      <div className={cn('ml-4', !prefs.volPane && 'pointer-events-none opacity-40')}>
        <Check on={prefs.volAvg} onChange={(v) => setPrefs({ volAvg: v })}>
          20-bar average line
        </Check>
      </div>
      <Check on={prefs.rsi} onChange={(v) => setPrefs({ rsi: v })}>
        RSI 14 (70 / 50 / 30)
      </Check>
      <div className={cn('ml-4', !prefs.rsi && 'pointer-events-none opacity-40')}>
        <Check
          on={prefs.rsiDiv}
          onChange={(v) => setPrefs({ rsiDiv: v })}
          title="Pivots 5 bars each side (confirmed 5 bars late, no repaint). Bearish: price higher high, RSI lower high, first RSI > 60. Bullish mirrored, first RSI < 40. Pivots 5-60 bars apart."
        >
          Divergence lines
        </Check>
        <Check on={prefs.rsiHidden} onChange={(v) => setPrefs({ rsiHidden: v })}>
          Hidden divergences
        </Check>
      </div>
      <Check on={prefs.rsPane} onChange={(v) => setPrefs({ rsPane: v })}>
        RS line vs {prefs.bm === 'nifty50' ? 'Nifty 50' : 'MidSml 400'}
      </Check>
    </Menu>
  );
}

const DRAWING_LABEL: Record<Drawing['kind'], string> = {
  hline: 'Line',
  trend: 'Trend',
  rect: 'Rectangle',
  long: 'Long',
  short: 'Short',
  avwap: 'VWAP from',
};

function drawingText(d: Drawing): string {
  if (d.kind === 'hline') return fmtNum(d.a.price);
  if (d.kind === 'avwap') return d.a.time;
  return `${fmtNum(d.a.price)} → ${fmtNum(d.b.price)}`;
}

/** Draw ▾ — tool picker + this symbol's drawings. */
export function DrawMenu({ symbol, tool, onTool }: { symbol: string | null; tool: DrawTool; onTool: (t: DrawTool) => void }) {
  const drawings = useDrawings(symbol ?? '');
  return (
    <div className="flex items-center gap-1">
      <div className="flex overflow-hidden rounded border border-line" role="group" aria-label="Drawing tool">
        <button
          type="button"
          aria-pressed={tool === 'hline'}
          disabled={!symbol}
          onClick={() => onTool(tool === 'hline' ? 'none' : 'hline')}
          title="Horizontal line (H): click a price"
          className={segBtn(tool === 'hline')}
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-pressed={tool === 'trend'}
          disabled={!symbol}
          onClick={() => onTool(tool === 'trend' ? 'none' : 'trend')}
          title="Trend line (T): click two points"
          className={segBtn(tool === 'trend')}
        >
          <PenLine className="h-3.5 w-3.5" />
        </button>
      </div>
      {symbol && drawings.length > 0 && (
        <Menu label={<span className="num">{drawings.length}</span>} title={`Drawings on ${symbol}`} width={240}>
          <ul className="space-y-0.5">
            {drawings.map((d) => (
              <li key={d.id} className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-surface-3">
                <span className="text-fg-2">{DRAWING_LABEL[d.kind]}</span>
                <span className="num truncate text-fg">{drawingText(d)}</span>
                <button type="button" aria-label="Delete drawing" onClick={() => removeDrawing(symbol, d.id)} className="ml-auto text-fg-3 hover:text-down">
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => clearDrawings(symbol)}
            className="mt-1 flex items-center gap-1 rounded px-1 py-0.5 text-fg-3 hover:text-down"
          >
            <Trash2 className="h-3 w-3" /> Clear all on {symbol}
          </button>
        </Menu>
      )}
    </div>
  );
}

/** Legend under the chart: event colours present on screen + divergence count. */
export function EventLegend({ layers, className }: { layers: ChartLayers; className?: string }) {
  const keys = new Set<EventKey>();
  for (const be of layers.byBar.values()) be.all.forEach((e) => keys.add(e.key));
  const bear = layers.divergences.filter((d) => d.kind === 'bear' || d.kind === 'hidden_bear').length;
  const bull = layers.divergences.length - bear;
  const label: Partial<Record<EventKey, string>> = {
    results: 'R results',
    deal_B: 'B net buy',
    deal_P: 'P placement',
    deal_S: 'S net sell',
    deal_C: 'C churn',
    deal_T: 'T transfer',
    breakout: '↑ box breakout',
    breakdown: '↓ box break',
    gap_up: 'G gap',
    gap_down: 'G gap',
    volume: 'V 3× volume',
    ex_date: 'E ex-date',
  };
  const shown = [...keys].filter((k, i, a) => !(k === 'gap_down' && a.includes('gap_up')));
  if (!shown.length && !layers.divergences.length) return null;
  return (
    <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-0.5 text-2xs text-fg-3', className)} aria-label="Chart legend">
      {shown.map((k) => (
        <span key={k} className="flex items-center gap-1">
          {swatch(EVENT_COLORS[k])} {label[k]}
        </span>
      ))}
      {layers.divergences.length > 0 && (
        <span className="flex items-center gap-1" title="RSI divergence lines on the price and RSI panes">
          <span className="inline-block h-0.5 w-3" style={{ background: `rgb(var(--c-${DIV_TOKENS.bear}))` }} /> {bear} bearish
          <span className="ml-1 inline-block h-0.5 w-3" style={{ background: `rgb(var(--c-${DIV_TOKENS.bull}))` }} /> {bull} bullish divergence
        </span>
      )}
      <span className="ml-auto">Hover a candle for what happened.</span>
    </div>
  );
}

// ====================================================================== Chart v2 controls
const pill = (on: boolean) =>
  cn('h-7 rounded px-2.5 text-xs font-semibold transition-colors', on ? 'bg-surface-3 text-fg' : 'text-fg-3 hover:bg-surface-3/60 hover:text-fg-2');

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="flex items-center gap-0.5 rounded-md bg-surface-2 p-0.5">
      {children}
    </div>
  );
}

/** Clean · Info (global). */
export function ModeToggle() {
  const [s, set] = useChartSettings();
  return (
    <Group label="Chart mode">
      <button type="button" aria-pressed={s.mode === 'clean'} onClick={() => set({ mode: 'clean' })} className={pill(s.mode === 'clean')} title="Clean: EMAs, Darvas, volume, RSI">
        Clean
      </button>
      <button type="button" aria-pressed={s.mode === 'info'} onClick={() => set({ mode: 'info' })} className={pill(s.mode === 'info')} title="Info: + events, deals, levels and the read">
        Info
      </button>
    </Group>
  );
}

/** Candles · Line · Vol candles (global, lib/chartPrefs). */
export function StyleToggleV2() {
  const [prefs, setPrefs] = useChartPrefs();
  const opts = [
    { id: 'candles', label: 'Candles', title: 'Candlesticks' },
    { id: 'line', label: 'Line', title: 'Close line' },
    { id: 'volume', label: 'Vol candles', title: 'Volume candles: width = volume vs its 20-bar average (0.35-3×)' },
  ] as const;
  return (
    <Group label="Price style">
      {opts.map((o) => (
        <button key={o.id} type="button" aria-pressed={prefs.style === o.id} title={o.title} onClick={() => setPrefs({ style: o.id })} className={pill(prefs.style === o.id)}>
          {o.label}
        </button>
      ))}
    </Group>
  );
}

export function TfToggle({ tf, onChange }: { tf: 'D' | 'W' | 'M'; onChange: (tf: 'D' | 'W' | 'M') => void }) {
  return (
    <Group label="Timeframe">
      {(['D', 'W', 'M'] as const).map((t) => (
        <button key={t} type="button" aria-pressed={tf === t} onClick={() => onChange(t)} className={cn(pill(tf === t), 'font-mono')} title={t === 'D' ? 'Daily' : t === 'W' ? 'Weekly' : 'Monthly'}>
          {t}
        </button>
      ))}
    </Group>
  );
}

/** Events · Normal candle colours (global; used in Info mode). */
export function ColourToggle() {
  const [s, set] = useChartSettings();
  return (
    <Group label="Candle colours">
      <button type="button" aria-pressed={s.colours === 'events'} onClick={() => set({ colours: 'events' })} className={pill(s.colours === 'events')} title="Deal and box-break candles take the event colour">
        Events
      </button>
      <button type="button" aria-pressed={s.colours === 'normal'} onClick={() => set({ colours: 'normal' })} className={pill(s.colours === 'normal')} title="Green / red candles">
        Normal
      </button>
    </Group>
  );
}

/** EMA 10 / 20 / 50 / 200 toggles (global). */
export function EmaToggles() {
  const [prefs, setPrefs] = useChartPrefs();
  return (
    <Group label="EMAs">
      {EMA_CHOICES.map((p) => {
        const on = prefs.emas.includes(p);
        return (
          <button
            key={p}
            type="button"
            aria-pressed={on}
            title={`EMA ${p}`}
            onClick={() => setPrefs({ emas: EMA_CHOICES.filter((x) => (x === p ? !on : prefs.emas.includes(x))) })}
            className={cn(pill(on), 'flex items-center gap-1 px-2 font-mono')}
          >
            <span className="inline-block h-0.5 w-2.5 rounded" style={{ background: `rgb(var(--c-ema-${p}))`, opacity: on ? 1 : 0.35 }} />
            {p}
          </button>
        );
      })}
    </Group>
  );
}

const TOOLS: { id: DrawTool; label: string; title: string; icon: ReactNode }[] = [
  { id: 'hline', label: 'Line', title: 'Horizontal line: click a price', icon: <Minus className="h-3.5 w-3.5" /> },
  { id: 'trend', label: 'Trend', title: 'Trend line: click two points', icon: <PenLine className="h-3.5 w-3.5" /> },
  { id: 'rect', label: 'Rectangle', title: 'Rectangle: click two corners', icon: <Square className="h-3.5 w-3.5" /> },
  { id: 'measure', label: 'Measure', title: 'Measure: click two points (% and bars). Not saved', icon: <Ruler className="h-3.5 w-3.5" /> },
  { id: 'long', label: 'Long', title: 'Long position: click the entry, then the stop (target = 2R)', icon: <ArrowUpRight className="h-3.5 w-3.5" /> },
  { id: 'short', label: 'Short', title: 'Short position: click the entry, then the stop (target = 2R)', icon: <ArrowDownRight className="h-3.5 w-3.5" /> },
  { id: 'avwap', label: 'VWAP', title: 'Anchored VWAP: click the anchor bar', icon: <Waves className="h-3.5 w-3.5" /> },
  { id: 'replay', label: 'Replay', title: 'Bar replay: click the bar to start from', icon: <History className="h-3.5 w-3.5" /> },
];

/** Chart tools: drawings, measure, positions, anchored VWAP, replay; compare opens a symbol box. No line alerts. */
export function ToolBar({
  symbol,
  tool,
  onTool,
  compare,
  onCompare,
}: {
  symbol: string | null;
  tool: DrawTool;
  onTool: (t: DrawTool) => void;
  compare: string | null;
  onCompare: (sym: string | null) => void;
}) {
  const drawings = useDrawings(symbol ?? '');
  const [cmpOpen, setCmpOpen] = useState(false);
  const [text, setText] = useState('');
  return (
    <div className="flex items-center gap-1">
      <Group label="Chart tools">
        {TOOLS.map((t) => (
          <button
            key={t.id}
            type="button"
            aria-pressed={tool === t.id}
            aria-label={t.label}
            disabled={!symbol}
            title={t.title}
            onClick={() => onTool(tool === t.id ? 'none' : t.id)}
            className={cn(pill(tool === t.id), 'px-1.5', tool === t.id && 'text-accent')}
          >
            {t.icon}
          </button>
        ))}
        <div className="relative">
          <button
            type="button"
            aria-pressed={!!compare}
            aria-label="Compare"
            disabled={!symbol}
            title={compare ? `Comparing with ${compare} (% scale). Click to change` : 'Compare: overlay a second symbol in %'}
            onClick={() => setCmpOpen((o) => !o)}
            className={cn(pill(!!compare), 'px-1.5', compare && 'text-accent')}
          >
            <GitCompare className="h-3.5 w-3.5" />
          </button>
          {cmpOpen && (
            <form
              className="absolute right-0 top-full z-40 mt-1 flex w-56 items-center gap-1 rounded-md border border-line-strong bg-surface-2 p-2 text-xs shadow-2xl"
              onSubmit={(e) => {
                e.preventDefault();
                const v = text.trim().toUpperCase().replace(/^NSE:/, '');
                onCompare(v || null);
                setCmpOpen(false);
              }}
            >
              <input
                autoFocus
                aria-label="Compare symbol"
                placeholder="Symbol, e.g. HAL"
                value={text}
                onChange={(e) => setText(e.target.value)}
                className="h-7 min-w-0 flex-1 rounded border border-line bg-surface px-2 font-mono text-fg"
              />
              {compare && (
                <button type="button" onClick={() => (onCompare(null), setCmpOpen(false))} className="rounded px-1.5 py-1 text-fg-3 hover:text-down" title="Stop comparing">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </form>
          )}
        </div>
      </Group>
      {symbol && drawings.length > 0 && (
        <Menu label={<span className="num">{drawings.length}</span>} title={`Drawings on ${symbol}`} width={250}>
          <ul className="space-y-0.5">
            {drawings.map((d) => (
              <li key={d.id} className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-surface-3">
                <span className="text-fg-2">{DRAWING_LABEL[d.kind]}</span>
                <span className="num truncate text-fg">{drawingText(d)}</span>
                <button type="button" aria-label="Delete drawing" onClick={() => removeDrawing(symbol, d.id)} className="ml-auto text-fg-3 hover:text-down">
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={() => clearDrawings(symbol)} className="mt-1 flex items-center gap-1 rounded px-1 py-0.5 text-fg-3 hover:text-down">
            <Trash2 className="h-3 w-3" /> Clear all on {symbol}
          </button>
        </Menu>
      )}
    </div>
  );
}
