/** Context strip beside the score: Pulse mood with direction, the "working now" gauge and the verdict (07 §8). */
import { Chip } from '../../ui/Chip';
import { Spark } from '../../ui/Spark';
import type { BoardContext } from './sectorApi';

export function SectorContext({ ctx, loading }: { ctx: BoardContext | undefined; loading?: boolean }) {
  if (!ctx || !ctx.mood) {
    return (
      <section aria-label="Sector Intel context" className="rounded border border-line bg-surface px-3 py-2 text-xs text-fg-3">
        {loading ? 'Loading market mood…' : 'Market mood is not available for this level.'}
      </section>
    );
  }
  const m = ctx.mood;
  const r = ctx.reliability;
  const E = ctx.evidence;
  const ev = ctx.evidence_now;
  const working = r?.working;
  const tone =
    working == null ? 'neutral' : !working || m.dir === 'cooling fast' ? 'negative' : m.dir === 'improving fast' ? 'positive' : 'warn';
  const spark = (m.spark ?? []).filter((x): x is number => x != null);
  return (
    <section
      aria-label="Sector Intel context"
      className="grid gap-3 rounded border border-line bg-surface px-3 py-2 text-xs md:grid-cols-[auto_1fr_1.3fr]"
    >
      <div>
        <div className="text-2xs uppercase tracking-wide text-fg-3">Market mood (Pulse)</div>
        <div className="flex items-baseline gap-2">
          <span className="num text-2xl font-semibold text-fg">{m.score ?? '—'}</span>
          <span className="text-fg-2">
            {m.label ?? '—'}
            {m.dir ? `, ${m.dir}` : ''}
          </span>
        </div>
        {spark.length > 2 && <Spark values={spark} baseline={50} width={170} height={26} label="Market mood, last 120 sessions" />}
        <div className="text-2xs text-fg-3">
          10 EMA breadth {m.a10chg == null ? 'change unknown (data gap)' : `${m.a10chg > 0 ? '+' : ''}${m.a10chg} pts in 10 sessions`}
        </div>
      </div>
      <div>
        <div className="text-2xs uppercase tracking-wide text-fg-3">Is group ranking working now?</div>
        <div className="my-1">
          <Chip tone={tone}>{working == null ? 'Unknown' : working ? 'Working' : 'Not working'}</Chip>
        </div>
        {r && r.top != null && r.bot != null ? (
          <>
            <div className="text-fg-2">
              In the last 3 months, top-fifth groups beat the median group <b className="text-fg">{r.top}%</b> of the time. Bottom-fifth
              groups did so <b className="text-fg">{r.bot}%</b> of the time.
            </div>
            <div className="text-2xs text-fg-3">
              Rank correlation {r.ic} · {r.days} signal days, {r.from} to {r.to} (the latest whose next 21 sessions are known)
            </div>
          </>
        ) : (
          <div className="text-fg-3">Not enough history with known next-21-session returns.</div>
        )}
      </div>
      <div className="text-sm leading-snug">
        <p className="text-fg">{ctx.verdict}</p>
        {ctx.what_to_do && (
          <p className="mt-1 rounded border-l-2 border-accent bg-surface-2 px-2 py-1 text-xs text-fg-2">
            <b className="text-fg">What to do:</b> {ctx.what_to_do}
          </p>
        )}
        {E && ev && m.dir && (
          <p className="mt-1 text-2xs text-fg-3">
            History ({E.period}, Broad Industry): when breadth was {m.dir}, top-fifth groups beat the median {ev.top}% of the time and
            bottom-fifth groups {ev.bot}%. After a working quarter the next month&apos;s correlation averaged {E.lag.working}. After a poor
            one it averaged {E.lag.not}.
          </p>
        )}
      </div>
    </section>
  );
}
