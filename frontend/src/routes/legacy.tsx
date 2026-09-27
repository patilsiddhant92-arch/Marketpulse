/**
 * Temporary bridge for the pre-rebuild workspaces (spec D6 "app always
 * shippable"). Each new tab route renders its legacy workspace inside
 * LegacyFrame until the rebuilt tab replaces it. Delete this file (and
 * src/components/) when the last tab migrates.
 */
import { useState, type ReactNode } from 'react';
import { useShell } from '../shell/ShellContext';
import { useAsOf, useUrlParam } from '../shell/urlState';
import { cn } from '../lib/cn';
import { fmtDate } from '../lib/fmt';

/** Props every legacy workspace accepts, wired to the new shell. */
export function useLegacyProps() {
  const shell = useShell();
  return {
    selectedSymbol: shell.symbol,
    onSelectSymbol: (sym: string) => shell.openSymbol(sym),
    onAddToBasket: (sym: string) => shell.toggleWatch(sym),
    onOpenMultiChart: (symbols?: string[]) => shell.openCharts(symbols && symbols.length ? symbols : shell.symbol ? [shell.symbol] : []),
  };
}

export interface LegacyView {
  id: string;
  label: string;
  render: () => ReactNode;
}

export interface LegacyFrameProps {
  /** Rebuild note, e.g. "Desk rebuild lands in step 6". */
  note?: string;
  /** Two legacy workspaces merged into one tab get a switcher (URL ?view=). */
  views?: LegacyView[];
  children?: ReactNode;
  className?: string;
}

export function LegacyFrame({ note, views, children, className }: LegacyFrameProps) {
  const [asOf] = useAsOf();
  const [viewParam, setView] = useUrlParam('view');
  const active = views?.find((v) => v.id === viewParam) ?? views?.[0];
  // Keep every visited legacy view mounted so switching back is instant.
  const [visited, setVisited] = useState<string[]>(active ? [active.id] : []);
  if (active && !visited.includes(active.id)) setVisited([...visited, active.id]); // adjust state during render

  return (
    <div className={cn('flex h-full min-h-0 flex-col', className)}>
      <div className="flex h-7 shrink-0 items-center gap-3 border-b border-line bg-surface px-3 text-2xs text-fg-3">
        <span className="rounded border border-line px-1.5 py-px font-semibold uppercase tracking-wide text-fg-3">Legacy view</span>
        {views && views.length > 1 && (
          <div className="flex items-center gap-1" role="tablist" aria-label="Legacy views">
            {views.map((v) => (
              <button
                key={v.id}
                type="button"
                role="tab"
                aria-selected={active?.id === v.id}
                onClick={() => setView(v.id)}
                className={cn('rounded px-2 py-0.5', active?.id === v.id ? 'bg-surface-3 text-fg' : 'hover:text-fg')}
              >
                {v.label}
              </button>
            ))}
          </div>
        )}
        {note && <span>{note}</span>}
        {asOf && (
          <span className="ml-auto text-violet">
            Shows the latest session — time travel ({fmtDate(asOf)}) does not apply to legacy views.
          </span>
        )}
      </div>
      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {views
          ? views
              .filter((v) => visited.includes(v.id) || v.id === active?.id)
              .map((v) => (
                <div key={v.id} className={cn('min-h-0 flex-1', v.id === active?.id ? 'flex' : 'hidden')}>
                  {v.render()}
                </div>
              ))
          : children}
      </div>
    </div>
  );
}
