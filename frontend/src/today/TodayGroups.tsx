/**
 * Groups › Today — which groups moved today and why, at the selected taxonomy level and floor.
 * Table: 1D equal-weight return, breadth, turnover / delivery vs 20 days, concentration, contributors,
 * participation, 5d / 21d persistence, rank; side panel: the fact-only "why", contributors and
 * detractors (click → Stock 360), deals, catalysts, drill + charts.
 */
import { ChevronRight, LineChart } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useApiQuery } from '../api/query';
import type { TodayContributor, TodayGroupRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtDate, fmtInt, fmtNum, fmtSigned, fmtSignedPct } from '../lib/fmt';
import { TvCopyBar } from '../routes/deals/TvCopy';
import { chartsSourceHref, type Floor, type Level } from '../routes/groups/groupsModel';
import { MetricInline, RankDelta, SourceNote, ZoneNum } from '../routes/groups/kit';
import { useShell } from '../shell/ShellContext';
import { useAsOf } from '../shell/urlState';
import { Chip } from '../ui/Chip';
import { DataTable, type DataTableColumn } from '../ui/DataTable';
import { EmptyState } from '../ui/EmptyState';
import { ChangeCell } from './parts';
import { BREADTH_TONE, PARTICIPATION_TONE, PERSISTENCE_TONE, clauseText, filterGroupsText, type RuleClause } from './todayModel';

const EMPTY: TodayGroupRow[] = [];

function columns(onDrill: (id: string) => void): DataTableColumn<TodayGroupRow>[] {
  return [
    { id: 'rank_1d', header: '#', accessor: 'rank_1d', format: 'int', width: 40, sticky: true, sortDescFirst: false, headerTitle: "Rank by today's return (groups with ≥ 3 members)" },
    {
      id: 'group_name',
      header: 'Group',
      accessor: 'group_name',
      width: 210,
      sticky: true,
      cell: (_v, r) => (
        <span className="flex min-w-0 items-center gap-1">
          <button
            type="button"
            className="min-w-0 truncate text-left text-fg hover:text-accent hover:underline"
            onClick={(e) => {
              e.stopPropagation();
              onDrill(r.id);
            }}
            title={`Drill into ${r.group_name}`}
          >
            {r.group_name}
          </button>
          {r.breadth_label && r.breadth_label !== 'mixed' && <Chip tone={BREADTH_TONE[r.breadth_label] ?? 'neutral'}>{r.breadth_label}</Chip>}
        </span>
      ),
    },
    { id: 'ret', header: '1D', accessor: 'return_1d', format: 'signedPct', width: 62, metricKey: 'group_return_1d', cell: (v) => <ChangeCell v={v as number} /> },
    {
      id: 'pct_up',
      header: 'Up %',
      accessor: 'pct_up',
      format: 'pct',
      digits: 0,
      width: 58,
      metricKey: 'group_pct_up_today',
      cell: (v, r) => (
        <span title={`${r.advancers ?? 0} up · ${r.decliners ?? 0} down of ${r.stocks_with_return}`}>
          <ZoneNum metricKey="group_pct_up_today" value={v as number} format="pct" digits={0} />
        </span>
      ),
    },
    { id: 'up2', header: '>+2%', accessor: 'pct_up_2', format: 'pct', digits: 0, width: 52, headerTitle: '% of members up more than 2%' },
    { id: 'dn2', header: '<−2%', accessor: 'pct_down_2', format: 'pct', digits: 0, width: 52, headerTitle: '% of members down more than 2%' },
    { id: 'to_x', header: 'T/O ×', accessor: 'turnover_vs_20d', format: 'num', digits: 2, width: 58, metricKey: 'group_turnover_vs_20d', cell: (v) => <ZoneNum metricKey="group_turnover_vs_20d" value={v as number} digits={2} /> },
    { id: 'dl_x', header: 'Deliv ×', accessor: 'delivery_vs_20d', format: 'num', digits: 2, width: 60, metricKey: 'group_delivery_vs_20d', cell: (v) => <ZoneNum metricKey="group_delivery_vs_20d" value={v as number} digits={2} /> },
    { id: 'top1', header: 'Top-1', accessor: 'top1_share_pct', format: 'pct', digits: 0, width: 54, metricKey: 'move_concentration', cell: (v) => <ZoneNum metricKey="move_concentration" value={v as number} format="pct" digits={0} /> },
    {
      id: 'led',
      header: 'Led by',
      accessor: (r) => r.top_contributors?.[0]?.symbol ?? null,
      width: 200,
      headerTitle: 'Top contributors to the move (change %)',
      cell: (_v, r) => (
        <span className="truncate font-mono text-2xs text-fg-2">
          {(r.top_contributors ?? [])
            .slice(0, 3)
            .map((c) => `${c.symbol} ${fmtSignedPct(c.change_1d_pct, 1)}`)
            .join('  ')}
        </span>
      ),
    },
    {
      id: 'part',
      header: 'Participation',
      accessor: 'participation',
      width: 150,
      headerTitle: 'From turnover × and delivery × (rules in the side panel)',
      cell: (_v, r) => <Chip tone={PARTICIPATION_TONE[r.participation_id ?? ''] ?? 'neutral'}>{r.participation}</Chip>,
    },
    { id: 'r5', header: '5D', accessor: 'return_5d', format: 'signedPct', width: 58, cell: (v) => <ChangeCell v={v as number} digits={1} /> },
    { id: 'r21', header: '21D', accessor: 'return_21d', format: 'signedPct', width: 58, metricKey: 'group_return_ew_21d', cell: (v) => <ChangeCell v={v as number} digits={1} /> },
    {
      id: 'pers',
      header: 'Pop or trend',
      accessor: 'persistence',
      width: 104,
      metricKey: 'group_move_persistence',
      cell: (_v, r) => <Chip tone={PERSISTENCE_TONE[r.persistence_id ?? ''] ?? 'neutral'}>{r.persistence}</Chip>,
    },
    { id: 'rank', header: 'Rank', accessor: 'rank', format: 'int', width: 50, sortDescFirst: false, metricKey: 'group_rank' },
    { id: 'rank_d5', header: 'Δ5', accessor: 'rank_delta_5', format: 'int', width: 46, metricKey: 'group_rank_delta_5', cell: (v) => <RankDelta value={v as number} /> },
    {
      id: 'deals',
      header: 'Deals',
      accessor: 'deal_net_cr',
      format: 'signed',
      digits: 1,
      width: 80,
      headerTitle: 'Bulk/block deals today in the group: net buyers / sellers (≥ ₹0.1 Cr net each), net ₹ Cr, PROP excluded',
      renderNull: true,
      cell: (_v, r) =>
        r.deal_buyers || r.deal_sellers ? (
          <span className="num text-2xs">
            <span className="text-up">{r.deal_buyers}B</span>/<span className="text-down">{r.deal_sellers}S</span>{' '}
            <span className={cn((r.deal_net_cr ?? 0) >= 0 ? 'text-up' : 'text-down')}>{fmtSigned(r.deal_net_cr, 1)}</span>
          </span>
        ) : (
          <span className="text-fg-3">—</span>
        ),
    },
    {
      id: 'cat',
      header: 'Catalysts',
      accessor: (r) => (r.results_nearby_n ?? 0) + (r.news_today_n ?? 0) || null,
      width: 84,
      headerTitle: 'Members with results within 5 sessions · members with news today',
      renderNull: true,
      cell: (_v, r) =>
        r.results_nearby_n || r.news_today_n ? (
          <span className="text-2xs text-fg-2" title={Object.entries(r.news_types ?? {}).map(([k, v]) => `${k}: ${v}`).join('\n') || undefined}>
            {r.results_nearby_n ? `${r.results_nearby_n} res` : ''}
            {r.results_nearby_n && r.news_today_n ? ' · ' : ''}
            {r.news_today_n ? `${r.news_today_n} news` : ''}
          </span>
        ) : (
          <span className="text-fg-3">—</span>
        ),
    },
    { id: 'stocks', header: 'Stocks', accessor: 'stocks', format: 'int', width: 56 },
    { id: 'to', header: 'T/O ₹Cr', accessor: 'turnover_cr', format: 'num', digits: 0, width: 70, defaultHidden: true },
  ];
}

function ContribList({ title, items, tone }: { title: string; items: readonly TodayContributor[]; tone: 'up' | 'down' }) {
  const shell = useShell();
  if (!items.length) return null;
  return (
    <div>
      <div className={cn('mb-0.5 text-2xs font-semibold uppercase tracking-wide', tone === 'up' ? 'text-fg-2' : 'text-fg-3')}>{title}</div>
      <table className="w-full text-2xs">
        <thead className="text-fg-3">
          <tr>
            <th className="text-left font-normal">Stock</th>
            <th className="text-right font-normal">Chg</th>
            <th className="text-right font-normal" title="Points of the equal-weight group return">Contrib</th>
            <th className="text-right font-normal" title="Share of the group move">Share</th>
            <th className="text-right font-normal" title="Equal weight in the group">Wt</th>
            <th className="text-right font-normal">RVOL</th>
            <th className="text-right font-normal">Deliv×</th>
          </tr>
        </thead>
        <tbody>
          {items.map((c) => (
            <tr key={c.symbol} className={cn('hover:bg-surface-2', shell.symbol === c.symbol && 'bg-accent/10')}>
              <td>
                <button type="button" className="font-mono font-semibold text-fg hover:text-accent hover:underline" onClick={() => shell.openSymbol(c.symbol)} onDoubleClick={() => shell.openStockPage(c.symbol)}>
                  {c.symbol}
                </button>
              </td>
              <td className="text-right">
                <ChangeCell v={c.change_1d_pct} digits={1} />
              </td>
              <td className="num text-right text-fg-2">{fmtSigned(c.contribution, 2)}</td>
              <td className="num text-right text-fg-2">{c.share_of_move_pct != null ? `${fmtNum(c.share_of_move_pct, 0)}%` : '—'}</td>
              <td className="num text-right text-fg-3">{fmtNum(c.weight_pct, 1)}%</td>
              <td className="text-right">
                <ZoneNum metricKey="rvol" value={c.rvol} digits={2} />
              </td>
              <td className="text-right">
                <ZoneNum metricKey="delivery_vs_20d" value={c.delivery_vs_20d} digits={2} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface RulesCtx {
  breadth_rules?: { one_stock_share: number; broad_pct: number; min_members: number };
  participation_rules?: { id: string; phrase: string; when: RuleClause[] }[];
  persistence_rules?: { id: string; label: string; when: RuleClause[] }[];
}

function Detail({ g, ctx, onDrill }: { g: TodayGroupRow; ctx: RulesCtx | undefined; onDrill: (id: string) => void }) {
  const [asOf] = useAsOf();
  return (
    <div className="space-y-3 p-3" aria-label={`${g.group_name} today`} role="region">
      <div className="flex flex-wrap items-center gap-1.5">
        <h3 className="text-sm font-semibold text-fg">{g.group_name}</h3>
        <ChangeCell v={g.return_1d} />
        {g.breadth_label && <Chip tone={BREADTH_TONE[g.breadth_label] ?? 'neutral'}>{g.breadth_label}</Chip>}
        {g.persistence && <Chip tone={PERSISTENCE_TONE[g.persistence_id ?? ''] ?? 'neutral'}>{g.persistence}</Chip>}
      </div>
      {g.why ? (
        <p className="rounded border border-line bg-surface-2 p-2 text-xs leading-relaxed text-fg" data-testid="group-why">
          {g.why}
        </p>
      ) : (
        <p className="text-2xs text-fg-3">No return for this group today.</p>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        <MetricInline metricKey="group_pct_up_today" label="Up today" value={g.pct_up}>
          <span className="num text-xs text-fg">
            {fmtNum(g.pct_up, 0)}% <span className="text-fg-3">({g.advancers}/{g.stocks_with_return})</span>
          </span>
        </MetricInline>
        <MetricInline metricKey="group_turnover_vs_20d" label="Turnover ×" value={g.turnover_vs_20d}>
          <ZoneNum metricKey="group_turnover_vs_20d" value={g.turnover_vs_20d} digits={2} className="text-xs" />
        </MetricInline>
        <MetricInline metricKey="group_delivery_vs_20d" label="Delivery ×" value={g.delivery_vs_20d}>
          <ZoneNum metricKey="group_delivery_vs_20d" value={g.delivery_vs_20d} digits={2} className="text-xs" />
        </MetricInline>
        <MetricInline metricKey="move_concentration" label="Top-1 share" value={g.top1_share_pct}>
          <ZoneNum metricKey="move_concentration" value={g.top1_share_pct} format="pct" digits={0} className="text-xs" />
        </MetricInline>
        <MetricInline metricKey="group_move_persistence" label="5d / 21d">
          <span className="num text-xs">
            <ChangeCell v={g.return_5d} digits={1} /> / <ChangeCell v={g.return_21d} digits={1} />
          </span>
        </MetricInline>
        <MetricInline metricKey="group_rank" label="Rank · Δ5 · today">
          <span className="num text-xs text-fg">
            {fmtInt(g.rank)}
            {g.rank_n ? <span className="text-fg-3">/{g.rank_n}</span> : null} <RankDelta value={g.rank_delta_5} /> · #{fmtInt(g.rank_1d)}
          </span>
        </MetricInline>
      </div>
      <ContribList title={`Drove the move (${(g.return_1d ?? 0) >= 0 ? 'up' : 'down'})`} items={g.top_contributors ?? []} tone="up" />
      <ContribList title="Pulled the other way" items={g.top_detractors ?? []} tone="down" />
      <div className="space-y-0.5 text-2xs text-fg-2">
        <div>
          Deals today: {g.deal_stocks ? `${g.deal_stocks} stock(s) with prints · ${g.deal_buyers} net buyer(s) · ${g.deal_sellers} net seller(s) · net ${fmtSigned(g.deal_net_cr, 1)} ₹Cr (PROP excluded)` : 'none'}
        </div>
        <div>
          Catalysts: {g.results_nearby_n ? `${g.results_nearby_n} with results within 5 sessions` : 'no results within 5 sessions'}
          {Object.keys(g.news_types ?? {}).length ? ` · news today: ${Object.entries(g.news_types ?? {}).map(([k, v]) => `${k} ${v}`).join(', ')}` : ''}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-2">
        <button type="button" onClick={() => onDrill(g.id)} className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
          Drill into group <ChevronRight className="h-3 w-3" />
        </button>
        <Link to={chartsSourceHref(g.id, g.symbols ?? [], asOf)} className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
          <LineChart className="h-3 w-3" /> Charts
        </Link>
        <TvCopyBar title={g.group_name} symbols={g.symbols ?? []} label="TV" />
      </div>
      {ctx && (
        <details className="text-2xs text-fg-3">
          <summary className="cursor-pointer hover:text-fg">How the labels are decided</summary>
          <div className="mt-1 space-y-1">
            {ctx.breadth_rules && (
              <div>
                Breadth: <b>thin</b> if &lt; {ctx.breadth_rules.min_members} members; <b>one-stock</b> if the top contributor is ≥ {ctx.breadth_rules.one_stock_share}% of the move;{' '}
                <b>broad</b> if ≥ {ctx.breadth_rules.broad_pct}% of members moved the group&apos;s way; else <b>mixed</b>.
              </div>
            )}
            {(ctx.participation_rules ?? []).map((r) => (
              <div key={r.id}>
                <b>{r.phrase}</b>: {clauseText(r.when)}
              </div>
            ))}
            {(ctx.persistence_rules ?? []).map((r) => (
              <div key={r.id}>
                <b>{r.label}</b>: {clauseText(r.when)}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

export function TodayGroups({ level, floor, text, onDrill }: { level: Level; floor: Floor; text: string; onDrill: (id: string) => void }) {
  const sidecarOpen = !!useShell().symbol;
  const q = useApiQuery('today/groups', { query: { level, floor, limit: 5000 } });
  const rows = useMemo(() => filterGroupsText(q.data?.rows ?? EMPTY, text), [q.data, text]);
  const [picked, setSelected] = useState<string | null>(null);
  // The picked group, or the first row when nothing (or a filtered-out group) is picked.
  const selected = picked && rows.some((r) => r.id === picked) ? picked : (rows[0]?.id ?? null);
  const cols = useMemo(() => columns(onDrill), [onDrill]);
  const sel = rows.find((r) => r.id === selected);
  const ctx = q.data?.meta.context as RulesCtx | undefined;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-6 shrink-0 items-center gap-3 border-b border-line bg-surface px-3 py-0.5 text-2xs text-fg-3">
        <span>
          What moved today and why · <span className="num text-fg-2">{rows.length}</span> groups · click a row for the why, Enter / name to drill
        </span>
        <SourceNote meta={q.data?.meta} />
        {q.data?.as_of && <span className="ml-auto">As of {fmtDate(q.data.as_of)}</span>}
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <DataTable
            label="Groups today"
            columns={cols}
            rows={rows}
            total={q.data ? rows.length : null}
            getRowId={(r) => r.id}
            loading={q.isLoading}
            error={q.error}
            onRetry={() => void q.refetch()}
            initialSort={[{ id: 'ret', desc: true }]}
            activeRowId={selected}
            onActiveRowChange={(r) => setSelected(r.id)}
            onRowClick={(r) => setSelected(r.id)}
            onRowActivate={(r) => onDrill(r.id)}
            emptyState={<EmptyState title="No groups" detail={q.data?.meta.reason ?? 'Clear the filter.'} />}
            className="min-h-0 flex-1"
          />
        </div>
        <aside className={cn('shrink-0 overflow-y-auto border-l border-line bg-surface', sidecarOpen ? 'w-[340px]' : 'w-[440px]')}>
          {sel ? <Detail g={sel} ctx={ctx} onDrill={onDrill} /> : <EmptyState compact title="Pick a group" />}
        </aside>
      </div>
    </div>
  );
}
