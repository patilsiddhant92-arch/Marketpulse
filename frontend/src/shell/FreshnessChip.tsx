import { useEffect, useRef, useState } from 'react';
import { cn } from '../lib/cn';
import { fmtDateWithDay } from '../lib/fmt';
import { useEscapeLayer } from '../lib/layers';
import type { FreshnessInfo } from './useFreshness';

const STYLE: Record<string, { dot: string; text: string; label: string }> = {
  fresh: { dot: 'bg-up', text: 'text-up', label: 'Fresh' },
  stale: { dot: 'bg-warn', text: 'text-warn', label: 'Stale' },
  degraded: { dot: 'bg-down', text: 'text-down', label: 'Degraded' },
  unavailable: { dot: 'bg-down', text: 'text-down', label: 'Unavailable' },
  unknown: { dot: 'bg-fg-3', text: 'text-fg-3', label: 'Unknown' },
};

/** Spec 7.1: green fresh / amber 1 session stale / red older or degraded. */
export function freshnessStyle(f: Pick<FreshnessInfo, 'status' | 'sessionsBehind'>) {
  if (f.status === 'stale' && f.sessionsBehind != null && f.sessionsBehind > 1) {
    return { ...STYLE.degraded, label: `${f.sessionsBehind} sessions stale` };
  }
  if (f.status === 'stale' && f.sessionsBehind === 1) return { ...STYLE.stale, label: '1 session stale' };
  return STYLE[f.status] ?? STYLE.unknown;
}

export function FreshnessChip({ info }: { info: FreshnessInfo }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEscapeLayer(open, () => setOpen(false));
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const s = freshnessStyle(info);
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="flex h-7 items-center gap-1.5 rounded border border-line bg-surface-2 px-2 text-xs transition-colors duration-fast hover:border-line-strong"
        title="Data health"
      >
        <span className={cn('relative flex h-2 w-2 rounded-full', s.dot)} aria-hidden>
          {info.status === 'fresh' && (
            <span className={cn('absolute inset-0 animate-ping rounded-full opacity-40 [animation-iteration-count:3]', s.dot)} />
          )}
        </span>
        <span className="mp-label hidden xl:inline">Data</span>
        <span className="num text-fg">{info.latestSession ? fmtDateWithDay(info.latestSession) : '—'}</span>
        <span className="sr-only">{s.label}</span>
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Data health"
          className="mp-fade-in absolute right-0 top-9 z-40 w-80 rounded-card border border-line-strong bg-surface-2 p-3 text-xs shadow-pop"
        >
          <div className="mb-2 flex items-center gap-2">
            <span className={cn('h-2 w-2 rounded-full', s.dot)} aria-hidden />
            <span className={cn('font-semibold', s.text)}>{s.label}</span>
            <span className="ml-auto text-2xs text-fg-3">source: {info.source}</span>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-fg-3">Latest session</dt>
            <dd className="num text-fg">{info.latestSession ?? '—'}</dd>
            {info.expectedSession && (
              <>
                <dt className="text-fg-3">Expected</dt>
                <dd className="num text-fg">{info.expectedSession}</dd>
              </>
            )}
            {info.sessionsBehind != null && (
              <>
                <dt className="text-fg-3">Behind</dt>
                <dd className="num text-fg">{info.sessionsBehind} sessions</dd>
              </>
            )}
          </dl>
          {info.detail && <p className="mt-2 text-fg-2">{info.detail}</p>}
          {info.checks.length > 0 && (
            <ul className="mt-2 space-y-1 border-t border-line pt-2">
              {info.checks.map((c) => (
                <li key={c.name} className="flex gap-2">
                  <span className={cn('w-8 shrink-0 font-mono uppercase', c.ok ? 'text-up' : 'text-down')}>{c.ok ? 'ok' : 'fail'}</span>
                  <span className="text-fg-2">{c.name}</span>
                  {c.detail && (
                    <span className="ml-auto truncate text-fg-3" title={c.detail}>
                      {c.detail}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {info.source === 'none' && <p className="mt-2 text-fg-3">No health endpoint answered.</p>}
          {info.version && <p className="mt-2 font-mono text-2xs text-fg-3">API {info.version}</p>}
          <button type="button" onClick={info.refetch} className="mt-3 rounded border border-line px-2 py-0.5 text-fg-2 hover:bg-surface-3">
            Re-check
          </button>
        </div>
      )}
    </div>
  );
}
