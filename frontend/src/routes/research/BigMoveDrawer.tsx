/**
 * One big-move event: pre/post price path (T-60…T+20, bounded by as_of),
 * pre-move fingerprint vs matched controls with n, catalyst attribution, and
 * links to Stock 360 as of the event date / Charts.
 */
import { ExternalLink, LineChart } from 'lucide-react';
import { useMemo } from 'react';
import { useNavigate } from 'react-router';
import { useApiQuery } from '../../api/query';
import type { BarRow, BigMoveRow } from '../../api/types';
import { cn } from '../../lib/cn';
import { fmtCr, fmtDateWithDay, fmtNum, fmtSignedPct, isNum } from '../../lib/fmt';
import type { OHLCBar } from '../../lib/indicators';
import { useShell } from '../../shell/ShellContext';
import { VERDICT_TEXT } from '../../shell/environment';
import { Chart } from '../../ui/Chart';
import { Chip } from '../../ui/Chip';
import { Drawer } from '../../ui/Drawer';
import { Skeleton } from '../../ui/Skeleton';
import { useResearchQuery } from './data';
import {
  CATALYST_LABEL,
  CATALYST_TONE,
  TRIGGER_LABEL,
  asCatalyst,
  bigMoveExtras,
  eventWindow,
  offsetLabel,
  pivotFeatures,
  readFeatures,
} from './model';
import { EvidencePending, FeatureName, PathChart, SampleN, Term } from './parts';

function toBars(rows: readonly BarRow[]): OHLCBar[] {
  return rows.flatMap((r) =>
    r.trade_date && r.open != null && r.high != null && r.low != null && r.close != null
      ? [
          {
            time: r.trade_date,
            open: r.open,
            high: r.high,
            low: r.low,
            close: r.close,
            volume: r.volume ?? null,
            delivery_pct: r.delivery_pct ?? null,
          },
        ]
      : [],
  );
}

export function CatalystChip({ value }: { value: unknown }) {
  const c = asCatalyst(value);
  if (!c) return <Chip>{typeof value === 'string' && value ? value : 'unattributed'}</Chip>;
  return <Chip tone={CATALYST_TONE[c]}>{CATALYST_LABEL[c]}</Chip>;
}

function PricePath({ row }: { row: BigMoveRow }) {
  const sym = row.symbol ?? '';
  const date = row.event_date ?? '';
  const bars = useApiQuery('stock/{sym}/bars', { params: { sym }, query: { tf: 'D' } }, { enabled: !!sym && !!date });
  const windowed = useMemo(() => eventWindow(toBars(bars.data?.rows ?? []), date), [bars.data, date]);
  const extras = bigMoveExtras(row);

  if (bars.isPending) return <Skeleton height={260} />;
  if (windowed.length > 1) {
    return (
      <div className="h-[280px]">
        <Chart
          bars={windowed}
          resample={false}
          emaPeriods={[10, 50]}
          markers={[{ time: date, kind: 'custom', text: 'T' }]}
          initialBars={windowed.length}
          label={`${sym} price path around the ${date} move`}
          className="h-full"
        />
      </div>
    );
  }
  // Bars unavailable: fall back to the served close path (starts at path_start_offset), if any.
  if (extras.path_pct) {
    const n = extras.path_pct.length;
    const start = extras.path_start_offset ?? -Math.floor(n / 2);
    return (
      <div className="space-y-1">
        <PathChart
          label={`${sym} close vs T-1 close around the event`}
          series={[
            {
              id: 'p',
              label: 'Close vs T-1 (%)',
              points: extras.path_pct.map((y, i) => ({ x: start + i, y })),
              tone: 'accent',
              strokeWidth: 1.75,
            },
          ]}
          xTicks={[start, -10, 0, 10, start + n - 1].map((x) => ({ x, label: offsetLabel(x) }))}
          yFormat={(v) => fmtSignedPct(v, 0)}
          markerX={0}
          markerLabel="event"
          height={200}
        />
        <div className="text-2xs text-fg-3">Price bars unavailable here; showing the served close path (% vs T-1 close).</div>
      </div>
    );
  }
  return <div className="rounded border border-line p-4 text-center text-2xs text-fg-3">No price history available for this event.</div>;
}

function Fingerprint({ eventId }: { eventId: string }) {
  const q = useResearchQuery('research/big-moves/{event_id}', { params: { event_id: eventId } });
  if (q.isPending) return <Skeleton height={160} />;
  const features = readFeatures(q.data?.meta);
  if (q.isError || !features.length) {
    return (
      <EvidencePending
        compact
        meta={q.data?.meta}
        what="Pre-move fingerprint at T-60 / T-20 / T-5 / T-1 against matched controls (same date, industry, mcap/ADV bucket): strength rank and change, base length and depth, range contraction, volume dry-up then expansion, delivery trend, distance from 52W high."
      />
    );
  }
  const { offsets, features: rows } = pivotFeatures(features);
  const nControls = Math.max(...features.map((f) => f.n_controls ?? 0));
  return (
    <div className="space-y-1">
      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full text-table" aria-label="Pre-move fingerprint vs controls">
          <thead className="bg-surface-2 text-2xs uppercase tracking-wide text-fg-3">
            <tr>
              <th className="px-2 py-1 text-left font-medium">Feature</th>
              {offsets.map((o) => (
                <th key={o} className="px-2 py-1 text-right font-medium">
                  {offsetLabel(o)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.feature} className="h-7 border-t border-line">
                <td className="px-2 text-fg-2">
                  <FeatureName feature={f.feature} metricKey={f.metric_key} />
                </td>
                {offsets.map((o) => {
                  const c = f.cells.get(o);
                  const hi = c && isNum(c.percentile) && c.percentile >= 80;
                  return (
                    <td key={o} className="px-2 text-right">
                      <span className={cn('num', hi ? 'text-up' : 'text-fg')}>{fmtNum(c?.mover, 1)}</span>
                      <span className="num ml-1 text-2xs text-fg-3">vs {fmtNum(c?.control_median, 1)}</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-2 text-2xs text-fg-3">
        <span>Mover value vs median of matched controls; green = above the 80th percentile of controls.</span>
        <SampleN n={nControls} label="controls" />
      </div>
    </div>
  );
}

export function BigMoveDrawer({ row, onClose }: { row: BigMoveRow | null; onClose: () => void }) {
  const shell = useShell();
  const navigate = useNavigate();
  const open = !!row;
  const extras = row ? bigMoveExtras(row) : null;
  const id = row?.event_id ?? null;
  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={720}
      title={row ? `${row.symbol ?? '—'} · ${fmtDateWithDay(row.event_date)}` : 'Big move'}
      actions={
        row?.symbol ? (
          <>
            <button
              type="button"
              onClick={() => navigate(`/stock/${encodeURIComponent(row.symbol!)}${row.event_date ? `?as_of=${row.event_date}` : ''}`)}
              className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-2xs text-fg-2 hover:bg-surface-3"
              title="Open Stock 360 time-travelled to the event date"
            >
              <ExternalLink className="h-3 w-3" aria-hidden /> Stock 360 as of event
            </button>
            <button
              type="button"
              onClick={() => shell.openCharts([row.symbol!])}
              className="inline-flex items-center gap-1 rounded border border-line px-2 py-0.5 text-2xs text-fg-2 hover:bg-surface-3"
            >
              <LineChart className="h-3 w-3" aria-hidden /> Charts
            </button>
          </>
        ) : null
      }
    >
      {row && extras && (
        <div className="space-y-4 overflow-y-auto p-4">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {extras.security_name && <span className="text-fg-2">{extras.security_name}</span>}
            <Chip tone="positive">{TRIGGER_LABEL[row.trigger ?? ''] ?? row.trigger ?? 'trigger —'}</Chip>
            <span className={cn('num font-medium', isNum(row.move_pct) ? 'text-up' : 'text-fg-3')}>{fmtSignedPct(row.move_pct)}</span>
            <span className="num text-fg-3">
              <Term k="market_cap_cr">mcap</Term> {fmtCr(row.mcap_cr_at_event, 0)} at event
            </span>
            {row.industry && <span className="text-fg-3">{row.industry}</span>}
            {extras.verdict_then && (
              <span className="text-fg-3">
                env <span className={VERDICT_TEXT[extras.verdict_then]}>{extras.verdict_then}</span>
              </span>
            )}
          </div>
          <section aria-label="Catalyst">
            <h3 className="mb-1 text-2xs font-semibold uppercase tracking-wide text-fg-3">Catalyst attribution</h3>
            <div className="flex items-center gap-2 text-xs">
              <CatalystChip value={row.catalyst} />
              <span className="text-fg-2">
                {extras.catalyst_detail ?? 'Window: results / deal ±3 sessions, sector-wide if ≥ 50% of the Industry moved.'}
              </span>
            </div>
          </section>
          <section aria-label="Price path">
            <h3 className="mb-1 text-2xs font-semibold uppercase tracking-wide text-fg-3">Price path T-60 … T+20</h3>
            <PricePath row={row} />
          </section>
          <section aria-label="Fingerprint">
            <h3 className="mb-1 text-2xs font-semibold uppercase tracking-wide text-fg-3">Pre-move fingerprint vs matched controls</h3>
            {id ? <Fingerprint eventId={id} /> : <div className="text-2xs text-fg-3">The server did not supply an event id.</div>}
          </section>
        </div>
      )}
    </Drawer>
  );
}
