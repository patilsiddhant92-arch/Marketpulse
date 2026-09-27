/**
 * Market Environment (spec 6.1): compact strip under the top bar + detail
 * drawer. Reads GET /api/v2/market/regime and degrades gracefully when the
 * endpoint 404s (v2 not deployed) or meta.status === "unavailable".
 */
import { ArrowDown, ArrowRight, ArrowUp, ChevronRight } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { isApiError, isUnavailable } from '../api/client';
import { useApiQuery } from '../api/query';
import type { Direction, PillarStatus, Verdict } from '../api/types';
import { cn } from '../lib/cn';
import { fmtDate } from '../lib/fmt';
import { Chip, type ChipTone } from '../ui/Chip';
import { Drawer } from '../ui/Drawer';
import { Metric } from '../ui/Metric';
import { Skeleton } from '../ui/Skeleton';
import { Tooltip } from '../ui/Tooltip';
import { toEnvironmentView, type EnvironmentView, type PillarView } from './regimeView';
import { useShell } from './ShellContext';

export const VERDICT_TEXT: Record<Verdict, string> = {
  Favourable: 'text-v-favourable',
  Constructive: 'text-v-constructive',
  Mixed: 'text-v-mixed',
  Weak: 'text-v-weak',
  Danger: 'text-v-danger',
};
const VERDICT_BG: Record<Verdict, string> = {
  Favourable: 'bg-v-favourable',
  Constructive: 'bg-v-constructive',
  Mixed: 'bg-v-mixed',
  Weak: 'bg-v-weak',
  Danger: 'bg-v-danger',
};

export const VERDICT_ACTION: Record<Verdict, string> = {
  Favourable: 'press',
  Constructive: 'normal size',
  Mixed: 'selective, half size',
  Weak: 'mostly cash',
  Danger: 'protect capital',
};

const PILLAR_DOT: Record<PillarStatus, string> = { Healthy: 'bg-up', Neutral: 'bg-warn', Weak: 'bg-down' };
const PILLAR_TONE: Record<PillarStatus, ChipTone> = { Healthy: 'positive', Neutral: 'warn', Weak: 'negative' };

function DirIcon({ dir, label }: { dir: Direction | null; label: string }) {
  const cls = 'h-3 w-3';
  const body =
    dir === 'up' ? (
      <ArrowUp className={cn(cls, 'text-up')} aria-hidden />
    ) : dir === 'down' ? (
      <ArrowDown className={cn(cls, 'text-down')} aria-hidden />
    ) : dir === 'flat' ? (
      <ArrowRight className={cn(cls, 'text-fg-3')} aria-hidden />
    ) : (
      <span className="text-fg-3">{'—'}</span>
    );
  return (
    <span className="inline-flex items-center gap-0.5 text-2xs text-fg-3" title={`${label}: ${dir ?? 'no data'}`}>
      {label}
      {body}
    </span>
  );
}

/** Regime query + view model; shared by the strip and (later) the Desk panel. */
export function useEnvironment() {
  const q = useApiQuery('market/regime');
  const view = useMemo(() => (q.data ? toEnvironmentView(q.data.rows) : null), [q.data]);
  return { q, view, unavailable: isUnavailable(q.data) || (!!q.data && !view) };
}

/** The one-line strip. */
export function EnvironmentStrip() {
  const { q, view, unavailable } = useEnvironment();
  const [open, setOpen] = useState(false);

  let content: ReactNode;
  if (q.isLoading) {
    content = <Skeleton width={320} height={10} />;
  } else if (q.error) {
    const notShipped = isApiError(q.error) && (q.error.kind === 'not_found' || q.error.kind === 'parse');
    content = (
      <span className="text-fg-3">Market environment {notShipped ? 'not available yet (API v2 pending)' : 'could not be loaded'}</span>
    );
  } else if (unavailable || !view) {
    const reason = q.data?.meta?.reason;
    content = <span className="text-fg-3">Market environment unavailable{reason ? ` — ${reason}` : ''}</span>;
  } else {
    content = (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="group flex min-w-0 items-center gap-3 text-left"
        aria-label="Open market environment details"
      >
        <span className="text-2xs uppercase tracking-wide text-fg-3">Environment</span>
        <span className={cn('text-sm font-semibold', view.verdict ? VERDICT_TEXT[view.verdict] : 'text-fg-3')}>{view.verdict ?? '—'}</span>
        {view.verdict && <span className="hidden text-xs text-fg-3 lg:inline">({VERDICT_ACTION[view.verdict]})</span>}
        {view.whatChanged && <span className="min-w-0 truncate text-xs text-fg-2">{view.whatChanged}</span>}
        <span className="flex items-center gap-1" aria-label="Pillars">
          {view.pillars.map((p) => (
            <Tooltip key={p.key} content={`${p.name}: ${p.status ?? 'no data'}${p.sentence ? ` — ${p.sentence}` : ''}`}>
              <span
                className={cn('h-2 w-2 rounded-full', p.status ? PILLAR_DOT[p.status] : 'bg-line-strong')}
                aria-label={`${p.name} ${p.status ?? 'no data'}`}
              />
            </Tooltip>
          ))}
        </span>
        <ChevronRight className="h-3.5 w-3.5 text-fg-3 group-hover:text-fg" aria-hidden />
      </button>
    );
  }

  return (
    <div className="flex h-envstrip shrink-0 items-center gap-3 border-b border-line bg-surface px-3 text-xs">
      {content}
      {view && <EnvironmentDrawer open={open} onClose={() => setOpen(false)} view={view} />}
    </div>
  );
}

function PillarCard({ p }: { p: PillarView }) {
  return (
    <section className="rounded border border-line bg-surface-2 p-3" aria-label={`${p.name} pillar`}>
      <header className="mb-1 flex items-center gap-2">
        <span className="text-sm font-semibold text-fg">{p.name}</span>
        {p.status ? <Chip tone={PILLAR_TONE[p.status]}>{p.status}</Chip> : <Chip>no data</Chip>}
        <span className="ml-auto flex items-center gap-2">
          <DirIcon dir={p.dir1d} label="1D" />
          <DirIcon dir={p.dir1w} label="1W" />
          <DirIcon dir={p.dir1m} label="1M" />
        </span>
      </header>
      <p className="text-xs text-fg-3">{p.question}</p>
      {p.sentence && <p className="mt-1 text-xs text-fg-2">{p.sentence}</p>}
      {p.metrics.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
          {p.metrics.map((r) => (
            <Metric key={r.metric} metricKey={r.metric} value={r.value} size="sm" />
          ))}
        </div>
      )}
      {p.notes.length > 0 && (
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 text-2xs">
          {p.notes.map((n) => (
            <div key={n.key} className="contents">
              <dt className="font-mono text-fg-3">{n.key}</dt>
              <dd className="text-fg-2">{n.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

/** 6-month verdict strip (spec 6.1.5), oldest -> newest. */
function VerdictStrip({ history }: { history: EnvironmentView['history'] }) {
  if (history.length < 2) return null;
  return (
    <div>
      <div className="mb-1 flex justify-between text-2xs text-fg-3">
        <span className="num">{fmtDate(history[0].date)}</span>
        <span>Verdict history ({history.length} sessions)</span>
        <span className="num">{fmtDate(history[history.length - 1].date)}</span>
      </div>
      <div className="flex h-3 overflow-hidden rounded-sm" role="img" aria-label="Verdict history">
        {history.map((h) => (
          <Tooltip key={h.date} content={`${fmtDate(h.date)}: ${h.verdict ?? 'no verdict'}`} className="flex-1" delay={0}>
            <span className={cn('block h-full w-full', h.verdict ? VERDICT_BG[h.verdict] : 'bg-surface-3')} />
          </Tooltip>
        ))}
      </div>
    </div>
  );
}

export function EnvironmentDrawer({ open, onClose, view }: { open: boolean; onClose: () => void; view: EnvironmentView }) {
  const shell = useShell();
  return (
    <Drawer open={open} onClose={onClose} title="Market environment" width={560}>
      <div className="space-y-4 p-4">
        <div>
          <div className="flex items-baseline gap-3">
            <span className={cn('text-2xl font-semibold', view.verdict ? VERDICT_TEXT[view.verdict] : 'text-fg-3')}>
              {view.verdict ?? '—'}
            </span>
            {view.verdict && <span className="text-sm text-fg-2">{VERDICT_ACTION[view.verdict]}</span>}
            <span className="num ml-auto text-2xs text-fg-3">as of {fmtDate(view.asOf)}</span>
          </div>
          {view.whatChanged && <p className="mt-1 text-sm text-fg-2">{view.whatChanged}</p>}
          <p className="num mt-1 text-2xs text-fg-3">
            {view.daysInState != null && `${view.daysInState} sessions in state`}
            {view.previousVerdict && ` · previously ${view.previousVerdict}`}
            {view.changedOn && ` · changed ${fmtDate(view.changedOn)}`}
            {view.ruleId && ` · rule ${view.ruleId}`}
          </p>
        </div>

        <VerdictStrip history={view.history} />

        <div className="space-y-2">
          {view.pillars.map((p) => (
            <PillarCard key={p.key} p={p} />
          ))}
        </div>

        <p className="rounded border border-info/30 bg-info/5 px-3 py-2 text-xs text-fg-2">
          <span className="font-semibold text-info">Timing · </span>% above 10 EMA is a short-term stretch gauge: above 80 is stretched
          (breakouts tend to pull back, wait 2–3 days), below 20 is washed out (bounces start). It never sets the verdict alone.
        </p>

        <section aria-label="Connected readings">
          <h3 className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-fg-3">Connected readings</h3>
          {view.readings.length === 0 ? (
            <p className="text-xs text-fg-3">No divergence rules fired this session.</p>
          ) : (
            <ul className="space-y-2">
              {view.readings.map((r) => (
                <li key={r.id} className="rounded border border-line bg-surface-2 p-2.5">
                  <div
                    className={cn(
                      'text-xs font-semibold',
                      r.tone === 'positive' ? 'text-up' : r.tone === 'negative' ? 'text-down' : 'text-fg',
                    )}
                  >
                    {r.title}
                  </div>
                  {r.text && <p className="mt-0.5 text-xs text-fg-2">{r.text}</p>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <button
          type="button"
          onClick={() => {
            onClose();
            shell.setBreadthOpen(true);
          }}
          className="text-xs text-info hover:underline"
        >
          Open 180-session breadth history (legacy) →
        </button>
      </div>
    </Drawer>
  );
}
