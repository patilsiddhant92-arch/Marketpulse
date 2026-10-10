/**
 * Charts (HarkPro/09-tab-charts.md, round 1): a TradingView-style charting tool.
 *
 * Toolbar: symbol search (Enter opens, Shift+Enter adds) · source picker (Desk queues, Screener,
 * Groups, Deals, Research, Watchlist, Peers of the stock, pasted TradingView text) · layout
 * 1 / 2 / 4 / 6 / 9 · D W M · Candles / Line / Volume candles · Indicators ▾ (global settings) ·
 * Draw (H horizontal / T trend line) · Peers together · Copy to TradingView.
 *
 * Layout 1 = the main chart + the list rail (J / K move through the list; the chart keeps its zoom
 * and indicators). Layouts 2-9 = a date-synced grid (J / K page). Stock 360 is the chart's side
 * panel (I, or a click on the symbol). Every chart reads the same stored chart settings.
 */
import { useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Copy, Crosshair, Users } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiGet } from '../api/client';
import { apiQueryKey, useApiQuery } from '../api/query';
import { DrawMenu, IndicatorsMenu, StyleToggle, segBtn } from '../charts/ChartControls';
import { ChartsGlance } from '../charts/ChartsGlance';
import { ChartTile, REL_WINDOWS } from '../charts/ChartTile';
import type { DrawTool } from '../charts/drawings';
import { ListRail } from '../charts/ListRail';
import { PRO_BARS, ProChart } from '../charts/ProChart';
import { SourcePicker } from '../charts/SourcePicker';
import { SymbolSearch } from '../charts/SymbolSearch';
import {
  LAYOUTS,
  SORTS,
  TILE_COUNTS,
  clampPage,
  fromSymbol,
  gridShape,
  pageCount,
  pageSlice,
  parseSource,
  sortItems,
} from '../charts/sources';
import { useSourceList } from '../charts/useSourceList';
import { useStockContext } from '../context/stockContext';
import { useChartPrefs } from '../lib/chartPrefs';
import { copyText } from '../lib/clipboard';
import { cn } from '../lib/cn';
import { openLayerCount, useEscapeLayer } from '../lib/layers';
import { setNavList, stepSymbol } from '../lib/navList';
import { useTabUrlState } from '../lib/tabUrlState';
import { formatTradingViewList } from '../lib/tradingview';
import { useShell } from '../shell/ShellContext';
import { isSymbol, useAsOf } from '../shell/urlState';
import { Stock360Sidecar } from '../stock360/Stock360';
import type { Timeframe } from '../ui/Chart';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';

const DEFAULTS = {
  src: 'queue:all',
  syms: '',
  sort: 'source',
  n: '1',
  tf: 'D',
  rel: '3M',
  page: '1',
  focus: '',
  sync: 'on',
  /** Symbol on the main chart (layout 1) / of the side panel. */
  cur: '',
  /** Stock 360 side panel open ('1'). */
  panel: '',
};
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
  const [prefs] = useChartPrefs();
  const [tool, setTool] = useState<DrawTool>('none');

  // "Open in Charts" from other tabs sends ?syms= without a source: show that list.
  useEffect(() => {
    if (active && state.syms && state.src !== 'list') setState({ src: 'list', page: null, cur: null });
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
  const layoutN = (TILE_COUNTS as readonly number[]).includes(Number(state.n)) ? Number(state.n) : 1;
  const single = layoutN === 1;
  const perPage = single ? 6 : layoutN;
  const syncRange = state.sync !== 'off';
  const [centerKey, setCenterKey] = useState(0);
  const pages = pageCount(items.length, perPage);
  const page = clampPage(Number(state.page) - 1, items.length, perPage);
  const visible = useMemo(() => pageSlice(items, page, perPage), [items, page, perPage]);
  const tf = (['D', 'W', 'M'].includes(state.tf) ? state.tf : 'D') as Timeframe;
  const rel = (REL_WINDOWS.some((w) => w.id === state.rel) ? state.rel : '3M') as (typeof REL_WINDOWS)[number]['id'];
  const focus = state.focus && items.some((i) => i.symbol === state.focus) ? state.focus : '';
  const shape = gridShape(focus ? 1 : visible.length || perPage);
  const itemSyms = useMemo(() => items.map((i) => i.symbol), [items]);

  // Main-chart symbol: the URL's (may be a one-off typed symbol outside the list), else the list's first.
  const cur = state.cur && isSymbol(state.cur) ? state.cur : (items[0]?.symbol ?? '');
  const curItem = useMemo(() => items.find((i) => i.symbol === cur) ?? (cur ? fromSymbol(cur) : undefined), [items, cur]);
  const panelOpen = state.panel === '1' && !!cur;
  const curPos = itemSyms.indexOf(cur);

  const goPage = useCallback(
    (p: number) => setState({ page: String(clampPage(p, items.length, perPage) + 1) }),
    [setState, items.length, perPage],
  );
  const openSym = useCallback((sym: string, extra: Record<string, string | null> = {}) => setState({ cur: sym, ...extra }), [setState]);
  const step = useCallback(
    (dir: 1 | -1) => {
      const next = stepSymbol(itemSyms, cur || null, dir);
      if (next && next !== cur) openSym(next);
    },
    [itemSyms, cur, openSym],
  );

  // Prefetch: the next page's bars (grid) or the next / previous symbol (main chart).
  useEffect(() => {
    if (!active) return;
    const prefetch = (sym: string, limit?: number) => {
      const params = { sym };
      const query = limit ? { tf, limit } : { tf };
      qc.prefetchQuery({
        queryKey: apiQueryKey('stock/{sym}/bars', params, query, asOf),
        queryFn: ({ signal }) => apiGet('stock/{sym}/bars', { params, query: { ...query, ...(asOf ? { as_of: asOf } : {}) } }, { signal }),
        staleTime: 5 * 60_000,
      });
    };
    if (single) {
      for (const d of [1, -1] as const) {
        const n = stepSymbol(itemSyms, cur || null, d);
        if (n && n !== cur) prefetch(n, PRO_BARS[tf]);
      }
      return;
    }
    if (page + 1 >= pages) return;
    for (const it of pageSlice(items, page + 1, perPage)) prefetch(it.symbol);
  }, [active, single, items, itemSyms, cur, page, perPage, pages, tf, asOf, qc]);

  // Keys (capture phase, so the Charts meaning wins over the global T / M / W keys on this tab).
  const keyRef = useRef({ single, step, goPage, page, cur, items: itemSyms });
  useEffect(() => {
    keyRef.current = { single, step, goPage, page, cur, items: itemSyms };
  });
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || isTyping(e.target) || openLayerCount() > 0) return;
      const k = keyRef.current;
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      let handled = true;
      if (key === 'j' || key === ']' || (k.single && key === 'ArrowDown')) {
        if (k.single) k.step(1);
        else k.goPage(k.page + 1);
      } else if (key === 'k' || key === '[' || (k.single && key === 'ArrowUp')) {
        if (k.single) k.step(-1);
        else k.goPage(k.page - 1);
      } else if (key === 's' && k.cur) shell.toggleWatch(k.cur);
      else if (key === 'i' && k.cur) setState({ panel: state.panel === '1' ? null : '1' });
      else if (key === 'd' || key === 'w' || key === 'm') setState({ tf: key === 'd' ? null : key.toUpperCase() });
      else if (key === 'h' && k.single) setTool((t) => (t === 'hline' ? 'none' : 'hline'));
      else if (key === 't' && k.single) setTool((t) => (t === 'trend' ? 'none' : 'trend'));
      else if (key === 'f' && k.cur) {
        setNavList(k.items);
        shell.openBigChart(k.cur);
      } else handled = false;
      if (handled) e.preventDefault();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [active, shell, setState, state.panel]);
  useEscapeLayer(active && tool !== 'none', () => setTool('none'), { modal: false });
  useEscapeLayer(active && !!focus, () => setState({ focus: null }), { modal: false });

  const copyTv = async () => {
    const { text, count } = formatTradingViewList([{ title: list.label, symbols: itemSyms }]);
    const ok = await copyText(text);
    setCopied(ok ? `Copied ${count}` : 'Copy failed');
    window.setTimeout(() => setCopied(null), 2500);
  };

  const editable = parsed?.kind === 'list';
  /** Add to the current list. A long source becomes an editable list of the page on screen, never a silently cut list. */
  const addSymbol = (sym: string) => {
    if (!isSymbol(sym)) return;
    const base = editable ? syms : items.length <= MAX_TYPED ? itemSyms : visible.map((i) => i.symbol);
    const next = [...base.filter((s) => s !== sym), sym];
    setState({ src: 'list', syms: next.join(','), page: String(pageCount(next.length, perPage)), focus: null, cur: sym });
  };
  const removeSymbol = (sym: string) => {
    const next = syms.filter((s) => s !== sym);
    setState({ syms: next.join(',') || null, focus: null, cur: cur === sym ? null : cur });
  };

  const first = items.length ? page * perPage + 1 : 0;
  const lastN = Math.min(items.length, (page + 1) * perPage);
  const tiles = focus ? items.filter((i) => i.symbol === focus) : visible;
  const tileSyms = useMemo(() => tiles.map((t) => t.symbol), [tiles]);
  const sctx = useStockContext(single ? [] : tileSyms);

  const body = list.error ? (
    <ErrorState error={list.error} onRetry={list.refetch} />
  ) : list.status === 'unavailable' && !cur ? (
    <EmptyState title="Source not available yet" detail={list.reason ?? undefined} />
  ) : single ? (
    cur ? (
      <ProChart
        key={cur}
        symbol={cur}
        item={curItem}
        tf={tf}
        onTimeframeChange={(t) => setState({ tf: t === 'D' ? null : t })}
        tool={tool}
        onToolDone={() => setTool('none')}
        onInfo={() => setState({ panel: panelOpen ? null : '1' })}
        infoOpen={panelOpen}
        position={curPos >= 0 ? `${curPos + 1} / ${items.length}` : 'not in list'}
        className="h-full"
      />
    ) : list.loading ? (
      <div className="h-full animate-pulse rounded border border-line bg-surface" />
    ) : (
      <EmptyState title="No stock to chart" detail={list.note ?? `Nothing in ${list.label}. Type a symbol above.`} />
    )
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
          active={cur === it.symbol}
          expanded={!!focus}
          onInspect={(s) => openSym(s, { panel: '1' })}
          onSymbol={(s) => openSym(s, { panel: '1' })}
          onOpenBig={(s) => {
            setNavList(itemSyms);
            shell.openBigChart(s);
          }}
          onToggleExpand={(s) => setState({ focus: focus ? null : s })}
          context={sctx.map.get(it.symbol.toUpperCase())}
          priceStyle={prefs.style}
          syncRange={syncRange && !focus}
          onRemove={editable ? removeSymbol : undefined}
        />
      ))}
    </div>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line bg-surface px-3 py-1.5">
        <SymbolSearch onOpen={(s) => openSym(s, { n: single ? null : '1' })} onAdd={addSymbol} />
        <SourcePicker
          value={state.src}
          label={list.label}
          count={list.loading ? null : items.length}
          watchCount={shell.watchlist.length}
          current={cur || null}
          onChange={(src) => setState({ src, page: null, focus: null, cur: null, syms: src === 'list' ? state.syms : null })}
          onPaste={(list2) => setState({ src: 'list', syms: list2.slice(0, MAX_TYPED).join(','), page: null, focus: null, cur: null })}
        />
        <select aria-label="Sort" className={seg} value={state.sort} onChange={(e) => setState({ sort: e.target.value, page: null })}>
          {SORTS.map((s) => (
            <option key={s.id} value={s.id}>
              Sort: {s.label}
            </option>
          ))}
        </select>
        <div className="flex overflow-hidden rounded border border-line" role="group" aria-label="Layout">
          {LAYOUTS.map((n) => (
            <button
              key={n}
              type="button"
              aria-pressed={layoutN === n}
              title={n === 1 ? 'Main chart + list rail (J / K through the list)' : `${n} charts, date-synced`}
              onClick={() =>
                setState({
                  n: n === 1 ? null : String(n),
                  // Land on the page that holds the current symbol.
                  page: n === 1 ? null : String(Math.floor(Math.max(0, curPos) / n) + 1),
                  focus: null,
                })
              }
              className={segBtn(layoutN === n)}
            >
              {n}
            </button>
          ))}
        </div>
        <div className="flex overflow-hidden rounded border border-line" role="group" aria-label="Timeframe">
          {(['D', 'W', 'M'] as const).map((t) => (
            <button key={t} type="button" aria-pressed={tf === t} onClick={() => setState({ tf: t === 'D' ? null : t })} className={cn(segBtn(tf === t), 'font-mono')}>
              {t}
            </button>
          ))}
        </div>
        <StyleToggle />
        <IndicatorsMenu />
        {single && <DrawMenu symbol={cur || null} tool={tool} onTool={setTool} />}
        {cur && (
          <button
            type="button"
            onClick={() => setState({ src: `peers:${cur}`, n: '6', page: null, focus: null, syms: null })}
            title={`Peers together: ${cur} and its strongest industry peers in a 6-chart grid`}
            className="flex h-7 items-center gap-1 rounded border border-line px-2 text-xs text-fg-2 hover:bg-surface-3 hover:text-fg"
          >
            <Users className="h-3 w-3" /> Peers
          </button>
        )}
        {!single && (
          <>
            <button
              type="button"
              aria-pressed={syncRange}
              onClick={() => setState({ sync: syncRange ? 'off' : null })}
              title="Sync pan / zoom across tiles by date (crosshair is always synced)"
              className={cn('rounded border border-line', segBtn(syncRange))}
            >
              Sync {syncRange ? 'on' : 'off'}
            </button>
            <button
              type="button"
              onClick={() => setCenterKey((k) => k + 1)}
              title="Re-center every tile on the latest bars"
              className="inline-flex h-7 items-center gap-1 rounded border border-line px-2 text-xs text-fg-3 hover:bg-surface-3 hover:text-fg"
            >
              <Crosshair className="h-3 w-3" /> Center
            </button>
            <label className="flex items-center gap-1 text-2xs text-fg-3" title="Window for the stock's return minus the NIFTY MidSml 400 return shown on each tile">
              vs MidSml400
              <select aria-label="Relative performance window" className={seg} value={rel} onChange={(e) => setState({ rel: e.target.value })}>
                {REL_WINDOWS.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.id}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
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
          {!single && (
            <>
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
            </>
          )}
        </div>
      </div>
      {!single && (
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
      )}
      <div className="flex min-h-0 flex-1">
        <div className={cn('min-h-0 min-w-0 flex-1', single ? '' : 'p-1.5')}>{body}</div>
        {single && (
          <ListRail
            label={list.label}
            items={items}
            current={cur || null}
            onPick={(s) => openSym(s)}
            onRemove={editable ? removeSymbol : undefined}
            loading={list.loading}
            className="w-56 shrink-0"
          />
        )}
        {panelOpen && (
          <aside className="w-[340px] shrink-0 border-l border-line bg-surface" aria-label={`Stock 360: ${cur}`}>
            <Stock360Sidecar symbol={cur} hideChart />
          </aside>
        )}
      </div>
    </div>
  );
}
