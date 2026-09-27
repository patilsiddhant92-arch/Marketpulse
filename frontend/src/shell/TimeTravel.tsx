import { History } from 'lucide-react';
import { cn } from '../lib/cn';
import { fmtDate } from '../lib/fmt';
import { isISODate, useAsOf } from './urlState';

/**
 * Time-travel date picker. Writes ?as_of=YYYY-MM-DD (pushes history so Back
 * returns to the previous date). Choosing the latest session clears it.
 */
export function TimeTravel({ latestSession }: { latestSession: string | null }) {
  const [asOf, setAsOf] = useAsOf();
  const value = asOf ?? latestSession ?? '';
  return (
    <div
      className={cn(
        'flex h-7 items-center gap-1 rounded border px-1.5',
        asOf ? 'border-violet/60 bg-violet/10' : 'border-line bg-surface-2',
      )}
    >
      <History className={cn('h-3.5 w-3.5', asOf ? 'text-violet' : 'text-fg-3')} aria-hidden />
      <label className="sr-only" htmlFor="mp-as-of">
        View data as of
      </label>
      <input
        id="mp-as-of"
        type="date"
        value={value}
        max={latestSession ?? undefined}
        onChange={(e) => {
          const v = e.target.value;
          if (!isISODate(v)) return;
          setAsOf(latestSession && v >= latestSession ? null : v);
        }}
        className="num w-[112px] bg-transparent text-xs text-fg outline-none [color-scheme:dark]"
        title={asOf ? `History mode: ${fmtDate(asOf)}` : 'Latest session — pick a date to time-travel'}
      />
      {asOf && (
        <button type="button" onClick={() => setAsOf(null)} className="rounded px-1 text-2xs font-semibold text-violet hover:bg-violet/20">
          Latest
        </button>
      )}
    </div>
  );
}
