/**
 * Symbol box (HarkPro/09-tab-charts.md §3): type a symbol or company name. Enter opens it,
 * Shift+Enter adds it to the current list. "/" focuses the box (global shortcut, data-filter-input).
 */
import { Search } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useApiQuery } from '../api/query';
import { cn } from '../lib/cn';
import { fmtCr } from '../lib/fmt';
import { isSymbol } from '../shell/urlState';

export interface SymbolSearchProps {
  onOpen: (sym: string) => void;
  onAdd: (sym: string) => void;
}

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = window.setTimeout(() => setD(v), ms);
    return () => window.clearTimeout(t);
  }, [v, ms]);
  return d;
}

export function SymbolSearch({ onOpen, onAdd }: SymbolSearchProps) {
  const [text, setText] = useState('');
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const q = useDebounced(text.trim(), 150);
  const res = useApiQuery('charts/search', { query: { q: q || '_', limit: 10 } }, { enabled: q.length >= 1, asOf: false });
  const rows = q ? (res.data?.rows ?? []) : [];

  const choose = (add: boolean) => {
    const pick = rows[hi]?.symbol ?? text.trim().toUpperCase();
    if (!pick || !isSymbol(pick)) return;
    if (add) onAdd(pick);
    else onOpen(pick);
    setText('');
    setOpen(false);
    inputRef.current?.blur();
  };

  return (
    <div className="relative">
      <div className="flex h-7 items-center gap-1 rounded border border-line-strong bg-surface-2 px-1.5 focus-within:border-accent">
        <Search className="h-3 w-3 text-fg-3" aria-hidden />
        <input
          ref={inputRef}
          data-filter-input
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            setHi(0);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              choose(e.shiftKey);
            } else if (e.key === 'ArrowDown') {
              e.preventDefault();
              setHi((h) => Math.min(h + 1, Math.max(0, rows.length - 1)));
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              setHi((h) => Math.max(0, h - 1));
            } else if (e.key === 'Escape') {
              setText('');
              inputRef.current?.blur();
            }
          }}
          placeholder="Symbol or name  /"
          aria-label="Open a symbol (Enter) or add it to the list (Shift+Enter)"
          title="Enter opens · Shift+Enter adds to the list · / focuses"
          className="w-40 bg-transparent text-xs text-fg placeholder:text-fg-3 focus:outline-none"
        />
      </div>
      {open && rows.length > 0 && (
        <ul role="listbox" className="absolute left-0 top-full z-50 mt-1 w-80 overflow-hidden rounded-md border border-line-strong bg-surface-2 py-0.5 text-xs shadow-2xl">
          {rows.map((r, i) => (
            <li
              key={r.symbol ?? i}
              role="option"
              aria-selected={i === hi}
              onMouseDown={(e) => {
                e.preventDefault();
                setHi(i);
                if (r.symbol) {
                  onOpen(r.symbol);
                  setText('');
                  setOpen(false);
                }
              }}
              className={cn('flex cursor-pointer items-baseline gap-2 px-2 py-1', i === hi ? 'bg-accent/15' : 'hover:bg-surface-3')}
            >
              <span className="font-mono font-semibold text-fg">{r.symbol}</span>
              <span className="truncate text-fg-2">{r.security_name}</span>
              <span className="num ml-auto shrink-0 text-2xs text-fg-3">{fmtCr(r.market_cap_cr ?? null, 0)}</span>
            </li>
          ))}
          <li className="border-t border-line px-2 py-0.5 text-2xs text-fg-3">Enter opens · Shift+Enter adds to the list</li>
        </ul>
      )}
    </div>
  );
}
