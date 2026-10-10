/**
 * Setups (HarkPro/06-tab2-setups.md, LOCKED 2026-10-09) — Siddhant's analysis tab.
 * One board, one row per stock, screener tags show confluence. Header: screener filter,
 * group-state filter, momentum template + volume gate, Copy for TradingView. Read-out and
 * scan-count history. Views: Board · Chart grid · Near-miss · Dropped · Divergences. Detail panel on row open.
 * The tab never sizes or places trades.
 */
import { Copy } from 'lucide-react';
import { useCallback, useDeferredValue, useMemo, useState } from 'react';
import { useApiQuery } from '../../api/query';
import type { SetupBoardRow } from '../../api/types';
import { copyText } from '../../lib/clipboard';
import { cn } from '../../lib/cn';
import { fmtDate } from '../../lib/fmt';
import { useTabUrlState } from '../../lib/tabUrlState';
import { useShell } from '../../shell/ShellContext';
import { Chip } from '../../ui/Chip';
import { DataTable } from '../../ui/DataTable';
import { EmptyState } from '../../ui/EmptyState';
import { boardColumns } from './columns';
import {
  SCREENERS,
  SETUPS_DEFAULTS,
  STATES,
  boardQuery,
  filterRows,
  parseList,
  rowHighlight,
  stateTone,
  toggleInList,
  tvText,
  type BoardContext,
  type GroupState,
  type ScreenerId,
  type TvGroupBy,
} from './model';
import { ChartGrid, DataGaps, DetailPanel, DroppedView, NearMissView, ReadOut, ScanCounts } from './parts';
import { DivergencesView } from './DivergencesView';

const EMPTY: SetupBoardRow[] = [];
const VIEWS = [
  { id: 'board', label: 'Board' },
  { id: 'grid', label: 'Chart grid' },
  { id: 'near', label: 'Near-miss' },
  { id: 'dropped', label: 'Dropped' },
  { id: 'div', label: 'Divergences' },
] as const;
const TV_GROUPS: { id: TvGroupBy; label: string }[] = [
  { id: 'screener', label: 'by screener' },
  { id: 'sector', label: 'by sector' },
  { id: 'industry', label: 'by industry' },
  { id: 'bucket', label: 'by momentum bucket' },
];

function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex items-center overflow-hidden rounded border border-line">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={value === o.id}
          onClick={() => onChange(o.id)}
          className={cn('h-6 px-2 text-xs', value === o.id ? 'bg-accent/15 text-accent' : 'text-fg-2 hover:text-fg')}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function SetupsView() {
  const shell = useShell();
  const [state, setState] = useTabUrlState('/setups', SETUPS_DEFAULTS, 'setups');
  const [search, setSearch] = useState('');
  const deferred = useDeferredValue(search);
  const [detail, setDetail] = useState<string | null>(null);
  const [sorted, setSorted] = useState<SetupBoardRow[]>([]);
  const [copied, setCopied] = useState<string | null>(null);

  const query = useMemo(() => boardQuery(state), [state]);
  const board = useApiQuery('setups/board', { query: query as never }, { keepPrevious: true });
  const rows = board.data?.rows ?? EMPTY;
  const ctx = (board.data?.meta.context ?? {}) as BoardContext;
  const unavailable = board.data?.meta.status === 'unavailable';

  const screeners = useMemo(() => parseList<ScreenerId>(state.sq, SCREENERS.map((s) => s.id)), [state.sq]);
  const states = useMemo(() => parseList<GroupState>(state.sg, STATES), [state.sg]);
  const filtered = useMemo(() => filterRows(rows, screeners, states, deferred), [rows, screeners, states, deferred]);
  const columns = useMemo(() => boardColumns(), []);
  const view = (VIEWS.find((v) => v.id === state.sv)?.id ?? 'board') as (typeof VIEWS)[number]['id'];
  const detailQuery = useMemo(() => ({ template: query.template, volume_mode: query.volume_mode, results_n: query.results_n }), [query]);

  const open = useCallback(
    (sym: string) => {
      setDetail(sym);
      shell.openSymbol(sym);
    },
    [shell],
  );

  const copyTv = async () => {
    const list = view === 'board' && sorted.length ? sorted : filtered;
    const { text, count } = tvText(list, (state.tvg as TvGroupBy) || 'screener');
    const ok = await copyText(text);
    setCopied(ok ? `Copied ${count} symbols` : 'Copy failed');
    window.setTimeout(() => setCopied(null), 2500);
  };

  const split = ctx.group_split;
  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 1. Header */}
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-3 py-1.5 text-xs">
        <div className="flex items-center gap-1" role="group" aria-label="Screener filter">
          <span className="text-2xs uppercase tracking-wide text-fg-3">Screener</span>
          {SCREENERS.map((s) => (
            <Chip key={s.id} size="sm" selected={screeners.includes(s.id)} tone={screeners.includes(s.id) ? 'accent' : 'neutral'} onClick={() => setState({ sq: toggleInList(state.sq, s.id) })}>
              {s.label}
              <span className="num text-fg-3">{ctx.counts?.[s.id]?.today ?? ''}</span>
            </Chip>
          ))}
        </div>
        <div className="flex items-center gap-1" role="group" aria-label="Group state filter">
          <span className="text-2xs uppercase tracking-wide text-fg-3">Group</span>
          {STATES.map((g) => (
            <Chip key={g} size="sm" variant="dot" selected={states.includes(g)} tone={stateTone(g)} onClick={() => setState({ sg: toggleInList(state.sg, g) })}>
              {g}
              <span className="num text-fg-3">{split?.[g] ?? ''}</span>
            </Chip>
          ))}
        </div>
        <div className="flex items-center gap-1" title="Momentum template: EMA stack (10>20>50>100>200) or SMA template (50>150>200, rising 200)">
          <span className="text-2xs uppercase tracking-wide text-fg-3">Momentum</span>
          <Seg label="Momentum template" value={state.tpl === 'sma' ? 'sma' : 'ema'} options={[{ id: 'ema', label: 'EMA template' }, { id: 'sma', label: 'SMA template' }]} onChange={(v) => setState({ tpl: v })} />
          <Seg
            label="Momentum volume gate"
            value={state.vg === 'avg20d' ? 'avg20d' : 'day'}
            options={[
              { id: 'day', label: 'Day vol ≥ 10L' },
              { id: 'avg20d', label: '20D avg vol ≥ 10L' },
            ]}
            onChange={(v) => setState({ vg: v })}
          />
        </div>
        <label className="flex items-center gap-1 text-fg-3" title="Highlight the whole row when results fall within N sessions">
          Results ≤
          <input
            type="number"
            min={1}
            max={60}
            value={state.rn}
            onChange={(e) => setState({ rn: e.target.value })}
            aria-label="Results within N sessions"
            className="h-6 w-12 rounded border border-line bg-surface-2 px-1 text-right text-xs text-fg"
          />
          sessions
        </label>
        <div className="ml-auto flex items-center gap-1.5">
          {copied && <span className="text-2xs text-fg-3">{copied}</span>}
          <select
            aria-label="TradingView sections"
            value={state.tvg}
            onChange={(e) => setState({ tvg: e.target.value })}
            className="h-6 rounded border border-line bg-surface-2 px-1 text-xs text-fg-2"
          >
            {TV_GROUPS.map((g) => (
              <option key={g.id} value={g.id}>
                {g.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void copyTv()}
            disabled={!filtered.length}
            className="flex items-center gap-1 rounded border border-line px-2 py-0.5 text-fg-2 hover:text-fg disabled:opacity-40"
            title="Copy the visible stocks as a TradingView watchlist (###Section,NSE:A,NSE:B)"
          >
            <Copy className="h-3 w-3" /> Copy for TradingView
          </button>
        </div>
      </div>

      {/* 2-3. Read-out + scan count history */}
      {board.data && !unavailable && (
        <div className="flex shrink-0 flex-wrap gap-3 border-b border-line px-3 py-2">
          <ReadOut ctx={ctx} />
          <ScanCounts ctx={ctx} />
        </div>
      )}

      {/* 4. Views */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line px-3 py-1 text-xs">
        <div role="tablist" aria-label="Setups views" className="flex items-center gap-1">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              role="tab"
              aria-selected={view === v.id}
              onClick={() => setState({ sv: v.id })}
              className={cn('h-6 rounded-md border px-2.5', view === v.id ? 'border-accent bg-accent/15 text-accent' : 'border-line text-fg-2 hover:text-fg')}
            >
              {v.label}
            </button>
          ))}
        </div>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter symbol / industry"
          aria-label="Filter setups"
          className="h-6 w-48 rounded border border-line bg-surface-2 px-2 text-xs text-fg"
        />
        {board.data && (
          <span className="text-fg-3">
            <span className="num font-semibold text-fg">{filtered.length}</span> of {board.data.total ?? '—'} · as of {fmtDate(board.data.as_of)}
            {ctx.confluence != null && ` · ${ctx.confluence} in 2+ screeners`}
          </span>
        )}
        <DataGaps gaps={ctx.data_gaps} />
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        {view === 'div' ? (
          <DivergencesView state={state} setState={setState} search={deferred} onOpen={(s) => shell.openSymbol(s)} />
        ) : view === 'near' ? (
          <NearMissView onPick={open} />
        ) : view === 'dropped' ? (
          <DroppedView query={detailQuery} onPick={open} />
        ) : unavailable ? (
          <EmptyState title="Not available" detail={board.data?.meta.reason ?? 'The board is not available for this date.'} />
        ) : view === 'grid' ? (
          <ChartGrid rows={sorted.length ? sorted : filtered} onInspect={open} activeSymbol={detail} />
        ) : (
          <DataTable<SetupBoardRow>
            label="Setups board"
            columns={columns}
            rows={filtered}
            getRowId={(r) => r.symbol}
            total={deferred || screeners.length || states.length ? filtered.length : (board.data?.total ?? null)}
            loading={board.isLoading}
            error={board.error}
            onRetry={() => void board.refetch()}
            onRowClick={(r) => shell.openSymbol(r.symbol)}
            onRowActivate={(r) => open(r.symbol)}
            onSortedRowsChange={setSorted}
            rowClassName={rowHighlight}
            className="min-h-0 flex-1"
            emptyState={<EmptyState title="No setups" detail="No stock passes a screener with the current filters." />}
          />
        )}
      </div>
      <DetailPanel symbol={detail} query={detailQuery} onClose={() => setDetail(null)} onSelect={open} />
    </div>
  );
}
