/**
 * "Why is X not in the list?" (spec 7.3 rule debugger): per-floor and per-rule
 * pass/fail for one symbol on the as-of date, with the actual value vs the
 * threshold. Darvas / VCP presets explain the Desk pool gates and geometry.
 */
import { Check, Search, X } from 'lucide-react';
import { useState } from 'react';
import { useApiQuery } from '../api/query';
import type { DebugRow } from '../api/types';
import { cn } from '../lib/cn';
import { fmtDate, fmtNum, isNum } from '../lib/fmt';
import { isSymbol } from '../shell/urlState';
import { EmptyState } from '../ui/EmptyState';
import { ErrorState } from '../ui/ErrorState';
import { SkeletonRows } from '../ui/Skeleton';
import { OP_SYMBOL, type NumOp } from './model';

export interface RuleDebuggerProps {
  symbol: string;
  onSymbol: (s: string) => void;
  /** Same preset / rules / floors as the run (minus lookback). */
  query: Record<string, unknown>;
  /** Symbols in the current result (to say "it IS in the list"). */
  inList: (sym: string) => boolean;
  fieldLabel: (field: string) => string;
  onClose: () => void;
}

function fmtActual(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (isNum(v)) return Math.abs(v) >= 1000 ? fmtNum(v, 0) : fmtNum(v, 2);
  return String(v);
}

function threshold(r: DebugRow, fieldLabel: (f: string) => string): string {
  if (r.kind === 'rule') {
    if (r.op === 'is_true') return 'must be true';
    if (r.op === 'is_false') return 'must be false';
    const sym = OP_SYMBOL[r.op as NumOp] ?? r.op ?? '';
    if (r.ref) return `${sym} ${fieldLabel(r.ref)} (${fmtActual(r.ref_actual)})`;
    return `${sym} ${fmtActual(r.value)}`;
  }
  if (r.ref_actual != null) return `vs ${fmtActual(r.ref_actual)}`;
  if (r.value != null) return `limit ${fmtActual(r.value)}`;
  return '';
}

export function RuleDebugger({ symbol, onSymbol, query, inList, fieldLabel, onClose }: RuleDebuggerProps) {
  const [draft, setDraft] = useState(symbol);
  const [seen, setSeen] = useState(symbol);
  if (seen !== symbol) {
    setSeen(symbol);
    setDraft(symbol);
  }
  const valid = isSymbol(symbol);
  const { lookback_days: _lb, limit: _l, ...q } = query as Record<string, unknown> & { lookback_days?: unknown; limit?: unknown };
  const dbg = useApiQuery('screener/debug', { query: { symbol, ...(q as object) } as never }, { enabled: valid });
  const rows = dbg.data?.rows ?? [];
  const ctx = (dbg.data?.meta.context ?? {}) as { passes_all?: boolean };
  const failed = rows.filter((r) => !r.passed && r.kind !== 'result');
  const listed = valid && inList(symbol);

  return (
    <div className="max-h-[210px] shrink-0 overflow-auto border-b border-line bg-surface-2/60 px-3 py-2">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-2xs font-semibold uppercase tracking-wide text-fg-3">Why is it (not) in the list?</span>
        <form
          className="flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            const s = draft.trim().toUpperCase();
            if (isSymbol(s)) onSymbol(s);
          }}
        >
          <input
            aria-label="Symbol to check"
            className="h-6 w-32 rounded border border-line bg-surface px-1.5 font-mono text-xs uppercase text-fg focus:border-accent focus:outline-none"
            value={draft}
            placeholder="SYMBOL"
            onChange={(e) => setDraft(e.target.value)}
          />
          <button type="submit" className="flex h-6 items-center gap-1 rounded bg-accent/15 px-2 text-xs text-accent hover:bg-accent/25">
            <Search className="h-3 w-3" /> Check
          </button>
        </form>
        {valid && dbg.data && (
          <span className={cn('text-xs', ctx.passes_all ? 'text-up' : 'text-down')}>
            {symbol}{' '}
            {ctx.passes_all
              ? listed
                ? 'passes every check and is in the list.'
                : 'passes every check on this date.'
              : `fails ${failed.length} check${failed.length === 1 ? '' : 's'}${
                  failed.length
                    ? `: ${failed
                        .map((f) => f.label)
                        .slice(0, 3)
                        .join(' · ')}`
                    : ''
                }.`}
            {dbg.data.as_of && <span className="ml-1 text-fg-3">({fmtDate(dbg.data.as_of)})</span>}
          </span>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close rule debugger"
          className="ml-auto rounded p-0.5 text-fg-3 hover:bg-surface-3 hover:text-fg"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {!valid ? (
        <div className="text-xs text-fg-3">
          Type a symbol, or select a row / open a stock in the sidecar to check it against the current preset, rules and floors.
        </div>
      ) : dbg.isLoading ? (
        <SkeletonRows rows={4} label="Checking rules" />
      ) : dbg.error ? (
        <ErrorState error={dbg.error} onRetry={() => void dbg.refetch()} compact />
      ) : dbg.data?.meta.status === 'unavailable' ? (
        <EmptyState compact title="Cannot check" detail={dbg.data.meta.reason ?? undefined} />
      ) : (
        <table className="w-full text-table">
          <thead className="text-2xs uppercase text-fg-3">
            <tr className="text-left">
              <th className="w-6 font-normal" />
              <th className="font-normal">Check</th>
              <th className="w-24 text-right font-normal">Actual</th>
              <th className="w-40 pl-3 font-normal">Needs</th>
              <th className="font-normal">Note</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={cn('border-t border-line/60', r.kind === 'result' && 'font-medium')}>
                <td className="py-0.5">
                  {r.passed ? (
                    <Check className="h-3.5 w-3.5 text-up" aria-label="pass" />
                  ) : (
                    <X className="h-3.5 w-3.5 text-down" aria-label="fail" />
                  )}
                </td>
                <td className="py-0.5 text-fg">
                  {r.label.replace(/>=/g, '≥').replace(/<=/g, '≤')}
                  {r.kind === 'floor' && <span className="ml-1 text-2xs text-fg-3">floor</span>}
                </td>
                <td className={cn('num py-0.5 text-right', r.missing_input ? 'text-warn' : 'text-fg-2')}>
                  {r.missing_input ? 'missing' : fmtActual(r.actual)}
                </td>
                <td className="num py-0.5 pl-3 text-fg-3">{threshold(r, fieldLabel)}</td>
                <td className="max-w-[260px] truncate py-0.5 text-fg-3" title={r.detail ?? undefined}>
                  {r.missing_input
                    ? r.passed
                      ? 'no data — this gate lets unknowns pass'
                      : 'no data → fails (fail-closed)'
                    : (r.detail ?? '')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
