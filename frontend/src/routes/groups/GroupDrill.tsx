/**
 * Group drill-down: breadcrumb (click a parent to move up), sub-groups,
 * headline metrics with dictionary tooltips, 120-session history and the
 * member table. Row focus opens the Stock 360 sidecar; Enter opens the page.
 */
import { ArrowLeft, ChevronRight, LineChart } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { useApiQuery } from '../../api/query';
import type { GroupRow, MemberRow } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtDate, fmtDateShort, fmtNum, fmtSigned, fmtValue, isNum, type FormatKind } from '../../lib/fmt';
import { useShell } from '../../shell/ShellContext';
import { Chip } from '../../ui/Chip';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { Skeleton } from '../../ui/Skeleton';
import { Spark } from '../../ui/Spark';
import { FLOORS, levelLabel, parseGroupId, rankSparkValues, type Floor } from './groupsModel';
import { MetricInline, QuadrantChip, RankDelta, SourceNote, ZoneNum } from './kit';

const EMPTY_M: MemberRow[] = [];
const EMPTY_G: GroupRow[] = [];

interface Crumb {
  level: string;
  name: string | null;
  id: string | null;
}

const memberColumns: DataTableColumn<MemberRow>[] = [
  { id: 'symbol', header: 'Symbol', accessor: 'symbol', width: 104, sticky: true, cell: (v) => <span className="font-mono font-medium text-fg">{String(v)}</span> },
  { id: 'name', header: 'Name', accessor: 'security_name', width: 180, cell: (v) => <span className="truncate text-fg-2">{String(v)}</span> },
  { id: 'mcap', header: 'Mcap ₹Cr', accessor: 'market_cap_cr', format: 'int', width: 76, metricKey: 'market_cap_cr' },
  { id: 'close', header: 'Close', accessor: 'close', format: 'inr', width: 76 },
  { id: 'chg', header: '1D', accessor: 'change_1d_pct', format: 'signedPct', digits: 1, width: 56, metricKey: 'change_1d_pct' },
  { id: 'rs', header: 'RS', accessor: 'rs_percentile', format: 'num', digits: 0, width: 44, metricKey: 'rs_percentile', cell: (v) => <ZoneNum metricKey="rs_percentile" value={v as number} digits={0} /> },
  { id: 'rs_d5', header: 'RS Δ5', accessor: 'rs_delta_5', format: 'signed', digits: 0, width: 52, metricKey: 'rs_delta_5' },
  {
    id: 'rs_hist',
    header: 'RS T-30…T0',
    accessor: 'rs_rank_t30',
    sortable: false,
    width: 96,
    headerTitle: 'Strength rank 30, 15 and 5 sessions ago and today',
    renderNull: true,
    cell: (_v, r) => {
      const vals = [r.rs_rank_t30 ?? null, r.rs_rank_t15 ?? null, r.rs_rank_t5 ?? null, r.rs_percentile ?? null];
      return (
        <span className="flex items-center gap-1" title={`T-30 ${fmtNum(vals[0], 0)} · T-15 ${fmtNum(vals[1], 0)} · T-5 ${fmtNum(vals[2], 0)} · T0 ${fmtNum(vals[3], 0)}`}>
          <Spark values={vals} label={`${r.symbol} strength rank history`} width={48} height={16} />
          <span className="num text-2xs text-fg-3">{fmtNum(vals[0], 0)}</span>
        </span>
      );
    },
  },
  { id: 'r1m', header: '1M', accessor: 'return_1m_pct', format: 'signedPct', digits: 1, width: 58 },
  { id: 'r3m', header: '3M', accessor: 'return_3m_pct', format: 'signedPct', digits: 1, width: 58 },
  { id: 'ex21', header: 'Exc 21d', accessor: 'excess_vs_midsml400_21d', format: 'signed', digits: 1, width: 62, headerTitle: '21-session return minus MidSml400, points' },
  { id: 'ex63', header: 'Exc 63d', accessor: 'excess_vs_midsml400_63d', format: 'signed', digits: 1, width: 62, metricKey: 'excess_vs_midsml400_63d', cell: (v) => <ZoneNum metricKey="excess_vs_midsml400_63d" value={v as number} format="signed" digits={1} /> },
  { id: 'vs_idx', header: 'vs Sector idx', accessor: 'rs_vs_sector_index_63d', format: 'signed', digits: 1, width: 84, metricKey: 'rs_vs_sector_index_63d' },
  {
    id: 'tt',
    header: 'TT',
    accessor: 'trend_template_pass_n',
    format: 'int',
    width: 48,
    metricKey: 'trend_template_pass_n',
    cell: (v, r) => <span className={cn('num', r.trend_template_pass ? 'text-up' : 'text-fg-2')}>{String(v)}/8</span>,
  },
  { id: 'acc', header: 'Acc d', accessor: 'delivery_accumulation_days', format: 'int', width: 50, metricKey: 'delivery_accumulation_days', cell: (v) => <ZoneNum metricKey="delivery_accumulation_days" value={v as number} format="int" /> },
  { id: 'deal', header: 'Deals 10s', accessor: 'deal_net_10s_cr', format: 'signed', digits: 1, width: 70, metricKey: 'deal_net_10s_cr', cell: (v) => <ZoneNum metricKey="deal_net_10s_cr" value={v as number} format="signed" digits={1} /> },
  { id: 'rvol', header: 'RVOL', accessor: 'rvol', format: 'num', digits: 2, width: 52, metricKey: 'rvol' },
  { id: 'dvs20', header: 'Deliv ×20d', accessor: 'delivery_vs_20d', format: 'ratio', digits: 2, width: 70, metricKey: 'delivery_vs_20d' },
  { id: 'hi52', header: 'From 52W hi', accessor: 'away_52w_high_pct', format: 'signedPct', digits: 1, width: 76, metricKey: 'away_52w_high_pct' },
  { id: 'adv', header: 'ADV ₹Cr', accessor: 'adv_cr_20d', format: 'num', digits: 1, width: 64, metricKey: 'adv_cr_20d', defaultHidden: true },
  {
    id: 'setups',
    header: 'Setups',
    accessor: (r) => (r.active_setups == null ? null : r.active_setups.join(' ')),
    width: 120,
    headerTitle: 'Active Desk setups today (needs setup_daily)',
    cell: (v) => (
      <span className="flex gap-1">
        {String(v)
          .split(' ')
          .filter(Boolean)
          .map((q) => (
            <Chip key={q} tone="accent">
              {q.replace('darvas_', 'D-').replace('_', ' ')}
            </Chip>
          ))}
      </span>
    ),
  },
];

function Headline({ label, metricKey, value, format = 'num', digits, delta }: { label: string; metricKey: string; value: number | null | undefined; format?: FormatKind; digits?: number; delta?: ReactNode }) {
  return (
    <MetricInline metricKey={metricKey} label={label} value={value}>
      <span className="flex items-baseline gap-1.5">
        <ZoneNum metricKey={metricKey} value={value} format={format} digits={digits} className="text-sm font-semibold" />
        {delta}
      </span>
    </MetricInline>
  );
}

function HistorySpark({ label, values, fmt, baseline }: { label: string; values: (number | null)[]; fmt: (v: number | null) => string; baseline?: number }) {
  const nums = values.filter(isNum);
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-2xs uppercase tracking-wide text-fg-3">{label}</span>
      <Spark values={values} label={label} width={200} height={36} baseline={baseline} />
      <span className="num text-2xs text-fg-3">
        {nums.length ? `${fmt(nums[0])} → ${fmt(nums[nums.length - 1])}` : 'no history'}
      </span>
    </div>
  );
}

export interface GroupDrillProps {
  groupId: string;
  floor: Floor;
  onBack: () => void;
  onNavigate: (id: string) => void;
  chartsHref: (symbols: string[]) => string;
}

export function GroupDrill({ groupId, floor, onBack, onNavigate, chartsHref }: GroupDrillProps) {
  const shell = useShell();
  const parsed = parseGroupId(groupId);
  const [sorted, setSorted] = useState<MemberRow[]>(EMPTY_M);
  const detail = useApiQuery('groups/{group_id}', { params: { group_id: groupId }, query: { floor, days: 120 } }, { enabled: !!parsed });
  const members = useApiQuery('groups/{group_id}/members', { params: { group_id: groupId }, query: { floor, limit: 5000 } }, { enabled: !!parsed });

  const hist = detail.data?.rows ?? EMPTY_G;
  const g = hist[0];
  const oldest = useMemo(() => [...hist].reverse(), [hist]);
  const ctx = detail.data?.meta.context as { breadcrumb?: Crumb[]; children?: Crumb[]; floor_label?: string } | undefined;
  const crumbs = ctx?.breadcrumb ?? [];
  const children = ctx?.children ?? [];
  const memberRows = members.data?.rows ?? EMPTY_M;
  const syms = (sorted.length ? sorted : memberRows).map((m) => m.symbol).filter((s): s is string => !!s);

  if (!parsed) {
    return <EmptyState title="Unknown group" detail={`"${groupId}" is not a valid group id.`} action={<button type="button" onClick={onBack} className="text-accent">Back to board</button>} />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-line bg-surface px-3 py-1.5">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3">
          <ArrowLeft className="h-3.5 w-3.5" /> Board
        </button>
        <nav aria-label="Taxonomy path" className="flex min-w-0 items-center gap-1 text-xs">
          {(crumbs.length ? crumbs : [{ level: parsed.level, name: parsed.name, id: groupId }]).map((c, i, arr) => (
            <span key={`${c.level}-${i}`} className="flex items-center gap-1">
              {i > 0 && <ChevronRight className="h-3 w-3 text-fg-3" />}
              {i === arr.length - 1 || !c.id ? (
                <span className={cn(i === arr.length - 1 ? 'font-semibold text-fg' : 'text-fg-3')} title={levelLabel(c.level)}>
                  {c.name ?? '—'}
                </span>
              ) : (
                <button type="button" className="text-fg-2 hover:text-accent hover:underline" title={`${levelLabel(c.level)} — open`} onClick={() => onNavigate(c.id as string)}>
                  {c.name}
                </button>
              )}
            </span>
          ))}
        </nav>
        <Chip>{levelLabel(parsed.level)}</Chip>
        {g && <QuadrantChip quadrant={g.rrg_quadrant} days={g.days_in_quadrant} />}
        <div className="ml-auto flex items-center gap-2">
          <SourceNote meta={detail.data?.meta} />
          <Link
            to={chartsHref(syms)}
            className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-xs text-fg-2 hover:bg-surface-3"
            title="Open these members in the Charts tab (source = this group)"
          >
            <LineChart className="h-3.5 w-3.5" /> Show these as charts
          </Link>
        </div>
      </div>

      <div className="shrink-0 border-b border-line bg-surface px-3 py-2">
        {detail.error ? (
          <ErrorState error={detail.error} compact onRetry={() => void detail.refetch()} />
        ) : detail.isLoading ? (
          <Skeleton height={64} />
        ) : !g ? (
          <EmptyState compact title="No history at this floor" detail={detail.data?.meta.reason ?? 'The group has no members meeting the floor.'} />
        ) : (
          <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
            <Headline
              label={`Rank${g.rank_n ? ` of ${g.rank_n}` : ''}`}
              metricKey="group_rank"
              value={g.rank}
              format="int"
              delta={
                <span className="flex gap-1 text-2xs">
                  <RankDelta value={g.rank_delta_5} />
                  <span className="text-fg-3">5d</span>
                  <RankDelta value={g.rank_delta_20} />
                  <span className="text-fg-3">20d</span>
                </span>
              }
            />
            <Headline label="Excess 21d" metricKey="group_excess_21d" value={g.excess_vs_midsml400_21d} format="signed" digits={1} />
            <Headline label="Excess 63d" metricKey="group_excess_63d" value={g.excess_vs_midsml400_63d} format="signed" digits={1} />
            <Headline label="RS-Ratio" metricKey="rs_ratio" value={g.rs_ratio} digits={2} />
            <Headline label="RS-Mom" metricKey="rs_momentum" value={g.rs_momentum} digits={2} />
            <Headline label=">50 EMA" metricKey="group_breadth_50" value={g.breadth_50} format="pct" digits={0} />
            <Headline label=">200 EMA" metricKey="group_breadth_200" value={g.breadth_200} format="pct" digits={0} />
            <Headline label="Trend tmpl" metricKey="group_trend_template_pct" value={g.trend_template_pct} format="pct" digits={0} />
            <Headline label="Flow Δ" metricKey="turnover_share_delta_20d" value={g.turnover_share_delta} format="signed" digits={2} />
            <Headline label="Deliv acc" metricKey="group_delivery_accumulation" value={g.delivery_accumulation} format="signed" digits={0} />
            <Headline label="Deals 10s ₹Cr" metricKey="deal_net_10s_cr" value={g.deal_net_10s_cr} format="signed" digits={0} />
            <Headline label="Top-1 share" metricKey="group_top1_turnover_share" value={g.top1_turnover_share_pct} format="pct" digits={0} />
            <div className="flex flex-col gap-0.5">
              <span className="text-2xs uppercase tracking-wide text-fg-3">Members</span>
              <span className="num text-sm font-semibold text-fg">{g.stocks ?? '—'}</span>
            </div>
          </div>
        )}
        {oldest.length > 1 && (
          <div className="mt-2 flex flex-wrap gap-6">
            <HistorySpark label={`Rank, ${oldest.length} sessions (up = better)`} values={rankSparkValues(oldest.map((r) => r.rank ?? null))} fmt={(v) => (v == null ? '—' : String(-v))} />
            <HistorySpark label="Excess vs MidSml400 63d" values={oldest.map((r) => r.excess_vs_midsml400_63d ?? null)} fmt={(v) => fmtSigned(v, 1)} baseline={0} />
            <HistorySpark label="RS-Ratio" values={oldest.map((r) => r.rs_ratio ?? null)} fmt={(v) => fmtNum(v, 1)} baseline={100} />
            <HistorySpark label="% above 50 EMA" values={oldest.map((r) => r.breadth_50 ?? null)} fmt={(v) => fmtValue(v, 'pct', 0)} />
            <HistorySpark label="Turnover share 5d" values={oldest.map((r) => r.turnover_share_5d ?? null)} fmt={(v) => fmtValue(v, 'pct', 2)} />
            <div className="text-2xs text-fg-3">
              {fmtDateShort(oldest[0].trade_date ?? null)} → {fmtDate(g?.trade_date ?? null)}
            </div>
          </div>
        )}
        {children.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1">
            <span className="mr-1 text-2xs uppercase tracking-wide text-fg-3">{levelLabel(children[0].level)}s:</span>
            {children.map((c) => (
              <Chip key={c.id ?? c.name} onClick={() => c.id && onNavigate(c.id)} title={`Drill into ${c.name}`}>
                {c.name}
              </Chip>
            ))}
          </div>
        )}
      </div>

      <div className="flex h-7 shrink-0 items-center gap-3 border-b border-line bg-surface px-3 text-2xs text-fg-3">
        <span className="font-semibold uppercase tracking-wide text-fg-2">Members</span>
        <span>{ctx?.floor_label ?? FLOORS.find((f) => f.value === floor)?.title}</span>
        <span>J/K moves · the sidecar follows · Enter opens Stock 360</span>
        {(members.data?.meta.notes ?? []).map((n) => (
          <span key={n} className="text-fg-3">
            {n}
          </span>
        ))}
      </div>
      <DataTable
        label={`${parsed.name} members`}
        columns={memberColumns}
        rows={memberRows}
        total={members.data?.total ?? null}
        getRowId={(r, i) => r.symbol ?? String(i)}
        loading={members.isLoading}
        error={members.error}
        onRetry={() => void members.refetch()}
        initialSort={[{ id: 'rs', desc: true }]}
        activeRowId={shell.symbol}
        onActiveRowChange={(r) => r.symbol && shell.openSymbol(r.symbol)}
        onRowActivate={(r) => r.symbol && shell.openStockPage(r.symbol)}
        onSortedRowsChange={setSorted}
        emptyState={<EmptyState title="No members at this floor" detail="Try the All floor." />}
        className="min-h-0 flex-1"
      />
    </div>
  );
}
