/**
 * Capital accumulators (restored from the old Capital Flow radar, parity audit 2026-09-27):
 * liquid stocks (mcap ≥ floor, ADV ≥ ₹3 Cr, CMP ≥ ₹10) up on the day with turnover ≥ ₹10 Cr
 * and ≥ 30% above its 20-day average, ranked by rupees. Full list (the old radar capped at 25),
 * GET /api/v2/market/accumulators. Copy to TradingView / Open in Charts use the rows as shown.
 */
import { Check, ClipboardCopy, LayoutGrid, Star } from 'lucide-react';
import { useCallback, useMemo, useRef, useState } from 'react';
import { useApiQuery } from '../../api/query';
import type { AccumulatorRow } from '../../api/types';
import { copyText } from '../../lib/clipboard';
import { cn } from '../../lib/cn';
import { formatTradingViewList } from '../../lib/tradingview';
import { useShell } from '../../shell/ShellContext';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { EmptyState } from '../../ui/EmptyState';
import { Unclassified } from '../../ui/Unclassified';
import { SourceNote } from './kit';
import { DealIcon } from '../../ui/DealIcon';

const EMPTY: AccumulatorRow[] = [];

function columns(isWatched: (s: string) => boolean, toggleWatch: (s: string) => void): DataTableColumn<AccumulatorRow>[] {
  return [
    {
      id: 'symbol',
      header: 'Symbol',
      accessor: 'symbol',
      width: 120,
      sticky: true,
      hideable: false,
      cell: (_v, r) => (
        <span className="flex min-w-0 items-center gap-1">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              if (r.symbol) toggleWatch(r.symbol);
            }}
            aria-label={`Watchlist ${r.symbol}`}
            title="Add to / remove from the watchlist (W)"
          >
            <Star className={cn('h-3 w-3 shrink-0', r.symbol && isWatched(r.symbol) ? 'fill-accent text-accent' : 'text-fg-3')} />
          </button>
          <span className="truncate font-mono font-semibold text-fg" title={r.security_name ?? undefined}>
            {r.symbol}
          </span>
          <DealIcon symbol={r.symbol} />
        </span>
      ),
    },
    {
      id: 'industry',
      header: 'Sector › Industry',
      accessor: 'industry',
      width: 190,
      renderNull: true,
      cell: (v, r) => (
        <span className="flex min-w-0 flex-col leading-tight" title={[r.broad_sector, r.sector, r.industry].filter(Boolean).join(' › ')}>
          <span className="truncate text-fg-2">{r.sector ?? '—'}</span>
          {v == null || v === '' ? <Unclassified /> : <span className="truncate text-2xs text-fg-3">{String(v)}</span>}
        </span>
      ),
    },
    { id: 'market_cap_cr', header: 'Mcap ₹Cr', accessor: 'market_cap_cr', format: 'int', width: 84, metricKey: 'market_cap_cr' },
    { id: 'close', header: 'Close', accessor: 'close', format: 'num', width: 76 },
    { id: 'change_1d_pct', header: '1D', accessor: 'change_1d_pct', format: 'signedPct', digits: 2, width: 64, metricKey: 'change_1d_pct' },
    { id: 'turnover_cr', header: 'T/O ₹Cr', accessor: 'turnover_cr', format: 'num', digits: 1, width: 76, headerTitle: 'Traded value today, ₹ Cr (default sort: rupees, not % spikes)' },
    {
      id: 'turnover_surge_pct',
      header: 'Surge',
      accessor: 'turnover_surge_pct',
      format: 'signedPct',
      digits: 0,
      width: 64,
      headerTitle: 'Turnover vs its 20-day average traded value',
      heat: (v) => (typeof v === 'number' ? Math.min(1, v / 300) : null),
    },
    { id: 'delivery_pct', header: 'Deliv %', accessor: 'delivery_pct', format: 'pct', digits: 1, width: 64, metricKey: 'delivery_pct' },
    { id: 'deliv_pct_x', header: 'Dlv %×', accessor: 'deliv_pct_x', format: 'ratio', width: 60, headerTitle: "Delivery % ÷ the stock's own 20-day average" },
    { id: 'ticket_ratio', header: 'Ticket', accessor: 'ticket_ratio', format: 'ratio', width: 60, headerTitle: 'Average trade size ÷ its 20-day average (≥ 1.25× = whale ticket)' },
    { id: 'rs_percentile', header: 'Rank', accessor: 'rs_percentile', format: 'num', digits: 0, width: 56, metricKey: 'rs_percentile' },
    {
      id: 'tags',
      header: 'Tags',
      accessor: (r) => (r.whale_ticket ? 1 : 0) + (r.delivery_spike ? 1 : 0) + (r.price_up_delivery_up ? 1 : 0),
      width: 170,
      headerTitle: 'Whale ticket · delivery spike · price up + delivery up',
      cell: (_v, r) => (
        <span className="flex gap-1">
          {r.whale_ticket && <Chip tone="violet" title="Average trade size ≥ 1.25× its 20-day average">Whale</Chip>}
          {r.delivery_spike && <Chip tone="positive" title="Delivery quantity spike vs its 20-day average">Deliv</Chip>}
          {r.price_up_delivery_up && <Chip tone="info" title="Price up and delivery up">Acc vol</Chip>}
        </span>
      ),
    },
  ];
}

export function AccumulatorsView({ text }: { text: string }) {
  const shell = useShell();
  const q = useApiQuery('market/accumulators', { query: { limit: 5000 } });
  const rows = q.data?.rows ?? EMPTY;
  const filtered = useMemo(() => {
    const t = text.trim().toLowerCase();
    if (!t) return rows;
    return rows.filter((r) =>
      [r.symbol, r.security_name, r.sector, r.industry].some((x) => (x ?? '').toLowerCase().includes(t)),
    );
  }, [rows, text]);
  const { isWatched, toggleWatch, openSymbol, openCharts } = shell;
  const cols = useMemo(() => columns(isWatched, toggleWatch), [isWatched, toggleWatch]);
  const sortedRef = useRef<AccumulatorRow[]>([]);
  const onSorted = useCallback((r: AccumulatorRow[]) => {
    sortedRef.current = r;
  }, []);
  const [msg, setMsg] = useState<string | null>(null);
  const shownSyms = () => sortedRef.current.map((r) => r.symbol).filter((s): s is string => !!s);
  const copy = async () => {
    const { text: out, count } = formatTradingViewList([{ symbols: shownSyms() }]);
    const ok = count > 0 && (await copyText(out));
    setMsg(ok ? `Copied ${count}` : 'Copy failed');
    window.setTimeout(() => setMsg(null), 2500);
  };
  const note = q.data?.meta.notes?.[0];
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line px-3 py-1.5 text-2xs">
        <span className="font-semibold uppercase tracking-wide text-fg-2">Capital accumulators</span>
        <span className="text-fg-3">{note ?? 'Liquid names with a turnover surge on an up day, ranked by rupees.'}</span>
        <span className="num text-fg-3">{q.data ? `${filtered.length} of ${q.data.total ?? rows.length}` : ''}</span>
        <div className="ml-auto flex items-center gap-1">
          <SourceNote meta={q.data?.meta} />
          {msg && (
            <span role="status" className="inline-flex items-center gap-0.5 text-up">
              <Check className="h-3 w-3" /> {msg}
            </span>
          )}
          <button
            type="button"
            onClick={() => void copy()}
            disabled={!filtered.length}
            title="Copy the rows as shown (filter + sort) as a TradingView watchlist"
            className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-fg-2 hover:bg-surface-3 disabled:opacity-50"
          >
            <ClipboardCopy className="h-3 w-3" /> TradingView ({filtered.length})
          </button>
          <button
            type="button"
            onClick={() => openCharts(shownSyms())}
            disabled={!filtered.length}
            className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-fg-2 hover:bg-surface-3 disabled:opacity-50"
          >
            <LayoutGrid className="h-3 w-3" /> Open in Charts
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        <DataTable
          label="Capital accumulators"
          columns={cols}
          rows={filtered}
          total={q.data ? filtered.length : null}
          getRowId={(r) => r.symbol ?? ''}
          loading={q.isLoading}
          error={q.error}
          onRetry={() => void q.refetch()}
          initialSort={[{ id: 'turnover_cr', desc: true }]}
          activeRowId={shell.symbol}
          onActiveRowChange={(r) => r.symbol && openSymbol(r.symbol)}
          onSortedRowsChange={onSorted}
          emptyState={
            <EmptyState
              title={q.data?.meta.status === 'unavailable' ? 'Accumulators unavailable' : 'No accumulators today'}
              detail={q.data?.meta.reason ?? 'No liquid stock met the surge rules on this session — a real empty result.'}
            />
          }
          className="h-full"
        />
      </div>
    </div>
  );
}
