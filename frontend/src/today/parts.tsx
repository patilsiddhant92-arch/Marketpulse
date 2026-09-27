/**
 * Shared Today cells and column builders: quality-of-move chip (server rule + why),
 * evidence trait chips, catalysts, deals today, queue chips, group link.
 * Every value is as served; NULL renders "—".
 */
import { CalendarClock, Megaphone, Newspaper } from 'lucide-react';
import { useCallback } from 'react';
import { useNavigate } from 'react-router';
import type { TodayStockRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtNum, fmtSigned, fmtSignedPct } from '../lib/fmt';
import { useAsOf } from '../shell/urlState';
import { Chip } from '../ui/Chip';
import { ChipRow } from '../ui/ChipRow';
import type { DataTableColumn } from '../ui/DataTable';
import { Tooltip } from '../ui/Tooltip';
import { ZoneNum } from '../routes/groups/kit';
import {
  KIND_LABELS,
  QUEUE_SHORT,
  TRAIT_LABELS,
  eventWhen,
  qualitySideNote,
  qualityTone,
  traitTitle,
  type EvidenceTrait,
  type QualityRule,
} from './todayModel';

/** Navigate to a Groups drill-down (keeps as_of). */
export function useGroupNav() {
  const navigate = useNavigate();
  const [asOf] = useAsOf();
  return useCallback(
    (id: string, extra: Record<string, string> = {}) => {
      const p = new URLSearchParams({ group: id, ...extra });
      if (asOf) p.set('as_of', asOf);
      navigate(`/groups?${p.toString()}`);
    },
    [navigate, asOf],
  );
}

export function ChangeCell({ v, digits = 2 }: { v: number | null | undefined; digits?: number }) {
  return <span className={cn('num', v == null ? 'text-fg-3' : v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-fg-2')}>{fmtSignedPct(v, digits)}</span>;
}

export function QualityChip({ row, rules }: { row: TodayStockRow; rules: readonly QualityRule[] | undefined }) {
  if (!row.quality) return <span className="text-2xs text-fg-3" title="RVOL unknown: no rule can match">—</span>;
  const rule = rules?.find((r) => r.id === row.quality_id);
  const side = qualitySideNote(row);
  return (
    <Tooltip
      content={
        <div className="max-w-xs space-y-1 text-fg-2">
          <div className="font-medium text-fg">
            {row.quality}
            {side ? ` — ${side}` : ''}
          </div>
          {rule?.why && <div>{rule.why}</div>}
          <div className="text-fg-3">
            RVOL {fmtNum(row.rvol, 2)} · delivered shares {fmtNum(row.delivery_qty_vs_20d, 2)}× normal · delivery % {fmtNum(row.delivery_vs_20d, 2)}× · mcap ₹{fmtNum(row.market_cap_cr, 0)} Cr
            {row.at_upper_circuit ? ' · at upper band' : row.at_lower_circuit ? ' · at lower band' : ''}
          </div>
        </div>
      }
    >
      <span tabIndex={0} className="inline-flex">
        <Chip tone={qualityTone(row.quality_tone)}>{row.quality}</Chip>
      </span>
    </Tooltip>
  );
}

export function TraitChips({ traits, evidence }: { traits: readonly string[] | undefined; evidence: readonly EvidenceTrait[] | undefined }) {
  return (
    <ChipRow
      budget={20}
      items={(traits ?? []).map((t) => ({ key: t, label: TRAIT_LABELS[t]?.short ?? t, tone: 'violet' as const, title: traitTitle(t, evidence) }))}
    />
  );
}

export function QueueChips({ queues }: { queues: readonly string[] | undefined }) {
  return (
    <ChipRow
      budget={10}
      items={(queues ?? []).map((q) => ({ key: q, label: QUEUE_SHORT[q] ?? q, tone: 'accent' as const, title: `In the ${QUEUE_SHORT[q] ?? q} Desk queue today` }))}
    />
  );
}

export function DealCell({ row }: { row: TodayStockRow }) {
  const v = row.deal_net_cr_today;
  if (v == null && !row.deal_prints_today) return <span className="text-fg-3">—</span>;
  return (
    <span
      className={cn('num', v == null ? 'text-fg-3' : v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-fg-2')}
      title={`Bulk/block deals today: ${row.deal_prints_today ?? 0} print(s), net ${fmtSigned(v, 2)} ₹Cr ex-PROP${row.deal_event_type ? ` · ${row.deal_event_type.replace(/_/g, ' ')}` : ''}`}
    >
      {v != null ? fmtSigned(v, 1) : '0'}
      {row.deal_event_type && <span className="ml-1 text-2xs text-fg-3">{row.deal_event_type.replace(/_/g, ' ')}</span>}
    </span>
  );
}

export function CatalystCell({ row, asOf }: { row: TodayStockRow; asOf: string | null | undefined }) {
  const res = eventWhen(row.results_nearby, asOf);
  const ca = eventWhen(row.corp_action_nearby, asOf);
  const news = row.news_today ?? [];
  if (!res && !ca && !news.length) return <span className="text-fg-3">—</span>;
  return (
    <span className="flex min-w-0 items-center gap-1.5 text-2xs">
      {res && (
        <span className="inline-flex items-center gap-0.5 text-warn" title={row.results_nearby?.headline ?? res}>
          <CalendarClock className="h-3 w-3 shrink-0" aria-hidden /> {res}
        </span>
      )}
      {ca && (
        <span className="inline-flex items-center gap-0.5 text-info" title={row.corp_action_nearby?.headline ?? ca}>
          <Megaphone className="h-3 w-3 shrink-0" aria-hidden /> {ca}
        </span>
      )}
      {news.length > 0 && (
        <span className="inline-flex min-w-0 items-center gap-0.5 text-fg-2" title={news.map((n) => `${n.label}: ${n.headline ?? ''}`).join('\n')}>
          <Newspaper className="h-3 w-3 shrink-0" aria-hidden /> <span className="truncate">{news.map((n) => n.label).join(', ')}</span>
        </span>
      )}
    </span>
  );
}

function GroupLink({ name, onGroup }: { name: string | null | undefined; onGroup: (id: string) => void }) {
  if (!name) return <span className="text-fg-3">—</span>;
  return (
    <button
      type="button"
      className="min-w-0 truncate text-left text-fg-2 hover:text-accent hover:underline"
      title={`Open the ${name} group`}
      onClick={(e) => {
        e.stopPropagation();
        onGroup(`industry:${name}`);
      }}
    >
      {name}
    </button>
  );
}

export interface StockColumnOpts {
  rules?: readonly QualityRule[];
  evidence?: readonly EvidenceTrait[];
  asOf: string | null | undefined;
  onGroup: (id: string) => void;
  isWatched?: (sym: string) => boolean;
  /** Extra columns after the change column (e.g. breakout kinds). */
  leading?: DataTableColumn<TodayStockRow>[];
}

/** Columns shared by movers and breakouts. */
export function stockColumns<T extends TodayStockRow>(o: StockColumnOpts): DataTableColumn<T>[] {
  const cols: DataTableColumn<TodayStockRow>[] = [
    {
      id: 'symbol',
      header: 'Symbol',
      accessor: 'symbol',
      width: 112,
      sticky: true,
      hideable: false,
      cell: (_v, r) => (
        <span className="flex min-w-0 items-center gap-1">
          <span className="truncate font-mono font-semibold text-fg" title={r.security_name ?? undefined}>
            {r.symbol}
          </span>
          {r.at_upper_circuit && <Chip tone="positive" title={`Closed at its upper price band (${fmtNum(r.circuit_band, 0)}%)`}>UC</Chip>}
          {r.at_lower_circuit && <Chip tone="negative" title={`Closed at its lower price band (${fmtNum(r.circuit_band, 0)}%)`}>LC</Chip>}
        </span>
      ),
    },
    { id: 'chg', header: 'Chg', accessor: 'change_1d_pct', format: 'signedPct', width: 64, metricKey: 'change_1d_pct', cell: (v) => <ChangeCell v={v as number} /> },
    ...(o.leading ?? []),
    {
      id: 'quality',
      header: 'Quality',
      accessor: 'quality',
      width: 92,
      metricKey: 'move_quality',
      renderNull: true,
      cell: (_v, r) => <QualityChip row={r} rules={o.rules} />,
    },
    { id: 'rvol', header: 'RVOL', accessor: 'rvol', format: 'num', digits: 2, width: 56, metricKey: 'rvol', cell: (v) => <ZoneNum metricKey="rvol" value={v as number} digits={2} /> },
    { id: 'deliv', header: 'Deliv %', accessor: 'delivery_pct', format: 'pct', digits: 0, width: 58, metricKey: 'delivery_pct' },
    {
      id: 'deliv_x',
      header: 'Deliv ×',
      accessor: 'delivery_qty_vs_20d',
      format: 'num',
      digits: 2,
      width: 62,
      metricKey: 'delivery_qty_vs_20d',
      cell: (v, r) => (
        <span className="inline-flex items-center gap-0.5">
          <ZoneNum metricKey="delivery_qty_vs_20d" value={v as number} digits={1} />
          {r.delivery_spike && (
            <span className="text-violet" title="Delivery spike: delivered shares > 2× their 20-day average">
              ●
            </span>
          )}
        </span>
      ),
    },
    { id: 'deliv_pct_x', header: 'Deliv% ×', accessor: 'delivery_vs_20d', format: 'num', digits: 2, width: 64, metricKey: 'delivery_vs_20d', defaultHidden: true },
    { id: 'to', header: 'T/O ₹Cr', accessor: 'turnover_cr', format: 'num', digits: 0, width: 66, headerTitle: 'Turnover today, ₹ Cr' },
    { id: 'to_x', header: 'T/O ×', accessor: 'turnover_vs_20d', format: 'num', digits: 1, width: 54, metricKey: 'turnover_vs_20d', cell: (v) => <ZoneNum metricKey="turnover_vs_20d" value={v as number} digits={1} /> },
    { id: 'group', header: 'Industry', accessor: 'industry', width: 140, cell: (_v, r) => <GroupLink name={r.industry} onGroup={o.onGroup} />, renderNull: true },
    { id: 'away', header: 'vs 52WH', accessor: 'away_52w_high_pct', format: 'signedPct', digits: 1, width: 64, metricKey: 'away_52w_high_pct' },
    { id: 'queues', header: 'Queue', accessor: (r) => r.queues?.join(',') || null, width: 78, headerTitle: 'Desk queues the stock is in today', cell: (_v, r) => <QueueChips queues={r.queues} />, renderNull: true },
    { id: 'deals', header: 'Deals', accessor: 'deal_net_cr_today', format: 'signed', digits: 1, width: 70, headerTitle: 'Bulk/block deal net today, ₹ Cr, PROP excluded', renderNull: true, cell: (_v, r) => <DealCell row={r} /> },
    {
      id: 'catalyst',
      header: 'Catalyst',
      accessor: (r) => (r.results_nearby || r.corp_action_nearby || r.news_today?.length ? 1 : null),
      width: 150,
      headerTitle: 'Results / corporate action within 5 sessions, news today (security_events, corporate_actions)',
      renderNull: true,
      cell: (_v, r) => <CatalystCell row={r} asOf={o.asOf} />,
    },
    {
      id: 'traits',
      header: 'Pre-move traits',
      accessor: (r) => r.traits?.length || null,
      width: 150,
      headerTitle: 'Traits the evidence engine found most common the session before upper-circuit moves (hover for the lift)',
      renderNull: true,
      cell: (_v, r) => <TraitChips traits={r.traits} evidence={o.evidence} />,
    },
    { id: 'mcap', header: 'Mcap ₹Cr', accessor: 'market_cap_cr', format: 'num', digits: 0, width: 74, metricKey: 'market_cap_cr', defaultHidden: true },
    { id: 'rs', header: 'RS', accessor: 'rs_percentile', format: 'num', digits: 0, width: 44, metricKey: 'rs_percentile', defaultHidden: true },
  ];
  return cols as unknown as DataTableColumn<T>[];
}

export function KindChips({ kinds, only, budget = 22 }: { kinds: readonly string[] | undefined; only?: readonly string[]; budget?: number }) {
  const ks = (kinds ?? []).filter((k) => !only || only.includes(k));
  return <ChipRow budget={budget} items={ks.map((k) => ({ key: k, label: KIND_LABELS[k]?.label ?? k, tone: KIND_LABELS[k]?.tone ?? 'neutral' }))} />;
}
