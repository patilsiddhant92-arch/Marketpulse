/**
 * Desk "at a glance" band (spec 7.2): verdict hero + key breadth KPIs + the
 * three queue counts with what is new today. Built only from queries the Desk
 * already makes (market/regime, market/health, desk/queues, desk/diff) —
 * TanStack Query shares them with the panels below.
 */
import { useMemo, useState } from 'react';
import { isApiError } from '../api/client';
import { useApiQuery } from '../api/query';
import type { PillarStatus, Verdict } from '../api/types';
import { cn } from '../lib/cn';
import { fmtDateWithDay, fmtInt, fmtNum, fmtSignedPct } from '../lib/fmt';
import { EnvironmentDrawer, VERDICT_ACTION, VERDICT_TEXT, useEnvironment } from '../shell/environment';
import { useUrlParam } from '../shell/urlState';
import { GlanceBand } from '../ui/GlanceBand';
import { KpiTile, type KpiTone } from '../ui/KpiTile';
import { Tooltip } from '../ui/Tooltip';
import { QUEUES, asQueueId, breadthSeries, breadthSnapshot, groupDiff } from './deskModel';

const VERDICT_TONE: Record<Verdict, KpiTone> = { Favourable: 'up', Constructive: 'up', Mixed: 'accent', Weak: 'warn', Danger: 'down' };
const PILLAR_DOT: Record<PillarStatus, string> = { Healthy: 'bg-up', Neutral: 'bg-warn', Weak: 'bg-down' };

/** Verdict hero tile (click = environment drawer). */
function VerdictTile() {
  const { q, view, unavailable } = useEnvironment();
  const [open, setOpen] = useState(false);
  const notShipped = isApiError(q.error) && (q.error.kind === 'not_found' || q.error.kind === 'parse');

  if (q.isLoading) return <KpiTile hero label="Environment" value={null} loading />;
  if (!view || unavailable || !view.verdict) {
    const reason = q.data?.meta?.reason;
    return (
      <KpiTile
        hero
        label="Environment"
        value={<span className="text-title text-fg-2">Verdict not available</span>}
        caption={
          <>
            {notShipped
              ? 'API v2 regime endpoint not deployed.'
              : q.error
                ? 'Could not load the regime.'
                : (reason ?? 'regime_daily has no row for this date.')}{' '}
            Read the raw breadth instead.
          </>
        }
        className="!min-w-[280px] !flex-[1.6]"
      />
    );
  }
  const v = view.verdict;
  return (
    <>
      <KpiTile
        hero
        tone={VERDICT_TONE[v]}
        label={<>Environment{view.asOf ? ` · ${fmtDateWithDay(view.asOf)}` : ''}</>}
        value={<span className={VERDICT_TEXT[v]}>{v}</span>}
        caption={
          <span className="flex min-w-0 items-center gap-2">
            <span className="font-medium text-fg-2">{VERDICT_ACTION[v]}</span>
            <span className="flex items-center gap-[3px]" aria-label="Pillars">
              {view.pillars.map((p) => (
                <Tooltip key={p.key} content={`${p.name}: ${p.status ?? 'no data'}${p.sentence ? ` — ${p.sentence}` : ''}`}>
                  <span
                    className={cn('h-[7px] w-[7px] rounded-[2px]', p.status ? PILLAR_DOT[p.status] : 'bg-line-strong')}
                    aria-label={`${p.name} ${p.status ?? 'no data'}`}
                  />
                </Tooltip>
              ))}
            </span>
            {view.whatChanged && <span className="min-w-0 truncate">{view.whatChanged}</span>}
          </span>
        }
        onClick={() => setOpen(true)}
        className="!min-w-[260px] !flex-[1.25]"
      />
      {view.evidenceNote && <span className="sr-only">{view.evidenceNote}</span>}
      <EnvironmentDrawer open={open} onClose={() => setOpen(false)} view={view} />
    </>
  );
}

/** Four breadth tiles; the other readings ride in their captions so nothing is dropped. */
function BreadthTiles() {
  const q = useApiQuery('market/health', { query: { days: 60, limit: 60 } });
  const rows = useMemo(() => q.data?.rows ?? [], [q.data]);
  const snap = useMemo(() => breadthSnapshot(rows), [rows]);
  const r = (k: string) => snap.readings.find((x) => x.key === k);
  const loading = q.isLoading;
  if (q.error) {
    return <KpiTile label="Breadth" value={<span className="text-sm text-fg-3">could not load</span>} caption="market/health failed" />;
  }
  if (!loading && !snap.date) {
    return <KpiTile label="Breadth" value={null} caption="No breadth rows for this date." />;
  }
  const a50 = r('pct_above_50ema');
  const a200 = r('pct_above_200ema');
  const a10 = r('pct_above_10ema');
  const nnh = r('net_new_highs');
  const adv = r('advance_pct');
  const dd = r('distribution_days_25');
  const vix = r('india_vix');
  const vix5 = rows[0]?.vix_change_5d_pct ?? null;
  return (
    <>
      <KpiTile
        label="Above 50 EMA"
        metricKey="pct_above_50ema"
        value={a50?.value ?? null}
        format="pct"
        digits={1}
        delta={a50?.delta ?? null}
        deltaFormat="signedPct"
        spark={breadthSeries(rows, 'pct_above_50ema')}
        sparkBaseline={50}
        sparkLabel="% above 50 EMA, 60 sessions"
        caption={a10?.value != null ? `10 EMA ${fmtNum(a10.value, 1)}%` : undefined}
        loading={loading}
      />
      <KpiTile
        label="Above 200 EMA"
        metricKey="pct_above_200ema"
        value={a200?.value ?? null}
        format="pct"
        digits={1}
        delta={a200?.delta ?? null}
        deltaFormat="signedPct"
        spark={breadthSeries(rows, 'pct_above_200ema')}
        sparkBaseline={50}
        sparkLabel="% above 200 EMA, 60 sessions"
        loading={loading}
      />
      <KpiTile
        label="Net new highs"
        metricKey="net_new_highs"
        value={nnh?.value ?? null}
        format="int"
        delta={nnh?.delta ?? null}
        spark={breadthSeries(rows, 'net_new_highs')}
        sparkBaseline={0}
        sparkLabel="Net new highs, 60 sessions"
        caption={
          adv?.value != null || dd?.value != null
            ? `Adv ${adv?.value != null ? `${fmtNum(adv.value, 1)}%` : '—'} · dist days ${dd?.value != null ? fmtInt(dd.value) : '—'}`
            : undefined
        }
        loading={loading}
      />
      <KpiTile
        label="India VIX"
        metricKey="india_vix"
        value={vix?.value ?? null}
        format="num"
        digits={2}
        delta={vix5}
        deltaFormat="signedPct"
        deltaTone="invert"
        caption={vix5 != null ? `5-day change ${fmtSignedPct(vix5, 1)}` : undefined}
        loading={loading}
      />
    </>
  );
}

/** Queue count tiles (count today + new vs yesterday); click switches the queue below. */
function QueueTiles() {
  const summary = useApiQuery('desk/queues');
  const diff = useApiQuery('desk/diff', { query: { limit: 5000 } });
  const newCounts = useMemo(() => groupDiff(diff.data?.rows ?? []), [diff.data]);
  const [queueParam, setQueueParam] = useUrlParam('queue');
  const active = asQueueId(queueParam);
  return (
    <>
      {QUEUES.map((x) => {
        const row = summary.data?.rows.find((r) => r.name === x.id);
        const added = newCounts[x.id]?.added.length ?? 0;
        const dropped = newCounts[x.id]?.dropped.length ?? 0;
        return (
          <KpiTile
            key={x.id}
            label={`${x.short} queue`}
            value={row?.counts?.D ?? null}
            format="int"
            delta={diff.data ? added : undefined}
            deltaTone={added > 0 ? 'auto' : 'neutral'}
            caption={diff.data ? `${added} new · ${dropped} dropped` : undefined}
            loading={summary.isLoading}
            tone="neutral"
            hint={row?.description ?? undefined}
            selected={active === x.id}
            onClick={() => setQueueParam(x.id === 'darvas_squeeze' ? null : x.id)}
          />
        );
      })}
    </>
  );
}

/** Desk header band. Exported under the old panel name so the Desk layout stays put. */
export function EnvironmentPanel({ className }: { className?: string }) {
  return (
    <GlanceBand label="Desk at a glance" className={className}>
      <VerdictTile />
      <BreadthTiles />
      <QueueTiles />
    </GlanceBand>
  );
}
