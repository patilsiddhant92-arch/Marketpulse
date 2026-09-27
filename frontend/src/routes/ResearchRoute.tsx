/**
 * Research (spec 7.6, lazy-loaded): market analogs, big movers with catalyst
 * attribution, pre-move watch, group studies and setup evidence. Every
 * statistic prints its sample size; screens waiting on the evidence engine
 * show an intentional "being computed" state. Time travel (?as_of) re-keys
 * every query, so each study is computed with data up to that date only.
 */
import { FlaskConical } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../lib/cn';
import { fmtDateWithDay } from '../lib/fmt';
import { useAsOf, useUrlParam } from '../shell/urlState';
import { AnalogsView } from './research/AnalogsView';
import { BigMoversView } from './research/BigMoversView';
import { FixtureModeProvider, useFixtureMode } from './research/data';
import { EvidenceView } from './research/EvidenceView';
import { GroupStudiesView } from './research/GroupStudiesView';
import { PreMoveView } from './research/PreMoveView';

export const RESEARCH_VIEWS = [
  { id: 'analogs', label: 'Market analogs', hint: 'When did the market last look like today — and what happened next' },
  { id: 'movers', label: 'Big movers', hint: 'Big-move events, catalysts, what preceded them' },
  { id: 'premove', label: 'Pre-move watch', hint: 'Stocks showing pre-move traits today (research)' },
  { id: 'groups', label: 'Group studies', hint: 'Big movers by taxonomy level' },
  { id: 'evidence', label: 'Setup evidence', hint: 'Queue outcomes per environment state' },
] as const;
export type ResearchView = (typeof RESEARCH_VIEWS)[number]['id'];

const VIEWS: Record<ResearchView, () => ReactNode> = {
  analogs: () => <AnalogsView />,
  movers: () => <BigMoversView />,
  premove: () => <PreMoveView />,
  groups: () => <GroupStudiesView />,
  evidence: () => <EvidenceView />,
};

function FixtureToggle() {
  const fx = useFixtureMode();
  if (!fx.available) return null;
  return (
    <button
      type="button"
      onClick={() => fx.set(!fx.on)}
      aria-pressed={fx.on}
      title="Dev only: serve Research from built-in fixture data instead of the API"
      className={cn(
        'inline-flex items-center gap-1 rounded border px-2 py-0.5 text-2xs',
        fx.on ? 'border-violet/50 bg-violet/10 text-violet' : 'border-line text-fg-3 hover:bg-surface-3',
      )}
    >
      <FlaskConical className="h-3 w-3" aria-hidden /> Fixtures {fx.on ? 'on' : 'off'} (dev)
    </button>
  );
}

function ResearchBody() {
  const [raw, setView] = useUrlParam('rview');
  const [asOf] = useAsOf();
  const fx = useFixtureMode();
  const view: ResearchView = RESEARCH_VIEWS.some((v) => v.id === raw) ? (raw as ResearchView) : 'analogs';
  const active = RESEARCH_VIEWS.find((v) => v.id === view)!;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-3 py-1.5">
        <nav aria-label="Research studies" className="flex flex-wrap gap-0.5">
          {RESEARCH_VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => setView(v.id === 'analogs' ? null : v.id)}
              aria-current={v.id === view ? 'page' : undefined}
              title={v.hint}
              className={cn(
                'rounded px-2.5 py-1 text-xs',
                v.id === view ? 'bg-surface-3 font-medium text-fg' : 'text-fg-3 hover:bg-surface-2 hover:text-fg-2',
              )}
            >
              {v.label}
            </button>
          ))}
        </nav>
        <span className="hidden text-2xs text-fg-3 lg:inline">{active.hint}</span>
        <div className="ml-auto flex items-center gap-2 text-2xs text-fg-3">
          {asOf ? (
            <span className="rounded border border-violet/40 bg-violet/10 px-1.5 py-0.5 text-violet" title="Studies use data up to this date only (no look-ahead)">
              Studies as of {fmtDateWithDay(asOf)}
            </span>
          ) : (
            <span>Latest session · point-in-time, no look-ahead</span>
          )}
          {fx.on && <span className="rounded border border-violet/40 px-1.5 py-0.5 text-violet">Fixture data — not real</span>}
          <FixtureToggle />
        </div>
      </div>
      <div className="min-h-0 flex-1" key={view}>
        {VIEWS[view]()}
      </div>
    </div>
  );
}

/** Research tab (lazy). Default export, no props. */
export default function ResearchRoute({ fixtures }: { fixtures?: boolean } = {}) {
  return (
    <FixtureModeProvider initial={fixtures}>
      <ResearchBody />
    </FixtureModeProvider>
  );
}
