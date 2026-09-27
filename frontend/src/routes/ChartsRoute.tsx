/**
 * Charts (spec 7.8, lazy-loaded): any list as a grid of charts.
 *
 * Source picker inside the tab (Desk queues, Screener preset / last custom run,
 * Groups at any level, Deals, Research, Watchlist, or ?syms= from "Open in
 * Charts"); sort; 4 / 6 / 9 tiles with a date-synced crosshair; D / W / M;
 * relative performance vs MidSml400 for a chosen window; page through the whole
 * list (J / K or [ / ]); click a symbol to inspect it in the Stock 360 sidecar
 * without leaving the grid; expand one tile (Esc returns). Only the visible
 * page is rendered; the next page's bars are prefetched.
 */
import { useStockContext } from '../context/stockContext';
import { useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Copy, Crosshair, Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiGet } from '../api/client';
import { apiQueryKey, useApiQuery } from '../api/query';
import { ChartsGlance } from '../charts/ChartsGlance';
import { ChartTile, REL_WINDOWS } from '../charts/ChartTile';
import { SourcePicker } from '../charts/SourcePicker';
import { SORTS, TILE_COUNTS, clampPage, gridShape, pageCount, pageSlice, parseSource, sortItems } from '../charts/sources';
import { useSourceList } from '../charts/useSourceList';
import { copyText } from '../lib/clipboard';
import { cn } from '../lib/cn';
import { useChartPrefs } from '../lib/chartPrefs';
import { openLayerCount, useEscapeLayer } from '../lib/layers';
import { setNavList } from '../lib/navList';
import { useTabUrlState } from '../lib/tabUrlState';
import { formatTradingViewList } from '../lib/tradingview';
import { useShell } from '../shell/ShellContext';
import { isSymbol, useAsOf } from '../shell/urlState';
import type { Timeframe } from '../ui/Chart';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';

const DEFAULTS = { src: 'queue:all', syms: '', sort: 'source', n: '6', tf: 'D', rel: '3M', page: '1', focus: '', style: 'candles', sync: 'on' };
/** Typed lists are kept in the URL; cap what an "add symbol" converts into one. */
const MAX_TYPED = 300;

const seg = 'h-7 rounded border border-line bg-surface-2 px-1.5 text-xs text-fg focus:border-accent focus:outline-none';

function isTyping(el: EventTarget | null): boolean {
  const t = el as HTMLElement | null;
  return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
}

export default function ChartsRoute() {
  const shell = useShell();
  const qc = useQueryClient();
  const [asOf] = useAsOf();
  const [state, setState, active] = useTabUrlState('/charts', DEFAULTS);
  const [copied, setCopied] = useState<string | null>(null);
  const [prefs, setPrefs] = useChartPrefs();

  // "Open in Charts" from other tabs sends ?syms= without a source: show that list.
  useEffect(() => {
    if (active && state.syms && state.src !== 'list') setState({ src: 'list', page: null });
  }, [active, state.syms, state.src, setState]);

  const syms = useMemo(
    () =>
      state.syms
        .split(',')
        .map((s) => s.trim().toUpperCase())
        .filter(isSymbol),
    [state.syms],
  );
  const parsed = parseSource(state.src) ?? parseSource(DEFAULTS.src);
  const presets = useApiQuery('screener/presets', {}, { staleTime: Infinity, enabled: parsed?.kind === 'screener' });
  const presetLabel = useCallback((id: string) => presets.data?.rows.find((p) => p.id === id)?.label, [presets.data]);
  const list = useSourceList(parsed, { watchlist: shell.watchlist, syms, presetLabel });

  const items = useMemo(() => sortItems(list.items, state.sort), [list.items, state.sort]);
  const perPage = (TILE_COUNTS as readonly number[]).includes(Number(state.n)) ? Number(state.n) : 6;
  const priceStyle = state.style === 'line' ? 'line' : 'candles';
  const syncRange = state.sync !== 'off';
  const [centerKey, setCenterKey] = useState(0);
  const [addText, setAddText] = useState('');
  const pages = pageCount(items.length, perPage);
  const page = clampPage(Number(state.page) - 1, items.length, perPage);
  const visible = useMemo(() => pageSlice(items, page, perPage), [items, page, perPage]);
  const tf = (['D', 'W', 'M'].includes(state.tf) ? state.tf : 'D') as Timeframe;
  const rel = (REL_WINDOWS.some((w) => w.id === state.rel) ? state.rel : '3M') as (typeof REL_WINDOWS)[number]['id'];
  const focus = state.focus && items.some((i) => i.symbol === state.focus) ? state.focus : '';
  const shape = gridShape(focus ? 1 : visible.length || perPage);

  const goPage = useCallback(
    (p: number) => setState({ page: String(clampPage(p, items.length, perPage) + 1) }),
    [setState, items.length, perPage],
  );

  // Prefetch the next page's bars + RS so paging feels instant (shared cache with Stock 360).
  useEffect(() => {
    if (!active) return;
    const next = pageSlice(items, page + 1, perPage);
    if (page + 1 >= pages) return;
    for (const it of next) {
      const params = { sym: it.symbol };
      qc.prefetchQuery({
        queryKey: apiQueryKey('stock/{sym}/bars', params, { tf }, asOf),
        queryFn: ({ signal }) => apiGet('stock/{sym}/bars', { params, query: { tf, ...(asOf ? { as_of: asOf } : {}) } }, { signal }),
        staleTime: 5 * 60_000,
      });
    }
  }, [active, items, page, perPage, pages, tf, asOf, qc]);

  // J / K (and [ / ]) page through the list; Esc leaves the expanded tile.
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || isTyping(e.target) || openLayerCount() > 0) return;
      if (e.key === 'j' || e.key === 'J' || e.key === ']') {
        e.preventDefault();
        goPage(page + 1);
      } else if (e.key === 'k' || e.key === 'K' || e.key === '[') {
        e.preventDefault();
        goPage(page - 1);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, goPage, page]);
  useEscapeLayer(active && !!focus, () => setState({ focus: null }), { modal: false });

  const copyTv = async () => {
    const { text, count } = formatTradingViewList([{ title: list.label, symbols: items.map((i) => i.symbol) }]);
    const ok = await copyText(text);
    setCopied(ok ? `Copied ${count}` : 'Copy failed');
    window.setTimeout(() => setCopied(null), 2500);
  };

  const editable = parsed?.kind === 'list';
  const addSymbol = () => {
    const sym = addText.trim().toUpperCase();
    if (!isSymbol(sym)) return;
    // A long source (e.g. all queues) becomes an editable list of the page on screen, never a silently cut list.
    const base = editable ? syms : items.length <= MAX_TYPED ? items.map((i) => i.symbol) : visible.map((i) => i.symbol);
    const next = [...base.filter((s) => s !== sym), sym];
    setState({ src: 'list', syms: next.join(','), page: String(pageCount(next.length, perPage)), focus: null });
    setAddText('');
  };
  const removeSymbol = (sym: string) => {
    const next = syms.filter((s) => s !== sym);
    setState({ syms: next.join(',') || null, focus: null });
  };

  const first = items.length ? page * perPage + 1 : 0;
  const lastN = Math.min(items.length, (page + 1) * perPage);
  const tiles = focus ? items.filter((i) => i.symbol === focus) : visible;
  const tileSyms = useMemo(() => tiles.map((t) => t.symbol), [tiles]);
  const sctx = useStockContext(tileSyms);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line bg-surface px-3 py-1.5">
        <SourcePicker
          value={state.src}
          label={list.label}
          count={list.loading ? null : items.length}
          watchCount={shell.watchlist.length}
          onChange={(src) => setState({ src, page: null, focus: null, syms: src === 'list' ? state.syms : null })}
        />
        <select aria-label="Sort" className={seg} value={state.sort} onChange={(e) => setState({ sort: e.target.value, page: null })}>
          {SORTS.map((s) => (
            <option key={s.id} value={s.id}>
              Sort: {s.label}
            </option>
          ))}
        </select>
        <div className="flex overflow-hidden rounded border border-line" role="group" aria-label="Tiles per page">
          {TILE_COUNTS.map((n) => (
            <button
              key={n}
              type="button"
              aria-pressed={perPage === n}
              onClick={() => setState({ n: String(n), page: String(Math.floor((page * perPage) / n) + 1) })}
              className={cn('px-2 py-1 text-xs', perPage === n ? 'bg-accent/20 text-accent' : 'text-fg-3 hover:bg-surface-3 hover:text-fg')}
            >
              {n}
            </button>
          ))}
        </div>
        <div className="flex overflow-hidden rounded border border-line" role="group" aria-label="Timeframe">
          {(['D', 'W', 'M'] as const).map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={tf === t}
              onClick={() => setState({ tf: t })}
              className={cn(
                'px-2 py-1 font-mono text-xs',
                tf === t ? 'bg-accent/20 text-accent' : 'text-fg-3 hover:bg-surface-3 hover:text-fg',
              )}
            >
              {t}
            </button>
          ))}
        </div>
        <button
          type="button"
          aria-pressed={prefs.darvas}
          onClick={() => setPrefs({ darvas: !prefs.darvas })}
          title="Shade historical Darvas boxes (same box as the Darvas Squeeze queue) with breakout / breakdown markers"
          className={cn(
            'rounded border border-line px-2 py-1 text-xs',
            prefs.darvas ? 'bg-accent/20 text-accent' : 'text-fg-3 hover:bg-surface-3 hover:text-fg',
          )}
        >
          Darvas boxes
        </button>
        <div className="flex overflow-hidden rounded border border-line" role="group" aria-label="Price style">
          {(['candles', 'line'] as const).map((st) => (
            <button
              key={st}
              type="button"
              aria-pressed={priceStyle === st}
              onClick={() => setState({ style: st === 'candles' ? null : st })}
              title={st === 'candles' ? 'Candlesticks on every tile' : 'Close line on every tile (TradingView line style)'}
              className={cn('px-2 py-1 text-xs', priceStyle === st ? 'bg-accent/20 text-accent' : 'text-fg-3 hover:bg-surface-3 hover:text-fg')}
            >
              {st === 'candles' ? 'Candles' : 'Line'}
            </button>
          ))}
        </div>
        <button
          type="button"
          aria-pressed={syncRange}
          onClick={() => setState({ sync: syncRange ? 'off' : null })}
          title="Sync pan / zoom across tiles by date (crosshair is always synced)"
          className={cn('rounded border border-line px-2 py-1 text-xs', syncRange ? 'bg-accent/20 text-accent' : 'text-fg-3 hover:bg-surface-3 hover:text-fg')}
        >
          Sync {syncRange ? 'on' : 'off'}
        </button>
        <button
          type="button"
          onClick={() => setCenterKey((k) => k + 1)}
          title="Re-center every tile on the latest bars"
          className="inline-flex items-center gap-1 rounded border border-line px-2 py-1 text-xs text-fg-3 hover:bg-surface-3 hover:text-fg"
        >
          <Crosshair className="h-3 w-3" /> Center
        </button>
        <form
          className="flex items-center"
          onSubmit={(e) => {
            e.preventDefault();
            addSymbol();
          }}
        >
          <input
            value={addText}
            onChange={(e) => setAddText(e.target.value)}
            placeholder="Add symbol"
            aria-label="Add a symbol to this list"
            title={editable ? 'Add a symbol to this list' : `Turns the current list (or, above ${MAX_TYPED} names, the page on screen) into an editable list and adds the symbol`}
            className="h-7 w-24 rounded-l border border-line bg-surface-2 px-1.5 text-xs uppercase text-fg placeholder:normal-case placeholder:text-fg-3 focus:border-accent focus:outline-none"
          />
          <button type="submit" aria-label="Add symbol" className="h-7 rounded-r border border-l-0 border-line px-1.5 text-fg-3 hover:bg-surface-3 hover:text-fg">
            <Plus className="h-3 w-3" />
          </button>
        </form>
        <label
          className="flex items-center gap-1 text-2xs text-fg-3"
          title="Window for the stock's return minus the NIFTY MidSml 400 return shown on each tile"
        >
          vs MidSml400
          <select aria-label="Relative performance window" className={seg} value={rel} onChange={(e) => setState({ rel: e.target.value })}>
            {REL_WINDOWS.map((w) => (
              <option key={w.id} value={w.id}>
                {w.id}
              </option>
            ))}
          </select>
        </label>
        <div className="ml-auto flex items-center gap-2 text-xs">
          {copied && <span className="text-2xs text-fg-3">{copied}</span>}
          <button
            type="button"
            onClick={() => void copyTv()}
            disabled={!items.length}
            className="flex items-center gap-1 rounded border border-line px-2 py-1 text-fg-2 hover:text-fg disabled:opacity-40"
            title="Copy the whole list (current sort) as a TradingView watchlist"
          >
            <Copy className="h-3 w-3" /> TradingView
          </button>
          <button
            type="button"
            onClick={() => goPage(page - 1)}
            disabled={page === 0 || !!focus}
            aria-label="Previous page (K)"
            className="rounded border border-line p-1 text-fg-2 hover:text-fg disabled:opacity-40"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <span className="num whitespace-nowrap text-fg-2" aria-live="polite">
            {items.length ? (
              <>
                {first}–{lastN} of {items.length} · page {page + 1}/{pages}
              </>
            ) : (
              '0 of 0'
            )}
          </span>
          <button
            type="button"
            onClick={() => goPage(page + 1)}
            disabled={page + 1 >= pages || !!focus}
            aria-label="Next page (J)"
            className="rounded border border-line p-1 text-fg-2 hover:text-fg disabled:opacity-40"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div className="shrink-0 px-1.5 pt-1.5">
        <ChartsGlance
          label={list.label}
          items={items}
          total={list.total}
          asOf={list.asOf}
          partialReason={list.status === 'partial' ? list.reason : null}
          note={list.note}
          page={page}
          pages={pages}
          loading={list.loading}
        />
      </div>
      <div className="min-h-0 flex-1 p-1.5">
        {list.error ? (
          <ErrorState error={list.error} onRetry={list.refetch} />
        ) : list.loading ? (
          <div
            className="grid h-full gap-1.5"
            style={{
              gridTemplateColumns: `repeat(${gridShape(perPage).cols}, minmax(0, 1fr))`,
              gridTemplateRows: `repeat(${gridShape(perPage).rows}, minmax(0, 1fr))`,
            }}
          >
            {Array.from({ length: perPage }, (_, i) => (
              <div key={i} className="animate-pulse rounded border border-line bg-surface" />
            ))}
          </div>
        ) : list.status === 'unavailable' ? (
          <EmptyState title="Source not available yet" detail={list.reason ?? undefined} />
        ) : items.length === 0 ? (
          <EmptyState title="No stocks in this source" detail={list.note ?? `Nothing in ${list.label} on this date.`} />
        ) : (
          <div
            className="grid h-full gap-1.5"
            style={{
              gridTemplateColumns: `repeat(${shape.cols}, minmax(0, 1fr))`,
              gridTemplateRows: `repeat(${shape.rows}, minmax(0, 1fr))`,
            }}
          >
            {tiles.map((it) => (
              <ChartTile
                key={`${it.symbol}-${tf}-${centerKey}`}
                item={it}
                timeframe={tf}
                relWindow={rel}
                syncGroup="charts-grid"
                compact={!focus && perPage >= 8}
                volume={!!focus || perPage <= 4}
                active={shell.symbol === it.symbol}
                expanded={!!focus}
                onInspect={(s) => {
                  setNavList(items.map((i) => i.symbol));
                  shell.openSymbol(s);
                }}
                onOpenBig={(s) => {
                  setNavList(items.map((i) => i.symbol));
                  shell.openBigChart(s);
                }}
                onToggleExpand={(s) => setState({ focus: focus ? null : s })}
                context={sctx.map.get(it.symbol.toUpperCase())}
                priceStyle={priceStyle}
                syncRange={syncRange && !focus}
                onRemove={editable ? removeSymbol : undefined}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
