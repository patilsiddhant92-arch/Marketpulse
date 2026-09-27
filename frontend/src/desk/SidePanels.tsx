import { GroupHealthChip, groupRowContext } from '../context/GroupContext';
import { useGroupNav } from '../today/parts';
import { X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { isUnavailable } from '../api/client';
import { useApiQuery } from '../api/query';
import type { DeskWatchRow, DiffRow } from '../api/types';
import { copyText } from '../lib/clipboard';
import { cn } from '../lib/cn';
import { fmtDateShort, fmtNum, fmtSigned, fmtSignedPct } from '../lib/fmt';
import { formatTradingViewList } from '../lib/tradingview';
import { useShell } from '../shell/ShellContext';
import { Chip } from '../ui/Chip';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { Panel } from '../ui/Panel';
import { Skeleton, SkeletonRows } from '../ui/Skeleton';
import { ZoneValue } from '../ui/ZoneValue';
import { QUEUES, groupDiff, leadingGroups } from './deskModel';

const QUEUE_SHORT: Record<string, string> = Object.fromEntries(QUEUES.map((q) => [q.id, q.short]));

function SymChip({ r, tone }: { r: DiffRow; tone: 'accent' | 'neutral' }) {
  const shell = useShell();
  return (
    <button
      type="button"
      onClick={() => r.symbol && shell.openSymbol(r.symbol)}
      onDoubleClick={() => r.symbol && shell.openStockPage(r.symbol)}
      title={`${r.symbol} · ${r.industry ?? 'no industry'} · rank ${fmtNum(r.rs_percentile, 0)} · close ${fmtNum(r.close)}`}
      className={cn(
        'rounded border px-1.5 py-0.5 font-mono text-2xs hover:brightness-125',
        tone === 'accent' ? 'border-accent/20 bg-accent/[0.08] text-accent' : 'border-transparent text-fg-3 line-through decoration-fg-3/50',
        shell.symbol === r.symbol && 'ring-1 ring-accent',
      )}
    >
      {r.symbol}
    </button>
  );
}

/** What entered / left each queue since the previous session (desk/diff). */
export function DiffPanel({ className }: { className?: string }) {
  const q = useApiQuery('desk/diff', { query: { limit: 5000 } });
  const groups = useMemo(() => groupDiff(q.data?.rows ?? []), [q.data]);
  const prev = (q.data?.meta?.context as { previous_session?: string } | undefined)?.previous_session;
  return (
    <Panel title="New vs yesterday" meta={prev ? `vs ${fmtDateShort(prev)}` : undefined} className={className} bodyClassName="overflow-y-auto">
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />
      ) : q.isLoading ? (
        <SkeletonRows rows={4} label="Loading changes" />
      ) : isUnavailable(q.data) ? (
        <EmptyState compact title="No comparison" detail={q.data?.meta.reason ?? undefined} />
      ) : (
        <div className="divide-y divide-line">
          {QUEUES.map((qq) => {
            const g = groups[qq.id];
            return (
              <div key={qq.id} className="space-y-1.5 px-3 py-2">
                <div className="flex items-center gap-2 text-xs">
                  <span className="font-medium text-fg">{qq.label}</span>
                  <span className="num text-2xs text-accent">+{g.added.length}</span>
                  <span className="num text-2xs text-fg-3">−{g.dropped.length}</span>
                </div>
                {g.added.length === 0 && g.dropped.length === 0 ? (
                  <p className="text-2xs text-fg-3">No change.</p>
                ) : (
                  <>
                    {g.added.length > 0 && (
                      <div className="flex flex-wrap gap-1" aria-label={`${qq.label} new`}>
                        {g.added.map((r) => (
                          <SymChip key={`n${r.symbol}`} r={r} tone="accent" />
                        ))}
                      </div>
                    )}
                    {g.dropped.length > 0 && (
                      <div className="flex flex-wrap gap-1" aria-label={`${qq.label} dropped`}>
                        {g.dropped.map((r) => (
                          <SymChip key={`d${r.symbol}`} r={r} tone="neutral" />
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          })}
          <p className="px-3 py-1.5 text-2xs text-fg-3">Click opens Stock 360 · double-click the full page · struck-through = dropped.</p>
        </div>
      )}
    </Panel>
  );
}

function WatchRow({ r }: { r: DeskWatchRow }) {
  const shell = useShell();
  const sym = r.symbol ?? '';
  const active = shell.symbol === sym;
  return (
    <li
      className={cn('group flex cursor-pointer items-center gap-2 px-3 py-1 hover:bg-surface-2', active && 'bg-accent/10')}
      onClick={() => shell.openSymbol(sym)}
      onDoubleClick={() => shell.openStockPage(sym)}
    >
      <span className="w-24 truncate font-mono text-xs font-semibold text-fg" title={r.security_name ?? undefined}>
        {sym}
      </span>
      <span className={cn('num w-14 text-right text-xs', r.change_1d_pct == null ? 'text-fg-3' : r.change_1d_pct >= 0 ? 'text-up' : 'text-down')}>
        {fmtSignedPct(r.change_1d_pct, 1)}
      </span>
      <span className="num w-12 text-right text-xs" title="Strength rank · 5-session change">
        <ZoneValue metricKey="rs_percentile" value={r.rs_percentile} digits={0} />
        <span className="ml-0.5 text-2xs text-fg-3">{r.rs_delta_5 != null ? fmtSigned(r.rs_delta_5) : ''}</span>
      </span>
      <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
        {!r.has_data ? (
          <span className="text-2xs text-fg-3">no data on this date</span>
        ) : r.queues?.length ? (
          r.queues.map((q) => (
            <Chip key={q} tone="accent" title={q === r.primary_queue && r.distance_to_trigger_pct != null ? `${fmtSignedPct(r.distance_to_trigger_pct, 1)} to trigger, risk ${fmtNum(r.risk_pct, 1)}%` : undefined}>
              {QUEUE_SHORT[q] ?? q}
            </Chip>
          ))
        ) : (
          <span className="text-2xs text-fg-3">no setup</span>
        )}
        {r.results_within_10 && (
          <Chip tone="warn" title={`${r.next_event?.event_type ?? 'results'} ${fmtDateShort(r.next_event?.event_date)}`}>
            results
          </Chip>
        )}
      </span>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          shell.removeWatch(sym);
        }}
        className="rounded p-0.5 text-fg-3 opacity-0 hover:bg-surface-3 hover:text-fg group-hover:opacity-100 focus:opacity-100"
        aria-label={`Remove ${sym} from watchlist`}
      >
        <X className="h-3 w-3" />
      </button>
    </li>
  );
}

const SYNC_TEXT = { loading: 'syncing…', synced: 'saved', local: 'server unreachable — local only', error: 'last change not saved' } as const;

/** Watchlist with today's setup status (desk/watchlist). */
export function WatchlistPanel({ className }: { className?: string }) {
  const shell = useShell();
  const symbols = shell.watchlist.join(',');
  const q = useApiQuery('desk/watchlist', { query: { symbols, limit: 1000 } }, { enabled: shell.watchlist.length > 0 });
  const rows = q.data?.rows ?? [];
  const inSetup = rows.filter((r) => (r.queues?.length ?? 0) > 0).length;
  const [copied, setCopied] = useState<string | null>(null);
  /** The old staging basket's "Copy for TradingView" / "CSV" buttons. */
  const copy = async (kind: 'tv' | 'csv') => {
    const text = kind === 'tv' ? formatTradingViewList([{ title: 'Watchlist', symbols: shell.watchlist }]).text : shell.watchlist.join(', ');
    const ok = await copyText(text);
    setCopied(ok ? (kind === 'tv' ? 'TV copied' : 'CSV copied') : 'Copy failed');
    window.setTimeout(() => setCopied(null), 2000);
  };
  return (
    <Panel
      title="Watchlist"
      meta={
        <span className={cn(shell.watchSync === 'error' || shell.watchSync === 'local' ? 'text-warn' : undefined)}>
          {shell.watchlist.length} · {q.data ? `${inSetup} in a setup · ` : ''}
          {SYNC_TEXT[shell.watchSync]}
        </span>
      }
      actions={
        shell.watchlist.length > 0 ? (
          <span className="inline-flex items-center gap-0.5 text-2xs">
            {copied && <span role="status" className="text-up">{copied}</span>}
            <button type="button" onClick={() => void copy('tv')} title="Copy the watchlist for TradingView (###Watchlist,NSE:…)" className="rounded px-1.5 py-0.5 text-info hover:bg-info/10">
              TV
            </button>
            <button type="button" onClick={() => void copy('csv')} title="Copy the symbols comma-separated" className="rounded px-1.5 py-0.5 text-info hover:bg-info/10">
              CSV
            </button>
            <button type="button" onClick={() => shell.openCharts(shell.watchlist)} className="rounded px-1.5 py-0.5 text-info hover:bg-info/10">
              Charts
            </button>
          </span>
        ) : undefined
      }
      className={className}
      bodyClassName="overflow-y-auto"
    >
      {shell.watchlist.length === 0 ? (
        <EmptyState compact title="Watchlist is empty" detail="Press W on a focused row, or ★ in Stock 360, to add a stock." />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />
      ) : q.isLoading ? (
        <SkeletonRows rows={Math.min(6, shell.watchlist.length)} label="Loading watchlist" />
      ) : (
        <ul className="py-1">
          {rows.map((r) => (
            <WatchRow key={r.symbol} r={r} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

/** Top groups strip (spec 7.2) → Groups tab. */
export function LeadingGroupsPanel({ className }: { className?: string }) {
  const shell = useShell();
  const q = useApiQuery('groups/board', { query: { level: 'industry', limit: 500 } });
  const lg = useMemo(() => leadingGroups(q.data?.rows ?? []), [q.data]);
  const onGroup = useGroupNav();
  return (
    <Panel
      title={lg.rrg ? 'Leading groups' : 'Top-ranked industries'}
      meta={q.data ? (lg.rrg ? 'RRG Leading, by rank' : `legacy rank, ≥ ${lg.minStocks} stocks · RRG not built yet`) : undefined}
      actions={
        <button type="button" onClick={() => shell.goTab('groups')} className="rounded px-1.5 py-0.5 text-2xs text-info hover:bg-info/10">
          Groups →
        </button>
      }
      className={className}
    >
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />
      ) : q.isLoading ? (
        <div className="p-3">
          <Skeleton height={60} />
        </div>
      ) : lg.rows.length === 0 ? (
        <EmptyState compact title="No groups" detail={q.data?.meta.reason ?? 'Nothing qualifies on this date.'} />
      ) : (
        <ol className="py-1 text-xs">
          {lg.rows.map((g) => (
            <li key={g.id} className="flex items-center gap-2 px-3 py-0.5" title={`${g.group_name} · ${g.stocks ?? '—'} stocks`}>
              <span className="num w-6 text-right text-fg-3">{g.rank ?? '—'}</span>
              <button type="button" className="min-w-0 flex-1 truncate text-left text-fg hover:text-accent hover:underline" onClick={() => onGroup(g.id)} title={`Drill into ${g.group_name}`}>
                {g.group_name}
              </button>
              <GroupHealthChip g={groupRowContext(g)} quadrant={false} clickable={false} />
              <span
                className={cn('num w-10 text-right text-2xs', g.rank_delta_5 == null ? 'text-fg-3' : g.rank_delta_5 > 0 ? 'text-up' : g.rank_delta_5 < 0 ? 'text-down' : 'text-fg-3')}
                title="Places gained (▲) or lost (▼) in the rank over 5 sessions"
              >
                {g.rank_delta_5 == null ? '—' : g.rank_delta_5 === 0 ? '0' : g.rank_delta_5 > 0 ? `▲${g.rank_delta_5}` : `▼${-g.rank_delta_5}`}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}
