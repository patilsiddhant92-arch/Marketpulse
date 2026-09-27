/**
 * Stock 360 sidecar frame: resizable (drag the left edge), pinnable (pinned
 * docks and pushes content; unpinned overlays it). Body = Stock360Sidecar.
 */
import { Expand, ExternalLink, Maximize2, Pin, PinOff, Star, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';
import { cn } from '../lib/cn';
import { useEscapeLayer } from '../lib/layers';
import { readJSON, writeJSON } from '../lib/storage';
import { tradingViewChartUrl } from '../lib/tradingview';
import { useShell } from './ShellContext';

const MIN_W = 360;
const PREF_KEY = 'mp.sidecar.v2';
const OLD_KEY = 'mp.sidecar.v1';

/** Widest the sidecar may get: 75 % of the window (the list keeps a usable strip). */
function maxWidth(): number {
  return Math.max(MIN_W, Math.round((typeof window === 'undefined' ? 1400 : window.innerWidth) * 0.75));
}

/** Default width: 40 % of the window, 480-640 px (560 px at 1400 px). */
export function defaultSidecarWidth(viewport: number): number {
  return Math.round(Math.min(640, Math.max(480, viewport * 0.4)));
}

interface SidecarPrefs {
  /** User-dragged width; null = automatic (40 % of the window). */
  width: number | null;
  pinned: boolean;
}

function loadPrefs(): SidecarPrefs {
  const v2 = readJSON<Partial<SidecarPrefs> | null>(PREF_KEY, null);
  const old = readJSON<Partial<SidecarPrefs> | null>(OLD_KEY, null);
  const width = typeof v2?.width === 'number' && Number.isFinite(v2.width) ? v2.width : null;
  const pinned = typeof v2?.pinned === 'boolean' ? v2.pinned : typeof old?.pinned === 'boolean' ? old.pinned : true;
  return { width, pinned };
}

/** Re-render on window resize (auto width and the max follow the window). */
function useViewportWidth(): number {
  const [vw, setVw] = useState(() => (typeof window === 'undefined' ? 1400 : window.innerWidth));
  useEffect(() => {
    const on = () => setVw(window.innerWidth);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return vw;
}

export interface StockSidecarProps {
  symbol: string;
  /** Sidecar body (Stock360Sidecar). */
  children: ReactNode;
}

export function StockSidecar({ symbol, children }: StockSidecarProps) {
  const shell = useShell();
  const [prefs, setPrefs] = useState<SidecarPrefs>(loadPrefs);
  const vw = useViewportWidth();
  const width = Math.min(maxWidth(), Math.max(MIN_W, prefs.width ?? defaultSidecarWidth(vw)));
  const dragging = useRef<{ x: number; w: number } | null>(null);
  useEffect(() => writeJSON(PREF_KEY, prefs), [prefs]);
  useEscapeLayer(true, () => shell.openSymbol(null), { modal: false });

  const onPointerDown = useCallback(
    (e: PointerEvent) => {
      dragging.current = { x: e.clientX, w: width };
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [width],
  );
  const onPointerMove = (e: PointerEvent) => {
    if (!dragging.current) return;
    const w = Math.min(maxWidth(), Math.max(MIN_W, dragging.current.w + (dragging.current.x - e.clientX)));
    setPrefs((p) => ({ ...p, width: w }));
  };
  const onPointerUp = () => {
    dragging.current = null;
  };
  const onKeyResize = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') setPrefs((p) => ({ ...p, width: Math.min(maxWidth(), width + 20) }));
    if (e.key === 'ArrowRight') setPrefs((p) => ({ ...p, width: Math.max(MIN_W, width - 20) }));
  };

  const watched = shell.isWatched(symbol);
  const btn = 'rounded p-1 text-fg-3 hover:bg-surface-3 hover:text-fg';

  return (
    <aside
      aria-label={`Stock 360: ${symbol}`}
      className={cn(
        'flex h-full shrink-0 flex-col border-l border-line bg-surface',
        !prefs.pinned && 'absolute bottom-0 right-0 top-0 z-30 shadow-2xl',
      )}
      style={{ width }}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidecar"
        aria-valuenow={width}
        aria-valuemin={MIN_W}
        aria-valuemax={maxWidth()}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onKeyDown={onKeyResize}
        onDoubleClick={() => setPrefs((p) => ({ ...p, width: null }))}
        title="Drag to resize · double-click = automatic width"
        className="absolute bottom-0 left-0 top-0 z-10 w-1.5 -translate-x-1/2 cursor-col-resize hover:bg-accent/40"
      />
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-line px-2">
        <span className="font-mono text-sm font-semibold text-fg">{symbol}</span>
        <span className="ml-1 text-2xs text-fg-3">Stock 360</span>
        <div className="ml-auto flex items-center gap-0.5">
          <button type="button" className={btn} onClick={() => shell.toggleWatch(symbol)} aria-pressed={watched} title="Watchlist (W)">
            <Star className={cn('h-3.5 w-3.5', watched && 'fill-accent text-accent')} />
          </button>
          <a className={btn} href={tradingViewChartUrl(symbol)} target="_blank" rel="noopener noreferrer" title="TradingView (T)">
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
          <button type="button" className={btn} onClick={() => shell.openBigChart(symbol)} title="Big chart (F)" aria-label="Big chart">
            <Expand className="h-3.5 w-3.5" />
          </button>
          <button type="button" className={btn} onClick={() => shell.openStockPage(symbol)} title="Full page (Enter)">
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            className={btn}
            onClick={() => setPrefs((p) => ({ ...p, pinned: !p.pinned }))}
            aria-pressed={prefs.pinned}
            title={prefs.pinned ? 'Unpin (overlay)' : 'Pin (dock)'}
          >
            {prefs.pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
          </button>
          <button type="button" className={btn} onClick={() => shell.openSymbol(null)} aria-label="Close sidecar" title="Close (Esc)">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden [&>aside]:!w-full [&>aside]:!border-l-0">{children}</div>
    </aside>
  );
}
