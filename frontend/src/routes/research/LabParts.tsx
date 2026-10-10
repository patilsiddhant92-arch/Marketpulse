/**
 * Shared pieces for the Research lab views: the standing caveat, the plain-English
 * summary block (04-writing-style: short sentences, "What to do" in bold), a
 * small static table, and the quadrant chip.
 */
import { FlaskConical } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../../lib/cn';
import { Chip } from '../../ui/Chip';
import { CAVEAT_FALLBACK, QUADRANT_LABEL, QUADRANT_TONE, isQuadrant } from './lab';

/** "Retrospective research, not advice; needs the 5-year archive" — shown on every lab view. */
export function Caveat({ text, className }: { text?: string | null; className?: string }) {
  return (
    <div
      role="note"
      data-caveat
      className={cn('flex items-start gap-2 rounded border border-violet/40 bg-violet/5 px-3 py-1.5 text-2xs text-fg-2', className)}
    >
      <FlaskConical className="mt-0.5 h-3.5 w-3.5 shrink-0 text-violet" aria-hidden />
      <span>{text || CAVEAT_FALLBACK}</span>
    </div>
  );
}

/** Server-written commentary; a "What to do:" sentence is set in bold. */
export function Summary({ lines, className }: { lines?: readonly string[] | null; className?: string }) {
  if (!lines?.length) return null;
  return (
    <div className={cn('space-y-0.5 text-xs text-fg-2', className)} data-summary>
      {lines.map((l, i) =>
        l.startsWith('What to do:') ? (
          <p key={i}>
            <strong className="text-fg">What to do:</strong>
            {l.slice('What to do:'.length)}
          </p>
        ) : (
          <p key={i}>{l}</p>
        ),
      )}
    </div>
  );
}

export function QuadrantChip({ q, label }: { q: unknown; label?: string | null }) {
  if (!isQuadrant(q)) return <span className="text-fg-3">—</span>;
  return <Chip tone={QUADRANT_TONE[q].chip}>{label ?? QUADRANT_LABEL[q]}</Chip>;
}

// The small static table moved to the shared UI kit (ui/StaticTable); the names stay for the lab views.
export { StaticTable as SimpleTable, type StaticColumn as SimpleColumn } from '../../ui/StaticTable';

export function Muted({ children }: { children: ReactNode }) {
  return <span className="text-fg-3">{children}</span>;
}
