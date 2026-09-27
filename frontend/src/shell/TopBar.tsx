import { Activity, Command as CommandIcon, Star } from 'lucide-react';
import { NavLink } from 'react-router';
import { cn } from '../lib/cn';
import { EnvironmentStrip } from './environment';
import { FreshnessChip } from './FreshnessChip';
import { useShell } from './ShellContext';
import { TABS } from './tabs';
import { TimeTravel } from './TimeTravel';
import type { FreshnessInfo } from './useFreshness';
import { useGlobalSearch } from './urlState';

/** Shared look for the small top-bar controls. */
export const TOPBAR_CTL =
  'flex h-7 items-center gap-1.5 rounded border border-line bg-surface-2 px-2 text-xs transition-colors duration-fast hover:border-line-strong';

export function TopBar({ freshness }: { freshness: FreshnessInfo }) {
  const shell = useShell();
  const search = useGlobalSearch();
  return (
    <header className="relative flex h-topbar shrink-0 items-center gap-4 border-b border-line bg-gradient-to-b from-surface-2 to-surface px-3">
      <div className="flex shrink-0 items-center gap-2 pr-1">
        <span className="flex h-6 w-6 items-center justify-center rounded-[5px] bg-accent/15 text-accent ring-1 ring-inset ring-accent/30" aria-hidden>
          <Activity className="h-3.5 w-3.5" strokeWidth={2.25} />
        </span>
        <span className="text-[15px] font-semibold tracking-tight">
          <span className="text-fg">Market</span>
          <span className="text-accent">Pulse</span>
        </span>
      </div>

      <nav aria-label="Tabs" className="flex h-full items-stretch gap-0.5">
        {TABS.map((t) => (
          <NavLink
            key={t.id}
            to={{ pathname: t.path, search }}
            title={`${t.hint} (${t.key})`}
            className={({ isActive }) =>
              cn(
                'group relative flex items-center gap-1.5 px-3 text-[13px] font-medium transition-colors duration-fast',
                'after:absolute after:inset-x-2 after:bottom-0 after:h-[2px] after:rounded-t after:transition-colors after:duration-fast',
                isActive ? 'text-fg after:bg-accent' : 'text-fg-3 after:bg-transparent hover:text-fg-2 hover:after:bg-line-strong',
              )
            }
          >
            <span className="num rounded-[3px] border border-line/80 px-1 text-[10px] leading-[14px] text-fg-3 group-hover:border-line-strong">{t.key}</span>
            {t.label}
          </NavLink>
        ))}
      </nav>

      <div className="ml-auto flex min-w-0 items-center gap-2">
        <EnvironmentStrip />
        <span className="mx-0.5 h-5 w-px shrink-0 bg-line" aria-hidden />
        <FreshnessChip info={freshness} />
        <TimeTravel latestSession={freshness.latestSession} />
        <button
          type="button"
          onClick={() => shell.openCharts(shell.watchlist)}
          disabled={shell.watchlist.length === 0}
          className={cn(TOPBAR_CTL, 'text-fg-2 disabled:opacity-60 disabled:hover:border-line')}
          title="Watchlist (W toggles the selected symbol) — click to open in Charts"
        >
          <Star className="h-3.5 w-3.5 text-accent" aria-hidden />
          <span className="num">{shell.watchlist.length}</span>
          <span className="sr-only">symbols in watchlist</span>
        </button>
        <button
          type="button"
          onClick={() => shell.setPaletteOpen(true)}
          className={cn(TOPBAR_CTL, 'text-fg-3 hover:text-fg')}
          aria-label="Open command palette"
        >
          <CommandIcon className="h-3.5 w-3.5" aria-hidden />
          <kbd className="font-mono text-2xs">Ctrl K</kbd>
        </button>
      </div>
    </header>
  );
}
