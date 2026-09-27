/**
 * Global keys (spec 7.1): Ctrl/Cmd+K palette · 1-6 tabs · W watchlist ·
 * T TradingView · C copy · F big chart · / focus filter. J/K/Enter live in DataTable
 * (focused table); Escape is handled by the layer stack (lib/layers.ts).
 */
import { useEffect, useRef } from 'react';
import { copyText } from '../lib/clipboard';
import { openLayerCount } from '../lib/layers';
import { toTradingViewSymbol, tradingViewChartUrl } from '../lib/tradingview';
import { useShell } from './ShellContext';
import { TABS } from './tabs';

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

export function useShortcuts(): void {
  const shell = useShell();
  const ref = useRef(shell);
  useEffect(() => {
    ref.current = shell;
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const s = ref.current;
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        s.setPaletteOpen(!s.paletteOpen);
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
      if (isTyping(e.target) || openLayerCount() > 0) return;

      const tab = TABS.find((t) => t.key === e.key);
      if (tab) {
        e.preventDefault();
        s.goTab(tab.id);
        return;
      }
      const sym = s.symbol;
      switch (e.key) {
        case 'f':
        case 'F': {
          const m = /^\/stock\/([^/?#]+)/.exec(window.location.pathname);
          const target = m ? decodeURIComponent(m[1]) : sym;
          if (target) {
            e.preventDefault();
            s.openBigChart(target);
          }
          break;
        }
        case 'w':
        case 'W':
          if (sym) s.toggleWatch(sym);
          break;
        case 't':
        case 'T':
          if (sym) window.open(tradingViewChartUrl(sym), '_blank', 'noopener');
          break;
        case 'c':
        case 'C':
          if (sym) void copyText(toTradingViewSymbol(sym));
          break;
        case '/': {
          const input = document.querySelector<HTMLElement>('section[data-active="true"] [data-filter-input]');
          if (input) {
            e.preventDefault();
            input.focus();
          }
          break;
        }
        default:
          return;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
