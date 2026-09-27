/**
 * TradingView copy for every Deals list: "Copy to TradingView" copies the list as shown
 * (current sort, current filters), "Copy selected" only the ticked rows. Same formatter
 * as Desk / Screener (lib/tradingview): ###Section,NSE:SYM,NSE:SYM (dash -> underscore).
 */
import { Check, ClipboardCopy } from 'lucide-react';
import { useCallback, useState } from 'react';
import { copyText } from '../../lib/clipboard';
import { formatTradingViewList } from '../../lib/tradingview';
import type { DataTableColumn, RowData } from '../../ui/DataTable';

export function useSelection() {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = useCallback((sym: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      return next;
    });
  }, []);
  const setMany = useCallback((syms: readonly string[], on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const s of syms) {
        if (on) next.add(s);
        else next.delete(s);
      }
      return next;
    });
  }, []);
  const clear = useCallback(() => setSelected(new Set()), []);
  return { selected, toggle, setMany, clear };
}

/** Leading checkbox column; `visible` = symbols currently shown (header box ticks them all). */
export function selectColumn<T extends RowData>(
  getSymbol: (r: T) => string | null | undefined,
  sel: ReturnType<typeof useSelection>,
  visible: readonly string[],
): DataTableColumn<T> {
  const all = visible.length > 0 && visible.every((s) => sel.selected.has(s));
  return {
    id: 'sel',
    header: (
      <input
        type="checkbox"
        aria-label="Select all shown"
        checked={all}
        onClick={(e) => e.stopPropagation()}
        onChange={() => sel.setMany(visible, !all)}
      />
    ),
    accessor: (r) => {
      const s = getSymbol(r);
      return s ? (sel.selected.has(s) ? 1 : 0) : null;
    },
    width: 30,
    sortable: false,
    hideable: false,
    renderNull: true,
    cell: (_v, r) => {
      const s = getSymbol(r);
      if (!s) return null;
      return (
        <input
          type="checkbox"
          aria-label={`Select ${s}`}
          checked={sel.selected.has(s)}
          onClick={(e) => e.stopPropagation()}
          onChange={() => sel.toggle(s)}
        />
      );
    },
  };
}

export function TvCopyBar({ title, symbols, selected, onClear }: { title: string; symbols: readonly string[]; selected?: ReadonlySet<string>; onClear?: () => void }) {
  const [msg, setMsg] = useState<string | null>(null);
  const copy = async (list: readonly string[], label: string) => {
    const { text, count } = formatTradingViewList([{ title, symbols: list }]);
    const ok = count > 0 && (await copyText(text));
    setMsg(ok ? `Copied ${count} ${label}` : 'Copy failed');
    window.setTimeout(() => setMsg(null), 2500);
  };
  const sel = selected ? symbols.filter((s) => selected.has(s)) : [];
  const extra = selected ? [...selected].filter((s) => !symbols.includes(s)) : [];
  const selList = [...sel, ...extra];
  return (
    <span className="inline-flex items-center gap-1.5 text-2xs">
      <button
        type="button"
        onClick={() => void copy(symbols, 'symbols')}
        disabled={!symbols.length}
        title={`Copy the list as shown in TradingView watchlist format (###${title},NSE:SYM,…)`}
        className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3 disabled:opacity-50"
      >
        <ClipboardCopy className="h-3.5 w-3.5" /> Copy to TradingView ({symbols.length})
      </button>
      {selected && (
        <button
          type="button"
          onClick={() => void copy(selList, 'selected')}
          disabled={!selList.length}
          title="Copy only the ticked rows"
          className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3 disabled:opacity-50"
        >
          Copy selected ({selList.length})
        </button>
      )}
      {selected && selList.length > 0 && onClear && (
        <button type="button" onClick={onClear} className="text-fg-3 hover:text-fg hover:underline">
          clear
        </button>
      )}
      {msg && (
        <span role="status" className="inline-flex items-center gap-0.5 text-up">
          <Check className="h-3 w-3" /> {msg}
        </span>
      )}
    </span>
  );
}
