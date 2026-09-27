/**
 * Screener → Momentum: the user's main scanner, restored with the old
 * workspace's controls, defaults and outputs (GET /api/v2/screener/momentum):
 * preset buttons, lookback 1–30D, min mcap, volume gate (day / 20D avg / off
 * with 5L–50L presets), 52W distances, EMA / SMA / OHLC / delivery / NR7 /
 * weekly-RSI toggles, debug symbol; rows grouped by coil bucket; top sectors /
 * industries with counts from the filtered list; Copy All to TV, Copy Buckets
 * (###bucket sections), Copy Top Sectors / Industries, per-leader Copy TV.
 *
 * On top: New / Dropped vs the previous session, leader Health + quadrant,
 * per-bucket evidence from past hits, Open bucket in Charts, context chips.
 */
import { BarChart3, LayoutGrid, SlidersHorizontal, Zap } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useApiQuery } from '../api/query';
import type { MomentumEvidenceRow } from '../api/types';
import { contextColumn } from '../context/StockContextChips';
import { useStockContext } from '../context/stockContext';
import { copyText } from '../lib/clipboard';
import { cn } from '../lib/cn';
import { fmtDate, fmtInt, fmtSignedPct } from '../lib/fmt';
import { useTabUrlState } from '../lib/tabUrlState';
import { formatTradingViewList } from '../lib/tradingview';
import { useShell } from '../shell/ShellContext';
import { useAsOf } from '../shell/urlState';
import { Chip } from '../ui/Chip';
import { DataTable, type DataTableGroupBy } from '../ui/DataTable';
import { EmptyState } from '../ui/EmptyState';
import { GlanceBand } from '../ui/GlanceBand';
import { KpiTile } from '../ui/KpiTile';
import { momentumColumns, type MRow } from './momentumColumns';
import {
  BUCKETS,
  BUCKET_LABEL,
  MOMENTUM_DEFAULTS,
  PRESETS,
  bucketChartsHref,
  bucketsTvFromRows,
  coilTone,
  isDefaultState,
  momentumQuery,
  presetPatch,
  type Leader,
  type MomentumContext,
  type MomentumPatch,
  type PresetId,
} from './momentumModel';
import { CopyButton, MomentumDebug, MomentumEvidenceTable, MomentumFilters, MomentumLeaders, evidenceLine } from './MomentumParts';

const EMPTY_ROWS: MRow[] = [];
const EMPTY_LEADERS: Leader[] = [];
const EMPTY_EVIDENCE: MomentumEvidenceRow[] = [];

export default function MomentumView() {
  const shell = useShell();
  const [asOf] = useAsOf();
  const [state, setState] = useTabUrlState('/screener', MOMENTUM_DEFAULTS, 'momentum');
  const [debugInput, setDebugInput] = useState('');
  const [debugSym, setDebugSym] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [droppedOpen, setDroppedOpen] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);

  const query = useMemo(() => momentumQuery(state, debugSym), [state, debugSym]);
  const run = useApiQuery('screener/momentum', { query: query as never }, { keepPrevious: true });
  const evidence = useApiQuery('screener/momentum/evidence', {}, { staleTime: 30 * 60_000 });
  const rows = (run.data?.rows as MRow[] | undefined) ?? EMPTY_ROWS;
  const ctx = (run.data?.meta.context ?? {}) as MomentumContext;
  const evRows = evidence.data?.rows ?? EMPTY_EVIDENCE;
  const evByBucket = useMemo(() => new Map(evRows.map((r) => [r.bucket, r])), [evRows]);
  const evCtx = (evidence.data?.meta.context ?? {}) as { start?: string | null; end?: string | null };
  const isDefault = isDefaultState(state);

  const onChange = useCallback((patch: MomentumPatch) => setState(patch), [setState]);
  const applyPreset = (id: PresetId) => setState(presetPatch(state, id));

  // Quick filters (sector / industry chips) narrow the table; copy buttons keep the old whole-scan semantics.
  const filtered = useMemo(
    () =>
      rows.filter(
        (r) =>
          (!state.msec || (r.sector ?? 'Unclassified') === state.msec) && (!state.mind || (r.industry ?? 'Unclassified') === state.mind),
      ),
    [rows, state.msec, state.mind],
  );

  const rowSyms = useMemo(() => rows.map((r) => r.symbol), [rows]);
  const sctx = useStockContext(rowSyms);
  const watchCtx = useMemo(() => ({ isWatched: shell.isWatched, toggleWatch: shell.toggleWatch }), [shell.isWatched, shell.toggleWatch]);
  const columns = useMemo(() => {
    const cols = momentumColumns(watchCtx);
    const at = cols.findIndex((c) => c.id === 'industry') + 1;
    cols.splice(
      at,
      0,
      contextColumn<MRow>((r) => r.symbol, sctx.map, { width: 170 }),
    );
    return cols;
  }, [watchCtx, sctx.map]);

  const onCopy = useCallback(async (label: string, text: string) => {
    const ok = await copyText(text);
    setCopied(ok ? label : null);
    window.setTimeout(() => setCopied((c) => (c === label ? null : c)), 2000);
  }, []);

  const allTv = useMemo(() => formatTradingViewList([{ symbols: rows.map((r) => r.symbol) }]).text, [rows]);
  const bucketsTv = ctx.buckets_tv ?? bucketsTvFromRows(rows);
  const bucketTv = useMemo(() => new Map((ctx.buckets ?? []).map((b) => [b.bucket, b.tv_str])), [ctx.buckets]);

  const groupBy = useMemo<DataTableGroupBy<MRow> | undefined>(
    () =>
      state.mgrp === '0'
        ? undefined
        : {
            key: (r) => r.bucket ?? 'Below 10EMA',
            order: BUCKETS,
            header: (key, list) => {
              const ev = evidenceLine(evByBucket.get(key));
              const syms = list.map((r) => r.symbol);
              const newCount = list.filter((r) => r.is_new).length;
              return (
                <>
                  <Chip tone={coilTone(key)} size="xs" title={BUCKET_LABEL[key as keyof typeof BUCKET_LABEL]}>
                    {key}
                  </Chip>
                  <span className="num font-semibold text-fg">{list.length}</span>
                  <span className="text-fg-3">{BUCKET_LABEL[key as keyof typeof BUCKET_LABEL]}</span>
                  {newCount > 0 && <span className="text-accent">· {newCount} new</span>}
                  <CopyButton
                    label={`Copy ${key}`}
                    text={formatTradingViewList([{ symbols: syms }]).text || (bucketTv.get(key as never) ?? '')}
                    onCopy={onCopy}
                    copied={copied}
                    small
                    title={`Copy the ${key} bucket as a TradingView list`}
                  />
                  <Link
                    to={bucketChartsHref(key, syms, asOf)}
                    onClick={(e) => e.stopPropagation()}
                    className="flex h-5 shrink-0 items-center gap-1 rounded border border-line px-1.5 text-2xs text-fg-2 hover:text-fg"
                    title="Open this bucket's charts in the Charts tab"
                  >
                    <LayoutGrid className="h-3 w-3" /> Charts
                  </Link>
                  {ev && (
                    <span className="truncate text-2xs text-fg-3" title="Default settings, 5 years of past scanner hits in this bucket">
                      {ev}
                    </span>
                  )}
                </>
              );
            },
          },
    [state.mgrp, evByBucket, onCopy, copied, asOf, bucketTv],
  );

  const onActive = useCallback(
    (r: MRow) => {
      if (!r.symbol) return;
      setActiveId(r.symbol);
      shell.openSymbol(r.symbol);
    },
    [shell],
  );

  const total = run.data?.total ?? null;
  const dropped = ctx.dropped ?? [];
  const sectors = ctx.top_sectors ?? EMPTY_LEADERS;
  const industries = ctx.top_industries ?? EMPTY_LEADERS;
  const loading = run.isLoading;
  const tight = ctx.buckets?.find((b) => b.bucket === '0_2%');
  const evAll = evByBucket.get('All hits');
  const evUni = evByBucket.get('Universe');

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 px-2 pb-1 pt-1">
        <GlanceBand label="Momentum at a glance" compact>
          <KpiTile
            compact
            tone="accent"
            label="Momentum · leaders found"
            value={total}
            format="int"
            caption={run.data?.as_of ? `trigger in last ${query.lookback_days}D · ${fmtDate(run.data.as_of)}` : undefined}
            loading={loading}
            className="!min-w-[200px] !flex-[1.2]"
          />
          <KpiTile
            compact
            label="0–2% coil"
            value={tight ? tight.count : null}
            format="int"
            tone="up"
            caption="tightest to the 10 EMA"
            loading={loading}
          />
          <KpiTile
            compact
            label="New today"
            value={ctx.new_count ?? null}
            format="int"
            tone={ctx.new_count ? 'up' : 'neutral'}
            caption={ctx.previous_session ? `not listed on ${fmtDate(ctx.previous_session)}` : undefined}
            loading={loading}
          />
          <KpiTile
            compact
            label="Dropped"
            value={loading ? null : dropped.length}
            format="int"
            tone={dropped.length ? 'warn' : 'neutral'}
            caption="left the list since the previous session"
            loading={loading}
          />
          <KpiTile
            compact
            label="Top sector"
            value={sectors[0] ? <span className="text-title text-fg">{sectors[0].sector}</span> : null}
            caption={sectors[0] ? `${fmtInt(sectors[0].stock_count)} of ${fmtInt(total)} in the scan` : undefined}
            loading={loading}
            className="!min-w-[200px] !flex-[1.4]"
          />
          <KpiTile
            compact
            label="Evidence · 20D avg"
            value={
              evAll && evAll.avg_20 != null ? (
                <span className={evAll.avg_20 > 0 ? 'text-up' : 'text-down'}>{fmtSignedPct(evAll.avg_20, 1)}</span>
              ) : null
            }
            caption={
              evAll && evUni
                ? `past hits vs ${fmtSignedPct(evUni.avg_20, 1)} for all ≥ ₹1,000 Cr · n=${fmtInt(evAll.n_20)}`
                : 'computing from 5 years of history…'
            }
            hint="Forward 20-session return after past default-setting scanner hits (5 years, point-in-time). Click Evidence for the per-bucket table."
            loading={evidence.isLoading}
            onClick={() => setEvidenceOpen((o) => !o)}
            selected={evidenceOpen}
          />
        </GlanceBand>
      </div>

      {/* preset buttons + actions (old top bar) */}
      <div className="flex min-h-8 shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-line bg-surface px-3 py-1 text-xs">
        <span
          className="flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide text-accent"
          title="Quick settings (same as before): they set some filters and leave the rest"
        >
          <Zap className="h-3.5 w-3.5" /> Presets
        </span>
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => applyPreset(p.id)}
            className="h-6 whitespace-nowrap rounded border border-line px-2 text-fg-2 hover:border-accent hover:text-fg"
          >
            {p.label}
          </button>
        ))}
        <button type="button" onClick={() => applyPreset('clear')} className="px-1 text-down hover:underline">
          Clear all
        </button>
        {!isDefault && (
          <button
            type="button"
            onClick={() => applyPreset('defaults')}
            className="px-1 text-accent hover:underline"
            title="Back to the scanner defaults"
          >
            Defaults
          </button>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {run.data && (
            <span className="num text-fg-2">
              <span className="font-semibold text-fg">{fmtInt(total)}</span> leaders found
              {filtered.length !== rows.length && <span className="text-fg-3"> · {filtered.length} shown</span>}
            </span>
          )}
          {ctx.new_count != null && (
            <Chip
              tone={ctx.new_count ? 'accent' : 'neutral'}
              size="xs"
              title={`Listed on ${fmtDate(run.data?.as_of)} but not on ${fmtDate(ctx.previous_session)}`}
            >
              {ctx.new_count} new
            </Chip>
          )}
          <div className="relative">
            <Chip
              tone={dropped.length ? 'warn' : 'neutral'}
              size="xs"
              onClick={() => setDroppedOpen((o) => !o)}
              selected={droppedOpen}
              title={`Listed on ${fmtDate(ctx.previous_session)} but not today`}
            >
              {dropped.length} dropped
            </Chip>
            {droppedOpen && dropped.length > 0 && (
              <div className="absolute right-0 top-full z-30 mt-1 max-h-64 w-72 overflow-auto rounded-md border border-line-strong bg-surface-2 p-1 shadow-2xl">
                <div className="px-1 pb-1 text-2xs text-fg-3">As of {fmtDate(ctx.previous_session)} — click to inspect or debug</div>
                {dropped.map((d) => (
                  <button
                    key={d.symbol}
                    type="button"
                    onClick={() => {
                      if (d.symbol) {
                        shell.openSymbol(d.symbol);
                        setDebugInput(d.symbol);
                        setDebugSym(d.symbol);
                      }
                      setDroppedOpen(false);
                    }}
                    className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs hover:bg-surface-3"
                  >
                    <span className="w-24 font-mono text-fg">{d.symbol}</span>
                    <span className="w-14 text-fg-3">{d.bucket ?? '—'}</span>
                    <span className="truncate text-fg-3">{d.industry ?? '—'}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <CopyButton
            label="Copy Buckets"
            text={bucketsTv}
            onCopy={onCopy}
            copied={copied}
            primary
            title="Copy the list split into coil buckets (###0_2%, ###2_5%, …) — pastes into TradingView as sections"
          />
          <CopyButton
            label="Copy All to TV"
            text={allTv}
            onCopy={onCopy}
            copied={copied}
            primary
            title="Copy every symbol in the scan as a TradingView list"
          />
          <button
            type="button"
            onClick={() => setEvidenceOpen((o) => !o)}
            aria-pressed={evidenceOpen}
            className={cn(
              'flex h-6 items-center gap-1 rounded border px-2',
              evidenceOpen ? 'border-accent text-accent' : 'border-line text-fg-2 hover:text-fg',
            )}
          >
            <BarChart3 className="h-3 w-3" /> Evidence
          </button>
          <button
            type="button"
            onClick={() => setState({ mgrp: state.mgrp === '0' ? '1' : '0' })}
            aria-pressed={state.mgrp !== '0'}
            className={cn(
              'h-6 rounded border px-2',
              state.mgrp !== '0' ? 'border-accent text-accent' : 'border-line text-fg-2 hover:text-fg',
            )}
            title="Group rows by coil bucket"
          >
            Group
          </button>
          <button
            type="button"
            onClick={() => setState({ mpanel: state.mpanel === '0' ? '1' : '0' })}
            className="flex h-6 items-center gap-1 rounded border border-line px-2 text-fg-2 hover:text-fg"
          >
            <SlidersHorizontal className="h-3 w-3" /> {state.mpanel === '0' ? 'Show filters' : 'Hide filters'}
          </button>
        </div>
      </div>

      {state.mpanel !== '0' && (
        <MomentumFilters
          state={state}
          onChange={onChange}
          debugInput={debugInput}
          onDebugInput={setDebugInput}
          onDebugSubmit={() => setDebugSym(debugInput.trim() ? debugInput.trim().toUpperCase() : null)}
        />
      )}

      {debugSym && ctx.debug && (
        <MomentumDebug
          symbol={ctx.debug.symbol}
          checks={ctx.debug.checks}
          inList={ctx.debug.in_list}
          onClose={() => {
            setDebugSym(null);
            setDebugInput('');
          }}
        />
      )}

      {evidenceOpen && (
        <MomentumEvidenceTable
          rows={evRows}
          start={evCtx.start}
          end={evCtx.end}
          notes={evidence.data?.meta.notes ?? []}
          isDefault={isDefault}
          onClose={() => setEvidenceOpen(false)}
        />
      )}

      {!loading && rows.length > 0 && !debugSym && (
        <MomentumLeaders
          sectors={sectors}
          industries={industries}
          distribution={ctx.sector_distribution ?? EMPTY_LEADERS}
          total={rows.length}
          sectorFilter={state.msec}
          industryFilter={state.mind}
          onSector={(s) => setState({ msec: s, mind: null })}
          onIndustry={(s) => setState({ mind: s, msec: null })}
          onCopy={onCopy}
          copied={copied}
        />
      )}

      <div className="flex min-h-0 flex-1 flex-col">
        <DataTable<MRow>
          label="Momentum scanner"
          columns={columns}
          rows={filtered}
          getRowId={(r, i) => r.symbol ?? `row-${i}`}
          total={filtered.length !== rows.length ? filtered.length : total}
          loading={run.isFetching}
          error={run.error}
          onRetry={() => void run.refetch()}
          activeRowId={activeId}
          onActiveRowChange={onActive}
          onRowClick={onActive}
          onRowActivate={(r) => r.symbol && shell.openStockPage(r.symbol)}
          groupBy={groupBy}
          className="min-h-0 flex-1"
          emptyState={
            <EmptyState
              title="No momentum candidates"
              detail={
                debugSym
                  ? `${debugSym} does not pass — see the conditions above.`
                  : 'Nothing matches these filters on this session. Try easing the 52W-high distance or the stack conditions, or widen the lookback.'
              }
            />
          }
        />
      </div>
    </div>
  );
}
