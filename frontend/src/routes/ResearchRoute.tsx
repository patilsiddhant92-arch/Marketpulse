/**
 * Research (HarkPro/10-tab-research.md, merged with History Lab; lazy-loaded):
 * days like today (regime quadrant + analogs), before the big moves, big-mover
 * case studies (with the D/W/M trait strip), the setup scorecard, the Desk
 * signal log (log and grade), the index study and setup evidence.
 * Every statistic prints its sample size and every view carries the
 * "retrospective research, not advice" caveat. Time travel (?as_of) re-keys
 * every query, so each study uses data up to that date only.
 * Pre-move watch is cut; group studies moved to Sector Intel (their component
 * files stay in research/ until the cross-tab pass).
 */
import { FlaskConical } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../lib/cn';
import { fmtDateWithDay } from '../lib/fmt';
import { useAsOf, useUrlParam } from '../shell/urlState';
import { BeforeMovesView } from './research/BeforeMovesView';
import { CaseStudyView } from './research/CaseStudyView';
import { FixtureModeProvider, useFixtureMode } from './research/data';
import { DaysLikeTodayView } from './research/DaysLikeTodayView';
import { EvidenceView } from './research/EvidenceView';
import { IndexStudyView } from './research/IndexStudyView';
import { ScorecardView } from './research/ScorecardView';
import { SignalLogView } from './research/SignalLogView';

export const RESEARCH_VIEWS = [
  { id: 'today', label: 'Days like today', hint: 'What kind of market is this, when did it look like this before, and what happened next' },
  { id: 'before', label: 'Before the big moves', hint: 'What runners looked like at the early lift, and today’s lifts scored' },
  { id: 'case', label: 'Case study', hint: 'Where our screener gave entries in a big mover' },
  { id: 'scorecard', label: 'Setup scorecard', hint: 'Each preset’s catch rate, how early it fired, and its false alarms' },
  { id: 'signals', label: 'Signal log', hint: 'Every Desk setup logged the day it appeared and graded 5 / 10 / 20 sessions later' },
  { id: 'index', label: 'Index study', hint: 'Falls > 8%, recoveries and size leadership on the equal-weight market' },
  { id: 'evidence', label: 'Setup evidence', hint: 'Queue outcomes per environment state' },
] as const;
export type ResearchView = (typeof RESEARCH_VIEWS)[number]['id'];

const VIEWS: Record<ResearchView, () => ReactNode> = {
  today: () => <DaysLikeTodayView />,
  before: () => <BeforeMovesView />,
  case: () => <CaseStudyView />,
  scorecard: () => <ScorecardView />,
  signals: () => <SignalLogView />,
  index: () => <IndexStudyView />,
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
  const view: ResearchView = RESEARCH_VIEWS.some((v) => v.id === raw) ? (raw as ResearchView) : 'today';
  const active = RESEARCH_VIEWS.find((v) => v.id === view)!;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface px-3 py-1.5">
        <nav aria-label="Research studies" className="flex flex-wrap gap-0.5">
          {RESEARCH_VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => setView(v.id === 'today' ? null : v.id)}
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
        <span className="hidden min-w-0 flex-1 truncate text-2xs text-fg-3 xl:inline">{active.hint}</span>
        <div className="ml-auto flex shrink-0 items-center gap-2 text-2xs text-fg-3">
          {asOf ? (
            <span
              className="rounded border border-violet/40 bg-violet/10 px-1.5 py-0.5 text-violet"
              title="Studies use data up to this date only (no look-ahead)"
            >
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
