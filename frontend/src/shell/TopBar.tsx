import { Command as CommandIcon, Star } from 'lucide-react';
import { NavLink } from 'react-router';
import { cn } from '../lib/cn';
import { FreshnessChip } from './FreshnessChip';
import { useShell } from './ShellContext';
import { TABS } from './tabs';
import { TimeTravel } from './TimeTravel';
import type { FreshnessInfo } from './useFreshness';
import { useGlobalSearch } from './urlState';

export function TopBar({ freshness }: { freshness: FreshnessInfo }) {
  const shell = useShell();
  const search = useGlobalSearch();
  return (
    <header className="flex h-topbar shrink-0 items-center gap-3 border-b border-line bg-surface-2 px-3">
      <div className="flex items-center gap-1.5 pr-1 text-sm font-bold tracking-tight">
        <span className="text-accent">Market</span>
        <span className="text-fg">Pulse</span>
      </div>

      <FreshnessChip info={freshness} />

      <nav aria-label="Tabs" className="flex h-full items-stretch">
        {TABS.map((t) => (
          <NavLink
            key={t.id}
            to={{ pathname: t.path, search }}
            title={`${t.hint} (${t.key})`}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-1.5 border-b-2 px-3 text-xs font-medium transition-colors',
                isActive ? 'border-accent text-fg' : 'border-transparent text-fg-3 hover:text-fg',
              )
            }
          >
            <span className="font-mono text-2xs text-fg-3">{t.key}</span>
            {t.label}
          </NavLink>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-2">
        <TimeTravel latestSession={freshness.latestSession} />
        <button
          type="button"
          onClick={() => shell.openCharts(shell.watchlist)}
          disabled={shell.watchlist.length === 0}
          className="flex h-7 items-center gap-1 rounded border border-line bg-surface-2 px-2 text-xs text-fg-2 enabled:hover:border-line-strong disabled:opacity-60"
          title="Watchlist (W toggles the selected symbol) — click to open in Charts"
        >
          <Star className="h-3.5 w-3.5 text-accent" aria-hidden />
          <span className="num">{shell.watchlist.length}</span>
          <span className="sr-only">symbols in watchlist</span>
        </button>
        <button
          type="button"
          onClick={() => shell.setPaletteOpen(true)}
          className="flex h-7 items-center gap-1.5 rounded border border-line bg-surface-2 px-2 text-xs text-fg-3 hover:border-line-strong hover:text-fg"
          aria-label="Open command palette"
        >
          <CommandIcon className="h-3.5 w-3.5" aria-hidden />
          <kbd className="font-mono text-2xs">Ctrl K</kbd>
        </button>
      </div>
    </header>
  );
}
