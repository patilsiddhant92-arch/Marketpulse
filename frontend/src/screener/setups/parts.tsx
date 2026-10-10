/** Setups tab pieces: read-out, scan counts, chart grid, detail panel, near-miss and dropped tables. */
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useApiQuery } from '../../api/query';
import type { SetupBoardRow, SetupDroppedRow, SetupNearMissRow } from '../../api/types';
import { ChartTile } from '../../charts/ChartTile';
import type { ChartItem } from '../../charts/sources';
import { cn } from '../../lib/cn';
import { fmtDate, fmtNum } from '../../lib/fmt';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { DataWarningChip } from '../../ui/DataWarningChip';
import { Drawer } from '../../ui/Drawer';
import { GroupStateChip } from '../../ui/GroupState';
import { useGroupState } from '../../context/groupState';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { Skeleton } from '../../ui/Skeleton';
import { Spark } from '../../ui/Spark';
import { SignedNum } from '../cells';
import { SCREENERS, countSeries, tagTone, type BoardContext, type DetailContext } from './model';
import { DealIcon, SymbolWithDeal } from '../../ui/DealIcon';

// ------------------------------------------------------------------ read-out + counts
export function ReadOut({ ctx }: { ctx: BoardContext }) {
  const r = ctx.readout;
  if (!r) return null;
  return (
    <section aria-label="Setups read-out" className="min-w-0 flex-1 space-y-0.5 text-xs leading-snug text-fg-2">
      {r.lines.map((l) => (
        <p key={l}>{l}</p>
      ))}
      {r.what_to_do.length > 0 && (
        <p className="text-fg">
          <span className="font-semibold">What to do:</span> {r.what_to_do.map((t) => `${t}.`).join(' ')}
        </p>
      )}
    </section>
  );
}

export function ScanCounts({ ctx }: { ctx: BoardContext }) {
  return (
    <section aria-label="Scan count history" className="flex shrink-0 flex-wrap gap-2">
      {SCREENERS.map((s) => {
        const c = ctx.counts?.[s.id];
        const series = countSeries(c);
        return (
          <div key={s.id} className="w-[132px] rounded border border-line bg-surface px-2 py-1" title={c?.gap ?? undefined}>
            <div className="flex items-baseline justify-between text-2xs text-fg-3">
              <span>{s.label}</span>
              <span className="num text-sm font-semibold text-fg">{c?.today ?? '—'}</span>
            </div>
            {series.length > 1 ? (
              <Spark values={series} width={116} height={18} tone="accent" label={`${s.label} daily count, ${series.length} sessions`} />
            ) : (
              <div className="h-[18px] text-2xs text-fg-3">{c?.gap ? 'history not stored' : '—'}</div>
            )}
            <div className="text-2xs text-fg-3">
              {c?.median_20 != null ? `20D median ${fmtNum(c.median_20, 0)}` : 'no median'}
              {c?.percentile != null && ` · p${fmtNum(c.percentile, 0)}`}
            </div>
          </div>
        );
      })}
    </section>
  );
}

export function DataGaps({ gaps }: { gaps?: string[] }) {
  if (!gaps?.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1" aria-label="Data gaps">
      {gaps.map((g) => (
        <DataWarningChip key={g} warning={g} />
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ chart grid (9 per page, synced, J/K pages)
export function toChartItem(r: SetupBoardRow): ChartItem {
  return {
    symbol: r.symbol,
    name: r.name,
    industry: r.industry,
    close: r.close,
    change_1d_pct: r.change_1d_pct,
    rs_percentile: r.rs_percentile,
    rs_delta_5: r.rs_delta_5d,
    trigger_price: r.trigger,
    stop_price: r.stop,
    market_cap_cr: r.market_cap_cr,
    setup_age_sessions: r.age,
    data_warning: r.data_warning,
    tags: r.tags,
  };
}

export const GRID_PAGE = 9;

export function ChartGrid({ rows, onInspect, activeSymbol }: { rows: readonly SetupBoardRow[]; onInspect: (s: string) => void; activeSymbol: string | null }) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / GRID_PAGE));
  const cur = Math.min(page, pages - 1);
  const [expanded, setExpanded] = useState<string | null>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if (e.key === 'j' || e.key === 'J') setPage((p) => Math.min(pages - 1, p + 1));
      if (e.key === 'k' || e.key === 'K') setPage((p) => Math.max(0, p - 1));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [pages]);
  const slice = rows.slice(cur * GRID_PAGE, cur * GRID_PAGE + GRID_PAGE);
  const shown = expanded ? slice.filter((r) => r.symbol === expanded) : slice;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-7 shrink-0 items-center gap-2 border-b border-line px-3 text-2xs text-fg-3">
        <button type="button" aria-label="Previous page" onClick={() => setPage(Math.max(0, cur - 1))} disabled={cur === 0} className="disabled:opacity-40">
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <span className="num">
          Page {cur + 1} / {pages} · {rows.length} stocks · J / K to page · crosshair synced
        </span>
        <button type="button" aria-label="Next page" onClick={() => setPage(Math.min(pages - 1, cur + 1))} disabled={cur >= pages - 1} className="disabled:opacity-40">
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No setups" detail="No stock matches the current filters." />
      ) : (
        <div className={cn('grid min-h-0 flex-1 gap-1 p-1', expanded ? 'grid-cols-1' : 'grid-cols-3 grid-rows-3')}>
          {shown.map((r) => (
            <ChartTile
              key={r.symbol}
              item={toChartItem(r)}
              timeframe="D"
              relWindow="3M"
              syncGroup="setups-grid"
              compact={!expanded}
              volume={!!expanded}
              active={activeSymbol === r.symbol}
              expanded={expanded === r.symbol}
              onInspect={onInspect}
              onToggleExpand={(s) => setExpanded((e) => (e === s ? null : s))}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ detail panel
function Fact({ label, children, title }: { label: string; children: React.ReactNode; title?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-line/40 py-0.5 text-xs" title={title}>
      <span className="text-fg-3">{label}</span>
      <span className="num text-right text-fg">{children}</span>
    </div>
  );
}

export function DetailPanel({
  symbol,
  query,
  onClose,
  onSelect,
}: {
  symbol: string | null;
  query: Record<string, string | number>;
  onClose: () => void;
  onSelect: (s: string) => void;
}) {
  const q = useApiQuery('setups/detail/{sym}', { params: { sym: symbol ?? '' }, query: query as never }, { enabled: !!symbol });
  const shared = useGroupState('industry');
  const raw = q.data?.rows[0];
  const sg = raw?.industry ? shared.map.get(raw.industry) : undefined;
  const row = raw && sg ? { ...raw, group_state: sg.state, group_reason: sg.reason } : raw;
  const ctx = (q.data?.meta.context ?? {}) as DetailContext;
  const item = useMemo(() => (row ? toChartItem(row) : symbol ? { symbol, tags: [] } : null), [row, symbol]);
  return (
    <Drawer open={!!symbol} onClose={onClose} title={symbol ? `${symbol} setup` : 'Setup'} width={760}>
      {q.isLoading && <Skeleton className="m-3" height={300} />}
      {q.error && <ErrorState error={q.error} onRetry={() => void q.refetch()} compact />}
      {item && (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-2">
          <div className="h-[340px] shrink-0">
            <ChartTile
              item={item}
              timeframe="D"
              relWindow="3M"
              syncGroup="setups-detail"
              compact={false}
              volume
              active
              expanded
              onInspect={() => undefined}
              onToggleExpand={() => undefined}
            />
          </div>
          {row ? (
            <div className="grid grid-cols-2 gap-x-4">
              <div>
                <div className="mb-1 flex flex-wrap gap-1">
                  {row.tags.map((t) => (
                    <Chip key={t} tone={tagTone(t)} size="xs">
                      {t}
                    </Chip>
                  ))}
                </div>
                <Fact label="Group">
                  <GroupStateChip state={row.group_state} reason={row.group_reason} />
                </Fact>
                <p className="py-0.5 text-2xs text-fg-2">{row.group_reason}</p>
                <Fact label="Trigger / stop">
                  {fmtNum(row.trigger)} / {fmtNum(row.stop)}
                </Fact>
                <Fact label="Risk % · ÷ ADR">
                  {fmtNum(row.risk_pct, 1)}% · {fmtNum(row.risk_adr, 2)}
                </Fact>
                <Fact label="Room to run">{row.blue_sky ? 'Blue sky' : `${fmtNum(row.room_to_run_pct, 1)}%`}</Fact>
                <Fact label="52W high · 10 EMA · 50 EMA">
                  <SignedNum value={row.away_52w_high_pct} /> · <SignedNum value={row.away_10ema_pct} /> · <SignedNum value={row.away_50ema_pct} />
                </Fact>
                <Fact label="RS 21D vs MidSml400">
                  <SignedNum value={row.rs_21d} />
                </Fact>
              </div>
              <div>
                <Fact
                  label="Base rate (20D)"
                  title={row.base_rate ? `${row.base_rate.scope ?? ''}, n ${row.base_rate.n ?? '—'}` : 'No stored outcomes'}
                >
                  {row.base_rate ? (
                    <>
                      {fmtNum(row.base_rate.win, 0)}% up · <SignedNum value={row.base_rate.median} /> · n {row.base_rate.n}
                    </>
                  ) : (
                    '—'
                  )}
                </Fact>
                <Fact label="Box breakouts 6M (held / failed)">
                  {row.breakouts_held_6m} / {row.breakouts_failed_6m}
                </Fact>
                <Fact label="Weekly: vs 10W · tight 3W">
                  {row.weekly_above_10w == null ? '—' : row.weekly_above_10w ? 'above' : 'below'} · {row.weekly_tight ? 'yes' : 'no'} (
                  {fmtNum(row.weekly_spread_3w_pct, 1)}%)
                </Fact>
                <Fact label="Delivery today / 20D · streak">
                  {fmtNum(row.delivery_pct, 0)}% / {fmtNum(row.delivery_avg_20d, 0)}% · {row.delivery_streak}d
                </Fact>
                <Fact label="Turnover 1D / 1W / 1M ×">
                  {fmtNum(row.turnover_1d_x, 2)} / {fmtNum(row.turnover_1w_x, 2)} / {fmtNum(row.turnover_1m_x, 2)}
                </Fact>
                <Fact label="Group share Δ 1D / 1W / 1M">
                  <SignedNum value={row.group_share_chg_1d} /> / <SignedNum value={row.group_share_chg_1w} /> / <SignedNum value={row.group_share_chg_1m} />
                </Fact>
                {row.peer_note && <p className="py-0.5 text-2xs text-info">{row.peer_note}</p>}
              </div>
            </div>
          ) : (
            q.data && <p className="text-xs text-fg-3">{symbol} is not on the board for this session.</p>
          )}
          {(ctx.deal_markers?.length ?? 0) > 0 && (
            <div className="text-2xs text-fg-3">
              Deal days (last 400 days):{' '}
              {ctx.deal_markers!.slice(-6).map((d) => (
                <span key={`${d.time}-${d.kind}`} className={cn('mr-2', d.kind === 'deal_buy' ? 'text-up' : 'text-down')}>
                  {fmtDate(d.time)} {d.kind === 'deal_buy' ? 'buy' : 'sell'} ₹{fmtNum(d.value_cr, 0)} Cr
                </span>
              ))}
            </div>
          )}
          {(ctx.rsi_divergences?.length ?? 0) > 0 && (
            <div className="text-2xs text-fg-3">
              RSI divergences (regular):{' '}
              {ctx.rsi_divergences!.slice(-4).map((d) => `${fmtDate(d.time)} ${d.kind.replace('regular_', '')}`).join(' · ')}
            </div>
          )}
          <DataGaps gaps={ctx.data_gaps} />
          <section aria-label="Peers">
            <div className="mb-0.5 text-2xs uppercase tracking-wide text-fg-3">Top RS peers · {ctx.industry ?? '—'}</div>
            {(ctx.peers ?? []).map((p) => (
              <button
                key={p.symbol}
                type="button"
                onClick={() => onSelect(p.symbol)}
                className={cn('flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs hover:bg-surface-3', p.symbol === symbol && 'text-accent')}
              >
                <span className="inline-flex w-24 items-center gap-1 font-mono">
                  {p.symbol}
                  <DealIcon symbol={p.symbol} />
                </span>
                <span className="num w-10 text-right">{fmtNum(p.rs_percentile, 0)}</span>
                <span className="w-16 text-right">
                  <SignedNum value={p.away_52w_high_pct} />
                </span>
                <span className="flex gap-1">
                  {p.tags.map((t) => (
                    <Chip key={t} tone={tagTone(t)} size="xs">
                      {t}
                    </Chip>
                  ))}
                </span>
              </button>
            ))}
          </section>
        </div>
      )}
    </Drawer>
  );
}

// ------------------------------------------------------------------ near-miss + dropped
const NEAR_COLS: DataTableColumn<SetupNearMissRow>[] = [
  { id: 'symbol', header: 'Symbol', accessor: 'symbol', width: 110, cell: (v) => <SymbolWithDeal symbol={String(v)} /> },
  { id: 'gate', header: 'Fails one gate', accessor: 'gate', width: 220, grow: true },
  { id: 'sq', header: 'Squeeze %', accessor: 'squeeze_pct', format: 'pct', digits: 1, width: 80 },
  { id: 'close', header: 'Close', accessor: 'close', format: 'num', width: 80 },
  { id: 'top', header: 'Box top', accessor: 'box_top', format: 'num', width: 80 },
  { id: 'e10', header: '10 EMA', accessor: 'ema_10', format: 'num', width: 80 },
  { id: 'rvol', header: 'RVOL', accessor: 'rvol', format: 'num', digits: 2, width: 64 },
  { id: 'ind', header: 'Industry', accessor: 'industry', width: 180 },
];

export function NearMissView({ onPick }: { onPick: (s: string) => void }) {
  const q = useApiQuery('setups/near-miss', { query: { limit: 200 } as never });
  return (
    <DataTable<SetupNearMissRow>
      label="Squeeze near-miss"
      columns={NEAR_COLS}
      rows={q.data?.rows ?? []}
      getRowId={(r) => r.symbol}
      total={q.data?.total ?? null}
      loading={q.isLoading}
      error={q.error}
      onRetry={() => void q.refetch()}
      onRowActivate={(r) => onPick(r.symbol)}
      className="min-h-0 flex-1"
      emptyState={<EmptyState title="No near-miss" detail="No close-in-zone candidate fails exactly one strict Squeeze gate." />}
    />
  );
}

const DROP_COLS: DataTableColumn<SetupDroppedRow>[] = [
  { id: 'symbol', header: 'Symbol', accessor: 'symbol', width: 110, cell: (v) => <SymbolWithDeal symbol={String(v)} /> },
  { id: 'scr', header: 'Screener', accessor: 'screener_name', width: 130 },
  { id: 'why', header: 'Why dropped', accessor: 'why', width: 320, grow: true },
  { id: 'close', header: 'Close', accessor: 'close', format: 'num', width: 80 },
  { id: 'ind', header: 'Industry', accessor: 'industry', width: 180 },
];

export function DroppedView({ query, onPick }: { query: Record<string, string | number>; onPick: (s: string) => void }) {
  const q = useApiQuery('setups/dropped', { query: query as never });
  const ctx = (q.data?.meta.context ?? {}) as { previous_session?: string; session_gap_days?: number };
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-3 py-1 text-2xs text-fg-3">
        Left a screener since {fmtDate(ctx.previous_session)}.
        {(ctx.session_gap_days ?? 0) > 7 && (
          <span className="ml-2">
            <DataWarningChip warning={`The previous session is ${ctx.session_gap_days} days earlier; this list compares across a data gap.`} />
          </span>
        )}
      </div>
      <DataTable<SetupDroppedRow>
        label="Why dropped"
        columns={DROP_COLS}
        rows={q.data?.rows ?? []}
        getRowId={(r) => `${r.screener}-${r.symbol}`}
        total={q.data?.total ?? null}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        onRowActivate={(r) => onPick(r.symbol)}
        className="min-h-0 flex-1"
        emptyState={<EmptyState title="Nothing dropped" detail="Every stock from the previous session is still listed." />}
      />
    </div>
  );
}
