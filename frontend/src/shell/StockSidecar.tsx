/**
 * Stock 360 sidecar: resizable (drag the left edge), pinnable (pinned docks
 * and pushes content; unpinned overlays it). Content is the legacy
 * InspectorSidecar until the Stock 360 rebuild lands (spec 10 step 6).
 */
import { ExternalLink, Maximize2, Pin, PinOff, Star, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';
import { cn } from '../lib/cn';
import { useEscapeLayer } from '../lib/layers';
import { readJSON, writeJSON } from '../lib/storage';
import { tradingViewChartUrl } from '../lib/tradingview';
import { useShell } from './ShellContext';

const MIN_W = 340;
const MAX_W = 900;
const PREF_KEY = 'mp.sidecar.v1';

export interface StockSidecarProps {
  symbol: string;
  /** Sidecar body; the shell passes the legacy inspector for now. */
  children: ReactNode;
}

export function StockSidecar({ symbol, children }: StockSidecarProps) {
  const shell = useShell();
  const [prefs, setPrefs] = useState(() => readJSON(PREF_KEY, { width: 440, pinned: true }));
  const dragging = useRef<{ x: number; w: number } | null>(null);
  useEffect(() => writeJSON(PREF_KEY, prefs), [prefs]);
  useEscapeLayer(true, () => shell.openSymbol(null), { modal: false });

  const onPointerDown = useCallback(
    (e: PointerEvent) => {
      dragging.current = { x: e.clientX, w: prefs.width };
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [prefs.width],
  );
  const onPointerMove = (e: PointerEvent) => {
    if (!dragging.current) return;
    const w = Math.min(MAX_W, Math.max(MIN_W, dragging.current.w + (dragging.current.x - e.clientX)));
    setPrefs((p) => ({ ...p, width: w }));
  };
  const onPointerUp = () => {
    dragging.current = null;
  };
  const onKeyResize = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') setPrefs((p) => ({ ...p, width: Math.min(MAX_W, p.width + 20) }));
    if (e.key === 'ArrowRight') setPrefs((p) => ({ ...p, width: Math.max(MIN_W, p.width - 20) }));
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
      style={{ width: prefs.width }}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidecar"
        aria-valuenow={prefs.width}
        aria-valuemin={MIN_W}
        aria-valuemax={MAX_W}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onKeyDown={onKeyResize}
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
