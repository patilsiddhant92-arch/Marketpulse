/**
 * Setups · Divergences: RSI(14) divergences confirmed in the last N bars across the ≥ ₹1,000 Cr
 * universe (GET /api/v2/setups/divergences). Filters side / type / timeframe / window, sortable
 * table, Copy for TradingView (sections per side + type), row click opens the chart drawer.
 * A divergence is listed from its confirm bar (2nd pivot + 3 bars); no look-ahead.
 */
import { Copy, ExternalLink } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useApiQuery } from '../../api/query';
import type { DivergenceScanRow } from '../../api/types';
import { copyText } from '../../lib/clipboard';
import { cn } from '../../lib/cn';
import { fmtCr, fmtDate, fmtNum } from '../../lib/fmt';
import { tradingViewChartUrl } from '../../lib/tradingview';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { EmptyState } from '../../ui/EmptyState';
import {
  DIV_SIDES,
  DIV_TFS,
  DIV_TYPES,
  DIV_WINDOWS,
  divergenceQuery,
  divergenceTvText,
  filterDivergences,
  sideTone,
  statusTone,
  typeRank,
} from './divergenceModel';
import { parseList, stateTone, toggleInList } from './model';

type R = DivergenceScanRow;
const EMPTY: R[] = [];

export interface DivergenceUrlState {
  dtf: string;
  dside: string;
  dtypes: string;
  dwin: string;
}

const signedCls = (v: number | null | undefined) => (v == null ? 'text-fg-3' : v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-fg');

export function divergenceColumns(): DataTableColumn<R>[] {
  return [
    {
      id: 'symbol',
      header: 'Symbol',
      accessor: 'symbol',
      width: 124,
      sticky: true,
      cell: (_v, r) => (
        <a
          href={tradingViewChartUrl(r.symbol)}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          title={`${r.name ?? r.symbol}: open in TradingView`}
          className="flex items-center gap-0.5 font-mono font-semibold text-fg hover:text-accent"
        >
          {r.symbol}
          <ExternalLink className="h-2.5 w-2.5 text-fg-3" aria-hidden />
        </a>
      ),
    },
    {
      id: 'div',
      header: 'Divergence',
      accessor: (r) => (r.side === 'bull' ? 0 : 10) + typeRank(r.type),
      width: 150,
      headerTitle: 'Side and type. Strong / Medium / Weak are regular (reversal) divergences; Hidden is trend continuation.',
      cell: (_v, r) => (
        <span className="flex items-center gap-1">
          <Chip tone={sideTone(r.side)} size="xs">
            {r.side === 'bull' ? 'Bull' : 'Bear'}
          </Chip>
          <span className="text-fg">{r.type}</span>
        </span>
      ),
    },
    {
      id: 'confirm',
      header: 'Confirmed',
      accessor: 'confirm_date',
      width: 118,
      headerTitle: 'Bar on which the divergence became known (2nd pivot + 3 bars) and bars since',
      cell: (_v, r) => (
        <span className="num">
          {fmtDate(r.confirm_date)}
          <span className="text-fg-3"> · {r.bars_since_confirm === 0 ? 'today' : `${r.bars_since_confirm}b`}</span>
        </span>
      ),
    },
    {
      id: 'status',
      header: 'Status',
      accessor: 'status',
      width: 96,
      headerTitle: 'Triggered: a daily close beyond the trigger. Failed: a close beyond the stop. Else watching.',
      cell: (_v, r) => (
        <Chip tone={statusTone(r.status)} size="xs" title={r.status_date ? `${r.status} on ${fmtDate(r.status_date)}` : undefined}>
          {r.status}
        </Chip>
      ),
    },
    { id: 'close', header: 'Close', accessor: 'close', format: 'num', width: 84 },
    {
      id: 'trigger',
      header: 'Trigger',
      accessor: 'trigger_price',
      format: 'num',
      width: 84,
      headerTitle: 'Bull: the highest high between the two lows. Bear: the lowest low between the two highs.',
    },
    {
      id: 'dist',
      header: 'To trigger',
      accessor: 'distance_to_trigger_pct',
      width: 88,
      headerTitle: 'Trigger vs the last close, %',
      cell: (v) => <span className={cn('num', signedCls(v as number))}>{fmtNum(v as number, 1)}%</span>,
    },
    { id: 'stop', header: 'Stop', accessor: 'stop_price', format: 'num', width: 84, headerTitle: "The 2nd pivot's low (bull) / high (bear)" },
    { id: 'risk', header: 'Risk %', accessor: 'risk_pct', format: 'num', digits: 1, width: 72, headerTitle: 'Last close to the stop, %' },
    { id: 'rsi', header: 'RSI', accessor: 'rsi', format: 'num', digits: 1, width: 64, headerTitle: 'RSI 14 on the last bar of the timeframe' },
    {
      id: 'pivots',
      header: 'Pivots',
      accessor: 'p2_date',
      width: 230,
      headerTitle: '1st → 2nd pivot: date, price, RSI',
      cell: (_v, r) => (
        <span className="num truncate text-2xs text-fg-2">
          {fmtDate(r.p1_date)} {fmtNum(r.p1_price, 1)} / {fmtNum(r.p1_rsi, 0)} → {fmtDate(r.p2_date)} {fmtNum(r.p2_price, 1)} /{' '}
          {fmtNum(r.p2_rsi, 0)}
        </span>
      ),
    },
    {
      id: 'group',
      header: 'Group',
      accessor: 'group',
      width: 210,
      grow: true,
      cell: (_v, r) => (
        <span className="flex min-w-0 items-center gap-1" title={r.group_reason ?? undefined}>
          {r.group_state && (
            <Chip tone={stateTone(r.group_state)} variant="dot" size="xs">
              {r.group_state}
            </Chip>
          )}
          <span className="truncate text-fg-2">{r.group ?? '—'}</span>
        </span>
      ),
    },
    { id: 'mcap', header: 'Mcap ₹Cr', accessor: 'market_cap_cr', width: 90, cell: (v) => <span className="num">{fmtCr(v as number, 0)}</span> },
  ];
}

function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex items-center overflow-hidden rounded border border-line">
      {options.map((o) => (
        <button
          key={o.id || 'all'}
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

export function DivergencesView({
  state,
  setState,
  search,
  onOpen,
}: {
  state: DivergenceUrlState;
  setState: (patch: Partial<Record<keyof DivergenceUrlState, string | null>>) => void;
  search: string;
  onOpen: (sym: string) => void;
}) {
  const [sorted, setSorted] = useState<R[]>([]);
  const [copied, setCopied] = useState<string | null>(null);
  const query = useMemo(() => divergenceQuery(state), [state]);
  const q = useApiQuery('setups/divergences', { query: query as never }, { keepPrevious: true });
  const rows = q.data?.rows ?? EMPTY;
  const filtered = useMemo(() => filterDivergences(rows, search), [rows, search]);
  const columns = useMemo(() => divergenceColumns(), []);
  const ctx = (q.data?.meta.context ?? {}) as { counts?: Record<string, number>; universe?: number; window?: number };
  const types = parseList(
    state.dtypes,
    DIV_TYPES.map((t) => t.id),
  );
  const unavailable = q.data?.meta.status === 'unavailable';
  const countFor = (t: string) => {
    if (!ctx.counts) return '';
    const sides = state.dside === 'bull' || state.dside === 'bear' ? [state.dside] : ['bull', 'bear'];
    return sides.reduce((a, s) => a + (ctx.counts?.[`${s}:${t}`] ?? 0), 0);
  };

  const copyTv = async () => {
    const { text, count } = divergenceTvText(sorted.length ? sorted : filtered, query.tf as string);
    const ok = await copyText(text);
    setCopied(ok ? `Copied ${count} symbols` : 'Copy failed');
    window.setTimeout(() => setCopied(null), 2500);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-1 text-xs">
        <Seg label="Divergence timeframe" value={query.tf as string} options={DIV_TFS} onChange={(v) => setState({ dtf: v })} />
        <Seg label="Divergence side" value={state.dside === 'bull' || state.dside === 'bear' ? state.dside : ''} options={DIV_SIDES} onChange={(v) => setState({ dside: v || null })} />
        <div className="flex items-center gap-1" role="group" aria-label="Divergence type filter">
          <span className="text-2xs uppercase tracking-wide text-fg-3">Type</span>
          {DIV_TYPES.map((t) => (
            <Chip
              key={t.id}
              size="sm"
              selected={types.includes(t.id)}
              tone={types.includes(t.id) ? 'accent' : 'neutral'}
              title={t.hint}
              onClick={() => setState({ dtypes: toggleInList(state.dtypes, t.id) || null })}
            >
              {t.id}
              <span className="num text-fg-3">{countFor(t.id)}</span>
            </Chip>
          ))}
        </div>
        <label className="flex items-center gap-1 text-fg-3" title="Confirmed within the last N bars of the timeframe">
          Confirmed in
          <select
            aria-label="Confirmed within"
            value={String(query.window)}
            onChange={(e) => setState({ dwin: e.target.value })}
            className="h-6 rounded border border-line bg-surface-2 px-1 text-xs text-fg-2"
          >
            {DIV_WINDOWS.map((w) => (
              <option key={w.id} value={w.id}>
                {w.label}
              </option>
            ))}
          </select>
        </label>
        {q.data && !unavailable && (
          <span className="text-fg-3">
            <span className="num font-semibold text-fg">{filtered.length}</span> divergence{filtered.length === 1 ? '' : 's'} · ≥ ₹1,000 Cr ·
            as of {fmtDate(q.data.as_of)}
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {copied && <span className="text-2xs text-fg-3">{copied}</span>}
          <button
            type="button"
            onClick={() => void copyTv()}
            disabled={!filtered.length}
            className="flex items-center gap-1 rounded border border-line px-2 py-0.5 text-fg-2 hover:text-fg disabled:opacity-40"
            title="Copy the visible divergences as a TradingView watchlist, one section per side + type"
          >
            <Copy className="h-3 w-3" /> Copy for TradingView
          </button>
        </div>
      </div>
      {unavailable ? (
        <EmptyState title="Not available" detail={q.data?.meta.reason ?? 'Divergences are not available for this date.'} />
      ) : (
        <DataTable<R>
          label="RSI divergences"
          columns={columns}
          rows={filtered}
          getRowId={(r) => `${r.symbol}-${r.side}-${r.type}-${r.p2_date}`}
          total={search ? filtered.length : (q.data?.total ?? null)}
          loading={q.isLoading}
          error={q.error}
          onRetry={() => void q.refetch()}
          onRowClick={(r) => onOpen(r.symbol)}
          onRowActivate={(r) => onOpen(r.symbol)}
          onSortedRowsChange={setSorted}
          className="min-h-0 flex-1"
          emptyState={
            <EmptyState
              title="No divergences"
              detail="No RSI divergence of the selected side / type was confirmed in this window. Widen the window or switch timeframe."
            />
          }
        />
      )}
    </div>
  );
}
