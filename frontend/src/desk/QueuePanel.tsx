import { Copy, LayoutGrid } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { isUnavailable } from '../api/client';
import { useApiQuery } from '../api/query';
import type { QueueRow } from '../api/types';
import { copyText } from '../lib/clipboard';
import { cn } from '../lib/cn';
import { fmtNum } from '../lib/fmt';
import { formatTradingViewList } from '../lib/tradingview';
import { useEnvironment } from '../shell/environment';
import { useShell } from '../shell/ShellContext';
import { useUrlParam } from '../shell/urlState';
import { DataTable } from '../ui/DataTable';
import { EmptyState } from '../ui/EmptyState';
import { SkeletonRows } from '../ui/Skeleton';
import { Tooltip } from '../ui/Tooltip';
import { QUEUES, asQueueId, asTf, countFlags, evidenceFor, filterQueueRows, groupDiff, type QueueId, type Tf } from './deskModel';
import { DEFAULT_SORT, queueColumns } from './queueColumns';

const EMPTY: QueueRow[] = [];

/** Elapsed seconds while `active` — the live queue fallback can take a while on a cold server. */
function useElapsed(active: boolean): number {
  const [s, setS] = useState(0);
  useEffect(() => {
    if (!active) return;
    const t0 = Date.now();
    const id = window.setInterval(() => setS(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => {
      window.clearInterval(id);
      setS(0);
    };
  }, [active]);
  return active ? s : 0;
}

function EvidenceLine({ queue }: { queue: QueueId }) {
  const q = useApiQuery('evidence/{setup}', { params: { setup: queue }, query: { by: 'environment' } });
  const { view } = useEnvironment();
  if (q.isLoading) return null;
  if (q.error || !q.data) return <span className="text-fg-3">Evidence: could not load.</span>;
  if (isUnavailable(q.data)) return <span className="text-fg-3">Evidence: not built yet — outcomes per setup arrive with the evidence engine.</span>;
  const ev = evidenceFor(q.data.rows, view?.verdict ?? null);
  const fmt = (r: typeof ev.all, label: string) =>
    !r ? null : r.insufficient_sample ? (
      <span key={label}>
        {label}: n={r.n}, too few to judge
      </span>
    ) : (
      <span key={label}>
        {label}: hit +2R <span className="num text-fg">{fmtNum(r.hit_rate_2r, 0)}%</span> · avg <span className="num text-fg">{fmtNum(r.avg_r, 2)}R</span> · n=
        <span className="num">{r.n}</span>
      </span>
    );
  return (
    <span className="flex flex-wrap gap-x-3 text-fg-3">
      {fmt(ev.all, 'All history')}
      {view?.verdict && fmt(ev.now, `In ${view.verdict}`)}
    </span>
  );
}

export interface QueuePanelProps {
  /** Extra tabs (New vs yesterday / Watchlist) when the Desk is too narrow for the side rail. */
  extraTabs?: { id: string; label: ReactNode; render: () => ReactNode }[];
  className?: string;
}

/** The three Desk queues with full counts, D/W/M, filter, export (spec 7.2). */
export function QueuePanel({ extraTabs = [], className }: QueuePanelProps) {
  const shell = useShell();
  const [queueParam, setQueueParam] = useUrlParam('queue');
  const [tfParam, setTfParam] = useUrlParam('tf');
  const [filter, setFilter] = useUrlParam('q');
  const [newParam, setNewParam] = useUrlParam('new');
  const [extra, setExtra] = useState<string | null>(null);
  const queue = asQueueId(queueParam);
  const tf: Tf = asTf(tfParam, queue);
  const onlyNew = newParam === '1';

  const summary = useApiQuery('desk/queues');
  const diff = useApiQuery('desk/diff', { query: { limit: 5000 } });
  const newCounts = useMemo(() => groupDiff(diff.data?.rows ?? []), [diff.data]);
  const q = useApiQuery('desk/queue/{name}', { params: { name: queue }, query: { tf, limit: 5000 } });
  const elapsed = useElapsed(q.isLoading);

  const rows = q.data?.rows ?? EMPTY;
  const shown = useMemo(() => filterQueueRows(rows, filter ?? '', onlyNew), [rows, filter, onlyNew]);
  const flags = useMemo(() => countFlags(rows), [rows]);
  const { isWatched } = shell;
  const columns = useMemo(() => queueColumns(queue, isWatched), [queue, isWatched]);

  const sortedRef = useRef<QueueRow[]>([]);
  const onSorted = useCallback((r: QueueRow[]) => {
    sortedRef.current = r;
  }, []);
  const [copied, setCopied] = useState<string | null>(null);
  const label = QUEUES.find((x) => x.id === queue)!.label;

  const copyTv = async () => {
    const syms = sortedRef.current.map((r) => r.symbol);
    const { text, count } = formatTradingViewList([{ title: `${label}${tf !== 'D' ? ` ${tf}` : ''}`, symbols: syms }]);
    const ok = await copyText(text);
    setCopied(ok ? `Copied ${count}` : 'Copy failed');
    window.setTimeout(() => setCopied(null), 2500);
  };

  // [ / ] cycle queues while the Desk is the active tab.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key !== '[' && e.key !== ']') return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if (!document.querySelector('section[data-active="true"] [data-desk-queues]')) return;
      e.preventDefault();
      const i = QUEUES.findIndex((x) => x.id === queue);
      const next = QUEUES[(i + (e.key === ']' ? 1 : QUEUES.length - 1)) % QUEUES.length];
      setExtra(null);
      setQueueParam(next.id === 'darvas_squeeze' ? null : next.id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [queue, setQueueParam]);

  const tabBtn = (active: boolean) =>
    cn(
      'flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 text-xs',
      active ? 'border-accent font-semibold text-fg' : 'border-transparent text-fg-3 hover:text-fg',
    );

  const tfs = QUEUES.find((x) => x.id === queue)!.timeframes as readonly Tf[];
  const extraTab = extraTabs.find((t) => t.id === extra);

  return (
    <section aria-label="Desk queues" data-desk-queues className={cn('flex min-h-0 min-w-0 flex-col overflow-hidden rounded border border-line bg-surface', className)}>
      <div className="flex shrink-0 items-center overflow-x-auto border-b border-line pr-2" role="tablist" aria-label="Queues">
        {QUEUES.map((x) => {
          const count = summary.data?.rows.find((r) => r.name === x.id)?.counts?.D;
          const added = newCounts[x.id]?.added.length;
          const active = !extraTab && x.id === queue;
          return (
            <button
              key={x.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => {
                setExtra(null);
                setQueueParam(x.id === 'darvas_squeeze' ? null : x.id);
              }}
              className={tabBtn(active)}
              title={summary.data?.rows.find((r) => r.name === x.id)?.description}
            >
              {x.label}
              <span className="num text-fg-2">{count ?? '·'}</span>
              {added ? <span className="num text-2xs text-accent">+{added}</span> : null}
            </button>
          );
        })}
        {extraTabs.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={extra === t.id} onClick={() => setExtra(t.id)} className={tabBtn(extra === t.id)}>
            {t.label}
          </button>
        ))}
        <span className="ml-auto hidden whitespace-nowrap pl-2 text-2xs text-fg-3 2xl:inline">[ ] queue · J/K rows · Enter full page · W watch</span>
      </div>

      {extraTab ? (
        <div className="min-h-0 flex-1 overflow-hidden [&>section]:h-full [&>section]:rounded-none [&>section]:border-0">{extraTab.render()}</div>
      ) : (
        <>
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line px-2 py-1.5 text-2xs">
            {tfs.length > 1 && (
              <div className="flex overflow-hidden rounded border border-line" role="group" aria-label="Timeframe">
                {tfs.map((t) => (
                  <button
                    key={t}
                    type="button"
                    aria-pressed={tf === t}
                    onClick={() => setTfParam(t === 'D' ? null : t)}
                    className={cn('px-2 py-0.5 font-mono', tf === t ? 'bg-accent/20 text-accent' : 'text-fg-3 hover:bg-surface-3 hover:text-fg')}
                    title={t === 'D' ? 'Daily' : t === 'W' ? 'Weekly (slow on first load)' : 'Monthly (slow on first load)'}
                  >
                    {t}
                  </button>
                ))}
              </div>
            )}
            <input
              data-filter-input
              value={filter ?? ''}
              onChange={(e) => setFilter(e.target.value || null)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') (e.target as HTMLInputElement).blur();
              }}
              placeholder="Filter symbol / industry  ( / )"
              aria-label="Filter queue"
              className="h-6 w-48 rounded border border-line bg-surface-2 px-2 text-xs text-fg placeholder:text-fg-3 focus:border-accent focus:outline-none"
            />
            <label className="flex cursor-pointer items-center gap-1 text-fg-2">
              <input type="checkbox" checked={onlyNew} onChange={(e) => setNewParam(e.target.checked ? '1' : null)} className="accent-[rgb(var(--c-accent))]" />
              New today only
            </label>
            {q.data && (
              <span className="num text-fg-3">
                {flags.isNew} new · {flags.pastTrigger} past trigger · {flags.wideRisk} wide risk · {flags.results} results soon
              </span>
            )}
            <div className="ml-auto flex items-center gap-1">
              {copied && <span className="text-fg-2">{copied}</span>}
              <Tooltip content="Copy the visible rows (filtered, in this order) as a TradingView watchlist">
                <button type="button" onClick={() => void copyTv()} disabled={!shown.length} className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-fg-2 hover:bg-surface-3 disabled:opacity-50">
                  <Copy className="h-3 w-3" aria-hidden /> TradingView
                </button>
              </Tooltip>
              <button
                type="button"
                onClick={() => shell.openCharts(sortedRef.current.map((r) => r.symbol).filter((s): s is string => !!s))}
                disabled={!shown.length}
                className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-fg-2 hover:bg-surface-3 disabled:opacity-50"
              >
                <LayoutGrid className="h-3 w-3" aria-hidden /> Open in Charts
              </button>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2 border-b border-line px-3 py-1 text-2xs">
            <EvidenceLine queue={queue} />
            {q.data?.meta.status === 'partial' && (
              <Tooltip content={q.data.meta.reason ?? ''}>
                <span className="ml-auto cursor-help text-warn">computed live · setup age n/a</span>
              </Tooltip>
            )}
          </div>
          <div className="flex min-h-0 min-w-0 flex-1">
            {q.isLoading ? (
              <div className="flex w-full flex-col">
                <p className="px-3 py-2 text-xs text-fg-2">
                  Computing {label}
                  {tf !== 'D' ? ` (${tf})` : ''} from the indicator tables… <span className="num text-fg-3">{elapsed}s</span>
                  {elapsed > 5 && (
                    <span className="block text-2xs text-fg-3">
                      setup_daily is not built yet, so the server runs the queue predicates live. The first load after each EOD update can take a
                      minute or two; later loads are instant.
                    </span>
                  )}
                </p>
                <SkeletonRows rows={10} label={`Loading ${label}`} />
              </div>
            ) : (
              <DataTable<QueueRow>
                key={`${queue}-${tf}`}
                label={`${label} queue`}
                columns={columns}
                rows={shown}
                total={filter || onlyNew ? shown.length : (q.data?.total ?? null)}
                getRowId={(r, i) => r.symbol ?? String(i)}
                error={q.error}
                onRetry={() => void q.refetch()}
                initialSort={DEFAULT_SORT[queue]}
                activeRowId={shell.symbol}
                onActiveRowChange={(r) => r.symbol && shell.openSymbol(r.symbol)}
                onRowClick={(r) => r.symbol && shell.openSymbol(r.symbol)}
                onRowActivate={(r) => r.symbol && shell.openStockPage(r.symbol)}
                onSortedRowsChange={onSorted}
                emptyState={
                  q.data && isUnavailable(q.data) ? (
                    <EmptyState title="Queue unavailable" detail={q.data.meta.reason ?? undefined} />
                  ) : rows.length > 0 ? (
                    <EmptyState title="No rows match the filter" detail="Clear the filter or the New-only toggle." />
                  ) : (
                    <EmptyState title={`Nothing in ${label} today`} detail="No stock met the queue's rules on this session — a real empty result, not an error." />
                  )
                }
                className="min-h-0 min-w-0 flex-1"
              />
            )}
          </div>
        </>
      )}
    </section>
  );
}
