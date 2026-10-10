/**
 * Sector Intel (tab id 'groups'; HarkPro/07-tab-sector-intel.md, rounds 1-3d).
 *
 * Answers two questions each evening: where is leadership broadening, and is this group's move broad or one
 * stock? Board at every level (Sector / Broad Industry / Industry / Index) with a 1D / 1W / 2W / 1M window,
 * the Pulse mood + "working now" gauge beside the score, a 9-card chart grid, the group panel, the
 * TradingView-style stock heatmap and the group studies (moved here from Research). No setup references here.
 */
import { CalendarClock, Check, ClipboardCopy } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { copyText } from '../lib/clipboard';
import { useShell } from '../shell/ShellContext';
import { useAsOf, useUrlParam } from '../shell/urlState';
import { Chip } from '../ui/Chip';
import { EmptyState } from '../ui/EmptyState';
import { GroupStudies } from './groups/GroupStudies';
import { Segmented, SourceNote } from './groups/kit';
import { WINDOWS, useSectors, type BoardContext, type IndexRow, type SectorLevel, type SectorRow } from './groups/sectorApi';
import { IndexBoard, SectorBoard } from './groups/SectorBoard';
import { GroupPanel, SectorChartGrid } from './groups/SectorCharts';
import { SectorContext } from './groups/SectorContext';
import {
  BOARD_LEVELS,
  VIEWS,
  asBoardLevel,
  asView,
  asWindow,
  filterRows,
  leadersTvText,
  levelFromGroupId,
  sortByScore,
  stateCounts,
} from './groups/sectorModel';
import { StockHeatmap } from './groups/StockHeatmap';

const EMPTY: SectorRow[] = [];

/** Set several search params in one navigation (two useUrlParam setters in one handler would clobber each other). */
function useSetParams(): (patch: Record<string, string | null>) => void {
  const [, setParams] = useSearchParams();
  return useCallback(
    (patch) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v === null || v === '') next.delete(k);
            else next.set(k, v);
          }
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );
}

export default function GroupsRoute() {
  const [levelParam] = useUrlParam('level');
  const setParams = useSetParams();
  const [winParam, setWin] = useUrlParam('win');
  const [viewParam] = useUrlParam('view');
  const [stateParam, setStateFilter] = useUrlParam('state');
  const [groupParam, setGroup] = useUrlParam('group', { push: true });
  const [pageParam, setPage] = useUrlParam('page');
  const [, setAsOf] = useAsOf();
  const shell = useShell();
  const level = levelFromGroupId(groupParam) ?? asBoardLevel(levelParam);
  const w = asWindow(winParam);
  const view = asView(viewParam);
  const stateF = stateParam === 'Favour' || stateParam === 'Neutral' || stateParam === 'Caution' ? stateParam : 'all';
  const [text, setText] = useState('');
  const [copied, setCopied] = useState(false);
  const isIndex = level === 'index';

  const board = useSectors<SectorRow | IndexRow, BoardContext>('board', { level, limit: 5000 }, { keepPrevious: true });
  const ctx = board.data?.meta.context;
  const rows = useMemo(
    () => (isIndex || board.data?.meta.context?.level !== level ? EMPTY : ((board.data?.rows ?? EMPTY) as SectorRow[])),
    [board.data, isIndex, level],
  );
  const filtered = useMemo(() => sortByScore(filterRows(rows, stateF, text), w), [rows, stateF, text, w]);
  // The board's current sort order (the chart grid follows it); valid only for the same rows.
  const [sorted, setSorted] = useState<{ of: SectorRow[]; rows: SectorRow[] } | null>(null);
  const ordered = sorted && sorted.of === filtered ? sorted.rows : filtered;
  const onSortedRows = useCallback((r: SectorRow[]) => setSorted({ of: filtered, rows: r }), [filtered]);
  const selected = groupParam && rows.some((r) => r.id === groupParam) ? groupParam : (ordered[0]?.id ?? null);
  const selRow = rows.find((r) => r.id === selected);
  const counts = stateCounts(rows);
  const gaps = ctx?.gap_windows ?? [];
  const lastClean = ctx?.last_clean_session;
  const levelLabel = BOARD_LEVELS.find((l) => l.value === level)?.label ?? '';
  const ctxQuery = useSectors<Record<string, unknown>, BoardContext>('context', { level: 'broad_industry' }, { enabled: isIndex });
  const shownCtx = isIndex ? (ctxQuery.data?.rows[0] as BoardContext | undefined) : ctx;

  const open = useCallback((id: string) => setGroup(id), [setGroup]);
  const onSymbol = useCallback((s: string) => shell.openSymbol(s), [shell]);
  const copyLeaders = async () => {
    const { text: t } = leadersTvText(ordered);
    if (t && (await copyText(t))) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line bg-surface px-3 py-1.5">
        <h1 className="text-sm font-semibold text-fg">Sector Intel</h1>
        <Segmented
          label="View"
          options={VIEWS.map((v) => ({ value: v.value, label: v.label, title: v.title }))}
          value={view}
          onChange={(v) => setParams({ view: v === 'board' ? null : v, page: null })}
        />
        {view !== 'heatmap' && (
          <Segmented
            label="Level"
            options={BOARD_LEVELS.filter((l) => view !== 'studies' || l.value !== 'index').map((l) => ({ value: l.value, label: l.label }))}
            value={level}
            onChange={(v) => setParams({ group: null, level: v === 'broad_industry' ? null : v, page: null })}
          />
        )}
        {(view === 'board' || view === 'grid') && (
          <Segmented
            label="Window"
            options={WINDOWS.map((k) => ({ value: k, label: k }))}
            value={w}
            onChange={(v) => setWin(v === '2W' ? null : v)}
          />
        )}
        {(view === 'board' || view === 'grid') && !isIndex && (
          <>
            <Segmented
              label="State filter"
              options={[
                { value: 'all', label: 'All' },
                { value: 'Favour', label: `Favour ${counts.Favour}` },
                { value: 'Neutral', label: `Neutral ${counts.Neutral}` },
                { value: 'Caution', label: `Caution ${counts.Caution}` },
              ]}
              value={stateF}
              onChange={(v) => setStateFilter(v === 'all' ? null : v)}
            />
            <input
              data-filter-input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Filter groups  /"
              aria-label="Filter groups by name"
              className="h-6 w-40 rounded border border-line bg-surface-2 px-2 text-xs text-fg placeholder:text-fg-3 focus:border-focus focus:outline-none"
            />
            <button
              type="button"
              onClick={() => void copyLeaders()}
              className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:text-fg"
              title="Copy the top 3 leaders of each group on screen as a TradingView list (###Group,NSE:A,…)"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-up" /> : <ClipboardCopy className="h-3.5 w-3.5" />} Copy leaders for TradingView
            </button>
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          {(view === 'board' || view === 'grid') && <SourceNote meta={board.data?.meta} />}
        </div>
      </div>

      {(view === 'board' || view === 'grid') && (
        <div className="shrink-0 space-y-1.5 px-2 pt-2">
          <SectorContext ctx={shownCtx} loading={board.isLoading || ctxQuery.isLoading} />
          {gaps.length > 0 && (
            <div
              role="status"
              className="flex flex-wrap items-center gap-2 rounded border border-warn/40 bg-warn/10 px-3 py-1.5 text-xs text-fg"
            >
              <CalendarClock className="h-3.5 w-3.5 text-warn" />
              <span>
                Data gap: the {gaps.join(', ')} {gaps.length === 1 ? 'window spans' : 'windows span'} missing sessions on{' '}
                {board.data?.as_of}, so those readings are blank.
              </span>
              {lastClean && lastClean !== board.data?.as_of && (
                <button type="button" className="text-accent hover:underline" onClick={() => setAsOf(lastClean)}>
                  Show {lastClean}, the latest good session
                </button>
              )}
            </div>
          )}
          {!isIndex && (
            <div className="flex flex-wrap items-center gap-2 text-2xs text-fg-3">
              <Chip variant="dot" tone="positive">
                Favour
              </Chip>
              <Chip variant="dot" tone="neutral">
                Neutral
              </Chip>
              <Chip variant="dot" tone="negative">
                Caution
              </Chip>
              <span>
                · window {w} · <span className="font-semibold text-up">green</span> = top 20% of groups today,{' '}
                <span className="text-down">red</span> = bottom 20%, plain = middle (rank, not sign) · p = vs own 2 years
              </span>
            </div>
          )}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {view === 'heatmap' ? (
          <StockHeatmap />
        ) : view === 'studies' ? (
          <GroupStudies level={(isIndex ? 'broad_industry' : level) as SectorLevel} />
        ) : isIndex ? (
          view === 'grid' ? (
            <EmptyState
              title="Index charts need index history"
              detail="index_daily holds about 32 sessions locally. Use Charts for index candles once the history is backfilled."
            />
          ) : (
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="px-3 py-1 text-2xs text-fg-3">{(board.data?.meta.notes ?? []).join(' ')}</div>
              <IndexBoard
                rows={(board.data?.meta.context?.level === 'index' ? board.data.rows : []) as IndexRow[]}
                w={w}
                loading={board.isLoading}
                error={board.error}
                onRetry={() => void board.refetch()}
              />
            </div>
          )
        ) : (
          <>
            <div className="flex min-w-0 flex-1 flex-col">
              {view === 'grid' ? (
                <SectorChartGrid
                  rows={ordered}
                  w={w}
                  page={Number(pageParam) || 0}
                  onPage={(p) => setPage(p ? String(p) : null)}
                  onOpen={open}
                />
              ) : (
                <SectorBoard
                  rows={filtered}
                  w={w}
                  levelLabel={levelLabel}
                  loading={board.isLoading}
                  error={board.error}
                  onRetry={() => void board.refetch()}
                  selected={selected}
                  onSelect={open}
                  onOpen={open}
                  onSortedRows={onSortedRows}
                />
              )}
            </div>
            <aside aria-label="Group panel" className="flex w-[480px] shrink-0 flex-col overflow-auto border-l border-line bg-surface">
              <GroupPanel row={selRow} w={w} levelLabel={levelLabel} onSymbol={onSymbol} />
            </aside>
          </>
        )}
      </div>
    </div>
  );
}
