/**
 * Ctrl+K command palette (cmdk): symbols, tabs, Setups presets, actions.
 * There is no symbol-list endpoint in v2, so any valid NSE symbol typed is
 * offered directly; watchlist and recent symbols are listed for recall.
 */
import { Command } from 'cmdk';
import { CornerDownLeft, History, LineChart, Search, SlidersHorizontal, Star } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useApiQuery } from '../api/query';
import { copyText } from '../lib/clipboard';
import { useEscapeLayer } from '../lib/layers';
import { formatTradingViewList } from '../lib/tradingview';
import { useShell } from './ShellContext';
import { TABS } from './tabs';
import { isSymbol, useAsOf, useGlobalSearch } from './urlState';

const itemCls =
  'flex h-8 cursor-pointer select-none items-center gap-2 rounded px-2 text-xs text-fg-2 data-[selected=true]:bg-accent/15 data-[selected=true]:text-fg';
const groupCls =
  '[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-fg-3';

export function CommandPalette() {
  const shell = useShell();
  const { paletteOpen: open, setPaletteOpen: setOpen } = shell;
  const navigate = useNavigate();
  const globalSearch = useGlobalSearch();
  const [asOf, setAsOf] = useAsOf();
  const [search, setSearch] = useState('');
  useEscapeLayer(open, () => setOpen(false));

  const presets = useApiQuery('screener/presets', {}, { enabled: open });
  const typed = search.trim().toUpperCase();
  const typedIsSymbol = isSymbol(typed) && typed.length >= 2;

  const close = () => {
    setOpen(false);
    setSearch('');
  };
  const run = (fn: () => void) => () => {
    fn();
    close();
  };

  const symbolsForRecall = [...new Set([...shell.watchlist, ...shell.recent])].filter((s) => s !== typed).slice(0, 12);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={(o) => (o ? setOpen(true) : close())}
      label="Command palette"
      shouldFilter
      loop
      overlayClassName="fixed inset-0 z-[60] bg-bg/70"
      contentClassName="fixed left-1/2 top-[12vh] z-[61] w-[560px] max-w-[92vw] -translate-x-1/2 overflow-hidden rounded-md border border-line-strong bg-surface shadow-2xl"
    >
      <div className="flex items-center gap-2 border-b border-line px-3">
        <Search className="h-4 w-4 text-fg-3" aria-hidden />
        <Command.Input
          value={search}
          onValueChange={setSearch}
          placeholder="Symbol, tab, preset or action…"
          className="h-11 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-3"
        />
        <kbd className="rounded border border-line px-1 font-mono text-2xs text-fg-3">Esc</kbd>
      </div>
      <Command.List className="max-h-[360px] overflow-auto p-1.5">
        <Command.Empty className="px-2 py-6 text-center text-xs text-fg-3">No matches. Type an NSE symbol to open it.</Command.Empty>

        {typedIsSymbol && (
          <Command.Group heading="Symbol" className={groupCls} forceMount>
            <Command.Item value={`sym-open ${typed}`} forceMount onSelect={run(() => shell.openSymbol(typed))} className={itemCls}>
              <CornerDownLeft className="h-3.5 w-3.5 text-accent" aria-hidden />
              Open <span className="font-mono text-fg">{typed}</span> in Stock 360 sidecar
            </Command.Item>
            <Command.Item value={`sym-page ${typed}`} forceMount onSelect={run(() => shell.openStockPage(typed))} className={itemCls}>
              <LineChart className="h-3.5 w-3.5 text-fg-3" aria-hidden />
              Open <span className="font-mono text-fg">{typed}</span> full page
            </Command.Item>
          </Command.Group>
        )}

        {symbolsForRecall.length > 0 && (
          <Command.Group heading="Watchlist & recent" className={groupCls}>
            {symbolsForRecall.map((s) => (
              <Command.Item key={s} value={`recall ${s}`} keywords={[s]} onSelect={run(() => shell.openSymbol(s))} className={itemCls}>
                {shell.isWatched(s) ? (
                  <Star className="h-3.5 w-3.5 text-accent" aria-hidden />
                ) : (
                  <History className="h-3.5 w-3.5 text-fg-3" aria-hidden />
                )}
                <span className="font-mono text-fg">{s}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}

        <Command.Group heading="Tabs" className={groupCls}>
          {TABS.map((t) => (
            <Command.Item
              key={t.id}
              value={`tab ${t.label}`}
              keywords={[t.hint]}
              onSelect={run(() => navigate(`${t.path}${globalSearch}`))}
              className={itemCls}
            >
              <kbd className="w-4 rounded border border-line text-center font-mono text-2xs text-fg-3">{t.key}</kbd>
              <span className="text-fg">{t.label}</span>
              <span className="text-fg-3">{t.hint}</span>
            </Command.Item>
          ))}
        </Command.Group>

        {(presets.data?.rows.length ?? 0) > 0 && (
          <Command.Group heading="Setups presets" className={groupCls}>
            {presets.data!.rows.map((p) => (
              <Command.Item
                key={p.id}
                value={`preset ${p.label}`}
                keywords={[p.id, p.description]}
                onSelect={run(() => {
                  const sp = new URLSearchParams(globalSearch);
                  sp.set('preset', p.id);
                  navigate(`/setups?${sp.toString()}`);
                })}
                className={itemCls}
              >
                <SlidersHorizontal className="h-3.5 w-3.5 text-fg-3" aria-hidden />
                <span className={p.available ? 'text-fg' : 'text-fg-3'}>{p.label}</span>
                {p.kind === 'lab' && <span className="text-2xs text-violet">lab</span>}
                {!p.available && <span className="text-2xs text-fg-3">unavailable</span>}
              </Command.Item>
            ))}
          </Command.Group>
        )}

        <Command.Group heading="Actions" className={groupCls}>
          {asOf && (
            <Command.Item value="action latest session" onSelect={run(() => setAsOf(null))} className={itemCls}>
              Back to latest session
            </Command.Item>
          )}
          {shell.watchlist.length > 0 && (
            <Command.Item
              value="action copy watchlist tradingview"
              onSelect={run(() => void copyText(formatTradingViewList([{ symbols: shell.watchlist }]).text))}
              className={itemCls}
            >
              Copy watchlist for TradingView ({shell.watchlist.length})
            </Command.Item>
          )}
          {shell.watchlist.length > 0 && (
            <Command.Item
              value="action open watchlist in charts"
              onSelect={run(() => shell.openCharts(shell.watchlist))}
              className={itemCls}
            >
              Open watchlist in Charts
            </Command.Item>
          )}
          <Command.Item value="action breadth history legacy" onSelect={run(() => shell.setBreadthOpen(true))} className={itemCls}>
            180-session breadth history (legacy)
          </Command.Item>
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
