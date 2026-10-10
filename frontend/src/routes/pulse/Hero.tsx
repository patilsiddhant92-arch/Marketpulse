/** §3 Hero: mood score, label + direction qualifier, sparkline (45–55 band), commentary and What to do. */
import { Card } from '../../ui/Card';
import { DataWarningChip } from '../../ui/DataWarningChip';
import type { PulseResult } from './data';
import { lookbackLabel, moodColour, signed, toneClass } from './model';
import { BandSpark, SectionBody } from './parts';
import type { SummaryRow } from './types';

export function Hero({ q, onOpenHistory }: { q: PulseResult<SummaryRow, unknown>; onOpenHistory?: () => void }) {
  const r = q.rows?.[0];
  return (
    <Card className="grid gap-3 p-3 md:grid-cols-[260px_minmax(0,1fr)]" aria-label="Market mood">
      <SectionBody q={q} rows={3} emptyTitle="Mood is not available for this session">
        {r && (
          <>
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <span className="mp-label">Market mood</span>
                <DataWarningChip warning={r.data_warning} />
              </div>
              <div className={`text-2xl font-semibold leading-tight ${moodColour(r.mood_tone, r.mood_label)}`} data-testid="mood-label">
                {r.mood_label}
              </div>
              {r.qualifier_text && (
                <div className={`text-sm ${r.qualifier === 'cooling' ? 'text-v-weak' : 'text-v-constructive'}`}>{r.qualifier_text}</div>
              )}
              <div className="mt-1 flex items-baseline gap-2">
                <span className="font-mono text-lg tabular-nums text-fg" data-testid="mood-score">
                  {Math.round(r.mood)} / 100
                </span>
                <span className={`text-xs ${toneClass(r.mood_change)}`}>
                  {signed(r.mood_change, 0)} vs {lookbackLabel(r.lookback)} ago
                </span>
              </div>
              <BandSpark
                values={r.mood_series.map((p) => p.mood)}
                band={[45, 55]}
                colour={`rgb(var(--c-${r.mood_tone === 'up' ? 'up' : r.mood_tone === 'down' ? 'down' : 'warn'}))`}
                label={`Mood score, last ${r.mood_series.length} sessions`}
              />
              <p className="text-2xs text-fg-3">
                Last {r.mood_series.length - 1} sessions. 100 = best breadth in our history. Shaded band = 45–55 (Mixed).
              </p>
              {r.mood_parts_known < 6 && (
                <p className="text-2xs text-warn">Only {r.mood_parts_known} of 6 mood readings exist for this session.</p>
              )}
            </div>
            <div className="flex min-w-0 flex-col gap-1.5 text-sm leading-snug text-fg-2" aria-label="Commentary">
              {r.commentary.map((l, i) => (
                <p key={i} data-kind={l.kind}>
                  {l.lead && <b className="text-fg">{l.lead} </b>}
                  {l.text}
                </p>
              ))}
              {r.action && (
                <div className="mt-1 rounded border border-accent/40 bg-accent/10 px-3 py-2" data-testid="what-to-do">
                  <b className="text-fg">What to do: </b>
                  {r.action}
                  {r.history_line && (
                    <div className="mt-1 text-2xs text-fg-3">
                      {r.history_line}{' '}
                      {onOpenHistory && (
                        <button type="button" className="text-info hover:underline" onClick={onOpenHistory}>
                          Open History Lab
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </SectionBody>
    </Card>
  );
}
