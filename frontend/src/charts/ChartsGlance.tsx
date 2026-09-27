/** Charts "at a glance" — a slim band: source, symbol count, breadth of the list. Uses the list already loaded. */
import { useMemo } from 'react';
import { countWhere, medianOf } from '../lib/glance';
import { fmtDate, fmtInt, fmtNum } from '../lib/fmt';
import { GlanceBand } from '../ui/GlanceBand';
import { KpiTile } from '../ui/KpiTile';
import type { ChartItem } from './sources';

export interface ChartsGlanceProps {
  label: string;
  items: readonly ChartItem[];
  total: number | null | undefined;
  asOf: string | null | undefined;
  partialReason: string | null | undefined;
  note: string | null | undefined;
  page: number;
  pages: number;
  loading: boolean;
}

export function ChartsGlance({ label, items, total, asOf, partialReason, note, page, pages, loading }: ChartsGlanceProps) {
  const up = useMemo(() => countWhere(items, (i) => (i.change_1d_pct ?? 0) > 0), [items]);
  const withChange = useMemo(() => countWhere(items, (i) => typeof i.change_1d_pct === 'number'), [items]);
  const med = useMemo(() => medianOf(items, (i) => i.rs_percentile), [items]);
  const n = items.length;
  return (
    <GlanceBand
      compact
      label="Charts at a glance"
      aside={
        <>
          <span className="flex items-center gap-2 whitespace-nowrap">
            {asOf && <span>as of {fmtDate(asOf)}</span>}
            {total != null && total !== n && (
              <span className="text-warn">
                {n} of {total} returned
              </span>
            )}
            {partialReason && (
              <span className="text-warn" title={partialReason}>
                partial data
              </span>
            )}
          </span>
          <span
            className="max-w-[420px] truncate"
            title={
              note ??
              'J / K (or ] / [) page · click a symbol to open Stock 360 · double-click or ⤢ to expand · crosshair synced by date · tile shows return vs NIFTY MidSml 400 over the chosen window'
            }
          >
            {note ?? 'J/K page · click symbol = Stock 360 · ⤢ expand'}
          </span>
        </>
      }
    >
      <KpiTile
        compact
        tone="accent"
        label="Source"
        value={<span className="block truncate text-fg">{label}</span>}
        loading={loading}
        className="!min-w-[200px] !flex-[1.6]"
      />
      <KpiTile compact label="Symbols" value={loading ? null : n} format="int" tone="neutral" loading={loading} />
      <KpiTile
        compact
        label="Up today"
        value={loading || !withChange ? null : <span className="num">{`${fmtInt(up)} / ${fmtInt(withChange)}`}</span>}
        tone={withChange && up / withChange >= 0.5 ? 'up' : withChange ? 'down' : 'neutral'}
        loading={loading}
      />
      <KpiTile compact label="Median strength" metricKey="rs_percentile" value={med} format="num" digits={0} loading={loading} />
      <KpiTile
        compact
        label="Page"
        value={<span className="num text-fg">{pages ? `${fmtNum(page + 1, 0)} / ${fmtNum(pages, 0)}` : '—'}</span>}
        loading={loading}
      />
    </GlanceBand>
  );
}
