/**
 * Big chart (F): near-full-screen Stock 360 chart — candles, EMAs, D/W/M,
 * Darvas boxes, setup trigger / stop levels (priced on the axis), volume /
 * delivery pane, RS pane — with the setup + sizer rail beside it.
 * J / K step through the current list (the table, queue or chart grid the
 * stock was opened from); D / W / M timeframe; B boxes; L log; Esc closes.
 */
import { ChevronDown, ChevronUp, ExternalLink, Maximize2, X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { isUnavailable } from '../api/client';
import { useChartPrefs } from '../lib/chartPrefs';
import { cn } from '../lib/cn';
import { useEscapeLayer } from '../lib/layers';
import { getNavList, stepSymbol } from '../lib/navList';
import { tradingViewChartUrl } from '../lib/tradingview';
import { useShell } from '../shell/ShellContext';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { StrengthBlock, TrendBlock } from './MetricsBlock';
import { SetupsBlock } from './SetupsBlock';
import { StockChartPanel } from './StockChartPanel';
import { StockHeader } from './StockHeader';
import { useStock360 } from './useStock360';

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable;
}

const BIG_PANES = { volume: 120, rs: 110 };

export function BigChart({ symbol }: { symbol: string }) {
  const shell = useShell();
  const [prefs, setPrefs] = useChartPrefs();
  const data = useStock360(symbol);
  const s = data.header.data?.rows[0];
  const list = getNavList();
  const pos = list.indexOf(symbol);

  const close = () => shell.openBigChart(null);
  useEscapeLayer(true, close, { modal: true });

  const step = (dir: 1 | -1) => {
    const next = stepSymbol(getNavList(), symbol, dir);
    if (!next || next === symbol) return;
    shell.openBigChart(next);
    if (shell.symbol) shell.openSymbol(next); // keep the sidecar on the same stock
  };
  const stepRef = useRef(step);
  const prefsRef = useRef(prefs);
  useEffect(() => {
    stepRef.current = step;
    prefsRef.current = prefs;
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      const k = e.key.toLowerCase();
      const p = prefsRef.current;
      let handled = true;
      if (k === 'j' || e.key === 'ArrowDown') stepRef.current(1);
      else if (k === 'k' || e.key === 'ArrowUp') stepRef.current(-1);
      else if (k === 'd') setPrefs({ bigTf: 'D' });
      else if (k === 'w') setPrefs({ bigTf: 'W' });
      else if (k === 'm') setPrefs({ bigTf: 'M' });
      else if (k === 'b') setPrefs({ darvas: !p.darvas });
      else if (k === 'l') setPrefs({ bigLog: !p.bigLog });
      else if (k === 'f') shell.openBigChart(null);
      else handled = false;
      if (handled) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    // Capture phase: the big chart is modal, table / Charts J/K underneath must not also fire.
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [setPrefs, shell]);

  const btn = 'rounded p-1 text-fg-3 hover:bg-surface-3 hover:text-fg disabled:opacity-30';
  const unavailable = data.header.data && isUnavailable(data.header.data);

  return (
    <div className="fixed inset-0 z-50 flex bg-bg/70 p-2 backdrop-blur-[1px]" role="dialog" aria-modal="true" aria-label={`Big chart: ${symbol}`}>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded border border-line-strong bg-surface shadow-2xl" data-testid="big-chart">
        <header className="flex shrink-0 items-start gap-3 border-b border-line px-3 py-1.5">
          <div className="flex items-center gap-0.5 self-center">
            <button type="button" className={btn} onClick={() => step(-1)} disabled={list.length === 0 || pos === 0} title="Previous in list (K)" aria-label="Previous stock">
              <ChevronUp className="h-4 w-4" />
            </button>
            <button
              type="button"
              className={btn}
              onClick={() => step(1)}
              disabled={list.length === 0 || pos === list.length - 1}
              title="Next in list (J)"
              aria-label="Next stock"
            >
              <ChevronDown className="h-4 w-4" />
            </button>
          </div>
          <h2 className="mt-0.5 font-mono text-lg font-semibold text-fg">{symbol}</h2>
          <div className="min-w-0 flex-1">
            <StockHeader row={s} loading={data.header.isLoading} asOf={data.header.data?.as_of} compact />
          </div>
          <div className="flex shrink-0 items-center gap-1 self-center text-2xs text-fg-3">
            <span className="num mr-2" title="Position in the current list (the table / queue / chart grid you opened it from)">
              {list.length ? `${pos >= 0 ? pos + 1 : '–'} / ${list.length}` : 'no list'} · J/K · D/W/M · B boxes · L log · Esc
            </span>
            <button
              type="button"
              aria-pressed={prefs.bigLog}
              onClick={() => setPrefs({ bigLog: !prefs.bigLog })}
              className={cn('rounded border border-line px-1.5 py-0.5 font-mono', prefs.bigLog ? 'bg-accent/20 text-accent' : 'hover:text-fg')}
              title="Log scale (L)"
            >
              log
            </button>
            <a className={btn} href={tradingViewChartUrl(symbol)} target="_blank" rel="noopener noreferrer" title="TradingView">
              <ExternalLink className="h-4 w-4" />
            </a>
            <button
              type="button"
              className={btn}
              onClick={() => {
                close();
                shell.openStockPage(symbol);
              }}
              title="Full Stock 360 page"
            >
              <Maximize2 className="h-4 w-4" />
            </button>
            <button type="button" className={btn} onClick={close} aria-label="Close big chart" title="Close (Esc)">
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>
        {data.header.error ? (
          <ErrorState error={data.header.error} onRetry={() => void data.header.refetch()} />
        ) : unavailable ? (
          <EmptyState title={`No data for ${symbol}`} detail={data.header.data?.meta.reason ?? undefined} />
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_300px]">
            <StockChartPanel
              key={symbol}
              symbol={symbol}
              data={data}
              setups={s?.setups}
              timeframe={prefs.bigTf}
              onTimeframeChange={(t) => setPrefs({ bigTf: t })}
              logScale={prefs.bigLog}
              paneHeights={BIG_PANES}
              initialBars={prefs.bigTf === 'D' ? 250 : prefs.bigTf === 'W' ? 160 : 90}
              className="min-w-0 border-r border-line"
            />
            <div className="min-h-0 space-y-2 overflow-y-auto p-2">
              <SetupsBlock setups={s?.setups} loading={data.header.isLoading} />
              {s && <StrengthBlock s={s} />}
              {s && <TrendBlock s={s} />}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
