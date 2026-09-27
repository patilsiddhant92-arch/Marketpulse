/**
 * Screener (spec 7.3) — Momentum + VCP Workbench merged.
 *
 * Server-side presets (replace, never stack) with their rules as editable
 * chips; custom rules; fail-closed floors; taxonomy group filter; history
 * columns; New / Dropped vs the previous session; rule debugger ("why is X not
 * in the list?"); VCP geometry for the focused row; evidence per preset;
 * TradingView export and Open in Charts. Honours as_of time travel.
 */
import { Bug, Copy, LayoutGrid } from 'lucide-react';
import { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useApiQuery } from '../api/query';
import type { PresetRow } from '../api/types';
import { chartsHref } from '../charts/sources';
import { copyText } from '../lib/clipboard';
import { cn } from '../lib/cn';
import { fmtDate, fmtInt } from '../lib/fmt';
import { useTabUrlState } from '../lib/tabUrlState';
import { formatTradingViewList } from '../lib/tradingview';
import { queueColumns, ruleColumns, type SRow } from '../screener/columns';
import { FilterBar } from '../screener/FilterBar';
import {
  SCREENER_DEFAULTS,
  decodeRules,
  describeFloors,
  encodeRules,
  lookbackDays,
  presetRules,
  runQuery,
  sameRules,
  saveLastRun,
  type Rule,
  type RuleField,
} from '../screener/model';
import { RuleBar } from '../screener/RuleBar';
import { RuleDebugger } from '../screener/RuleDebugger';
import { VcpDetail } from '../screener/VcpDetail';
import { useShell } from '../shell/ShellContext';
import { Chip } from '../ui/Chip';
import { DataTable } from '../ui/DataTable';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { Skeleton } from '../ui/Skeleton';
import { Tooltip } from '../ui/Tooltip';

const EMPTY_ROWS: SRow[] = [];
const EMPTY_PRESETS: PresetRow[] = [];
const EMPTY_FIELDS: RuleField[] = [];
const CATEGORY_ORDER = ['Trend', 'Highs', 'Coil', 'Momentum', 'Setups', 'Lab'];

interface DroppedRow {
  symbol: string | null;
  close: number | null;
  rs_percentile: number | null;
  industry: string | null;
}
interface RunContext {
  preset?: string | null;
  new_count?: number;
  dropped?: DroppedRow[];
  previous_session?: string | null;
  delegated_to?: string;
}

export default function ScreenerRoute() {
  const shell = useShell();
  const navigate = useNavigate();
  const location = useLocation();
  const [state, setState, active] = useTabUrlState('/screener', SCREENER_DEFAULTS);
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [debugOpen, setDebugOpen] = useState(false);
  const [debugSym, setDebugSym] = useState('');
  const [droppedOpen, setDroppedOpen] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sorted, setSorted] = useState<SRow[]>([]);
  const [copied, setCopied] = useState<string | null>(null);

  // ---- presets + rule catalog
  const presetsQ = useApiQuery('screener/presets', {}, { staleTime: Infinity });
  const presets = presetsQ.data?.rows ?? EMPTY_PRESETS;
  const fields = ((presetsQ.data?.meta.context as { fields?: RuleField[] } | undefined)?.fields ?? EMPTY_FIELDS) as RuleField[];
  const fieldMap = useMemo(() => new Map(fields.map((f) => [f.field, f])), [fields]);
  const preset = presets.find((p) => p.id === state.preset);
  const isQueue = preset?.kind === 'queue';
  const baseRules = useMemo(() => presetRules(preset), [preset]);
  const customRules = decodeRules(state.rules);
  const rules: Rule[] = customRules ?? baseRules;
  const custom = customRules !== null && !sameRules(customRules, baseRules);
  const queuePresetActive = isQueue && !custom && customRules === null;

  // ---- run
  const query = useMemo(() => runQuery(state), [state]);
  const run = useApiQuery('screener/run', { query: query as never }, { enabled: presets.length > 0 && preset?.available !== false });
  const rows = (run.data?.rows as SRow[] | undefined) ?? EMPTY_ROWS;
  const ctx = (run.data?.meta.context ?? {}) as RunContext;
  const unavailable = run.data?.meta.status === 'unavailable';

  // Custom rules or non-default floors: remember the run so Charts can show it ("Screener · last custom run").
  const tweaked =
    custom || (['mcap', 'price', 'vol', 'avgvol', 'lb', 'ipo', 'level', 'group'] as const).some((k) => state[k] !== SCREENER_DEFAULTS[k]);
  useEffect(() => {
    if (tweaked && run.data && !unavailable) saveLastRun({ label: `${custom ? 'custom rules' : 'custom floors'} on ${preset?.label ?? state.preset}`, query });
  }, [tweaked, custom, run.data, unavailable, preset, state.preset, query]);

  const evidence = useApiQuery('evidence/{setup}', { params: { setup: state.preset } }, { enabled: !!preset && !custom });

  const filtered = useMemo(() => {
    const q = deferredSearch.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        (r.symbol ?? '').toLowerCase().includes(q) ||
        (r.security_name ?? '').toLowerCase().includes(q) ||
        (r.industry ?? '').toLowerCase().includes(q),
    );
  }, [rows, deferredSearch]);

  const symbolsInList = useMemo(() => new Set(rows.map((r) => r.symbol)), [rows]);
  const lookback = lookbackDays(state) > 1;
  const watchCtx = useMemo(() => ({ isWatched: shell.isWatched, toggleWatch: shell.toggleWatch }), [shell.isWatched, shell.toggleWatch]);
  const columns = useMemo(
    () => (queuePresetActive ? queueColumns(watchCtx, preset?.queue) : ruleColumns(watchCtx, lookback)),
    [queuePresetActive, preset?.queue, lookback, watchCtx],
  );
  const activeRow = activeId ? rows.find((r) => r.symbol === activeId) : undefined;

  // Keep the debugger on the focused / sidecar symbol unless the user typed one.
  useEffect(() => {
    if (active && shell.symbol && !debugSym) setDebugSym(shell.symbol);
  }, [active, shell.symbol, debugSym]);

  const selectPreset = (id: string) => {
    setState({ preset: id, rules: null });
    setActiveId(null);
  };
  const setRules = (next: Rule[]) => setState({ rules: sameRules(next, baseRules) ? null : encodeRules(next) });

  const onActive = useCallback(
    (r: SRow) => {
      if (!r.symbol) return;
      setActiveId(r.symbol);
      shell.openSymbol(r.symbol);
      setDebugSym(r.symbol);
    },
    [shell],
  );

  const copyTv = async () => {
    const title = custom ? 'Screener custom' : (preset?.label ?? 'Screener');
    const { text, count } = formatTradingViewList([{ title, symbols: sorted.map((r) => r.symbol) }]);
    const ok = await copyText(text);
    setCopied(ok ? `Copied ${count} symbols` : 'Copy failed');
    window.setTimeout(() => setCopied(null), 2500);
  };
  const openInCharts = () => {
    navigate(chartsHref(location.search, tweaked ? 'screener:custom' : `screener:${state.preset}`));
  };

  const categories = useMemo(() => {
    const by = new Map<string, PresetRow[]>();
    for (const p of presets) {
      const c = p.category ?? 'Other';
      by.set(c, [...(by.get(c) ?? []), p]);
    }
    return [...by.entries()].sort((a, b) => CATEGORY_ORDER.indexOf(a[0]) - CATEGORY_ORDER.indexOf(b[0]));
  }, [presets]);

  const floors = describeFloors(state, queuePresetActive);
  const dropped = ctx.dropped ?? [];
  const evRow = evidence.data?.rows[0];

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* presets */}
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-3 py-1.5" role="tablist" aria-label="Screener presets">
        {presetsQ.isLoading && <Skeleton width={480} height={18} />}
        {presetsQ.error && <ErrorState error={presetsQ.error} onRetry={() => void presetsQ.refetch()} compact />}
        {categories.map(([cat, list]) => (
          <div key={cat} className="flex shrink-0 items-center gap-1">
            <span className="mr-0.5 text-2xs uppercase tracking-wide text-fg-3">{cat}</span>
            {list.map((p) => (
              <Tooltip key={p.id} content={<div className="max-w-xs">{p.description}{!p.available && <div className="mt-1 text-warn">Not ported to v2 yet.</div>}</div>}>
                <button
                  type="button"
                  role="tab"
                  aria-selected={state.preset === p.id}
                  disabled={!p.available}
                  onClick={() => selectPreset(p.id)}
                  className={cn(
                    'whitespace-nowrap rounded border px-2 py-0.5 text-xs',
                    state.preset === p.id
                      ? 'border-accent bg-accent/15 text-accent'
                      : 'border-line text-fg-2 hover:border-line-strong hover:text-fg',
                    !p.available && 'cursor-not-allowed opacity-40',
                  )}
                >
                  {p.label}
                </button>
              </Tooltip>
            ))}
          </div>
        ))}
      </div>

      <RuleBar
        rules={rules}
        fields={fields}
        custom={custom}
        disabled={queuePresetActive}
        disabledNote={`${preset?.label ?? ''} uses the Desk queue's own predicate (${preset?.description ?? ''}) — not editable here. Use the debugger to see why a stock is in or out.`}
        onChange={setRules}
        onReset={() => setState({ rules: null })}
      />
      <FilterBar state={state} queuePreset={queuePresetActive} onChange={setState} search={search} onSearch={setSearch} />

      {/* summary + actions */}
      <div className="flex min-h-8 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-3 py-1 text-xs">
        {run.isLoading ? (
          <span className="text-fg-3">
            Running{queuePresetActive ? ' — the first Desk-queue call of a session computes live and can take 10–30 s' : '…'}
          </span>
        ) : run.data && !unavailable ? (
          <>
            <span className="text-fg">
              <span className="num font-semibold">{fmtInt(run.data.total)}</span> match{run.data.total === 1 ? '' : 'es'}
              {deferredSearch && (
                <span className="text-fg-3">
                  {' '}
                  · <span className="num">{filtered.length}</span> after filter
                </span>
              )}
              {run.data.returned !== run.data.total && <span className="text-warn"> · {run.data.returned} returned (paged)</span>}
            </span>
            <span className="text-fg-3">as of {fmtDate(run.data.as_of)}</span>
            {ctx.new_count != null && (
              <Chip tone={ctx.new_count ? 'accent' : 'neutral'} size="xs" title={`Matched on ${fmtDate(run.data.as_of)} but not on ${fmtDate(ctx.previous_session)}`}>
                {ctx.new_count} new
              </Chip>
            )}
            <div className="relative">
              <Chip
                tone={dropped.length ? 'warn' : 'neutral'}
                size="xs"
                onClick={() => setDroppedOpen((o) => !o)}
                selected={droppedOpen}
                title={`Matched on ${fmtDate(ctx.previous_session)} but not today`}
              >
                {dropped.length} dropped
              </Chip>
              {droppedOpen && dropped.length > 0 && (
                <div className="absolute left-0 top-full z-30 mt-1 max-h-64 w-72 overflow-auto rounded-md border border-line-strong bg-surface-2 p-1 shadow-2xl">
                  <div className="px-1 pb-1 text-2xs text-fg-3">Shown as of {fmtDate(ctx.previous_session)} — click to inspect or debug</div>
                  {dropped.map((d) => (
                    <button
                      key={d.symbol}
                      type="button"
                      onClick={() => {
                        if (d.symbol) {
                          shell.openSymbol(d.symbol);
                          setDebugSym(d.symbol);
                          setDebugOpen(true);
                        }
                        setDroppedOpen(false);
                      }}
                      className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs hover:bg-surface-3"
                    >
                      <span className="w-24 font-mono text-fg">{d.symbol}</span>
                      <span className="num w-10 text-right text-fg-2">{d.rs_percentile ?? '—'}</span>
                      <span className="truncate text-fg-3">{d.industry ?? '—'}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            {floors.length > 0 && <span className="text-fg-3">{floors.join(' · ')}</span>}
            {run.data.meta.status === 'partial' && run.data.meta.reason && (
              <span className="text-warn" title={run.data.meta.reason}>
                partial: {run.data.meta.reason}
              </span>
            )}
          </>
        ) : null}
        <span className="text-fg-3" title={evidence.data?.meta.reason ?? undefined}>
          Evidence:{' '}
          {custom
            ? 'custom rules have no stored outcomes'
            : evidence.data?.meta.status === 'unavailable'
              ? 'not built yet'
              : evRow
                ? evRow.insufficient_sample
                  ? `insufficient sample (n=${evRow.n})`
                  : `hit +2R ${evRow.hit_rate_2r ?? '—'}% · avg ${evRow.avg_r ?? '—'}R · n=${evRow.n}`
                : '—'}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          {copied && <span className="text-2xs text-fg-3">{copied}</span>}
          <button type="button" onClick={() => setDebugOpen((o) => !o)} aria-pressed={debugOpen} className={cn('flex items-center gap-1 rounded border px-2 py-0.5', debugOpen ? 'border-accent text-accent' : 'border-line text-fg-2 hover:text-fg')}>
            <Bug className="h-3 w-3" /> Why not?
          </button>
          <button type="button" onClick={() => void copyTv()} disabled={!sorted.length} className="flex items-center gap-1 rounded border border-line px-2 py-0.5 text-fg-2 hover:text-fg disabled:opacity-40" title="Copy the visible rows (current sort / filter) as a TradingView watchlist">
            <Copy className="h-3 w-3" /> TradingView
          </button>
          <button type="button" onClick={openInCharts} disabled={!rows.length} className="flex items-center gap-1 rounded border border-line px-2 py-0.5 text-fg-2 hover:text-fg disabled:opacity-40">
            <LayoutGrid className="h-3 w-3" /> Open in Charts
          </button>
        </div>
      </div>

      {debugOpen && (
        <RuleDebugger
          symbol={debugSym}
          onSymbol={(s) => {
            setDebugSym(s);
            shell.openSymbol(s);
          }}
          query={query}
          inList={(s) => symbolsInList.has(s)}
          fieldLabel={(f) => fieldMap.get(f)?.label ?? f}
          onClose={() => setDebugOpen(false)}
        />
      )}

      <div className="flex min-h-0 flex-1 flex-col">
        {unavailable ? (
          <EmptyState title="Not available" detail={run.data?.meta.reason ?? 'This preset is not available.'} />
        ) : (
          <DataTable<SRow>
            label={`Screener: ${preset?.label ?? state.preset}`}
            columns={columns}
            rows={filtered}
            getRowId={(r, i) => r.symbol ?? `row-${i}`}
            total={deferredSearch ? filtered.length : run.data?.total ?? null}
            loading={run.isLoading || presetsQ.isLoading}
            error={run.error}
            onRetry={() => void run.refetch()}
            activeRowId={activeId}
            onActiveRowChange={onActive}
            onRowClick={onActive}
            onRowActivate={(r) => r.symbol && shell.openStockPage(r.symbol)}
            onSortedRowsChange={setSorted}
            className="min-h-0 flex-1"
            emptyState={
              <EmptyState
                title="Nothing matched"
                detail={
                  <>
                    No stock passed every rule and floor on {fmtDate(run.data?.as_of)}. Loosen a rule chip, lower a floor, widen the lookback — or use{' '}
                    <button type="button" className="text-accent underline" onClick={() => setDebugOpen(true)}>
                      Why not?
                    </button>{' '}
                    on a stock you expected.
                  </>
                }
              />
            }
          />
        )}
        {queuePresetActive && preset?.queue === 'vcp' && activeRow && <VcpDetail row={activeRow} />}
      </div>
    </div>
  );
}
